"""Opt-in protection for a public deployment: rate limit (429), upload size limit (413), /health readiness (503)."""

from __future__ import annotations

from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.agents.workflow import CareerPilotWorkflow
from src.api.dependencies import get_index_stats, get_workflow
from src.api.main import app
from src.domain.entities import CandidateProfile, IndexStats
from src.domain.interfaces import IndexStatsReader
from src.infrastructure.config import Settings, get_settings

UI_ORIGIN = "http://localhost:3000"


def _client_with(**settings: object) -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_settings] = lambda: Settings(groq_api_key="fake", **settings)
    with TestClient(app) as tc:  # leaving the context clears app state, including rate-limit counters
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    yield from _client_with()


@pytest.fixture
def limited_client() -> Generator[TestClient, None, None]:
    yield from _client_with(rate_limit="2/minute")


def _use_mock_workflow(profile: CandidateProfile) -> MagicMock:
    workflow = MagicMock(spec=CareerPilotWorkflow)
    workflow.build_profile.return_value = profile
    workflow.match.return_value = []
    app.dependency_overrides[get_workflow] = lambda: workflow
    return workflow


def _use_stats(total_jobs: int) -> None:
    reader = MagicMock(spec=IndexStatsReader)
    reader.get_stats.return_value = IndexStats(total_jobs=total_jobs, total_chunks=0, fts5_available=True)
    app.dependency_overrides[get_index_stats] = lambda: reader


class TestRateLimit:
    def test_disabled_by_default(self, client: TestClient, sample_profile: CandidateProfile) -> None:
        _use_mock_workflow(sample_profile)
        codes = [client.post("/profile", data={"raw_text": "Alice"}).status_code for _ in range(5)]
        assert codes == [status.HTTP_200_OK] * 5

    def test_exceeding_the_limit_is_429_with_retry_after(
        self, limited_client: TestClient, sample_profile: CandidateProfile
    ) -> None:
        _use_mock_workflow(sample_profile)
        codes = [limited_client.post("/profile", data={"raw_text": "Alice"}).status_code for _ in range(2)]
        blocked = limited_client.post("/profile", data={"raw_text": "Alice"}, headers={"Origin": UI_ORIGIN})

        assert codes == [status.HTTP_200_OK] * 2
        assert blocked.status_code == status.HTTP_429_TOO_MANY_REQUESTS
        assert "Rate limit exceeded" in blocked.json()["detail"]
        assert 1 <= int(blocked.headers["retry-after"]) <= 60
        # The browser can read the wait (CORS exposes Retry-After on the error response too).
        assert blocked.headers["access-control-allow-origin"] == UI_ORIGIN
        assert "retry-after" in blocked.headers["access-control-expose-headers"].lower()

    def test_limit_is_counted_per_endpoint(self, limited_client: TestClient, sample_profile: CandidateProfile) -> None:
        _use_mock_workflow(sample_profile)
        for _ in range(2):
            limited_client.post("/profile", data={"raw_text": "Alice"})
        match = limited_client.post("/match", json={"profile": {"raw_text": "Alice Python"}})
        assert match.status_code == status.HTTP_200_OK

    def test_health_is_never_rate_limited(self, limited_client: TestClient) -> None:
        _use_stats(total_jobs=10)
        codes = {limited_client.get("/health").status_code for _ in range(5)}
        assert codes == {status.HTTP_200_OK}

    def test_malformed_limit_is_rejected_at_start_up(self) -> None:
        with pytest.raises(ValidationError):
            Settings(groq_api_key="fake", rate_limit="10 per banana")


class TestUploadLimit:
    @pytest.fixture
    def small_limit_client(self) -> Generator[TestClient, None, None]:
        yield from _client_with(max_upload_mb=0.001)  # 1,048 bytes

    def test_oversized_file_is_413_before_parsing(
        self, small_limit_client: TestClient, sample_profile: CandidateProfile
    ) -> None:
        workflow = _use_mock_workflow(sample_profile)
        response = small_limit_client.post("/profile", files={"file": ("cv.txt", b"x" * 2000, "text/plain")})

        assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
        assert "too large" in response.json()["detail"]
        workflow.build_profile.assert_not_called()

    def test_oversized_file_is_413_on_pipeline(
        self, small_limit_client: TestClient, sample_profile: CandidateProfile
    ) -> None:
        workflow = _use_mock_workflow(sample_profile)
        response = small_limit_client.post("/pipeline", files={"file": ("cv.txt", b"x" * 2000, "text/plain")})
        assert response.status_code == status.HTTP_413_CONTENT_TOO_LARGE
        workflow.run_pipeline.assert_not_called()

    def test_file_at_the_limit_is_accepted(
        self, small_limit_client: TestClient, sample_profile: CandidateProfile
    ) -> None:
        workflow = _use_mock_workflow(sample_profile)
        limit = int(0.001 * 1024 * 1024)
        response = small_limit_client.post("/profile", files={"file": ("cv.txt", b"x" * limit, "text/plain")})
        assert response.status_code == status.HTTP_200_OK
        workflow.build_profile.assert_called_once()

    def test_default_limit_is_5_mb(self) -> None:
        assert Settings(groq_api_key="fake", _env_file=None).max_upload_mb == 5


class TestHealthReadiness:
    def test_empty_index_is_503_and_unavailable(self, client: TestClient) -> None:
        _use_stats(total_jobs=0)
        response = client.get("/health")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json() == {"status": "unavailable", "fts5_available": True, "total_jobs": 0, "total_chunks": 0}

    def test_missing_database_file_is_503(self, tmp_path) -> None:
        """The real SQLite wiring: a missing index file must not look healthy."""
        app.dependency_overrides[get_settings] = lambda: Settings(
            groq_api_key="fake", index_path=tmp_path / "missing" / "careerpilot.db"
        )
        with TestClient(app) as tc:
            response = tc.get("/health")
        app.dependency_overrides.clear()
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.json()["total_jobs"] == 0
        assert response.json()["status"] == "unavailable"

    def test_populated_index_is_200(self, client: TestClient) -> None:
        _use_stats(total_jobs=13975)
        assert client.get("/health").status_code == status.HTTP_200_OK
