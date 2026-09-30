"""API endpoint tests using FastAPI TestClient with dependency overrides.

Endpoints are tested against a mocked ``CareerPilotWorkflow`` and, where error
propagation matters, against the real LangGraph graph wired with fake ports.
"""

from __future__ import annotations

from typing import Generator
from unittest.mock import MagicMock

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from src.agents.gap_agent import GapAnalyzerAgent
from src.agents.graph import create_careerpilot_graph
from src.agents.matcher_agent import MatcherAgent
from src.agents.profile_agent import ProfileAgent
from src.agents.tailor_agent import TailorAgent
from src.agents.verifier_agent import VerifierAgent
from src.agents.workflow import CareerPilotWorkflow, PipelineResult
from src.api.dependencies import get_index_stats, get_ingest_jobs_use_case, get_workflow
from src.api.main import app
from src.application.analyze_gap import AnalyzeGapUseCase
from src.application.build_profile import BuildProfileUseCase
from src.application.ingest_jobs import IngestJobsUseCase
from src.application.match_jobs import MatchJobsUseCase
from src.application.tailor_cv import TailorCVUseCase
from src.application.verify_tailored_cv import VerifyTailoredCVUseCase
from src.domain.entities import (
    CandidateProfile,
    GapItem,
    GapReport,
    IndexStats,
    IngestResult,
    JobMatch,
    JobPosting,
)
from src.domain.exceptions import (
    CVParsingError,
    LLMRateLimitError,
    LLMResponseParseError,
)
from src.domain.interfaces import GapAnalyzer, IndexStatsReader
from src.infrastructure.config import Settings, get_settings
from tests.fakes import (
    FakeClaimVerifier,
    FakeCVParser,
    FakeCVTailor,
    FakeGapAnalyzer,
    FakeJobRepository,
    FakeProfileExtractor,
    FakeRetriever,
    IdentityExpander,
    PassThroughReranker,
)

ADMIN_TOKEN = "test-admin-token"


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_settings] = lambda: Settings(groq_api_key="fake", admin_token=ADMIN_TOKEN)
    with TestClient(app) as tc:
        yield tc
    app.dependency_overrides.clear()


@pytest.fixture
def mock_job() -> JobPosting:
    return JobPosting(
        job_id=42,
        title="Full Stack Engineer",
        company_name="Acme Corp",
        description="FastAPI, React, PostgreSQL",
        location="Remote",
        remote_allowed=True,
        skills=["FastAPI", "React"],
    )


def _profile_payload(profile: CandidateProfile) -> dict:
    return {"raw_text": profile.raw_text, "name": profile.name, "skills": profile.skills}


def _use_mock_workflow() -> MagicMock:
    workflow = MagicMock(spec=CareerPilotWorkflow)
    app.dependency_overrides[get_workflow] = lambda: workflow
    return workflow


def _use_fake_graph(job: JobPosting, gap: GapAnalyzer | None = None, fabrications: list[str] | None = None) -> None:
    """Wire the real graph with fake ports; the tailor always produces one real and one fabricated bullet."""
    repo = FakeJobRepository([job])
    graph = create_careerpilot_graph(
        profile_agent=ProfileAgent(BuildProfileUseCase(FakeCVParser(), FakeProfileExtractor())),
        matcher_agent=MatcherAgent(MatchJobsUseCase(FakeRetriever([]), IdentityExpander(), PassThroughReranker(), repo)),
        gap_agent=GapAnalyzerAgent(AnalyzeGapUseCase(repo, gap or FakeGapAnalyzer())),
        tailor_agent=TailorAgent(
            TailorCVUseCase(repo, FakeCVTailor(["Built APIs in FastAPI", "Led a team of 40 engineers"]))
        ),
        verifier_agent=VerifierAgent(VerifyTailoredCVUseCase(FakeClaimVerifier(fabrications or ["team of 40"]))),
    )
    workflow = CareerPilotWorkflow(graph)
    app.dependency_overrides[get_workflow] = lambda: workflow


