from __future__ import annotations

from pathlib import Path

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
    """A blank SESSION_SECRET is generated and persisted, not rejected.

    Refusing to start made a first run need manual setup for no security
    benefit -- a generated secret is stronger than one a person invents.
    """

    def test_generated_when_unset(self, tmp_path: Path) -> None:
        settings = Settings(
            auth_mode="local",
            session_secret="",
            secret_file=tmp_path / ".session_secret",
            database_url="sqlite:///:memory:",
        )
        assert len(settings.session_secret) >= 32

    def test_persisted_so_sessions_survive_a_restart(self, tmp_path: Path) -> None:
        secret_file = tmp_path / ".session_secret"
        first = Settings(
            auth_mode="local",
            session_secret="",
            secret_file=secret_file,
            database_url="sqlite:///:memory:",
        )
        second = Settings(
            auth_mode="local",
            session_secret="",
            secret_file=secret_file,
            database_url="sqlite:///:memory:",
        )
        assert first.session_secret == second.session_secret

    def test_secret_file_is_owner_only(self, tmp_path: Path) -> None:
        secret_file = tmp_path / ".session_secret"
        Settings(
            auth_mode="local",
            session_secret="",
            secret_file=secret_file,
            database_url="sqlite:///:memory:",
        )
        # Anyone who can read this file can forge a session.
        assert secret_file.stat().st_mode & 0o077 == 0

    def test_explicit_secret_is_used_verbatim(self, tmp_path: Path) -> None:
        explicit = "p" * 48
        settings = Settings(
            auth_mode="local",
            session_secret=explicit,
            secret_file=tmp_path / ".session_secret",
            database_url="sqlite:///:memory:",
        )
        assert settings.session_secret == explicit

    def test_rejects_short_secret(self) -> None:
        with pytest.raises(ValidationError, match="at least 32 characters"):
            Settings(
                auth_mode="local", session_secret="tooshort", database_url="sqlite:///:memory:"
            )

    def test_unwritable_location_still_starts(self, tmp_path: Path) -> None:
        # A read-only volume costs session persistence, not availability.
        blocked = tmp_path / "ro"
        blocked.mkdir()
        blocked.chmod(0o500)
        try:
            settings = Settings(
                auth_mode="local",
                session_secret="",
                secret_file=blocked / "nested" / ".secret",
                database_url="sqlite:///:memory:",
            )
            assert len(settings.session_secret) >= 32
        finally:
            blocked.chmod(0o700)


def test_log_level_is_normalised() -> None:
    assert _settings(log_level="debug").log_level == "DEBUG"


def test_rejects_unknown_log_level() -> None:
    with pytest.raises(ValidationError):
        _settings(log_level="chatty")
