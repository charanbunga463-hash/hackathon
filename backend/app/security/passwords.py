"""Password hashing.

Argon2id, the current recommendation for password storage: memory-hard, so a
GPU or ASIC attacker gains far less than against a fast hash. The parameters
below are the argon2-cffi defaults, which target roughly 64 MiB and ~50ms per
hash on commodity hardware.

Two properties this module guarantees to the rest of the app:

  * a plaintext password is never returned, logged or stored — only the encoded
    `$argon2id$...` string, which embeds its own salt and parameters;
  * verification takes about the same time whether or not the user exists, so
    login cannot be used to enumerate accounts by timing. `verify()` on a dummy
    hash is the supported way to do that (see `DUMMY_HASH`).
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from ..utils.logging import get_logger

logger = get_logger(__name__)

_hasher = PasswordHasher()

# A real Argon2 hash of a value nobody can log in with. Verifying against this
# when the email is unknown keeps the response time indistinguishable from a
# wrong-password attempt on a real account.
DUMMY_HASH = _hasher.hash("this-password-belongs-to-no-account")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _hasher.verify(encoded or DUMMY_HASH, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(encoded: str) -> bool:
    """True when the hash was made with weaker parameters than we use now."""
    try:
        return _hasher.check_needs_rehash(encoded)
    except (InvalidHashError, ValueError):
        return True


def burn_dummy_verification() -> None:
    """Spend the same work as a real check, for a login on an unknown email."""
    verify_password("not-the-password", DUMMY_HASH)
