"""Claude API 呼び出しの共通処理（構造化出力 + 拒否時のサーバー側フォールバック）。"""

import json
from typing import Any

import anthropic

from .config import get_settings

_client: anthropic.AsyncAnthropic | None = None


def get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        key = get_settings().anthropic_api_key
        # 未設定なら SDK 側の資格情報解決（ant auth login のプロファイル等）に任せる
        _client = anthropic.AsyncAnthropic(api_key=key) if key else anthropic.AsyncAnthropic()
    return _client


class ClaudeError(RuntimeError):
    pass


# 拒否時のサーバー側フォールバックに対応しているモデル（Haiku は非対応）
_FALLBACK_MODELS = {"claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}


async def structured_call(system: str, user: str, schema: dict[str, Any], effort: str = "medium") -> dict[str, Any]:
    """JSONスキーマに従った出力を1回のリクエストで得る。"""
    model = get_settings().claude_model
    extra: dict[str, Any] = {}
    if model in _FALLBACK_MODELS:
        # 安全分類器による拒否時は、拒否カテゴリに応じた推奨モデルでサーバー側が再実行する
        extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
    response = await get_client().beta.messages.create(
        model=model,
        max_tokens=16000,
        system=system,
        messages=[{"role": "user", "content": user}],
        thinking={"type": "adaptive"},
        output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
        **extra,
    )
    if response.stop_reason == "refusal":
        raise ClaudeError(f"refused: {response.stop_details}")
    if response.stop_reason == "max_tokens":
        raise ClaudeError("output truncated (max_tokens)")
    text = next((b.text for b in response.content if b.type == "text"), None)
    if text is None:
        raise ClaudeError("no text block in response")
    return json.loads(text)
