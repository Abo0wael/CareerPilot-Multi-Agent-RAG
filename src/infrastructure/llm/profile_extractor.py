"""Groq implementation of ``ProfileExtractor``."""

from __future__ import annotations

from typing import Optional

from src.domain.entities import CandidateProfile, EducationEntry, ExperienceEntry, ProjectEntry
from src.domain.interfaces import LLMClient, ProfileExtractor
from src.infrastructure.llm.formatting import dict_list, str_list
from src.infrastructure.llm.prompts.profile_prompts import (
    PROFILE_SYSTEM_PROMPT,
    PROFILE_USER_PROMPT_TEMPLATE,
)

_NOT_SPECIFIED = "not specified"


def _text(value: object) -> str:
    """Stringify an LLM field, treating the prompt's 'Not specified' marker as empty."""
    text = str(value or "").strip()
    return "" if text.lower() == _NOT_SPECIFIED else text


class GroqProfileExtractor(ProfileExtractor):
    """Extracts a structured profile from CV text with one Groq JSON call."""

    def __init__(self, llm_client: LLMClient, model: Optional[str] = None, max_cv_chars: int = 12000) -> None:
        self._llm = llm_client
        self._model = model
        self._max_cv_chars = max_cv_chars

    def extract(self, raw_cv_text: str) -> CandidateProfile:
        data = self._llm.generate_json(
            prompt=PROFILE_USER_PROMPT_TEMPLATE.format(cv_text=raw_cv_text[: self._max_cv_chars]),
            system_prompt=PROFILE_SYSTEM_PROMPT,
            model=self._model,
            temperature=0.0,
        )
        return CandidateProfile(
            raw_text=raw_cv_text,
            name=_text(data.get("name")),
            email=_text(data.get("email")),
            phone=_text(data.get("phone")),
            summary=_text(data.get("summary")),
            skills=str_list(data.get("skills")),
            experiences=[
                ExperienceEntry(
                    role=_text(e.get("role")),
                    company=_text(e.get("company")),
                    duration=_text(e.get("duration")),
                    bullets=str_list(e.get("bullets")),
                )
                for e in dict_list(data.get("experiences"))
                if _text(e.get("role"))
            ],
            projects=[
                ProjectEntry(
                    name=_text(p.get("name")),
                    description=_text(p.get("description")),
                    technologies=str_list(p.get("technologies")),
                )
                for p in dict_list(data.get("projects"))
                if _text(p.get("name"))
            ],
            education=[
                EducationEntry(
                    degree=_text(ed.get("degree")),
                    institution=_text(ed.get("institution")),
                    year=_text(ed.get("year")),
                    details=_text(ed.get("details")),
                )
                for ed in dict_list(data.get("education"))
                if _text(ed.get("degree"))
            ],
            certifications=str_list(data.get("certifications")),
        )
