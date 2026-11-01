import logging
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from . import db, runs, tickers
from .config import get_settings
from .indicators import BY_CODE, latest_indicators, refresh_indicators
from .ingest import ingest_news, reanalyze
from .scoring import WEIGHTS, score_all, score_company
from .taxonomy import NEWS_INDICATORS, SECTORS

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 前回のプロセスが実行途中で止まった（--reload での再起動など）ジョブを中断扱いにする
    await db.execute(
        "update ingest_runs set status = 'failed', error = 'サーバー再起動により中断', finished_at = now()"
        " where status = 'running'"
    )
    yield
    await db.close_pool()


app = FastAPI(title="finc_agent API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in get_settings().cors_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
async def health():
    return {"ok": await db.fetchval("select true")}


@app.get("/api/taxonomy")
async def taxonomy():
    return {"sectors": SECTORS, "indicators": NEWS_INDICATORS, "score_weights": WEIGHTS}


# ---- ジョブ実行（オンデマンド） ------------------------------------------

def _launch_guard(kind: str) -> None:
    if runs.is_running(kind):
        raise HTTPException(409, f"{kind} のジョブが実行中です")


@app.post("/api/ingest/news", status_code=202)
async def start_news_ingest():
    _launch_guard("news")
    return {"run_id": await runs.launch("news", ingest_news)}


@app.post("/api/news/reanalyze", status_code=202)
async def start_reanalyze():
    """評価に失敗した記事・未評価の記事をもう一度評価する。"""
    _launch_guard("news")
    return {"run_id": await runs.launch("news", reanalyze)}


@app.get("/api/runs")
async def list_runs(kind: str | None = None, limit: int = Query(20, le=100)):
    return await db.fetch(
        "select * from ingest_runs where ($1::text is null or kind = $1) order by started_at desc limit $2",
        kind, limit,
    )


@app.get("/api/runs/{run_id}")
async def get_run(run_id: UUID):
    row = await db.fetchrow("select * from ingest_runs where id = $1", run_id)
    if row is None:
        raise HTTPException(404)
    return row


# ---- ニュース ------------------------------------------------------------

@app.get("/api/news")
async def list_news(
    limit: int = Query(50, le=200),
    offset: int = 0,
    source: str | None = None,
    sector: str | None = None,
    q: str | None = None,
):
    where = """
        where ($1::text is null or source = $1)
          and ($2::text is null or primary_sector = $2)
          and ($3::text is null or title ilike '%' || $3 || '%')
    """
    items = await db.fetch(
        f"""
        select id, published_at, title, url, source, content_summary, macro_score, industry_score, ticker_score,
               primary_sector, primary_ticker, ai_analysis_reason, analysis_status
        from news {where}
        order by published_at desc nulls last
        limit $4 offset $5
        """,
        source, sector, q, limit, offset,
    )
    total = await db.fetchval(f"select count(*) from news {where}", source, sector, q)
    return {"items": items, "total": total}


@app.get("/api/news/{news_id}")
async def get_news(news_id: UUID):
    row = await db.fetchrow("select * from news where id = $1", news_id)
    if row is None:
        raise HTTPException(404)
    row["news_impacts"] = await db.fetch(
        "select target_type, target_code, target_name, score, reason from news_impacts where news_id = $1",
        news_id,
    )
    return row


@app.get("/api/impacts/summary")
async def impacts_summary(days: int = Query(7, ge=1, le=90)):
    return await db.fetch("select * from impact_summary($1)", days)


# ---- 金融指標 ------------------------------------------------------------

@app.post("/api/indicators/refresh")
async def indicators_refresh():
    # 主キー (indicator_code, observed_on) への upsert なので同時に押されても重複しない
    run_id = await runs.start_run("indicators")
    try:
        stats = await refresh_indicators()
    except Exception as e:
        await runs.finish_run(run_id, "failed", {}, repr(e))
        raise
    await runs.finish_run(run_id, "partial" if stats["errors"] else "success", stats)
    return stats


@app.get("/api/indicators")
async def indicators(history_days: int = Query(180, ge=1, le=400)):
    return await latest_indicators(history_days)


@app.get("/api/indicators/{code}")
async def indicator_detail(code: str, history_days: int = Query(400, ge=1, le=400), news_limit: int = Query(20, le=100)):
    """1指標の詳細（長めの履歴 + その指標に影響すると評価されたニュース）。"""
    if code not in BY_CODE:
        raise HTTPException(404)
    [ind] = await latest_indicators(history_days, code)
    ind["news"] = await db.fetch(
        """
        select n.id, n.published_at, n.title, n.url, n.source, i.score, i.reason
        from news_impacts i
        join news n on n.id = i.news_id
        where i.target_type = 'indicator' and i.target_code = $1 and i.score <> 0
        order by n.published_at desc nulls last
        limit $2
        """,
        code, news_limit,
    )
    return ind


# ---- 銘柄スコア ----------------------------------------------------------

class CompanyIn(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)
    name: str = Field(min_length=1)
    sector: str


@app.get("/api/tickers/search")
async def ticker_search(q: str = Query(min_length=1, max_length=50), limit: int = Query(10, le=30)):
    """銘柄追加フォームの候補。日本語の社名・証券コード・英語名・米国ティッカーで検索できる。"""
    return await tickers.search(q, limit)


@app.get("/api/companies")
async def list_companies():
    companies = await db.fetch("select * from companies order by ticker")
    latest = {
        s["ticker"]: s
        for s in await db.fetch("select distinct on (ticker) * from company_scores order by ticker, scored_at desc")
    }
    return [{**c, "latest_score": latest.get(c["ticker"])} for c in companies]


@app.post("/api/companies", status_code=201)
async def add_company(body: CompanyIn):
    if body.sector not in SECTORS:
        raise HTTPException(422, f"sector は {list(SECTORS)} のいずれか")
    return await db.fetchrow(
        """
        insert into companies (ticker, name, sector) values ($1, $2, $3)
        on conflict (ticker) do update set name = excluded.name, sector = excluded.sector
        returning *
        """,
        body.ticker.strip().upper(), body.name.strip(), body.sector,
    )


@app.delete("/api/companies/{ticker}", status_code=204)
async def delete_company(ticker: str):
    await db.execute("delete from companies where ticker = $1", ticker.upper())


@app.post("/api/companies/score-all", status_code=202)
async def start_score_all():
    _launch_guard("company_scores")
    return {"run_id": await runs.launch("company_scores", score_all)}


@app.post("/api/companies/{ticker}/score")
async def score_one(ticker: str):
    try:
        return await score_company(ticker.upper())
    except LookupError:
        raise HTTPException(404, "未登録の銘柄です")


@app.get("/api/companies/{ticker}/scores")
async def score_history(ticker: str, limit: int = Query(30, le=200)):
    return await db.fetch(
        "select * from company_scores where ticker = $1 order by scored_at desc limit $2",
        ticker.upper(), limit,
    )
