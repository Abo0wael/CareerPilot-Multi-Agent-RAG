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
from src.infrastructure.config import CorsSettings

UI_ORIGIN = "http://localhost:3000"


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


def test_origins_parsed_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALLOWED_ORIGINS", "https://careerpilot.vercel.app/, http://localhost:3000")
    assert CorsSettings().origins == ["https://careerpilot.vercel.app", "http://localhost:3000"]


def test_default_allows_local_ui(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    assert UI_ORIGIN in CorsSettings(_env_file=None).origins


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
