"""金融指標の取得（FRED API + Yahoo Finance）。"""

import asyncio
import logging
import math
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

import httpx
import yfinance as yf

from .config import get_settings
from . import db

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Indicator:
    code: str
    name: str
    unit: str
    source: str  # "fred" | "yahoo"
    series: str
    fred_units: str = "lin"  # FRED の変換。pc1 = 前年同月比(%)


INDICATORS: list[Indicator] = [
    Indicator("US10Y", "米10年債利回り", "%", "fred", "DGS10"),
    Indicator("US2Y", "米2年債利回り", "%", "fred", "DGS2"),
    Indicator("JGB10Y", "日本10年債利回り（月次）", "%", "fred", "IRLTLT01JPM156N"),
    Indicator("FED_FUNDS", "FF金利（実効）", "%", "fred", "DFF"),
    Indicator("US_BREAKEVEN10Y", "米10年期待インフレ率", "%", "fred", "T10YIE"),
    Indicator("US_CPI_YOY", "米CPI 前年比", "%", "fred", "CPIAUCSL", "pc1"),
    Indicator("US_CORE_CPI_YOY", "米コアCPI 前年比", "%", "fred", "CPILFESL", "pc1"),
    Indicator("US_UNRATE", "米失業率", "%", "fred", "UNRATE"),
    Indicator("USDJPY", "ドル円", "円", "yahoo", "JPY=X"),
    Indicator("SPX", "S&P500", "pt", "yahoo", "^GSPC"),
    Indicator("N225", "日経平均", "円", "yahoo", "^N225"),
    Indicator("VIX", "VIX", "pt", "yahoo", "^VIX"),
    Indicator("WTI", "WTI原油", "$", "yahoo", "CL=F"),
    Indicator("GOLD", "金先物", "$", "yahoo", "GC=F"),
]
BY_CODE = {i.code: i for i in INDICATORS}

_HISTORY_DAYS = 400


async def _fetch_fred(client: httpx.AsyncClient, ind: Indicator, api_key: str) -> list[tuple[str, float]]:
    resp = await client.get(
        "https://api.stlouisfed.org/fred/series/observations",
        params={
            "series_id": ind.series,
            "api_key": api_key,
            "file_type": "json",
            "units": ind.fred_units,
            # 前年比の計算に1年以上前のデータが必要な系列もあるので長めに取る
            "observation_start": (date.today() - timedelta(days=_HISTORY_DAYS)).isoformat(),
        },
    )
    resp.raise_for_status()
    return [(o["date"], float(o["value"])) for o in resp.json()["observations"] if o["value"] != "."]


def _fetch_yahoo_sync(ind: Indicator) -> list[tuple[str, float]]:
    hist = yf.Ticker(ind.series).history(period="1y", interval="1d", auto_adjust=False)
    return [
        (idx.date().isoformat(), float(close))
        for idx, close in hist["Close"].items()
        if not math.isnan(close)
    ]


async def refresh_indicators() -> dict[str, Any]:
    api_key = get_settings().fred_api_key
    stats: dict[str, Any] = {"updated": {}, "errors": {}}

    async with httpx.AsyncClient(timeout=20) as client:

        async def fetch(ind: Indicator) -> list[tuple[str, float]]:
            if ind.source == "fred":
                if not api_key:
                    raise RuntimeError("FRED_API_KEY が未設定です")
                return await _fetch_fred(client, ind, api_key)
            return await asyncio.to_thread(_fetch_yahoo_sync, ind)

        results = await asyncio.gather(*(fetch(i) for i in INDICATORS), return_exceptions=True)

    for ind, result in zip(INDICATORS, results):
        if isinstance(result, Exception):
            log.warning("indicator %s failed: %r", ind.code, result)
            stats["errors"][ind.code] = repr(result)
            continue
        rows = [(ind.code, date.fromisoformat(d), v, ind.source) for d, v in result]
        if rows:
            # (indicator_code, observed_on) が主キーなので何度更新しても重複しない
            pool = await db.get_pool()
            await pool.executemany(
                """
                insert into indicator_observations (indicator_code, observed_on, value, source)
                values ($1, $2, $3, $4)
                on conflict (indicator_code, observed_on)
                do update set value = excluded.value, source = excluded.source, fetched_at = now()
                """,
                rows,
            )
        stats["updated"][ind.code] = len(rows)
    return stats


async def latest_indicators(history_days: int = 180) -> list[dict[str, Any]]:
    """各指標の最新値・前回値・変化幅と、チャート用の履歴を返す。

    月次指標は発表が1か月以上遅れるので、最新値・前回値は期間外でも直近2件を必ず含める。
    """
    rows = await db.fetch(
        """
        select indicator_code, observed_on, value, observed_on >= $1 as in_window
        from (
            select *, row_number() over (partition by indicator_code order by observed_on desc) as rn
            from indicator_observations
        ) t
        where observed_on >= $1 or rn <= 2
        order by indicator_code, observed_on
        """,
        date.today() - timedelta(days=history_days),
    )
    by_code: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_code.setdefault(r["indicator_code"], []).append(r)

    out = []
    for ind in INDICATORS:
        points = by_code.get(ind.code, [])
        hist = [{"observed_on": p["observed_on"], "value": p["value"]} for p in points if p["in_window"]]
        latest = points[-1] if points else None
        prev = points[-2] if len(points) > 1 else None
        out.append({
            "code": ind.code,
            "name": ind.name,
            "unit": ind.unit,
            "latest": latest["value"] if latest else None,
            "latest_date": latest["observed_on"] if latest else None,
            "change": latest["value"] - prev["value"] if latest and prev else None,
            "history": hist,
        })
    return out
