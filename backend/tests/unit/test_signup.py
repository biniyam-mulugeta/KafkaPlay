"""Self-registration.

The security question here is who is allowed to create an account. The rule:
registration is open only while the database has no users, and that first
account becomes the administrator. After that it stays closed unless an
operator turns ALLOW_SIGNUP on, and later accounts are viewers.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import REPO_ROOT

PASSWORD = "a-perfectly-fine-password"


def settings_without_admin(tmp_path: Path, **overrides: object) -> Settings:
    """A deployment with no pre-seeded admin -- the zero-config first run."""
    base: dict[str, object] = {
        "auth_mode": "local",
        "session_secret": "s" * 48,
        "admin_password": "",
        "themes_dir": REPO_ROOT / "themes",
        "theme": "offsetscope",
        "database_url": f"sqlite:///{tmp_path / 'signup.db'}",
        "clusters_file": tmp_path / "clusters.yaml",
        "log_format": "console",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


class TestFirstUser:
    def test_registration_is_open_on_an_empty_deployment(self, tmp_path: Path) -> None:
        with TestClient(create_app(settings_without_admin(tmp_path))) as client:
            body = client.get("/api/v1/auth/signup").json()
        assert body["available"] is True
        assert body["first_user"] is True

    def test_first_account_becomes_the_administrator(self, tmp_path: Path) -> None:
        with TestClient(create_app(settings_without_admin(tmp_path))) as client:
            response = client.post(
                "/api/v1/auth/signup", json={"username": "owner", "password": PASSWORD}
            )
        assert response.status_code == 201
        assert response.json()["role"] == "admin"

    def test_registering_signs_you_in(self, tmp_path: Path) -> None:
        with TestClient(create_app(settings_without_admin(tmp_path))) as client:
            client.post("/api/v1/auth/signup", json={"username": "owner", "password": PASSWORD})
            # The session cookie from signup should already be valid.
            me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["username"] == "owner"

    def test_meta_tells_the_ui_to_show_registration(self, tmp_path: Path) -> None:
        with TestClient(create_app(settings_without_admin(tmp_path))) as client:
            body = client.get("/api/v1/meta").json()
        assert body["signup_available"] is True
        assert body["signup_is_first_user"] is True


class TestClosedAfterFirstUser:
    def _claim(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/signup", json={"username": "owner", "password": PASSWORD}
        )
        assert response.status_code == 201
        client.post("/api/v1/auth/logout")

    def test_registration_closes_once_an_account_exists(self, tmp_path: Path) -> None:
        """The central guarantee: a deployment cannot be joined by a stranger."""
        with TestClient(create_app(settings_without_admin(tmp_path))) as client:
            self._claim(client)
            availability = client.get("/api/v1/auth/signup").json()
            attempt = client.post(
                "/api/v1/auth/signup", json={"username": "intruder", "password": PASSWORD}
            )

        assert availability["available"] is False
        assert attempt.status_code == 403
        assert "closed" in attempt.json()["detail"]

    def test_allow_signup_reopens_it(self, tmp_path: Path) -> None:
        config = settings_without_admin(tmp_path, allow_signup=True)
        with TestClient(create_app(config)) as client:
            self._claim(client)
            response = client.post(
                "/api/v1/auth/signup", json={"username": "colleague", "password": PASSWORD}
            )
        assert response.status_code == 201

    def test_later_accounts_are_viewers_not_admins(self, tmp_path: Path) -> None:
        """Only the first account is privileged; the rest must be promoted."""
        config = settings_without_admin(tmp_path, allow_signup=True)
        with TestClient(create_app(config)) as client:
            self._claim(client)
            response = client.post(
                "/api/v1/auth/signup", json={"username": "colleague", "password": PASSWORD}
            )
        assert response.json()["role"] == "viewer"

    def test_a_preseeded_admin_closes_registration_immediately(self, tmp_path: Path) -> None:
        config = settings_without_admin(tmp_path, admin_password="seeded-admin-password")
        with TestClient(create_app(config)) as client:
            availability = client.get("/api/v1/auth/signup").json()
            attempt = client.post(
                "/api/v1/auth/signup", json={"username": "someone", "password": PASSWORD}
            )
        assert availability["available"] is False
        assert attempt.status_code == 403


class TestValidation:
    def test_duplicate_username_is_rejected(self, tmp_path: Path) -> None:
        config = settings_without_admin(tmp_path, allow_signup=True)
        with TestClient(create_app(config)) as client:
            client.post("/api/v1/auth/signup", json={"username": "taken", "password": PASSWORD})
            client.post("/api/v1/auth/logout")
            again = client.post(
                "/api/v1/auth/signup", json={"username": "taken", "password": PASSWORD}
            )
        assert again.status_code == 409

    def test_short_password_is_rejected(self, tmp_path: Path) -> None:
        with TestClient(create_app(settings_without_admin(tmp_path))) as client:
            response = client.post(
                "/api/v1/auth/signup", json={"username": "owner", "password": "short"}
            )
        assert response.status_code == 422

    @pytest.mark.parametrize("username", ["with space", "semi;colon", "slash/es", ""])
    def test_invalid_usernames_are_rejected(self, tmp_path: Path, username: str) -> None:
        with TestClient(create_app(settings_without_admin(tmp_path))) as client:
            response = client.post(
                "/api/v1/auth/signup", json={"username": username, "password": PASSWORD}
            )
        assert response.status_code == 422

    def test_registration_is_audited(self, tmp_path: Path) -> None:
        with TestClient(create_app(settings_without_admin(tmp_path))) as client:
            client.post("/api/v1/auth/signup", json={"username": "owner", "password": PASSWORD})
            audit = client.get("/api/v1/audit?days=1").json()

        actions = [entry["action"] for entry in audit["entries"]]
        assert "auth.signup" in actions
