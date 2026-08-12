"""Accounts: registration, OTP, sign-in, password reset, and isolation.

The failures these prevent are not crashes. They are: an unauthenticated
caller reading someone's source, one account seeing another's projects, a
replayed OTP, a password reset that leaves old sessions alive, and a login
form that tells an attacker which addresses are registered.

The email transport is replaced with a capturing fake, because the code only
ever exists in the message body — it is never in a response, so there is no
other way for a test (or an attacker) to learn it.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api import deps
from app.config.settings import Settings, get_settings
from app.main import app
from app.services import email_service, otp_service, repair_service, session_service
from app.services import user_service as user_service_module
from app.services.project_service import ProjectService

from .conftest import reset_database, test_database_url, upload_fixture

PASSWORD = "correct-horse-9"
OTHER_PASSWORD = "battery-staple-7"


class CapturingSender:
    """Stands in for SMTP; records what would have been delivered."""

    name = "capture"

    def __init__(self) -> None:
        self.messages: list[dict] = []

    def send(self, *, to: str, subject: str, text: str, html: str | None = None) -> None:
        self.messages.append({"to": to, "subject": subject, "text": text})

    def latest_code(self, to: str) -> str:
        for message in reversed(self.messages):
            if message["to"] == to:
                match = re.search(r"\b(\d{6})\b", message["text"])
                if match:
                    return match.group(1)
        raise AssertionError(f"no code was sent to {to}: {self.messages}")


async def _reset_state() -> None:
    from app.runtime.state import reset_state_backend

    await reset_state_backend()


@pytest.fixture
def mailbox() -> CapturingSender:
    return CapturingSender()


@pytest.fixture
def auth_client(tmp_path: Path, monkeypatch, mailbox: CapturingSender):
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
        auth_mode="user",
        secret_key="k" * 48,
        rate_limit_enabled=False,
        otp_resend_cooldown_seconds=0,
    )
    configured.ensure_directories()

    get_settings.cache_clear()
    monkeypatch.setattr("app.config.settings.get_settings", lambda: configured)
    monkeypatch.setattr("app.api.deps.get_settings", lambda: configured)
    monkeypatch.setattr("app.main.get_settings", lambda: configured)

    projects = ProjectService(configured)
    deps._project_service.cache_clear()
    monkeypatch.setattr(deps, "_project_service", lambda: projects)

    for module in (repair_service, user_service_module, otp_service, session_service):
        getattr(module, f"reset_{module.__name__.rsplit('.', 1)[-1]}")()
    email_service.reset_email_service()
    email_service._service = email_service.EmailService(configured, mailbox)

    # Sessions, codes and their counters all live in the state backend, so a
    # leftover one from the previous test would leak into this one.
    import asyncio

    asyncio.run(_reset_state())

    app.dependency_overrides[deps.settings_dep] = lambda: configured
    app.dependency_overrides[deps.project_service] = lambda: projects
    with TestClient(app) as client:
        client.settings = configured        # type: ignore[attr-defined]
        yield client

    app.dependency_overrides.clear()
    for module in (repair_service, user_service_module, otp_service, session_service):
        getattr(module, f"reset_{module.__name__.rsplit('.', 1)[-1]}")()
    email_service.reset_email_service()
    get_settings.cache_clear()


def signup(client: TestClient, mailbox: CapturingSender, email: str, *, name: str = "Test User"):
    """Register and verify, leaving the client signed in."""
    response = client.post(
        "/api/auth/register", json={"name": name, "email": email, "password": PASSWORD}
    )
    assert response.status_code == 201, response.text
    code = mailbox.latest_code(email)
    verified = client.post("/api/auth/verify-otp", json={"email": email, "code": code})
    assert verified.status_code == 200, verified.text
    return verified.json()["user"]


# ------------------------------------------------------------ the gateway ---
PROTECTED = [
    ("GET", "/api/projects"),
    ("GET", "/api/projects/prj_anything"),
    ("DELETE", "/api/projects/prj_anything"),
    ("GET", "/api/projects/usage"),
    ("GET", "/api/reports/dashboard"),
    ("GET", "/api/reports/history"),
    ("GET", "/api/events/history"),
    ("GET", "/api/execution/queue"),
    ("POST", "/api/repair/prj_anything/start"),
    ("GET", "/api/auth/me"),
]


@pytest.mark.parametrize("method,path", PROTECTED)
def test_protected_endpoints_refuse_anonymous_callers(auth_client, method, path):
    response = auth_client.request(method, path, json={})
    assert response.status_code == 401, f"{method} {path} answered {response.status_code}"


def test_public_auth_endpoints_are_reachable_without_a_session(auth_client):
    assert auth_client.get("/api/auth/config").status_code == 200
    assert auth_client.post("/api/auth/login", json={"email": "", "password": ""}).status_code == 401


def test_removed_demo_endpoints_stay_removed(auth_client):
    assert auth_client.get("/api/demos").status_code in {401, 404}


# ----------------------------------------------------------- registration ---
def test_register_verify_and_land_on_an_empty_workspace(auth_client, mailbox):
    user = signup(auth_client, mailbox, "ada@example.com", name="Ada Lovelace")
    assert user["email"] == "ada@example.com"
    assert user["email_verified"] is True
    assert "password" not in user and "password_hash" not in user

    assert auth_client.get("/api/projects").json() == []
    dashboard = auth_client.get("/api/reports/dashboard").json()
    assert dashboard["stats"]["projects"] == 0
    assert dashboard["recent_failures"] == []
    assert auth_client.get("/api/reports/history").json()["entries"] == []


def test_registration_never_returns_the_code(auth_client, mailbox):
    response = auth_client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": "ada@example.com", "password": PASSWORD},
    )
    code = mailbox.latest_code("ada@example.com")
    assert code not in response.text
    assert "otp" not in response.text.lower()


def test_duplicate_registration_does_not_disclose_the_account(auth_client, mailbox):
    first = auth_client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": "ada@example.com", "password": PASSWORD},
    )
    second = auth_client.post(
        "/api/auth/register",
        json={"name": "Impostor", "email": "ada@example.com", "password": "different-999"},
    )
    assert second.status_code == first.status_code
    assert second.json()["status"] == first.json()["status"]

    # The original account is untouched: the first password still works and the
    # second one does not.
    code = mailbox.latest_code("ada@example.com")
    auth_client.post("/api/auth/verify-otp", json={"email": "ada@example.com", "code": code})
    auth_client.post("/api/auth/logout")
    assert auth_client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "different-999"}
    ).status_code == 401
    assert auth_client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
    ).status_code == 200


@pytest.mark.parametrize(
    "field,payload",
    [
        ("name", {"name": "A", "email": "a@example.com", "password": PASSWORD}),
        ("email", {"name": "Ada", "email": "not-an-email", "password": PASSWORD}),
        ("password", {"name": "Ada", "email": "a@example.com", "password": "short1"}),
        ("password", {"name": "Ada", "email": "a@example.com", "password": "nodigitshere"}),
    ],
)
def test_registration_validates_server_side(auth_client, field, payload):
    response = auth_client.post("/api/auth/register", json=payload)
    assert response.status_code == 422
    assert response.headers.get("X-Field") == field


# ------------------------------------------------------------------- otp ---
def test_wrong_code_is_rejected_and_the_right_one_still_works(auth_client, mailbox):
    auth_client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": "ada@example.com", "password": PASSWORD},
    )
    bad = auth_client.post(
        "/api/auth/verify-otp", json={"email": "ada@example.com", "code": "000000"}
    )
    assert bad.status_code == 400
    assert "not correct" in bad.json()["detail"]

    code = mailbox.latest_code("ada@example.com")
    assert auth_client.post(
        "/api/auth/verify-otp", json={"email": "ada@example.com", "code": code}
    ).status_code == 200


def test_a_code_cannot_be_used_twice(auth_client, mailbox):
    auth_client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": "ada@example.com", "password": PASSWORD},
    )
    code = mailbox.latest_code("ada@example.com")
    assert auth_client.post(
        "/api/auth/verify-otp", json={"email": "ada@example.com", "code": code}
    ).status_code == 200

    replay = auth_client.post(
        "/api/auth/verify-otp", json={"email": "ada@example.com", "code": code}
    )
    assert replay.status_code == 400
    assert "already used" in replay.json()["detail"]


def test_repeated_wrong_codes_burn_the_code(auth_client, mailbox):
    auth_client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": "ada@example.com", "password": PASSWORD},
    )
    code = mailbox.latest_code("ada@example.com")
    limit = auth_client.settings.otp_max_attempts     # type: ignore[attr-defined]

    for _ in range(limit + 1):
        auth_client.post(
            "/api/auth/verify-otp", json={"email": "ada@example.com", "code": "111111"}
        )

    # Past the budget even the correct code is refused: it was invalidated.
    final = auth_client.post(
        "/api/auth/verify-otp", json={"email": "ada@example.com", "code": code}
    )
    assert final.status_code == 400
    assert "expired or was already used" in final.json()["detail"]


def test_an_expired_code_is_refused(auth_client, mailbox, monkeypatch):
    """TTL is the expiry mechanism, so dropping the key is a real expiry."""
    auth_client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": "ada@example.com", "password": PASSWORD},
    )
    code = mailbox.latest_code("ada@example.com")

    import asyncio

    from app.runtime.state import get_state_backend
    from app.services.otp_service import get_otp_service

    otps = get_otp_service(auth_client.settings)         # type: ignore[attr-defined]
    key = otps._code_key("verify", "ada@example.com")    # noqa: SLF001
    asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        get_state_backend().delete(key)
    )

    response = auth_client.post(
        "/api/auth/verify-otp", json={"email": "ada@example.com", "code": code}
    )
    assert response.status_code == 400
    assert "expired" in response.json()["detail"]


def test_resend_gives_a_fresh_working_code(auth_client, mailbox):
    auth_client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": "ada@example.com", "password": PASSWORD},
    )
    first = mailbox.latest_code("ada@example.com")
    assert auth_client.post(
        "/api/auth/resend-otp", json={"email": "ada@example.com", "purpose": "verify"}
    ).status_code == 200
    second = mailbox.latest_code("ada@example.com")

    assert auth_client.post(
        "/api/auth/verify-otp", json={"email": "ada@example.com", "code": first}
    ).status_code == 400
    assert auth_client.post(
        "/api/auth/verify-otp", json={"email": "ada@example.com", "code": second}
    ).status_code == 200


def test_resend_to_an_unknown_address_sends_nothing_but_says_the_same(auth_client, mailbox):
    response = auth_client.post(
        "/api/auth/resend-otp", json={"email": "nobody@example.com", "purpose": "verify"}
    )
    assert response.status_code == 200
    assert not [m for m in mailbox.messages if m["to"] == "nobody@example.com"]


def test_resend_cooldown_is_enforced(tmp_path, monkeypatch, mailbox):
    """The cooldown is disabled in the shared fixture, so configure it here."""
    from app.services.otp_service import OtpService, ResendTooSoon

    configured = Settings(
        data_dir=tmp_path / "data",
        # Hermetic: never reach for the developer's real Redis, whose state
        # would persist across runs and across suites.
        redis_url=None,
        auth_mode="user",
        secret_key="k" * 48,
        otp_resend_cooldown_seconds=60,
        openai_api_key=None,
    )
    otps = OtpService(configured)

    import asyncio

    async def scenario():
        await otps.issue("verify", "ada@example.com")
        with pytest.raises(ResendTooSoon):
            await otps.issue("verify", "ada@example.com")

    asyncio.run(scenario())


# ----------------------------------------------------------------- login ---
def test_login_and_logout(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    assert auth_client.post("/api/auth/logout").status_code == 200
    assert auth_client.get("/api/projects").status_code == 401

    assert auth_client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
    ).status_code == 200
    assert auth_client.get("/api/projects").status_code == 200


def test_wrong_password_and_unknown_account_are_indistinguishable(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    auth_client.post("/api/auth/logout")

    wrong = auth_client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": "not-the-password-1"}
    )
    unknown = auth_client.post(
        "/api/auth/login", json={"email": "ghost@example.com", "password": "not-the-password-1"}
    )
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json()["detail"] == unknown.json()["detail"]


def test_an_unverified_account_cannot_sign_in(auth_client, mailbox):
    auth_client.post(
        "/api/auth/register",
        json={"name": "Ada", "email": "ada@example.com", "password": PASSWORD},
    )
    response = auth_client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json()["status"] == "verification_required"
    # No session was issued, so the app is still closed.
    assert auth_client.get("/api/projects").status_code == 401


def test_logout_invalidates_the_session_server_side(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    stolen = auth_client.cookies.get("apidoctor_session")
    auth_client.post("/api/auth/logout")

    # Replaying the cookie after logout must fail: the record is gone.
    auth_client.cookies.set("apidoctor_session", stolen)
    assert auth_client.get("/api/projects").status_code == 401


def test_a_session_survives_a_page_reload(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    for _ in range(3):
        assert auth_client.get("/api/auth/me").status_code == 200


# -------------------------------------------------------- password reset ---
def test_forgot_password_end_to_end(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    auth_client.post("/api/auth/logout")

    assert auth_client.post(
        "/api/auth/forgot-password", json={"email": "ada@example.com"}
    ).status_code == 200
    code = mailbox.latest_code("ada@example.com")

    verified = auth_client.post(
        "/api/auth/verify-reset-otp", json={"email": "ada@example.com", "code": code}
    )
    assert verified.status_code == 200
    ticket = verified.json()["ticket"]

    reset = auth_client.post(
        "/api/auth/reset-password", json={"ticket": ticket, "password": OTHER_PASSWORD}
    )
    assert reset.status_code == 200

    assert auth_client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
    ).status_code == 401
    assert auth_client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": OTHER_PASSWORD}
    ).status_code == 200


def test_forgot_password_does_not_reveal_whether_the_account_exists(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    auth_client.post("/api/auth/logout")

    known = auth_client.post("/api/auth/forgot-password", json={"email": "ada@example.com"})
    unknown = auth_client.post("/api/auth/forgot-password", json={"email": "ghost@example.com"})
    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()
    assert not [m for m in mailbox.messages if m["to"] == "ghost@example.com"]


def test_a_reset_ticket_is_single_use(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    auth_client.post("/api/auth/logout")
    auth_client.post("/api/auth/forgot-password", json={"email": "ada@example.com"})
    code = mailbox.latest_code("ada@example.com")
    ticket = auth_client.post(
        "/api/auth/verify-reset-otp", json={"email": "ada@example.com", "code": code}
    ).json()["ticket"]

    assert auth_client.post(
        "/api/auth/reset-password", json={"ticket": ticket, "password": OTHER_PASSWORD}
    ).status_code == 200
    replay = auth_client.post(
        "/api/auth/reset-password", json={"ticket": ticket, "password": "third-password-3"}
    )
    assert replay.status_code == 400


def test_reset_password_refuses_a_forged_ticket(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    response = auth_client.post(
        "/api/auth/reset-password", json={"ticket": "made-up", "password": OTHER_PASSWORD}
    )
    assert response.status_code == 400


def test_reset_signs_out_every_existing_session(auth_client, mailbox):
    """A reset is how you recover a compromised account; old cookies must die."""
    signup(auth_client, mailbox, "ada@example.com")
    old_cookie = auth_client.cookies.get("apidoctor_session")
    assert auth_client.get("/api/auth/me").status_code == 200

    auth_client.post("/api/auth/forgot-password", json={"email": "ada@example.com"})
    code = mailbox.latest_code("ada@example.com")
    ticket = auth_client.post(
        "/api/auth/verify-reset-otp", json={"email": "ada@example.com", "code": code}
    ).json()["ticket"]
    auth_client.post(
        "/api/auth/reset-password", json={"ticket": ticket, "password": OTHER_PASSWORD}
    )

    auth_client.cookies.set("apidoctor_session", old_cookie)
    assert auth_client.get("/api/auth/me").status_code == 401


# ------------------------------------------------------------- isolation ---
def test_one_user_cannot_see_or_touch_another_users_projects(auth_client, mailbox):
    signup(auth_client, mailbox, "alice@example.com", name="Alice")
    alice_project = upload_fixture(auth_client, "fastapi-keyerror").json()["id"]
    assert len(auth_client.get("/api/projects").json()) == 1
    auth_client.post("/api/auth/logout")

    signup(auth_client, mailbox, "bob@example.com", name="Bob")
    # A brand-new account starts empty, whatever anyone else has uploaded.
    assert auth_client.get("/api/projects").json() == []

    bob_project = upload_fixture(auth_client, "fastapi-billing").json()["id"]
    assert {p["id"] for p in auth_client.get("/api/projects").json()} == {bob_project}

    # Guessing the id gets Bob nothing: not-found and not-yours look identical.
    assert auth_client.get(f"/api/projects/{alice_project}").status_code == 404
    assert auth_client.delete(f"/api/projects/{alice_project}").status_code == 404
    assert auth_client.get(f"/api/projects/{alice_project}/files").status_code == 404
    assert auth_client.get(
        f"/api/projects/{alice_project}/file", params={"path": "main.py"}
    ).status_code == 404
    assert auth_client.post(f"/api/projects/{alice_project}/analyze").status_code == 404
    assert auth_client.post(f"/api/repair/{alice_project}/start", json={}).status_code == 404
    assert auth_client.post(f"/api/execution/{alice_project}/tests").status_code == 404

    # Aggregates are per-account too.
    assert auth_client.get("/api/reports/dashboard").json()["stats"]["projects"] == 1

    # And Alice still has hers.
    auth_client.post("/api/auth/logout")
    auth_client.post("/api/auth/login", json={"email": "alice@example.com", "password": PASSWORD})
    assert {p["id"] for p in auth_client.get("/api/projects").json()} == {alice_project}


def test_events_are_scoped_to_the_account_that_produced_them(auth_client, mailbox):
    """The SSE replay buffer is shared by every client, so it must be filtered."""
    signup(auth_client, mailbox, "alice@example.com", name="Alice")
    upload_fixture(auth_client, "fastapi-keyerror")
    alice_events = auth_client.get("/api/events/history").json()
    assert alice_events["count"] > 0
    auth_client.post("/api/auth/logout")

    signup(auth_client, mailbox, "bob@example.com", name="Bob")
    bob_events = auth_client.get("/api/events/history").json()
    assert bob_events["count"] == 0, "Bob can see Alice's activity feed"
    assert "fastapi-keyerror" not in str(bob_events)


def test_the_stored_record_never_exposes_the_password(auth_client, mailbox):
    """Whichever backend is storing it, the plaintext must not be there."""
    signup(auth_client, mailbox, "ada@example.com")
    settings = auth_client.settings                 # type: ignore[attr-defined]

    if settings.database_url:
        from app.db.pool import retrying

        def read(conn):
            with conn.cursor() as cur:
                cur.execute("SELECT password_hash FROM users WHERE email = %s", ("ada@example.com",))
                return cur.fetchone()

        row = retrying(read)
        assert row, "the account was not persisted"
        stored = row[0]
    else:
        records = list(settings.users_dir.glob("*.json"))
        assert records, "the account was not persisted"
        stored = records[0].read_text(encoding="utf-8")

    assert PASSWORD not in stored
    assert "$argon2id$" in stored, "the password must be stored as an Argon2id hash"

    me = auth_client.get("/api/auth/me").json()
    assert "password_hash" not in me and "password" not in me
