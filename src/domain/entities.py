"""Domain entities for CareerPilot.

Pure Python dataclasses — no framework imports, no infrastructure dependencies.
Each entity validates its own invariants in ``__post_init__``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from .exceptions import EmptyFieldError, InvalidEntityError


# ── Enums ────────────────────────────────────────────────────────────

class ChunkSection(str, Enum):
    """Semantic section labels assigned to job-posting chunks."""

    ABOUT = "about"
    RESPONSIBILITIES = "responsibilities"
    REQUIREMENTS = "requirements"
    NICE_TO_HAVE = "nice_to_have"
    BENEFITS = "benefits"
    FULL = "full"  # fallback when no section headers are detected


class ClaimVerdict(str, Enum):
    """Verdict assigned to each tailored CV claim by the claim verifier.

    ``UNVERIFIED`` means the verifier gave no usable verdict for the claim
    (missing or malformed); it is never counted as supported.
    """

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNVERIFIED = "unverified"

    @classmethod
    def from_llm(cls, value: object) -> ClaimVerdict:
        """Parse a verdict strictly: only the exact enum strings are accepted.

        Anything else (typos, prose, ``None``) becomes ``UNVERIFIED``.
        Substring matching is deliberately avoided ("unsupported" contains "supp").
        """
        if not isinstance(value, str):
            return cls.UNVERIFIED
        normalized = value.strip().lower()
        if normalized == cls.SUPPORTED.value:
            return cls.SUPPORTED
        if normalized == cls.UNSUPPORTED.value:
            return cls.UNSUPPORTED
        return cls.UNVERIFIED


# ── Helper ───────────────────────────────────────────────────────────

def _require_non_empty(entity_name: str, field_name: str, value: str) -> str:
    """Return *value* stripped, raising ``EmptyFieldError`` if blank."""
    stripped = value.strip()
    if not stripped:
        raise EmptyFieldError(entity_name, field_name)
    return stripped


# ── Job domain ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class JobPosting:
    """A single LinkedIn job posting (cleaned, subset-filtered).

    Frozen to ensure immutability after construction.  Uses
    ``object.__setattr__`` in ``__post_init__`` because the dataclass
    is frozen.
    """

    job_id: int
    title: str
    company_name: str
    description: str
    location: str = ""
    formatted_work_type: str = ""
    formatted_experience_level: str = ""
    remote_allowed: bool = False
    min_salary: Optional[float] = None
    max_salary: Optional[float] = None
    currency: str = ""
    skills: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "title", _require_non_empty("JobPosting", "title", self.title)
        )
        object.__setattr__(
            self,
            "description",
            _require_non_empty("JobPosting", "description", self.description),
        )


@dataclass(frozen=True)
class JobChunk:
    """A chunk of a job posting, representing one semantic section.

    Stored in the FTS5 index for lexical retrieval.
    """

    chunk_id: str
    job_id: int
    section: ChunkSection
    text: str
    title: str = ""
    company_name: str = ""
    location: str = ""
    formatted_experience_level: str = ""
    formatted_work_type: str = ""
    remote_allowed: bool = False
    min_salary: Optional[float] = None
    max_salary: Optional[float] = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "text", _require_non_empty("JobChunk", "text", self.text)
        )
        if not self.chunk_id:
            raise InvalidEntityError("JobChunk", "chunk_id must not be empty.")


# ── Candidate domain (sub-entries defined first for dataclass ordering) ──

@dataclass
class ExperienceEntry:
    """A single work-experience block from a CV."""

    role: str
    company: str = ""
    duration: str = ""
    bullets: list[str] = field(default_factory=list)


@dataclass
class ProjectEntry:
    """A single project block from a CV."""

    name: str
    description: str = ""
    technologies: list[str] = field(default_factory=list)


@dataclass
class EducationEntry:
    """A single education block from a CV."""

    degree: str
    institution: str = ""
    year: str = ""
    details: str = ""


@dataclass
class CandidateProfile:
    """Structured representation of a candidate's CV.

    ``raw_text`` is the original CV text; structured fields are
    populated by the ProfileAgent.
    """

    raw_text: str
    name: str = ""
    email: str = ""
    phone: str = ""
    summary: str = ""
    skills: list[str] = field(default_factory=list)
    experiences: list[ExperienceEntry] = field(default_factory=list)
    projects: list[ProjectEntry] = field(default_factory=list)
    education: list[EducationEntry] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.raw_text = _require_non_empty(
            "CandidateProfile", "raw_text", self.raw_text
        )


# ── Search / retrieval ───────────────────────────────────────────────

@dataclass
class SearchQuery:
    """Input to the retrieval pipeline."""

    raw_query: str
    expanded_terms: list[str] = field(default_factory=list)
    filters: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.raw_query = _require_non_empty(
            "SearchQuery", "raw_query", self.raw_query
        )


@dataclass
class ScoredChunk:
    """A retrieval result: chunk + BM25 score."""

    chunk: JobChunk
    score: float

    @property
    def job_id(self) -> int:
        """Convenience property for accessing the underlying chunk's job_id."""
        return self.chunk.job_id

    @property
    def chunk_id(self) -> str:
        """Convenience property for accessing the underlying chunk's chunk_id."""
        return self.chunk.chunk_id

    @property
    def section(self) -> ChunkSection:
        """Convenience property for accessing the underlying chunk's section."""
        return self.chunk.section

    @property
    def text(self) -> str:
        """Convenience property for accessing the underlying chunk's text."""
        return self.chunk.text



