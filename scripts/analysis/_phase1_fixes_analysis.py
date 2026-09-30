"""Phase 1 fixes: data analysis tasks.

1. Tech subset precision (50-title sample + exclusion list)
2. Experience level coverage + rule-based fallback
3. Header detection precision (30-sample manual check)
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# UTF-8 logging fix (item 7)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    handlers=[logging.StreamHandler(stream=open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False))],
)
logger = logging.getLogger(__name__)

from src.infrastructure.config import get_settings
from src.infrastructure.data.loader import KaggleDataLoader

# Reuse section patterns from eda_chunking
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

# ── Experience level patterns ─────────────────────────────────────────
TITLE_LEVEL_PATTERNS = [
    (re.compile(r"\b(?:intern|internship|co-?op)\b", re.IGNORECASE), "Internship"),
    (re.compile(r"\b(?:entry[- ]?level|junior|jr\.?|associate|graduate|new\s+grad)\b", re.IGNORECASE), "Entry level"),
    (re.compile(r"\b(?:mid[- ]?level|mid[- ]?senior)\b", re.IGNORECASE), "Mid-Senior level"),
    (re.compile(r"\b(?:senior|sr\.?|staff|principal|lead|architect)\b", re.IGNORECASE), "Mid-Senior level"),
    (re.compile(r"\b(?:director|vp|vice\s+president|head\s+of|chief|c-level|cto|cio)\b", re.IGNORECASE), "Director"),
    (re.compile(r"\b(?:executive|president|managing\s+director)\b", re.IGNORECASE), "Executive"),
]

DESCRIPTION_YEARS_PATTERN = re.compile(
    r"(\d+)\+?\s*(?:[-–]?\s*\d+\s*)?(?:\+\s*)?years?\s+(?:of\s+)?(?:experience|exp\b|work)",
    re.IGNORECASE,
)

def infer_level_from_title(title: str) -> str:
    """Infer experience level from job title using regex patterns."""
    for pattern, level in TITLE_LEVEL_PATTERNS:
        if pattern.search(title):
            return level
    return ""

def infer_level_from_description(desc: str) -> str:
    """Infer experience level from years-of-experience mentions in description."""
    matches = DESCRIPTION_YEARS_PATTERN.findall(desc)
    if not matches:
        return ""
    # Take the first mention
    years = int(matches[0])
    if years <= 1:
        return "Entry level"
    elif years <= 3:
        return "Entry level"
    elif years <= 7:
        return "Mid-Senior level"
    elif years <= 12:
        return "Mid-Senior level"
    else:
        return "Director"

# ── Non-tech exclusion keywords ───────────────────────────────────────
NON_TECH_EXCLUSIONS = [
    "mechanical engineer", "civil engineer", "electrical engineer",
    "chemical engineer", "structural engineer", "environmental engineer",
    "biomedical engineer", "industrial engineer", "manufacturing engineer",
    "process engineer", "petroleum engineer", "mining engineer",
    "sales engineer", "sales representative", "sales manager",
    "sales associate", "account executive", "account manager",
    "data entry", "data entry clerk", "administrative",
    "nurse", "nursing", "registered nurse", "lpn",
    "teacher", "teaching", "instructor",
    "truck driver", "driver", "delivery",
    "custodian", "janitor", "maintenance tech",
    "hvac", "plumber", "electrician",
    "welder", "machinist", "carpenter",
    "dental", "pharmacy", "veterinary",
    "physical therapist", "occupational therapist",
    "real estate", "mortgage", "loan officer",
    "cook", "chef", "restaurant", "barista",
    "retail", "cashier", "store manager",
]


def main() -> None:
    settings = get_settings()
    loader = KaggleDataLoader(settings)

    raw_df = loader.load_postings_df()
    df = loader.clean_postings(raw_df)
    job_skills = loader.load_job_skills()
    job_industries = loader.load_job_industries()
    tech_df = loader.filter_tech_subset(df, job_skills, job_industries)

    # ═══════════════════════════════════════════════════════════════════
    # TASK 1: Tech Subset Precision (50-title sample)
    # ═══════════════════════════════════════════════════════════════════
    print("=" * 80)
    print("  TASK 1: TECH SUBSET PRECISION (50-title random sample)")
    print("=" * 80)

    sample_50 = tech_df.sample(50, random_state=99)
    print("\n--- BEFORE exclusion list ---")
    for i, (_, row) in enumerate(sample_50.iterrows(), 1):
        title = row["title"]
        # Simple heuristic: is this title obviously tech?
        title_lower = title.lower()
        is_tech = any(kw in title_lower for kw in [
            "software", "developer", "engineer", "data", "analyst",
            "devops", "cloud", "python", "java", "react", "node",
            "frontend", "backend", "full stack", "fullstack",
            "machine learning", "ml", "ai", "sre", "security",
            "network", "system", "database", "dba", "it ",
            "technical", "tech", "qa", "test", "scrum",
            "product manager", "web", "mobile", "ios", "android",
            "computer", "information", "cyber", "platform",
        ])
        # Check non-tech exclusion
        is_excluded = any(ex in title_lower for ex in NON_TECH_EXCLUSIONS)
        marker = "TECH" if (is_tech and not is_excluded) else "???"
        print(f"  {i:2d}. [{marker:4s}] {title}")

    # Apply exclusion filter
    exclusion_pattern = "|".join(re.escape(ex) for ex in NON_TECH_EXCLUSIONS)
    excluded_mask = tech_df["title"].str.lower().str.contains(exclusion_pattern, na=False, regex=True)
    excluded_count = excluded_mask.sum()
    tech_df_filtered = tech_df[~excluded_mask].copy()

    print(f"\n  Excluded by non-tech list: {excluded_count:,}")
    print(f"  Tech subset BEFORE exclusion: {len(tech_df):,}")
    print(f"  Tech subset AFTER exclusion:  {len(tech_df_filtered):,}")

    # Re-sample after exclusion
    sample_50_after = tech_df_filtered.sample(50, random_state=99)
    print("\n--- AFTER exclusion list ---")
    tech_count = 0
    for i, (_, row) in enumerate(sample_50_after.iterrows(), 1):
        title = row["title"]
        title_lower = title.lower()
        is_tech = any(kw in title_lower for kw in [
            "software", "developer", "engineer", "data", "analyst",
            "devops", "cloud", "python", "java", "react", "node",
            "frontend", "backend", "full stack", "fullstack",
            "machine learning", "ml", "ai", "sre", "security",
            "network", "system", "database", "dba", "it ",
            "technical", "tech", "qa", "test", "scrum",
            "product manager", "web", "mobile", "ios", "android",
            "computer", "information", "cyber", "platform",
        ])
        is_excluded = any(ex in title_lower for ex in NON_TECH_EXCLUSIONS)
        is_valid = is_tech and not is_excluded
        if is_valid:
            tech_count += 1
        marker = "TECH" if is_valid else "???"
        print(f"  {i:2d}. [{marker:4s}] {title}")
    print(f"\n  Precision after exclusion: {tech_count}/50 = {100*tech_count/50:.0f}%")

    # ═══════════════════════════════════════════════════════════════════
    # TASK 2: Experience Level Coverage + Fallback
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  TASK 2: EXPERIENCE LEVEL COVERAGE")
    print("=" * 80)

    # Original coverage
    has_level = tech_df["formatted_experience_level"].astype(str).str.strip().ne("")
    orig_coverage = has_level.sum()
    orig_pct = 100 * orig_coverage / len(tech_df)
    print(f"\n  Original formatted_experience_level:")
    print(f"    Present: {orig_coverage:,} / {len(tech_df):,} ({orig_pct:.1f}%)")
    print(f"    Missing: {len(tech_df) - orig_coverage:,} ({100 - orig_pct:.1f}%)")

    # Value distribution
    print(f"\n  Level distribution (original):")
    level_counts = tech_df["formatted_experience_level"].value_counts(dropna=False)
    for level, count in level_counts.items():
        print(f"    {str(level):25s}: {count:>6,} ({100*count/len(tech_df):5.1f}%)")

    # Apply rule-based fallback
    inferred_title = tech_df["title"].apply(infer_level_from_title)
    inferred_desc = tech_df["description"].apply(infer_level_from_description)

    # Combine: original > title > description
    combined = tech_df["formatted_experience_level"].astype(str).str.strip()
    filled_from_title = 0
    filled_from_desc = 0
    for idx in combined.index:
        if combined[idx] == "" or combined[idx] == "nan":
            if inferred_title[idx]:
                combined[idx] = inferred_title[idx]
                filled_from_title += 1
            elif inferred_desc[idx]:
                combined[idx] = inferred_desc[idx]
                filled_from_desc += 1

    after_coverage = combined.ne("").sum() - combined.eq("nan").sum()
    after_pct = 100 * after_coverage / len(tech_df)

    print(f"\n  After rule-based fallback:")
    print(f"    Filled from title patterns:       {filled_from_title:,}")
    print(f"    Filled from description patterns:  {filled_from_desc:,}")
    print(f"    Total coverage: {after_coverage:,} / {len(tech_df):,} ({after_pct:.1f}%)")
    print(f"    Improvement: +{after_pct - orig_pct:.1f} percentage points")

    # ═══════════════════════════════════════════════════════════════════
    # TASK 3: Header Detection Precision (30 samples)
    # ═══════════════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print("  TASK 3: HEADER DETECTION PRECISION (30 samples)")
    print("=" * 80)

    # Get postings that have at least one detected header
    has_header = tech_df["description"].apply(
        lambda d: any(p.search(d) for p in SECTION_PATTERNS.values())
    )
    with_headers = tech_df[has_header]
    header_sample = with_headers.sample(30, random_state=77)

    correct = 0
    total_detections = 0
    for i, (_, row) in enumerate(header_sample.iterrows(), 1):
        desc = row["description"]
        detected = {}
        for name, pattern in SECTION_PATTERNS.items():
            match = pattern.search(desc)
            if match:
                # Get context around the match
                start = max(0, match.start() - 20)
                end = min(len(desc), match.end() + 60)
                context = desc[start:end].replace("\n", " | ")
                detected[name] = context

        total_detections += len(detected)
        # Check if the detection looks correct by examining context
        all_correct = True
        for name, context in detected.items():
            # A header detection is correct if it's at the start of a line
            # and followed by content (not embedded in a sentence)
            pass  # We print for manual inspection

        print(f"\n  [{i:2d}] Title: {row['title'][:60]}")
        for name, context in detected.items():
            print(f"       {name:20s} -> ...{context}...")
            correct += 1  # Count for now, we verify by inspection

    print(f"\n  Total detections across 30 postings: {total_detections}")
    print(f"  (Manual inspection of context above needed to confirm precision)")


if __name__ == "__main__":
    main()
