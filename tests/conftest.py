"""Shared pytest fixtures for claude-candidate tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES_DIR


@pytest.fixture
def sample_candidate_profile_json() -> str:
    return (FIXTURES_DIR / "sample_candidate_profile.json").read_text()


@pytest.fixture
def sample_resume_profile_json() -> str:
    return (FIXTURES_DIR / "sample_resume_profile.json").read_text()


@pytest.fixture
def sample_job_posting_text() -> str:
    return (FIXTURES_DIR / "sample_job_posting.txt").read_text()


@pytest.fixture
def sample_requirements_json() -> str:
    return (FIXTURES_DIR / "sample_job_posting.requirements.json").read_text()


@pytest.fixture
def candidate_profile():
    from claude_candidate.schemas.candidate_profile import CandidateProfile
    data = (FIXTURES_DIR / "sample_candidate_profile.json").read_text()
    return CandidateProfile.from_json(data)


@pytest.fixture
def resume_profile():
    from claude_candidate.schemas.resume_profile import ResumeProfile
    data = (FIXTURES_DIR / "sample_resume_profile.json").read_text()
    return ResumeProfile.from_json(data)


@pytest.fixture
def quick_requirements():
    from claude_candidate.schemas.job_requirements import QuickRequirement
    data = json.loads((FIXTURES_DIR / "sample_job_posting.requirements.json").read_text())
    return [QuickRequirement(**r) for r in data]


@pytest.fixture
def minimal_engine():
    from claude_candidate.merger import merge_candidate_only
    from claude_candidate.quick_match import QuickMatchEngine
    from claude_candidate.schemas.candidate_profile import CandidateProfile
    data = (FIXTURES_DIR / "sample_candidate_profile.json").read_text()
    cp = CandidateProfile.from_json(data)
    merged = merge_candidate_only(cp)
    return QuickMatchEngine(merged)


@pytest.fixture
def eligibility_requirement():
    from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
    return QuickRequirement(
        description="Must be authorized to work in the United States",
        skill_mapping=["us-work-authorization"],
        priority=RequirementPriority.MUST_HAVE,
        is_eligibility=True,
        source_text="Must be authorized to work in the United States",
    )
