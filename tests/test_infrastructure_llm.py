"""Tests for infrastructure adapters: CV parser, Groq client, and the Groq-backed ports.

All LLM responses come from ``FakeLLMClient`` or a mocked Groq SDK; nothing calls Groq.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import groq
import httpx
import pytest
from pypdf import PdfWriter

from src.domain.entities import (
    CandidateProfile,
    ClaimVerdict,
    JobMatch,
    JobPosting,
    SearchQuery,
    TailoredBullet,
)
from src.domain.exceptions import CVParsingError, LLMError, LLMRateLimitError, LLMResponseParseError
from src.infrastructure.config import Settings
from src.infrastructure.llm.claim_verifier import GroqClaimVerifier
from src.infrastructure.llm.client import GroqClient
from src.infrastructure.llm.cv_tailor import GroqCVTailor
from src.infrastructure.llm.formatting import relevant_job_text
from src.infrastructure.llm.gap_analyzer import GroqGapAnalyzer
from src.infrastructure.llm.profile_extractor import GroqProfileExtractor
from src.infrastructure.parsing.cv_parser import UniversalCVParser
from src.infrastructure.retrieval.expander import GroqQueryExpander
from src.infrastructure.retrieval.reranker import GroqReranker
from tests.fakes import FakeLLMClient


# ── CV parser ────────────────────────────────────────────────────────

class TestUniversalCVParser:
    def test_parse_plain_text(self) -> None:
        result = UniversalCVParser().parse(b"John Doe\nSoftware Engineer\nSkills: Python, Go", "resume.txt")
        assert "John Doe" in result
        assert "Python" in result

    def test_blank_pdf_raises(self) -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=72, height=72)
        buf = io.BytesIO()
        writer.write(buf)
        with pytest.raises(CVParsingError):
            UniversalCVParser().parse(buf.getvalue(), "empty.pdf")

    def test_parse_empty_bytes_raises(self) -> None:
        with pytest.raises(CVParsingError):
            UniversalCVParser().parse(b"", "empty.txt")

    def test_unsupported_format_raises(self) -> None:
        with pytest.raises(CVParsingError):
            UniversalCVParser().parse(b"\x00\x01\x02\x03\x04", "image.png")


# ── Groq client ──────────────────────────────────────────────────────

def _mock_groq(content: str) -> MagicMock:
    mock_groq = MagicMock()
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    response.usage.prompt_tokens = 10
    response.usage.completion_tokens = 5
    response.usage.total_tokens = 15
    mock_groq.chat.completions.create.return_value = response
    return mock_groq


class TestGroqClient:
    def test_caching_and_metrics(self, tmp_path) -> None:
        settings = Settings(groq_api_key="fake", llm_cache_dir=tmp_path / "cache", llm_max_retries=1)
        mock_groq = _mock_groq("Cached completion")
        client = GroqClient(settings=settings, client=mock_groq)

        assert client.generate("Hello world") == "Cached completion"
        assert (client.call_count, client.total_tokens, client.cache_hits) == (1, 15, 0)

        assert client.generate("Hello world") == "Cached completion"
        assert (client.call_count, client.cache_hits) == (1, 1)
        assert mock_groq.chat.completions.create.call_count == 1

    def _client_raising(self, tmp_path, error: Exception) -> tuple[GroqClient, MagicMock]:
        settings = Settings(
            groq_api_key="fake", llm_cache_dir=tmp_path / "cache", llm_max_retries=2, llm_retry_min_wait=0,
            llm_retry_max_wait=0, groq_fallback_models="",  # one model: retries only (fallback: test_model_fallback.py)
        )
        mock_groq = MagicMock()
        mock_groq.chat.completions.create.side_effect = error
        return GroqClient(settings=settings, client=mock_groq), mock_groq

    def test_persistent_429_becomes_domain_rate_limit_error(self, tmp_path) -> None:
        request = httpx.Request("POST", "https://api.groq.com")
        error = groq.RateLimitError("429", response=httpx.Response(429, request=request), body=None)
        client, mock_groq = self._client_raising(tmp_path, error)
        with pytest.raises(LLMRateLimitError):
            client.generate_json("x")
        assert mock_groq.chat.completions.create.call_count == 2  # retried before giving up

    def test_waits_as_long_as_retry_after_header_says(self, tmp_path) -> None:
        request = httpx.Request("POST", "https://api.groq.com")
        response = httpx.Response(429, request=request, headers={"retry-after": "7"})
        error = groq.RateLimitError("429", response=response, body=None)
        client, _ = self._client_raising(tmp_path, error)
        client._settings.llm_retry_max_wait = 60
        waits: list[float] = []
        # tenacity's default sleeper is time.sleep; record instead of sleeping.
        with patch("tenacity.nap.time.sleep", side_effect=waits.append):
            with pytest.raises(LLMRateLimitError):
                client.generate("x")
        assert waits == [7.0]
        assert client.rate_limit_hits == 2  # both attempts got a 429

    def test_reasoning_effort_sent_only_to_gpt_oss(self, tmp_path) -> None:
        settings = Settings(groq_api_key="fake", llm_cache_dir=tmp_path / "cache", groq_reasoning_effort="low")
        mock_groq = _mock_groq("{}")
        client = GroqClient(settings=settings, client=mock_groq)
        client.generate_json("a", model="openai/gpt-oss-20b")
        client.generate_json("b", model="llama-3.1-8b-instant")
        first, second = (c.kwargs for c in mock_groq.chat.completions.create.call_args_list)
        assert first["reasoning_effort"] == "low"
        assert "reasoning_effort" not in second

    def test_connection_failure_becomes_llm_error(self, tmp_path) -> None:
        error = groq.APIConnectionError(request=httpx.Request("POST", "https://api.groq.com"))
        client, _ = self._client_raising(tmp_path, error)
        with pytest.raises(LLMError):
            client.generate("x")

    def test_json_extracted_from_markdown_fence(self, tmp_path) -> None:
        settings = Settings(groq_api_key="fake", llm_cache_dir=tmp_path / "cache", llm_max_retries=1)
        client = GroqClient(settings=settings, client=_mock_groq('```json\n{"skills": ["Python", "FastAPI"]}\n```'))
        assert client.generate_json("Extract skills") == {"skills": ["Python", "FastAPI"]}


# ── Query expander & reranker ────────────────────────────────────────

class TestQueryExpander:
    def test_enriches_terms(self) -> None:
        expander = GroqQueryExpander(FakeLLMClient(json_response={"expanded_terms": ["Django", "FastAPI"]}))
        assert expander.expand(SearchQuery(raw_query="Python backend")).expanded_terms == ["Django", "FastAPI"]

    def test_rate_limit_is_not_swallowed(self) -> None:
        expander = GroqQueryExpander(FakeLLMClient(error=LLMRateLimitError("429")))
        with pytest.raises(LLMRateLimitError):
            expander.expand(SearchQuery(raw_query="Python"))


def _job(job_id: int, title: str = "Engineer") -> JobPosting:
    return JobPosting(job_id=job_id, title=title, company_name="Co", description="Python role")


class TestReranker:
    def test_scores_and_reason_from_llm(self, sample_job: JobPosting, sample_profile: CandidateProfile) -> None:
        llm = FakeLLMClient(json_response={"rankings": [{"job_id": 101, "score": 92.5, "reason": "Strong Python match."}]})
        reranked = GroqReranker(llm).rerank(sample_profile, [JobMatch(job=sample_job, score=5.0, reason="BM25")], top_k=5)
        assert reranked[0].score == 92.5
        assert "Strong Python" in reranked[0].reason

    def test_sorted_by_llm_score_bm25_only_breaks_ties(self, sample_profile: CandidateProfile) -> None:
        matches = [
            JobMatch(job=_job(1), score=40.0, reason="bm25"),
            JobMatch(job=_job(2), score=10.0, reason="bm25"),
            JobMatch(job=_job(3), score=25.0, reason="bm25"),
        ]
        llm = FakeLLMClient(json_response={"rankings": [
            {"job_id": 1, "score": 50, "reason": "ok"},
            {"job_id": 2, "score": 90, "reason": "best"},
            {"job_id": 3, "score": 50, "reason": "ok"},
        ]})
        reranked = GroqReranker(llm).rerank(sample_profile, matches, top_k=3)
        # 2 has the highest LLM score; 1 and 3 tie on LLM score, BM25 (40 > 25) breaks the tie.
        assert [m.job.job_id for m in reranked] == [2, 1, 3]

    def test_unranked_jobs_never_outrank_llm_scored_jobs(self, sample_profile: CandidateProfile) -> None:
        # Job 2 has a huge BM25 score but the LLM did not score it: it must not be mixed into the LLM scale.
        matches = [JobMatch(job=_job(1), score=5.0, reason="bm25"), JobMatch(job=_job(2), score=500.0, reason="bm25")]
        llm = FakeLLMClient(json_response={"rankings": [{"job_id": 1, "score": 3, "reason": "weak"}]})
        reranked = GroqReranker(llm).rerank(sample_profile, matches, top_k=2)
        assert [m.job.job_id for m in reranked] == [1, 2]

    def test_unreadable_output_keeps_bm25_order(self, sample_profile: CandidateProfile) -> None:
        matches = [JobMatch(job=_job(1), score=9.0, reason="bm25"), JobMatch(job=_job(2), score=3.0, reason="bm25")]
        llm = FakeLLMClient(error=LLMResponseParseError("raw", "bad"))
        assert [m.job.job_id for m in GroqReranker(llm).rerank(sample_profile, matches)] == [1, 2]

    def test_rate_limit_is_not_swallowed(self, sample_profile: CandidateProfile) -> None:
        llm = FakeLLMClient(error=LLMRateLimitError("429"))
        with pytest.raises(LLMRateLimitError):
            GroqReranker(llm).rerank(sample_profile, [JobMatch(job=_job(1), score=1.0, reason="bm25")])

    def test_string_job_ids_from_llm_are_accepted(self, sample_profile: CandidateProfile) -> None:
        llm = FakeLLMClient(json_response={"rankings": [{"job_id": "7", "score": 80, "reason": "fit"}]})
        reranked = GroqReranker(llm).rerank(sample_profile, [JobMatch(job=_job(7), score=1.0, reason="bm25")])
        assert reranked[0].score == 80


# ── Groq-backed reasoning ports ──────────────────────────────────────

class TestGroqProfileExtractor:
    def test_extracts_structured_profile(self) -> None:
        llm = FakeLLMClient(json_response={
            "name": "Jane Smith",
            "email": "Not specified",
            "skills": ["Go", "Kubernetes"],
            "experiences": [{"role": "Cloud Engineer", "company": "CloudCorp", "bullets": ["Maintained K8s"]}, "junk"],
        })
        profile = GroqProfileExtractor(llm, model="m").extract("Jane Smith\nCloud Engineer")
        assert profile.name == "Jane Smith"
        assert profile.email == ""
        assert profile.skills == ["Go", "Kubernetes"]
        assert len(profile.experiences) == 1
        assert llm.json_calls[0]["model"] == "m"


class TestGroqGapAnalyzer:
    def test_builds_report(self, sample_job: JobPosting, sample_profile: CandidateProfile) -> None:
        llm = FakeLLMClient(json_response={
            "matched_items": [{"requirement": "Python", "evidence": "Python developer"}],
            "missing_items": [{"requirement": "Kubernetes"}],
            "summary": "Missing Kubernetes.",
        })
        report = GroqGapAnalyzer(llm).analyze(sample_profile, sample_job)
        assert report.job_id == 101
        assert report.matched_items[0].matched is True
        assert report.missing_items[0].matched is False


class TestGroqCVTailor:
    def test_returns_unverified_bullets(self, sample_job: JobPosting, sample_profile: CandidateProfile) -> None:
        llm = FakeLLMClient(json_response={"summary": "T", "bullets": [{"original": "o", "tailored": "t"}, {"original": "x"}]})
        tailored = GroqCVTailor(llm).tailor(sample_profile, sample_job)
        assert [b.tailored for b in tailored.bullets] == ["t"]
        assert tailored.bullets[0].verdict is None
        assert "Built REST APIs using FastAPI" in llm.json_calls[0]["prompt"]


class TestGroqClaimVerifier:
    BULLETS = [
        TailoredBullet(original="Built REST APIs", tailored="Built REST APIs with FastAPI"),
        TailoredBullet(original="Built REST APIs", tailored="Served 5 million users at 99.99% uptime"),
    ]

    def test_llm_unsupported_verdict_is_parsed_as_unsupported(self) -> None:
        llm = FakeLLMClient(json_response={"verifications": [
            {"bullet_id": 1, "verdict": "supported", "evidence": "Built REST APIs"},
            {"bullet_id": 2, "verdict": "unsupported", "evidence": "metrics not in CV"},
        ]})
        report = GroqClaimVerifier(llm).verify("Built REST APIs", self.BULLETS)
        assert [c.verdict for c in report.claims] == [ClaimVerdict.SUPPORTED, ClaimVerdict.UNSUPPORTED]
        assert report.claims[1].evidence == "metrics not in CV"

    def test_no_claims_means_unverified_not_supported(self) -> None:
        report = GroqClaimVerifier(FakeLLMClient(json_response={"verifications": []})).verify("cv", self.BULLETS)
        assert report.supported_count == 0
        assert report.unverified_count == 2

    def test_claims_are_matched_by_id_not_order(self) -> None:
        llm = FakeLLMClient(json_response={"verifications": [
            {"bullet_id": 2, "verdict": "unsupported"},
            {"bullet_id": 1, "verdict": "supported"},
        ]})
        report = GroqClaimVerifier(llm).verify("cv", self.BULLETS)
        assert [c.verdict for c in report.claims] == [ClaimVerdict.SUPPORTED, ClaimVerdict.UNSUPPORTED]
        assert report.claims[0].claim == self.BULLETS[0].tailored

    def test_malformed_verdicts_and_ids_are_unverified(self) -> None:
        llm = FakeLLMClient(json_response={"verifications": [
            {"bullet_id": 1, "verdict": "mostly supported"},
            {"bullet_id": True, "verdict": "supported"},
        ]})
        report = GroqClaimVerifier(llm).verify("cv", self.BULLETS)
        assert report.unverified_count == 2

    def test_no_bullets_skips_llm_call(self) -> None:
        llm = FakeLLMClient()
        assert GroqClaimVerifier(llm).verify("cv", []).total_count == 0
        assert llm.json_calls == []


class TestRelevantJobText:
    def test_keeps_requirement_sections_and_drops_benefits(self) -> None:
        job = JobPosting(
            job_id=1,
            title="Dev",
            company_name="Co",
            description=(
                "About Us\nWe are a great company with a long history of excellence in our field.\n\n"
                "Requirements\n- 3+ years of Python and FastAPI experience building production APIs.\n\n"
                "Benefits\n- Free lunch, gym membership and unlimited paid time off for everyone."
            ),
        )
        text = relevant_job_text(job, max_chars=1000)
        assert "Python and FastAPI" in text
        assert "Free lunch" not in text
        assert "great company" not in text

    def test_falls_back_to_description_without_headers(self) -> None:
        job = JobPosting(job_id=1, title="Dev", company_name="Co", description="Plain text posting about Python work.")
        assert relevant_job_text(job, max_chars=10) == "Plain text"
