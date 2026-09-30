"""Tune tech filtering rule to get ~18-20K postings with >= 85% precision."""

from __future__ import annotations
import re
import sys
from pathlib import Path
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.data.loader import KaggleDataLoader
from src.infrastructure.config import get_settings

settings = get_settings()
loader = KaggleDataLoader(settings)

raw_df = loader.load_postings_df()
df = loader.clean_postings(raw_df)

# Specific tech title keywords (multi-word or qualified to prevent false positives)
TECH_TITLE_KEYWORDS = [
    "software", "developer", "devops", "cloud",
    "backend", "frontend", "full stack", "fullstack", "full-stack",
    "python", "java", "javascript", "typescript", "react", "node",
    "golang", "rust", "c++", "c#", ".net", "ios", "android",
    "mobile developer", "mobile engineer", "mobile app",
    "web developer", "web engineer", "sre", "site reliability",
    "infrastructure engineer", "database", "dba", "sql developer", "sql engineer",
    "data engineer", "data scientist", "data analyst", "data architect",
    "machine learning", "ml engineer", "ai engineer", "deep learning", "nlp", "computer vision",
    "cybersecurity", "security engineer", "network engineer", "systems engineer",
    "systems administrator", "sysadmin", "system admin",
    "qa engineer", "sdet", "test engineer", "automation engineer",
    "quality assurance engineer", "scrum master",
    "tech lead", "technical lead", "technical project manager", "technical program manager",
    "solutions architect", "enterprise architect", "cloud architect", "software architect",
    "it support", "desktop support", "helpdesk", "help desk", "it specialist", "it engineer"
]

NON_TECH_EXCLUSIONS = [
    # Non-software engineering disciplines (including inverted names like "Engineer, Structural")
    r"mechanical", r"civil", r"electrical", r"chemical", r"structural", r"environmental",
    r"biomedical", r"industrial", r"manufacturing", r"process", r"petroleum", r"mining",
    r"plant\s+engineer", r"packaging\s+engineer", r"flight\s+engineer", r"water\s+resources",
    r"sanitation", r"mechanic", r"maintenance\s+technician", r"field\s+service\s+technician",
    # Sales, business dev, marketing
    r"sales", r"account\s+exec", r"account\s+manager", r"realtor", r"real\s+estate",
    r"business\s+development", r"merchandis", r"retail", r"store\s+manager", r"cashier",
    # Medical, healthcare, lab, food
    r"nurse", r"nursing", r"\brn\b", r"clinical", r"medical", r"hospital", r"chaplain",
    r"therapist", r"dental", r"pharmacy", r"phlebotom", r"radiolog", r"allied", r"sushi",
    r"food", r"cook", r"chef", r"restaurant",
    # Finance, legal, admin
    r"teller", r"claims", r"billing", r"credit", r"underwriter", r"paralegal", r"attorney",
    r"legal\s+assistant", r"administrative\s+assistant", r"admin\s+assistant", r"office\s+manager",
    # Manual labor, transport
    r"driver", r"truck", r"bus\s+driver", r"porter", r"custodian", r"janitor", r"laborer",
    r"warehouse", r"forklift", r"data\s*entry", r"clerk", r"receptionist", r"security\s+guard",
    r"security\s+officer", r"behavior\s+analyst", r"behavioral", r"sand\s+management"
]

kw_pattern = "|".join(r"\b" + re.escape(kw) + r"\b" if len(kw) <= 4 else re.escape(kw) for kw in TECH_TITLE_KEYWORDS)
excl_pattern = "|".join(NON_TECH_EXCLUSIONS)

title_lower = df["title"].str.lower()
title_match = title_lower.str.contains(kw_pattern, na=False, regex=True)
excl_match = title_lower.str.contains(excl_pattern, na=False, regex=True)

final_subset = df[title_match & ~excl_match].copy()
print(f"Refined subset size: {len(final_subset)} postings")

sample_50 = final_subset.sample(n=50, random_state=42)[["job_id", "title", "company_name"]].to_dict(orient="records")

print("\n--- NEW SAMPLE OF 50 FROM REFINED SUBSET ---")
for i, item in enumerate(sample_50, 1):
    print(f"{i:2d}. {item['title']} ({item['company_name']})")
