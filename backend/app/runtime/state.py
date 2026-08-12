"""Shared state: the difference between "multiple workers" and "correct".

Single-worker, in-process dicts are fine. The moment you run four uvicorn
workers behind nginx, three bugs appear immediately:

  1. A developer's approval POST lands on worker B while the repair runs on
     worker A. Worker B has no orchestrator to notify, so the patch never
     applies and the run times out.
  2. An SSE client connected to worker C sees none of the events worker A emits,
     so the activity feed silently shows nothing.
  3. Two workers read-modify-write the same project JSON and one update is lost.

This module fixes all three by putting the shared bits behind one interface:
pub/sub, key-value with TTL, atomic counters, and distributed locks.

`MemoryStateBackend` keeps single-node deployments dependency-free and is the
default. `RedisStateBackend` is selected by setting `REDIS_URL`, and is what
makes horizontal scaling actually work.
"""

from __future__ import annotations

import abc
import asyncio
import contextlib
import json
import time
import uuid
from typing import Any, AsyncIterator

from ..utils.logging import get_logger

logger = get_logger(__name__)

LOCK_TTL_SECONDS = 30.0


class LockTimeout(RuntimeError):
    """Raised when a distributed lock could not be acquired in time."""


class StateBackend(abc.ABC):
    """Everything that must be shared between workers."""

    name: str = "abstract"

    async def start(self) -> None:  # pragma: no cover - trivial
        return None

    async def close(self) -> None:  # pragma: no cover - trivial
        return None

    async def healthy(self) -> bool:
        return True

    # ------------------------------------------------------------- kv ------
    @abc.abstractmethod
    async def get_json(self, key: str) -> Any | None: ...

    # Note: `ttl=None` *and* `ttl=0` both mean "never expires". Callers with a
    # configurable duration must not pass a computed zero and assume the key
    # goes away — check for zero first.
    @abc.abstractmethod
    async def set_json(self, key: str, value: Any, *, ttl: float | None = None) -> None: ...

    @abc.abstractmethod
    async def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    async def scan_prefix(self, prefix: str, *, limit: int = 500) -> list[str]: ...

    # -------------------------------------------------------- counters -----
    @abc.abstractmethod
    async def incr(self, key: str, amount: int = 1, *, ttl: float | None = None) -> int: ...

    async def decr(self, key: str, amount: int = 1) -> int:
        return await self.incr(key, -amount)

    @abc.abstractmethod
    async def get_int(self, key: str) -> int: ...

    # ----------------------------------------------------------- locks -----
    @abc.abstractmethod
    async def acquire(self, key: str, *, ttl: float, timeout: float) -> str | None: ...

    @abc.abstractmethod
    async def release(self, key: str, token: str) -> None: ...

    @contextlib.asynccontextmanager
    async def lock(
        self, key: str, *, ttl: float = LOCK_TTL_SECONDS, timeout: float = 10.0
    ) -> AsyncIterator[None]:
        token = await self.acquire(key, ttl=ttl, timeout=timeout)
        if token is None:
            raise LockTimeout(f"could not acquire lock {key!r} within {timeout:g}s")
        try:
            yield
        finally:
            await self.release(key, token)

    # ---------------------------------------------------------- pubsub -----
    @abc.abstractmethod
    async def publish(self, channel: str, payload: dict) -> None: ...

    @abc.abstractmethod
    def subscribe(self, channel: str) -> AsyncIterator[dict]: ...


# ---------------------------------------------------------------------------
# In-memory (single worker)
# ---------------------------------------------------------------------------


class MemoryStateBackend(StateBackend):
    name = "memory"

    def __init__(self) -> None:
        self._kv: dict[str, tuple[Any, float | None]] = {}
        self._locks: dict[str, tuple[str, float]] = {}
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._guard = asyncio.Lock()

    def _expired(self, key: str) -> bool:
        entry = self._kv.get(key)
        if entry is None:
            return True
        _value, expires = entry
        if expires is not None and expires < time.monotonic():
            self._kv.pop(key, None)
            return True
        return False

    async def get_json(self, key: str) -> Any | None:
        if self._expired(key):
            return None
        return self._kv[key][0]

    async def set_json(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        expires = time.monotonic() + ttl if ttl else None
        self._kv[key] = (value, expires)

    async def delete(self, key: str) -> None:
        self._kv.pop(key, None)

    async def scan_prefix(self, prefix: str, *, limit: int = 500) -> list[str]:
        keys = [key for key in list(self._kv) if key.startswith(prefix) and not self._expired(key)]
        return keys[:limit]

    async def incr(self, key: str, amount: int = 1, *, ttl: float | None = None) -> int:
        async with self._guard:
            current = 0 if self._expired(key) else int(self._kv[key][0])
            updated = current + amount
            expires = time.monotonic() + ttl if ttl else (
                self._kv.get(key, (None, None))[1] if key in self._kv else None
            )
            self._kv[key] = (updated, expires)
            return updated

    async def get_int(self, key: str) -> int:
        value = await self.get_json(key)
        return int(value or 0)

    async def acquire(self, key: str, *, ttl: float, timeout: float) -> str | None:
        token = uuid.uuid4().hex
        deadline = time.monotonic() + timeout
        while True:
            async with self._guard:
                holder = self._locks.get(key)
                if holder is None or holder[1] < time.monotonic():
                    self._locks[key] = (token, time.monotonic() + ttl)
                    return token
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.02)

    async def release(self, key: str, token: str) -> None:
        async with self._guard:
            holder = self._locks.get(key)
            if holder is not None and holder[0] == token:
                self._locks.pop(key, None)

    async def publish(self, channel: str, payload: dict) -> None:
        for queue in list(self._subscribers.get(channel, ())):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # A stalled consumer loses history, never liveness.
                with contextlib.suppress(asyncio.QueueEmpty, asyncio.QueueFull):
                    queue.get_nowait()
                    queue.put_nowait(payload)

    async def subscribe(self, channel: str) -> AsyncIterator[dict]:
        queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.setdefault(channel, set()).add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.get(channel, set()).discard(queue)


