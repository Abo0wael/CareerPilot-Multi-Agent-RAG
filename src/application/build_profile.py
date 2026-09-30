"""Build Profile use case: CV file or text -> structured ``CandidateProfile``."""

from __future__ import annotations

import logging

from src.domain.entities import CandidateProfile
from src.domain.interfaces import CVParser, ProfileExtractor

logger = logging.getLogger(__name__)


class BuildProfileUseCase:
    """Parse a CV and extract a structured profile.

    Depends only on the ``CVParser`` and ``ProfileExtractor`` ports.
    """

    def __init__(self, cv_parser: CVParser, profile_extractor: ProfileExtractor) -> None:
        self._cv_parser = cv_parser
        self._extractor = profile_extractor

    def execute(self, file_bytes: bytes, filename: str) -> CandidateProfile:
        """Extract a profile from an uploaded CV file (.pdf or .txt)."""
        raw_text = self._cv_parser.parse(file_bytes, filename)
        logger.info("Parsed CV '%s' (%d characters).", filename, len(raw_text))
        return self._extractor.extract(raw_text)

    def execute_from_text(self, raw_text: str) -> CandidateProfile:
        """Extract a profile from CV text supplied directly."""
        return self._extractor.extract(raw_text)
