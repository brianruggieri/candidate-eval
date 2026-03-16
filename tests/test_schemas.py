"""Tests for all Pydantic schemas — round-trip, validation, edge cases."""

from __future__ import annotations

import json
from datetime import datetime

import pytest
from pydantic import ValidationError

from claude_candidate.schemas.candidate_profile import (
    CandidateProfile,
    DepthLevel,
    DEPTH_RANK,
    PatternType,
    ProblemSolvingPattern,
    SessionReference,
    SkillEntry,
)
from claude_candidate.schemas.job_requirements import (
    JobRequirements,
    QuickRequirement,
    RequirementPriority,
)
from claude_candidate.schemas.match_evaluation import MatchEvaluation, SkillMatch
from claude_candidate.schemas.resume_profile import ResumeProfile, ResumeSkill
from claude_candidate.schemas.merged_profile import (
    EvidenceSource,
    MergedEvidenceProfile,
    MergedSkillEvidence,
)
from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.fit_assessment import (
    FitAssessment,
    DimensionScore,
    score_to_grade,
    score_to_verdict,
)


# === SessionReference ===

class TestSessionReference:
    def test_valid_reference(self):
        ref = SessionReference(
            session_id="2026-01-01_10-00-00_abc12345",
            session_date=datetime(2026, 1, 1, 10),
            project_context="test project",
            evidence_snippet="Did something with Python",
            evidence_type="direct_usage",
            confidence=0.85,
        )
        assert ref.confidence == 0.85
        assert ref.evidence_type == "direct_usage"

    def test_confidence_bounds(self):
        with pytest.raises(ValidationError):
            SessionReference(
                session_id="test",
                session_date=datetime.now(),
                project_context="test",
                evidence_snippet="test",
                evidence_type="direct_usage",
                confidence=1.5,  # Over 1.0
            )

        with pytest.raises(ValidationError):
            SessionReference(
                session_id="test",
                session_date=datetime.now(),
                project_context="test",
                evidence_snippet="test",
                evidence_type="direct_usage",
                confidence=-0.1,  # Below 0.0
            )

    def test_empty_snippet_rejected(self):
        with pytest.raises(ValidationError):
            SessionReference(
                session_id="test",
                session_date=datetime.now(),
                project_context="test",
                evidence_snippet="   ",  # Whitespace only
                evidence_type="direct_usage",
                confidence=0.5,
            )

    def test_snippet_max_length(self):
        with pytest.raises(ValidationError):
            SessionReference(
                session_id="test",
                session_date=datetime.now(),
                project_context="test",
                evidence_snippet="x" * 501,  # Over 500
                evidence_type="direct_usage",
                confidence=0.5,
            )


# === SkillEntry ===

class TestSkillEntry:
    def test_name_normalization(self):
        skill = SkillEntry(
            name="  Python  ",
            category="language",
            depth=DepthLevel.DEEP,
            frequency=10,
            recency=datetime.now(),
            first_seen=datetime(2025, 1, 1),
            evidence=[SessionReference(
                session_id="test",
                session_date=datetime.now(),
                project_context="test",
                evidence_snippet="Used Python",
                evidence_type="direct_usage",
                confidence=0.9,
            )],
        )
        assert skill.name == "python"  # Normalized

    def test_requires_at_least_one_evidence(self):
        with pytest.raises(ValidationError):
            SkillEntry(
                name="python",
                category="language",
                depth=DepthLevel.DEEP,
                frequency=10,
                recency=datetime.now(),
                first_seen=datetime(2025, 1, 1),
                evidence=[],  # Empty — should fail
            )


# === CandidateProfile Round-Trip ===

class TestCandidateProfile:
    def test_round_trip_serialization(self, sample_candidate_profile_json):
        profile = CandidateProfile.from_json(sample_candidate_profile_json)
        json_str = profile.to_json()
        profile2 = CandidateProfile.from_json(json_str)

        assert profile.session_count == profile2.session_count
        assert len(profile.skills) == len(profile2.skills)
        assert len(profile.projects) == len(profile2.projects)
        assert profile.manifest_hash == profile2.manifest_hash

    def test_get_skill(self, candidate_profile):
        python = candidate_profile.get_skill("python")
        assert python is not None
        assert python.depth == DepthLevel.DEEP

        missing = candidate_profile.get_skill("cobol")
        assert missing is None

    def test_skills_by_category(self, candidate_profile):
        languages = candidate_profile.skills_by_category("language")
        assert len(languages) >= 2
        assert all(s.category == "language" for s in languages)

    def test_fixture_has_required_fields(self, candidate_profile):
        assert candidate_profile.session_count > 0
        assert len(candidate_profile.skills) > 0
        assert len(candidate_profile.problem_solving_patterns) > 0
        assert len(candidate_profile.projects) > 0
        assert candidate_profile.working_style_summary
        assert candidate_profile.extraction_notes