# ---------------------------------------------------------------------------
# Redis (horizontal scale)
# ---------------------------------------------------------------------------

# Release only if we still own the lock; otherwise a slow holder whose TTL
# expired would delete the next holder's lock.
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
else
  return 0
end
"""


class RedisStateBackend(StateBackend):
    name = "redis"

    def __init__(self, url: str, *, namespace: str = "apidoctor") -> None:
        self.url = url
        self.namespace = namespace
        self._redis = None
        self._release_sha: str | None = None

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    async def start(self) -> None:
        try:
            from redis.asyncio import Redis
        except ImportError as exc:  # pragma: no cover - depends on install
            raise RuntimeError(
                "REDIS_URL is set but the 'redis' package is not installed. "
                "Install it with: pip install 'redis>=5.0'"
            ) from exc
        self._redis = Redis.from_url(
            self.url, encoding="utf-8", decode_responses=True,
            socket_timeout=5, socket_connect_timeout=5, health_check_interval=30,
        )
        await self._redis.ping()
        self._release_sha = await self._redis.script_load(_RELEASE_LUA)
        logger.info("redis state backend connected: %s", _redact(self.url))

    async def close(self) -> None:
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def healthy(self) -> bool:
        try:
            return bool(self._redis is not None and await self._redis.ping())
        except Exception:  # noqa: BLE001
            return False

    async def get_json(self, key: str) -> Any | None:
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw

    async def set_json(self, key: str, value: Any, *, ttl: float | None = None) -> None:
        payload = json.dumps(value, default=str)
        if ttl:
            await self._redis.set(self._key(key), payload, ex=int(max(1, ttl)))
        else:
            await self._redis.set(self._key(key), payload)

    async def delete(self, key: str) -> None:
        await self._redis.delete(self._key(key))

    async def scan_prefix(self, prefix: str, *, limit: int = 500) -> list[str]:
        found: list[str] = []
        pattern = f"{self._key(prefix)}*"
        offset = len(self.namespace) + 1
        async for key in self._redis.scan_iter(match=pattern, count=200):
            found.append(key[offset:])
            if len(found) >= limit:
                break
        return found

    async def incr(self, key: str, amount: int = 1, *, ttl: float | None = None) -> int:
        pipe = self._redis.pipeline()
        pipe.incrby(self._key(key), amount)
        if ttl:
            pipe.expire(self._key(key), int(max(1, ttl)))
        result = await pipe.execute()
        return int(result[0])

    async def get_int(self, key: str) -> int:
        raw = await self._redis.get(self._key(key))
        try:
            return int(raw or 0)
        except (TypeError, ValueError):
            return 0

    async def acquire(self, key: str, *, ttl: float, timeout: float) -> str | None:
        token = uuid.uuid4().hex
        deadline = time.monotonic() + timeout
        redis_key = self._key(f"lock:{key}")
        while True:
            if await self._redis.set(redis_key, token, nx=True, px=int(ttl * 1000)):
                return token
            if time.monotonic() >= deadline:
                return None
            await asyncio.sleep(0.02)

    async def release(self, key: str, token: str) -> None:
        redis_key = self._key(f"lock:{key}")
        try:
            await self._redis.evalsha(self._release_sha, 1, redis_key, token)
        except Exception:  # noqa: BLE001 - script cache may have been flushed
            await self._redis.eval(_RELEASE_LUA, 1, redis_key, token)

    async def publish(self, channel: str, payload: dict) -> None:
        await self._redis.publish(self._key(channel), json.dumps(payload, default=str))

    async def subscribe(self, channel: str) -> AsyncIterator[dict]:
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._key(channel))
        try:
            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue
                try:
                    yield json.loads(message["data"])
                except (TypeError, ValueError):
                    continue
        finally:
            with contextlib.suppress(Exception):
                await pubsub.unsubscribe(self._key(channel))
                await pubsub.aclose()


def _redact(url: str) -> str:
    if "@" not in url:
        return url
    scheme, _, rest = url.partition("://")
    return f"{scheme}://***@{rest.rpartition('@')[2]}"


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

_backend: StateBackend | None = None


async def init_state_backend(redis_url: str | None, *, namespace: str = "apidoctor") -> StateBackend:
    """Choose and start the backend. Falls back to memory if Redis is down."""
    global _backend
    if _backend is not None:
        return _backend
    if redis_url:
        candidate = RedisStateBackend(redis_url, namespace=namespace)
        try:
            await candidate.start()
            _backend = candidate
            return _backend
        except Exception as exc:  # noqa: BLE001
            # Degrade loudly: a silent fallback would mean multi-worker
            # deployments quietly lose approvals and events.
            logger.error(
                "REDIS_URL is configured but unreachable (%s). Falling back to in-memory "
                "state — this is only correct with a SINGLE worker. Approvals and SSE will "
                "not work across workers until Redis is available.",
                exc,
            )
    _backend = MemoryStateBackend()
    await _backend.start()
    return _backend


def get_state_backend() -> StateBackend:
    global _backend
    if _backend is None:
        _backend = MemoryStateBackend()
    return _backend


async def reset_state_backend() -> None:
    """Test hook."""
    global _backend
    if _backend is not None:
        await _backend.close()
    _backend = None
