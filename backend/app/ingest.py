"""ニュース取得 → 重複排除 → 保存 → AI評価 のパイプライン。

重複防止は3段構え:
1. 同一バッチ内: 正規化URLハッシュ / (媒体, 正規化タイトルハッシュ) で除外
2. DB一意制約: url_hash UNIQUE と (source, title_hash) UNIQUE。INSERT ... ON CONFLICT DO NOTHING で
   既存記事は1文で黙ってスキップされる（同時実行でも安全）
3. 保存してから評価する: AI評価は analysis_status = 'pending' の行だけが対象なので、既存記事に課金は発生しない。
   評価に失敗した記事は 'failed' で残り、/api/news/reanalyze でやり直せる
"""

import asyncio
import logging
from typing import Any

from . import db
from .analyzer import analyze
from .config import get_settings
from .dedup import title_hash, url_hash
from .feeds import fetch_all
from .taxonomy import NEWS_INDICATORS, SECTORS

log = logging.getLogger(__name__)


async def ingest_news(run_id: str) -> tuple[str, dict[str, Any]]:
    s = get_settings()
    items, feed_errors = await fetch_all(s.news_lookback_hours, s.max_items_per_feed)

    # 1. バッチ内重複
    seen_urls: set[str] = set()
    seen_titles: set[tuple[str, str]] = set()
    rows: list[tuple] = []
    for it in items:
        uh, th = url_hash(it.url), title_hash(it.title)
        if uh in seen_urls or (it.source, th) in seen_titles:
            continue
        seen_urls.add(uh)
        seen_titles.add((it.source, th))
        rows.append((it.url, uh, it.title, th, it.source, it.feed_name, it.published_at, it.excerpt or None))

    # 2. 一意制約に当たった行（保存済みの記事）はスキップ
    inserted = 0
    if rows:
        cols = list(zip(*rows))
        inserted = len(await db.fetch(
            """
            insert into news (url, url_hash, title, title_hash, source, feed_name, published_at, raw_excerpt, ingest_run_id)
            select u.*, $9::uuid
            from unnest($1::text[], $2::text[], $3::text[], $4::text[], $5::text[], $6::text[],
                        $7::timestamptz[], $8::text[]) as u
            on conflict do nothing
            returning id
            """,
            *map(list, cols), run_id,
        ))

    analysis = await analyze_pending()

    stats = {
        "fetched": len(items),
        "unique_in_batch": len(rows),
        "already_stored": len(rows) - inserted,
        "inserted": inserted,
        **analysis,
        "feed_errors": feed_errors,
    }
    status = "partial" if feed_errors or analysis["analysis_failed"] else "success"
    return status, stats


async def analyze_pending(include_failed: bool = False, limit: int = 300) -> dict[str, int]:
    """未評価（必要なら失敗分も）の記事を並列でAI評価する。"""
    statuses = ["pending", "failed"] if include_failed else ["pending"]
    pending = await db.fetch(
        """
        select id, source, title, raw_excerpt, published_at from news
        where analysis_status = any($1::text[]) order by fetched_at limit $2
        """,
        statuses, limit,
    )
    sem = asyncio.Semaphore(get_settings().analysis_concurrency)
    results = await asyncio.gather(*(_analyze_one(row, sem) for row in pending))
    ok = sum(results)
    return {"analyzed": ok, "analysis_failed": len(results) - ok}


async def _analyze_one(row: dict[str, Any], sem: asyncio.Semaphore) -> bool:
    async with sem:
        try:
            result = await analyze(row)
        except Exception as e:
            log.warning("analysis failed for %s: %r", row["id"], e)
            await db.execute(
                "update news set analysis_status = 'failed', analysis_error = $2 where id = $1",
                row["id"], repr(e)[:2000],
            )
            return False

    impacts: dict[tuple[str, str], tuple[str, int, str]] = {}
    for code, v in result["sector_impacts"].items():
        impacts[("sector", code)] = (SECTORS[code], v["score"], v["reason"])
    for code, v in result["indicator_impacts"].items():
        impacts[("indicator", code)] = (NEWS_INDICATORS[code], v["score"], v["reason"])
    for t in result["ticker_impacts"]:
        code = t["ticker"].strip().upper()
        if code:  # 同じティッカーが重複して返っても後勝ちで1行にまとまる
            impacts[("ticker", code)] = (t["name"], t["score"], t["reason"])

    pool = await db.get_pool()
    async with pool.acquire() as conn, conn.transaction():
        await conn.executemany(
            """
            insert into news_impacts (news_id, target_type, target_code, target_name, score, reason)
            values ($1, $2, $3, $4, $5, $6)
            on conflict (news_id, target_type, target_code)
            do update set target_name = excluded.target_name, score = excluded.score, reason = excluded.reason
            """,
            [(row["id"], tt, code, *v) for (tt, code), v in impacts.items()],
        )
        await conn.execute(
            """
            update news set content_summary = $2, macro_score = $3, industry_score = $4, ticker_score = $5,
                primary_sector = $6, primary_ticker = $7, ai_analysis_reason = $8,
                analysis_status = 'done', analysis_error = null, analyzed_at = now()
            where id = $1
            """,
            row["id"], result["summary_ja"], result["macro_score"], result["industry_score"],
            result["ticker_score"], result["primary_sector"], result["primary_ticker"].strip().upper() or None,
            result["reason_ja"],
        )
    return True


async def reanalyze(run_id: str) -> tuple[str, dict[str, Any]]:
    stats = await analyze_pending(include_failed=True)
    return ("partial" if stats["analysis_failed"] else "success"), stats
