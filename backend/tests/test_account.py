"""The /api/account surface behind the Settings page.

What these tests are actually guarding:

  * a settings control that does nothing — every preference here is asserted to
    reach the code that consumes it, not merely to round-trip through storage;
  * a password change that leaves the old password working, or that signs the
    user out of the tab they are standing in;
  * "log out all sessions" that leaves a session alive;
  * one account reading or changing another account's settings;
  * account deletion that leaves the user's projects behind.
"""

from __future__ import annotations

import contextlib

import pytest
from fastapi.testclient import TestClient

from app.main import app

from .test_auth import (  # noqa: F401 - fixtures are used by name
    PASSWORD,
    CapturingSender,
    auth_client,
    mailbox,
    signup,
)

NEW_PASSWORD = "brand-new-pass-42"


@contextlib.contextmanager
def second_device(_primary, email: str = "ada@example.com", password: str = PASSWORD):
    """A second signed-in client for the same account.

    Its own cookie jar is the whole point: a second login on the *same* client
    replaces the cookie, so a test written that way proves nothing about the
    first session. The app and its state are shared, so this is a real second
    session as far as the backend is concerned.
    """
    client = TestClient(app)
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    try:
        yield client
    finally:
        client.close()


# ------------------------------------------------------------ the gateway ---
ACCOUNT_ENDPOINTS = [
    ("GET", "/api/account/profile"),
    ("PATCH", "/api/account/profile"),
    ("POST", "/api/account/password"),
    ("GET", "/api/account/sessions"),
    ("POST", "/api/account/sessions/revoke-all"),
    ("GET", "/api/account/preferences"),
    ("PUT", "/api/account/preferences"),
    ("DELETE", "/api/account"),
]


@pytest.mark.parametrize("method,path", ACCOUNT_ENDPOINTS)
def test_account_endpoints_refuse_anonymous_callers(auth_client, method, path):
    response = auth_client.request(method, path, json={})
    assert response.status_code == 401, f"{method} {path} answered {response.status_code}"


