"""Kaggle CSV loader, cleaning, and tech-subset filter.

Reads ``postings.csv`` and related files, normalises text, and
filters to a configurable tech subset.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

import pandas as pd

from src.domain.entities import JobPosting
from src.domain.exceptions import CareerPilotError
from src.domain.interfaces import JobSource
from src.infrastructure.config import Settings

logger = logging.getLogger(__name__)


def _normalise_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs but preserve line breaks."""
    # Replace \r\n with \n, then collapse horizontal whitespace
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Collapse multiple spaces/tabs (not newlines) into single space
    text = re.sub(r"[^\S\n]+", " ", text)
    # Collapse 3+ consecutive newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class KaggleDataLoader(JobSource):
    """Loads and cleans LinkedIn job postings from the Kaggle dataset.

    Single Responsibility: reading CSVs, cleaning, and filtering.
    """

    def __init__(self, settings: Settings) -> None:
        self._data_dir = settings.data_raw_dir
        self._title_keywords = [kw.lower() for kw in settings.tech_title_keywords]
        self._skill_abbreviations = set(settings.tech_skill_abbreviations)
        self._tech_industry_ids = set(settings.tech_industry_ids)
        self._title_exclusions = [ex.lower() for ex in settings.tech_title_exclusions]
        self._exp_level_patterns = settings.experience_level_title_patterns

    # ── Public API ───────────────────────────────────────────────────

    def load_postings(self) -> list[JobPosting]:
        """Run the full load -> clean -> tech filter -> enrich pipeline (``JobSource``)."""
        df = self.clean_postings(self.load_postings_df())
        tech_df = self.filter_tech_subset(df, self.load_job_skills(), self.load_job_industries())
        tech_df = self.enrich_experience_level(tech_df)
        logger.info("Tech subset: %d postings.", len(tech_df))
        return self.to_job_postings(tech_df)

    def load_postings_df(self) -> pd.DataFrame:
        """Load the raw postings CSV into a DataFrame.

        Returns:
            DataFrame with original columns, NaN-safe.
        """
        path = self._data_dir / "postings.csv"
        logger.info("Loading postings from %s", path)
        df = pd.read_csv(path, low_memory=False)
        logger.info("Loaded %d raw postings.", len(df))
        return df

    def load_job_skills(self) -> pd.DataFrame:
        """Load the job_skills mapping (job_id -> skill_abr)."""
        path = self._data_dir / "jobs" / "job_skills.csv"
        return pd.read_csv(path)

    def load_job_industries(self) -> pd.DataFrame:
        """Load the job_industries mapping (job_id -> industry_id)."""
        path = self._data_dir / "jobs" / "job_industries.csv"
        return pd.read_csv(path)

    def load_skills_mapping(self) -> pd.DataFrame:
        """Load skill abbreviation -> name mapping."""
        path = self._data_dir / "mappings" / "skills.csv"
        return pd.read_csv(path)

    def load_industries_mapping(self) -> pd.DataFrame:
        """Load industry_id -> name mapping."""
        path = self._data_dir / "mappings" / "industries.csv"
        return pd.read_csv(path)

    def clean_postings(self, df: pd.DataFrame) -> pd.DataFrame:
        """Clean the raw postings DataFrame.

        - Drop rows with missing title or description.
        - Normalise whitespace in text fields.
        - Fill NaN in categorical columns with empty strings.
        """
        before = len(df)
        df = df.dropna(subset=["title", "description"]).copy()
        logger.info(
            "Dropped %d postings with missing title/description.", before - len(df)
        )

        # Normalise text
        df["title"] = df["title"].astype(str).apply(str.strip)
        df["description"] = df["description"].astype(str).apply(_normalise_whitespace)
        df["company_name"] = df["company_name"].fillna("").astype(str).apply(str.strip)
        df["location"] = df["location"].fillna("").astype(str).apply(str.strip)
        df["skills_desc"] = df["skills_desc"].fillna("").astype(str)

        # Categorical fills
        df["formatted_work_type"] = df["formatted_work_type"].fillna("")
        df["formatted_experience_level"] = df["formatted_experience_level"].fillna("")
        df["remote_allowed"] = df["remote_allowed"].fillna(0).astype(int)
        df["currency"] = df["currency"].fillna("")

        return df

    def filter_tech_subset(
        self,
        df: pd.DataFrame,
        job_skills: Optional[pd.DataFrame] = None,
        job_industries: Optional[pd.DataFrame] = None,
    ) -> pd.DataFrame:
        """Filter to a tech-relevant subset using a refined, high-precision rule:

        1. **Title match:** Title contains high-precision tech keywords (word-boundary aware).
        2. **Skill match:** Job has ENG or IT skill tags AND a tech-qualifying title.
        (Note: Industry alone is deliberately excluded to prevent non-tech roles at
        tech companies like janitors, sales, or food service from being included).

        A posting qualifies if condition 1 or 2 is met, and no non-tech exclusion applies.
        """
        title_lower = df["title"].str.lower()

        # 1. Title keyword match (word-boundary safe for short terms)
        pattern = "|".join(
            r"\b" + re.escape(kw) + r"\b" if len(kw) <= 4 else re.escape(kw)
            for kw in self._title_keywords
        )
        title_mask = title_lower.str.contains(pattern, na=False, regex=True)
        logger.info("Title-keyword matches: %d", title_mask.sum())

        # 2. Skill match: ENG or IT, qualified by tech context
        skill_mask = pd.Series(False, index=df.index)
        if job_skills is not None and not job_skills.empty:
            tech_skill_jobs = set(
                job_skills[
                    job_skills["skill_abr"].isin(self._skill_abbreviations)
                ]["job_id"]
            )
            tech_qualifier = title_lower.str.contains(
                r"\b(?:engineer|developer|architect|programmer|data|software|cloud|system|network|web)\b",
                regex=True, na=False,
            )
            skill_mask = df["job_id"].isin(tech_skill_jobs) & tech_qualifier
            logger.info("Skill-tag matches (tech qualified): %d", skill_mask.sum())

        combined = title_mask | skill_mask
        subset = df[combined].copy()
        logger.info(
            "Tech subset (before exclusions): %d / %d postings (%.1f%%).",
            len(subset), len(df), 100 * len(subset) / len(df),
        )

        # 3. Apply exclusion list
        if self._title_exclusions:
            excl_pattern = "|".join(self._title_exclusions)
            excl_mask = subset["title"].str.lower().str.contains(
                excl_pattern, na=False, regex=True
            )
            excluded_count = excl_mask.sum()
            subset = subset[~excl_mask].copy()
            logger.info(
                "Excluded %d postings by title exclusion list. Final: %d.",
                excluded_count, len(subset),
            )

        return subset

    def enrich_experience_level(self, df: pd.DataFrame) -> pd.DataFrame:
        """Fill missing ``formatted_experience_level`` using rule-based fallback.

        Priority: original value > title patterns > description years-of-experience.
        No LLM calls -- pure regex.
        """
        df = df.copy()
        col = "formatted_experience_level"
        missing_before = (df[col].astype(str).str.strip().isin(["", "nan"])).sum()

        years_pattern = re.compile(
            r"(\d+)\+?\s*(?:[-\u2013]?\s*\d+\s*)?(?:\+\s*)?years?\s+(?:of\s+)?(?:experience|exp\b|work)",
            re.IGNORECASE,
        )

        filled_title = 0
        filled_desc = 0

        for idx, row in df.iterrows():
            current = str(row[col]).strip()
            if current and current != "nan":
                continue

            # Try title
            title_lower = str(row["title"]).lower()
            inferred = ""
            for level, keywords in self._exp_level_patterns.items():
                if any(kw in title_lower for kw in keywords):
                    inferred = level
                    break

            if inferred:
                df.at[idx, col] = inferred
                filled_title += 1
                continue

            # Try description years
            matches = years_pattern.findall(str(row["description"]))
            if matches:
                years = int(matches[0])
                if years <= 3:
                    inferred = "Entry level"
                elif years <= 7:
                    inferred = "Mid-Senior level"
                else:
                    inferred = "Director"
                df.at[idx, col] = inferred
                filled_desc += 1

        missing_after = (df[col].astype(str).str.strip().isin(["", "nan"])).sum()
        logger.info(
            "Experience level fallback: filled %d from title, %d from description. "
            "Missing: %d -> %d (%.1f%% -> %.1f%% coverage).",
            filled_title, filled_desc,
            missing_before, missing_after,
            100 * (1 - missing_before / len(df)),
            100 * (1 - missing_after / len(df)),
        )
        return df

    def to_job_postings(self, df: pd.DataFrame) -> list[JobPosting]:
        """Convert a cleaned DataFrame into a list of ``JobPosting`` entities."""
        postings: list[JobPosting] = []
        skipped = 0
        for _, row in df.iterrows():
            try:
                posting = JobPosting(
                    job_id=int(row["job_id"]),
                    title=str(row["title"]),
                    company_name=str(row.get("company_name", "")),
                    description=str(row["description"]),
                    location=str(row.get("location", "")),
                    formatted_work_type=str(row.get("formatted_work_type", "")),
                    formatted_experience_level=str(
                        row.get("formatted_experience_level", "")
                    ),
                    remote_allowed=bool(row.get("remote_allowed", 0)),
                    min_salary=row.get("min_salary") if pd.notna(row.get("min_salary")) else None,
                    max_salary=row.get("max_salary") if pd.notna(row.get("max_salary")) else None,
                    currency=str(row.get("currency", "")),
                )
                postings.append(posting)
            except (CareerPilotError, ValueError, TypeError):
                skipped += 1

        if skipped:
            logger.warning("Skipped %d rows due to validation errors.", skipped)
        logger.info("Converted %d postings to domain entities.", len(postings))
        return postings
