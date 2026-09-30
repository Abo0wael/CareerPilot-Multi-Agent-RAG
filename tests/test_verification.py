"""Tests for claim verification: strict verdict parsing and removal of unsupported claims."""

from __future__ import annotations

import pytest

from src.domain.entities import (
    ClaimVerdict,
    ClaimVerification,
    TailoredBullet,
    TailoredCV,
    VerificationReport,
)
from src.domain.exceptions import InvalidEntityError


class TestClaimVerdictParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("supported", ClaimVerdict.SUPPORTED),
            ("  Supported ", ClaimVerdict.SUPPORTED),
            ("unsupported", ClaimVerdict.UNSUPPORTED),
            ("UNSUPPORTED", ClaimVerdict.UNSUPPORTED),
            ("not supported", ClaimVerdict.UNVERIFIED),
            ("supp", ClaimVerdict.UNVERIFIED),
            ("", ClaimVerdict.UNVERIFIED),
            (None, ClaimVerdict.UNVERIFIED),
            (1, ClaimVerdict.UNVERIFIED),
        ],
    )
    def test_only_exact_enum_values_are_accepted(self, raw: object, expected: ClaimVerdict) -> None:
        assert ClaimVerdict.from_llm(raw) is expected

    def test_unsupported_is_never_parsed_as_supported(self) -> None:
        # Regression: the old parser used `"supp" in verdict`, which matched "unsupported".
        assert ClaimVerdict.from_llm("unsupported") is not ClaimVerdict.SUPPORTED


def _cv(*tailored: str) -> TailoredCV:
    return TailoredCV(bullets=[TailoredBullet(original=f"o{i}", tailored=t) for i, t in enumerate(tailored)])


class TestApplyVerification:
    def test_unsupported_bullets_are_removed_and_kept_aside(self) -> None:
        cv = _cv("real claim", "fake metric", "unclear claim")
        report = VerificationReport(
            claims=[
                ClaimVerification("real claim", ClaimVerdict.SUPPORTED, "quote"),
                ClaimVerification("fake metric", ClaimVerdict.UNSUPPORTED, "invented 99.99%"),
                ClaimVerification("unclear claim", ClaimVerdict.UNVERIFIED),
            ]
        )
        cv.apply_verification(report)

        assert [b.tailored for b in cv.bullets] == ["real claim", "unclear claim"]
        assert [b.verdict for b in cv.bullets] == [ClaimVerdict.SUPPORTED, ClaimVerdict.UNVERIFIED]
        assert [b.tailored for b in cv.removed_bullets] == ["fake metric"]
        assert cv.removed_bullets[0].evidence == "invented 99.99%"
        assert cv.verification is report
        assert (report.supported_count, report.unsupported_count, report.unverified_count) == (1, 1, 1)

    def test_report_must_cover_every_bullet(self) -> None:
        cv = _cv("a", "b")
        with pytest.raises(InvalidEntityError):
            cv.apply_verification(VerificationReport(claims=[ClaimVerification("a", ClaimVerdict.SUPPORTED)]))
