"""HTTP API tests via FastAPI's TestClient."""

from __future__ import annotations

import io
import re
import time
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.config.settings import Settings, get_settings
from app.main import app
from app.services import repair_service
from app.services.project_service import ProjectService

from .conftest import reset_database, test_database_url, upload_fixture


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    """A TestClient wired to an isolated data directory."""
    reset_database()
    configured = Settings(
        database_url=test_database_url(),
        data_dir=tmp_path / "data",
        # Hermetic: never reach for the developer's real Redis, whose state
        # would persist across runs and across suites.
        redis_url=None,
        execution_mode="local",
        require_approval=False,
        openai_api_key=None,
        # These suites exercise project behaviour, not sign-in. Accounts have
        # their own suite in test_auth.py.
        auth_mode="open",
    )
    configured.ensure_directories()

    get_settings.cache_clear()
    monkeypatch.setattr("app.config.settings.get_settings", lambda: configured)
    monkeypatch.setattr("app.api.deps.get_settings", lambda: configured)
    # Lifespan publishes the running config to app.state, which the middleware
    # reads per request.
    monkeypatch.setattr("app.main.get_settings", lambda: configured)

    projects = ProjectService(configured)
    deps._project_service.cache_clear()
    monkeypatch.setattr(deps, "_project_service", lambda: projects)
    repair_service.reset_repair_service()

    app.dependency_overrides[deps.settings_dep] = lambda: configured
    app.dependency_overrides[deps.project_service] = lambda: projects
    with TestClient(app) as test_client:
        test_client.settings = configured           # type: ignore[attr-defined]
        test_client.projects = projects             # type: ignore[attr-defined]
        yield test_client
    app.dependency_overrides.clear()
    repair_service.reset_repair_service()
    get_settings.cache_clear()


def _zip_of(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, text in entries.items():
            zf.writestr(name, text)
    return buffer.getvalue()


# ---------------------------------------------------------------- health ---
def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_root(client):
    body = client.get("/").json()
    assert body["ai_provider"] == "openai"


def test_system_reports_configuration_without_secrets(client):
    body = client.get("/api/system").json()
    assert body["ai_provider"] == "openai"
    assert body["openai_model"]
    assert "openai_api_key" not in body
    assert body["openai_key_hint"] is None      # no key configured in tests
    assert body["execution_mode_resolved"] in {"docker", "local"}
    assert "sandbox" in body


def test_system_ai_status(client):
    body = client.get("/api/system/ai").json()
    assert body["provider"] == "openai"
    assert body["configured"] is False
    assert body["active_engine"] == "deterministic-offline"


def test_sandbox_endpoint_declares_isolation_honestly(client):
    body = client.get("/api/execution/sandbox").json()
    assert body["kind"] == "local"
    assert body["isolated"] is False
    assert "LOCAL TRUSTED MODE" in body["trusted_mode_banner"]
    assert body["warnings"]
    # A present Docker CLI must never be reported as a reachable sandbox.
    assert body["docker_daemon_reachable"] is False


def test_system_does_not_conflate_docker_cli_with_a_working_sandbox(client):
    body = client.get("/api/system").json()
    assert "docker_available" not in body, (
        "ambiguous field: the CLI can be installed while the daemon is down"
    )
    assert "docker_cli_present" in body
    # The authoritative isolation signal is the probed sandbox.
    assert body["sandbox"]["kind"] == "local"
    assert body["sandbox"]["isolated"] is False
    assert body["execution_isolated"] is False
    assert body["execution_mode_resolved"] == "local"


def test_env_example_documents_every_supported_setting():
    """`.env.example` is the reference; a setting missing from it is invisible."""
    example = Path(__file__).resolve().parents[2] / ".env.example"
    assert example.exists(), ".env.example is the documented way to configure this app"

    documented = set()
    for line in example.read_text(encoding="utf-8").splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if "=" in cleaned and cleaned.split("=")[0].strip().isupper():
            documented.add(cleaned.split("=")[0].strip())

    undocumented = sorted(
        name.upper() for name in Settings.model_fields if name.upper() not in documented
    )
    assert not undocumented, f"settings missing from .env.example: {undocumented}"


def test_env_example_contains_no_credentials():
    example = Path(__file__).resolve().parents[2] / ".env.example"
    text = example.read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9_\-]{12,}", text), "a real-looking key is committed"
    for secret_field in ("OPENAI_API_KEY", "API_KEYS", "ADMIN_API_KEYS"):
        for line in text.splitlines():
            if line.strip().startswith(f"{secret_field}="):
                assert line.strip() == f"{secret_field}=", (
                    f"{secret_field} must ship empty in the committed example"
                )


