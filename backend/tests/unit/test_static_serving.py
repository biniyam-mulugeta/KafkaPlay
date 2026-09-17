"""Serving the built frontend bundle.

These exist because of a real escape: the SPA catch-all route is only
registered when the static directory is present. No local test had one, so the
route was never constructed, and the image -- where the bundle always exists --
crashed on startup with `FastAPIError: Invalid args for response field`.

Anything that only runs when the bundle is present belongs in this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from tests.conftest import TEST_ADMIN_PASSWORD

INDEX_HTML = "<!doctype html><title>Offsetscope</title><div id='root'></div>"


@pytest.fixture
def bundled_settings(settings: Settings, tmp_path: Path) -> Settings:
    """Settings pointing at a directory shaped like a real Vite build."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    (static / "index.html").write_text(INDEX_HTML, encoding="utf-8")
    (static / "assets" / "index-abc123.js").write_text("console.log(1)", encoding="utf-8")
    (static / "assets" / "index-abc123.css").write_text("body{}", encoding="utf-8")
    return settings.model_copy(update={"static_dir": static})


@pytest.fixture
def bundled_client(bundled_settings: Settings):
    with TestClient(create_app(bundled_settings)) as client:
        yield client


class TestAppStartsWithABundle:
    def test_app_builds_when_static_is_present(self, bundled_settings: Settings) -> None:
        # The original bug: constructing the app raised FastAPIError because
        # the catch-all's `FileResponse | JSONResponse` return annotation was
        # treated as a Pydantic response model.
        create_app(bundled_settings)

    def test_app_builds_when_static_is_absent(self, settings: Settings) -> None:
        create_app(settings)


class TestSpaRouting:
    def test_root_serves_index(self, bundled_client: TestClient) -> None:
        response = bundled_client.get("/")
        assert response.status_code == 200
        assert "Offsetscope" in response.text

    def test_deep_link_serves_index(self, bundled_client: TestClient) -> None:
        # Client-side routes must return the shell so the router can take over.
        response = bundled_client.get("/topics")
        assert response.status_code == 200
        assert "root" in response.text

    def test_hashed_asset_is_served(self, bundled_client: TestClient) -> None:
        response = bundled_client.get("/assets/index-abc123.js")
        assert response.status_code == 200
        assert "console.log" in response.text

    def test_unknown_api_path_is_json_404_not_the_shell(self, bundled_client: TestClient) -> None:
        response = bundled_client.get("/api/v1/does-not-exist")
        assert response.status_code == 404
        assert response.json()["detail"] == "not found"

    def test_unknown_ws_path_is_json_404(self, bundled_client: TestClient) -> None:
        response = bundled_client.get("/ws/nope")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")

    def test_real_api_routes_still_win(self, bundled_client: TestClient) -> None:
        # The catch-all is registered last; it must not shadow the API.
        assert bundled_client.get("/api/v1/meta").status_code == 200
        assert bundled_client.get("/healthz").json()["status"] == "ok"

    def test_api_still_works_after_the_catch_all(self, bundled_client: TestClient) -> None:
        login = bundled_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
        )
        assert login.status_code == 200

    def test_path_traversal_falls_back_to_the_shell(self, bundled_client: TestClient) -> None:
        # Must never serve a file from outside the bundle.
        response = bundled_client.get("/../../../../etc/passwd")
        assert response.status_code == 200
        assert "root:x:" not in response.text

    def test_brand_assets_are_mounted(self, bundled_client: TestClient) -> None:
        # The theme directory is served even though the crest itself is absent.
        assert bundled_client.get("/brand/theme.json").status_code == 200
