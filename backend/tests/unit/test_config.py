from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.config import AuthMode, Settings, _is_loopback

SECRET = "y" * 48


def _settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "session_secret": SECRET,
        "database_url": "sqlite:///:memory:",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("127.0.0.1", True),
        ("localhost", True),
        ("::1", True),
        ("127.5.5.5", True),
        ("0.0.0.0", False),
        ("192.168.1.10", False),
        ("kafka.example.com", False),
    ],
)
def test_is_loopback(host: str, expected: bool) -> None:
    assert _is_loopback(host) is expected


class TestNoAuthGuard:
    """AUTH_MODE=none must not silently expose a console to a network."""

    def test_allowed_on_loopback(self) -> None:
        settings = _settings(auth_mode="none", console_host="127.0.0.1")
        assert settings.auth_mode is AuthMode.NONE

    def test_refused_on_wildcard_bind(self) -> None:
        with pytest.raises(ValidationError, match="ALLOW_INSECURE_NO_AUTH"):
            _settings(auth_mode="none", console_host="0.0.0.0")

    def test_allowed_on_wildcard_bind_with_acknowledgement(self) -> None:
        settings = _settings(
            auth_mode="none",
            console_host="0.0.0.0",
            allow_insecure_no_auth=True,
        )
        assert settings.is_no_auth

    def test_generates_ephemeral_secret(self) -> None:
        settings = Settings(
            auth_mode="none",
            console_host="127.0.0.1",
            session_secret="",
            database_url="sqlite:///:memory:",
        )
        assert len(settings.session_secret) >= 32


class TestSessionSecret:
    def test_required_for_local_auth(self) -> None:
        with pytest.raises(ValidationError, match="SESSION_SECRET must be set"):
            Settings(auth_mode="local", session_secret="", database_url="sqlite:///:memory:")

    def test_rejects_short_secret(self) -> None:
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(
                auth_mode="local", session_secret="tooshort", database_url="sqlite:///:memory:"
            )


def test_log_level_is_normalised() -> None:
    assert _settings(log_level="debug").log_level == "DEBUG"


def test_rejects_unknown_log_level() -> None:
    with pytest.raises(ValidationError):
        _settings(log_level="chatty")
