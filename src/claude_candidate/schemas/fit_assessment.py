"""
FitAssessment: The primary output of the Quick Match engine.

Rendered in the browser extension popup/sidebar. Evaluates three
equally-weighted dimensions grounded entirely in resume + session evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from claude_candidate.schemas.merged_profile import EvidenceSource


class DimensionScore(BaseModel):
    """Score for a single fit dimension."""

    dimension: Literal[
        "skill_match", "experience_match", "education_match",
        "mission_alignment", "culture_fit",
    ]
    score: float = Field(ge=0.0, le=1.0)
    grade: str  # "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"
    weight: float = 0.333
    summary: str
    details: list[str] = Field(min_length=1, max_length=7)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    insufficient_data: bool = False


class SkillMatchDetail(BaseModel):
    """Detailed skill-by-skill match result."""

    requirement: str
    priority: str  # must_have, strong_preference, nice_to_have, implied
    match_status: str  # strong_match, partial_match, adjacent, no_evidence, exceeds
    candidate_evidence: str
    evidence_source: EvidenceSource
    confidence: float = Field(ge=0.0, le=1.0)
    matched_skill: str | None = None  # Canonical skill name that resolved this requirement


def score_to_grade(score: float) -> str:
    """Convert a 0.0–1.0 score to a letter grade."""
    if score >= 0.95:
        return "A+"
    elif score >= 0.90:
        return "A"
    elif score >= 0.85:
        return "A-"
    elif score >= 0.80:
        return "B+"
    elif score >= 0.75:
        return "B"
    elif score >= 0.70:
        return "B-"
    elif score >= 0.65:
        return "C+"
    elif score >= 0.60:
        return "C"
    elif score >= 0.55:
        return "C-"
    elif score >= 0.45:
        return "D"
    else:
        return "F"


def score_to_verdict(score: float) -> Literal[
    "strong_yes", "yes", "maybe", "probably_not", "no"
]:
    """Convert overall score to a blunt recommendation."""
    if score >= 0.80:
        return "strong_yes"
    elif score >= 0.65:
        return "yes"
    elif score >= 0.50:
        return "maybe"
    elif score >= 0.35:
        return "probably_not"
    else:
        return "no"


class FitAssessment(BaseModel):
    """
    Complete fit assessment for a job posting.

    The data model rendered in the extension popup/sidebar.
    """

    # Identification
    assessment_id: str
    assessed_at: datetime

    job_title: str
    company_name: str
    posting_url: str | None = None
    source: str  # "linkedin", "greenhouse", "paste", etc.

    # Phase tracking
    assessment_phase: Literal["partial", "full"] = "partial"
    partial_percentage: float | None = None  # 0-100 weighted %

    # Overall
    overall_score: float = Field(ge=0.0, le=1.0)
    overall_grade: str
    overall_summary: str

    # Narrative verdict & receptivity (populated during full assessment)
    narrative_verdict: str | None = None
    receptivity_level: Literal["high", "medium", "low"] | None = None
    receptivity_reason: str | None = None

    # Dimensions
    skill_match: DimensionScore
    experience_match: DimensionScore | None = None
    education_match: DimensionScore | None = None
    mission_alignment: DimensionScore | None = None
    culture_fit: DimensionScore | None = None

    # Skill detail
    skill_matches: list[SkillMatchDetail]
    must_have_coverage: str  # "5/7 must-haves met"
    strongest_match: str
    biggest_gap: str

    # Discovery
    resume_gaps_discovered: list[str]  # Skills in sessions but not resume
    resume_unverified: list[str]  # Resume skills without session backing

    # Company context
    company_profile_summary: str
    company_enrichment_quality: str

    # Actionability
    should_apply: Literal["strong_yes", "yes", "maybe", "probably_not", "no"]
    action_items: list[str] = Field(min_length=1, max_length=6)

    # Metadata
    profile_hash: str
    time_to_assess_seconds: float = Field(ge=0.0)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> FitAssessment:
        return cls.model_validate_json(data)