@dataclass
class JobMatch:
    """A matched job posting returned to the user, with a grounded reason."""

    job: JobPosting
    score: float
    reason: str

    def __post_init__(self) -> None:
        self.reason = _require_non_empty("JobMatch", "reason", self.reason)


# ── Gap analysis ─────────────────────────────────────────────────────

@dataclass
class GapItem:
    """A single requirement from a job posting, with match status."""

    requirement: str
    matched: bool
    evidence: str = ""  # quote from CV if matched


@dataclass
class GapReport:
    """Full gap analysis for a candidate vs. a specific job."""

    job_id: int
    job_title: str
    matched_items: list[GapItem] = field(default_factory=list)
    missing_items: list[GapItem] = field(default_factory=list)
    summary: str = ""


# ── Tailoring & verification ────────────────────────────────────────

@dataclass
class TailoredBullet:
    """A single rewritten CV bullet for a target job.

    ``verdict`` and ``evidence`` are filled in once the bullet is verified.
    """

    original: str
    tailored: str
    section: str = ""
    verdict: Optional[ClaimVerdict] = None
    evidence: str = ""


@dataclass
class ClaimVerification:
    """Verification result for a single tailored claim."""

    claim: str
    verdict: ClaimVerdict
    evidence: str = ""  # supporting quote from original CV, or why it is unsupported


@dataclass
class VerificationReport:
    """Output of the claim verifier: one entry per tailored bullet, in order."""

    claims: list[ClaimVerification] = field(default_factory=list)

    def _count(self, verdict: ClaimVerdict) -> int:
        return sum(1 for c in self.claims if c.verdict == verdict)

    @property
    def supported_count(self) -> int:
        """Number of claims verified as supported."""
        return self._count(ClaimVerdict.SUPPORTED)

    @property
    def unsupported_count(self) -> int:
        """Number of claims marked as unsupported (fabricated or exaggerated)."""
        return self._count(ClaimVerdict.UNSUPPORTED)

    @property
    def unverified_count(self) -> int:
        """Number of claims the verifier returned no usable verdict for."""
        return self._count(ClaimVerdict.UNVERIFIED)

    @property
    def total_count(self) -> int:
        """Total number of audited claims."""
        return len(self.claims)


@dataclass
class TailoredCV:
    """Output of the tailoring step, optionally verified.

    After ``apply_verification``, ``bullets`` holds only claims that were not
    rejected (supported or unverified, each carrying its verdict), and
    ``removed_bullets`` holds the unsupported claims that must not be used.
    """

    bullets: list[TailoredBullet] = field(default_factory=list)
    verification: Optional[VerificationReport] = None
    summary: str = ""
    removed_bullets: list[TailoredBullet] = field(default_factory=list)

    def apply_verification(self, report: VerificationReport) -> None:
        """Attach *report* and remove every bullet judged unsupported.

        Raises:
            InvalidEntityError: If the report does not have one claim per bullet.
        """
        if len(report.claims) != len(self.bullets):
            raise InvalidEntityError(
                "VerificationReport",
                f"expected {len(self.bullets)} claims, got {len(report.claims)}.",
            )
        kept: list[TailoredBullet] = []
        for bullet, claim in zip(self.bullets, report.claims):
            bullet.verdict = claim.verdict
            bullet.evidence = claim.evidence
            if claim.verdict == ClaimVerdict.UNSUPPORTED:
                self.removed_bullets.append(bullet)
            else:
                kept.append(bullet)
        self.bullets = kept
        self.verification = report


# ── Index administration ────────────────────────────────────────────

@dataclass(frozen=True)
class IngestResult:
    """Outcome of (re)building the search index."""

    jobs_ingested: int
    chunks_indexed: int


@dataclass(frozen=True)
class IndexStats:
    """Read-only diagnostics about the search index."""

    total_jobs: int
    total_chunks: int
    fts5_available: bool
