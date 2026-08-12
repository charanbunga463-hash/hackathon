"""Database layer: Neon Postgres for the system of record.

    Postgres  users, projects, repair sessions, execution records
    Redis     sessions, one-time codes, rate limits, locks, pub/sub, hot caches
    Disk      project workspaces and snapshots — the code that actually runs

Selection is by configuration, not by import: set `DATABASE_URL` and the
Postgres stores are used; leave it unset and the JSON stores keep a laptop
working with no services to install. Production refuses to start without it.
"""

from __future__ import annotations

from ..utils.logging import get_logger
from .pool import (
    DatabaseError,
    close_pool,
    get_pool,
    healthy,
    init_pool,
    normalize_dsn,
    pool_is_open,
    redact_dsn,
)

logger = get_logger(__name__)

__all__ = [
    "DatabaseError",
    "close_pool",
    "database_enabled",
    "get_pool",
    "healthy",
    "init_database",
    "init_pool",
    "normalize_dsn",
    "pool_is_open",
    "redact_dsn",
]


def database_enabled() -> bool:
    return pool_is_open()


def init_database(url: str | None, *, min_size: int = 1, max_size: int = 8) -> bool:
    """Open the pool and bring the schema up to date. Returns True if enabled."""
    if not url:
        logger.warning(
            "DATABASE_URL is not set — falling back to the on-disk JSON stores. "
            "That is fine for local development and wrong for anything shared: "
            "the data lives in one container's filesystem."
        )
        return False

    from .migrations import migrate

    init_pool(url, min_size=min_size, max_size=max_size)
    applied = migrate()
    if applied:
        logger.info("database migrated: revisions %s", applied)
    return True
