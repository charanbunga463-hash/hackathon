"""Shared test fixtures.

`demo-projects/` is the test corpus of intentionally-broken FastAPI projects.
It is no longer a product feature — there is no Demo Lab and no demo endpoint —
so tests load a fixture the same way a real user would: by uploading a zip.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config.settings import Settings  # noqa: E402

DEMO_ROOT = REPO_ROOT / "demo-projects"

SKIP_IN_ZIP = {"__pycache__", ".pytest_cache", ".git"}


def test_database_url() -> str | None:
    """Run the suite against a real Postgres when one is offered.

    Unset, every suite uses the on-disk JSON stores and needs no services.
    Set `TEST_DATABASE_URL` and the *same* tests run with Postgres as the
    system of record, which is what proves the two backends behave alike:

        TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55432/apidoctor \\
            python -m pytest -q
    """
    return os.getenv("TEST_DATABASE_URL") or None


def reset_database() -> None:
    """Empty every table so one test cannot see another's rows.

    TRUNCATE rather than DROP: the schema is migrated once per session, and
    re-running migrations for each test would dominate the runtime.
    """
    url = test_database_url()
    if not url:
        return
    from app.db import init_database
    from app.db.pool import retrying

    init_database(url)

    def run(conn):
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE users, projects, repair_sessions, executions RESTART IDENTITY CASCADE"
            )

    retrying(run)


def fixture_zip(slug: str) -> bytes:
    """Zip a fixture project exactly as a user would upload it."""
    source = DEMO_ROOT / slug
    if not source.exists():
        pytest.skip(f"fixture project {slug} is not present")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(source.rglob("*")):
            if not path.is_file() or path.name in {"demo.json"} or path.suffix == ".pyc":
                continue
            if any(part in SKIP_IN_ZIP for part in path.relative_to(source).parts):
                continue
            zf.write(path, path.relative_to(source).as_posix())
    return buffer.getvalue()


def upload_fixture(client, slug: str, **kwargs):
    """POST a fixture project to the real upload endpoint."""
    return client.post(
        "/api/projects/upload",
        files={"file": (f"{slug}.zip", fixture_zip(slug), "application/zip")},
        **kwargs,
    )


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    reset_database()
    configured = Settings(
        database_url=test_database_url(),
        data_dir=tmp_path / "data",
        # Hermetic: never reach for the developer's real Redis, whose state
        # would persist across runs and across suites.
        redis_url=None,
        execution_mode="local",
        require_approval=False,
        max_repair_attempts=2,
        openai_api_key=None,
        # These suites exercise project behaviour, not sign-in. Accounts have
        # their own suite in test_auth.py.
        auth_mode="open",
    )
    configured.ensure_directories()
    return configured


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    target = tmp_path / "workspace"
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.fixture
def demo_workspace(tmp_path: Path):
    """Copy a demo project into an isolated workspace."""

    def _make(slug: str) -> Path:
        source = DEMO_ROOT / slug
        if not source.exists():
            pytest.skip(f"demo project {slug} is not present")
        target = tmp_path / slug
        shutil.copytree(
            source,
            target,
            ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc", "demo.json"),
        )
        return target

    return _make


@pytest.fixture
def sample_project(workspace: Path) -> Path:
    """A tiny FastAPI project used by analysis and patch tests."""
    (workspace / "main.py").write_text(
        '''from fastapi import FastAPI, HTTPException

app = FastAPI()

ITEMS = [{"id": 1, "label": "first"}]


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/items/{item_id}")
def get_item(item_id: int):
    for item in ITEMS:
        if item["id"] == item_id:
            return {"id": item["id"], "name": item["title"]}
    raise HTTPException(status_code=404, detail="not found")
''',
        encoding="utf-8",
    )
    (workspace / "requirements.txt").write_text("fastapi\npytest\n", encoding="utf-8")
    tests_dir = workspace / "tests"
    tests_dir.mkdir(exist_ok=True)
    (tests_dir / "test_items.py").write_text(
        '''def test_placeholder():
    assert True
''',
        encoding="utf-8",
    )
    return workspace
