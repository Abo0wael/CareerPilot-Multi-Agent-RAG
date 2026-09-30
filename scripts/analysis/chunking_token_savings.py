"""Reranker input size: section chunks vs full postings, for the same top-20 jobs per profile.

For each of the 6 evaluation profiles, the exact 20 candidates the reranker receives
are rebuilt (same query, same cached expansion). Three job-text variants are measured:

  full      the whole posting description (what "no chunking" would send)
  sections  requirements + responsibilities + nice_to_have sections (llm/formatting.py);
            postings without recognised headers fall back to the full description
  deployed  the first 600 characters of the description (current GroqReranker)

A 20-job prompt of full postings exceeds Groq's 8,000 tokens/minute limit, so tokens
are not measured by sending the prompts. Instead characters are counted exactly and
converted with a chars-per-token ratio calibrated from Groq's reported
``usage.prompt_tokens`` on real job texts (8 postings, full text and sections, each
sent alone with max_tokens=1, minus the fixed per-message overhead).

Usage: python scripts/analysis/chunking_token_savings.py
Output: outputs/evaluation/chunking_token_savings.json
"""

from __future__ import annotations

import json
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "scripts")]

from groq import Groq  # noqa: E402

from evaluate import FIXTURES, IdentityExpander, NoRerank  # noqa: E402,F401
from src.application.build_profile import BuildProfileUseCase  # noqa: E402
from src.application.match_jobs import MatchJobsUseCase  # noqa: E402
from src.infrastructure.config import get_settings  # noqa: E402
from src.infrastructure.llm.client import GroqClient  # noqa: E402
from src.infrastructure.llm.formatting import relevant_job_text  # noqa: E402
from src.infrastructure.llm.profile_extractor import GroqProfileExtractor  # noqa: E402
from src.infrastructure.parsing.cv_parser import UniversalCVParser  # noqa: E402
from src.infrastructure.retrieval.expander import GroqQueryExpander  # noqa: E402
from src.infrastructure.search.sqlite_index import SQLiteFTSIndex, SQLiteJobRepository  # noqa: E402

RERANK_CANDIDATES = 20
DEPLOYED_CHARS = 600
NO_CAP = 10**9
OUTPUT = ROOT / "outputs" / "evaluation" / "chunking_token_savings.json"


def prompt_tokens(client: Groq, model: str, text: str) -> int:
    """Groq-reported prompt tokens for a single user message (waits on 429)."""
    for _ in range(10):
        try:
            r = client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": text}], max_tokens=1
            )
            return r.usage.prompt_tokens
        except Exception as err:  # noqa: BLE001 - calibration only; retry on rate limit
            if "rate" not in str(err).lower():
                raise
            time.sleep(20)
    raise RuntimeError("Groq rate limit did not clear during calibration.")


def main() -> None:
    settings = get_settings()
    llm = GroqClient(settings=settings)  # cached: profiles and expansions come from the evaluation cache
    index = SQLiteFTSIndex(settings.index_path)
    repo = SQLiteJobRepository(settings.index_path)
    profiles = BuildProfileUseCase(
        UniversalCVParser(),
        GroqProfileExtractor(llm, model=settings.model_for(settings.profile_model), max_cv_chars=settings.prompt_max_cv_chars),
    )
    candidates = MatchJobsUseCase(
        index, GroqQueryExpander(llm, model=settings.groq_fast_model), NoRerank(), repo,
        top_n=settings.bm25_top_n, top_k=RERANK_CANDIDATES,
    )

    per_profile = []
    all_jobs = {}
    for filename, family in FIXTURES:
        path = ROOT / "tests" / "fixtures" / filename
        jobs = [m.job for m in candidates.execute(profiles.execute(path.read_bytes(), filename))]
        for job in jobs:
            all_jobs[job.job_id] = job
        chars = {
            "full": sum(len(j.description) for j in jobs),
            "sections": sum(len(relevant_job_text(j, NO_CAP)) for j in jobs),
            "deployed": sum(len(j.description[:DEPLOYED_CHARS]) for j in jobs),
        }
        sectioned = [j for j in jobs if relevant_job_text(j, NO_CAP) != j.description]
        chars["full_sectioned_jobs_only"] = sum(len(j.description) for j in sectioned)
        chars["sections_sectioned_jobs_only"] = sum(len(relevant_job_text(j, NO_CAP)) for j in sectioned)
        per_profile.append({
            "profile": family,
            "jobs": len(jobs),
            "jobs_with_sections": sum(relevant_job_text(j, NO_CAP) != j.description for j in jobs),
            "chars": chars,
        })

    # Calibrate chars/token on real job texts using Groq's reported usage.
    groq = Groq(api_key=settings.groq_api_key)
    model = settings.groq_fast_model
    overhead = prompt_tokens(groq, model, "x") - 1
    sample = random.Random(7).sample(
        [j for j in all_jobs.values() if relevant_job_text(j, NO_CAP) != j.description], 8
    )
    calib = {"full": [0, 0], "sections": [0, 0]}  # [chars, tokens]
    for job in sample:
        for variant, text in (("full", job.description), ("sections", relevant_job_text(job, NO_CAP))):
            calib[variant][0] += len(text)
            calib[variant][1] += prompt_tokens(groq, model, text) - overhead
    ratio = {v: c / t for v, (c, t) in calib.items()}
    ratio["deployed"] = ratio["full"]  # a prefix of the same text
    ratio["full_sectioned_jobs_only"] = ratio["full"]
    ratio["sections_sectioned_jobs_only"] = ratio["sections"]

    for row in per_profile:
        row["est_tokens"] = {v: round(c / ratio[v]) for v, c in row["chars"].items()}
        full = row["est_tokens"]["full"]
        row["saved_vs_full_pct"] = {
            v: round(100 * (1 - row["est_tokens"][v] / full), 1) for v in ("sections", "deployed")
        }

    avg = {v: round(sum(r["est_tokens"][v] for r in per_profile) / len(per_profile)) for v in ("full", "sections", "deployed")}
    result = {
        "method": "exact character counts; tokens = chars / ratio calibrated from Groq usage.prompt_tokens",
        "calibration_model": model,
        "calibration_jobs": len(sample),
        "per_message_overhead_tokens": overhead,
        "chars_per_token": {v: round(r, 2) for v, r in ratio.items()},
        "per_profile": per_profile,
        "average_job_text_tokens_per_rerank_call": avg,
        "average_saved_vs_full_pct": {
            v: round(100 * (1 - avg[v] / avg["full"]), 1) for v in ("sections", "deployed")
        },
        "saved_on_postings_with_headers_pct": round(100 * (1 - sum(
            r["est_tokens"]["sections_sectioned_jobs_only"] for r in per_profile) / sum(
            r["est_tokens"]["full_sectioned_jobs_only"] for r in per_profile)), 1),
        "share_of_candidates_with_headers": round(
            sum(r["jobs_with_sections"] for r in per_profile) / sum(r["jobs"] for r in per_profile), 3),
        "note": "Job-text tokens only; the rerank prompt adds about 500 tokens of instructions and candidate profile.",
    }
    OUTPUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("chars_per_token", "average_job_text_tokens_per_rerank_call",
                                              "average_saved_vs_full_pct", "saved_on_postings_with_headers_pct",
                                              "share_of_candidates_with_headers")}, indent=2))
    for r in per_profile:
        print(r["profile"], r["jobs_with_sections"], "/", r["jobs"], "sectioned |", r["est_tokens"], r["saved_vs_full_pct"])


if __name__ == "__main__":
    main()
