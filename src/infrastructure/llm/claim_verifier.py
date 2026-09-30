"""Groq implementation of ``ClaimVerifier``."""

from __future__ import annotations

from typing import Optional

from src.domain.entities import ClaimVerdict, ClaimVerification, TailoredBullet, VerificationReport
from src.domain.interfaces import ClaimVerifier, LLMClient
from src.infrastructure.llm.formatting import dict_list
from src.infrastructure.llm.prompts.verifier_prompts import (
    VERIFIER_SYSTEM_PROMPT,
    VERIFIER_USER_PROMPT_TEMPLATE,
)


class GroqClaimVerifier(ClaimVerifier):
    """Audits numbered bullets against the original CV with one Groq JSON call.

    Verdicts are matched to bullets by ``bullet_id`` (not by echoed text) and
    parsed strictly; any bullet without a valid verdict is ``UNVERIFIED``.
    """

    def __init__(self, llm_client: LLMClient, model: Optional[str] = None, max_cv_chars: int = 12000) -> None:
        self._llm = llm_client
        self._model = model
        self._max_cv_chars = max_cv_chars

    def verify(self, original_cv_text: str, bullets: list[TailoredBullet]) -> VerificationReport:
        if not bullets:
            return VerificationReport()

        numbered = "\n".join(f"[{i}] {b.tailored}" for i, b in enumerate(bullets, start=1))
        data = self._llm.generate_json(
            prompt=VERIFIER_USER_PROMPT_TEMPLATE.format(
                original_cv_text=original_cv_text[: self._max_cv_chars],
                tailored_bullets=numbered,
            ),
            system_prompt=VERIFIER_SYSTEM_PROMPT,
            model=self._model,
            temperature=0.0,
        )

        by_id: dict[int, dict] = {}
        for item in dict_list(data.get("verifications")):
            bullet_id = item.get("bullet_id")
            if isinstance(bullet_id, int) and not isinstance(bullet_id, bool):
                by_id.setdefault(bullet_id, item)

        return VerificationReport(
            claims=[
                ClaimVerification(
                    claim=bullet.tailored,
                    verdict=ClaimVerdict.from_llm(by_id.get(i, {}).get("verdict")),
                    evidence=str(by_id.get(i, {}).get("evidence", "")).strip(),
                )
                for i, bullet in enumerate(bullets, start=1)
            ]
        )
