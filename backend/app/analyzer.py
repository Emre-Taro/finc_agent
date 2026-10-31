"""ニュース1件をClaudeで評価する。"""

from typing import Any

from .claude import structured_call
from .taxonomy import NEWS_INDICATORS, SECTORS

# 全セクター×全指標を固定キーで必須にすると構造化出力の文法が大きくなりすぎて API に拒否される
# （"compiled grammar is too large"）。そのため配列で受け取り、範囲の丸めと欠損の補完は normalize() で行う。
SCORE = {"type": "integer"}


def _impact_list(codes: list[str]) -> dict[str, Any]:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"code": {"type": "string", "enum": codes}, "score": SCORE, "reason": {"type": "string"}},
            "required": ["code", "score", "reason"],
            "additionalProperties": False,
        },
    }


ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary_ja": {"type": "string"},
        "macro_score": SCORE,
        "primary_sector": {"type": "string", "enum": list(SECTORS)},
        "industry_score": SCORE,
        "primary_ticker": {"type": "string"},
        "ticker_score": SCORE,
        "reason_ja": {"type": "string"},
        "sector_impacts": _impact_list(list(SECTORS)),
        "indicator_impacts": _impact_list(list(NEWS_INDICATORS)),
        "ticker_impacts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string"},
                    "name": {"type": "string"},
                    "score": SCORE,
                    "reason": {"type": "string"},
                },
                "required": ["ticker", "name", "score", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "summary_ja", "macro_score", "primary_sector", "industry_score", "primary_ticker",
        "ticker_score", "reason_ja", "sector_impacts", "indicator_impacts", "ticker_impacts",
    ],
    "additionalProperties": False,
}

_sector_lines = "\n".join(f"- {k}: {v}" for k, v in SECTORS.items())
_indicator_lines = "\n".join(f"- {k}: {v}" for k, v in NEWS_INDICATORS.items())

SYSTEM_PROMPT = f"""あなたは機関投資家向けのマクロ・株式ストラテジストです。
金融ニュース1件（タイトルとRSSの概要のみ。本文は無い）を読み、市場への影響を評価してください。
概要が短い場合はタイトルから合理的に推測し、確信が持てない項目は 0 にしてください。誇張せず、ニュース単体の影響に絞って評価します。

スコアはすべて -2〜+2 の整数です。
- macro_score: 世界経済・リスク資産全体にとっての好悪（+2 = 非常に好材料, -2 = 非常に悪材料）
- primary_sector / industry_score: 最も影響を受けるセクターと、そのセクターにとっての好悪
- primary_ticker / ticker_score: 最も影響を受ける個別企業のティッカーと好悪。特定企業の話でなければ primary_ticker は空文字、ticker_score は 0
- sector_impacts: 下記の全セクターを1回ずつ（11件）、そのセクターの株価にとっての好悪
- indicator_impacts: 下記の全指標を1回ずつ（13件）、その指標の値が「上がる(+)か下がる(-)か」の方向。好悪ではない点に注意（例: インフレ加速なら US_INFLATION は +）
- ticker_impacts: 記事で言及・影響が明確な個別企業（無ければ空配列）

ティッカーは Yahoo Finance 形式（米国株: AAPL、日本株: 7203.T など）で書いてください。
summary_ja は日本語で2〜3文の要約、reason_ja は各スコアの根拠となる因果関係を日本語で簡潔に説明してください。
各 reason も日本語で1文程度。影響がない項目は「直接の影響は小さい」等で構いません。

セクター:
{_sector_lines}

指標:
{_indicator_lines}
"""


async def analyze(news: dict[str, Any]) -> dict[str, Any]:
    """news テーブルの1行を受け取り、ANALYSIS_SCHEMA に沿った評価を返す。"""
    user = (
        f"媒体: {news['source']}\n公開日時: {news.get('published_at') or '不明'}\n"
        f"タイトル: {news['title']}\n概要: {news.get('raw_excerpt') or '（なし）'}"
    )
    return normalize(await structured_call(SYSTEM_PROMPT, user, ANALYSIS_SCHEMA))


def _clamp(v: Any) -> int:
    return max(-2, min(2, int(v)))


def _complete(items: list[dict[str, Any]], codes: dict[str, str]) -> dict[str, dict[str, Any]]:
    """配列を code → {score, reason} に変換し、出力されなかった項目は 0 で補完する。"""
    out = {code: {"score": 0, "reason": "評価なし（直接の影響は小さい）"} for code in codes}
    for it in items:
        out[it["code"]] = {"score": _clamp(it["score"]), "reason": it["reason"]}
    return out


def normalize(result: dict[str, Any]) -> dict[str, Any]:
    """スコアを -2〜+2 に丸め、全セクター・全指標がそろった形にする。"""
    for key in ("macro_score", "industry_score", "ticker_score"):
        result[key] = _clamp(result[key])
    result["sector_impacts"] = _complete(result["sector_impacts"], SECTORS)
    result["indicator_impacts"] = _complete(result["indicator_impacts"], NEWS_INDICATORS)
    for t in result["ticker_impacts"]:
        t["score"] = _clamp(t["score"])
    return result
