"""Keeping the event loop free.

FastAPI serves every request on one event loop per worker. A synchronous call
inside an `async def` handler blocks *every* other request on that worker, so a
300 ms project analysis under 200 concurrent users becomes a 60 s queue.

Everything blocking therefore runs in a bounded thread pool:

  * CPU-bound parsing (AST analysis, diffing) -> `cpu_bound`
  * Disk I/O (archive extraction, JSON scans, file reads) -> `io_bound`

The pools are bounded deliberately. An unbounded pool under load just moves the
collapse from the event loop to the machine: thousands of threads thrashing on
one disk is slower than a queue that admits work at the rate the box can serve.
"""

from __future__ import annotations

import asyncio
import functools
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

from ..utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

_cpu_pool: ThreadPoolExecutor | None = None
_io_pool: ThreadPoolExecutor | None = None


def _default_cpu_workers() -> int:
    # Parsing is GIL-bound, so more threads than cores buys nothing.
    return max(2, min(8, (os.cpu_count() or 2)))


def _default_io_workers() -> int:
    # Disk I/O releases the GIL, so oversubscribe. The ceiling matters less than
    # it looks: aggregate reads are coalesced by the TTL cache, so this pool
    # mostly serves distinct per-project reads.
    return max(8, min(64, (os.cpu_count() or 2) * 8))


def configure_pools(cpu_workers: int | None = None, io_workers: int | None = None) -> None:
    global _cpu_pool, _io_pool
    shutdown_pools()
    _cpu_pool = ThreadPoolExecutor(
        max_workers=cpu_workers or _default_cpu_workers(), thread_name_prefix="apidoctor-cpu"
    )
    _io_pool = ThreadPoolExecutor(
        max_workers=io_workers or _default_io_workers(), thread_name_prefix="apidoctor-io"
    )
    logger.info(
        "thread pools ready: cpu=%d io=%d",
        _cpu_pool._max_workers,   # noqa: SLF001 - reporting only
        _io_pool._max_workers,    # noqa: SLF001
    )


def shutdown_pools(wait: bool = False) -> None:
    global _cpu_pool, _io_pool
    for pool in (_cpu_pool, _io_pool):
        if pool is not None:
            pool.shutdown(wait=wait, cancel_futures=not wait)
    _cpu_pool = None
    _io_pool = None


def _pool(kind: str) -> ThreadPoolExecutor:
    global _cpu_pool, _io_pool
    if _cpu_pool is None or _io_pool is None:
        configure_pools()
    return _cpu_pool if kind == "cpu" else _io_pool   # type: ignore[return-value]


async def cpu_bound(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run CPU-bound work off the event loop."""
    loop = asyncio.get_running_loop()
    call = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_pool("cpu"), call)


async def io_bound(func: Callable[..., T], /, *args: Any, **kwargs: Any) -> T:
    """Run blocking disk/network work off the event loop."""
    loop = asyncio.get_running_loop()
    call = functools.partial(func, *args, **kwargs)
    return await loop.run_in_executor(_pool("io"), call)


def pool_stats() -> dict:
    stats = {}
    for name, pool in (("cpu", _cpu_pool), ("io", _io_pool)):
        if pool is None:
            stats[name] = {"configured": False}
            continue
        queue = getattr(pool, "_work_queue", None)
        stats[name] = {
            "configured": True,
            "max_workers": pool._max_workers,          # noqa: SLF001
            "threads": len(pool._threads),             # noqa: SLF001
            "queued": queue.qsize() if queue is not None else 0,
        }
    return stats


async def with_timeout(awaitable, seconds: float, *, what: str):
    """Await with a deadline, raising a clear error instead of hanging a request."""
    try:
        return await asyncio.wait_for(awaitable, timeout=seconds)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"{what} exceeded its {seconds:g}s deadline") from exc


async def gather_bounded(coros, *, limit: int):
    """`asyncio.gather` with a concurrency ceiling."""
    semaphore = asyncio.Semaphore(limit)

    async def run(coro):
        async with semaphore:
            return await coro

    return await asyncio.gather(*(run(coro) for coro in coros), return_exceptions=True)