class TestHealth:
    def test_health_uses_stats_port(self, client: TestClient) -> None:
        reader = MagicMock(spec=IndexStatsReader)
        reader.get_stats.return_value = IndexStats(total_jobs=567, total_chunks=1234, fts5_available=True)
        app.dependency_overrides[get_index_stats] = lambda: reader

        data = client.get("/health").json()
        assert data == {"status": "ok", "fts5_available": True, "total_jobs": 567, "total_chunks": 1234}


class TestProfile:
    def test_from_text(self, client: TestClient, sample_profile: CandidateProfile) -> None:
        workflow = _use_mock_workflow()
        workflow.build_profile.return_value = sample_profile

        response = client.post("/profile", data={"raw_text": "Alice\nPython engineer"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["name"] == "Alice Doe"
        workflow.build_profile.assert_called_once_with(raw_text="Alice\nPython engineer")

    def test_from_file_upload(self, client: TestClient, sample_profile: CandidateProfile) -> None:
        workflow = _use_mock_workflow()
        workflow.build_profile.return_value = sample_profile

        response = client.post("/profile", files={"file": ("cv.txt", b"Alice\nPython", "text/plain")})
        assert response.status_code == status.HTTP_200_OK
        workflow.build_profile.assert_called_once_with(file_bytes=b"Alice\nPython", filename="cv.txt")

    def test_empty_request_is_400(self, client: TestClient) -> None:
        _use_mock_workflow()
        assert client.post("/profile").status_code == status.HTTP_400_BAD_REQUEST


class TestMatch:
    def test_success(self, client: TestClient, mock_job: JobPosting, sample_profile: CandidateProfile) -> None:
        workflow = _use_mock_workflow()
        workflow.match.return_value = [JobMatch(job=mock_job, score=88.456, reason="FastAPI overlap.")]

        response = client.post("/match", json={"profile": _profile_payload(sample_profile), "top_k": 5})
        data = response.json()
        assert response.status_code == status.HTTP_200_OK
        assert data["total_matches"] == 1
        assert data["matches"][0]["job_id"] == 42
        assert data["matches"][0]["score"] == 88.46


class TestGap:
    def test_success(self, client: TestClient, sample_profile: CandidateProfile) -> None:
        workflow = _use_mock_workflow()
        workflow.analyze_gap.return_value = GapReport(
            job_id=42,
            job_title="Full Stack Engineer",
            matched_items=[GapItem(requirement="FastAPI", matched=True, evidence="Built APIs in FastAPI")],
            missing_items=[GapItem(requirement="React", matched=False)],
        )
        data = client.post("/gap", json={"profile": _profile_payload(sample_profile), "job_id": 42}).json()
        assert data["matched_items"][0]["evidence"] == "Built APIs in FastAPI"
        assert data["missing_items"][0]["requirement"] == "React"


class TestTailorThroughGraph:
    def test_unsupported_claims_are_removed_from_bullets(
        self, client: TestClient, mock_job: JobPosting, sample_profile: CandidateProfile
    ) -> None:
        _use_fake_graph(mock_job)
        response = client.post("/tailor", json={"profile": _profile_payload(sample_profile), "job_id": 42})
        data = response.json()

        assert response.status_code == status.HTTP_200_OK
        assert [b["tailored"] for b in data["bullets"]] == ["Built APIs in FastAPI"]
        assert data["bullets"][0]["verdict"] == "supported"
        assert [b["tailored"] for b in data["removed_bullets"]] == ["Led a team of 40 engineers"]
        assert data["removed_bullets"][0]["verdict"] == "unsupported"
        assert data["verification"] == {
            "total_claims": 2, "supported_claims": 1, "unsupported_claims": 1, "unverified_claims": 0
        }


class TestPipeline:
    def test_runs_full_flow(self, client: TestClient, mock_job: JobPosting, sample_profile: CandidateProfile) -> None:
        workflow = _use_mock_workflow()
        workflow.run_pipeline.return_value = PipelineResult(
            profile=sample_profile,
            matches=[JobMatch(job=mock_job, score=90, reason="fit")],
            target_job_id=42,
            gap_report=GapReport(job_id=42, job_title="Full Stack Engineer"),
        )
        response = client.post("/pipeline", data={"raw_text": "Alice\nPython", "preferences": "remote"})
        data = response.json()

        assert response.status_code == status.HTTP_200_OK
        assert data["target_job_id"] == 42
        assert data["matches"]["total_matches"] == 1
        assert data["gap"]["job_id"] == 42
        assert data["tailored_cv"] is None
        workflow.run_pipeline.assert_called_once_with(raw_text="Alice\nPython", preferences="remote", top_k=10)


class TestErrorsReachHandlers:
    """Errors raised inside graph nodes must reach the HTTP layer, not be swallowed."""

    def _gap_raising(self, error: Exception) -> GapAnalyzer:
        class Failing(GapAnalyzer):
            def analyze(self, profile, job):
                raise error

        return Failing()

    def test_rate_limit_inside_graph_is_503(
        self, client: TestClient, mock_job: JobPosting, sample_profile: CandidateProfile
    ) -> None:
        _use_fake_graph(mock_job, gap=self._gap_raising(LLMRateLimitError("429")))
        response = client.post("/gap", json={"profile": _profile_payload(sample_profile), "job_id": 42})
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        assert response.headers["Retry-After"] == "30"

    def test_unparseable_llm_output_is_502(
        self, client: TestClient, mock_job: JobPosting, sample_profile: CandidateProfile
    ) -> None:
        _use_fake_graph(mock_job, gap=self._gap_raising(LLMResponseParseError("raw", "bad json")))
        response = client.post("/gap", json={"profile": _profile_payload(sample_profile), "job_id": 42})
        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    def test_unknown_job_is_404(self, client: TestClient, mock_job: JobPosting, sample_profile: CandidateProfile) -> None:
        _use_fake_graph(mock_job)
        response = client.post("/tailor", json={"profile": _profile_payload(sample_profile), "job_id": 999})
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "not found" in response.json()["detail"].lower()

    def test_cv_parsing_error_is_400(self, client: TestClient) -> None:
        workflow = _use_mock_workflow()
        workflow.build_profile.side_effect = CVParsingError("bad.pdf", "Corrupted PDF file header")
        response = client.post("/profile", files={"file": ("bad.pdf", b"garbage", "application/pdf")})
        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert "parsing failed" in response.json()["detail"].lower()

    def test_rate_limit_from_mocked_match_is_503(self, client: TestClient, sample_profile: CandidateProfile) -> None:
        workflow = _use_mock_workflow()
        workflow.match.side_effect = LLMRateLimitError("429")
        response = client.post("/match", json={"profile": _profile_payload(sample_profile)})
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


class TestIngestAuth:
    @pytest.fixture
    def ingest_use_case(self) -> MagicMock:
        use_case = MagicMock(spec=IngestJobsUseCase)
        use_case.execute.return_value = IngestResult(jobs_ingested=3, chunks_indexed=9)
        app.dependency_overrides[get_ingest_jobs_use_case] = lambda: use_case
        return use_case

    def test_missing_token_is_401(self, client: TestClient, ingest_use_case: MagicMock) -> None:
        assert client.post("/ingest").status_code == status.HTTP_401_UNAUTHORIZED
        ingest_use_case.execute.assert_not_called()

    def test_wrong_token_is_401(self, client: TestClient, ingest_use_case: MagicMock) -> None:
        response = client.post("/ingest", headers={"X-Admin-Token": "wrong"})
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        ingest_use_case.execute.assert_not_called()

    def test_disabled_when_no_token_configured(self, client: TestClient, ingest_use_case: MagicMock) -> None:
        app.dependency_overrides[get_settings] = lambda: Settings(groq_api_key="fake", admin_token="")
        response = client.post("/ingest", headers={"X-Admin-Token": ""})
        assert response.status_code == status.HTTP_403_FORBIDDEN
        ingest_use_case.execute.assert_not_called()

    def test_valid_token_rebuilds_index(self, client: TestClient, ingest_use_case: MagicMock) -> None:
        response = client.post("/ingest", headers={"X-Admin-Token": ADMIN_TOKEN})
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"status": "success", "jobs_ingested": 3, "chunks_indexed": 9}
        ingest_use_case.execute.assert_called_once_with(clear_existing=True)
