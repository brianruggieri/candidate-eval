"""
JobRequirements: Structured representation of a job posting.

Parsed from pasted text, URL fetch, or manual structured input.
Consumed by the Matcher agent (full pipeline) and QuickMatchEngine (extension).
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RequirementPriority(str, Enum):
    """How critical a requirement is to the role."""

    MUST_HAVE = "must_have"
    STRONG_PREFERENCE = "strong_preference"
    NICE_TO_HAVE = "nice_to_have"
    IMPLIED = "implied"


PRIORITY_WEIGHT = {
    RequirementPriority.MUST_HAVE: 3.0,
    RequirementPriority.STRONG_PREFERENCE: 2.0,
    RequirementPriority.NICE_TO_HAVE: 1.0,
    RequirementPriority.IMPLIED: 0.5,
}


class JobRequirement(BaseModel):
    """A single requirement or preference from a job posting."""

    description: str
    skill_mapping: list[str] = Field(min_length=1)
    priority: RequirementPriority
    years_experience: int | None = None
    evidence_needed: str


class JobRequirements(BaseModel):
    """Full structured representation of a job posting."""

    # Source
    company: str
    title: str
    posting_url: str | None = None
    posting_text_hash: str
    ingested_at: datetime
    seniority_level: Literal[
        "junior", "mid", "senior", "staff", "principal", "director", "unknown"
    ]

    # Requirements
    requirements: list[JobRequirement]
    responsibilities: list[str]

    # Context
    tech_stack_mentioned: list[str]
    team_context: str | None = None
    culture_signals: list[str]
    red_flags: list[str] | None = None

    def must_haves(self) -> list[JobRequirement]:
        """Return only must-have requirements."""
        return [r for r in self.requirements if r.priority == RequirementPriority.MUST_HAVE]

    def all_required_skills(self) -> set[str]:
        """Return flat set of all skill names across all requirements."""
        skills: set[str] = set()
        for req in self.requirements:
            skills.update(s.lower() for s in req.skill_mapping)
        return skills

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> JobRequirements:
        return cls.model_validate_json(data)


class QuickRequirement(BaseModel):
    """
    Lightweight requirement for fast matching in the browser extension flow.

    Stripped-down version of JobRequirement that skips evidence_needed
    for speed. Produced by the QuickMatchEngine's internal parser or
    the enriched extraction prompt rather than the full Job Parser agent.
    """

    description: str
    skill_mapping: list[str] = Field(min_length=1)
    priority: RequirementPriority
    years_experience: int | None = None
    education_level: str | None = None  # "bachelor", "master", "phd", etc.
    source_text: str = ""  # Original text fragment this was extracted from
    is_eligibility: bool = False  # True = binary gate (work auth, travel, language), not scored