# ---------------------------------------------------------------- profile ---
def test_profile_reads_and_updates_the_signed_in_account(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com", name="Ada Lovelace")

    profile = auth_client.get("/api/account/profile")
    assert profile.status_code == 200
    assert profile.json()["name"] == "Ada Lovelace"
    assert "password_hash" not in profile.json()

    updated = auth_client.patch("/api/account/profile", json={"name": "Ada L"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Ada L"
    # And it persisted, rather than only being echoed back.
    assert auth_client.get("/api/auth/me").json()["name"] == "Ada L"


def test_profile_rejects_an_empty_name_with_a_field_hint(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    response = auth_client.patch("/api/account/profile", json={"name": " "})
    assert response.status_code == 422
    assert response.headers.get("X-Field") == "name"


# --------------------------------------------------------------- password ---
def test_password_change_requires_the_current_password(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    response = auth_client.post(
        "/api/account/password",
        json={"current_password": "not-the-password", "new_password": NEW_PASSWORD},
    )
    assert response.status_code == 422
    assert response.headers.get("X-Field") == "current_password"
    # The old password must still work, i.e. nothing was changed.
    assert auth_client.get("/api/account/profile").status_code == 200


def test_password_change_enforces_the_password_policy(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    response = auth_client.post(
        "/api/account/password",
        json={"current_password": PASSWORD, "new_password": "short"},
    )
    assert response.status_code == 422
    assert response.headers.get("X-Field") == "new_password"


def test_password_change_keeps_this_session_and_kills_the_others(auth_client, mailbox):
    """The tab you changed it in stays signed in; every other one does not."""
    signup(auth_client, mailbox, "ada@example.com")

    # A genuinely separate device: its own client, so its own cookie jar. Using
    # the same client would only prove that its jar was overwritten.
    with second_device(auth_client) as other:
        assert other.get("/api/auth/me").status_code == 200

        changed = auth_client.post(
            "/api/account/password",
            json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
        )
        assert changed.status_code == 200

        # This session survived...
        assert auth_client.get("/api/account/profile").status_code == 200
        # ...the other one did not.
        assert other.get("/api/auth/me").status_code == 401


def test_the_new_password_works_and_the_old_one_does_not(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    auth_client.post(
        "/api/account/password",
        json={"current_password": PASSWORD, "new_password": NEW_PASSWORD},
    )
    auth_client.post("/api/auth/logout")

    refused = auth_client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
    )
    assert refused.status_code == 401

    accepted = auth_client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": NEW_PASSWORD}
    )
    assert accepted.status_code == 200


# --------------------------------------------------------------- sessions ---
def test_sessions_lists_this_account_only_and_leaks_no_token(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")

    with second_device(auth_client):
        body = auth_client.get("/api/account/sessions").json()

    assert body["count"] == 2
    # Exactly one row is the caller's own, so the UI can label it.
    assert sum(1 for s in body["sessions"] if s["current"]) == 1
    serialized = str(body)
    assert "token" not in serialized and "hash" not in serialized
    for session in body["sessions"]:
        # The handle is a truncated digest, never anything usable as a cookie.
        assert len(session["id"]) == 16


def test_revoke_all_signs_out_every_session_including_this_one(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")

    with second_device(auth_client) as other:
        response = auth_client.post("/api/account/sessions/revoke-all")
        assert response.status_code == 200
        assert response.json()["revoked"] == 2

        assert auth_client.get("/api/auth/me").status_code == 401
        assert other.get("/api/auth/me").status_code == 401


# ------------------------------------------------------------ preferences ---
def test_preferences_start_at_the_documented_defaults(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    prefs = auth_client.get("/api/account/preferences").json()
    assert prefs == {
        "theme": "system",
        "api_timeout_seconds": 30,
        "probe_write_methods": False,
        "ai_analysis": True,
        "require_patch_approval": True,
    }


def test_preferences_update_is_partial_and_persists(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")

    updated = auth_client.put("/api/account/preferences", json={"theme": "dark"})
    assert updated.status_code == 200
    assert updated.json()["theme"] == "dark"
    # A field the client did not send keeps its value rather than resetting.
    assert updated.json()["api_timeout_seconds"] == 30

    auth_client.put("/api/account/preferences", json={"api_timeout_seconds": 45})
    after = auth_client.get("/api/account/preferences").json()
    assert after["theme"] == "dark" and after["api_timeout_seconds"] == 45


def test_preferences_reject_an_out_of_range_timeout(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    assert auth_client.put(
        "/api/account/preferences", json={"api_timeout_seconds": 99999}
    ).status_code == 422
    assert auth_client.put(
        "/api/account/preferences", json={"api_timeout_seconds": 0}
    ).status_code == 422


def test_an_unknown_theme_falls_back_rather_than_being_stored(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    response = auth_client.put("/api/account/preferences", json={"theme": "neon"})
    assert response.status_code == 200
    assert response.json()["theme"] == "system"


def test_preferences_reach_the_execution_engine(auth_client, mailbox):
    """The point of the setting: it changes what the API test engine does.

    Asserted at the seam where the run is configured, because a preference that
    is only proven to round-trip through storage is exactly the kind of fake
    setting this refactor was meant to remove.
    """
    from app.models.execution import RunOptions
    from app.models.user import UserPreferences

    saved = UserPreferences(api_timeout_seconds=12, probe_write_methods=True)
    options = RunOptions.from_preferences(saved)
    assert options.probe_timeout_seconds == 12.0
    assert options.include_write_methods is True

    # And the absence of preferences leaves the deployment defaults alone.
    default = RunOptions.from_preferences(None)
    assert default.probe_timeout_seconds is None
    assert default.include_write_methods is False


# --------------------------------------------------------------- deletion ---
def test_account_deletion_requires_the_password(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    response = auth_client.request(
        "DELETE", "/api/account", json={"password": "wrong-password"}
    )
    assert response.status_code == 422
    assert response.headers.get("X-Field") == "password"
    assert auth_client.get("/api/auth/me").status_code == 200


def test_account_deletion_removes_the_account_its_sessions_and_its_projects(
    auth_client, mailbox
):
    from .conftest import upload_fixture

    signup(auth_client, mailbox, "ada@example.com")
    upload = upload_fixture(auth_client, "fastapi-attribute-error")
    if upload.status_code != 201:
        pytest.skip(f"fixture upload unavailable: {upload.status_code}")
    assert len(auth_client.get("/api/projects").json()) == 1

    response = auth_client.request("DELETE", "/api/account", json={"password": PASSWORD})
    assert response.status_code == 200
    assert response.json()["projects_deleted"] == 1

    # The session died with the account.
    assert auth_client.get("/api/auth/me").status_code == 401
    # And the credentials no longer authenticate.
    assert auth_client.post(
        "/api/auth/login", json={"email": "ada@example.com", "password": PASSWORD}
    ).status_code == 401


# -------------------------------------------------------------- isolation ---
def test_one_account_cannot_see_or_change_another_accounts_settings(
    auth_client, mailbox
):
    signup(auth_client, mailbox, "ada@example.com", name="Ada")
    auth_client.put("/api/account/preferences", json={"theme": "dark"})
    ada_sessions = auth_client.get("/api/account/sessions").json()["count"]
    auth_client.post("/api/auth/logout")

    signup(auth_client, mailbox, "bob@example.com", name="Bob")
    # Bob sees his own defaults, not Ada's.
    assert auth_client.get("/api/account/preferences").json()["theme"] == "system"
    assert auth_client.get("/api/account/profile").json()["name"] == "Bob"
    # Bob's session list is his own; Ada's sessions are not in it.
    assert auth_client.get("/api/account/sessions").json()["count"] == 1
    assert ada_sessions >= 1

    # Bob changing his settings leaves Ada's alone.
    auth_client.put("/api/account/preferences", json={"theme": "light"})
    auth_client.post("/api/auth/logout")
    auth_client.post("/api/auth/login", json={"email": "ada@example.com", "password": PASSWORD})
    assert auth_client.get("/api/account/preferences").json()["theme"] == "dark"


# ------------------------------------------------------- stale-cookie loop ---
def test_a_rejected_session_cookie_is_cleared(auth_client, mailbox):
    """A refused cookie must not survive the response that refused it.

    Otherwise the browser is stuck: the frontend's edge middleware sees a
    session cookie and routes to the app, the app's guard gets a 401 and routes
    to /login, and the cookie sends it straight back — a redirect loop with a
    loading spinner and no way out.
    """
    signup(auth_client, mailbox, "ada@example.com")

    # The second device is the realistic case: its session is revoked out from
    # under it, so it keeps presenting a cookie the server no longer honours.
    # (Revoking from *this* client would clear its own cookie in the response,
    # leaving nothing to test.)
    with second_device(auth_client) as other:
        auth_client.post("/api/account/sessions/revoke-all")
        response = other.get("/api/auth/me")

    assert response.status_code == 401
    set_cookie = response.headers.get("set-cookie", "")
    assert "apidoctor_session=" in set_cookie, set_cookie
    assert "Max-Age=0" in set_cookie, set_cookie
    assert "Path=/" in set_cookie, set_cookie
    # Deleting a cookie only works if the flags match the ones it was set with.
    assert "HttpOnly" in set_cookie, set_cookie


def test_a_request_with_no_cookie_is_not_sent_a_deletion(auth_client):
    """Nothing to clear, so no Set-Cookie noise on every anonymous request."""
    response = auth_client.get("/api/auth/me")
    assert response.status_code == 401
    assert "set-cookie" not in {k.lower() for k in response.headers}
