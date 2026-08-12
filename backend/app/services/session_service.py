"""Login sessions.

An opaque random token in an HttpOnly cookie, with the server-side record in
the shared state backend. Chosen over a self-contained JWT for one reason that
matters here: logout and "sign out everywhere after a password reset" have to
actually work. A stateless JWT cannot be withdrawn before it expires; a session
record can be deleted.

The token is never stored as given. Redis holds `sha256(token)`, so read access
to the datastore does not hand over usable sessions.

Two independent expiries:

  * idle    — the key's TTL, refreshed as the user works;
  * absolute — `expires_at` in the record, never extended, so a stolen token
               cannot be kept alive forever by using it.

`epoch` is compared against the user's `session_epoch` on every request. A
password reset increments the user's epoch, which invalidates every session
issued before it without having to hunt them down.

Keys, all under the `session:` prefix so they are never touched by cache
invalidation (which only ever deletes `cache:*`):

    session:{token_hash}        the session record, TTL = idle window
    session:index:{user_id}     that user's live token hashes, TTL = absolute

The index exists so the Settings page can list active sessions and revoke them
individually. It is written on issue and revoke only — never on the hot path.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from hashlib import sha256

from ..config.settings import Settings
from ..runtime.state import LockTimeout, get_state_backend
from ..utils.logging import get_logger

logger = get_logger(__name__)

SESSION_COOKIE = "apidoctor_session"

# The idle window is refreshed at most this often. Without it every single
# authenticated request costs a Redis write purely to move a TTL a few
# milliseconds forward. The cost of the throttle is that a session can expire up
# to this many seconds earlier than a strict reading of the idle timeout — on a
# 12-hour window, immaterial.
TOUCH_INTERVAL_SECONDS = 60.0


@dataclass(frozen=True)
class SessionRecord:
    token_hash: str
    user_id: str
    epoch: int
    created_at: float
    expires_at: float
    last_seen: float = 0.0
    user_agent: str = ""
    ip: str = ""

    @property
    def seconds_remaining(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    def as_payload(self) -> dict:
        return {
            "user_id": self.user_id,
            "epoch": self.epoch,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "last_seen": self.last_seen,
            "user_agent": self.user_agent,
            "ip": self.ip,
        }

    def public(self, *, current: bool) -> dict:
        """What the Settings page shows. Never the token or its hash."""
        return {
            # A stable, non-reversible handle so the UI can target one session
            # for revocation without ever holding anything usable as a token.
            "id": self.token_hash[:16],
            "created_at": self.created_at,
            "last_seen": self.last_seen or self.created_at,
            "expires_at": self.expires_at,
            "user_agent": self.user_agent[:200],
            "current": current,
        }


def _hash(token: str) -> str:
    return sha256(token.encode("utf-8")).hexdigest()


class SessionService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _key(self, token_hash: str) -> str:
        return f"session:{token_hash}"

    def _index_key(self, user_id: str) -> str:
        return f"session:index:{user_id}"

    # ------------------------------------------------------------- issue ---
    async def issue(
        self,
        user_id: str,
        epoch: int,
        *,
        user_agent: str = "",
        ip: str = "",
    ) -> tuple[str, int]:
        """Create a session. Returns (token, cookie max-age)."""
        token = secrets.token_urlsafe(40)
        token_hash = _hash(token)
        now = time.time()
        absolute = now + self.settings.session_absolute_lifetime_seconds
        idle = self.settings.session_idle_timeout_seconds
        ttl = min(idle, self.settings.session_absolute_lifetime_seconds)

        state = get_state_backend()
        await state.set_json(
            self._key(token_hash),
            {
                "user_id": user_id,
                "epoch": epoch,
                "created_at": now,
                "expires_at": absolute,
                "last_seen": now,
                "user_agent": (user_agent or "")[:200],
                "ip": (ip or "")[:64],
            },
            ttl=ttl,
        )
        await self._index_add(user_id, token_hash)
        logger.info("session issued for %s", user_id)
        return token, int(ttl)

    # -------------------------------------------------------------- load ---
    async def load(self, token: str) -> SessionRecord | None:
        if not token:
            return None
        token_hash = _hash(token)
        record = await get_state_backend().get_json(self._key(token_hash))
        return self._to_record(token_hash, record)

    def _to_record(self, token_hash: str, record) -> SessionRecord | None:
        if not isinstance(record, dict) or not record.get("user_id"):
            return None
        expires_at = float(record.get("expires_at") or 0)
        if expires_at and expires_at < time.time():
            return None
        return SessionRecord(
            token_hash=token_hash,
            user_id=str(record["user_id"]),
            epoch=int(record.get("epoch") or 0),
            created_at=float(record.get("created_at") or 0),
            expires_at=expires_at,
            last_seen=float(record.get("last_seen") or 0),
            user_agent=str(record.get("user_agent") or ""),
            ip=str(record.get("ip") or ""),
        )

    async def touch(self, record: SessionRecord) -> bool:
        """Slide the idle window forward, never past the absolute deadline.

        Returns whether a write actually happened. Throttled: see
        TOUCH_INTERVAL_SECONDS.
        """
        now = time.time()
        remaining = record.seconds_remaining
        if remaining <= 0:
            await self.revoke_hash(record.token_hash, user_id=record.user_id)
            return True
        if record.last_seen and (now - record.last_seen) < TOUCH_INTERVAL_SECONDS:
            return False

        ttl = min(self.settings.session_idle_timeout_seconds, remaining)
        payload = record.as_payload()
        payload["last_seen"] = now
        await get_state_backend().set_json(self._key(record.token_hash), payload, ttl=ttl)
        return True

    # ------------------------------------------------------------ revoke ---
    async def revoke(self, token: str) -> None:
        if token:
            await self.revoke_hash(_hash(token))

    async def revoke_hash(self, token_hash: str, *, user_id: str | None = None) -> None:
        state = get_state_backend()
        if user_id is None:
            record = await state.get_json(self._key(token_hash))
            if isinstance(record, dict):
                user_id = str(record.get("user_id") or "") or None
        await state.delete(self._key(token_hash))
        if user_id:
            await self._index_remove(user_id, token_hash)

    async def revoke_all(self, user_id: str, *, except_hash: str | None = None) -> int:
        """Sign out every session for this account. Returns how many died.

        Deliberately explicit rather than relying on the epoch bump alone: the
        Settings page offers this without changing the password, so there is no
        epoch change to piggy-back on.
        """
        state = get_state_backend()
        hashes = await self._index_read(user_id)
        killed = 0
        keep: list[str] = []
        for token_hash in hashes:
            if except_hash and token_hash == except_hash:
                keep.append(token_hash)
                continue
            await state.delete(self._key(token_hash))
            killed += 1
        await state.set_json(
            self._index_key(user_id),
            {"tokens": keep},
            ttl=self.settings.session_absolute_lifetime_seconds,
        )
        logger.info("revoked %d session(s) for %s", killed, user_id)
        return killed

    # ------------------------------------------------------------- list ----
    async def list_for_user(self, user_id: str) -> list[SessionRecord]:
        """Live sessions, pruning index entries whose record has expired.

        One GET per live session, on the Settings page only. A user has a
        handful, so this stays cheaper than maintaining a denormalised copy on
        every request.
        """
        state = get_state_backend()
        hashes = await self._index_read(user_id)
        records: list[SessionRecord] = []
        alive: list[str] = []
        for token_hash in hashes:
            record = self._to_record(token_hash, await state.get_json(self._key(token_hash)))
            if record is None:
                continue
            records.append(record)
            alive.append(token_hash)
        if len(alive) != len(hashes):
            await state.set_json(
                self._index_key(user_id),
                {"tokens": alive},
                ttl=self.settings.session_absolute_lifetime_seconds,
            )
        records.sort(key=lambda r: r.last_seen or r.created_at, reverse=True)
        return records

    # ------------------------------------------------------------ index ----
    async def _index_read(self, user_id: str) -> list[str]:
        payload = await get_state_backend().get_json(self._index_key(user_id))
        if not isinstance(payload, dict):
            return []
        tokens = payload.get("tokens")
        return [str(t) for t in tokens] if isinstance(tokens, list) else []

    async def _index_write(self, user_id: str, mutate) -> None:
        """Read-modify-write the index under a lock.

        Two logins racing would otherwise lose an entry, leaving a live session
        that "log out everywhere" cannot see. A lock timeout must not fail the
        login that triggered it, so the update proceeds unlocked: the worst case
        is one index entry lost, which costs a stale row on the Settings page —
        strictly better than refusing to sign the user in.
        """
        state = get_state_backend()
        key = self._index_key(user_id)
        ttl = self.settings.session_absolute_lifetime_seconds
        try:
            async with state.lock(f"lock:{key}", ttl=5.0, timeout=3.0):
                tokens = mutate(await self._index_read(user_id))
                await state.set_json(key, {"tokens": tokens}, ttl=ttl)
            return
        except LockTimeout:
            logger.warning("session index lock timed out for %s; writing unlocked", user_id)
        except Exception as exc:  # noqa: BLE001 - the index is not worth a 500
            logger.warning("session index update failed for %s: %s", user_id, exc)
            return
        try:
            tokens = mutate(await self._index_read(user_id))
            await state.set_json(key, {"tokens": tokens}, ttl=ttl)
        except Exception as exc:  # noqa: BLE001
            logger.warning("session index update failed for %s: %s", user_id, exc)

    async def _index_add(self, user_id: str, token_hash: str) -> None:
        def mutate(tokens: list[str]) -> list[str]:
            if token_hash not in tokens:
                tokens.append(token_hash)
            # Bound the index: a user who never logs out should not accumulate
            # an unbounded list. Oldest entries fall off; their records expire
            # on their own TTL regardless.
            return tokens[-50:]

        await self._index_write(user_id, mutate)

    async def _index_remove(self, user_id: str, token_hash: str) -> None:
        await self._index_write(
            user_id, lambda tokens: [t for t in tokens if t != token_hash]
        )

    async def purge_user(self, user_id: str) -> None:
        """Everything belonging to a deleted account."""
        await self.revoke_all(user_id)
        await get_state_backend().delete(self._index_key(user_id))

    def cookie_kwargs(self, max_age: int) -> dict:
        """Cookie flags. Secure is on unless we are on plain-HTTP localhost."""
        return {
            "key": SESSION_COOKIE,
            "max_age": max_age,
            "httponly": True,
            "secure": self.settings.session_cookie_secure,
            "samesite": self.settings.session_cookie_samesite,
            "path": "/",
        }


_service: SessionService | None = None


def get_session_service(settings: Settings) -> SessionService:
    global _service
    if _service is None:
        _service = SessionService(settings)
    return _service


def reset_session_service() -> None:
    global _service
    _service = None
