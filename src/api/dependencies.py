"""Composition root: the only place (besides scripts) where concrete classes are created.

Layer direction: api -> agents -> application -> domain <- infrastructure.
Endpoints receive a ``CareerPilotWorkflow`` (agents) or domain ports; they never
see SQLite or Groq classes directly.
"""

from __future__ import annotations

import logging
import math
import secrets
import time
from typing import Any, Optional

from fastapi import Depends, Header, HTTPException, Request, status
from limits import parse as parse_rate_limit
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.agents.gap_agent import GapAnalyzerAgent
from src.agents.graph import create_careerpilot_graph
from src.agents.matcher_agent import MatcherAgent
from src.agents.profile_agent import ProfileAgent
from src.agents.tailor_agent import TailorAgent
from src.agents.verifier_agent import VerifierAgent
from src.agents.workflow import CareerPilotWorkflow
from src.application.analyze_gap import AnalyzeGapUseCase
from src.application.build_profile import BuildProfileUseCase
from src.application.ingest_jobs import IngestJobsUseCase
from src.application.match_jobs import MatchJobsUseCase
from src.application.tailor_cv import TailorCVUseCase
from src.application.verify_tailored_cv import VerifyTailoredCVUseCase
from src.domain.interfaces import IndexStatsReader, LLMClient, ModelUsageTracker
from src.infrastructure.chunking.chunkers import CompositeChunker
from src.infrastructure.config import Settings, get_settings
from src.infrastructure.data.loader import KaggleDataLoader
from src.infrastructure.llm.claim_verifier import GroqClaimVerifier
from src.infrastructure.llm.client import GroqClient
from src.infrastructure.llm.cv_tailor import GroqCVTailor
from src.infrastructure.llm.gap_analyzer import GroqGapAnalyzer
from src.infrastructure.llm.model_usage import ContextModelUsageTracker
from src.infrastructure.llm.profile_extractor import GroqProfileExtractor
from src.infrastructure.parsing.cv_parser import UniversalCVParser
from src.infrastructure.retrieval.expander import GroqQueryExpander
from src.infrastructure.retrieval.reranker import GroqReranker
from src.infrastructure.search.sqlite_index import SQLiteFTSIndex, SQLiteJobRepository

logger = logging.getLogger(__name__)

# Shared singletons (released on shutdown).
_app_state: dict[str, Any] = {}


def _singleton(key: str, factory: Any) -> Any:
    if key not in _app_state:
        _app_state[key] = factory()
    return _app_state[key]


def _sqlite_index(settings: Settings) -> SQLiteFTSIndex:
    def create() -> SQLiteFTSIndex:
        index = SQLiteFTSIndex(settings.index_path)
        index.initialize()
        return index

    return _singleton("index", create)


def _job_repository(settings: Settings) -> SQLiteJobRepository:
    return _singleton("job_repo", lambda: SQLiteJobRepository(settings.index_path))


def _usage_tracker() -> ContextModelUsageTracker:
    return _singleton("usage_tracker", ContextModelUsageTracker)


def _rate_limiter() -> Limiter:
    # In-memory storage: counters live in this process and reset on restart (one Space container).
    return _singleton("rate_limiter", lambda: Limiter(key_func=get_remote_address))


def _llm_client(settings: Settings) -> GroqClient:
    return _singleton("llm_client", lambda: GroqClient(settings=settings, usage_tracker=_usage_tracker()))


