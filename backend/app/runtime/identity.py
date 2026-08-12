"""Who is calling, and what they are allowed to see.

Without this every user shares one namespace: `GET /api/projects` returns
everyone's uploads, and any user can start a repair on — or delete — anyone
else's code. That is a data-leak bug long before it is a scaling bug.

Identity is deliberately simple and pluggable:

  * `AUTH_MODE=user`   — email + password accounts. The session cookie resolves
                         to a user, and `Principal.tenant` is that user's id.
                         This is the product default.
  * `AUTH_MODE=apikey` — `Authorization: Bearer <key>`, keys from API_KEYS.
                         Each key maps to its own isolated tenant.
  * `AUTH_MODE=open`   — single implicit tenant. Local development only; the
                         API refuses to start this way when APP_ENV=production.

Whatever the mode, everything downstream keys off `Principal.tenant`, so adding
OIDC later means writing one resolver, not touching the services.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

from ..utils.logging import get_logger

logger = get_logger(__name__)

ANONYMOUS_TENANT = "public"


@dataclass(frozen=True)
class Principal:
    """The authenticated caller."""

    tenant: str
    label: str = ""
    is_admin: bool = False
    auth_mode: str = "open"
    # Set only in `user` mode. The tenant is already the user id; these carry
    # the rest of the account so routes do not re-read it from disk.
    user_id: str | None = None
    email: str | None = None
    session_token_hash: str | None = None

    @property
    def is_anonymous(self) -> bool:
        return self.tenant == ANONYMOUS_TENANT

    def as_dict(self) -> dict:
        return {
            "tenant": self.tenant,
            "label": self.label,
            "is_admin": self.is_admin,
            "auth_mode": self.auth_mode,
        }


def user_label(user_id: str, email: str) -> str:
    """A log-safe caller hint: the account id plus a hashed email fragment."""
    digest = hashlib.sha256((email or "").encode("utf-8")).hexdigest()[:8]
    return f"{user_id}/{digest}"


class AuthError(Exception):
    """Raised when a caller cannot be identified."""


def parse_api_keys(raw: str) -> dict[str, str]:
    """Parse `API_KEYS` into {key: tenant}.

    Accepts `key:tenant,key2:tenant2` or bare `key,key2` (tenant derived from a
    hash of the key, so distinct keys are always distinct tenants).
    """
    mapping: dict[str, str] = {}
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        if ":" in entry:
            key, _, tenant = entry.partition(":")
            key, tenant = key.strip(), tenant.strip()
        else:
            key, tenant = entry, ""
        if not key:
            continue
        mapping[key] = tenant or f"t_{hashlib.sha256(key.encode()).hexdigest()[:12]}"
    return mapping


def tenant_label(key: str) -> str:
    """A non-reversible hint so logs can distinguish callers without leaking keys."""
    if not key:
        return "anonymous"
    return f"key-{hashlib.sha256(key.encode()).hexdigest()[:8]}"


async def resolve_session_principal(settings, cookie_token: str | None) -> Principal:
    """Resolve the session cookie into a user, or raise AuthError.

    Three things have to hold, not one: the session record must exist and be
    inside both its idle and absolute windows, the account must still exist,
    and the session's epoch must match the account's. The last one is what
    makes "sign out everywhere" work after a password reset — the sessions are
    not hunted down, they simply stop matching.
    """
    from ..services.session_service import get_session_service
    from ..services.user_service import get_user_service

    if not cookie_token:
        raise AuthError("authentication required")

    sessions = get_session_service(settings)
    record = await sessions.load(cookie_token)
    if record is None:
        raise AuthError("your session has expired; sign in again")

    users = get_user_service(settings)
    # Cached with a very short TTL and invalidated on every write to the
    # account. This read used to be one database round trip on *every*
    # authenticated request; see UserService.get_cached_async.
    user = await users.get_cached_async(record.user_id)
    if user is None:
        await sessions.revoke_hash(record.token_hash)
        raise AuthError("your session has expired; sign in again")
    if record.epoch != user.session_epoch:
        await sessions.revoke_hash(record.token_hash)
        raise AuthError("your password changed; sign in again")
    if not user.email_verified:
        raise AuthError("verify your email address to continue")

    await sessions.touch(record)
    return Principal(
        tenant=user.id,
        label=user_label(user.id, user.email),
        auth_mode="user",
        user_id=user.id,
        email=user.email,
        session_token_hash=record.token_hash,
    )


def resolve_principal(
    *,
    auth_mode: str,
    authorization: str | None,
    api_keys: dict[str, str],
    admin_keys: set[str],
) -> Principal:
    if auth_mode == "open":
        return Principal(tenant=ANONYMOUS_TENANT, label="anonymous", auth_mode="open")
    if auth_mode == "user":
        # Resolved asynchronously by the gateway; reaching here means a caller
        # bypassed it, so fail closed rather than guessing a tenant.
        raise AuthError("authentication required")

    token = _bearer(authorization)
    if not token:
        raise AuthError("missing bearer token; send 'Authorization: Bearer <api key>'")

    # Constant-time comparison against every configured key: a plain dict lookup
    # leaks key length and prefix through timing.
    matched: str | None = None
    for candidate in api_keys:
        if hmac.compare_digest(candidate, token):
            matched = candidate
            break
    if matched is None:
        raise AuthError("invalid API key")

    return Principal(
        tenant=api_keys[matched],
        label=tenant_label(matched),
        is_admin=matched in admin_keys,
        auth_mode="apikey",
    )


def _bearer(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, value = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    return value.strip() or None
