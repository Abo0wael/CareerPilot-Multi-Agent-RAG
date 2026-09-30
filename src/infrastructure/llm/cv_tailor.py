"""Groq implementation of ``CVTailor``."""

from __future__ import annotations

from typing import Optional

from src.domain.entities import CandidateProfile, JobPosting, TailoredBullet, TailoredCV
from src.domain.interfaces import CVTailor, LLMClient
from src.infrastructure.llm.formatting import dict_list, relevant_job_text
from src.infrastructure.llm.prompts.tailor_prompts import (
    TAILOR_SYSTEM_PROMPT,
    TAILOR_USER_PROMPT_TEMPLATE,
)

_MIN_RAW_LINE_CHARS = 30  # raw-text fallback: shorter lines are headers/contact info


def _source_bullets(profile: CandidateProfile) -> list[str]:
    """Collect the original CV facts that may be rephrased."""
    bullets = [f"[{e.role} at {e.company}] {b}" for e in profile.experiences for b in e.bullets]
    bullets += [f"[Project: {p.name}] {p.description}" for p in profile.projects if p.description]
    if bullets:
        return bullets
    return [
        line.strip("- *• ")
        for line in profile.raw_text.splitlines()
        if len(line.strip()) > _MIN_RAW_LINE_CHARS
    ]


class GroqCVTailor(CVTailor):
    """Rewrites up to *max_bullets* CV bullets for a job with one Groq JSON call."""

    def __init__(
        self,
        llm_client: LLMClient,
        model: Optional[str] = None,
        max_job_chars: int = 2500,
        max_bullets: int = 10,
    ) -> None:
        self._llm = llm_client
        self._model = model
        self._max_job_chars = max_job_chars
        self._max_bullets = max_bullets

    def tailor(self, profile: CandidateProfile, job: JobPosting) -> TailoredCV:
        bullets = _source_bullets(profile)[: self._max_bullets]
        prompt = TAILOR_USER_PROMPT_TEMPLATE.format(
            job_title=job.title,
            company_name=job.company_name,
            job_snippet=relevant_job_text(job, self._max_job_chars),
            candidate_bullets="\n".join(f"- {b}" for b in bullets),
        )
        data = self._llm.generate_json(
            prompt=prompt,
            system_prompt=TAILOR_SYSTEM_PROMPT,
            model=self._model,
            temperature=0.0,
        )
        return TailoredCV(
            bullets=[
                TailoredBullet(
                    original=str(b.get("original", "")).strip(),
                    tailored=str(b["tailored"]).strip(),
                    section=str(b.get("section", "Experience")).strip(),
                )
                for b in dict_list(data.get("bullets"))
                if str(b.get("tailored", "")).strip()
            ],
            summary=str(data.get("summary", "")).strip(),
        )
