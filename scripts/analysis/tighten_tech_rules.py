"""Refine tech title keywords and exclusions with word boundaries to achieve >= 85% precision."""

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

# Specific tech title regex patterns with word boundaries
TECH_TITLE_PATTERNS = [
    r"\b(?:software|developer|devops|full[- ]?stack|frontend|front[- ]?end|backend|back[- ]?end)\b",
    r"\b(?:data\s+(?:engineer|scientist|analyst|architect|specialist)|machine\s+learning|ml\b|ai\b|artificial\s+intelligence)\b",
    r"\b(?:python|java|javascript|typescript|react|node\.?js|golang|c\+\+|c#|\.net|rust|scala)\b",
    r"\b(?:cloud|aws|azure|gcp|kubernetes|docker|terraform|sre|site\s+reliability)\b",
    r"\b(?:database\s+administrator|dba|sql\s+developer|data\s+warehouse|etl)\b",
    r"\b(?:cybersecurity|security\s+engineer|infosec|information\s+security|soc\s+analyst)\b",
    r"\b(?:systems?\s+(?:engineer|administrator|admin)|network\s+engineer|infrastructure\s+engineer)\b",
    r"\b(?:qa\s+engineer|sdet|test\s+engineer|quality\s+assurance\s+engineer)\b",
    r"\b(?:bi\s+developer|bi\s+analyst|business\s+intelligence|tableau|power\s+bi)\b",
    r"\b(?:tech(?:nical)?\s+lead|solutions?\s+architect|enterprise\s+architect)\b",
    r"\b(?:technical\s+project\s+manager|technical\s+program\s+manager|scrum\s+master)\b",
    r"\b(?:it\s+support|desktop\s+support|helpdesk|help\s+desk|it\s+specialist|it\s+engineer)\b",
    r"\b(?:mobile\s+developer|ios\s+developer|android\s+developer|web\s+developer)\b",
]

NON_TECH_PATTERNS = [
    r"\b(?:mechanical|civil|electrical|chemical|structural|environmental|biomedical|industrial|manufacturing|process|petroleum|mining|plant|packaging)\s+engineer",
    r"\b(?:sales|account\s+exec|account\s+manager|realtor|real\s+estate|business\s+dev|growth|marketing|merchandis|teller|host|waiter|cashier|retail)\b",
    r"\b(?:financial|credit|claims|billing|audit|accounting|behavior|behavioral|clinical|rehab|medical|nurse|nursing|chaplain|paralegal|legal)\b",
    r"\b(?:data\s*entry|clerk|porter|laborer|driver|operator|dishwasher|food|cook|chef|custodian|janitor|cleaner|security\s+guard|security\s+officer)\b",
]

tech_regex = re.compile("|".join(TECH_TITLE_PATTERNS), re.IGNORECASE)
non_tech_regex = re.compile("|".join(NON_TECH_PATTERNS), re.IGNORECASE)

title_series = df["title"].astype(str)

tech_match = title_series.apply(lambda t: bool(tech_regex.search(t)))
non_tech_match = title_series.apply(lambda t: bool(non_tech_regex.search(t)))

refined_subset = df[tech_match & ~non_tech_match].copy()
print(f"Refined tech subset size: {len(refined_subset)} postings")

sample_50 = refined_subset.sample(n=50, random_state=42)[["job_id", "title", "company_name"]].to_dict(orient="records")

print("\n--- NEW SAMPLE OF 50 FROM REFINED SUBSET ---")
tech_count = 0
for i, item in enumerate(sample_50, 1):
    title = item['title']
    company = item['company_name']
    print(f"{i:2d}. {title} ({company})")
