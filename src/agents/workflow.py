"""Typed facade over the compiled LangGraph workflow.

The API calls these methods; each one runs the graph with the matching
``request_type`` and unpacks the final state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from src.agents.graph import AgentWorkflowState, RequestType
from src.domain.entities import CandidateProfile, GapReport, JobMatch, TailoredCV


@dataclass
class PipelineResult:
    """Everything the full pipeline produced (later steps are ``None`` if no job matched)."""

    profile: CandidateProfile
    matches: list[JobMatch] = field(default_factory=list)
    target_job_id: Optional[int] = None
    gap_report: Optional[GapReport] = None
    tailored_cv: Optional[TailoredCV] = None


class CareerPilotWorkflow:
    """Runs the multi-agent graph for each kind of request."""

    def __init__(self, graph: Any) -> None:
        self._graph = graph

    def _run(self, state: AgentWorkflowState) -> dict[str, Any]:
        return self._graph.invoke(state)

    @staticmethod
    def _cv_input(raw_text: Optional[str], file_bytes: Optional[bytes], filename: str) -> AgentWorkflowState:
        if file_bytes is not None:
            return {"cv_file_bytes": file_bytes, "cv_filename": filename}
        return {"raw_cv_text": raw_text or ""}

    def build_profile(
        self, raw_text: Optional[str] = None, file_bytes: Optional[bytes] = None, filename: str = ""
    ) -> CandidateProfile:
        state = self._run({"request_type": RequestType.PROFILE.value, **self._cv_input(raw_text, file_bytes, filename)})
        return state["profile"]

    def match(self, profile: CandidateProfile, preferences: str = "", top_k: Optional[int] = None) -> list[JobMatch]:
        state = self._run(
            {"request_type": RequestType.MATCH.value, "profile": profile, "preferences": preferences, "top_k": top_k}
        )
        return state["matches"]

    def analyze_gap(self, profile: CandidateProfile, job_id: int) -> GapReport:
        state = self._run({"request_type": RequestType.GAP.value, "profile": profile, "job_id": job_id})
        return state["gap_report"]

    def tailor(self, profile: CandidateProfile, job_id: int) -> TailoredCV:
        state = self._run({"request_type": RequestType.TAILOR.value, "profile": profile, "job_id": job_id})
        return state["tailored_cv"]

    def run_pipeline(
        self,
        raw_text: Optional[str] = None,
        file_bytes: Optional[bytes] = None,
        filename: str = "",
        preferences: str = "",
        top_k: Optional[int] = None,
    ) -> PipelineResult:
        state = self._run(
            {
                "request_type": RequestType.PIPELINE.value,
                "preferences": preferences,
                "top_k": top_k,
                **self._cv_input(raw_text, file_bytes, filename),
            }
        )
        return PipelineResult(
            profile=state["profile"],
            matches=state.get("matches", []),
            target_job_id=state.get("job_id"),
            gap_report=state.get("gap_report"),
            tailored_cv=state.get("tailored_cv"),
        )