# === ResumeProfile Round-Trip ===

class TestResumeProfile:
    def test_round_trip_serialization(self, sample_resume_profile_json):
        profile = ResumeProfile.from_json(sample_resume_profile_json)
        json_str = profile.to_json()
        profile2 = ResumeProfile.from_json(json_str)

        assert len(profile.skills) == len(profile2.skills)
        assert len(profile.roles) == len(profile2.roles)
        assert profile.source_file_hash == profile2.source_file_hash

    def test_get_skill(self, resume_profile):
        python = resume_profile.get_skill("python")
        assert python is not None
        assert python.years_experience == 8.0

    def test_all_skill_names(self, resume_profile):
        names = resume_profile.all_skill_names()
        assert "python" in names
        assert "typescript" in names

    def test_skill_name_normalization(self):
        skill = ResumeSkill(
            name="  TypeScript  ",
            source_context="test",
            implied_depth=DepthLevel.APPLIED,
            recency="current_role",
        )
        assert skill.name == "typescript"


# === QuickRequirement ===

class TestQuickRequirement:
    def test_requires_skill_mapping(self):
        with pytest.raises(ValidationError):
            QuickRequirement(
                description="test",
                skill_mapping=[],  # Empty — should fail
                priority=RequirementPriority.MUST_HAVE,
            )

    def test_valid_requirement(self, quick_requirements):
        assert len(quick_requirements) > 0
        for req in quick_requirements:
            assert len(req.skill_mapping) >= 1


# === Depth Ranking ===

class TestDepthRank:
    def test_ordering(self):
        assert DEPTH_RANK[DepthLevel.MENTIONED] < DEPTH_RANK[DepthLevel.USED]
        assert DEPTH_RANK[DepthLevel.USED] < DEPTH_RANK[DepthLevel.APPLIED]
        assert DEPTH_RANK[DepthLevel.APPLIED] < DEPTH_RANK[DepthLevel.DEEP]
        assert DEPTH_RANK[DepthLevel.DEEP] < DEPTH_RANK[DepthLevel.EXPERT]


# === MergedSkillEvidence ===

class TestMergedSkillEvidence:
    def test_compute_effective_depth_corroborated(self):
        # When corroborated, take the higher depth
        depth = MergedSkillEvidence.compute_effective_depth(
            EvidenceSource.CORROBORATED, DepthLevel.APPLIED, DepthLevel.DEEP
        )
        assert depth == DepthLevel.DEEP

    def test_compute_effective_depth_sessions_only(self):
        depth = MergedSkillEvidence.compute_effective_depth(
            EvidenceSource.SESSIONS_ONLY, None, DepthLevel.APPLIED
        )
        assert depth == DepthLevel.APPLIED

    def test_compute_effective_depth_resume_only(self):
        depth = MergedSkillEvidence.compute_effective_depth(
            EvidenceSource.RESUME_ONLY, DepthLevel.DEEP, None
        )
        assert depth == DepthLevel.DEEP

    def test_compute_effective_depth_conflicting_uses_sessions(self):
        depth = MergedSkillEvidence.compute_effective_depth(
            EvidenceSource.CONFLICTING, DepthLevel.EXPERT, DepthLevel.USED
        )
        assert depth == DepthLevel.USED  # Sessions win in conflict

    def test_compute_confidence_corroborated_high_freq(self):
        conf = MergedSkillEvidence.compute_confidence(
            EvidenceSource.CORROBORATED, 50, "Detailed context"
        )
        assert conf >= 0.9

    def test_compute_confidence_resume_only_vague(self):
        conf = MergedSkillEvidence.compute_confidence(
            EvidenceSource.RESUME_ONLY, None, "test"
        )
        assert conf <= 0.4  # Short/vague context


# === Score Functions ===

class TestScoreFunctions:
    def test_score_to_grade_boundaries(self):
        assert score_to_grade(0.95) == "A+"
        assert score_to_grade(0.90) == "A"
        assert score_to_grade(0.85) == "A-"
        assert score_to_grade(0.80) == "B+"
        assert score_to_grade(0.75) == "B"
        assert score_to_grade(0.45) == "D"
        assert score_to_grade(0.20) == "F"

    def test_score_to_verdict(self):
        assert score_to_verdict(0.90) == "strong_yes"
        assert score_to_verdict(0.70) == "yes"
        assert score_to_verdict(0.55) == "maybe"
        assert score_to_verdict(0.40) == "probably_not"
        assert score_to_verdict(0.20) == "no"


# === CompanyProfile ===

class TestCompanyProfile:
    def test_minimal_company_profile(self):
        cp = CompanyProfile(
            company_name="Test Corp",
            product_description="Builds things",
            product_domain=["developer-tooling"],
            enriched_at=datetime.now(),
        )
        assert cp.enrichment_quality == "sparse"  # Default
        assert cp.oss_activity_level == "unknown"
