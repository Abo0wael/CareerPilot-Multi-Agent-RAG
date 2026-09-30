"""Tests for domain entities — validation errors (OOP: Encapsulation)."""

from __future__ import annotations

import pytest

from src.domain.entities import (
    CandidateProfile,
    ChunkSection,
    ClaimVerdict,
    ClaimVerification,
    JobChunk,
    JobMatch,
    JobPosting,
    SearchQuery,
    VerificationReport,
)
from src.domain.exceptions import EmptyFieldError, InvalidEntityError


# ── JobPosting validation ────────────────────────────────────────────

class TestJobPosting:
    """Encapsulation: JobPosting validates its own invariants."""

    def test_valid_posting(self) -> None:
        jp = JobPosting(
            job_id=1,
            title="Software Engineer",
            company_name="Acme",
            description="Build things.",
        )
        assert jp.title == "Software Engineer"
        assert jp.description == "Build things."

    def test_empty_title_raises(self) -> None:
        with pytest.raises(EmptyFieldError, match="title"):
            JobPosting(
                job_id=1,
                title="   ",
                company_name="Acme",
                description="Build things.",
            )

    def test_empty_description_raises(self) -> None:
        with pytest.raises(EmptyFieldError, match="description"):
            JobPosting(
                job_id=1,
                title="Engineer",
                company_name="Acme",
                description="",
            )

    def test_strips_whitespace(self) -> None:
        jp = JobPosting(
            job_id=1,
            title="  Engineer  ",
            company_name="Acme",
            description="  Build.  ",
        )
        assert jp.title == "Engineer"
        assert jp.description == "Build."

    def test_frozen(self) -> None:
        jp = JobPosting(
            job_id=1,
            title="Engineer",
            company_name="Acme",
            description="Build.",
        )
        with pytest.raises(AttributeError):
            jp.title = "New Title"  # type: ignore[misc]


# ── JobChunk validation ─────────────────────────────────────────────

class TestJobChunk:
    """Encapsulation: JobChunk validates chunk_id and text."""

    def test_valid_chunk(self) -> None:
        jc = JobChunk(
            chunk_id="1_req",
            job_id=1,
            section=ChunkSection.REQUIREMENTS,
            text="Must know Python.",
        )
        assert jc.section == ChunkSection.REQUIREMENTS

    def test_empty_text_raises(self) -> None:
        with pytest.raises(EmptyFieldError, match="text"):
            JobChunk(
                chunk_id="1_req",
                job_id=1,
                section=ChunkSection.REQUIREMENTS,
                text="",
            )

    def test_empty_chunk_id_raises(self) -> None:
        with pytest.raises(InvalidEntityError, match="chunk_id"):
            JobChunk(
                chunk_id="",
                job_id=1,
                section=ChunkSection.REQUIREMENTS,
                text="Must know Python.",
            )


# ── CandidateProfile validation ─────────────────────────────────────

class TestCandidateProfile:
    """Encapsulation: CandidateProfile requires non-empty raw_text."""

    def test_valid_profile(self) -> None:
        cp = CandidateProfile(raw_text="John Doe, Software Engineer.")
        assert cp.raw_text == "John Doe, Software Engineer."

    def test_empty_raw_text_raises(self) -> None:
        with pytest.raises(EmptyFieldError, match="raw_text"):
            CandidateProfile(raw_text="   ")


# ── SearchQuery validation ──────────────────────────────────────────

class TestSearchQuery:
    """Encapsulation: SearchQuery requires non-empty raw_query."""

    def test_valid_query(self) -> None:
        sq = SearchQuery(raw_query="data engineer remote")
        assert sq.raw_query == "data engineer remote"

    def test_empty_query_raises(self) -> None:
        with pytest.raises(EmptyFieldError, match="raw_query"):
            SearchQuery(raw_query="")


# ── JobMatch validation ─────────────────────────────────────────────

class TestJobMatch:
    """Encapsulation: JobMatch requires a non-empty reason."""

    def test_empty_reason_raises(self) -> None:
        jp = JobPosting(
            job_id=1,
            title="Engineer",
            company_name="Acme",
            description="Build.",
        )
        with pytest.raises(EmptyFieldError, match="reason"):
            JobMatch(job=jp, score=0.9, reason="")


# ── VerificationReport computed properties ──────────────────────────

class TestVerificationReport:
    """Tests computed properties on VerificationReport."""

    def test_counts(self) -> None:
        vr = VerificationReport(
            claims=[
                ClaimVerification(claim="a", verdict=ClaimVerdict.SUPPORTED),
                ClaimVerification(claim="b", verdict=ClaimVerdict.UNSUPPORTED),
                ClaimVerification(claim="c", verdict=ClaimVerdict.SUPPORTED),
            ]
        )
        assert vr.supported_count == 2
        assert vr.unsupported_count == 1
        assert vr.total_count == 3

    def test_empty_report(self) -> None:
        vr = VerificationReport()
        assert vr.total_count == 0
        assert vr.supported_count == 0


def test_settings_model_aliases() -> None:
    from src.infrastructure.config import Settings

    s = Settings(groq_api_key="k", groq_fast_model="fast-id", groq_agent_model="agent-id")
    assert (s.model_for("fast"), s.model_for("agent"), s.model_for(""), s.model_for("custom")) == (
        "fast-id", "agent-id", "agent-id", "custom"
    )
