"""In-memory fakes for every domain port. Tests never call Groq."""

from __future__ import annotations

from typing import Any, Optional

from src.domain.entities import (
    CandidateProfile,
    ClaimVerdict,
    ClaimVerification,
    GapReport,
    JobMatch,
    JobPosting,
    ScoredChunk,
    SearchQuery,
    TailoredBullet,
    TailoredCV,
    VerificationReport,
)
from src.domain.exceptions import JobNotFoundError
from src.domain.interfaces import (
    ClaimVerifier,
    CVParser,
    CVTailor,
    GapAnalyzer,
    JobRepository,
    LLMClient,
    ProfileExtractor,
    QueryExpander,
    Reranker,
    Retriever,
)


class FakeLLMClient(LLMClient):
    """Returns canned responses (or raises *error*) and records every call."""

    def __init__(
        self,
        text_response: str = "Fake response",
        json_response: Optional[dict[str, Any]] = None,
        error: Optional[Exception] = None,
    ) -> None:
        self.text_response = text_response
        self.json_response = json_response or {}
        self.error = error
        self.generate_calls: list[dict[str, Any]] = []
        self.json_calls: list[dict[str, Any]] = []

    def generate(self, prompt: str, system_prompt: str = "", model: Optional[str] = None,
                 temperature: float = 0.0, max_tokens: int = 4096) -> str:
        self.generate_calls.append({"prompt": prompt, "system_prompt": system_prompt, "model": model})
        if self.error:
            raise self.error
        return self.text_response

    def generate_json(self, prompt: str, system_prompt: str = "", model: Optional[str] = None,
                      temperature: float = 0.0, max_tokens: int = 4096) -> dict[str, Any]:
        self.json_calls.append({"prompt": prompt, "system_prompt": system_prompt, "model": model})
        if self.error:
            raise self.error
        return self.json_response


class FakeJobRepository(JobRepository):
    def __init__(self, postings: list[JobPosting]) -> None:
        self._jobs = {j.job_id: j for j in postings}

    def get_by_id(self, job_id: int) -> JobPosting:
        if job_id not in self._jobs:
            raise JobNotFoundError(job_id)
        return self._jobs[job_id]

    def get_by_ids(self, job_ids: list[int]) -> list[JobPosting]:
        return [self._jobs[jid] for jid in job_ids if jid in self._jobs]


class FakeRetriever(Retriever):
    def __init__(self, chunks: list[ScoredChunk]) -> None:
        self._chunks = chunks
        self.searched_queries: list[SearchQuery] = []

    def search(self, query: SearchQuery, top_n: int = 50, sections: Optional[list[str]] = None,
               excluded_sections: Optional[list[str]] = None) -> list[ScoredChunk]:
        self.searched_queries.append(query)
        return self._chunks[:top_n]


class IdentityExpander(QueryExpander):
    def expand(self, query: SearchQuery) -> SearchQuery:
        return query


class PassThroughReranker(Reranker):
    def rerank(self, profile: CandidateProfile, matches: list[JobMatch], top_k: int = 10) -> list[JobMatch]:
        return matches[:top_k]


class FakeCVParser(CVParser):
    def parse(self, file_bytes: bytes, filename: str) -> str:
        return file_bytes.decode("utf-8")


class FakeProfileExtractor(ProfileExtractor):
    def __init__(self, skills: Optional[list[str]] = None) -> None:
        self.skills = skills or ["Python"]
        self.calls: list[str] = []

    def extract(self, raw_cv_text: str) -> CandidateProfile:
        self.calls.append(raw_cv_text)
        return CandidateProfile(raw_text=raw_cv_text, skills=list(self.skills))


class FakeGapAnalyzer(GapAnalyzer):
    def __init__(self) -> None:
        self.calls: list[int] = []

    def analyze(self, profile: CandidateProfile, job: JobPosting) -> GapReport:
        self.calls.append(job.job_id)
        return GapReport(job_id=job.job_id, job_title=job.title, summary="fake gap")


class FakeCVTailor(CVTailor):
    def __init__(self, tailored: Optional[list[str]] = None) -> None:
        self.tailored = tailored or ["Built REST APIs with FastAPI"]
        self.calls: list[int] = []

    def tailor(self, profile: CandidateProfile, job: JobPosting) -> TailoredCV:
        self.calls.append(job.job_id)
        return TailoredCV(
            bullets=[TailoredBullet(original="orig", tailored=t) for t in self.tailored],
            summary="fake tailoring",
        )


class FakeClaimVerifier(ClaimVerifier):
    """Marks a bullet unsupported if it contains any of *fabrications*, else supported."""

    def __init__(self, fabrications: Optional[list[str]] = None) -> None:
        self.fabrications = fabrications or []
        self.calls: list[int] = []

    def verify(self, original_cv_text: str, bullets: list[TailoredBullet]) -> VerificationReport:
        self.calls.append(len(bullets))
        return VerificationReport(
            claims=[
                ClaimVerification(
                    claim=b.tailored,
                    verdict=ClaimVerdict.UNSUPPORTED
                    if any(f in b.tailored for f in self.fabrications)
                    else ClaimVerdict.SUPPORTED,
                )
                for b in bullets
            ]
        )
