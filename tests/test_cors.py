"""CORS: only configured origins may call the API, and Retry-After is readable by the browser."""

from __future__ import annotations

from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from src.agents.workflow import CareerPilotWorkflow
from src.api.dependencies import get_workflow
from src.api.main import app
from src.domain.exceptions import LLMRateLimitError
from src.infrastructure.config import ServerSettings

UI_ORIGIN = "http://localhost:3000"


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


def test_origins_parsed_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://careerpilot.vercel.app/, http://localhost:3000")
    assert ServerSettings().origins == ["https://careerpilot.vercel.app", "http://localhost:3000"]


def test_default_allows_local_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    origins = ServerSettings(_env_file=None).origins
    assert UI_ORIGIN in origins
    assert "http://127.0.0.1:3000" in origins
    assert "http://192.168.100.17:3000" not in origins


def test_custom_lan_origin_configurable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    custom_lan = "http://192.168.1.100:3000"
    monkeypatch.setenv("ALLOWED_ORIGINS", f"http://localhost:3000, {custom_lan}")
    origins = ServerSettings(_env_file=None).origins
    assert custom_lan in origins
    assert UI_ORIGIN in origins


def test_preflight_from_ui_origin_is_allowed(client: TestClient) -> None:
    response = client.options(
        "/match",
        headers={"Origin": UI_ORIGIN, "Access-Control-Request-Method": "POST",
                 "Access-Control-Request-Headers": "content-type"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == UI_ORIGIN


def test_unknown_origin_is_not_allowed(client: TestClient) -> None:
    response = client.options(
        "/match",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_retry_after_is_exposed_to_the_browser(client: TestClient) -> None:
    workflow = MagicMock(spec=CareerPilotWorkflow)
    workflow.match.side_effect = LLMRateLimitError("429")
    app.dependency_overrides[get_workflow] = lambda: workflow

    response = client.post("/match", json={"profile": {"raw_text": "Alice Python"}}, headers={"Origin": UI_ORIGIN})

    assert response.status_code == 503
    assert response.headers["access-control-allow-origin"] == UI_ORIGIN
    assert "retry-after" in response.headers["access-control-expose-headers"].lower()


def test_production_does_not_serve_ingest(monkeypatch: pytest.MonkeyPatch) -> None:
    import importlib

    import src.api.main as main_module

    monkeypatch.setenv("APP_ENV", "production")
    try:
        production_app = importlib.reload(main_module).app
        paths = set(production_app.openapi()["paths"])
        assert "/ingest" not in paths
        assert {"/health", "/profile", "/match", "/gap", "/tailor", "/pipeline"} <= paths
        with TestClient(production_app) as tc:
            assert tc.post("/ingest", headers={"X-Admin-Token": "anything"}).status_code == 404
    finally:
        monkeypatch.delenv("APP_ENV")
        importlib.reload(main_module)


def test_development_serves_ingest(client: TestClient) -> None:
    assert client.post("/ingest").status_code != 404  # exists (rejected without a valid token)
