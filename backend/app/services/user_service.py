"""User accounts: create, look up, verify, change password.

Persistence follows the pattern already used for projects: a `UserStore`
Protocol with a filesystem+JSON implementation. This project has no SQL layer
and no migration system, so introducing one for a single table would be a
larger change than the feature warrants — moving to PostgreSQL later means
writing one more class here, not touching the routes.

On-disk layout:

    data/users/
        <user_id>.json          the account record
        index/<email_key>.json  {"user_id": ...} — the email -> id lookup

The email index is a separate small file rather than a scan, so login is one
stat + one read regardless of how many accounts exist. Email keys are hashed,
so a directory listing does not disclose the address of every registered user.

Account creation takes a cross-worker lock, otherwise two simultaneous
registrations for the same address both pass the "is it taken?" check and the
second silently overwrites the first.
"""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path
from typing import Protocol

from ..config.settings import Settings
from ..models.user import User, UserPreferences, UserStatus, normalize_email
from ..runtime.cache import get_cache
from ..runtime.concurrency import io_bound
from ..runtime.state import LockTimeout, get_state_backend
from ..security.passwords import hash_password, needs_rehash, verify_password
from ..utils.filesystem import ensure_dir, read_json, write_json_atomic
from ..utils.logging import get_logger
from ..utils.timestamps import utcnow_iso

logger = get_logger(__name__)


class UserError(RuntimeError):
    pass


class EmailTaken(UserError):
    """Raised when an account already exists for that address."""


class InvalidCredentials(UserError):
    """Raised when a password change is attempted without the current password."""


def _shared_key(user_id: str) -> str:
    """The cross-worker invalidation key for one user's hot-path record."""
    return f"user:{user_id}"


def _cache_key(user_id: str) -> tuple:
    """The L1 key. Shaped ("shared", <key>) so `shared_cache.invalidate` —
    which drops exactly that tuple locally and on every sibling worker — is the
    one mechanism that expires it."""
    return ("shared", _shared_key(user_id))


def email_key(email: str) -> str:
    """A filesystem-safe, non-reversible key for the email index."""
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest()[:32]


class UserStore(Protocol):
    """Persistence boundary. Implement this to move to a database."""

    def save(self, user: User) -> None: ...
    def load(self, user_id: str) -> User | None: ...
    def find_by_email(self, email: str) -> User | None: ...
    def delete(self, user_id: str) -> bool: ...
    def count(self) -> int: ...


class JsonUserStore:
    def __init__(self, root: Path) -> None:
        self.root = ensure_dir(root)
        self.index_dir = ensure_dir(root / "index")

    def _record(self, user_id: str) -> Path:
        return self.root / f"{user_id}.json"

    def save(self, user: User) -> None:
        user.touch()
        write_json_atomic(self._record(user.id), user.model_dump(mode="json"))
        write_json_atomic(
            self.index_dir / f"{email_key(user.email)}.json", {"user_id": user.id}
        )

    def load(self, user_id: str) -> User | None:
        # `user_id` reaches this from a signed session, but a traversal here
        # would read arbitrary JSON, so refuse anything that is not a plain id.
        if not user_id or "/" in user_id or "\\" in user_id or user_id.startswith("."):
            return None
        payload = read_json(self._record(user_id))
        if payload is None:
            return None
        try:
            return User.model_validate(payload)
        except Exception as exc:  # noqa: BLE001 - a corrupt record must not 500
            logger.warning("unreadable user record %s: %s", user_id, exc)
            return None

    def find_by_email(self, email: str) -> User | None:
        entry = read_json(self.index_dir / f"{email_key(email)}.json")
        if not entry or not entry.get("user_id"):
            return None
        user = self.load(entry["user_id"])
        # Guard against a stale index pointing at a deleted or renamed account.
        if user is not None and normalize_email(user.email) == normalize_email(email):
            return user
        return None

    def delete(self, user_id: str) -> bool:
        user = self.load(user_id)
        if user is None:
            return False
        self._record(user_id).unlink(missing_ok=True)
        (self.index_dir / f"{email_key(user.email)}.json").unlink(missing_ok=True)
        return True

    def count(self) -> int:
        return sum(1 for path in self.root.glob("*.json") if path.is_file())


