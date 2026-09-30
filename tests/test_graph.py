"""LangGraph workflow tests: every request type runs exactly the intended agents."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.agents.gap_agent import GapAnalyzerAgent
from src.agents.graph import (
    GAP_NODE,
    MATCHER_NODE,
    PROFILE_NODE,
    TAILOR_NODE,
    create_careerpilot_graph,
    route_after_matcher,
    route_request,
)
from src.agents.matcher_agent import MatcherAgent
from src.agents.profile_agent import ProfileAgent
from src.agents.tailor_agent import TailorAgent
from src.agents.verifier_agent import VerifierAgent
from src.agents.workflow import CareerPilotWorkflow
from src.application.analyze_gap import AnalyzeGapUseCase
from src.application.build_profile import BuildProfileUseCase
from src.application.match_jobs import MatchJobsUseCase
from src.application.tailor_cv import TailorCVUseCase
from src.application.verify_tailored_cv import VerifyTailoredCVUseCase
from src.domain.entities import CandidateProfile, ChunkSection, JobChunk, JobPosting, ScoredChunk
from src.domain.exceptions import LLMRateLimitError, WorkflowStateError
from src.domain.interfaces import GapAnalyzer
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


@dataclass
class Harness:
    workflow: CareerPilotWorkflow
    extractor: FakeProfileExtractor
    retriever: FakeRetriever
    gap: GapAnalyzer
    tailor: FakeCVTailor
    verifier: FakeClaimVerifier


def _harness(job: JobPosting, chunks: list[ScoredChunk], gap: GapAnalyzer | None = None) -> Harness:
    repo = FakeJobRepository([job])
    extractor, retriever = FakeProfileExtractor(), FakeRetriever(chunks)
    gap = gap or FakeGapAnalyzer()
    tailor, verifier = FakeCVTailor(), FakeClaimVerifier()
    graph = create_careerpilot_graph(
        profile_agent=ProfileAgent(BuildProfileUseCase(FakeCVParser(), extractor)),
        matcher_agent=MatcherAgent(MatchJobsUseCase(retriever, IdentityExpander(), PassThroughReranker(), repo)),
        gap_agent=GapAnalyzerAgent(AnalyzeGapUseCase(repo, gap)),
        tailor_agent=TailorAgent(TailorCVUseCase(repo, tailor)),
        verifier_agent=VerifierAgent(VerifyTailoredCVUseCase(verifier)),
    )
    return Harness(CareerPilotWorkflow(graph), extractor, retriever, gap, tailor, verifier)


@pytest.fixture
def harness(sample_job: JobPosting) -> Harness:
    chunk = JobChunk(chunk_id="c1", job_id=sample_job.job_id, section=ChunkSection.REQUIREMENTS, text="Python")
    return _harness(sample_job, [ScoredChunk(chunk=chunk, score=10.0)])


def test_profile_request_runs_only_profile_agent(harness: Harness) -> None:
    profile = harness.workflow.build_profile(raw_text="Alice\nPython developer")
    assert profile.raw_text == "Alice\nPython developer"
    assert harness.retriever.searched_queries == []
    assert harness.gap.calls == [] and harness.tailor.calls == [] and harness.verifier.calls == []


def test_profile_request_accepts_file_bytes(harness: Harness) -> None:
    assert harness.workflow.build_profile(file_bytes=b"From a file", filename="cv.txt").raw_text == "From a file"


def test_match_request_runs_only_matcher(harness: Harness, sample_profile: CandidateProfile) -> None:
    matches = harness.workflow.match(sample_profile)
    assert [m.job.job_id for m in matches] == [101]
    assert harness.extractor.calls == []
    assert harness.gap.calls == [] and harness.tailor.calls == []


def test_gap_request_does_not_run_tailor_or_verifier(harness: Harness, sample_profile: CandidateProfile) -> None:
    report = harness.workflow.analyze_gap(sample_profile, 101)
    assert report.job_id == 101
    assert harness.gap.calls == [101]
    assert harness.tailor.calls == []
    assert harness.verifier.calls == []
    assert harness.extractor.calls == [] and harness.retriever.searched_queries == []


def test_tailor_request_always_runs_verifier(harness: Harness, sample_profile: CandidateProfile) -> None:
    tailored = harness.workflow.tailor(sample_profile, 101)
    assert harness.tailor.calls == [101]
    assert harness.verifier.calls == [1]
    assert tailored.verification is not None
    assert harness.gap.calls == []


def test_pipeline_runs_every_agent_in_order(harness: Harness) -> None:
    result = harness.workflow.run_pipeline(raw_text="Alice\nPython developer", preferences="remote")
    assert result.profile.raw_text == "Alice\nPython developer"
    assert [m.job.job_id for m in result.matches] == [101]
    assert result.target_job_id == 101
    assert result.gap_report.job_id == 101
    assert result.tailored_cv.verification.supported_count == 1


def test_pipeline_stops_after_matcher_when_nothing_matches(sample_job: JobPosting) -> None:
    h = _harness(sample_job, chunks=[])
    result = h.workflow.run_pipeline(raw_text="Alice\nCobol")
    assert result.matches == []
    assert result.gap_report is None and result.tailored_cv is None
    assert h.gap.calls == [] and h.tailor.calls == []


def test_llm_errors_propagate_out_of_the_graph(sample_job: JobPosting, sample_profile: CandidateProfile) -> None:
    class RateLimitedGap(GapAnalyzer):
        def analyze(self, profile, job):
            raise LLMRateLimitError("429")

    h = _harness(sample_job, chunks=[], gap=RateLimitedGap())
    with pytest.raises(LLMRateLimitError):
        h.workflow.analyze_gap(sample_profile, 101)


def test_routing_is_driven_by_request_type() -> None:
    assert route_request({"request_type": "profile"}) == PROFILE_NODE
    assert route_request({"request_type": "pipeline"}) == PROFILE_NODE
    assert route_request({"request_type": "match"}) == MATCHER_NODE
    assert route_request({"request_type": "gap"}) == GAP_NODE
    assert route_request({"request_type": "tailor"}) == TAILOR_NODE
    with pytest.raises(WorkflowStateError):
        route_request({"request_type": "coach"})


def test_routers_do_not_mutate_state(sample_job: JobPosting) -> None:
    from src.domain.entities import JobMatch

    state = {"request_type": "pipeline", "matches": [JobMatch(job=sample_job, score=1.0, reason="r")]}
    snapshot = dict(state)
    route_after_matcher(state)
    assert state == snapshot


def test_node_without_required_state_fails_loudly(harness: Harness) -> None:
    with pytest.raises(WorkflowStateError):
        harness.workflow.build_profile(raw_text="")
