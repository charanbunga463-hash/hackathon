"""Short-TTL caching with single-flight coalescing.

The load test made the problem obvious: `/api/reports/dashboard` walks every
session file on disk, and with 1000 concurrent viewers that became 1000
identical disk scans queued behind a 32-thread pool. Throughput collapsed to
63 rps with a 7.6 s median.

Two ideas fix it:

**Single-flight.** When N requests want the same key at the same time, exactly
one does the work and the other N-1 await its result. This is the important
half: it turns a thundering herd into one scan regardless of concurrency.

**Short TTL.** Aggregates are polled every few seconds by the UI and are
inherently a snapshot. Serving a 2-second-old dashboard is correct behaviour,
not a compromise.

Deliberately *not* cached: anything a user just changed and expects to see, and
anything tenant-specific is keyed by tenant so no cache entry can cross a
tenant boundary.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Hashable

from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class _Entry:
    value: Any = None
    expires_at: float = 0.0
    inflight: asyncio.Future | None = None
    hits: int = 0


@dataclass
class TTLCache:
    """Async TTL cache where concurrent misses share one computation."""

    default_ttl: float = 2.0
    max_entries: int = 2048
    _entries: dict[Hashable, _Entry] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    hits: int = 0
    misses: int = 0
    coalesced: int = 0

    async def get_or_compute(
        self,
        key: Hashable,
        compute: Callable[[], Awaitable[Any]],
        *,
        ttl: float | None = None,
    ) -> Any:
        ttl = self.default_ttl if ttl is None else ttl
        now = time.monotonic()

        async with self._lock:
            entry = self._entries.get(key)
            if entry is not None and entry.expires_at > now and entry.inflight is None:
                entry.hits += 1
                self.hits += 1
                return entry.value
            if entry is not None and entry.inflight is not None:
                # Someone is already computing this exact key: wait for them
                # instead of duplicating the work.
                self.coalesced += 1
                inflight = entry.inflight
            else:
                self.misses += 1
                loop = asyncio.get_running_loop()
                entry = _Entry(inflight=loop.create_future())
                self._entries[key] = entry
                inflight = None
                self._evict_if_needed()

        if inflight is not None:
            return await asyncio.shield(inflight)

        # We own the computation.
        future = entry.inflight
        try:
            value = await compute()
        except Exception as exc:  # noqa: BLE001 - propagate to every waiter
            async with self._lock:
                self._entries.pop(key, None)
            if future is not None and not future.done():
                future.set_exception(exc)
            raise
        async with self._lock:
            entry.value = value
            entry.expires_at = time.monotonic() + ttl
            entry.inflight = None
        if future is not None and not future.done():
            future.set_result(value)
        return value

    def _evict_if_needed(self) -> None:
        if len(self._entries) <= self.max_entries:
            return
        now = time.monotonic()
        stale = [
            key for key, entry in self._entries.items()
            if entry.inflight is None and entry.expires_at <= now
        ]
        for key in stale:
            self._entries.pop(key, None)
        if len(self._entries) > self.max_entries:
            # Still over budget: drop the soonest-to-expire completed entries.
            candidates = sorted(
                (
                    (entry.expires_at, key)
                    for key, entry in self._entries.items()
                    if entry.inflight is None
                ),
            )
            for _expiry, key in candidates[: len(self._entries) - self.max_entries]:
                self._entries.pop(key, None)

    async def invalidate(self, *keys: Hashable) -> None:
        async with self._lock:
            for key in keys:
                self._entries.pop(key, None)

    async def invalidate_prefix(self, prefix: str) -> None:
        async with self._lock:
            for key in [
                key for key in self._entries
                if isinstance(key, tuple) and key and str(key[0]).startswith(prefix)
            ]:
                self._entries.pop(key, None)

    async def clear(self) -> None:
        async with self._lock:
            self._entries.clear()

    def stats(self) -> dict:
        total = self.hits + self.misses + self.coalesced
        return {
            "entries": len(self._entries),
            "hits": self.hits,
            "misses": self.misses,
            "coalesced": self.coalesced,
            "hit_rate": round((self.hits + self.coalesced) / total, 4) if total else 0.0,
        }


_cache: TTLCache | None = None


def get_cache() -> TTLCache:
    global _cache
    if _cache is None:
        _cache = TTLCache()
    return _cache


def reset_cache() -> None:
    global _cache
    _cache = None
