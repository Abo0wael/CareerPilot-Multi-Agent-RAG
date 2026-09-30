"""Groq implementation of ``GapAnalyzer``."""

from __future__ import annotations

from typing import Optional

from src.domain.entities import CandidateProfile, GapItem, GapReport, JobPosting
from src.domain.interfaces import GapAnalyzer, LLMClient
from src.infrastructure.llm.formatting import (
    dict_list,
    experience_lines,
    project_lines,
    relevant_job_text,
)
from src.infrastructure.llm.prompts.gap_prompts import GAP_SYSTEM_PROMPT, GAP_USER_PROMPT_TEMPLATE


def _gap_items(raw: object, matched: bool) -> list[GapItem]:
    return [
        GapItem(
            requirement=str(item["requirement"]).strip(),
            matched=matched,
            evidence=str(item.get("evidence", "")).strip(),
        )
        for item in dict_list(raw)
        if str(item.get("requirement", "")).strip()
    ]


class GroqGapAnalyzer(GapAnalyzer):
    """Produces a grounded gap report with one Groq JSON call."""

    def __init__(self, llm_client: LLMClient, model: Optional[str] = None, max_job_chars: int = 4000) -> None:
        self._llm = llm_client
        self._model = model
        self._max_job_chars = max_job_chars

    def analyze(self, profile: CandidateProfile, job: JobPosting) -> GapReport:
        prompt = GAP_USER_PROMPT_TEMPLATE.format(
            candidate_name=profile.name or "Candidate",
            candidate_skills=", ".join(profile.skills) or "Not specified",
            candidate_summary=profile.summary or profile.raw_text[:300],
            candidate_experience=experience_lines(profile),
            candidate_projects=project_lines(profile),
            job_title=job.title,
            company_name=job.company_name,
            experience_level=job.formatted_experience_level or "Not specified",
            job_description=relevant_job_text(job, self._max_job_chars),
        )
        data = self._llm.generate_json(
            prompt=prompt,
            system_prompt=GAP_SYSTEM_PROMPT,
            model=self._model,
            temperature=0.0,
        )
        return GapReport(
            job_id=job.job_id,
            job_title=job.title,
            matched_items=_gap_items(data.get("matched_items"), matched=True),
            missing_items=_gap_items(data.get("missing_items"), matched=False),
            summary=str(data.get("summary", "")).strip(),
        )
