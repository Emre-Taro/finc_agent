"""銘柄の3軸スコアリング（マクロ / 業界 / 個別銘柄、各100点満点）。

蓄積したニュース評価（-2〜+2）を集計した定量ベースラインと、最新の金融指標を
Claude に渡し、その企業固有の感応度（例: 輸出企業にとっての円安）を踏まえて採点させる。
"""

import asyncio
import json
from typing import Any

from . import db
from .claude import structured_call
from .indicators import latest_indicators
from .taxonomy import SECTORS

# 総合スコアの重み
WEIGHTS = {"macro": 0.3, "industry": 0.3, "ticker": 0.4}
MACRO_DAYS = 7
SECTOR_DAYS = 14
TICKER_DAYS = 30

_AXIS = {
    "type": "object",
    "properties": {"score": {"type": "integer"}, "reason": {"type": "string"}},
    "required": ["score", "reason"],
    "additionalProperties": False,
}
SCORE_SCHEMA = {
    "type": "object",
    "properties": {"macro": _AXIS, "industry": _AXIS, "ticker": _AXIS, "summary": {"type": "string"}},
    "required": ["macro", "industry", "ticker", "summary"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """あなたは株式アナリストです。与えられた材料だけを根拠に、指定銘柄の投資環境を3軸で採点してください。

各軸 0〜100 の整数（50 = 中立、100 = 極めて良好、0 = 極めて悪い）:
- macro: マクロ環境（金利・インフレ・為替・景気・リスク選好）がこの企業にとって追い風か逆風か。
  市場全体の好悪ではなく、この企業の事業構造に照らした感応度で判断すること（例: 円安は輸出企業に追い風、輸入企業に逆風）
- industry: 所属セクターを取り巻くニュースフロー・需給・規制の好悪
- ticker: この企業固有のニュース（決算、ガイダンス、M&A、訴訟、格付け等）の好悪。固有ニュースが無ければ 50 付近

「定量ベースライン」はニュース評価(-2〜+2)の単純平均を 0〜100 に換算したもの（50 + 25×平均）。出発点として使い、
材料の重要度・鮮度・企業固有の感応度を踏まえて調整してください。材料が乏しい軸は 50 に寄せること。
reason と summary は日本語で、根拠にしたニュースや指標を具体的に挙げてください。"""


def _to_100(scores: list[float]) -> float | None:
    if not scores:
        return None
    return round(50 + 25 * sum(scores) / len(scores), 1)


async def _impacts(target_type: str, code: str, days: int) -> list[dict[str, Any]]:
    return await db.fetch(
        """
        select i.score, i.reason, n.title, n.content_summary, n.published_at, n.source
        from news_impacts i join news n on n.id = i.news_id
        where i.target_type = $1 and i.target_code = $2 and i.score <> 0
          and n.published_at >= now() - make_interval(days => $3)
        order by n.published_at desc limit 60
        """,
        target_type, code, days,
    )


async def gather_evidence(company: dict[str, Any]) -> dict[str, Any]:
    macro, sector, ticker, indicators = await asyncio.gather(
        db.fetch(
            """
            select title, content_summary, macro_score, published_at, source from news
            where analysis_status = 'done' and published_at >= now() - make_interval(days => $1)
            order by published_at desc limit 60
            """,
            MACRO_DAYS,
        ),
        _impacts("sector", company["sector"], SECTOR_DAYS),
        _impacts("ticker", company["ticker"].upper(), TICKER_DAYS),
        latest_indicators(history_days=40),
    )
    return {
        "baseline": {
            "macro": _to_100([float(n["macro_score"]) for n in macro if n["macro_score"] is not None]),
            "industry": _to_100([float(i["score"]) for i in sector]),
            "ticker": _to_100([float(i["score"]) for i in ticker]),
        },
        "counts": {"macro_news": len(macro), "sector_impacts": len(sector), "ticker_impacts": len(ticker)},
        "macro_news": macro,
        "sector_impacts": sector,
        "ticker_impacts": ticker,
        "indicators": [
            {k: i[k] for k in ("code", "name", "unit", "latest", "latest_date", "change")} for i in indicators
        ],
    }


def _news_line(n: dict[str, Any], score: float) -> str:
    day = n["published_at"].date().isoformat() if n.get("published_at") else "日付不明"
    return f"- [{day} {n['source']}] ({score:+}) {n['title']} — {n.get('content_summary') or ''}"


def _build_prompt(company: dict[str, Any], ev: dict[str, Any]) -> str:
    macro = "\n".join(_news_line(n, float(n["macro_score"])) for n in ev["macro_news"]) or "（なし）"
    sector = "\n".join(_news_line(i, float(i["score"])) + f" / 影響: {i['reason']}" for i in ev["sector_impacts"]) or "（なし）"
    ticker = "\n".join(_news_line(i, float(i["score"])) + f" / 影響: {i['reason']}" for i in ev["ticker_impacts"]) or "（なし）"
    return f"""# 対象銘柄
{company['ticker']} {company['name']}（セクター: {SECTORS.get(company['sector'], company['sector'])}）

# 定量ベースライン（材料が無い軸は null）
{json.dumps(ev['baseline'], ensure_ascii=False)}

# 最新の金融指標（change は前回観測値からの変化）
{json.dumps(ev['indicators'], ensure_ascii=False, default=str)}

# 直近{MACRO_DAYS}日のマクロニュース（括弧内はマクロスコア -2〜+2）
{macro}

# 直近{SECTOR_DAYS}日のセクター関連ニュース（括弧内はセクターへの影響）
{sector}

# 直近{TICKER_DAYS}日の個別ニュース（括弧内は銘柄への影響）
{ticker}
"""


def _clamp(v: int) -> int:
    return max(0, min(100, int(v)))


async def score_company(ticker: str) -> dict[str, Any]:
    company = await db.fetchrow("select * from companies where ticker = $1", ticker)
    if company is None:
        raise LookupError(ticker)
    ev = await gather_evidence(company)
    out = await structured_call(SYSTEM_PROMPT, _build_prompt(company, ev), SCORE_SCHEMA, effort="high")

    m, i, t = _clamp(out["macro"]["score"]), _clamp(out["industry"]["score"]), _clamp(out["ticker"]["score"])
    total = round(m * WEIGHTS["macro"] + i * WEIGHTS["industry"] + t * WEIGHTS["ticker"], 1)
    return await db.fetchrow(
        """
        insert into company_scores (ticker, macro_score, industry_score, ticker_score, total_score,
            macro_reason, industry_reason, ticker_reason, summary, evidence)
        values ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
        returning *
        """,
        ticker, m, i, t, total,
        out["macro"]["reason"], out["industry"]["reason"], out["ticker"]["reason"], out["summary"],
        {"baseline": ev["baseline"], "counts": ev["counts"], "weights": WEIGHTS},
    )


async def score_all(run_id: str) -> tuple[str, dict[str, Any]]:
    tickers = [r["ticker"] for r in await db.fetch("select ticker from companies")]
    sem = asyncio.Semaphore(3)
    errors: dict[str, str] = {}

    async def one(ticker: str) -> None:
        async with sem:
            try:
                await score_company(ticker)
            except Exception as e:
                errors[ticker] = repr(e)

    await asyncio.gather(*(one(t) for t in tickers))
    stats = {"scored": len(tickers) - len(errors), "errors": errors}
    return ("partial" if errors else "success"), stats
