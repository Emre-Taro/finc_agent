"""RSSフィードの取得とパース。

Reuters と日経は公式の公開RSSが無いため、Google News RSS の site: 検索で代替している。
各媒体は有料記事が多いので本文はスクレイピングせず、RSSのタイトルと概要だけを使う。
"""

import asyncio
import html
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote_plus

import feedparser
import httpx

from .dedup import strip_source_suffix

log = logging.getLogger(__name__)


def _google_news(query: str, lang: str) -> str:
    region = {"en": "hl=en-US&gl=US&ceid=US:en", "ja": "hl=ja&gl=JP&ceid=JP:ja"}[lang]
    return f"https://news.google.com/rss/search?q={quote_plus(query)}&{region}"


@dataclass(frozen=True)
class Feed:
    source: str
    name: str
    url: str


FEEDS: list[Feed] = [
    Feed("Bloomberg", "Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss"),
    Feed("Bloomberg", "Bloomberg Economics", "https://feeds.bloomberg.com/economics/news.rss"),
    Feed("Reuters", "Reuters Business (Google News)", _google_news("site:reuters.com/business when:1d", "en")),
    Feed("Reuters", "Reuters Markets (Google News)", _google_news("site:reuters.com/markets when:1d", "en")),
    Feed("Financial Times", "FT Markets", "https://www.ft.com/markets?format=rss"),
    Feed("Financial Times", "FT Global Economy", "https://www.ft.com/global-economy?format=rss"),
    Feed("日本経済新聞", "Nikkei (Google News)", _google_news("site:nikkei.com when:1d", "ja")),
]


@dataclass
class FeedItem:
    source: str
    feed_name: str
    title: str
    url: str
    published_at: datetime | None
    excerpt: str


_TAG = re.compile(r"<[^>]+>")
# Google News の site: 検索に混ざる株価ページ等の非記事
_NOT_ARTICLE = re.compile(r"Stock Price & Latest News|Stock Quote|株価・株式情報", re.I)


def _clean_html(text: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(_TAG.sub(" ", text or ""))).strip()


def _published(entry) -> datetime | None:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return None
    return datetime(*st[:6], tzinfo=timezone.utc)


async def _fetch_one(client: httpx.AsyncClient, feed: Feed, cutoff: datetime, limit: int) -> list[FeedItem]:
    resp = await client.get(feed.url)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)
    items: list[FeedItem] = []
    for entry in parsed.entries[:limit]:
        link = entry.get("link")
        title = strip_source_suffix(_clean_html(entry.get("title", "")))
        if not link or not title:
            continue
        published = _published(entry)
        if published and published < cutoff:
            continue
        if _NOT_ARTICLE.search(title):
            continue
        excerpt = _clean_html(entry.get("summary", ""))
        # Google News の summary は「タイトル + 媒体名」の繰り返しなので捨てる
        if excerpt.startswith(title):
            excerpt = ""
        items.append(FeedItem(feed.source, feed.name, title, link, published, excerpt[:1000]))
    return items


async def fetch_all(lookback_hours: int, limit_per_feed: int) -> tuple[list[FeedItem], dict[str, str]]:
    """全フィードを並列取得する。戻り値は (記事, フィード名→エラー内容)。"""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    headers = {"User-Agent": "Mozilla/5.0 (finc_agent RSS reader)"}
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers) as client:
        results = await asyncio.gather(
            *(_fetch_one(client, f, cutoff, limit_per_feed) for f in FEEDS), return_exceptions=True
        )
    items: list[FeedItem] = []
    errors: dict[str, str] = {}
    for feed, result in zip(FEEDS, results):
        if isinstance(result, Exception):
            log.warning("feed %s failed: %s", feed.name, result)
            errors[feed.name] = repr(result)
        else:
            items.extend(result)
    return items, errors
