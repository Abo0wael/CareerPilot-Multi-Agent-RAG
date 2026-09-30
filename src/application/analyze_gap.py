"""Analyze Gap use case: candidate profile + job id -> grounded ``GapReport``."""

from __future__ import annotations

from src.domain.entities import CandidateProfile, GapReport
from src.domain.interfaces import GapAnalyzer, JobRepository


class AnalyzeGapUseCase:
    """Load the target job and compare the candidate against its requirements."""

    def __init__(self, job_repository: JobRepository, gap_analyzer: GapAnalyzer) -> None:
        self._job_repo = job_repository
        self._analyzer = gap_analyzer

    def execute(self, profile: CandidateProfile, job_id: int) -> GapReport:
        """Raises ``JobNotFoundError`` if *job_id* does not exist."""
        job = self._job_repo.get_by_id(job_id)
        return self._analyzer.analyze(profile, job)
