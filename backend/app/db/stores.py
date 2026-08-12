"""Postgres implementations of the persistence protocols.

These satisfy `UserStore` and `ProjectStore` exactly as the JSON stores do, so
the services above them did not change — that is what the Protocol boundary was
for. `PostgresRecordStore` is new, covering repair sessions and execution
records, which the repair service previously read and wrote as loose files.

What stays on disk: the project **workspace** and its **snapshots**. Those are
real source trees that pytest and Docker execute against; a database row cannot
be a working directory. Postgres is the system of record for everything *about*
a project, the filesystem holds the code itself, and Redis holds the ephemera
(sessions, one-time codes, rate limits, locks, pub/sub).

Every query is scoped by owner where the caller supplies one. Ownership is still
enforced above this layer too — defence in depth, not one check in one place.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg.types.json import Jsonb

from ..models.execution import ExecutionRecord
from ..models.project import Project, ProjectSummary
from ..models.report import RepairSession
from ..models.user import User, normalize_email
from ..utils.logging import get_logger
from .pool import retrying

logger = get_logger(__name__)


def _ts(value: str | None) -> datetime:
    """Parse the models' ISO timestamps into something Postgres can order.

    The authoritative value stays inside the JSONB record; this column exists
    so ORDER BY happens in the database instead of in Python.
    """
    if not value:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return datetime.now(timezone.utc)


def _model(cls, payload: Any, what: str):
    """Validate a stored record, treating corruption as absence rather than 500."""
    if payload is None:
        return None
    try:
        return cls.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("unreadable %s record: %s", what, exc)
        return None


# --------------------------------------------------------------- users ------
class PostgresUserStore:
    def save(self, user: User) -> None:
        user.touch()
        record = user.model_dump(mode="json")

        def run(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO users (id, name, email, password_hash, email_verified,
                                       status, session_epoch, last_login_at,
                                       created_at, updated_at, preferences)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        name = EXCLUDED.name,
                        email = EXCLUDED.email,
                        password_hash = EXCLUDED.password_hash,
                        email_verified = EXCLUDED.email_verified,
                        status = EXCLUDED.status,
                        session_epoch = EXCLUDED.session_epoch,
                        last_login_at = EXCLUDED.last_login_at,
                        updated_at = EXCLUDED.updated_at,
                        preferences = EXCLUDED.preferences
                    """,
                    (
                        user.id,
                        user.name,
                        normalize_email(user.email),
                        user.password_hash,
                        user.email_verified,
                        user.status.value,
                        user.session_epoch,
                        _ts(user.last_login_at) if user.last_login_at else None,
                        _ts(record["created_at"]),
                        _ts(record["updated_at"]),
                        Jsonb(record["preferences"]),
                    ),
                )

        retrying(run)

    def _row_to_user(self, row) -> User | None:
        if row is None:
            return None
        (
            user_id, name, email, password_hash, email_verified,
            status, session_epoch, last_login_at, created_at, updated_at,
            preferences,
        ) = row
        return _model(
            User,
            {
                "id": user_id,
                "name": name,
                "email": email,
                "password_hash": password_hash,
                "email_verified": email_verified,
                "status": status,
                "session_epoch": session_epoch,
                "last_login_at": last_login_at.isoformat() if last_login_at else None,
                "created_at": created_at.isoformat(),
                "updated_at": updated_at.isoformat(),
                # Rows written before revision 2 default to '{}', which the
                # model fills in with its own defaults.
                "preferences": preferences or {},
            },
            "user",
        )

    _SELECT = (
        "SELECT id, name, email, password_hash, email_verified, status, "
        "session_epoch, last_login_at, created_at, updated_at, preferences FROM users"
    )

    def load(self, user_id: str) -> User | None:
        if not user_id:
            return None

        def run(conn):
            with conn.cursor() as cur:
                cur.execute(f"{self._SELECT} WHERE id = %s", (user_id,))
                return cur.fetchone()

        return self._row_to_user(retrying(run))

    def find_by_email(self, email: str) -> User | None:
        normalized = normalize_email(email)
        if not normalized:
            return None

        def run(conn):
            with conn.cursor() as cur:
                cur.execute(f"{self._SELECT} WHERE email = %s", (normalized,))
                return cur.fetchone()

        return self._row_to_user(retrying(run))

    def delete(self, user_id: str) -> bool:
        def run(conn):
            with conn.cursor() as cur:
                cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
                return cur.rowcount > 0

        return retrying(run)

    def count(self) -> int:
        def run(conn):
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM users")
                return int(cur.fetchone()[0])

        return retrying(run)


