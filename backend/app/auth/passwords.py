"""Password hashing.

bcrypt directly rather than passlib: passlib is unmaintained and its bcrypt
backend breaks against bcrypt>=4. One less dependency, one less surprise.
"""

from __future__ import annotations

import bcrypt

# bcrypt truncates silently at 72 bytes, which would make two different long
# passwords interchangeable. Reject rather than truncate.
MAX_PASSWORD_BYTES = 72
MIN_PASSWORD_LENGTH = 12

_DEFAULT_ROUNDS = 12


class PasswordError(ValueError):
    """Raised when a password cannot be used as given."""


def validate_password(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise PasswordError(
            f"password must be at most {MAX_PASSWORD_BYTES} bytes when UTF-8 encoded "
            "(bcrypt would otherwise silently ignore the remainder)"
        )


def hash_password(password: str, rounds: int = _DEFAULT_ROUNDS) -> str:
    validate_password(password)
    salt = bcrypt.gensalt(rounds=rounds)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("ascii")


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time-ish verification that does not leak whether a user exists.

    When ``password_hash`` is None we still run a bcrypt comparison against a
    dummy hash so a missing user costs the same time as a wrong password.
    """
    if password_hash is None:
        bcrypt.checkpw(password.encode("utf-8"), _DUMMY_HASH)
        return False
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("ascii"))
    except (ValueError, UnicodeEncodeError):
        return False


# Generated once at import so timing stays comparable for unknown users.
_DUMMY_HASH = bcrypt.hashpw(b"kafkaplay-dummy-password", bcrypt.gensalt(rounds=_DEFAULT_ROUNDS))
