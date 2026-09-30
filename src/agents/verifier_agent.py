"""VerifierAgent: audits tailored claims against the original CV and removes unsupported ones."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent
from src.application.verify_tailored_cv import VerifyTailoredCVUseCase


class VerifierAgent(BaseAgent):
    """Verifies every tailored bullet; the original CV text is the only ground truth."""

    def __init__(self, use_case: VerifyTailoredCVUseCase, name: str = "VerifierAgent") -> None:
        super().__init__(name=name)
        self._use_case = use_case

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        profile = self._require(state, "profile")
        tailored = self._use_case.execute(profile.raw_text, self._require(state, "tailored_cv"))
        return {"tailored_cv": tailored}