def test_copying_env_example_produces_a_valid_configuration(tmp_path, monkeypatch):
    """The file says "copy me and it works" — verify that is true.

    Blank optional values are the trap: a .env file cannot express None, so
    `CPU_POOL_WORKERS=` arrives as an empty string and used to fail int
    validation, crashing startup on a config the example itself recommends.
    """
    example = Path(__file__).resolve().parents[2] / ".env.example"
    target = tmp_path / ".env"
    target.write_text(example.read_text(encoding="utf-8"), encoding="utf-8")

    # Environment variables win over the file, so clear anything that would mask it.
    for name in list(Settings.model_fields):
        monkeypatch.delenv(name.upper(), raising=False)

    configured = Settings(_env_file=str(target))

    assert configured.openai_api_key is None       # blank key -> unset, not ""
    assert configured.cpu_pool_workers is None     # blank int -> default
    assert configured.io_pool_workers is None
    assert configured.redis_url is None
    assert configured.openai_model
    assert configured.max_concurrent_jobs > 0
    assert configured.require_approval is True
    # A copied example is development config, so it must pass its own checks.
    assert configured.app_env == "development"
    assert configured.validate_for_environment() == []


def test_isolation_is_never_claimed_from_configuration_alone():
    """A stopped Docker daemon must never be reported as an isolated sandbox.

    `resolve_execution_mode()` only sees the CLI on PATH, so the synchronous
    settings payload must default to the safe value and let a probe upgrade it.
    """
    configured = Settings(execution_mode="docker", openai_api_key=None)
    info = configured.public_system_info()

    assert configured.resolve_execution_mode() == "docker"     # the intent
    assert info["execution_mode_intended"] == "docker"
    # ...but nothing has been probed, so no isolation may be claimed.
    assert info["execution_isolated"] is False
    assert info["execution_mode_resolved"] == "local"


def test_execution_probe_is_cached_across_requests(client, monkeypatch):
    """The sidebar, banner and Settings page all ask on every navigation.

    Probing spawns a `docker version` subprocess, so an uncached probe meant
    four of them per page load — each waiting out a timeout when the daemon is
    down.
    """
    import asyncio

    from app.execution import sandbox as sandbox_module
    from app.runtime.cache import get_cache

    async def clear_caches() -> None:
        sandbox_module.reset_probe_cache()
        await get_cache().clear()

    asyncio.run(clear_caches())
    calls = {"n": 0}
    real = sandbox_module._probe_uncached          # noqa: SLF001 - test seam

    async def counting(settings):
        calls["n"] += 1
        return await real(settings)

    monkeypatch.setattr(sandbox_module, "_probe_uncached", counting)

    for _ in range(4):
        assert client.get("/api/system").status_code == 200
        assert client.get("/api/execution/sandbox").status_code == 200

    assert calls["n"] == 1, f"expected one probe for 8 requests, got {calls['n']}"

    asyncio.run(clear_caches())
    client.get("/api/system")
    assert calls["n"] == 2, "clearing the caches must force a fresh probe"


def test_dashboard_does_not_claim_isolation_before_anything_has_run(client):
    stats = client.get("/api/reports/dashboard").json()["stats"]
    assert stats["isolated_execution"] is False
    assert stats["execution_mode"] == "not yet determined"


def test_dashboard_reports_the_sandbox_actually_used(client):
    """After a run the dashboard reports the sandbox that really ran it.

    Asserted against the probe rather than a hard-coded mode, because whether
    the Docker daemon is up is a property of the machine, not of the code.
    """
    project_id = upload_fixture(client, "fastapi-keyerror").json()["id"]
    client.post(f"/api/execution/{project_id}/tests")

    actual = client.get("/api/execution/sandbox").json()
    stats = client.get("/api/reports/dashboard").json()["stats"]
    assert stats["execution_mode"] == actual["kind"]
    assert stats["isolated_execution"] == actual["isolated"]


