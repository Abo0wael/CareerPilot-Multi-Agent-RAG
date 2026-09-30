"""EDA & chunking analysis for CareerPilot.

Produces statistics and figures that drive the chunking strategy decision:
  1. Description length distribution
  2. Percentage of postings with line breaks (potential section structure)
  3. Section-header coverage (how often common headers appear)
  4. Three raw description samples

Outputs are saved to ``outputs/figures/``.

Usage:
    python scripts/eda_chunking.py
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")            # non-interactive backend for Windows
import matplotlib.pyplot as plt
import pandas as pd

# ── Setup paths ──────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.config import get_settings
from src.infrastructure.data.loader import KaggleDataLoader
from src.infrastructure.search.fts5_check import verify_fts5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)

FIGURES_DIR = PROJECT_ROOT / "outputs" / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)

# ── Section-header patterns ──────────────────────────────────────────
# Case-insensitive regex patterns for common job-posting sections
SECTION_PATTERNS: dict[str, re.Pattern] = {
    "responsibilities": re.compile(
        r"(?:^|\n)\s*(?:#+\s*)?(?:key\s+)?(?:roles?\s*(?:and|&)\s*)?responsibilities\b",
        re.IGNORECASE,
    ),
    "requirements": re.compile(
        r"(?:^|\n)\s*(?:#+\s*)?(?:minimum\s+|basic\s+|required\s+)?(?:requirements?|qualifications?)\b",
        re.IGNORECASE,
    ),
    "nice_to_have": re.compile(
        r"(?:^|\n)\s*(?:#+\s*)?(?:nice\s*to\s*have|preferred|bonus|desired|plus)\b",
        re.IGNORECASE,
    ),
    "benefits": re.compile(
        r"(?:^|\n)\s*(?:#+\s*)?(?:benefits?|perks?|compensation|what\s+we\s+offer)\b",
        re.IGNORECASE,
    ),
    "about": re.compile(
        r"(?:^|\n)\s*(?:#+\s*)?(?:about\s+(?:us|the\s+company|the\s+role)|company\s+(?:overview|description)|who\s+we\s+are)\b",
        re.IGNORECASE,
    ),
}


def main() -> None:
    """Run EDA analysis and save outputs."""
    # ── 0. Pre-checks ────────────────────────────────────────────────
    verify_fts5()
    logger.info("FTS5 is available ✓")

    settings = get_settings()
    loader = KaggleDataLoader(settings)

    # ── 1. Load and clean ────────────────────────────────────────────
    raw_df = loader.load_postings_df()
    df = loader.clean_postings(raw_df)

    # ── 2. Tech subset ───────────────────────────────────────────────
    job_skills = loader.load_job_skills()
    job_industries = loader.load_job_industries()
    tech_df = loader.filter_tech_subset(df, job_skills, job_industries)

    print(f"\n{'='*70}")
    print(f"  TOTAL POSTINGS (after cleaning):  {len(df):,}")
    print(f"  TECH SUBSET:                      {len(tech_df):,}")
    print(f"{'='*70}\n")

    # ── 3. Description length distribution ───────────────────────────
    desc_lengths = tech_df["description"].str.len()
    stats = desc_lengths.describe(percentiles=[0.1, 0.25, 0.5, 0.75, 0.9, 0.95])
    print("Description length statistics (characters):")
    print(stats.to_string())
    print()

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.hist(desc_lengths.clip(upper=10000), bins=80, color="#4A90D9", edgecolor="white")
    ax.set_xlabel("Description Length (chars)")
    ax.set_ylabel("Count")
    ax.set_title("Distribution of Job Description Lengths (Tech Subset)")
    ax.axvline(desc_lengths.median(), color="red", linestyle="--", label=f"Median: {int(desc_lengths.median())}")
    ax.axvline(desc_lengths.mean(), color="orange", linestyle="--", label=f"Mean: {int(desc_lengths.mean())}")
    ax.legend()
    fig.tight_layout()
    fig.savefig(FIGURES_DIR / "description_length_distribution.png", dpi=150)
    plt.close(fig)
    logger.info("Saved description_length_distribution.png")

    # ── 4. Line-break analysis ───────────────────────────────────────
    has_linebreaks = tech_df["description"].str.contains("\n", na=False)
    pct_linebreaks = 100 * has_linebreaks.sum() / len(tech_df)
    newline_counts = tech_df["description"].str.count("\n")

    print(f"Postings with >=1 line break: {has_linebreaks.sum():,} / {len(tech_df):,} ({pct_linebreaks:.1f}%)")
    print(f"  Median newlines per posting: {newline_counts.median():.0f}")
    print(f"  Mean newlines per posting:   {newline_counts.mean():.1f}")
    print()

    # ── 5. Section-header coverage ───────────────────────────────────
    print("Section-header coverage (tech subset):")
    section_counts: dict[str, int] = {}
    for name, pattern in SECTION_PATTERNS.items():
        matches = tech_df["description"].apply(lambda d: bool(pattern.search(d)))
        count = matches.sum()
        pct = 100 * count / len(tech_df)
        section_counts[name] = count
        print(f"  {name:20s}: {count:>6,} ({pct:5.1f}%)")

    # At least one section header
    any_section = tech_df["description"].apply(
        lambda d: any(p.search(d) for p in SECTION_PATTERNS.values())
    )
    pct_any = 100 * any_section.sum() / len(tech_df)
    print(f"  {'ANY HEADER':20s}: {any_section.sum():>6,} ({pct_any:5.1f}%)")
    print()

    # Multiple sections
    section_count_per_posting = tech_df["description"].apply(
        lambda d: sum(1 for p in SECTION_PATTERNS.values() if p.search(d))
    )
    multi_section = (section_count_per_posting >= 2).sum()
    pct_multi = 100 * multi_section / len(tech_df)
    print(f"  Postings with >=2 detected sections: {multi_section:,} ({pct_multi:.1f}%)")
    print()

    # Bar chart of section coverage
    fig2, ax2 = plt.subplots(figsize=(8, 4))
    names = list(section_counts.keys()) + ["any_header"]
    counts = list(section_counts.values()) + [any_section.sum()]
    pcts = [100 * c / len(tech_df) for c in counts]
    bars = ax2.barh(names, pcts, color="#4A90D9", edgecolor="white")
    ax2.set_xlabel("% of Tech Postings")
    ax2.set_title("Section-Header Detection Coverage")
    for bar, pct_val in zip(bars, pcts):
        ax2.text(bar.get_width() + 0.5, bar.get_y() + bar.get_height() / 2,
                 f"{pct_val:.1f}%", va="center", fontsize=9)
    fig2.tight_layout()
    fig2.savefig(FIGURES_DIR / "section_header_coverage.png", dpi=150)
    plt.close(fig2)
    logger.info("Saved section_header_coverage.png")

    # ── 6. Three raw samples ─────────────────────────────────────────
    print("=" * 70)
    print("  THREE RAW DESCRIPTION SAMPLES")
    print("=" * 70)
    samples = tech_df.sample(3, random_state=42)
    for idx, (_, row) in enumerate(samples.iterrows(), 1):
        desc = row["description"]
        print(f"\n--- Sample {idx} ---")
        print(f"Title: {row['title']}")
        print(f"Company: {row['company_name']}")
        print(f"Length: {len(desc)} chars, {desc.count(chr(10))} newlines")
        # Detect which sections match
        found = [name for name, p in SECTION_PATTERNS.items() if p.search(desc)]
        print(f"Detected sections: {found if found else 'NONE'}")
        print(f"Description (first 1000 chars):\n{desc[:1000]}")
        print()

    # ── 7. Summary / recommendation ──────────────────────────────────
    print("=" * 70)
    print("  CHUNKING DECISION SUMMARY")
    print("=" * 70)
    print(f"""
  Tech subset size: {len(tech_df):,}
  Median description length: {int(desc_lengths.median())} chars
  Mean description length:   {int(desc_lengths.mean())} chars
  Postings with line breaks: {pct_linebreaks:.1f}%
  Postings with >=1 section header: {pct_any:.1f}%
  Postings with >=2 section headers: {pct_multi:.1f}%

  RECOMMENDATION:
  - Use SectionChunker for postings with detectable headers ({pct_any:.1f}%).
  - Use ParagraphChunker as fallback for the rest ({100 - pct_any:.1f}%).
  - Parent-document retrieval: search chunks -> aggregate by job_id -> return full postings.
""")

    logger.info("EDA complete. Figures saved to %s", FIGURES_DIR)


if __name__ == "__main__":
    main()
