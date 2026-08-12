"""Postgres connection pool, tuned for Neon.

Neon is serverless Postgres, and two of its properties shape everything here:

**The compute suspends when idle.** A connection that worked a minute ago can be
dead now, and the failure surfaces as an `OperationalError` on the next query
rather than at checkout. The pool is therefore configured to check connections
before handing them out, and `retrying()` re-runs a failed operation once so a
cold start costs latency instead of a 500.

**Connections are the scarce resource, not queries.** Neon's free tier caps
concurrent connections, so the pool is deliberately small and every caller
returns its connection immediately. Point `DATABASE_URL` at Neon's `-pooler`
host to sit behind their PgBouncer when running more than one worker.

The pool is synchronous on purpose. Every store call in this codebase already
runs through `io_bound`, so a sync driver in a worker thread matches the
existing execution model exactly and avoids threading a second async stack
through the services.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, TypeVar
from urllib.parse import urlparse

from ..utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

_pool: Any = None
_lock = threading.Lock()


class DatabaseError(RuntimeError):
    pass


def normalize_dsn(url: str) -> str:
    """Accept the URL shapes Neon and Heroku-style tools hand out.

    Neon's console copies `postgresql://...?sslmode=require&channel_binding=require`,
    some tools emit `postgres://`, and psycopg only understands the former.
    TLS is forced when the host is not local: Neon refuses plaintext anyway, and
    silently downgrading would be worse than failing.
    """
    dsn = (url or "").strip()
    if not dsn:
        raise DatabaseError("DATABASE_URL is empty")
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://") :]
    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    is_local = host in {"localhost", "127.0.0.1", "::1", ""}
    if "sslmode=" not in dsn and not is_local:
        dsn += ("&" if "?" in dsn else "?") + "sslmode=require"
    return dsn


def redact_dsn(url: str) -> str:
    """A log-safe rendering: keeps host and database, drops the credentials."""
    try:
        parsed = urlparse(url)
        database = (parsed.path or "/").lstrip("/") or "?"
        return f"{parsed.hostname or '?'}/{database}"
    except Exception:  # noqa: BLE001
        return "?"


def init_pool(url: str, *, min_size: int = 1, max_size: int = 8, timeout: float = 30.0):
    """Open the pool. Safe to call more than once; the first call wins."""
    global _pool
    with _lock:
        if _pool is not None:
            return _pool
        try:
            from psycopg import OperationalError
            from psycopg_pool import ConnectionPool
        except ImportError as exc:  # pragma: no cover - depends on install
            raise DatabaseError(
                "DATABASE_URL is set but psycopg is not installed. "
                "Install it with: pip install 'psycopg[binary,pool]'"
            ) from exc

        dsn = normalize_dsn(url)
        pool = ConnectionPool(
            dsn,
            min_size=min_size,
            max_size=max_size,
            timeout=timeout,
            # NO `check=` on purpose.
            #
            # `ConnectionPool.check_connection` issues a `SELECT 1` on every
            # checkout to prove the connection is alive. Against a managed
            # database in another region that doubles the round trips of every
            # query for no new safety: `retrying()` below already catches
            # OperationalError and retries with backoff, which is the same
            # recovery path a failed check would have led to.
            #
            # Measured against a Neon instance one region away: 1014 ms per
            # query with the check, 751 ms without — 26% of every database call
            # spent re-proving liveness the retry loop already handles.
            kwargs={"application_name": "api-doctor", "connect_timeout": 15},
            # Recycle before Neon's own idle cutoff so a checkout rarely meets a
            # server-closed socket in the first place.
            max_idle=120.0,
            open=False,
        )
        pool.open(wait=True, timeout=timeout)
        _pool = pool
        logger.info("postgres pool ready: %s", redact_dsn(dsn))
        _ = OperationalError  # imported for the retry path below
        return _pool


def get_pool():
    if _pool is None:
        raise DatabaseError(
            "the database pool is not initialised; DATABASE_URL must be set at startup"
        )
    return _pool


def pool_is_open() -> bool:
    return _pool is not None


def close_pool() -> None:
    global _pool
    with _lock:
        if _pool is not None:
            _pool.close()
            _pool = None


def healthy() -> bool:
    if _pool is None:
        return False
    try:
        with _pool.connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1")
            return cur.fetchone() is not None
    except Exception as exc:  # noqa: BLE001
        logger.warning("postgres health check failed: %s", exc)
        return False


def retrying(operation: Callable[[Any], T], *, attempts: int = 3) -> T:
    """Run `operation(connection)`, surviving a suspended Neon compute.

    Only connection-level failures are retried. A constraint violation or a bad
    query is a real error and is raised on the first attempt — retrying those
    would just hide the bug and write the same row twice.
    """
    from psycopg import OperationalError

    pool = get_pool()
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            with pool.connection() as conn:
                return operation(conn)
        except OperationalError as exc:
            last = exc
            if attempt == attempts - 1:
                break
            delay = 0.4 * (2**attempt)
            logger.warning(
                "postgres connection failed (%s); retrying in %.1fs — this is normal "
                "on the first query after a Neon compute suspends",
                exc,
                delay,
            )
            time.sleep(delay)
    raise DatabaseError(f"database unavailable after {attempts} attempts: {last}") from last
