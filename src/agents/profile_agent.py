"""ProfileAgent: CV file or text -> structured ``CandidateProfile``."""

from __future__ import annotations

from typing import Any

from src.agents.base import BaseAgent
from src.application.build_profile import BuildProfileUseCase
from src.domain.exceptions import WorkflowStateError


class ProfileAgent(BaseAgent):
    """Builds the candidate profile from an uploaded file or raw CV text."""

    def __init__(self, use_case: BuildProfileUseCase, name: str = "ProfileAgent") -> None:
        super().__init__(name=name)
        self._use_case = use_case

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("cv_file_bytes") is not None:
            profile = self._use_case.execute(state["cv_file_bytes"], state.get("cv_filename", ""))
        elif state.get("raw_cv_text"):
            profile = self._use_case.execute_from_text(state["raw_cv_text"])
        else:
            raise WorkflowStateError(f"{self.name} requires 'cv_file_bytes' or 'raw_cv_text'.")
        return {"profile": profile}