# -------------------------------------------------------------- projects ---
def test_list_projects_is_empty(client):
    assert client.get("/api/projects").json() == []


def test_upload_zip_creates_and_analyzes_project(client):
    payload = _zip_of(
        {
            "main.py": "from fastapi import FastAPI\n\napp = FastAPI()\n\n\n"
                       "@app.get('/ping')\ndef ping():\n    return {'ok': True}\n",
            "tests/test_ping.py": "def test_ok():\n    assert True\n",
            "requirements.txt": "fastapi\n",
        }
    )
    response = client.post(
        "/api/projects/upload",
        files={"file": ("demo.zip", payload, "application/zip")},
    )
    assert response.status_code == 201, response.text
    project = response.json()
    assert project["metadata"]["framework"] == "fastapi"
    assert project["metadata"]["entry_point"] == "main.py"
    assert any(r["path"] == "/ping" for r in project["metadata"]["routes"])
    assert client.get("/api/projects").json()[0]["id"] == project["id"]


def test_upload_rejects_non_zip(client):
    response = client.post(
        "/api/projects/upload", files={"file": ("x.tar", b"not a zip", "application/x-tar")}
    )
    assert response.status_code == 400


def test_upload_rejects_traversal_archive(client):
    payload = _zip_of({"../../pwned.py": "print('pwned')"})
    response = client.post(
        "/api/projects/upload", files={"file": ("evil.zip", payload, "application/zip")}
    )
    assert response.status_code == 400
    assert "traversal" in response.json()["detail"].lower() or "unsafe" in response.json()["detail"].lower()


def test_remote_import_endpoint_is_gone(client):
    """A ZIP upload is the only ingestion path; nothing fetches remote code."""
    response = client.post("/api/projects/import/github", json={"url": "https://example.com/x/y"})
    assert response.status_code == 404


def test_get_missing_project_404(client):
    assert client.get("/api/projects/prj_nope").status_code == 404


def test_upload_project_and_browse_files(client):
    response = upload_fixture(client, "fastapi-keyerror")
    assert response.status_code == 201, response.text
    project = response.json()
    project_id = project["id"]

    tree = client.get(f"/api/projects/{project_id}/files").json()["tree"]
    names = {node["name"] for node in tree}
    assert "main.py" in names

    file_body = client.get(
        f"/api/projects/{project_id}/file", params={"path": "main.py"}
    ).json()
    assert file_body["language"] == "python"
    assert "FastAPI" in file_body["content"]

    routes = client.get(f"/api/projects/{project_id}/routes").json()
    assert any(r["path"] == "/users/{user_id}" for r in routes["routes"])


def test_file_read_rejects_traversal(client):
    project_id = upload_fixture(client, "fastapi-keyerror").json()["id"]
    response = client.get(
        f"/api/projects/{project_id}/file", params={"path": "../../../../etc/passwd"}
    )
    assert response.status_code in {400, 404}


def test_a_project_stored_before_the_demo_lab_was_removed_still_loads():
    """Removing the enum value must not make a user's projects disappear.

    `source: "demo"` is on disk for anyone who used the Demo Lab. Rejecting it
    dropped 23 real projects silently out of the list rather than loudly, which
    is exactly the failure mode a validation error is supposed to prevent.
    """
    from app.models.project import Project, ProjectSource

    project = Project.model_validate(
        {"id": "prj_legacy0000001", "name": "legacy", "source": "demo", "owner": "public"}
    )
    assert project.source is ProjectSource.UPLOAD


def test_demo_endpoints_are_gone(client):
    """The Demo Lab is not part of the product; nothing seeds sample data."""
    assert client.get("/api/demos").status_code == 404
    assert client.post("/api/demos/load", json={"slug": "fastapi-keyerror"}).status_code == 404


def test_delete_project(client):
    project_id = upload_fixture(client, "fastapi-keyerror").json()["id"]
    assert client.delete(f"/api/projects/{project_id}").json()["deleted"] is True
    assert client.get(f"/api/projects/{project_id}").status_code == 404


