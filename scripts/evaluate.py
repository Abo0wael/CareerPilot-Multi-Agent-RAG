"""Evaluation for CareerPilot (all numbers are measured, never edited by hand).

1. Retrieval ablation, Precision@10 with a title-family weak label (word-boundary matching):
     sections_bm25        BM25 over section chunks (benefits/about excluded)
     whole_bm25           BM25 over one chunk per whole posting (same query, same pipeline stage)
     sections_exp_or      + LLM expansion, terms OR-ed into one query (original design)
     sections_exp_weighted+ LLM expansion fused as original + w * expansion (fix under test)
     full_pipeline        deployed configuration: expansion (settings) + LLM rerank
2. Faithfulness of real tailoring (top match per profile) as judged by the VerifierAgent.
3. Adversarial verifier test: planted fabrications (skill, metric, employer, certification)
   mixed with verbatim CV bullets; recall on planted claims and specificity on real ones.
4. Tokens, calls, latency and 429 hits per LLM step.

Usage:
    python scripts/evaluate.py                 # everything
    python scripts/evaluate.py --retrieval-only
Outputs: outputs/evaluation/evaluation_results.json and evaluation_report.md
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.api.dependencies import build_workflow  # noqa: E402
from src.application.build_profile import BuildProfileUseCase  # noqa: E402
from src.application.ingest_jobs import IngestJobsUseCase  # noqa: E402
from src.application.match_jobs import MatchJobsUseCase  # noqa: E402
from src.domain.entities import (  # noqa: E402
    CandidateProfile,
    ChunkSection,
    ClaimVerdict,
    JobChunk,
    JobMatch,
    JobPosting,
    SearchQuery,
    TailoredBullet,
)
from src.domain.interfaces import Chunker, QueryExpander, Reranker  # noqa: E402
from src.infrastructure.config import Settings, get_settings  # noqa: E402
from src.infrastructure.data.loader import KaggleDataLoader  # noqa: E402
from src.infrastructure.llm.claim_verifier import GroqClaimVerifier  # noqa: E402
from src.infrastructure.llm.client import GroqClient  # noqa: E402
from src.infrastructure.llm.profile_extractor import GroqProfileExtractor  # noqa: E402
from src.infrastructure.parsing.cv_parser import UniversalCVParser  # noqa: E402
from src.infrastructure.retrieval.expander import GroqQueryExpander  # noqa: E402
from src.infrastructure.retrieval.reranker import GroqReranker  # noqa: E402
from src.infrastructure.search.sqlite_index import SQLiteFTSIndex, SQLiteJobRepository  # noqa: E402

from metering import MeteredLLMClient  # noqa: E402  (scripts/ is on sys.path when run as a script)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("evaluate")
logger.setLevel(logging.INFO)

FIXTURES_DIR = _ROOT / "tests" / "fixtures"
OUTPUT_DIR = _ROOT / "outputs" / "evaluation"
WHOLE_INDEX_PATH = _ROOT / "index" / "whole_postings.db"
K = 10
EXPANSION_WEIGHT_UNDER_TEST = 0.5  # chosen a priori (original terms count double); not tuned on these profiles

FIXTURES = [
    ("sample_cv_backend_engineer.txt", "backend"),
    ("sample_cv_data_analyst.txt", "data_analyst"),
    ("sample_cv_data_scientist.txt", "data_scientist"),
    ("sample_cv_devops_engineer.txt", "devops"),
    ("sample_cv_frontend_entry_level.txt", "frontend"),
    ("sample_cv_software_engineer.txt", "software_engineer"),
]

# ── Weak label: job-title families ───────────────────────────────────
# A title is relevant if it contains a family keyword as a whole word
# (so "ml" does not match "html" and "ai" does not match "maintenance").
FAMILY_KEYWORDS: dict[str, list[str]] = {
    "backend": [
        "backend", "back-end", "back end", "java", "python", "golang", "go", "distributed", "api",
        "microservices", "server", "software engineer", "software developer", "c++", ".net", "c#",
    ],
    "data_analyst": [
        "analyst", "analytics", "business intelligence", "bi", "tableau", "power bi",
        "sql", "reporting", "insights",
    ],
    "data_scientist": [
        "data scientist", "data science", "machine learning", "ml", "ai", "artificial intelligence",
        "nlp", "computer vision", "statistician", "deep learning",
    ],
    "devops": [
        "devops", "cloud", "infrastructure", "sre", "site reliability", "platform",
        "kubernetes", "k8s", "aws", "terraform", "systems administrator", "linux",
    ],
    "frontend": [
        "frontend", "front-end", "front end", "react", "ui", "ux", "web",
        "javascript", "typescript", "angular", "vue", "css", "html",
    ],
    "software_engineer": [
        "software engineer", "software developer", "programmer", "software",
        "full stack", "fullstack", "full-stack", "applications developer", "developer",
    ],
}
# Keywords added AFTER inspecting retrieved titles (clear false negatives of the original list).
# Both label versions are reported so the effect of this change is visible.
ADDED_AFTER_INSPECTION: dict[str, list[str]] = {
    "data_scientist": ["scientist"],  # "Applied Scientist", "Research Scientist"
    "frontend": ["reactjs", "react.js", "user interface"],  # "Sr ReactJs Developer", "User Interface Architect"
}


def _patterns(keywords: list[str]) -> list[re.Pattern]:
    return [re.compile(rf"(?<![a-z0-9]){re.escape(kw)}(?![a-z0-9])") for kw in keywords]


_ORIGINAL_PATTERNS = {family: _patterns(kws) for family, kws in FAMILY_KEYWORDS.items()}
_REVISED_PATTERNS = {
    family: _patterns(kws + ADDED_AFTER_INSPECTION.get(family, [])) for family, kws in FAMILY_KEYWORDS.items()
}


def matches_family(title: str, family: str, revised: bool = True) -> bool:
    patterns = (_REVISED_PATTERNS if revised else _ORIGINAL_PATTERNS)[family]
    return any(p.search(title.lower()) for p in patterns)


def precision_at_k(matches: list[JobMatch], family: str, k: int = K, revised: bool = True) -> float:
    """Relevant titles in the top *k* divided by *k* (missing slots count as non-relevant)."""
    return sum(matches_family(m.job.title, family, revised) for m in matches[:k]) / k


# ── Instrumentation ──────────────────────────────────────────────────

class RecordingExpander(QueryExpander):
    """Delegates to the real expander and remembers the last queries (for the report)."""

    def __init__(self, inner: QueryExpander) -> None:
        self._inner = inner
        self.last_input: Optional[SearchQuery] = None
        self.last_output: Optional[SearchQuery] = None

    def expand(self, query: SearchQuery) -> SearchQuery:
        self.last_input = query
        self.last_output = self._inner.expand(query)
        return self.last_output


class IdentityExpander(QueryExpander):
    def expand(self, query: SearchQuery) -> SearchQuery:
        return query


class NoRerank(Reranker):
    def rerank(self, profile: CandidateProfile, matches: list[JobMatch], top_k: int = 10) -> list[JobMatch]:
        return matches[:top_k]


class WholePostingChunker(Chunker):
    """One chunk per posting containing the entire description (the 'no chunking' baseline)."""

    def chunk(self, posting: JobPosting) -> list[JobChunk]:
        return [
            JobChunk(
                chunk_id=f"{posting.job_id}_whole",
                job_id=posting.job_id,
                section=ChunkSection.FULL,
                text=posting.description,
                title=posting.title,
                company_name=posting.company_name,
                location=posting.location,
                formatted_experience_level=posting.formatted_experience_level,
                formatted_work_type=posting.formatted_work_type,
                remote_allowed=posting.remote_allowed,
                min_salary=posting.min_salary,
                max_salary=posting.max_salary,
            )
        ]


# ── Retrieval ────────────────────────────────────────────────────────

def ensure_whole_posting_index(settings: Settings) -> SQLiteFTSIndex:
    """Build (once) a BM25 index with one chunk per whole posting, same 13,975 postings."""
    index = SQLiteFTSIndex(WHOLE_INDEX_PATH)
    index.initialize()
    if index.get_stats().total_chunks == 0:
        logger.info("Building whole-posting baseline index at %s (zero LLM calls)...", WHOLE_INDEX_PATH)
        IngestJobsUseCase(KaggleDataLoader(settings), WholePostingChunker(), index).execute(clear_existing=True)
    return index


@dataclass
class RetrievalRun:
    matches: list[JobMatch]
    precision: float
    raw_query: str = ""
    expanded_terms: list[str] = field(default_factory=list)


def run_stage(use_case: MatchJobsUseCase, profile: CandidateProfile, family: str,
              recorder: Optional[RecordingExpander] = None) -> RetrievalRun:
    matches = use_case.execute(profile)
    run = RetrievalRun(matches=matches, precision=precision_at_k(matches, family))
    if recorder and recorder.last_output:
        run.raw_query = recorder.last_output.raw_query
        run.expanded_terms = list(recorder.last_output.expanded_terms)
    return run


# ── Adversarial verifier test ────────────────────────────────────────

# Several candidates per type: (phrase appended to a real bullet, markers that must NOT already be in the CV).
# The first candidate whose markers are all absent from the CV is planted.
FABRICATIONS: dict[str, list[tuple[str, list[str]]]] = {
    "fake_skill": [
        ("using Rust and Elixir", ["rust", "elixir"]),
        ("using Haskell and Erlang", ["haskell", "erlang"]),
    ],
    "fake_metric": [
        ("cutting infrastructure costs by 73%", ["73%"]),
        ("improving conversion by 41% for 3 million users", ["41%", "3 million"]),
    ],
    "fake_employer": [
        ("while on contract at Goldman Sachs", ["goldman"]),
        ("while on contract at Netflix", ["netflix"]),
    ],
    "fake_certification": [
        ("and earned the Google Professional Cloud Architect certification", ["google professional", "gcp"]),
        ("and earned the CISSP certification", ["cissp"]),
    ],
}


def cv_bullets(raw_text: str) -> list[str]:
    """Verbatim bullet lines from the CV text (ground truth: supported)."""
    return [line.strip()[2:].strip() for line in raw_text.splitlines() if line.strip().startswith("- ")]


def build_adversarial_set(raw_text: str, rng: random.Random, n_controls: int = 4) -> list[tuple[str, str]]:
    """Return (label, bullet) pairs: 'control' bullets are verbatim, others carry one fabrication."""
    bullets = cv_bullets(raw_text)
    if len(bullets) < n_controls + len(FABRICATIONS):
        raise ValueError("CV has too few bullets for the adversarial set.")
    rng.shuffle(bullets)
    lowered_cv = raw_text.lower()
    items = [("control", b) for b in bullets[:n_controls]]
    for (label, options), base in zip(FABRICATIONS.items(), bullets[n_controls:]):
        phrase = next(p for p, markers in options if not any(m in lowered_cv for m in markers))
        items.append((label, f"{base.rstrip('.')}, {phrase}"))
    rng.shuffle(items)
    return items


def run_adversarial(verifier: GroqClaimVerifier, raw_text: str, rng: random.Random) -> dict[str, Any]:
    items = build_adversarial_set(raw_text, rng)
    report = verifier.verify(raw_text, [TailoredBullet(original="", tailored=b) for _, b in items])
    rows = [
        {"type": label, "bullet": bullet, "verdict": claim.verdict.value, "evidence": claim.evidence}
        for (label, bullet), claim in zip(items, report.claims)
    ]
    return {"rows": rows}


# ── Main ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval-only", action="store_true", help="Skip gap/tailor/verify and adversarial runs.")
    args = parser.parse_args()

    settings = get_settings()
    groq = GroqClient(settings=settings)
    llm = MeteredLLMClient(groq)
    fast = settings.groq_fast_model

    section_index = SQLiteFTSIndex(settings.index_path)
    section_index.initialize()
    whole_index = ensure_whole_posting_index(settings)
    job_repo = SQLiteJobRepository(settings.index_path)
    whole_repo = SQLiteJobRepository(WHOLE_INDEX_PATH)

    recorder = RecordingExpander(GroqQueryExpander(llm, model=fast))
    reranker = GroqReranker(llm, model=fast)
    top_n, top_k = settings.bm25_top_n, settings.rerank_top_k
    stages = {
        "sections_bm25": MatchJobsUseCase(section_index, IdentityExpander(), NoRerank(), job_repo, top_n, top_k),
        "whole_bm25": MatchJobsUseCase(whole_index, IdentityExpander(), NoRerank(), whole_repo, top_n, top_k),
        "sections_exp_or": MatchJobsUseCase(section_index, recorder, NoRerank(), job_repo, top_n, top_k),
        "sections_exp_weighted": MatchJobsUseCase(
            section_index, recorder, NoRerank(), job_repo, top_n, top_k, expansion_weight=EXPANSION_WEIGHT_UNDER_TEST
        ),
        "full_pipeline": MatchJobsUseCase(
            section_index, recorder, reranker, job_repo, top_n, top_k, expansion_weight=settings.expansion_weight
        ),
    }

    profile_use_case = BuildProfileUseCase(
        UniversalCVParser(),
        GroqProfileExtractor(llm, model=settings.model_for(settings.profile_model), max_cv_chars=settings.prompt_max_cv_chars),
    )
    workflow = build_workflow(settings, llm) if not args.retrieval_only else None
    verifier = GroqClaimVerifier(llm, model=settings.model_for(settings.verifier_model), max_cv_chars=settings.prompt_max_cv_chars)
    rng = random.Random(42)

    retrieval: list[dict[str, Any]] = []
    faithfulness: list[dict[str, Any]] = []
    adversarial: list[dict[str, Any]] = []
    evaluated = 0

    for filename, family in FIXTURES:
        path = FIXTURES_DIR / filename
        if not path.exists():
            raise FileNotFoundError(f"Missing evaluation fixture: {path}")
        logger.info("=== %s (%s) ===", filename, family)
        profile = profile_use_case.execute(path.read_bytes(), filename)

        row: dict[str, Any] = {"fixture": filename, "family": family, "profile_skills_used_in_query": profile.skills[:5]}
        for name, use_case in stages.items():
            run = run_stage(use_case, profile, family, recorder if "exp" in name or name == "full_pipeline" else None)
            row[name] = {
                "precision_at_10": round(run.precision, 2),
                "precision_at_10_original_label": round(precision_at_k(run.matches, family, revised=False), 2),
                "top10_titles": [m.job.title for m in run.matches[:K]],
                "top10_relevant": [matches_family(m.job.title, family) for m in run.matches[:K]],
            }
            if run.expanded_terms:
                row["raw_query"] = run.raw_query
                row["expanded_terms"] = run.expanded_terms
            logger.info("  %-22s P@10=%.2f", name, run.precision)
        retrieval.append(row)
        evaluated += 1

        if args.retrieval_only:
            continue

        # Real tailoring on the top match of the deployed pipeline, through the LangGraph workflow.
        full_matches = stages["full_pipeline"].execute(profile)
        if full_matches:
            target = full_matches[0].job
            gap = workflow.analyze_gap(profile, target.job_id)
            tailored = workflow.tailor(profile, target.job_id)
            report = tailored.verification
            faithfulness.append({
                "fixture": filename,
                "job_id": target.job_id,
                "job_title": target.title,
                "gap_matched": len(gap.matched_items),
                "gap_missing": len(gap.missing_items),
                "claims": report.total_count,
                "supported": report.supported_count,
                "unsupported": report.unsupported_count,
                "unverified": report.unverified_count,
                "removed_bullets": [b.tailored for b in tailored.removed_bullets],
            })

        result = run_adversarial(verifier, profile.raw_text, rng)
        adversarial.append({"fixture": filename, **result})

    write_outputs(settings, evaluated, retrieval, faithfulness, adversarial, llm, args.retrieval_only)


# ── Reporting ────────────────────────────────────────────────────────

STAGE_LABELS = {
    "sections_bm25": "BM25 sections",
    "whole_bm25": "BM25 whole posting",
    "sections_exp_or": "+ expansion (OR)",
    "sections_exp_weighted": f"+ expansion (weighted w={EXPANSION_WEIGHT_UNDER_TEST})",
    "full_pipeline": "Full pipeline (deployed expansion + rerank)",
}


def _macro(retrieval: list[dict[str, Any]], stage: str, key: str = "precision_at_10") -> float:
    return round(sum(r[stage][key] for r in retrieval) / len(retrieval), 3) if retrieval else 0.0


def _adversarial_summary(adversarial: list[dict[str, Any]]) -> dict[str, Any]:
    by_type: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for run in adversarial:
        for row in run["rows"]:
            by_type[row["type"]][row["verdict"]] += 1
            by_type[row["type"]]["total"] += 1
    summary: dict[str, Any] = {}
    planted_caught = planted_total = 0
    for label, counts in by_type.items():
        total = counts["total"]
        if label == "control":
            summary["control_specificity"] = {
                "supported": counts[ClaimVerdict.SUPPORTED.value],
                "total": total,
                "rate": round(counts[ClaimVerdict.SUPPORTED.value] / total, 3) if total else None,
                "false_alarms_unsupported": counts[ClaimVerdict.UNSUPPORTED.value],
                "unverified": counts[ClaimVerdict.UNVERIFIED.value],
            }
        else:
            caught = counts[ClaimVerdict.UNSUPPORTED.value]
            planted_caught += caught
            planted_total += total
            summary[label] = {"caught": caught, "total": total, "recall": round(caught / total, 3) if total else None}
    summary["planted_overall"] = {
        "caught": planted_caught,
        "total": planted_total,
        "recall": round(planted_caught / planted_total, 3) if planted_total else None,
    }
    return summary


def write_outputs(settings: Settings, evaluated: int, retrieval: list, faithfulness: list, adversarial: list,
                  llm: MeteredLLMClient, retrieval_only: bool) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total_claims = sum(f["claims"] for f in faithfulness)
    supported = sum(f["supported"] for f in faithfulness)
    results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "fixtures_evaluated": evaluated,
        "config": {
            "fast_model": settings.groq_fast_model,
            "agent_model": settings.groq_agent_model,
            "profile_model": settings.model_for(settings.profile_model),
            "gap_model": settings.model_for(settings.gap_model),
            "tailor_model": settings.model_for(settings.tailor_model),
            "verifier_model": settings.model_for(settings.verifier_model),
            "reasoning_effort": settings.groq_reasoning_effort,
            "deployed_expansion_weight": settings.expansion_weight,
            "bm25_top_n_chunks": settings.bm25_top_n,
        },
        "family_keywords": FAMILY_KEYWORDS,
        "family_keywords_added_after_inspection": ADDED_AFTER_INSPECTION,
        "retrieval": {
            "macro_precision_at_10": {stage: _macro(retrieval, stage) for stage in STAGE_LABELS},
            "macro_precision_at_10_original_label": {
                stage: _macro(retrieval, stage, "precision_at_10_original_label") for stage in STAGE_LABELS
            },
            "per_profile": retrieval,
        },
        "llm_steps": llm.summary(),
    }
    if not retrieval_only:
        results["faithfulness"] = {
            "per_profile": faithfulness,
            "claims": total_claims,
            "supported": supported,
            "unsupported": sum(f["unsupported"] for f in faithfulness),
            "unverified": sum(f["unverified"] for f in faithfulness),
            "supported_rate": round(supported / total_claims, 3) if total_claims else None,
        }
        results["adversarial"] = {"summary": _adversarial_summary(adversarial), "per_profile": adversarial}

    stem = "retrieval_only" if retrieval_only else "evaluation"
    (OUTPUT_DIR / f"{stem}_results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    (OUTPUT_DIR / f"{stem}_report.md").write_text(render_markdown(results), encoding="utf-8")
    logger.info("Wrote %s_results.json and %s_report.md to %s", stem, stem, OUTPUT_DIR)


def _table(header: list[str], rows: list[list[Any]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(c) for c in row) + " |" for row in rows]
    return "\n".join(lines)


def render_markdown(results: dict[str, Any]) -> str:
    """Tables generated from the measured results; no numbers are typed by hand."""
    cfg = results["config"]
    per_profile = results["retrieval"]["per_profile"]
    stages = list(STAGE_LABELS)
    out = [
        "# CareerPilot Evaluation Report",
        f"_Generated by `scripts/evaluate.py` on {results['timestamp']}. Fixtures evaluated: "
        f"{results['fixtures_evaluated']} (synthetic CVs in `tests/fixtures/`)._",
        "",
        f"Models: profile=`{cfg['profile_model']}`, gap=`{cfg['gap_model']}`, tailor=`{cfg['tailor_model']}`, "
        f"verifier=`{cfg['verifier_model']}`, expansion/rerank=`{cfg['fast_model']}`; "
        f"reasoning_effort=`{cfg['reasoning_effort']}`; deployed expansion_weight=`{cfg['deployed_expansion_weight']}`.",
        "",
        "## 1. Retrieval: Precision@10 (weak label = job-title family, whole-word match)",
        "",
        _table(
            ["Profile", *[STAGE_LABELS[s] for s in stages]],
            [[r["family"], *[f"{r[s]['precision_at_10']:.2f}" for s in stages]] for r in per_profile]
            + [["**Macro average**", *[f"**{results['retrieval']['macro_precision_at_10'][s]:.3f}**" for s in stages]]]
            + [["Macro, original label", *[f"{results['retrieval']['macro_precision_at_10_original_label'][s]:.3f}" for s in stages]]],
        ),
        "",
        f"Keywords added after inspecting titles (both label versions shown above): "
        f"`{json.dumps(results['family_keywords_added_after_inspection'])}`.",
        "",
        "### Queries and expansions",
        "",
        _table(
            ["Profile", "BM25 query (preferences + first 5 skills)", "LLM expansion terms"],
            [[r["family"], r.get("raw_query", ""), ", ".join(r.get("expanded_terms", []))] for r in per_profile],
        ),
    ]
    if "faithfulness" in results:
        f = results["faithfulness"]
        out += [
            "",
            "## 2. Faithfulness of real tailoring (judged by the VerifierAgent)",
            "",
            _table(
                ["Profile", "Target job", "Claims", "Supported", "Unsupported (removed)", "Unverified"],
                [[p["fixture"], p["job_title"], p["claims"], p["supported"], p["unsupported"], p["unverified"]]
                 for p in f["per_profile"]]
                + [["**Total**", "", f["claims"], f["supported"], f["unsupported"], f["unverified"]]],
            ),
            "",
            f"Supported rate: **{f['supported_rate']}**. This is an LLM judging an LLM; see section 3 for how "
            "often the judge catches known fabrications.",
            "",
            "## 3. Adversarial verifier test (planted fabrications)",
            "",
        ]
        summary = results["adversarial"]["summary"]
        rows = [[k, v["caught"], v["total"], v["recall"]] for k, v in summary.items() if k.startswith("fake_")]
        rows.append(["**All planted**", summary["planted_overall"]["caught"], summary["planted_overall"]["total"],
                     f"**{summary['planted_overall']['recall']}**"])
        out.append(_table(["Fabrication type", "Caught (unsupported)", "Planted", "Recall"], rows))
        c = summary["control_specificity"]
        out += [
            "",
            f"Verbatim CV bullets (controls) judged supported: {c['supported']}/{c['total']} "
            f"(specificity {c['rate']}); false alarms: {c['false_alarms_unsupported']}; unverified: {c['unverified']}.",
            "",
            "Missed fabrications:",
            "",
        ]
        missed = [
            f"- `{run['fixture']}` [{row['type']}] {row['bullet']} -> {row['verdict']}"
            for run in results["adversarial"]["per_profile"] for row in run["rows"]
            if row["type"] != "control" and row["verdict"] != ClaimVerdict.UNSUPPORTED.value
        ]
        out += missed or ["- none"]
    out += [
        "",
        "## 4. LLM cost and latency per step (this run)",
        "",
        _table(
            ["Step", "Requests", "Groq calls", "Cache hits", "Tokens", "Tokens/call", "Avg live latency (s)", "Max live latency (s)", "429s"],
            [[step, s["requests"], s["groq_calls"], s["cache_hits"], s["total_tokens"], s["tokens_per_groq_call"],
              s["avg_live_latency_s"], s["max_live_latency_s"], s["rate_limit_429s"]] for step, s in results["llm_steps"].items()],
        ),
        "",
        "Latency is measured on requests that reached Groq (cache hits excluded) and includes any "
        "waiting for Groq's rate-limit window (429 -> retry-after). Cached requests cost 0 tokens.",
        "",
    ]
    return "\n".join(out)


if __name__ == "__main__":
    main()
