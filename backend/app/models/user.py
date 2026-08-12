"""User account model.

A user is the unit of isolation. `User.id` becomes `Principal.tenant`, which is
what every project, session, report and event is already scoped by — so adding
accounts did not require a new isolation mechanism, only a new way to resolve
the tenant.

The password hash never leaves the backend: `public()` is the only projection
sent to a client, and it has no hash, no OTP and no session data.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..utils.timestamps import utcnow_iso

# Deliberately permissive but structural: anything with exactly one @, a dot in
# the domain, and no whitespace. Over-strict patterns reject valid addresses.
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[A-Za-z]{2,}$")

MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 200
MAX_NAME_LENGTH = 80


class UserStatus(str, Enum):
    PENDING = "pending"     # registered, email not verified yet
    ACTIVE = "active"


def normalize_email(raw: str) -> str:
    """Lowercase and trim. Storage and lookup must agree on exactly one form."""
    return (raw or "").strip().lower()


def validate_email(raw: str) -> str | None:
    email = normalize_email(raw)
    if not email:
        return "Enter your email address."
    if len(email) > 254 or not EMAIL_RE.match(email):
        return "Enter a valid email address."
    return None


def validate_password(password: str, *, name: str = "", email: str = "") -> str | None:
    """Server-side password policy. The frontend mirrors it; this one decides."""
    if not password:
        return "Enter a password."
    if len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
    if len(password) > MAX_PASSWORD_LENGTH:
        return f"Password must be at most {MAX_PASSWORD_LENGTH} characters."
    if not any(c.isalpha() for c in password):
        return "Password must contain at least one letter."
    if not any(c.isdigit() for c in password):
        return "Password must contain at least one number."
    lowered = password.lower()
    local = normalize_email(email).partition("@")[0]
    if local and len(local) >= 4 and local in lowered:
        return "Password must not contain your email address."
    if name and len(name) >= 4 and name.strip().lower() in lowered:
        return "Password must not contain your name."
    return None


def validate_name(raw: str) -> str | None:
    name = (raw or "").strip()
    if len(name) < 2:
        return "Enter your name."
    if len(name) > MAX_NAME_LENGTH:
        return f"Name must be at most {MAX_NAME_LENGTH} characters."
    return None


Theme = Literal["system", "light", "dark"]


class UserPreferences(BaseModel):
    """Per-account settings.

    Every field here changes real behaviour somewhere. A preference that no code
    reads is worse than no preference at all: it tells the user they configured
    something when they did not. The comment on each field names its consumer.
    """

    model_config = ConfigDict(extra="ignore")

    # Read by the frontend shell to pick the colour scheme.
    theme: Theme = "system"

    # Read by RunOptions -> run_api_probe: the per-request timeout applied to
    # each endpoint call when testing a project's API.
    api_timeout_seconds: int = Field(default=30, ge=1, le=300)

    # Read by RunOptions -> run_api_probe: whether POST/PUT/PATCH/DELETE routes
    # are called during a probe. Off by default because the project's data store
    # is real and a probe would mutate it.
    probe_write_methods: bool = False

    # Read by the orchestrator: when false, diagnosis uses the deterministic
    # engine only and no OpenAI call is made.
    ai_analysis: bool = True

    # Read by the orchestrator: whether a proposed patch waits for an explicit
    # approval before it is applied.
    require_patch_approval: bool = True

    @field_validator("theme", mode="before")
    @classmethod
    def _normalize_theme(cls, value):
        text = str(value or "system").strip().lower()
        return text if text in {"system", "light", "dark"} else "system"


class User(BaseModel):
    id: str
    name: str
    email: str
    password_hash: str = Field(repr=False)
    email_verified: bool = False
    status: UserStatus = UserStatus.PENDING
    created_at: str = Field(default_factory=utcnow_iso)
    updated_at: str = Field(default_factory=utcnow_iso)
    # Bumped on password reset so every previously issued session dies.
    session_epoch: int = 0
    last_login_at: str | None = None
    preferences: UserPreferences = Field(default_factory=UserPreferences)

    def touch(self) -> None:
        self.updated_at = utcnow_iso()

    def public(self) -> dict:
        """The only shape a client ever sees."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "email_verified": self.email_verified,
            "created_at": self.created_at,
            "preferences": self.preferences.model_dump(mode="json"),
        }


class PublicUser(BaseModel):
    """Response model for /auth/me and friends. No hash, ever."""

    id: str
    name: str
    email: str
    email_verified: bool
    created_at: str
    preferences: UserPreferences = Field(default_factory=UserPreferences)
