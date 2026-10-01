"""LangGraph workflow for the CareerPilot multi-agent system.

Every API request that needs reasoning runs through this graph. The entry
node and every transition are chosen by ``request_type``:

    profile  : ProfileAgent
    match    : MatcherAgent
    gap      : GapAnalyzerAgent
    tailor   : TailorAgent -> VerifierAgent
    pipeline : ProfileAgent -> MatcherAgent -> GapAnalyzerAgent -> TailorAgent -> VerifierAgent

Routers are pure functions of the state: they never modify it.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from src.agents.base import BaseAgent
from src.agents.gap_agent import GapAnalyzerAgent
from src.agents.matcher_agent import MatcherAgent
from src.agents.profile_agent import ProfileAgent
from src.agents.tailor_agent import TailorAgent
from src.agents.verifier_agent import VerifierAgent
from src.domain.entities import CandidateProfile, GapReport, JobMatch, TailoredCV
from src.domain.exceptions import WorkflowStateError
from src.domain.interfaces import ModelUsageTracker


class RequestType(str, Enum):
    """What the caller asked the workflow to do."""

    PROFILE = "profile"
    MATCH = "match"
    GAP = "gap"
    TAILOR = "tailor"
    PIPELINE = "pipeline"


PROFILE_NODE = "profile_agent"
MATCHER_NODE = "matcher_agent"
GAP_NODE = "gap_agent"
TAILOR_NODE = "tailor_agent"
VERIFIER_NODE = "verifier_agent"

_ENTRY_NODES = {
    RequestType.PROFILE: PROFILE_NODE,
    RequestType.PIPELINE: PROFILE_NODE,
    RequestType.MATCH: MATCHER_NODE,
    RequestType.GAP: GAP_NODE,
    RequestType.TAILOR: TAILOR_NODE,
}


class AgentWorkflowState(TypedDict, total=False):
    """State shared between workflow nodes."""

    request_type: str
    cv_file_bytes: bytes
    cv_filename: str
    raw_cv_text: str
    profile: CandidateProfile
    preferences: str
    top_k: Optional[int]
    matches: list[JobMatch]
    job_id: int
    gap_report: GapReport
    tailored_cv: TailoredCV


def _request_type(state: AgentWorkflowState) -> RequestType:
    try:
        return RequestType(state.get("request_type"))
    except ValueError as err:
        raise WorkflowStateError(f"Unknown request_type: {state.get('request_type')!r}") from err


def _is_pipeline(state: AgentWorkflowState) -> bool:
    return _request_type(state) is RequestType.PIPELINE


def route_request(state: AgentWorkflowState) -> str:
    """Choose the entry node from ``request_type``."""
    return _ENTRY_NODES[_request_type(state)]


def route_after_profile(state: AgentWorkflowState) -> str:
    return MATCHER_NODE if _is_pipeline(state) else END


def route_after_matcher(state: AgentWorkflowState) -> str:
    # The pipeline stops if nothing matched: there is no job to analyse.
    return GAP_NODE if _is_pipeline(state) and state.get("matches") else END


def route_after_gap(state: AgentWorkflowState) -> str:
    return TAILOR_NODE if _is_pipeline(state) else END


def _tracked(agent: BaseAgent, usage_tracker: Optional[ModelUsageTracker]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Run *agent* so every LLM call it makes is attributed to it."""
    if usage_tracker is None:
        return agent

    def node(state: dict[str, Any]) -> dict[str, Any]:
        with usage_tracker.step(agent.name):
            return agent(state)

    return node


def create_careerpilot_graph(
    profile_agent: ProfileAgent,
    matcher_agent: MatcherAgent,
    gap_agent: GapAnalyzerAgent,
    tailor_agent: TailorAgent,
    verifier_agent: VerifierAgent,
    usage_tracker: Optional[ModelUsageTracker] = None,
) -> Any:
    """Build and compile the workflow graph (with *usage_tracker*, LLM calls are tagged per agent)."""
    workflow = StateGraph(AgentWorkflowState)

    workflow.add_node(PROFILE_NODE, _tracked(profile_agent, usage_tracker))
    workflow.add_node(MATCHER_NODE, _tracked(matcher_agent, usage_tracker))
    workflow.add_node(GAP_NODE, _tracked(gap_agent, usage_tracker))
    workflow.add_node(TAILOR_NODE, _tracked(tailor_agent, usage_tracker))
    workflow.add_node(VERIFIER_NODE, _tracked(verifier_agent, usage_tracker))

    workflow.add_conditional_edges(START, route_request, list(set(_ENTRY_NODES.values())))
    workflow.add_conditional_edges(PROFILE_NODE, route_after_profile, [MATCHER_NODE, END])
    workflow.add_conditional_edges(MATCHER_NODE, route_after_matcher, [GAP_NODE, END])
    workflow.add_conditional_edges(GAP_NODE, route_after_gap, [TAILOR_NODE, END])
    # Tailoring is never returned unverified.
    workflow.add_edge(TAILOR_NODE, VERIFIER_NODE)
    workflow.add_edge(VERIFIER_NODE, END)

    return workflow.compile()
