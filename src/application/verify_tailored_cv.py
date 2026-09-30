"""Verify Tailored CV use case: audit every tailored claim and drop unsupported ones."""

from __future__ import annotations

import logging

from src.domain.entities import TailoredCV
from src.domain.interfaces import ClaimVerifier

logger = logging.getLogger(__name__)


class VerifyTailoredCVUseCase:
    """Check each tailored bullet against the original CV text.

    Unsupported bullets are moved to ``TailoredCV.removed_bullets`` so they are
    never presented as usable CV content.
    """

    def __init__(self, claim_verifier: ClaimVerifier) -> None:
        self._verifier = claim_verifier

    def execute(self, original_cv_text: str, tailored_cv: TailoredCV) -> TailoredCV:
        report = self._verifier.verify(original_cv_text, tailored_cv.bullets)
        tailored_cv.apply_verification(report)
        logger.info(
            "Verification: %d supported, %d unsupported (removed), %d unverified.",
            report.supported_count,
            report.unsupported_count,
            report.unverified_count,
        )
        return tailored_cv
