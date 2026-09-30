"""Analyze tech subset precision and test tightened filtering rules."""

from __future__ import annotations

import logging
import random
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

print(f"Total cleaned postings: {len(df)}")

# Evaluate current rule
subset_current = loader.filter_tech_subset(df, job_skills, job_industries)
print(f"Current subset size: {len(subset_current)}")

# Sample 50 with seed 42 for reproducibility
random.seed(42)
sample_50 = subset_current.sample(n=50, random_state=42)[["job_id", "title", "company_name"]].to_dict(orient="records")
print("\n--- SAMPLE OF 50 FROM CURRENT SUBSET ---")
for i, item in enumerate(sample_50, 1):
    print(f"{i:2d}. {item['title']} ({item['company_name']})")
