"""One-time codes for email verification and password reset.

Everything here lives in the shared state backend (Redis when `REDIS_URL` is
set) and expires on its own. TTL is the mechanism, not a stored timestamp we
remember to compare — an expired code is a key that no longer exists, which
cannot be replayed by a clock bug or a missed check.

What is stored:

    otp:{purpose}:{email_key}   the HMAC of the code + metadata, TTL = lifetime
    otp:attempts:{purpose}:...  verification attempts, TTL = lifetime
    otp:resend:{purpose}:...    cooldown marker, TTL = cooldown
    otp:sends:{purpose}:...     sends this hour, TTL = 1 hour

The code itself is never stored. Only `HMAC-SHA256(secret, purpose|email|code)`
is, so a dump of Redis does not hand an attacker a set of working codes — a
six-digit code is only ~20 bits, so a plain hash would fall to an offline sweep
in milliseconds. The secret lives in the app config, never in the datastore.

A code is single-use: the record is deleted the moment it verifies, and the
consumer receives a short-lived ticket instead. That ticket is what authorises
the actual password change, so the reset step cannot be reached by guessing.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from hashlib import sha256
from typing import Literal

from ..config.settings import Settings
from ..models.user import normalize_email
from ..runtime.state import get_state_backend
from ..utils.logging import get_logger

logger = get_logger(__name__)

Purpose = Literal["verify", "reset"]

CODE_DIGITS = 6


class OtpError(RuntimeError):
    """Base for OTP failures that are safe to describe to the caller."""


class ResendTooSoon(OtpError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(f"Please wait {retry_after}s before requesting another code.")
        self.retry_after = retry_after


class TooManySends(OtpError):
    def __init__(self) -> None:
        super().__init__("Too many codes requested. Try again later.")


@dataclass(frozen=True)
class VerifyResult:
    ok: bool
    # Set only on success: proves the code was verified, for the next step.
    ticket: str | None = None
    # A caller-safe explanation. Never distinguishes "expired" from "no code
    # was ever issued" beyond what the user needs to act on.
    reason: str = ""
    attempts_left: int | None = None


def _key_for(email: str) -> str:
    return sha256(normalize_email(email).encode("utf-8")).hexdigest()[:32]


class OtpService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    # ------------------------------------------------------------- keys ---
    def _code_key(self, purpose: Purpose, email: str) -> str:
        return f"otp:{purpose}:{_key_for(email)}"

    def _attempts_key(self, purpose: Purpose, email: str) -> str:
        return f"otp:attempts:{purpose}:{_key_for(email)}"

    def _resend_key(self, purpose: Purpose, email: str) -> str:
        return f"otp:resend:{purpose}:{_key_for(email)}"

    def _sends_key(self, purpose: Purpose, email: str) -> str:
        return f"otp:sends:{purpose}:{_key_for(email)}"

    def _ticket_key(self, purpose: Purpose, ticket: str) -> str:
        return f"otp:ticket:{purpose}:{sha256(ticket.encode()).hexdigest()[:32]}"

    # ------------------------------------------------------------ digest ---
    def _digest(self, purpose: Purpose, email: str, code: str) -> str:
        message = f"{purpose}|{normalize_email(email)}|{code}".encode("utf-8")
        return hmac.new(self.settings.secret_key.encode("utf-8"), message, sha256).hexdigest()

    # ------------------------------------------------------------- issue ---
    async def issue(self, purpose: Purpose, email: str, *, enforce_cooldown: bool = True) -> str:
        """Create a code, store only its HMAC, and return the code to be emailed.

        The returned value is for the email transport alone. It must never be
        put in an HTTP response, a log line or an event.
        """
        state = get_state_backend()

        cooldown = self.settings.otp_resend_cooldown_seconds
        if enforce_cooldown:
            # A zero cooldown means "no cooldown". Writing the marker anyway
            # would be worse than useless: a ttl of 0 is stored as *no expiry*,
            # so the first send would block every later one forever.
            if cooldown > 0 and await state.get_json(self._resend_key(purpose, email)) is not None:
                raise ResendTooSoon(cooldown)
            sent = await state.incr(self._sends_key(purpose, email), 1, ttl=3600)
            if sent > self.settings.otp_max_sends_per_hour:
                raise TooManySends()

        code = f"{secrets.randbelow(10 ** CODE_DIGITS):0{CODE_DIGITS}d}"
        ttl = self.settings.otp_ttl_seconds
        await state.set_json(
            self._code_key(purpose, email),
            {"digest": self._digest(purpose, email, code), "email": normalize_email(email)},
            ttl=ttl,
        )
        # A fresh code resets the attempt budget; otherwise a user who fat-fingered
        # the last one would be locked out of the new one too.
        await state.delete(self._attempts_key(purpose, email))
        if cooldown > 0:
            await state.set_json(self._resend_key(purpose, email), {"sent": True}, ttl=cooldown)
        logger.info("issued %s code for %s", purpose, _key_for(email))
        return code

    # ------------------------------------------------------------ verify ---
    async def verify(self, purpose: Purpose, email: str, code: str) -> VerifyResult:
        state = get_state_backend()
        code = (code or "").strip()
        record = await state.get_json(self._code_key(purpose, email))
        if not isinstance(record, dict) or not record.get("digest"):
            return VerifyResult(
                ok=False,
                reason="That code has expired or was already used. Request a new one.",
            )

        attempts = await state.incr(
            self._attempts_key(purpose, email), 1, ttl=self.settings.otp_ttl_seconds
        )
        if attempts > self.settings.otp_max_attempts:
            # Burn the code: past the budget it is no longer trustworthy.
            await state.delete(self._code_key(purpose, email))
            return VerifyResult(
                ok=False,
                reason="Too many incorrect attempts. Request a new code.",
                attempts_left=0,
            )

        if not hmac.compare_digest(record["digest"], self._digest(purpose, email, code)):
            left = max(0, self.settings.otp_max_attempts - attempts)
            return VerifyResult(
                ok=False,
                reason="That code is not correct.",
                attempts_left=left,
            )

        # Correct: consume it so the same code can never be presented twice.
        await state.delete(self._code_key(purpose, email))
        await state.delete(self._attempts_key(purpose, email))

        ticket = secrets.token_urlsafe(32)
        await state.set_json(
            self._ticket_key(purpose, ticket),
            {"email": normalize_email(email)},
            ttl=self.settings.otp_ticket_ttl_seconds,
        )
        return VerifyResult(ok=True, ticket=ticket)

    # ------------------------------------------------------------ ticket ---
    async def consume_ticket(self, purpose: Purpose, ticket: str) -> str | None:
        """Redeem a verification ticket exactly once, returning its email."""
        if not ticket:
            return None
        state = get_state_backend()
        key = self._ticket_key(purpose, ticket)
        record = await state.get_json(key)
        if not isinstance(record, dict) or not record.get("email"):
            return None
        await state.delete(key)
        return str(record["email"])

    async def clear(self, purpose: Purpose, email: str) -> None:
        """Drop any outstanding code, e.g. once the account is verified."""
        state = get_state_backend()
        for key in (
            self._code_key(purpose, email),
            self._attempts_key(purpose, email),
        ):
            await state.delete(key)


_service: OtpService | None = None


def get_otp_service(settings: Settings) -> OtpService:
    global _service
    if _service is None:
        _service = OtpService(settings)
    return _service


def reset_otp_service() -> None:
    global _service
    _service = None
