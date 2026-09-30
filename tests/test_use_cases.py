"""Application use cases tested against fake ports only (Dependency Inversion)."""

from __future__ import annotations

import pytest

from src.application.analyze_gap import AnalyzeGapUseCase
from src.application.build_profile import BuildProfileUseCase
from src.application.match_jobs import MatchJobsUseCase
from src.application.tailor_cv import TailorCVUseCase
from src.application.verify_tailored_cv import VerifyTailoredCVUseCase
from src.domain.entities import (
    CandidateProfile,
    ChunkSection,
    ClaimVerdict,
    JobChunk,
    JobPosting,
    ScoredChunk,
)
from src.domain.exceptions import JobNotFoundError
from src.infrastructure.retrieval.expander import GroqQueryExpander
from src.infrastructure.retrieval.reranker import GroqReranker
from tests.fakes import (
    FakeClaimVerifier,
    FakeCVParser,
    FakeCVTailor,
    FakeGapAnalyzer,
    FakeJobRepository,
    FakeLLMClient,
    FakeProfileExtractor,
    FakeRetriever,
    PassThroughReranker,
)


def test_match_jobs_orchestration(sample_job: JobPosting, sample_profile: CandidateProfile) -> None:
    chunk = JobChunk(chunk_id="c1", job_id=101, section=ChunkSection.REQUIREMENTS, text="Python FastAPI Docker")
    use_case = MatchJobsUseCase(
        retriever=FakeRetriever([ScoredChunk(chunk=chunk, score=8.5)]),
        query_expander=GroqQueryExpander(FakeLLMClient(json_response={"expanded_terms": ["FastAPI"]})),
        reranker=GroqReranker(
            FakeLLMClient(json_response={"rankings": [{"job_id": 101, "score": 95.0, "reason": "Perfect fit"}]})
        ),
        job_repository=FakeJobRepository([sample_job]),
        top_n=10,
        top_k=5,
    )
    results = use_case.execute(profile=sample_profile)
    assert [(m.job.job_id, m.score, m.reason) for m in results] == [(101, 95.0, "Perfect fit")]


def test_build_profile_from_file_and_text() -> None:
    extractor = FakeProfileExtractor()
    use_case = BuildProfileUseCase(cv_parser=FakeCVParser(), profile_extractor=extractor)
    assert use_case.execute(b"Jane from file", "cv.txt").raw_text == "Jane from file"
    assert use_case.execute_from_text("Jane from text").raw_text == "Jane from text"
    assert extractor.calls == ["Jane from file", "Jane from text"]


def test_analyze_gap_loads_job_then_analyzes(sample_job: JobPosting, sample_profile: CandidateProfile) -> None:
    analyzer = FakeGapAnalyzer()
    report = AnalyzeGapUseCase(FakeJobRepository([sample_job]), analyzer).execute(sample_profile, 101)
    assert report.job_id == 101
    assert analyzer.calls == [101]


def test_unknown_job_raises_and_skips_llm(sample_profile: CandidateProfile) -> None:
    analyzer = FakeGapAnalyzer()
    with pytest.raises(JobNotFoundError):
        AnalyzeGapUseCase(FakeJobRepository([]), analyzer).execute(sample_profile, 999)
    assert analyzer.calls == []


def test_tailor_then_verify_removes_fabrication(sample_job: JobPosting, sample_profile: CandidateProfile) -> None:
    tailored = TailorCVUseCase(
        FakeJobRepository([sample_job]),
        FakeCVTailor(["Built REST APIs with FastAPI", "Certified AWS Solutions Architect"]),
    ).execute(sample_profile, 101)

    verified = VerifyTailoredCVUseCase(FakeClaimVerifier(fabrications=["AWS"])).execute(
        sample_profile.raw_text, tailored
    )

    assert [b.tailored for b in verified.bullets] == ["Built REST APIs with FastAPI"]
    assert [b.tailored for b in verified.removed_bullets] == ["Certified AWS Solutions Architect"]
    assert verified.removed_bullets[0].verdict == ClaimVerdict.UNSUPPORTED
    assert verified.verification.total_count == 2


def test_weighted_expansion_keeps_original_terms_dominant(sample_profile: CandidateProfile) -> None:
    jobs = [JobPosting(job_id=i, title=f"Job {i}", company_name="Co", description="d") for i in (1, 2)]
    orig_hit = ScoredChunk(JobChunk(chunk_id="a", job_id=1, section=ChunkSection.REQUIREMENTS, text="x"), 10.0)
    exp_hit = ScoredChunk(JobChunk(chunk_id="b", job_id=2, section=ChunkSection.REQUIREMENTS, text="y"), 15.0)

    class SplitRetriever(FakeRetriever):
        def search(self, query, top_n=50, sections=None, excluded_sections=None):
            self.searched_queries.append(query)
            return [orig_hit] if query.raw_query == "Python FastAPI Docker PostgreSQL" else [exp_hit]

    retriever = SplitRetriever([])
    use_case = MatchJobsUseCase(
        retriever=retriever,
        query_expander=GroqQueryExpander(FakeLLMClient(json_response={"expanded_terms": ["Kubernetes"]})),
        reranker=PassThroughReranker(),
        job_repository=FakeJobRepository(jobs),
        expansion_weight=0.5,
    )
    results = use_case.execute(sample_profile)

    assert [q.raw_query for q in retriever.searched_queries] == ["Python FastAPI Docker PostgreSQL", "Kubernetes"]
    # 10 (original) beats 0.5 * 15 = 7.5 (expansion-only match).
    assert [(m.job.job_id, m.score) for m in results] == [(1, 10.0), (2, 7.5)]
