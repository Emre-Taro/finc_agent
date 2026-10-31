"""重複判定用のURL・タイトル正規化。"""

import hashlib
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# 記事の同一性に関係しないトラッキング系クエリ
_TRACKING_PARAMS = {
    "cmpid", "srnd", "ftag", "segmentid", "ncid", "taid", "rss", "feed", "ref",
    "src", "sref", "smid", "fbclid", "gclid", "mc_cid", "mc_eid", "leadsource",
}

# Google News経由のタイトルは "記事タイトル - Reuters" の形で媒体名が付く
_SOURCE_SUFFIX = re.compile(r"\s+[-|–—]\s+(Reuters|ロイター|日本経済新聞|日経電子版|Nikkei Asia|Bloomberg|Financial Times)\s*$", re.I)


def normalize_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS
    ]
    query.sort()
    host = parts.netloc.lower().removeprefix("www.")
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https", host, path, urlencode(query), ""))


def strip_source_suffix(title: str) -> str:
    return _SOURCE_SUFFIX.sub("", title).strip()


def normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKC", strip_source_suffix(title)).lower()
    # 記号・空白をすべて除去（全角/半角や句読点の揺れを吸収）
    return re.sub(r"[\W_]+", "", t)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def url_hash(url: str) -> str:
    return sha256(normalize_url(url))


def title_hash(title: str) -> str:
    return sha256(normalize_title(title))
