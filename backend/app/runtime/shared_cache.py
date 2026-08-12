"""Redis cache tier and cross-worker invalidation.

Two levels sit in front of Postgres:

    L1  in-process TTLCache — sub-millisecond, single-flight, ~2s TTL
    L2  Redis              — shared by every worker, longer TTL
    origin  Postgres (Neon)

L1 alone was correct when each worker had its own filesystem. With one shared
database it is not: worker A writes, invalidates *its* cache, and worker B keeps
serving its own stale copy until the TTL lapses. That is the bug this module
closes — an invalidation is published to Redis and every worker drops the key.

L2 exists for the queries that are expensive at the origin rather than merely
frequent: the dashboard and history aggregate across a tenant's whole history.
The project list is deliberately *not* in L2 — it is one indexed query, and a
Redis round-trip would cost more than it saves.

With no Redis configured both tiers degrade to the in-process cache, which is
exactly right for one worker.
"""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from ..utils.logging import get_logger
from .cache import get_cache
from .state import MemoryStateBackend, get_state_backend

logger = get_logger(__name__)

INVALIDATION_CHANNEL = "cache:invalidate"

_listener: asyncio.Task | None = None


def _distributed() -> bool:
    return not isinstance(get_state_backend(), MemoryStateBackend)


# ----------------------------------------------------------------- L2 -------
async def cached(
    key: str,
    compute: Callable[[], Awaitable[Any]],
    *,
    ttl: float,
) -> Any:
    """Read through L1 then L2, computing at the origin only on a full miss."""
    state = get_state_backend()

    async def from_l2_or_origin() -> Any:
        if _distributed():
            try:
                hit = await state.get_json(f"cache:{key}")
                if hit is not None:
                    return hit
            except Exception as exc:  # noqa: BLE001 - a cache must never 500
                logger.warning("shared cache read failed for %s: %s", key, exc)

        value = await compute()

        if _distributed():
            try:
                await state.set_json(f"cache:{key}", value, ttl=ttl)
            except Exception as exc:  # noqa: BLE001
                logger.warning("shared cache write failed for %s: %s", key, exc)
        return value

    # L1 also collapses concurrent misses into one computation, so a burst of
    # dashboard polls does not become a burst of queries.
    return await get_cache().get_or_compute(("shared", key), from_l2_or_origin, ttl=min(ttl, 2.0))


# -------------------------------------------------------- invalidation ------
async def invalidate(*keys: str, prefixes: tuple[str, ...] = ()) -> None:
    """Drop these keys here and on every other worker."""
    await _apply_locally(keys, prefixes)
    if not _distributed():
        return
    state = get_state_backend()
    try:
        for key in keys:
            await state.delete(f"cache:{key}")
        await state.publish(
            INVALIDATION_CHANNEL, {"keys": list(keys), "prefixes": list(prefixes)}
        )
    except Exception as exc:  # noqa: BLE001
        # Worst case the other workers serve a stale aggregate until their TTL
        # lapses. Failing the write that triggered this would be worse.
        logger.warning("could not broadcast cache invalidation: %s", exc)


async def _apply_locally(keys, prefixes) -> None:
    cache = get_cache()
    if keys:
        await cache.invalidate(*[("shared", key) for key in keys])
    for prefix in prefixes:
        await cache.invalidate_prefix(prefix)


async def start_invalidation_listener() -> None:
    """Subscribe to invalidations published by sibling workers."""
    global _listener
    if _listener is not None or not _distributed():
        return
    state = get_state_backend()

    async def listen() -> None:
        while True:
            try:
                async for payload in state.subscribe(INVALIDATION_CHANNEL):
                    await _apply_locally(
                        tuple(payload.get("keys") or ()),
                        tuple(payload.get("prefixes") or ()),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                logger.warning("cache invalidation listener dropped (%s); reconnecting", exc)
                await asyncio.sleep(1.0)

    _listener = asyncio.create_task(listen(), name="cache-invalidation")


async def stop_invalidation_listener() -> None:
    global _listener
    if _listener is not None:
        _listener.cancel()
        try:
            await _listener
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _listener = None


def stats() -> dict:
    return {"tier1": get_cache().stats(), "tier2": "redis" if _distributed() else "disabled"}
