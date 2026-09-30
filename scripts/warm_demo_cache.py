"""Pre-run the demo CV through the full multi-agent pipeline to fill the LLM cache.

Uses exactly the API wiring (``build_workflow``), so the cached prompts are the
ones /profile, /match, /gap, /tailor and /pipeline will send for this CV. A live
demo with the same CV and preferences then makes zero Groq calls, so it cannot hit
Groq's 8,000 tokens/minute limit.

It runs the pipeline twice and reports tokens, latency and 429s per step:
pass 1 fills the cache (live Groq calls unless already cached), pass 2 must be all cache hits.

Usage:
    python scripts/warm_demo_cache.py [--cv tests/fixtures/sample_cv_backend_engineer.txt] [--preferences "remote"]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from metering import MeteredLLMClient  # noqa: E402

from src.api.dependencies import build_workflow  # noqa: E402
from src.infrastructure.config import get_settings  # noqa: E402
from src.infrastructure.llm.client import GroqClient  # noqa: E402

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

DEFAULT_CV = _ROOT / "tests" / "fixtures" / "sample_cv_backend_engineer.txt"
OUTPUT = _ROOT / "outputs" / "evaluation" / "demo_warmup.json"


def run_pass(cv: Path, preferences: str) -> dict:
    settings = get_settings()
    llm = MeteredLLMClient(GroqClient(settings=settings))
    workflow = build_workflow(settings, llm)
    t0 = time.perf_counter()
    result = workflow.run_pipeline(file_bytes=cv.read_bytes(), filename=cv.name, preferences=preferences)
    elapsed = time.perf_counter() - t0
    steps = llm.summary()
    report = result.tailored_cv.verification if result.tailored_cv else None
    return {
        "wall_time_s": round(elapsed, 2),
        "groq_calls": sum(s["groq_calls"] for s in steps.values()),
        "total_tokens": sum(s["total_tokens"] for s in steps.values()),
        "rate_limit_429s": sum(s["rate_limit_429s"] for s in steps.values()),
        "top_match": result.matches[0].job.title if result.matches else None,
        "claims": report.total_count if report else 0,
        "unsupported_removed": report.unsupported_count if report else 0,
        "steps": steps,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cv", type=Path, default=DEFAULT_CV)
    parser.add_argument("--preferences", default="")
    args = parser.parse_args()

    passes = {"pass_1_fill_cache": run_pass(args.cv, args.preferences), "pass_2_from_cache": run_pass(args.cv, args.preferences)}
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps({"cv": args.cv.name, "preferences": args.preferences, **passes}, indent=2), encoding="utf-8"
    )
    for name, p in passes.items():
        print(f"{name}: {p['wall_time_s']}s, {p['groq_calls']} Groq calls, {p['total_tokens']} tokens, "
              f"{p['rate_limit_429s']} x 429, top match: {p['top_match']}")
        for step, s in p["steps"].items():
            print(f"    {step:20s} calls={s['groq_calls']} cache_hits={s['cache_hits']} tokens={s['total_tokens']} "
                  f"avg_live_latency={s['avg_live_latency_s']}s 429s={s['rate_limit_429s']}")
    if passes["pass_2_from_cache"]["groq_calls"]:
        print("WARNING: pass 2 still called Groq; the demo is not fully cached.")
        sys.exit(1)


if __name__ == "__main__":
    main()