# ------------------------------------------------------------ projects ------
class PostgresProjectStore:
    def save(self, project: Project) -> None:
        project.touch()
        record = project.model_dump(mode="json")
        size = (project.metadata.total_size_bytes if project.metadata else 0) or 0

        def run(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO projects (id, owner, name, source, status, origin,
                                          description, error, metadata, stats,
                                          upload_report, size_bytes,
                                          created_at, updated_at, record)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        owner = EXCLUDED.owner,
                        name = EXCLUDED.name,
                        source = EXCLUDED.source,
                        status = EXCLUDED.status,
                        origin = EXCLUDED.origin,
                        description = EXCLUDED.description,
                        error = EXCLUDED.error,
                        metadata = EXCLUDED.metadata,
                        stats = EXCLUDED.stats,
                        upload_report = EXCLUDED.upload_report,
                        size_bytes = EXCLUDED.size_bytes,
                        updated_at = EXCLUDED.updated_at,
                        record = EXCLUDED.record
                    """,
                    (
                        project.id,
                        project.owner,
                        project.name,
                        project.source.value,
                        project.status.value,
                        project.origin,
                        project.description,
                        project.error,
                        Jsonb(record.get("metadata")),
                        Jsonb(record.get("stats") or {}),
                        Jsonb(record.get("upload_report")),
                        size,
                        _ts(record["created_at"]),
                        _ts(record["updated_at"]),
                        Jsonb(record),
                    ),
                )

        retrying(run)

    def load(self, project_id: str) -> Project | None:
        if not project_id:
            return None

        def run(conn):
            with conn.cursor() as cur:
                cur.execute("SELECT record FROM projects WHERE id = %s", (project_id,))
                row = cur.fetchone()
                return row[0] if row else None

        return _model(Project, retrying(run), "project")

    def list(self, owner: str | None = None) -> list[Project]:
        def run(conn):
            with conn.cursor() as cur:
                if owner is None:
                    cur.execute("SELECT record FROM projects ORDER BY updated_at DESC")
                else:
                    cur.execute(
                        "SELECT record FROM projects WHERE owner = %s ORDER BY updated_at DESC",
                        (owner,),
                    )
                return [row[0] for row in cur.fetchall()]

        projects = [_model(Project, payload, "project") for payload in retrying(run)]
        return [project for project in projects if project is not None]

    def list_summaries(self, owner: str | None = None) -> list[ProjectSummary]:
        """The project list, without dragging every project's full record back.

        `record` is the whole Pydantic model as JSONB — for a large upload that
        includes every source path, every discovered route and the upload
        report, none of which the list view renders. This selects the promoted
        columns plus the two small pieces of `metadata` the summary needs, so
        the bytes crossing the wire are proportional to what is displayed.

        Ordering and filtering are done by the database against
        `projects_owner_updated_idx`; no row for another tenant is ever fetched.
        """
        def run(conn):
            with conn.cursor() as cur:
                sql = """
                    SELECT id, owner, name, source, status, origin,
                           created_at, updated_at, stats,
                           metadata->>'language',
                           metadata->>'framework',
                           coalesce(jsonb_array_length(metadata->'routes'), 0),
                           coalesce(metadata->'test_details', '[]'::jsonb)
                    FROM projects
                """
                if owner is None:
                    cur.execute(sql + " ORDER BY updated_at DESC")
                else:
                    cur.execute(sql + " WHERE owner = %s ORDER BY updated_at DESC", (owner,))
                return cur.fetchall()

        summaries: list[ProjectSummary] = []
        for row in retrying(run):
            (
                project_id, row_owner, name, source, status, origin,
                created_at, updated_at, stats, language, framework,
                route_count, test_details,
            ) = row
            try:
                summaries.append(
                    ProjectSummary(
                        id=project_id,
                        owner=row_owner,
                        name=name,
                        source=source,
                        status=status,
                        origin=origin,
                        created_at=created_at.isoformat(),
                        updated_at=updated_at.isoformat(),
                        language=language or "unknown",
                        framework=framework or "unknown",
                        route_count=int(route_count or 0),
                        test_count=sum(
                            int(entry.get("test_count") or 0)
                            for entry in (test_details or [])
                            if isinstance(entry, dict)
                        ),
                        stats=stats or {},
                    )
                )
            except Exception as exc:  # noqa: BLE001 - one bad row must not 500
                logger.warning("unreadable project summary %s: %s", project_id, exc)
        return summaries

    def delete(self, project_id: str) -> bool:
        # Sessions and executions cascade; the workspace on disk is removed by
        # the service, which owns the filesystem side.
        def run(conn):
            with conn.cursor() as cur:
                cur.execute("DELETE FROM projects WHERE id = %s", (project_id,))
                return cur.rowcount > 0

        return retrying(run)

    def storage_used(self, owner: str) -> int:
        """One SUM instead of loading every project to add up their sizes."""

        def run(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT coalesce(sum(size_bytes), 0) FROM projects WHERE owner = %s",
                    (owner,),
                )
                return int(cur.fetchone()[0])

        return retrying(run)

    def count_for(self, owner: str) -> int:
        def run(conn):
            with conn.cursor() as cur:
                cur.execute("SELECT count(*) FROM projects WHERE owner = %s", (owner,))
                return int(cur.fetchone()[0])

        return retrying(run)


# ---------------------------------------- repair sessions and executions ----
class PostgresRecordStore:
    """Repair sessions and execution records.

    Both were loose JSON files keyed by directory. In Postgres they are rows
    owned by a project, which is what makes "the newest session for this
    tenant" a query instead of a walk over every project directory on disk.
    """

    # ---- repair sessions ----
    def save_session(self, project_id: str, owner: str, session: RepairSession) -> None:
        record = session.model_dump(mode="json")

        def run(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO repair_sessions (id, project_id, owner, verdict, verified,
                                                 created_at, updated_at, record)
                    VALUES (%s, %s, %s, %s, %s, %s, now(), %s)
                    ON CONFLICT (id) DO UPDATE SET
                        verdict = EXCLUDED.verdict,
                        verified = EXCLUDED.verified,
                        updated_at = now(),
                        record = EXCLUDED.record
                    """,
                    (
                        session.id,
                        project_id,
                        owner,
                        session.verdict.value,
                        session.verified,
                        _ts(record.get("created_at")),
                        Jsonb(record),
                    ),
                )

        retrying(run)

    def load_session(self, project_id: str, session_id: str) -> RepairSession | None:
        def run(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT record FROM repair_sessions WHERE id = %s AND project_id = %s",
                    (session_id, project_id),
                )
                row = cur.fetchone()
                return row[0] if row else None

        return _model(RepairSession, retrying(run), "repair session")

    def find_session(self, session_id: str, owner: str | None) -> tuple[str, RepairSession] | None:
        """Locate a session by id alone, scoped to the tenant that owns it."""

        def run(conn):
            with conn.cursor() as cur:
                if owner is None:
                    cur.execute(
                        "SELECT project_id, record FROM repair_sessions WHERE id = %s",
                        (session_id,),
                    )
                else:
                    cur.execute(
                        "SELECT project_id, record FROM repair_sessions "
                        "WHERE id = %s AND owner = %s",
                        (session_id, owner),
                    )
                return cur.fetchone()

        row = retrying(run)
        if row is None:
            return None
        session = _model(RepairSession, row[1], "repair session")
        return (row[0], session) if session is not None else None

    def list_sessions(
        self, project_id: str | None, owner: str | None, limit: int
    ) -> list[RepairSession]:
        def run(conn):
            clauses, params = [], []
            if project_id is not None:
                clauses.append("project_id = %s")
                params.append(project_id)
            if owner is not None:
                clauses.append("owner = %s")
                params.append(owner)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            params.append(limit)
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT record FROM repair_sessions {where} "
                    "ORDER BY created_at DESC LIMIT %s",
                    tuple(params),
                )
                return [row[0] for row in cur.fetchall()]

        sessions = [_model(RepairSession, payload, "repair session") for payload in retrying(run)]
        return [session for session in sessions if session is not None]

    # ---- execution records ----
    def save_execution(self, project_id: str, owner: str, record: ExecutionRecord) -> None:
        payload = record.model_dump(mode="json")

        def run(conn):
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO executions (id, project_id, owner, created_at, record)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET record = EXCLUDED.record
                    """,
                    (
                        record.id,
                        project_id,
                        owner,
                        _ts(payload.get("created_at")),
                        Jsonb(payload),
                    ),
                )

        retrying(run)

    def list_executions(self, project_id: str, limit: int) -> list[ExecutionRecord]:
        def run(conn):
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT record FROM executions WHERE project_id = %s "
                    "ORDER BY created_at DESC LIMIT %s",
                    (project_id, limit),
                )
                return [row[0] for row in cur.fetchall()]

        records = [_model(ExecutionRecord, payload, "execution") for payload in retrying(run)]
        return [record for record in records if record is not None]
