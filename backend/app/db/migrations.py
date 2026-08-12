"""Schema migrations.

There was no migration system in this project, so this is the smallest one that
is still honest: numbered statements applied in order, recorded in a table, each
inside a transaction, and skipped when already applied. It runs at startup, so a
fresh Neon branch becomes a working database without a separate deploy step.

Adding a change means appending to `MIGRATIONS`. Never edit a revision that has
shipped — an applied revision is not re-run, so the edit would silently apply to
new databases only, and the two would drift.
"""

from __future__ import annotations

from pathlib import Path

from ..utils.logging import get_logger
from .pool import retrying

logger = get_logger(__name__)

SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text(encoding="utf-8")

_PREFERENCES_SQL = """
ALTER TABLE users
    ADD COLUMN IF NOT EXISTS preferences JSONB NOT NULL DEFAULT '{}'::jsonb
"""

# (revision, description, sql)
MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "initial schema: users, projects, repair_sessions, executions", SCHEMA_SQL),
    (2, "users.preferences for the settings page", _PREFERENCES_SQL),
]

_TRACKING_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    revision    INTEGER PRIMARY KEY,
    description TEXT        NOT NULL,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def applied_revisions() -> set[int]:
    def run(conn) -> set[int]:
        with conn.cursor() as cur:
            cur.execute(_TRACKING_TABLE)
            cur.execute("SELECT revision FROM schema_migrations")
            return {row[0] for row in cur.fetchall()}

    return retrying(run)


def migrate() -> list[int]:
    """Apply every pending revision. Returns the ones that ran."""
    done = applied_revisions()
    pending = [m for m in MIGRATIONS if m[0] not in done]
    if not pending:
        logger.info("database schema is up to date (revision %d)", max(done, default=0))
        return []

    ran: list[int] = []
    for revision, description, sql in pending:
        def run(conn, revision=revision, description=description, sql=sql):
            # One transaction per revision: a failure leaves the database on the
            # last good revision rather than half-migrated.
            with conn.transaction(), conn.cursor() as cur:
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (revision, description) VALUES (%s, %s) "
                    "ON CONFLICT (revision) DO NOTHING",
                    (revision, description),
                )

        retrying(run)
        ran.append(revision)
        logger.info("applied migration %d: %s", revision, description)
    return ran
