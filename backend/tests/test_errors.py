"""The error contract.

Two things are being protected here.

**Shape.** Every failure, from any layer — the ASGI gateway, request validation,
a route's HTTPException, an unhandled crash — carries `success: false` and an
`error` object with a stable `code`. A client that switches on `error.code`
must not have to special-case which layer produced the response.

**Silence.** A 5xx never carries the exception's own text. Stack traces, file
paths, connection strings and credentials are logged against a request id and
answered with a fixed sentence, because a message written for a developer is a
message written for an attacker too.
"""

from __future__ import annotations

import pytest

from app.api.errors import SAFE_STATUS, envelope, error_code

from .test_auth import (  # noqa: F401 - fixtures are used by name
    PASSWORD,
    CapturingSender,
    auth_client,
    mailbox,
    signup,
)


def assert_envelope(body: dict, code: str | None = None) -> None:
    assert body["success"] is False, body
    assert isinstance(body.get("error"), dict), body
    assert isinstance(body["error"].get("code"), str) and body["error"]["code"], body
    assert isinstance(body["error"].get("message"), str) and body["error"]["message"], body
    # `detail` is kept for existing clients and must agree with the envelope.
    assert body["detail"] == body["error"]["message"], body
    if code:
        assert body["error"]["code"] == code, body


# ------------------------------------------------------------------ shape ---
def test_unauthenticated_request_uses_the_envelope(auth_client):
    response = auth_client.get("/api/projects")
    assert response.status_code == 401
    assert_envelope(response.json(), "UNAUTHENTICATED")


def test_not_found_uses_the_envelope(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    response = auth_client.get("/api/projects/prj_does_not_exist")
    assert response.status_code == 404
    assert_envelope(response.json(), "NOT_FOUND")


def test_validation_failure_names_the_field(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    # `api_timeout_seconds` is bounded at 300 by the request model.
    response = auth_client.put(
        "/api/account/preferences", json={"api_timeout_seconds": 10**6}
    )
    assert response.status_code == 422
    assert_envelope(response.json(), "VALIDATION_FAILED")
    # The form needs to know which input to highlight.
    assert response.headers.get("X-Field") == "api_timeout_seconds"


def test_route_raised_field_errors_keep_their_header_and_envelope(auth_client, mailbox):
    signup(auth_client, mailbox, "ada@example.com")
    response = auth_client.patch("/api/account/profile", json={"name": ""})
    assert response.status_code == 422
    assert_envelope(response.json())
    assert response.headers.get("X-Field") == "name"


def test_rate_limit_envelope_carries_retry_after(auth_client, monkeypatch):
    """The gateway answers before the router, and still uses the envelope."""
    from app.runtime import ratelimit

    limiter = ratelimit.get_rate_limiter()

    async def always_limited(_tenant, _bucket):
        return ratelimit.RateDecision(
            allowed=False, remaining=0, retry_after=7, limit=10
        )

    monkeypatch.setattr(limiter, "check", always_limited)

    response = auth_client.post("/api/auth/login", json={"email": "a@b.co", "password": "x"})
    assert response.status_code == 429
    body = response.json()
    assert_envelope(body, "RATE_LIMITED")
    assert body["retry_after"] == 7
    assert response.headers.get("Retry-After")


# ---------------------------------------------------------------- silence ---
def test_a_crash_reveals_nothing_but_a_request_id(auth_client, mailbox, monkeypatch):
    """An unhandled exception must not put its message in the response."""
    signup(auth_client, mailbox, "ada@example.com")

    secret = "postgresql://user:hunter2@db.internal:5432/prod"

    def explode(*_args, **_kwargs):
        raise RuntimeError(f"connection failed for {secret} at /srv/app/db/pool.py:88")

    from app.services.user_service import UserService

    monkeypatch.setattr(UserService, "set_name", explode)

    response = auth_client.patch(
        "/api/account/profile", json={"name": "New Name"}, headers={"X-Request-ID": "rid-123"}
    )
    assert response.status_code == 500
    body = response.json()
    assert_envelope(body, "INTERNAL_ERROR")

    serialized = response.text
    for leak in (secret, "hunter2", "db.internal", "/srv/app", "pool.py", "RuntimeError", "Traceback"):
        assert leak not in serialized, f"{leak!r} leaked into a 500 response"

    # The operator can still correlate the response with the log line.
    assert body["error"]["request_id"] == "rid-123"


def test_five_hundred_messages_are_fixed_text_not_exception_text():
    """The allowlist, asserted directly: only 4xx keeps its authored message."""
    assert 500 not in SAFE_STATUS
    assert 502 not in SAFE_STATUS and 504 not in SAFE_STATUS
    assert {400, 401, 403, 404, 409, 413, 422, 429} <= SAFE_STATUS


# ------------------------------------------------------------------ codes ---
@pytest.mark.parametrize(
    "status_code,expected",
    [
        (400, "BAD_REQUEST"),
        (401, "UNAUTHENTICATED"),
        (402, "QUOTA_EXCEEDED"),
        (404, "NOT_FOUND"),
        (409, "CONFLICT"),
        (413, "PAYLOAD_TOO_LARGE"),
        (422, "VALIDATION_FAILED"),
        (429, "RATE_LIMITED"),
        (500, "INTERNAL_ERROR"),
        (504, "API_TIMEOUT"),
        # An unmapped status still gets a usable code rather than a KeyError.
        (418, "BAD_REQUEST"),
        (599, "INTERNAL_ERROR"),
    ],
)
def test_status_maps_to_a_stable_code(status_code, expected):
    assert error_code(status_code) == expected


def test_envelope_matches_the_documented_shape():
    body = envelope(504, "The target API did not respond.", code="API_TIMEOUT")
    assert body == {
        "success": False,
        "error": {
            "code": "API_TIMEOUT",
            "message": "The target API did not respond.",
        },
        "detail": "The target API did not respond.",
    }
