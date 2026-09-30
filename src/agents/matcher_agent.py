"""MatcherAgent: candidate profile -> ranked ``JobMatch`` list."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent
from src.application.match_jobs import MatchJobsUseCase


class MatcherAgent(BaseAgent):
    """Runs retrieval + reranking; selects the top match as the target job if none is set."""

    def __init__(self, use_case: MatchJobsUseCase, name: str = "MatcherAgent") -> None:
        super().__init__(name=name)
        self._use_case = use_case

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        matches = self._use_case.execute(
            profile=self._require(state, "profile"),
            preferences=state.get("preferences", ""),
            top_k=state.get("top_k"),
        )
        update: dict[str, Any] = {"matches": matches}
        if matches and state.get("job_id") is None:
            update["job_id"] = matches[0].job.job_id
        return update
