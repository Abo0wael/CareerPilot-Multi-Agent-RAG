"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from src.domain.entities import CandidateProfile, ExperienceEntry, JobPosting


@pytest.fixture
def sample_job() -> JobPosting:
    return JobPosting(
        job_id=101,
        title="Senior Python Backend Engineer",
        company_name="TechNova Inc.",
        description="We require 5+ years with Python, FastAPI, Docker, and PostgreSQL. Nice to have Kubernetes.",
        location="Remote",
        formatted_experience_level="Mid-Senior level",
        skills=["Python", "FastAPI", "Docker", "PostgreSQL"],
    )


@pytest.fixture
def sample_profile() -> CandidateProfile:
    return CandidateProfile(
        raw_text="Alice Doe\nPython developer with 4 years building REST APIs using FastAPI, Docker, and PostgreSQL.",
        name="Alice Doe",
        skills=["Python", "FastAPI", "Docker", "PostgreSQL"],
        experiences=[
            ExperienceEntry(role="Developer", company="Co", duration="2020-2024", bullets=["Built REST APIs using FastAPI"])
        ],
    )
