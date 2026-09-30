"""GapAnalyzerAgent: profile + target job -> grounded ``GapReport``."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent
from src.application.analyze_gap import AnalyzeGapUseCase


class GapAnalyzerAgent(BaseAgent):
    """Compares the candidate against the target job's requirements."""

    def __init__(self, use_case: AnalyzeGapUseCase, name: str = "GapAnalyzerAgent") -> None:
        super().__init__(name=name)
        self._use_case = use_case

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        report = self._use_case.execute(self._require(state, "profile"), self._require(state, "job_id"))
        return {"gap_report": report}
