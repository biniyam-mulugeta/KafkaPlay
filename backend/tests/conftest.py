from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

REPO_ROOT = Path(__file__).resolve().parents[2]

TEST_SESSION_SECRET = "x" * 48
TEST_ADMIN_PASSWORD = "correct-horse-battery"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        app_name="KafkaPlay",
        theme="kafkaplay",
        themes_dir=REPO_ROOT / "themes",
        auth_mode="local",
        session_secret=TEST_SESSION_SECRET,
        admin_username="admin",
        admin_password=TEST_ADMIN_PASSWORD,
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        clusters_file=tmp_path / "clusters.yaml",
        log_format="console",
    )


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


@pytest.fixture
def authed_client(client: TestClient) -> TestClient:
    response = client.post(
        "/api/v1/auth/login",
        json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
    )
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    return client


@pytest.fixture(scope="session")
def bootstrap_servers() -> str:
    """Live broker for integration tests, or skip.

    Integration tests never spin up a broker themselves; they use one supplied
    via KAFKAPLAY_TEST_BOOTSTRAP so the suite stays green for contributors who
    have no broker at hand.
    """
    value = os.environ.get("KAFKAPLAY_TEST_BOOTSTRAP")
    if not value:
        pytest.skip("KAFKAPLAY_TEST_BOOTSTRAP is not set; skipping integration test")
    return value
