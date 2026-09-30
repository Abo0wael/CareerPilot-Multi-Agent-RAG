"""Domain interface ports (ABCs) for CareerPilot.

Every concrete implementation lives in ``infrastructure/``.
Use cases and agents depend **only** on these abstractions (Dependency Inversion).
Read-side interfaces are separated from write-side interfaces (Interface Segregation).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from .entities import (
    CandidateProfile,
    GapReport,
    IndexStats,
    JobChunk,
    JobMatch,
    JobPosting,
    ScoredChunk,
    SearchQuery,
    TailoredBullet,
    TailoredCV,
    VerificationReport,
)


# ── CV parsing ──────────────────────────────────────────────────────

class CVParser(ABC):
    """Extracts raw text from an uploaded CV file."""

    @abstractmethod
    def parse(self, file_bytes: bytes, filename: str) -> str:
        """Return the plain-text content of the CV.

        Args:
            file_bytes: Raw bytes of the uploaded file.
            filename: Original filename (used to detect format).

        Returns:
            Extracted text.

        Raises:
            CVParsingError: If text cannot be extracted.
        """


# ── Chunking ────────────────────────────────────────────────────────

class Chunker(ABC):
    """Splits a job posting description into semantic chunks."""

    @abstractmethod
    def chunk(self, posting: JobPosting) -> list[JobChunk]:
        """Return one or more ``JobChunk`` instances for *posting*.

        The implementation decides the chunking strategy
        (section-based, paragraph-based, etc.).
        """


# ── Search index (write side) ──────────────────────────────────────

class SearchIndexWriter(ABC):
    """Writes full postings and their chunks to the full-text search index."""

    @abstractmethod
    def add_jobs(self, postings: list[JobPosting]) -> int:
        """Store full postings (the parent documents).

        Returns:
            Number of postings stored.
        """

    @abstractmethod
    def add_chunks(self, chunks: list[JobChunk]) -> int:
        """Insert *chunks* into the index.

        Returns:
            Number of chunks successfully inserted.
        """

    @abstractmethod
    def clear(self) -> None:
        """Remove all data from the index."""


# ── Search index (read side) ───────────────────────────────────────

class Retriever(ABC):
    """Performs BM25 retrieval over indexed job chunks."""

    @abstractmethod
    def search(
        self,
        query: SearchQuery,
        top_n: int = 50,
        sections: Optional[list[str]] = None,
        excluded_sections: Optional[list[str]] = None,
    ) -> list[ScoredChunk]:
        """Search the index and return up to *top_n* scored chunks.

        Args:
            query: The search query (may include expanded terms).
            top_n: Maximum number of results.
            sections: If provided, restrict to these section types.
            excluded_sections: If provided, exclude these section types.
                Defaults to excluding Benefits/About if neither is given.

        Returns:
            Chunks sorted by descending BM25 score.
        """


# ── Job repository (read side) ─────────────────────────────────────

class JobRepository(ABC):
    """Read-only access to full job postings by ID."""

    @abstractmethod
    def get_by_id(self, job_id: int) -> JobPosting:
        """Return the full ``JobPosting`` for *job_id*.

        Raises:
            JobNotFoundError: If the job does not exist.
        """

    @abstractmethod
    def get_by_ids(self, job_ids: list[int]) -> list[JobPosting]:
        """Return ``JobPosting`` objects for the given IDs (order preserved)."""


# ── LLM client ──────────────────────────────────────────────────────

class LLMClient(ABC):
    """Sends prompts to a language model and returns text responses."""

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> str:
        """Generate a completion.

        Args:
            prompt: The user message.
            system_prompt: Optional system message.
            model: Model identifier override (uses default if ``None``).
            temperature: Sampling temperature.
            max_tokens: Maximum tokens to generate.

        Returns:
            The generated text.

        Raises:
            LLMRateLimitError: If rate limits persist after retries.
            LLMError: For other LLM failures.
        """

    @abstractmethod
    def generate_json(
        self,
        prompt: str,
        system_prompt: str = "",
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 4096,
    ) -> dict:
        """Generate a JSON-parseable completion.

        Automatically requests JSON mode from the provider, validates
        the output, and retries once on parse failure.

        Returns:
            Parsed JSON as a dict.

        Raises:
            LLMResponseParseError: If JSON cannot be extracted after retry.
        """


# ── Query expansion ─────────────────────────────────────────────────

class QueryExpander(ABC):
    """Expands a search query with synonyms and related terms."""

    @abstractmethod
    def expand(self, query: SearchQuery) -> SearchQuery:
        """Return a new ``SearchQuery`` with ``expanded_terms`` populated."""


# ── Reranking ───────────────────────────────────────────────────────

class Reranker(ABC):
    """Re-scores and re-orders job matches using an LLM."""

    @abstractmethod
    def rerank(
        self,
        profile: CandidateProfile,
        matches: list[JobMatch],
        top_k: int = 10,
    ) -> list[JobMatch]:
        """Rerank *matches* for *profile*, returning the top *top_k*.

        Each returned ``JobMatch`` must include a grounded ``reason``.
        """


# ── Job source & index diagnostics ──────────────────────────────────

class JobSource(ABC):
    """Provides the cleaned job postings to be indexed."""

    @abstractmethod
    def load_postings(self) -> list[JobPosting]:
        """Return all postings that should be searchable."""


class IndexStatsReader(ABC):
    """Reads diagnostics about the search index."""

    @abstractmethod
    def get_stats(self) -> IndexStats:
        """Return job/chunk counts and FTS5 availability."""


# ── LLM-backed reasoning steps ──────────────────────────────────────

class ProfileExtractor(ABC):
    """Turns raw CV text into a structured ``CandidateProfile``."""

    @abstractmethod
    def extract(self, raw_cv_text: str) -> CandidateProfile:
        """Extract a profile using only facts present in *raw_cv_text*."""


class GapAnalyzer(ABC):
    """Compares a candidate against one job's requirements."""

    @abstractmethod
    def analyze(self, profile: CandidateProfile, job: JobPosting) -> GapReport:
        """Return matched requirements (with CV evidence) and missing ones."""


class CVTailor(ABC):
    """Rewrites CV bullets for a target job without adding new facts."""

    @abstractmethod
    def tailor(self, profile: CandidateProfile, job: JobPosting) -> TailoredCV:
        """Return an unverified ``TailoredCV`` for *job*."""


class ClaimVerifier(ABC):
    """Audits tailored bullets against the original CV text."""

    @abstractmethod
    def verify(self, original_cv_text: str, bullets: list[TailoredBullet]) -> VerificationReport:
        """Return exactly one ``ClaimVerification`` per bullet, in the same order.

        A bullet without a usable verdict must be ``UNVERIFIED``, never ``SUPPORTED``.
        """
