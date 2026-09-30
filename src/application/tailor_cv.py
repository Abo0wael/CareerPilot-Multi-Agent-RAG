"""Tailor CV use case: candidate profile + job id -> unverified ``TailoredCV``."""

from __future__ import annotations

from src.domain.entities import CandidateProfile, TailoredCV
from src.domain.interfaces import CVTailor, JobRepository


class TailorCVUseCase:
    """Rewrite the candidate's bullets for one job.

    The result is *unverified*; ``VerifyTailoredCVUseCase`` must run next.
    """

    def __init__(self, job_repository: JobRepository, cv_tailor: CVTailor) -> None:
        self._job_repo = job_repository
        self._tailor = cv_tailor

    def execute(self, profile: CandidateProfile, job_id: int) -> TailoredCV:
        """Raises ``JobNotFoundError`` if *job_id* does not exist."""
        job = self._job_repo.get_by_id(job_id)
        return self._tailor.tailor(profile, job)
