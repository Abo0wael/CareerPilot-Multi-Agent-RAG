"""Centralised application configuration.

All tunables live here -- no magic numbers elsewhere in the codebase.
Values are loaded from environment variables / ``.env`` via pydantic-settings.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Application-wide settings loaded from environment / .env file."""

    # ── Groq API ─────────────────────────────────────────────────────
    groq_api_key: str = Field(
        ..., description="Groq API key (required)."
    )
    groq_fast_model: str = Field(
        default="openai/gpt-oss-20b",
        description="Fast Groq model for query expansion and reranking.",
    )
    groq_agent_model: str = Field(
        default="openai/gpt-oss-120b",
        description="Strong Groq model for agent reasoning tasks.",
    )

    groq_reasoning_effort: str = Field(
        default="low",
        description="reasoning_effort for gpt-oss models (none/low/medium/high; '' = provider default).",
    )

    # Model per reasoning step: "fast", "agent", or an explicit Groq model id.
    # Each Groq model has its own 8,000 tokens/minute limit, so steps are split
    # across both models; the verifier (the safety net) stays on the strong model.
    profile_model: str = Field(default="fast", description="Model for CV profile extraction.")
    gap_model: str = Field(default="agent", description="Model for gap analysis.")
    tailor_model: str = Field(default="agent", description="Model for CV tailoring (fast model measured worse: 80-84% vs 96% supported claims).")
    verifier_model: str = Field(default="agent", description="Model for claim verification.")

    # Prompt size caps (characters) to stay under Groq tokens-per-minute limits.
    prompt_max_cv_chars: int = Field(default=12000, description="Max CV characters sent to the LLM.")
    prompt_max_job_chars_gap: int = Field(default=4000, description="Max job-posting characters for gap analysis.")
    prompt_max_job_chars_tailor: int = Field(default=2500, description="Max job-posting characters for tailoring.")
    tailor_max_bullets: int = Field(default=10, description="Max CV bullets rewritten per tailoring call.")

    # ── Admin ────────────────────────────────────────────────────────
    admin_token: str = Field(
        default="",
        description="Token required in the X-Admin-Token header for /ingest. Empty disables /ingest.",
    )

    # ── Data paths ───────────────────────────────────────────────────
    data_raw_dir: Path = Field(
        default=_PROJECT_ROOT / "data",
        description="Root directory containing raw Kaggle CSV files.",
    )
    index_path: Path = Field(
        default=_PROJECT_ROOT / "index" / "careerpilot.db",
        description="Path to the SQLite FTS5 index file.",
    )

    # ── Tech-subset filter ───────────────────────────────────────────
    tech_title_keywords: list[str] = Field(
        default=[
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
        ],
        description="High-precision keywords matched against job title to build tech subset.",
    )
    tech_skill_abbreviations: list[str] = Field(
        default=["ENG", "IT"],
        description="Skill abbreviations from the dataset that indicate tech roles.",
    )
    tech_industry_ids: list[int] = Field(
        default=[
            3, 4, 5, 6, 7, 8, 84, 109, 115, 118,
            1285, 1594, 2458,
            3101, 3102, 3103, 3105, 3106, 3124,
            3127, 3130, 3132, 3134, 3218, 3231, 3234, 3235,
        ],
        description="Industry IDs from the dataset that indicate tech companies.",
    )
    tech_title_exclusions: list[str] = Field(
        default=[
            # Non-software engineering disciplines
            "mechanical", "civil", "electrical", "chemical", "structural", "environmental",
            "biomedical", "industrial", "manufacturing", "process", "petroleum", "mining",
            "plant engineer", "packaging engineer", "flight engineer", "water resources",
            "sanitation", "mechanic", "maintenance technician", "field service technician",
            # Sales, marketing, retail
            "sales", "account exec", "account manager", "realtor", "real estate",
            "business development", "merchandis", "retail", "store manager", "cashier",
            # Healthcare, medical, lab, food
            "nurse", "nursing", "rn ", "clinical", "medical", "hospital", "chaplain",
            "therapist", "dental", "pharmacy", "phlebotom", "radiolog", "allied", "sushi",
            "food", "cook", "chef", "restaurant",
            # Finance, legal, admin
            "teller", "claims", "billing", "credit", "underwriter", "paralegal", "attorney",
            "legal assistant", "administrative assistant", "admin assistant", "office manager",
            # Manual labor, transport
            "driver", "truck", "bus driver", "porter", "custodian", "janitor", "laborer",
            "warehouse", "forklift", "data entry", "clerk", "receptionist", "security guard",
            "security officer", "behavior analyst", "behavioral", "sand management"
        ],
        description="Title substrings and patterns that exclude non-tech positions.",
    )

    # -- Experience level fallback ────────────────────────────────────
    experience_level_title_patterns: dict[str, list[str]] = Field(
        default={
            "Internship": ["intern", "internship", "co-op"],
            "Entry level": ["entry-level", "entry level", "junior", "jr.",
                            "associate", "graduate", "new grad"],
            "Mid-Senior level": ["senior", "sr.", "staff", "principal",
                                  "lead", "architect", "mid-level", "mid-senior"],
            "Director": ["director", "vp", "vice president",
                         "head of", "chief", "cto", "cio"],
            "Executive": ["executive", "president", "managing director"],
        },
        description="Title keywords mapped to experience levels for rule-based fallback.",
    )

    # -- Search scope ────────────────────────────────────────────────
    search_excluded_sections: list[str] = Field(
        default=["benefits", "about"],
        description="Chunk sections excluded from BM25 search (Benefits/About contain no requirements).",
    )

    paragraph_chunk_max_length: int = Field(
        default=800,
        description="Maximum character length for paragraph-based chunks.",
    )
    paragraph_chunk_overlap: int = Field(
        default=50,
        description="Character overlap between consecutive paragraph chunks.",
    )
    chunk_min_length: int = Field(
        default=100,
        description="Minimum character length for chunks; smaller fragments are merged into neighbors.",
    )

    # ── Retrieval ────────────────────────────────────────────────────
    bm25_top_n: int = Field(
        default=50,
        description="Number of chunks to retrieve from BM25 before aggregation.",
    )
    expansion_weight: Optional[float] = Field(
        default=None,
        description="None = OR expansion terms into one BM25 query; float w = fuse original + w * expansion.",
    )
    rerank_top_k: int = Field(
        default=10,
        description="Number of final job matches after LLM reranking.",
    )

    # ── LLM client ───────────────────────────────────────────────────
    llm_max_retries: int = Field(
        default=6,
        description="Maximum retries on transient LLM errors (429, 5xx).",
    )
    llm_retry_min_wait: float = Field(
        default=1.0,
        description="Minimum wait in seconds between LLM retries.",
    )
    llm_retry_max_wait: float = Field(
        default=60.0,
        description="Maximum wait in seconds between LLM retries.",
    )
    llm_cache_dir: Path = Field(
        default=_PROJECT_ROOT / ".llm_cache",
        description="Directory for disk-based LLM response cache.",
    )

    model_config = {
        "env_file": str(_PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


    def model_for(self, step_model: str) -> str:
        """Resolve a per-step model setting ("fast" / "agent" aliases, or an explicit model id)."""
        aliases = {"fast": self.groq_fast_model, "agent": self.groq_agent_model, "": self.groq_agent_model}
        return aliases.get(step_model, step_model)


def get_settings() -> Settings:
    """Factory function to create a ``Settings`` instance.

    Used as a FastAPI dependency and in script composition roots.
    """
    return Settings()


class CorsSettings(BaseSettings):
    """Browser origins allowed to call the API (read at app start-up).

    Kept separate from ``Settings`` so building the FastAPI app does not
    require ``GROQ_API_KEY`` (tests and tooling import the app without it).
    """

    allowed_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://192.168.100.17:3000",
        description="Comma-separated origins allowed by CORS (the web UI).",
    )

    model_config = {
        "env_file": str(_PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]
