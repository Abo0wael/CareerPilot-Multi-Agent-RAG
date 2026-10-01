"""Pre-run the demo scenarios through the multi-agent workflow to fill the LLM cache.

Uses exactly the API wiring (``build_workflow``) and the same step-by-step calls the
web UI makes (/profile, /match, /gap, /tailor), so a live demo with the same CV and
empty preferences makes zero Groq calls and cannot hit Groq's 8,000 tokens/minute limit.

Scenarios (the web UI offers both):
  demo1  backend CV; analyses the top match
  demo2  entry-level frontend CV; analyses job 3900943289, where the evaluation
         (run 3) recorded the Verifier removing a fabricated claim

Each scenario runs twice: pass 1 fills the cache (live Groq calls unless already
cached), pass 2 must be all cache hits. Removed bullets are printed as returned by
the Verifier; nothing is injected. Because LLM output is not fully deterministic, a
cold run (empty cache) may produce different bullets and may remove none.

Usage:
    python scripts/warm_demo_cache.py [--scenario demo1|demo2|all]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from metering import MeteredLLMClient  # noqa: E402

from src.api.dependencies import build_workflow  # noqa: E402
from src.infrastructure.config import get_settings  # noqa: E402
from src.infrastructure.llm.client import GroqClient  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
# LLM output contains characters such as U+2011 that the Windows console code page cannot encode.
sys.stdout.reconfigure(encoding="utf-8")

FIXTURES = _ROOT / "tests" / "fixtures"
OUTPUT = _ROOT / "outputs" / "evaluation" / "demo_warmup.json"
TOP_K = 10  # the UI's default


@dataclass(frozen=True)
class Scenario:
    name: str
    cv: Path
    job_id: Optional[int]  # None = the top match


SCENARIOS = {
    "demo1": Scenario("demo1", FIXTURES / "sample_cv_backend_engineer.txt", None),
    "demo2": Scenario("demo2", FIXTURES / "sample_cv_frontend_entry_level.txt", 3900943289),
}


def run_pass(scenario: Scenario) -> dict:
    settings = get_settings()
    llm = MeteredLLMClient(GroqClient(settings=settings))
    workflow = build_workflow(settings, llm)
    t0 = time.perf_counter()
    profile = workflow.build_profile(file_bytes=scenario.cv.read_bytes(), filename=scenario.cv.name)
    matches = workflow.match(profile, preferences="", top_k=TOP_K)
    match_ids = [m.job.job_id for m in matches]
    job_id = scenario.job_id if scenario.job_id is not None else match_ids[0]
    gap = workflow.analyze_gap(profile, job_id)
    tailored = workflow.tailor(profile, job_id)
    elapsed = time.perf_counter() - t0
    steps = llm.summary()
    report = tailored.verification
    return {
        "wall_time_s": round(elapsed, 2),
        "groq_calls": sum(s["groq_calls"] for s in steps.values()),
        "total_tokens": sum(s["total_tokens"] for s in steps.values()),
        "rate_limit_429s": sum(s["rate_limit_429s"] for s in steps.values()),
        "analysed_job_id": job_id,
        "analysed_job_title": gap.job_title,
        "analysed_job_rank_in_matches": match_ids.index(job_id) + 1 if job_id in match_ids else None,
        "claims": report.total_count if report else 0,
        "supported": report.supported_count if report else 0,
        "removed": [{"bullet": b.tailored, "reason": b.evidence} for b in tailored.removed_bullets],
        "steps": steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    args = parser.parse_args()
    chosen = list(SCENARIOS.values()) if args.scenario == "all" else [SCENARIOS[args.scenario]]

    results = {}
    not_cached = False
    for scenario in chosen:
        passes = {"pass_1_fill_cache": run_pass(scenario), "pass_2_from_cache": run_pass(scenario)}
        results[scenario.name] = {"cv": scenario.cv.name, "job_id": scenario.job_id, **passes}
        for name, p in passes.items():
            rank = p["analysed_job_rank_in_matches"]
            print(f"[{scenario.name}] {name}: {p['wall_time_s']}s, {p['groq_calls']} Groq calls, "
                  f"{p['total_tokens']} tokens, {p['rate_limit_429s']} x 429 | job {p['analysed_job_id']} "
                  f"'{p['analysed_job_title']}' (rank {rank if rank else 'not in top matches'}) | "
                  f"{p['supported']}/{p['claims']} supported, {len(p['removed'])} removed")
        for removed in passes["pass_2_from_cache"]["removed"]:
            print(f"    removed: {removed['bullet']}\n    reason:  {removed['reason']}")
        not_cached |= passes["pass_2_from_cache"]["groq_calls"] > 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    if not_cached:
        print("WARNING: pass 2 still called Groq; the demo is not fully cached.")
        sys.exit(1)


if __name__ == "__main__":
    main()
