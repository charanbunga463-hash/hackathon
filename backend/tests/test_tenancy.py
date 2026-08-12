"""Multi-tenant isolation.

The failure these prevent is not a crash — it is user A quietly seeing,
repairing or deleting user B's source code. Every route that touches project
data is checked here, because one missed handler is a full leak.
"""

from __future__ import annotations

import io
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

KEY_A = "key-alpha-000000000000000000000"
KEY_B = "key-bravo-111111111111111111111"


@pytest.fixture
def tenant_client(tmp_path: Path, monkeypatch):
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
        auth_mode="apikey",
        api_keys=f"{KEY_A}:alpha,{KEY_B}:bravo",
        rate_limit_enabled=False,
    )
    configured.ensure_directories()

    get_settings.cache_clear()
    projects = ProjectService(configured)
    deps._project_service.cache_clear()
    monkeypatch.setattr(deps, "_project_service", lambda: projects)
    repair_service.reset_repair_service()

    app.dependency_overrides[deps.settings_dep] = lambda: configured
    app.dependency_overrides[deps.project_service] = lambda: projects
    # Middleware resolves settings from app.state per request, and lifespan sets
    # it from get_settings(), so patch the function main.py actually calls.
    monkeypatch.setattr("app.main.get_settings", lambda: configured)

    with TestClient(app) as client:
        client.settings = configured        # type: ignore[attr-defined]
        yield client

    app.dependency_overrides.clear()
    repair_service.reset_repair_service()
    get_settings.cache_clear()


def auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    return buffer.getvalue()


# --------------------------------------------------------------- auth -----
def test_unauthenticated_requests_are_refused(tenant_client):
    response = tenant_client.get("/api/projects")
    assert response.status_code == 401
    assert "bearer" in response.json()["detail"].lower()


def test_invalid_key_is_refused(tenant_client):
    response = tenant_client.get("/api/projects", headers=auth("not-a-real-key"))
    assert response.status_code == 401


def test_health_probes_stay_unauthenticated(tenant_client):
    # A load balancer cannot present credentials.
    assert tenant_client.get("/healthz").status_code == 200
    assert tenant_client.get("/api/health").status_code == 200
    assert tenant_client.get("/metrics").status_code == 200


# ------------------------------------------------------------ isolation ---
def test_listing_shows_only_your_own_projects(tenant_client):
    upload_fixture(tenant_client, "fastapi-keyerror", headers=auth(KEY_A))
    upload_fixture(tenant_client, "fastapi-billing", headers=auth(KEY_B))

    alpha = tenant_client.get("/api/projects", headers=auth(KEY_A)).json()
    bravo = tenant_client.get("/api/projects", headers=auth(KEY_B)).json()

    assert len(alpha) == 1 and len(bravo) == 1
    assert alpha[0]["owner"] == "alpha"
    assert bravo[0]["owner"] == "bravo"
    assert alpha[0]["id"] != bravo[0]["id"]


@pytest.mark.parametrize(
    "method,path_suffix",
    [
        ("get", ""),
        ("get", "/files"),
        ("get", "/routes"),
        ("get", "/file?path=main.py"),
        ("post", "/analyze"),
        ("delete", ""),
    ],
)
def test_another_tenant_cannot_touch_your_project(tenant_client, method, path_suffix):
    created = upload_fixture(tenant_client, "fastapi-keyerror", headers=auth(KEY_A)
    ).json()
    project_id = created["id"]

    response = getattr(tenant_client, method)(
        f"/api/projects/{project_id}{path_suffix}", headers=auth(KEY_B)
    )
    # 404 rather than 403: a distinct status would confirm the id exists.
    assert response.status_code == 404, f"{method.upper()} {path_suffix} leaked across tenants"

    # And the owner is unaffected.
    assert tenant_client.get(f"/api/projects/{project_id}", headers=auth(KEY_A)).status_code == 200


