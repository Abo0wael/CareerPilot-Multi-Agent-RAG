"""TailorAgent: profile + target job -> unverified ``TailoredCV``."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent
from src.application.tailor_cv import TailorCVUseCase


class TailorAgent(BaseAgent):
    """Rewrites CV bullets for the target job (always followed by the VerifierAgent)."""

    def __init__(self, use_case: TailorCVUseCase, name: str = "TailorAgent") -> None:
        super().__init__(name=name)
        self._use_case = use_case

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        tailored = self._use_case.execute(self._require(state, "profile"), self._require(state, "job_id"))
        return {"tailored_cv": tailored}
