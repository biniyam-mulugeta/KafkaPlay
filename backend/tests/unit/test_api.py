from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import REPO_ROOT, TEST_ADMIN_PASSWORD


class TestHealth:
    def test_healthz(self, client: TestClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_healthz_needs_no_auth(self, client: TestClient) -> None:
        # A container probe must not have to log in.
        assert client.get("/healthz").status_code == 200

    def test_readyz(self, client: TestClient) -> None:
        response = client.get("/readyz")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ready"
        names = {check["name"] for check in body["checks"]}
        assert names == {"database", "clusters", "theme"}

    def test_readyz_reports_missing_theme(self, settings: Settings, tmp_path: Path) -> None:
        broken = settings.model_copy(update={"themes_dir": tmp_path / "nowhere"})
        with TestClient(create_app(broken)) as client:
            response = client.get("/readyz")
        assert response.status_code == 503
        theme = next(c for c in response.json()["checks"] if c["name"] == "theme")
        assert theme["ok"] is False


class TestAuthFlow:
    def test_me_requires_authentication(self, client: TestClient) -> None:
        assert client.get("/api/v1/auth/me").status_code == 401

    def test_login_success(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["username"] == "admin"
        assert body["role"] == "admin"
        assert body["csrf_token"]

    def test_login_wrong_password(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong-but-long-enough"},
        )
        assert response.status_code == 401
        # The message must not reveal whether the account exists.
        assert response.json()["detail"] == "invalid username or password"

    def test_login_unknown_user_same_message(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": "nobody", "password": "wrong-but-long-enough"},
        )
        assert response.status_code == 401
        assert response.json()["detail"] == "invalid username or password"

    def test_me_after_login(self, authed_client: TestClient) -> None:
        response = authed_client.get("/api/v1/auth/me")
        assert response.status_code == 200
        assert response.json()["username"] == "admin"

    def test_logout_clears_session(self, authed_client: TestClient) -> None:
        assert authed_client.post("/api/v1/auth/logout").status_code == 204
        assert authed_client.get("/api/v1/auth/me").status_code == 401


class TestCsrfEnforcement:
    def test_logout_is_deliberately_exempt(self, client: TestClient) -> None:
        # logout does not depend on get_principal: it only clears a cookie, so
        # a forged cross-site logout achieves nothing an attacker wants. Every
        # *guarded* write endpoint goes through get_principal, which enforces
        # the header -- covered end-to-end in M5 when write endpoints land.
        login = client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
        )
        assert login.status_code == 200
        assert client.post("/api/v1/auth/logout").status_code == 204

    def test_safe_request_needs_no_csrf(self, client: TestClient) -> None:
        client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
        )
        assert client.get("/api/v1/clusters").status_code == 200


class TestMeta:
    def test_meta_is_public(self, client: TestClient) -> None:
        # The login screen needs branding before anyone has authenticated.
        response = client.get("/api/v1/meta")
        assert response.status_code == 200

    def test_meta_reports_theme(self, client: TestClient) -> None:
        body = client.get("/api/v1/meta").json()
        assert body["theme"]["name"] == "kafkaplay"
        assert body["theme"]["product_name"] == "KafkaPlay"
        assert body["theme"]["colors"]["light"]["brand"] == "#054434"

    def test_missing_logo_degrades_to_none(self, client: TestClient) -> None:
        # The crest is git-ignored, so the theme must not advertise a broken URL.
        assert client.get("/api/v1/meta").json()["theme"]["logo"] is None

    def test_neutral_theme_loads(self, settings: Settings) -> None:
        neutral = settings.model_copy(update={"theme": "neutral"})
        with TestClient(create_app(neutral)) as client:
            body = client.get("/api/v1/meta").json()
        assert body["theme"]["product_name"] == "Kafka Console"

    def test_broken_theme_falls_back(self, settings: Settings, tmp_path: Path) -> None:
        bad = tmp_path / "themes" / "bad"
        bad.mkdir(parents=True)
        (bad / "theme.json").write_text("{not json", encoding="utf-8")
        broken = settings.model_copy(update={"themes_dir": tmp_path / "themes", "theme": "bad"})
        with TestClient(create_app(broken)) as client:
            response = client.get("/api/v1/meta")
        assert response.status_code == 200
        assert response.json()["theme"]["product_name"] == "KafkaPlay"

    def test_meta_reports_flags(self, client: TestClient) -> None:
        body = client.get("/api/v1/meta").json()
        assert body["auth_mode"] == "local"
        assert body["insecure_no_auth"] is False
        assert body["read_only"] is False
        assert body["masking_enabled"] is True
        assert "ipv4" in body["mask_presets"]


class TestClustersEndpoint:
    def test_requires_authentication(self, client: TestClient) -> None:
        assert client.get("/api/v1/clusters").status_code == 401

    def test_empty_when_no_config_file(self, authed_client: TestClient) -> None:
        # A first run with no clusters.yaml is a valid state, not an error.
        response = authed_client.get("/api/v1/clusters")
        assert response.status_code == 200
        assert response.json()["clusters"] == []

    def test_lists_configured_clusters_without_secrets(self, settings: Settings) -> None:
        settings.clusters_file.write_text(
            """
            clusters:
              - name: prod
                label: Production
                bootstrap_servers: broker:9092
                security_protocol: SASL_SSL
                read_only: true
                sasl:
                  mechanism: SCRAM-SHA-512
                  username: svc
                  password: super-secret
            """,
            encoding="utf-8",
        )
        with TestClient(create_app(settings)) as client:
            client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
            )
            response = client.get("/api/v1/clusters")

        assert response.status_code == 200
        raw = response.text
        # Credentials must never leave the backend.
        assert "super-secret" not in raw
        assert "svc" not in raw

        cluster = response.json()["clusters"][0]
        assert cluster["name"] == "prod"
        assert cluster["label"] == "Production"
        assert cluster["read_only"] is True
        assert cluster["sasl_mechanism"] == "SCRAM-SHA-512"


class TestNoAuthMode:
    def _no_auth_settings(self, settings: Settings) -> Settings:
        return Settings(
            auth_mode="none",
            console_host="127.0.0.1",
            session_secret="",
            themes_dir=REPO_ROOT / "themes",
            theme="kafkaplay",
            database_url=settings.database_url,
            clusters_file=settings.clusters_file,
            log_format="console",
        )

    def test_everything_is_open(self, settings: Settings) -> None:
        with TestClient(create_app(self._no_auth_settings(settings))) as client:
            assert client.get("/api/v1/clusters").status_code == 200
            me = client.get("/api/v1/auth/me").json()
        assert me["username"] == "anonymous"
        assert me["role"] == "admin"

    def test_login_is_refused(self, settings: Settings) -> None:
        with TestClient(create_app(self._no_auth_settings(settings))) as client:
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
            )
        assert response.status_code == 400
        assert "AUTH_MODE=none" in response.json()["detail"]

    def test_meta_flags_the_insecure_mode(self, settings: Settings) -> None:
        with TestClient(create_app(self._no_auth_settings(settings))) as client:
            body = client.get("/api/v1/meta").json()
        assert body["insecure_no_auth"] is True


class TestOpenApi:
    def test_spec_is_published(self, client: TestClient) -> None:
        response = client.get("/api/openapi.json")
        assert response.status_code == 200
        assert "/api/v1/clusters" in response.json()["paths"]

    def test_docs_are_served(self, client: TestClient) -> None:
        assert client.get("/api/docs").status_code == 200
