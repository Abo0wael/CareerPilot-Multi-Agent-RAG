"""Reranker using Groq LLM to re-score matches and produce grounded rationales."""

from __future__ import annotations

import logging
from typing import Optional

from src.domain.entities import CandidateProfile, JobMatch
from src.domain.exceptions import LLMResponseParseError
from src.domain.interfaces import LLMClient, Reranker

logger = logging.getLogger(__name__)

RERANKER_SYSTEM_PROMPT = """\
You are an expert technical hiring manager evaluating job opportunities for a candidate.
Compare the candidate profile against each job posting.
Evaluate:
1. Core technical skills overlap.
2. Seniority / experience level fit.
3. Domain / tech stack alignment.

Output MUST be a JSON object with key "rankings" containing a list of objects:
[
  {
    "job_id": <int>,
    "score": <float between 0 and 100>,
    "reason": "<1-2 sentence grounded justification detailing specific matching skills and any missing gaps>"
  }
]
Sort rankings descending by score.
"""


def _as_job_id(value: object) -> Optional[int]:
    """Accept integer ids and numeric strings from the LLM; reject anything else."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


class GroqReranker(Reranker):
    """Re-scores the top BM25 candidates with an LLM and explains each match.

    Ordering rule (scales are never mixed):
      1. Jobs the LLM scored, by LLM score (0-100); BM25 score breaks ties.
      2. Jobs the LLM did not score, after all of them, in BM25 order.
    ``JobMatch.score`` is the LLM score for group 1 and the BM25 score for group 2.
    """

    def __init__(
        self,
        llm_client: LLMClient,
        model: Optional[str] = None,
        max_candidates: int = 20,
        max_description_chars: int = 600,
    ) -> None:
        self._llm = llm_client
        self._model = model
        self._max_candidates = max_candidates
        self._max_description_chars = max_description_chars

    def rerank(
        self,
        profile: CandidateProfile,
        matches: list[JobMatch],
        top_k: int = 10,
    ) -> list[JobMatch]:
        """Rerank *matches* and return the top *top_k* with grounded reasons."""
        if not matches:
            return []

        candidates = matches[: self._max_candidates]
        try:
            response = self._llm.generate_json(
                prompt=self._build_prompt(profile, candidates),
                system_prompt=RERANKER_SYSTEM_PROMPT,
                model=self._model,
                temperature=0.0,
            )
        except LLMResponseParseError as err:
            # Unreadable rerank output degrades to BM25 order; rate limits propagate.
            logger.warning("Reranker output unreadable; keeping BM25 order: %s", err)
            return matches[:top_k]

        by_id = {m.job.job_id: m for m in candidates}
        llm_ranked: list[tuple[float, float, JobMatch]] = []
        for item in response.get("rankings", []):
            if not isinstance(item, dict):
                continue
            job_id = _as_job_id(item.get("job_id"))
            original = by_id.pop(job_id, None) if job_id is not None else None
            if original is None:
                continue  # unknown or duplicate id
            try:
                llm_score = float(item.get("score", 0.0))
            except (TypeError, ValueError):
                llm_score = 0.0
            reason = str(item.get("reason", "")).strip() or original.reason
            llm_ranked.append((llm_score, original.score, JobMatch(job=original.job, score=llm_score, reason=reason)))

        llm_ranked.sort(key=lambda t: (t[0], t[1]), reverse=True)
        scored_ids = {m.job.job_id for _, _, m in llm_ranked}
        unscored = [m for m in matches if m.job.job_id not in scored_ids]  # already in BM25 order
        return ([m for _, _, m in llm_ranked] + unscored)[:top_k]

    def _build_prompt(self, profile: CandidateProfile, candidates: list[JobMatch]) -> str:
        skills = ", ".join(profile.skills) or "Not specified"
        experience = "; ".join(f"{e.role} at {e.company}" for e in profile.experiences[:3])
        jobs = "\n\n".join(
            f"[Job ID {m.job.job_id}] Title: {m.job.title} | Company: {m.job.company_name} | "
            f"Level: {m.job.formatted_experience_level or 'Any'} | Location: {m.job.location}\n"
            "Description snippet: "
            + m.job.description[: self._max_description_chars].replace("\n", " ").strip()
            for m in candidates
        )
        return (
            f"=== CANDIDATE PROFILE ===\nCandidate Skills: {skills}\n"
            f"Recent Experience: {experience or 'See profile'}\nSummary: {profile.raw_text[:400]}\n\n"
            f"=== JOB CANDIDATES ===\n{jobs}\n\n"
            "Rank and score each job for this candidate. Provide grounded reasons."
        )