# ------------------------------------------------------------- execution ---
def test_run_tests_detects_seeded_failure(client):
    project_id = upload_fixture(client, "fastapi-keyerror").json()["id"]
    record = client.post(f"/api/execution/{project_id}/tests").json()
    assert record["mode"] == "test"
    assert record["healthy"] is False
    assert record["failure_count"] >= 1
    assert record["test_result"]["failed"] >= 1
    failure = record["test_result"]["failures"][0]
    assert failure["error_type"] == "KeyError"
    assert failure["file"] == "main.py"


def test_failures_endpoint(client):
    project_id = upload_fixture(client, "fastapi-keyerror").json()["id"]
    client.post(f"/api/execution/{project_id}/tests")
    failures = client.get(f"/api/diagnosis/{project_id}/failures").json()
    assert failures and failures[0]["error_type"] == "KeyError"


def test_diagnose_endpoint_is_read_only(client):
    project_id = upload_fixture(client, "fastapi-keyerror").json()["id"]
    workspace = client.projects.workspace(project_id)          # type: ignore[attr-defined]
    before = (workspace / "main.py").read_text(encoding="utf-8")

    client.post(f"/api/execution/{project_id}/tests")
    body = client.post(f"/api/diagnosis/{project_id}", json={}).json()

    assert body["reasoning_engine"] == "deterministic-offline"
    assert "username" in body["diagnosis"]["root_cause"]
    assert body["diagnosis"]["evidence"]
    assert body["observed_facts"]
    # Diagnosis must never write to the workspace.
    assert (workspace / "main.py").read_text(encoding="utf-8") == before


# ---------------------------------------------------------------- reports --
def test_dashboard_shape(client):
    body = client.get("/api/reports/dashboard").json()
    assert set(body) == {"stats", "recent_failures", "system"}
    assert body["stats"]["reasoning_engine"] == "deterministic-offline"
    assert body["system"]["ai_provider"] == "openai"


def test_history_empty(client):
    assert client.get("/api/reports/history").json()["entries"] == []


def test_report_for_missing_session_404(client):
    assert client.get("/api/reports/sessions/sess_nope").status_code == 404


# ----------------------------------------------------------------- events --
def test_event_history_records_project_creation(client):
    upload_fixture(client, "fastapi-keyerror")
    body = client.get("/api/events/history").json()
    assert body["count"] >= 1
    assert any(event["type"] == "project.created" for event in body["events"])


# ----------------------------------------------------------------- repair --
def test_full_repair_via_api_reaches_verified(client):
    project_id = upload_fixture(client, "fastapi-keyerror").json()["id"]
    started = client.post(
        f"/api/repair/{project_id}/start", json={"mode": "test", "auto_approve": True}
    )
    assert started.status_code == 200, started.text
    session_id = started.json()["id"]

    # The repair runs as a background task on the app's own event loop, which
    # TestClient drives from a worker thread — so poll from here rather than
    # trying to await it.
    repairs = deps.get_repair_service(client.settings, client.projects)   # type: ignore[attr-defined]
    deadline = time.monotonic() + 120
    while repairs.is_running(project_id) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not repairs.is_running(project_id), "repair did not finish within 120s"

    session = client.get(f"/api/repair/{project_id}/sessions/{session_id}").json()
    assert session["verdict"] == "verified", session.get("summary")
    assert session["attempts"][-1]["full_test"]["exit_code"] == 0

    # A finished repair is served from disk, not pinned in this process — two
    # workers holding different sessions is what makes the UI flicker.
    assert repairs.active_session(project_id) is None
    active = client.get(f"/api/repair/{project_id}/active").json()
    assert active["running"] is False
    assert active["session"]["id"] == session_id

    report = client.get(f"/api/reports/sessions/{session_id}").json()
    assert report["headline"] == "FIX VERIFIED"
    assert report["verified"] is True
    assert report["root_cause"]
    assert report["evidence"]
    assert report["diff"]
    assert "measured" in report["disclaimer"]

    markdown = client.get(f"/api/reports/sessions/{session_id}/markdown")
    assert markdown.status_code == 200
    assert "FIX VERIFIED" in markdown.text

    history = client.get("/api/reports/history").json()["entries"]
    assert history[0]["verified"] is True


def test_decision_on_unknown_patch_conflicts(client):
    project_id = upload_fixture(client, "fastapi-keyerror").json()["id"]
    response = client.post(
        f"/api/repair/{project_id}/patch/patch_nope/decision", json={"approve": True}
    )
    assert response.status_code == 409
