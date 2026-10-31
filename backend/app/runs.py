"""ingest_runs テーブルへの実行ログ記録と、バックグラウンド実行の管理。"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from . import db

log = logging.getLogger(__name__)

# 同じ種類のジョブの二重起動を防ぐ（ボタン連打対策）。単一プロセス前提。
_locks: dict[str, asyncio.Lock] = {}
_tasks: set[asyncio.Task] = set()


def is_running(kind: str) -> bool:
    return _locks.setdefault(kind, asyncio.Lock()).locked()


async def start_run(kind: str) -> str:
    return str(await db.fetchval("insert into ingest_runs (kind) values ($1) returning id", kind))


async def finish_run(run_id: str, status: str, stats: dict[str, Any], error: str | None = None) -> None:
    await db.execute(
        "update ingest_runs set status = $2, stats = $3, error = $4, finished_at = now() where id = $1",
        run_id, status, stats, error,
    )


async def launch(kind: str, job: Callable[[str], Awaitable[tuple[str, dict[str, Any]]]]) -> str:
    """ジョブをバックグラウンドで実行し、すぐに run_id を返す。job は (status, stats) を返す。"""
    lock = _locks.setdefault(kind, asyncio.Lock())
    await lock.acquire()
    try:
        run_id = await start_run(kind)
    except Exception:
        lock.release()
        raise

    async def runner() -> None:
        try:
            status, stats = await job(run_id)
            await finish_run(run_id, status, stats)
        except Exception as e:
            log.exception("%s run %s failed", kind, run_id)
            await finish_run(run_id, "failed", {}, repr(e))
        finally:
            lock.release()

    task = asyncio.create_task(runner())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return run_id
