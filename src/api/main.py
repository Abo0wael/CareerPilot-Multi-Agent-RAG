"""FastAPI backend for CareerPilot.

Endpoints:
- GET  /health    index diagnostics (503 while the index has no jobs)
- POST /profile   CV file or text -> CandidateProfile            (graph: profile)
- POST /match     profile + preferences -> ranked JobMatch list  (graph: matcher)
- POST /gap       profile + job_id -> GapReport                   (graph: gap)
- POST /tailor    profile + job_id -> verified TailoredCV         (graph: tailor -> verifier)
- POST /pipeline  CV -> profile, matches, gap + tailored CV for the top match (full graph)
- POST /ingest    rebuild the index (requires X-Admin-Token)

Every reasoning endpoint runs the LangGraph workflow and reports, in
``model_calls``, which Groq model answered each agent (a fallback model answers
when the requested one stays rate-limited). Domain exceptions are mapped to
HTTP status codes in ``error_handlers.py``.

Opt-in protection for a public deployment: RATE_LIMIT (per client IP, 429 with
Retry-After) on every Groq-calling endpoint, and MAX_UPLOAD_MB on CV uploads (413).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware

from src.agents.workflow import CareerPilotWorkflow
from src.api.dependencies import (
    clear_app_state,
    enforce_rate_limit,
    get_index_stats,
    get_ingest_jobs_use_case,
    get_max_upload_bytes,
    get_model_usage_tracker,
    get_workflow,
    require_admin_token,
)
from src.api.error_handlers import register_error_handlers
from src.api.schemas import (
    CandidateProfileSchema,
    GapResponse,
    HealthResponse,
    IngestResponse,
    JobTargetRequest,
    MatchRequest,
    MatchResponse,
    ModelCallSchema,
    PipelineResponse,
    ProfileResponse,
    TailorResponse,
)
from src.application.ingest_jobs import IngestJobsUseCase
from src.domain.interfaces import IndexStatsReader, ModelUsageTracker
from src.infrastructure.config import CorsSettings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("CareerPilot API server starting.")
    yield
    clear_app_state()
    logger.info("CareerPilot API server shutdown.")


app = FastAPI(
    title="CareerPilot API",
    description="Multi-agent job matching, gap analysis and verified CV tailoring for job seekers.",
    version="1.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CorsSettings().origins,  # ALLOWED_ORIGINS in .env (the web UI)
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Admin-Token"],
    expose_headers=["Retry-After"],  # lets the browser read the rate-limit wait
)
register_error_handlers(app)

# Endpoints that call Groq; RATE_LIMIT applies to each of them (no-op when empty).
RATE_LIMITED = [Depends(enforce_rate_limit)]


async def _read_cv(file: Optional[UploadFile], raw_text: Optional[str], max_bytes: int) -> dict:
    """Return workflow CV input from a multipart upload or a text form field.

    Uploads larger than *max_bytes* are rejected with 413 before any parsing.
    """
    if file and file.filename:
        file_bytes = await file.read(max_bytes + 1)
        if len(file_bytes) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=f"CV file is too large: the limit is {max_bytes / (1024 * 1024):g} MB.",
            )
        return {"file_bytes": file_bytes, "filename": file.filename}
    if raw_text and raw_text.strip():
        return {"raw_text": raw_text.strip()}
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Must provide either an uploaded CV file or 'raw_text' form field.",
    )


@app.get("/health", response_model=HealthResponse, tags=["System"])
def health_check(response: Response, stats_reader: IndexStatsReader = Depends(get_index_stats)) -> HealthResponse:
    """Index diagnostics: job/chunk counts and FTS5 availability.

    Returns 503 with status "unavailable" while the index has no jobs, e.g. a missing database
    file (opening it creates an empty one), so readiness checks are reliable.
    """
    stats = stats_reader.get_stats()
    if stats.total_jobs == 0:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if stats.total_jobs else "unavailable",
        fts5_available=stats.fts5_available,
        total_jobs=stats.total_jobs,
        total_chunks=stats.total_chunks,
    )


@app.post("/profile", response_model=ProfileResponse, tags=["CV Profile"], dependencies=RATE_LIMITED)
async def build_profile(
    file: Optional[UploadFile] = File(None),
    raw_text: Optional[str] = Form(None),
    max_upload_bytes: int = Depends(get_max_upload_bytes),
    workflow: CareerPilotWorkflow = Depends(get_workflow),
    usage: ModelUsageTracker = Depends(get_model_usage_tracker),
) -> ProfileResponse:
    """Extract a structured profile from an uploaded CV (PDF / text) or a text form field."""
    cv_input = await _read_cv(file, raw_text, max_upload_bytes)
    with usage.collect() as calls:
        response = ProfileResponse.from_domain(workflow.build_profile(**cv_input))
    response.model_calls = ModelCallSchema.from_calls(calls)
    return response


@app.post("/match", response_model=MatchResponse, tags=["Matching"], dependencies=RATE_LIMITED)
def match_jobs(
    request: MatchRequest,
    workflow: CareerPilotWorkflow = Depends(get_workflow),
    usage: ModelUsageTracker = Depends(get_model_usage_tracker),
) -> MatchResponse:
    """BM25 retrieval over job sections + LLM query expansion and reranking."""
    with usage.collect() as calls:
        response = MatchResponse.from_domain(
            workflow.match(request.profile.to_domain(), request.preferences, request.top_k)
        )
    response.model_calls = ModelCallSchema.from_calls(calls)
    return response


@app.post("/gap", response_model=GapResponse, tags=["Gap Analysis"], dependencies=RATE_LIMITED)
def analyze_gap(
    request: JobTargetRequest,
    workflow: CareerPilotWorkflow = Depends(get_workflow),
    usage: ModelUsageTracker = Depends(get_model_usage_tracker),
) -> GapResponse:
    """Matched requirements (with CV evidence) and missing requirements for one job."""
    with usage.collect() as calls:
        response = GapResponse.from_domain(workflow.analyze_gap(request.profile.to_domain(), request.job_id))
    response.model_calls = ModelCallSchema.from_calls(calls)
    return response


@app.post("/tailor", response_model=TailorResponse, tags=["CV Tailoring"], dependencies=RATE_LIMITED)
def tailor_cv(
    request: JobTargetRequest,
    workflow: CareerPilotWorkflow = Depends(get_workflow),
    usage: ModelUsageTracker = Depends(get_model_usage_tracker),
) -> TailorResponse:
    """Tailor CV bullets for one job; unsupported claims are removed and listed separately."""
    with usage.collect() as calls:
        response = TailorResponse.from_domain(workflow.tailor(request.profile.to_domain(), request.job_id))
    response.model_calls = ModelCallSchema.from_calls(calls)
    return response


@app.post("/pipeline", response_model=PipelineResponse, tags=["Pipeline"], dependencies=RATE_LIMITED)
async def run_pipeline(
    file: Optional[UploadFile] = File(None),
    raw_text: Optional[str] = Form(None),
    preferences: str = Form(""),
    top_k: int = Form(10, ge=1, le=50),
    max_upload_bytes: int = Depends(get_max_upload_bytes),
    workflow: CareerPilotWorkflow = Depends(get_workflow),
    usage: ModelUsageTracker = Depends(get_model_usage_tracker),
) -> PipelineResponse:
    """Full flow: profile -> match -> gap -> tailor -> verify (for the top-ranked job)."""
    cv_input = await _read_cv(file, raw_text, max_upload_bytes)
    with usage.collect() as calls:
        result = workflow.run_pipeline(**cv_input, preferences=preferences, top_k=top_k)
    return PipelineResponse(
        profile=CandidateProfileSchema.from_domain(result.profile),
        matches=MatchResponse.from_domain(result.matches),
        target_job_id=result.target_job_id,
        gap=GapResponse.from_domain(result.gap_report) if result.gap_report else None,
        tailored_cv=TailorResponse.from_domain(result.tailored_cv) if result.tailored_cv else None,
        model_calls=ModelCallSchema.from_calls(calls),
    )


@app.post(
    "/ingest",
    response_model=IngestResponse,
    tags=["Admin"],
    dependencies=[Depends(require_admin_token)],
)
def rebuild_index(use_case: IngestJobsUseCase = Depends(get_ingest_jobs_use_case)) -> IngestResponse:
    """Rebuild the index from the raw dataset (zero LLM calls). Requires X-Admin-Token."""
    result = use_case.execute(clear_existing=True)
    return IngestResponse(
        status="success",
        jobs_ingested=result.jobs_ingested,
        chunks_indexed=result.chunks_indexed,
    )