def build_user_store(settings: Settings) -> UserStore:
    """Postgres when a database is configured, JSON files otherwise."""
    from ..db import database_enabled

    if database_enabled():
        from ..db.stores import PostgresUserStore

        return PostgresUserStore()
    return JsonUserStore(settings.users_dir)


class UserService:
    def __init__(self, settings: Settings, store: UserStore | None = None) -> None:
        self.settings = settings
        self.store = store or build_user_store(settings)

    # ------------------------------------------------------------ lookup ---
    def get(self, user_id: str) -> User | None:
        return self.store.load(user_id)

    def by_email(self, email: str) -> User | None:
        return self.store.find_by_email(email)

    async def get_async(self, user_id: str) -> User | None:
        return await io_bound(self.store.load, user_id)

    async def get_cached_async(self, user_id: str) -> User | None:
        """The read on the authentication hot path.

        Every authenticated request has to resolve the session's user to check
        `session_epoch` and `email_verified`, which was one database round trip
        (or one file read) per request. A very short TTL with single-flight
        collapses a burst of requests from one user into a single read.

        The TTL is the staleness bound on `session_epoch`, i.e. how long a
        session revoked by a password change could still be honoured on a worker
        that has not seen the change. `_invalidate_cached` publishes across
        workers on every write, so the TTL only matters if that broadcast is
        lost — and `aggregate_cache_seconds` (2s by default) is a short enough
        window to accept for that failure mode.
        """
        ttl = self.settings.aggregate_cache_seconds
        if ttl <= 0:
            return await self.get_async(user_id)

        async def load() -> dict | None:
            user = await io_bound(self.store.load, user_id)
            # Cache a plain dict: handing the same mutable model to every
            # caller invites one request's edit from leaking into another's.
            return user.model_dump(mode="json") if user else None

        payload = await get_cache().get_or_compute(_cache_key(user_id), load, ttl=ttl)
        if payload is None:
            return None
        try:
            return User.model_validate(payload)
        except Exception:  # noqa: BLE001 - fall back to the authoritative read
            return await self.get_async(user_id)

    async def by_email_async(self, email: str) -> User | None:
        return await io_bound(self.store.find_by_email, email)

    async def invalidate_cached(self, user_id: str) -> None:
        """Drop this user's hot-path entry here and on every other worker.

        Keyed per user, so one account's password change does not throw away
        every other account's cached record.
        """
        from ..runtime.shared_cache import invalidate as broadcast

        await broadcast(_shared_key(user_id))

    # ------------------------------------------------------------ create ---
    def create(self, *, name: str, email: str, password: str) -> User:
        email = normalize_email(email)
        if self.store.find_by_email(email) is not None:
            raise EmailTaken("an account already exists for that email")
        # The UNIQUE index on users.email is the real guard against two
        # registrations racing; this check is for the friendly message.
        user = User(
            id=f"usr_{uuid.uuid4().hex[:16]}",
            name=name.strip(),
            email=email,
            password_hash=hash_password(password),
            status=UserStatus.PENDING,
        )
        try:
            self.store.save(user)
        except Exception as exc:  # noqa: BLE001
            # A unique-violation here means someone else won the race between
            # the check above and this insert. Report it as taken, not as a 500.
            if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
                raise EmailTaken("an account already exists for that email") from exc
            raise
        logger.info("created user %s", user.id)
        return user

    async def create_async(self, *, name: str, email: str, password: str) -> User:
        """Create an account, serialised per email across workers."""
        state = get_state_backend()
        try:
            async with state.lock(f"user:create:{email_key(email)}", ttl=10.0, timeout=5.0):
                return await io_bound(
                    lambda: self.create(name=name, email=email, password=password)
                )
        except LockTimeout:
            # Someone else is registering this address right now. Treat it as
            # taken rather than racing them.
            raise EmailTaken("an account already exists for that email") from None

    # ------------------------------------------------------ authenticate ---
    def authenticate(self, email: str, password: str) -> User | None:
        """Verify credentials in constant-ish time whether or not the user exists."""
        user = self.store.find_by_email(email)
        if user is None:
            from ..security.passwords import burn_dummy_verification

            burn_dummy_verification()
            return None
        if not verify_password(password, user.password_hash):
            return None
        # Transparently upgrade a hash made with older parameters.
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
            self.store.save(user)
        return user

    async def authenticate_async(self, email: str, password: str) -> User | None:
        return await io_bound(self.authenticate, email, password)

    # --------------------------------------------------------- mutations ---
    def mark_verified(self, user: User) -> User:
        user.email_verified = True
        user.status = UserStatus.ACTIVE
        self.store.save(user)
        return user

    async def mark_verified_async(self, user: User) -> User:
        return await io_bound(self.mark_verified, user)

    def set_password(self, user: User, password: str) -> User:
        """Replace the password and invalidate every existing session."""
        user.password_hash = hash_password(password)
        user.session_epoch += 1
        # A password reset also proves control of the mailbox.
        user.email_verified = True
        user.status = UserStatus.ACTIVE
        self.store.save(user)
        return user

    async def set_password_async(self, user: User, password: str) -> User:
        updated = await io_bound(self.set_password, user, password)
        # `session_epoch` changed: no worker may keep serving the old value, or
        # a session this reset was meant to kill would survive on that worker.
        await self.invalidate_cached(user.id)
        return updated

    def record_login(self, user: User) -> None:
        user.last_login_at = utcnow_iso()
        self.store.save(user)

    async def record_login_async(self, user: User) -> None:
        await io_bound(self.record_login, user)
        await self.invalidate_cached(user.id)

    # ------------------------------------------------------------ account ---
    def set_name(self, user: User, name: str) -> User:
        user.name = name.strip()
        self.store.save(user)
        return user

    async def set_name_async(self, user: User, name: str) -> User:
        updated = await io_bound(self.set_name, user, name)
        await self.invalidate_cached(user.id)
        return updated

    def set_preferences(self, user: User, preferences: UserPreferences) -> User:
        user.preferences = preferences
        self.store.save(user)
        return user

    async def set_preferences_async(self, user: User, preferences: UserPreferences) -> User:
        updated = await io_bound(self.set_preferences, user, preferences)
        await self.invalidate_cached(user.id)
        return updated

    def change_password(self, user: User, current: str, new_password: str) -> User:
        """Change a password for a signed-in user who proves the current one.

        Unlike a reset this does not go through email, so the current password
        is the only proof of control — it is verified here rather than by the
        caller so no route can skip it.
        """
        if not verify_password(current, user.password_hash):
            raise InvalidCredentials("Your current password is not correct.")
        return self.set_password(user, new_password)

    async def change_password_async(self, user: User, current: str, new_password: str) -> User:
        updated = await io_bound(self.change_password, user, current, new_password)
        await self.invalidate_cached(user.id)
        return updated

    def delete(self, user_id: str) -> bool:
        return self.store.delete(user_id)

    async def delete_async(self, user_id: str) -> bool:
        deleted = await io_bound(self.store.delete, user_id)
        await self.invalidate_cached(user_id)
        return deleted


_service: UserService | None = None


def get_user_service(settings: Settings) -> UserService:
    global _service
    if _service is None:
        _service = UserService(settings)
    return _service


def reset_user_service() -> None:
    """Test hook: drop the singleton so fresh settings take effect."""
    global _service
    _service = None
