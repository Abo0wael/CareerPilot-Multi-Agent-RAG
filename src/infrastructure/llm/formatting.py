"""Helpers that render domain entities as compact prompt text.

Keeping these in one place avoids each Groq service re-implementing them,
and keeps prompt size (tokens) under control.
"""

from __future__ import annotations

from src.domain.entities import CandidateProfile, ChunkSection, JobPosting
from src.infrastructure.chunking.chunkers import SectionChunker

# Sections that describe what the job needs; "about" and "benefits" are marketing.
_RELEVANT_SECTIONS = {
    ChunkSection.REQUIREMENTS,
    ChunkSection.RESPONSIBILITIES,
    ChunkSection.NICE_TO_HAVE,
}
_section_chunker = SectionChunker()


def relevant_job_text(job: JobPosting, max_chars: int) -> str:
    """Return the requirement-bearing sections of *job*, capped at *max_chars*.

    Reuses the same header detection as indexing. Postings without recognised
    headers fall back to the start of the full description.
    """
    chunks = [c for c in _section_chunker.chunk(job) if c.section in _RELEVANT_SECTIONS]
    text = "\n".join(c.text for c in chunks) if chunks else job.description
    return text[:max_chars]


def experience_lines(profile: CandidateProfile) -> str:
    """One line per experience entry: role, company, duration and bullets."""
    lines = [
        f"{e.role} at {e.company} ({e.duration}): " + "; ".join(e.bullets)
        for e in profile.experiences
    ]
    return "\n".join(lines) or "Not specified"


def project_lines(profile: CandidateProfile) -> str:
    """One line per project: name, technologies and description."""
    lines = [
        f"{p.name} ({', '.join(p.technologies)}): {p.description}" for p in profile.projects
    ]
    return "\n".join(lines) or "Not specified"


def str_list(value: object) -> list[str]:
    """Coerce an LLM JSON field into a list of non-empty stripped strings."""
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()]


def dict_list(value: object) -> list[dict]:
    """Coerce an LLM JSON field into a list of dicts, dropping anything else."""
    if not isinstance(value, list):
        return []
    return [v for v in value if isinstance(v, dict)]
