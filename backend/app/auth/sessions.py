"""Signed session cookies and double-submit CSRF tokens.

No server-side session table: the cookie is an itsdangerous-signed payload with
a max age. Logging out clears the cookie; rotating SESSION_SECRET invalidates
every session at once, which is the intended emergency lever.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

_SALT = "kafkaplay.session.v1"
CSRF_HEADER = "X-CSRF-Token"
# Methods that cannot change state, and so need no CSRF token.
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})


@dataclass(frozen=True, slots=True)
class SessionData:
    username: str
    role: str
    provider: str
    csrf_token: str

    def to_dict(self) -> dict[str, str]:
        return {
            "u": self.username,
            "r": self.role,
            "p": self.provider,
            "c": self.csrf_token,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> SessionData | None:
        try:
            return cls(
                username=str(raw["u"]),
                role=str(raw["r"]),
                provider=str(raw["p"]),
                csrf_token=str(raw["c"]),
            )
        except (KeyError, TypeError):
            return None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


class SessionCodec:
    def __init__(self, secret: str, max_age_seconds: int) -> None:
        self._serializer = URLSafeTimedSerializer(secret, salt=_SALT)
        self._max_age = max_age_seconds

    def dumps(self, data: SessionData) -> str:
        return self._serializer.dumps(data.to_dict())

    def loads(self, token: str) -> SessionData | None:
        """Return the session, or None when it is absent, tampered, or expired."""
        try:
            raw = self._serializer.loads(token, max_age=self._max_age)
        except (BadSignature, SignatureExpired):
            return None
        if not isinstance(raw, dict):
            return None
        return SessionData.from_dict(raw)


def csrf_matches(expected: str, provided: str | None) -> bool:
    if not provided:
        return False
    return secrets.compare_digest(expected, provided)