def build_workflow(
    settings: Settings, llm: LLMClient, usage_tracker: Optional[ModelUsageTracker] = None
) -> CareerPilotWorkflow:
    """Wire use cases, agents and the LangGraph graph (also used by scripts).

    Pass the same *usage_tracker* the LLM client records into to tag calls per agent.
    """
    job_repo = _job_repository(settings)
    fast = settings.groq_fast_model
    match_use_case = MatchJobsUseCase(
        retriever=_sqlite_index(settings),
        query_expander=GroqQueryExpander(llm_client=llm, model=fast),
        reranker=GroqReranker(llm_client=llm, model=fast),
        job_repository=job_repo,
        top_n=settings.bm25_top_n,
        top_k=settings.rerank_top_k,
        expansion_weight=settings.expansion_weight,
    )
    profile_use_case = BuildProfileUseCase(
        cv_parser=UniversalCVParser(),
        profile_extractor=GroqProfileExtractor(
            llm, model=settings.model_for(settings.profile_model), max_cv_chars=settings.prompt_max_cv_chars
        ),
    )
    gap_use_case = AnalyzeGapUseCase(
        job_repository=job_repo,
        gap_analyzer=GroqGapAnalyzer(
            llm, model=settings.model_for(settings.gap_model), max_job_chars=settings.prompt_max_job_chars_gap
        ),
    )
    tailor_use_case = TailorCVUseCase(
        job_repository=job_repo,
        cv_tailor=GroqCVTailor(
            llm,
            model=settings.model_for(settings.tailor_model),
            max_job_chars=settings.prompt_max_job_chars_tailor,
            max_bullets=settings.tailor_max_bullets,
        ),
    )
    verify_use_case = VerifyTailoredCVUseCase(
        claim_verifier=GroqClaimVerifier(
            llm, model=settings.model_for(settings.verifier_model), max_cv_chars=settings.prompt_max_cv_chars
        ),
    )
    graph = create_careerpilot_graph(
        profile_agent=ProfileAgent(profile_use_case),
        matcher_agent=MatcherAgent(match_use_case),
        gap_agent=GapAnalyzerAgent(gap_use_case),
        tailor_agent=TailorAgent(tailor_use_case),
        verifier_agent=VerifierAgent(verify_use_case),
        usage_tracker=usage_tracker,
    )
    return CareerPilotWorkflow(graph)


# ── FastAPI providers ────────────────────────────────────────────────

def get_workflow(settings: Settings = Depends(get_settings)) -> CareerPilotWorkflow:
    """Provide the multi-agent workflow (built once)."""
    return _singleton("workflow", lambda: build_workflow(settings, _llm_client(settings), _usage_tracker()))


def get_model_usage_tracker() -> ModelUsageTracker:
    """Provide the tracker that reports which model answered each agent's LLM calls."""
    return _usage_tracker()


def get_index_stats(settings: Settings = Depends(get_settings)) -> IndexStatsReader:
    """Provide index diagnostics through the domain port."""
    return _sqlite_index(settings)


def get_ingest_jobs_use_case(settings: Settings = Depends(get_settings)) -> IngestJobsUseCase:
    """Wire the index rebuild use case."""
    return IngestJobsUseCase(
        job_source=KaggleDataLoader(settings),
        chunker=CompositeChunker(
            max_length=settings.paragraph_chunk_max_length,
            min_length=settings.chunk_min_length,
            overlap=settings.paragraph_chunk_overlap,
        ),
        index_writer=_sqlite_index(settings),
    )


def enforce_rate_limit(request: Request, settings: Settings = Depends(get_settings)) -> None:
    """Reject the request with 429 when the client IP exceeds RATE_LIMIT on this endpoint.

    Counted per (client IP, endpoint path). Disabled when RATE_LIMIT is empty (the default).
    Behind a proxy, uvicorn's --proxy-headers makes ``request.client`` the real client IP.
    """
    if not settings.rate_limit:
        return
    limit = parse_rate_limit(settings.rate_limit)
    strategy = _rate_limiter().limiter
    key = get_remote_address(request)
    if strategy.hit(limit, key, request.url.path):
        return
    reset_time, _ = strategy.get_window_stats(limit, key, request.url.path)
    retry_after = max(1, math.ceil(reset_time - time.time()))
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=f"Rate limit exceeded ({settings.rate_limit} per client). Retry in {retry_after} seconds.",
        headers={"Retry-After": str(retry_after)},
    )


def get_max_upload_bytes(settings: Settings = Depends(get_settings)) -> int:
    """Largest accepted CV upload in bytes (MAX_UPLOAD_MB)."""
    return int(settings.max_upload_mb * 1024 * 1024)


def require_admin_token(
    x_admin_token: Optional[str] = Header(default=None),
    settings: Settings = Depends(get_settings),
) -> None:
    """Reject the request unless X-Admin-Token matches ADMIN_TOKEN from .env."""
    if not settings.admin_token:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin endpoints are disabled (ADMIN_TOKEN not set).")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing X-Admin-Token.")


def clear_app_state() -> None:
    """Release open database connections on shutdown."""
    for key in ("index", "job_repo"):
        resource = _app_state.get(key)
        if resource is not None:
            resource.close()
    _app_state.clear()