@pytest.mark.parametrize(
    "path_suffix",
    ["/tests", "/probe", "/history", "/latest"],
)
def test_execution_routes_are_tenant_scoped(tenant_client, path_suffix):
    created = upload_fixture(tenant_client, "fastapi-keyerror", headers=auth(KEY_A)
    ).json()
    method = tenant_client.post if path_suffix in {"/tests", "/probe"} else tenant_client.get
    response = method(f"/api/execution/{created['id']}{path_suffix}", headers=auth(KEY_B))
    assert response.status_code == 404


def test_repair_routes_are_tenant_scoped(tenant_client):
    created = upload_fixture(tenant_client, "fastapi-keyerror", headers=auth(KEY_A)
    ).json()
    project_id = created["id"]

    assert tenant_client.post(
        f"/api/repair/{project_id}/start", json={"mode": "test"}, headers=auth(KEY_B)
    ).status_code == 404
    assert tenant_client.get(
        f"/api/repair/{project_id}/active", headers=auth(KEY_B)
    ).status_code == 404
    assert tenant_client.post(
        f"/api/repair/{project_id}/patch/patch_x/decision",
        json={"approve": True}, headers=auth(KEY_B),
    ).status_code == 404


def test_diagnosis_is_tenant_scoped(tenant_client):
    created = upload_fixture(tenant_client, "fastapi-keyerror", headers=auth(KEY_A)
    ).json()
    assert tenant_client.get(
        f"/api/diagnosis/{created['id']}/failures", headers=auth(KEY_B)
    ).status_code == 404


def test_dashboard_and_history_are_tenant_scoped(tenant_client):
    upload_fixture(tenant_client, "fastapi-keyerror", headers=auth(KEY_A))

    alpha = tenant_client.get("/api/reports/dashboard", headers=auth(KEY_A)).json()
    bravo = tenant_client.get("/api/reports/dashboard", headers=auth(KEY_B)).json()
    assert alpha["stats"]["projects"] == 1
    assert bravo["stats"]["projects"] == 0

    assert tenant_client.get("/api/reports/history", headers=auth(KEY_B)).json()["entries"] == []


def test_uploaded_projects_are_owned_by_the_uploader(tenant_client):
    response = tenant_client.post(
        "/api/projects/upload",
        files={"file": ("p.zip", _zip(), "application/zip")},
        headers=auth(KEY_B),
    )
    assert response.status_code == 201
    assert response.json()["owner"] == "bravo"
    assert tenant_client.get("/api/projects", headers=auth(KEY_A)).json() == []


# -------------------------------------------------------------- quotas ----
def test_project_quota_is_enforced_per_tenant(tenant_client):
    tenant_client.settings.max_projects_per_tenant = 2   # type: ignore[attr-defined]

    for _ in range(2):
        assert upload_fixture(tenant_client, "fastapi-keyerror", headers=auth(KEY_A)
        ).status_code == 201

    blocked = upload_fixture(tenant_client, "fastapi-keyerror", headers=auth(KEY_A)
    )
    assert blocked.status_code == 402
    assert "limit reached" in blocked.json()["detail"]

    # The other tenant still has its own allowance.
    assert upload_fixture(tenant_client, "fastapi-keyerror", headers=auth(KEY_B)
    ).status_code == 201


def test_usage_endpoint_reports_this_tenant_only(tenant_client):
    upload_fixture(tenant_client, "fastapi-keyerror", headers=auth(KEY_A))
    usage = tenant_client.get("/api/projects/usage", headers=auth(KEY_A)).json()
    assert usage["tenant"] == "alpha"
    assert usage["projects"] == 1
    assert tenant_client.get("/api/projects/usage", headers=auth(KEY_B)).json()["projects"] == 0


# ------------------------------------------------------- request context --
def test_every_response_carries_a_request_id(tenant_client):
    response = tenant_client.get("/api/health")
    assert response.headers.get("X-Request-ID")


def test_supplied_request_id_is_echoed(tenant_client):
    response = tenant_client.get("/api/health", headers={"X-Request-ID": "trace-me-123"})
    assert response.headers["X-Request-ID"] == "trace-me-123"
