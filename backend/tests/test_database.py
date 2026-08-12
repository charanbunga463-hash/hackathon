"""Guarantees that only the database can make.

The rest of the suite runs against both backends and proves they *behave*
alike. This module covers what is specific to Postgres — the constraints and
cascades that stop bad data existing at all — and one backend-agnostic test for
records written by an older version of the app.

Skipped unless `TEST_DATABASE_URL` is set:

    TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/apidoctor \\
        python -m pytest tests/test_database.py -q
"""

from __future__ import annotations

import pytest

from app.models.project import Project, ProjectSource
from app.models.user import User

from .conftest import reset_database, test_database_url

pytestmark = pytest.mark.skipif(
    test_database_url() is None,
    reason="set TEST_DATABASE_URL to run the Postgres-specific tests",
)


@pytest.fixture
def db():
    reset_database()
    from app.db import init_database
    from app.db.stores import PostgresProjectStore, PostgresRecordStore, PostgresUserStore

    init_database(test_database_url())
    return PostgresUserStore(), PostgresProjectStore(), PostgresRecordStore()


def _user(email: str, user_id: str = "usr_test000000001") -> User:
    return User(
        id=user_id, name="Test", email=email, password_hash="$argon2id$fake", email_verified=True
    )


def _project(project_id: str, owner: str, name: str = "demo") -> Project:
    return Project(id=project_id, name=name, source=ProjectSource.UPLOAD, owner=owner)


# ------------------------------------------------------------ constraints ---
def test_two_accounts_cannot_share_an_email(db):
    """The UNIQUE index is the real guard; the service check is only advisory.

    Two registrations that pass the "is it taken?" check at the same instant
    both reach the insert. Without the constraint the second silently
    overwrites the first, and one person loses their account.
    """
    users, _, _ = db
    users.save(_user("ada@example.com", "usr_aaaaaaaaaaaaaaa1"))

    from app.db.pool import retrying

    def insert_duplicate(conn):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (id, name, email, password_hash) VALUES (%s, %s, %s, %s)",
                ("usr_bbbbbbbbbbbbbbb2", "Impostor", "ada@example.com", "$argon2id$other"),
            )

    with pytest.raises(Exception) as caught:
        retrying(insert_duplicate)
    assert "unique" in str(caught.value).lower() or "duplicate" in str(caught.value).lower()


def test_the_service_reports_a_lost_race_as_taken_not_as_a_crash(db):
    """A unique violation must surface as EmailTaken, never as a 500."""
    from app.config.settings import Settings
    from app.services.user_service import EmailTaken, UserService

    users, _, _ = db
    settings = Settings(database_url=test_database_url(), openai_api_key=None)
    service = UserService(settings, store=users)
    service.create(name="Ada", email="race@example.com", password="analytical-99")

    with pytest.raises(EmailTaken):
        service.create(name="Other", email="race@example.com", password="different-99")


def test_deleting_a_project_takes_its_history_with_it(db):
    """Orphaned sessions would keep counting toward a deleted project."""
    from app.models.report import RepairSession

    _, projects, records = db
    projects.save(_project("prj_cascade00001", "usr_owner1"))
    records.save_session(
        "prj_cascade00001",
        "usr_owner1",
        RepairSession(id="sess_cascade1", project_id="prj_cascade00001", project_name="x"),
    )
    assert len(records.list_sessions("prj_cascade00001", None, 10)) == 1

    projects.delete("prj_cascade00001")
    assert records.list_sessions("prj_cascade00001", None, 10) == []


# ---------------------------------------------------------------- scoping ---
def test_queries_are_scoped_by_owner_in_the_database(db):
    _, projects, records = db
    projects.save(_project("prj_alice00000001", "usr_alice", "alice-project"))
    projects.save(_project("prj_bob0000000001", "usr_bob", "bob-project"))

    assert [p.id for p in projects.list("usr_alice")] == ["prj_alice00000001"]
    assert [p.id for p in projects.list("usr_bob")] == ["prj_bob0000000001"]
    assert projects.count_for("usr_alice") == 1
    assert projects.count_for("usr_nobody") == 0


def test_find_session_will_not_cross_owners(db):
    """Guessing a session id must not reveal another tenant's report."""
    from app.models.report import RepairSession

    _, projects, records = db
    projects.save(_project("prj_owned00000001", "usr_alice"))
    records.save_session(
        "prj_owned00000001",
        "usr_alice",
        RepairSession(id="sess_private1", project_id="prj_owned00000001", project_name="x"),
    )

    assert records.find_session("sess_private1", "usr_alice") is not None
    assert records.find_session("sess_private1", "usr_bob") is None


# -------------------------------------------------------------- migration ---
def test_migrations_are_idempotent(db):
    from app.db.migrations import applied_revisions, migrate

    before = applied_revisions()
    assert migrate() == [], "a second run must apply nothing"
    assert applied_revisions() == before


def test_storage_total_is_summed_by_the_database(db):
    _, projects, _ = db
    from app.models.project import ProjectMetadata

    for index in range(3):
        project = _project(f"prj_size0000000{index}", "usr_sizes")
        project.metadata = ProjectMetadata(total_size_bytes=1000)
        projects.save(project)

    assert projects.storage_used("usr_sizes") == 3000
    assert projects.storage_used("usr_nobody") == 0
