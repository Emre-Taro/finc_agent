"""銘柄検索（銘柄追加フォームの候補表示用）。

- 日本語の社名・証券コード: JPX（日本取引所グループ）の上場銘柄一覧から検索
  （Yahoo Finance の検索は日本語の社名に対応していないため）
- 英語の社名・米国株などのティッカー: Yahoo Finance の検索
どちらもセクターを taxonomy.SECTORS（GICS 11セクター）に対応づけて返す。
"""

import asyncio
import io
import logging
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

import httpx
import pandas as pd
import yfinance as yf

log = logging.getLogger(__name__)

JPX_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
_CACHE_FILE = Path(__file__).resolve().parent.parent / "data" / "jpx_listed.xlsx"
_CACHE_TTL = 7 * 24 * 3600  # 一覧は月1回更新なので週1回取り直せば十分

# JPX 33業種 → GICS 11セクター（厳密な対応ではないので、追加後にフォームで修正できる）
JPX_SECTOR_MAP = {
    "水産・農林業": "consumer_staples", "食料品": "consumer_staples",
    "鉱業": "energy", "石油・石炭製品": "energy",
    "建設業": "industrials", "機械": "industrials", "陸運業": "industrials", "海運業": "industrials",
    "空運業": "industrials", "倉庫・運輸関連業": "industrials", "卸売業": "industrials", "サービス業": "industrials",
    "繊維製品": "consumer_discretionary", "ゴム製品": "consumer_discretionary",
    "輸送用機器": "consumer_discretionary", "その他製品": "consumer_discretionary", "小売業": "consumer_discretionary",
    "パルプ・紙": "materials", "化学": "materials", "ガラス・土石製品": "materials", "鉄鋼": "materials",
    "非鉄金属": "materials", "金属製品": "materials",
    "医薬品": "health_care", "精密機器": "health_care",
    "電気機器": "information_technology",
    "情報・通信業": "communication_services",
    "電気・ガス業": "utilities",
    "銀行業": "financials", "証券、商品先物取引業": "financials", "保険業": "financials", "その他金融業": "financials",
    "不動産業": "real_estate",
}

# Yahoo Finance のセクター名 → GICS 11セクター
YAHOO_SECTOR_MAP = {
    "Technology": "information_technology",
    "Financial Services": "financials",
    "Healthcare": "health_care",
    "Consumer Cyclical": "consumer_discretionary",
    "Consumer Defensive": "consumer_staples",
    "Energy": "energy",
    "Basic Materials": "materials",
    "Industrials": "industrials",
    "Communication Services": "communication_services",
    "Utilities": "utilities",
    "Real Estate": "real_estate",
}

_JP_CODE = re.compile(r"^\d{3}[0-9A-Z]$")
_jpx: list[dict[str, Any]] | None = None
_jpx_loaded_at = 0.0
_jpx_lock = asyncio.Lock()


def _norm(s: str) -> str:
    return unicodedata.normalize("NFKC", s).lower().replace(" ", "")


def _parse_jpx(content: bytes) -> list[dict[str, Any]]:
    df = pd.read_excel(io.BytesIO(content), dtype=str)
    rows = []
    for r in df.itertuples(index=False):
        code, name, market, sector33, size_code = r[1], r[2], r[3], r[5], r[8]
        # ETF・REIT・PRO Market など株式以外（業種区分が "-"）は除外
        if sector33 not in JPX_SECTOR_MAP:
            continue
        rows.append({
            "symbol": f"{code}.T",
            "name": unicodedata.normalize("NFKC", name).strip(),
            "exchange": market,
            "sector": JPX_SECTOR_MAP[sector33],
            "sector_detail": sector33,
            "source": "jpx",
            "_key": _norm(name) + " " + code.lower(),
            # 規模コード: 1=TOPIX Core30, 2=Large70, 4=Mid400, 6=Small1, 7=Small2, "-"=指数対象外
            "_size": int(size_code) if size_code and size_code.isdigit() else 99,
        })
    return rows


async def _load_jpx() -> list[dict[str, Any]]:
    global _jpx, _jpx_loaded_at
    async with _jpx_lock:
        if _jpx is not None and time.time() - _jpx_loaded_at < _CACHE_TTL:
            return _jpx
        content: bytes | None = None
        if _CACHE_FILE.exists() and time.time() - _CACHE_FILE.stat().st_mtime < _CACHE_TTL:
            content = _CACHE_FILE.read_bytes()
        else:
            try:
                async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
                    resp = await client.get(JPX_URL)
                    resp.raise_for_status()
                content = resp.content
                _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                _CACHE_FILE.write_bytes(content)
            except Exception as e:
                # 取得に失敗しても古いキャッシュがあればそれを使う
                log.warning("JPX list download failed: %r", e)
                if _CACHE_FILE.exists():
                    content = _CACHE_FILE.read_bytes()
        _jpx = await asyncio.to_thread(_parse_jpx, content) if content else []
        _jpx_loaded_at = time.time()
        return _jpx


async def _search_jpx(q: str, limit: int) -> list[dict[str, Any]]:
    key = _norm(q)
    hits = [r for r in await _load_jpx() if key in r["_key"]]
    # コード一致 → 大型株 → 社名の先頭一致 の順に並べる
    hits.sort(key=lambda r: (not r["symbol"].lower().startswith(key), r["_size"], not r["_key"].startswith(key)))
    return [{k: v for k, v in r.items() if not k.startswith("_")} for r in hits[:limit]]


def _search_yahoo_sync(q: str, limit: int) -> list[dict[str, Any]]:
    quotes = yf.Search(q, max_results=limit * 2, news_count=0, enable_fuzzy_query=True).quotes
    out = []
    for x in quotes:
        if x.get("quoteType") != "EQUITY" or not x.get("symbol"):
            continue
        out.append({
            "symbol": x["symbol"],
            "name": x.get("longname") or x.get("shortname") or x["symbol"],
            "exchange": x.get("exchDisp") or x.get("exchange"),
            "sector": YAHOO_SECTOR_MAP.get(x.get("sector") or ""),
            "sector_detail": x.get("industry") or x.get("sector"),
            "source": "yahoo",
        })
    return out[:limit]


async def search(q: str, limit: int = 10) -> list[dict[str, Any]]:
    q = q.strip()
    if not q:
        return []
    is_japanese = any(ord(c) > 0x7F for c in q)
    tasks = [_search_jpx(q, limit)]
    if not is_japanese:  # Yahoo は日本語の社名では何も返さない
        tasks.append(asyncio.to_thread(_search_yahoo_sync, q, limit))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    merged: dict[str, dict[str, Any]] = {}
    # 日本語・証券コードでの検索は JPX、それ以外は Yahoo の結果を先に並べる
    ordered = results if is_japanese or _JP_CODE.match(q.upper()) else results[::-1]
    for res in ordered:
        if isinstance(res, Exception):
            log.warning("ticker search failed: %r", res)
            continue
        for r in res:
            merged.setdefault(r["symbol"].upper(), r)
    return list(merged.values())[:limit]
