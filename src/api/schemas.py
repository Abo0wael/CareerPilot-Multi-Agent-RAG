"""Pydantic request/response schemas and their mapping to/from domain entities."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from src.domain.entities import (
    CandidateProfile,
    EducationEntry,
    ExperienceEntry,
    GapItem,
    GapReport,
    JobMatch,
    ModelCall,
    ProjectEntry,
    TailoredBullet,
    TailoredCV,
)


# ── Candidate profile ────────────────────────────────────────────────

class ExperienceItem(BaseModel):
    role: str
    company: str = ""
    duration: str = ""
    bullets: list[str] = Field(default_factory=list)


class ProjectItem(BaseModel):
    name: str
    description: str = ""
    technologies: list[str] = Field(default_factory=list)


class EducationItem(BaseModel):
    degree: str
    institution: str = ""
    year: str = ""
    details: str = ""


class CandidateProfileSchema(BaseModel):
    """Structured representation of a candidate CV."""

    raw_text: str = Field(..., description="Raw plain text of the CV.")
    name: str = ""
    email: str = ""
    phone: str = ""
    summary: str = ""
    skills: list[str] = Field(default_factory=list)
    experiences: list[ExperienceItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)

    def to_domain(self) -> CandidateProfile:
        return CandidateProfile(
            raw_text=self.raw_text,
            name=self.name,
            email=self.email,
            phone=self.phone,
            summary=self.summary,
            skills=self.skills,
            experiences=[ExperienceEntry(**e.model_dump()) for e in self.experiences],
            projects=[ProjectEntry(**p.model_dump()) for p in self.projects],
            education=[EducationEntry(**ed.model_dump()) for ed in self.education],
            certifications=self.certifications,
        )

    @classmethod
    def from_domain(cls, profile: CandidateProfile) -> CandidateProfileSchema:
        return cls(
            raw_text=profile.raw_text,
            name=profile.name,
            email=profile.email,
            phone=profile.phone,
            summary=profile.summary,
            skills=profile.skills,
            experiences=[ExperienceItem(**vars(e)) for e in profile.experiences],
            projects=[ProjectItem(**vars(p)) for p in profile.projects],
            education=[EducationItem(**vars(ed)) for ed in profile.education],
            certifications=profile.certifications,
        )


# ── Model usage ──────────────────────────────────────────────────────

class ModelCallSchema(BaseModel):
    """Which Groq model answered one LLM request of an agent."""

    agent: str
    requested_model: str
    answered_model: str
    used_fallback: bool = Field(..., description="True if the requested model was rate-limited and a fallback answered.")
    cached: bool = Field(..., description="True if the answer came from the LLM disk cache.")

    @classmethod
    def from_domain(cls, call: ModelCall) -> ModelCallSchema:
        return cls(
            agent=call.agent,
            requested_model=call.requested_model,
            answered_model=call.answered_model,
            used_fallback=call.used_fallback,
            cached=call.cached,
        )

    @classmethod
    def from_calls(cls, calls: list[ModelCall]) -> list[ModelCallSchema]:
        return [cls.from_domain(c) for c in calls]


class ProfileResponse(CandidateProfileSchema):
    """The profile plus the models that produced it (extra fields are ignored when sent back)."""

    model_calls: list[ModelCallSchema] = Field(default_factory=list)


# ── Requests ─────────────────────────────────────────────────────────

class MatchRequest(BaseModel):
    profile: CandidateProfileSchema
    preferences: str = Field(default="", description="Optional preferences, e.g. 'remote Python backend'.")
    top_k: int = Field(default=10, ge=1, le=50, description="Number of matches to return.")


class JobTargetRequest(BaseModel):
    """Payload for /gap and /tailor."""

    profile: CandidateProfileSchema
    job_id: int = Field(..., description="ID of the target job posting.")


# ── Responses ────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    fts5_available: bool
    total_jobs: int
    total_chunks: int


class MatchedJobItem(BaseModel):
    job_id: int
    title: str
    company_name: str
    location: str
    formatted_experience_level: str
    formatted_work_type: str
    remote_allowed: bool
    score: float
    reason: str
    skills: list[str]

    @classmethod
    def from_domain(cls, match: JobMatch) -> MatchedJobItem:
        job = match.job
        return cls(
            job_id=job.job_id,
            title=job.title,
            company_name=job.company_name,
            location=job.location,
            formatted_experience_level=job.formatted_experience_level,
            formatted_work_type=job.formatted_work_type,
            remote_allowed=job.remote_allowed,
            score=round(match.score, 2),
            reason=match.reason,
            skills=job.skills,
        )


class MatchResponse(BaseModel):
    total_matches: int
    matches: list[MatchedJobItem]
    model_calls: list[ModelCallSchema] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, matches: list[JobMatch]) -> MatchResponse:
        return cls(total_matches=len(matches), matches=[MatchedJobItem.from_domain(m) for m in matches])


class GapItemSchema(BaseModel):
    requirement: str
    matched: bool
    evidence: str = ""

    @classmethod
    def from_domain(cls, item: GapItem) -> GapItemSchema:
        return cls(requirement=item.requirement, matched=item.matched, evidence=item.evidence)


class GapResponse(BaseModel):
    job_id: int
    job_title: str
    matched_items: list[GapItemSchema]
    missing_items: list[GapItemSchema]
    summary: str
    model_calls: list[ModelCallSchema] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, report: GapReport) -> GapResponse:
        return cls(
            job_id=report.job_id,
            job_title=report.job_title,
            matched_items=[GapItemSchema.from_domain(i) for i in report.matched_items],
            missing_items=[GapItemSchema.from_domain(i) for i in report.missing_items],
            summary=report.summary,
        )


class TailoredBulletSchema(BaseModel):
    section: str = ""
    original: str
    tailored: str
    verdict: Optional[str] = Field(default=None, description="supported | unsupported | unverified")
    evidence: str = ""

    @classmethod
    def from_domain(cls, bullet: TailoredBullet) -> TailoredBulletSchema:
        return cls(
            section=bullet.section,
            original=bullet.original,
            tailored=bullet.tailored,
            verdict=bullet.verdict.value if bullet.verdict else None,
            evidence=bullet.evidence,
        )


class VerificationSummarySchema(BaseModel):
    total_claims: int
    supported_claims: int
    unsupported_claims: int
    unverified_claims: int


class TailorResponse(BaseModel):
    """Tailored CV. ``bullets`` excludes unsupported claims; they are listed in ``removed_bullets``."""

    summary: str
    bullets: list[TailoredBulletSchema]
    removed_bullets: list[TailoredBulletSchema]
    verification: Optional[VerificationSummarySchema] = None
    model_calls: list[ModelCallSchema] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, tailored: TailoredCV) -> TailorResponse:
        report = tailored.verification
        return cls(
            summary=tailored.summary,
            bullets=[TailoredBulletSchema.from_domain(b) for b in tailored.bullets],
            removed_bullets=[TailoredBulletSchema.from_domain(b) for b in tailored.removed_bullets],
            verification=VerificationSummarySchema(
                total_claims=report.total_count,
                supported_claims=report.supported_count,
                unsupported_claims=report.unsupported_count,
                unverified_claims=report.unverified_count,
            )
            if report
            else None,
        )


class PipelineResponse(BaseModel):
    """Full flow: profile -> matches -> gap report + tailored CV for the top match."""

    profile: CandidateProfileSchema
    matches: MatchResponse
    target_job_id: Optional[int] = None
    gap: Optional[GapResponse] = None
    tailored_cv: Optional[TailorResponse] = None
    model_calls: list[ModelCallSchema] = Field(default_factory=list, description="Every LLM call of the run, per agent.")


class IngestResponse(BaseModel):
    status: str
    jobs_ingested: int
    chunks_indexed: int
