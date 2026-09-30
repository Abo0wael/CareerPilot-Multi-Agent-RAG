import re
import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.config import get_settings
from src.infrastructure.data.loader import KaggleDataLoader

settings = get_settings()
loader = KaggleDataLoader(settings)

raw_df = loader.load_postings_df()
df = loader.clean_postings(raw_df)
job_skills = loader.load_job_skills()
job_industries = loader.load_job_industries()

title_lower = df["title"].str.lower()
kw_pattern = "|".join(re.escape(kw) for kw in settings.tech_title_keywords)
title_mask = title_lower.str.contains(kw_pattern, na=False, regex=True)

# Exclusions
excl_pattern = "|".join(re.escape(ex) for ex in settings.tech_title_exclusions)
excl_mask = title_lower.str.contains(excl_pattern, na=False, regex=True)

# Rule 1: Title keywords only (minus exclusions)
subset_title_only = df[title_mask & ~excl_mask].copy()
print(f"Rule 1 (Title only - exclusions): {len(subset_title_only)} postings")

# Rule 2: Title keywords OR (Skill tag ENG/IT AND has software/data/cloud/web/app/code in description)
# Let's check a sample of 50 from Rule 1
sample_50 = subset_title_only.sample(n=50, random_state=42)[["job_id", "title", "company_name"]].to_dict(orient="records")

print("\n--- SAMPLE OF 50 FROM RULE 1 (Title-Based) ---")
for i, item in enumerate(sample_50, 1):
    print(f"{i:2d}. {item['title']} ({item['company_name']})")
