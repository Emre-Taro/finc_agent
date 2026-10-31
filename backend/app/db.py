import json
from typing import Any

import asyncpg

from .config import get_settings

_pool: asyncpg.Pool | None = None


async def _init_conn(conn: asyncpg.Connection) -> None:
    for t in ("json", "jsonb"):
        await conn.set_type_codec(t, encoder=json.dumps, decoder=json.loads, schema="pg_catalog")


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            get_settings().database_url,
            init=_init_conn,
            min_size=1,
            max_size=10,
            # Neon/Supabase などの接続プーラー（PgBouncer）経由でも動くようプリペアドステートメントのキャッシュを切る
            statement_cache_size=0,
        )
    return _pool


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


async def fetch(sql: str, *args: Any) -> list[dict[str, Any]]:
    return [dict(r) for r in await (await get_pool()).fetch(sql, *args)]


async def fetchrow(sql: str, *args: Any) -> dict[str, Any] | None:
    row = await (await get_pool()).fetchrow(sql, *args)
    return dict(row) if row else None


async def fetchval(sql: str, *args: Any) -> Any:
    return await (await get_pool()).fetchval(sql, *args)


async def execute(sql: str, *args: Any) -> str:
    return await (await get_pool()).execute(sql, *args)
