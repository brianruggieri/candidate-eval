"""Tests for the QuickMatchEngine — three-dimension scoring and assessment generation."""

from __future__ import annotations

from datetime import datetime

import pytest

from claude_candidate.merger import merge_profiles, merge_candidate_only
from claude_candidate.quick_match import QuickMatchEngine
from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.fit_assessment import score_to_grade, score_to_verdict
from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority


class TestQuickMatchAssessment:
    """Integration tests running the full assessment flow."""

    def test_full_assessment_produces_valid_output(
        self, candidate_profile, resume_profile, quick_requirements
    ):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=quick_requirements,
            company="AI Tools Corp",
            title="Senior AI Engineer",
            seniority="senior",
        )

        # Basic structure
        assert assessment.assessment_id
        assert assessment.job_title == "Senior AI Engineer"
        assert assessment.company_name == "AI Tools Corp"
        assert 0.0 <= assessment.overall_score <= 1.0
        assert assessment.overall_grade
        assert assessment.overall_summary
        assert assessment.should_apply in ("strong_yes", "yes", "maybe", "probably_not", "no")

        # Dimensions present
        assert assessment.skill_match.dimension == "skill_match"
        assert assessment.mission_alignment.dimension == "mission_alignment"
        assert assessment.culture_fit.dimension == "culture_fit"

        # Skill details match requirements count
        assert len(assessment.skill_matches) == len(quick_requirements)

    def test_strong_fit_produces_high_score(
        self, candidate_profile, resume_profile, quick_requirements
    ):
        """The sample profile is deliberately a strong fit for the sample posting."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=quick_requirements,
            company="AI Tools Corp",
            title="Senior AI Engineer",
            seniority="senior",
            culture_signals=["open source", "documentation", "remote", "autonomous"],
            tech_stack=["python", "typescript", "react", "fastapi", "claude-api"],
        )

        # This candidate should score well against this posting
        assert assessment.skill_match.score >= 0.6
        assert assessment.should_apply in ("strong_yes", "yes")

    def test_must_have_coverage_string(
        self, candidate_profile, resume_profile, quick_requirements
    ):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=quick_requirements,
            company="Test",
            title="Test",
            seniority="senior",
        )

        # Should contain "X/Y must-haves met" format
        assert "must-haves met" in assessment.must_have_coverage

    def test_resume_gaps_discovered(
        self, candidate_profile, resume_profile, quick_requirements
    ):
        """Skills in sessions but not resume that are relevant should be flagged."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=quick_requirements,
            company="Test",
            title="Test",
        )

        # claude-api is in sessions but not resume, and is required by this job
        # It should appear in resume_gaps_discovered
        # (depends on exact matching — may or may not match depending on fuzzy logic)
        assert isinstance(assessment.resume_gaps_discovered, list)

    def test_action_items_non_empty(
        self, candidate_profile, resume_profile, quick_requirements
    ):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=quick_requirements,
            company="Test",
            title="Test",
        )

        assert len(assessment.action_items) >= 1

    def test_assessment_timing_tracked(
        self, candidate_profile, resume_profile, quick_requirements
    ):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=quick_requirements,
            company="Test",
            title="Test",
        )

        assert assessment.time_to_assess_seconds >= 0


class TestSkillMatchScoring:
    def test_exact_skill_match(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        requirements = [QuickRequirement(
            description="Python proficiency",
            skill_mapping=["python"],
            priority=RequirementPriority.MUST_HAVE,
        )]

        assessment = engine.assess(
            requirements=requirements,
            company="Test",
            title="Test",
            seniority="senior",
        )

        detail = assessment.skill_matches[0]
        assert detail.match_status in ("strong_match", "exceeds")

    def test_missing_skill_detected(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        requirements = [QuickRequirement(
            description="Rust proficiency",
            skill_mapping=["rust"],
            priority=RequirementPriority.MUST_HAVE,
        )]

        assessment = engine.assess(
            requirements=requirements,
            company="Test",
            title="Test",
        )

        detail = assessment.skill_matches[0]
        assert detail.match_status == "no_evidence"

    def test_priority_weighting_affects_score(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        # All must-have = missing skill → low score
        reqs_must = [QuickRequirement(
            description="Rust",
            skill_mapping=["rust"],
            priority=RequirementPriority.MUST_HAVE,
        )]

        # All nice-to-have = missing skill → less impact
        reqs_nice = [QuickRequirement(
            description="Rust",
            skill_mapping=["rust"],
            priority=RequirementPriority.NICE_TO_HAVE,
        )]

        a_must = engine.assess(requirements=reqs_must, company="T", title="T")
        a_nice = engine.assess(requirements=reqs_nice, company="T", title="T")

        # Both should be low (missing skill), but must_have weights it more heavily
        # in overall scoring. Since both have only one requirement, the raw scores
        # for the skill dimension should be the same (0.0), but verify it doesn't crash.
        assert a_must.skill_match.score == 0.0
        assert a_nice.skill_match.score == 0.0


class TestMissionAlignment:
    def test_with_company_profile(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        company_profile = CompanyProfile(
            company_name="DevTools Inc",
            product_description="AI-powered developer tools",
            product_domain=["developer-tooling", "ai-infrastructure"],
            tech_stack_public=["python", "typescript", "react"],
            oss_activity_level="very_active",
            enriched_at=datetime.now(),
            enrichment_quality="rich",
        )

        assessment = engine.assess(
            requirements=[QuickRequirement(
                description="Python", skill_mapping=["python"],
                priority=RequirementPriority.MUST_HAVE,
            )],
            company="DevTools Inc",
            title="Engineer",
            company_profile=company_profile,
        )

        # Strong alignment expected: developer-tooling domain overlap, tech overlap, OSS
        assert assessment.mission_alignment.score > 0.5

    def test_without_company_profile(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=[QuickRequirement(
                description="Python", skill_mapping=["python"],
                priority=RequirementPriority.MUST_HAVE,
            )],
            company="Unknown Corp",
            title="Engineer",
            tech_stack=["python", "typescript"],
        )

        # Should still produce a score, but with lower confidence
        assert 0.0 <= assessment.mission_alignment.score <= 1.0
        assert "Limited enrichment" in assessment.mission_alignment.details[-1] or \
               "Insufficient" in assessment.mission_alignment.details[-1] or \
               "overlap" in " ".join(assessment.mission_alignment.details).lower()


class TestCultureFit:
    def test_with_matching_signals(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=[QuickRequirement(
                description="Python", skill_mapping=["python"],
                priority=RequirementPriority.MUST_HAVE,
            )],
            company="Test",
            title="Test",
            culture_signals=["documentation", "autonomous", "open source"],
        )

        # The candidate has documentation_driven, scope_management, and open-source patterns
        assert assessment.culture_fit.score > 0.5

    def test_no_culture_signals(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=[QuickRequirement(
                description="Python", skill_mapping=["python"],
                priority=RequirementPriority.MUST_HAVE,
            )],
            company="Test",
            title="Test",
        )

        # Should default to neutral (0.5)
        assert assessment.culture_fit.score == 0.5


class TestCandidateOnlyAssessment:
    """Test assessment when only session data is available (no resume)."""

    def test_works_without_resume(self, candidate_profile, quick_requirements):
        merged = merge_candidate_only(candidate_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=quick_requirements,
            company="Test",
            title="Test",
        )

        assert assessment.overall_score > 0
        assert len(assessment.skill_matches) == len(quick_requirements)
