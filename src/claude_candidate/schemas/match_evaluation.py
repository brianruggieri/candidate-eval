"""
MatchEvaluation: The result of comparing CandidateProfile against JobRequirements.

This IR drives all deliverable generation in Stage 5.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from claude_candidate.schemas.candidate_profile import SessionReference
from claude_candidate.schemas.job_requirements import JobRequirement


class SkillMatch(BaseModel):
    """How a specific job requirement maps to candidate evidence."""

    requirement: JobRequirement
    match_status: Literal[
        "strong_match", "partial_match", "adjacent", "no_evidence", "exceeds"
    ]
    supporting_evidence: list[SessionReference]
    public_corroboration: list[str] | None = None
    narrative: str
    gap_description: str | None = None


class MatchEvaluation(BaseModel):
    """
    Full match evaluation — CandidateProfile × JobRequirements.
    """

    profile_hash: str
    job_hash: str
    evaluated_at: datetime

    # Match results
    skill_matches: list[SkillMatch]
    overall_fit: Literal["strong", "good", "moderate", "weak", "poor"]
    fit_reasoning: str

    # Strengths & gaps
    top_strengths: list[str] = Field(min_length=1, max_length=7)
    notable_gaps: list[str]
    differentiators: list[str]

    # Strategic recommendations
    resume_emphasis: list[str]
    cover_letter_themes: list[str]
    interview_prep_topics: list[str]
    risk_mitigation: list[str]

    def must_have_coverage(self) -> tuple[int, int]:
        """Return (met, total) for must-have requirements."""
        from claude_candidate.schemas.job_requirements import RequirementPriority

        must_haves = [
            m for m in self.skill_matches
            if m.requirement.priority == RequirementPriority.MUST_HAVE
        ]
        met = sum(
            1 for m in must_haves
            if m.match_status in ("strong_match", "exceeds", "partial_match")
        )
        return met, len(must_haves)

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> MatchEvaluation:
        return cls.model_validate_json(data)
