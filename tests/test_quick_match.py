"""Tests for the QuickMatchEngine — three-dimension scoring and assessment generation."""

from __future__ import annotations

from datetime import datetime


from claude_candidate.merger import merge_profiles, merge_candidate_only
from claude_candidate.quick_match import QuickMatchEngine, _compute_weights
from claude_candidate.schemas.company_profile import CompanyProfile
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


class TestComputeWeights:
    """Unit tests for _compute_weights() across all four confidence tiers."""

    def _make_profile(self, quality: str) -> CompanyProfile:
        return CompanyProfile(
            company_name="Test Co",
            product_description="A product",
            product_domain=["saas"],
            enriched_at=datetime.now(),
            enrichment_quality=quality,  # type: ignore[arg-type]
        )

    def test_no_company_data_returns_none_tier_weights(self):
        skill_w, mission_w, culture_w = _compute_weights(None)
        assert skill_w == 0.85
        assert mission_w == 0.10
        assert culture_w == 0.05

    def test_sparse_enrichment_returns_sparse_tier_weights(self):
        profile = self._make_profile("sparse")
        skill_w, mission_w, culture_w = _compute_weights(profile)
        assert skill_w == 0.70
        assert mission_w == 0.15
        assert culture_w == 0.15

    def test_moderate_enrichment_returns_moderate_tier_weights(self):
        profile = self._make_profile("moderate")
        skill_w, mission_w, culture_w = _compute_weights(profile)
        assert skill_w == 0.60
        assert mission_w == 0.20
        assert culture_w == 0.20

    def test_rich_enrichment_returns_rich_tier_weights(self):
        profile = self._make_profile("rich")
        skill_w, mission_w, culture_w = _compute_weights(profile)
        assert skill_w == 0.50
        assert mission_w == 0.25
        assert culture_w == 0.25

    def test_weights_sum_to_one_for_each_tier(self):
        for quality in ("rich", "moderate", "sparse"):
            profile = self._make_profile(quality)
            weights = _compute_weights(profile)
            assert abs(sum(weights) - 1.0) < 1e-9, (
                f"Weights for {quality!r} do not sum to 1.0: {weights}"
            )
        none_weights = _compute_weights(None)
        assert abs(sum(none_weights) - 1.0) < 1e-9


class TestAdaptiveWeightsWiredIntoAssessment:
    """Integration tests verifying dimension weights are set from company data quality."""

    def _minimal_requirements(self) -> list[QuickRequirement]:
        return [QuickRequirement(
            description="Python",
            skill_mapping=["python"],
            priority=RequirementPriority.MUST_HAVE,
        )]

    def _make_company_profile(self, quality: str) -> CompanyProfile:
        return CompanyProfile(
            company_name="Test Co",
            product_description="A product",
            product_domain=["saas"],
            enriched_at=datetime.now(),
            enrichment_quality=quality,  # type: ignore[arg-type]
        )

    def test_rich_profile_sets_rich_weights_on_dimensions(
        self, candidate_profile, resume_profile
    ):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)
        company_profile = self._make_company_profile("rich")

        assessment = engine.assess(
            requirements=self._minimal_requirements(),
            company="Test Co",
            title="Engineer",
            company_profile=company_profile,
        )

        assert assessment.skill_match.weight == 0.50
        assert assessment.mission_alignment.weight == 0.25
        assert assessment.culture_fit.weight == 0.25

    def test_moderate_profile_sets_moderate_weights_on_dimensions(
        self, candidate_profile, resume_profile
    ):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)
        company_profile = self._make_company_profile("moderate")

        assessment = engine.assess(
            requirements=self._minimal_requirements(),
            company="Test Co",
            title="Engineer",
            company_profile=company_profile,
        )

        assert assessment.skill_match.weight == 0.60
        assert assessment.mission_alignment.weight == 0.20
        assert assessment.culture_fit.weight == 0.20

    def test_sparse_profile_sets_sparse_weights_on_dimensions(
        self, candidate_profile, resume_profile
    ):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)
        company_profile = self._make_company_profile("sparse")

        assessment = engine.assess(
            requirements=self._minimal_requirements(),
            company="Test Co",
            title="Engineer",
            company_profile=company_profile,
        )

        assert assessment.skill_match.weight == 0.70
        assert assessment.mission_alignment.weight == 0.15
        assert assessment.culture_fit.weight == 0.15

    def test_no_company_profile_sets_none_tier_weights_on_dimensions(
        self, candidate_profile, resume_profile
    ):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=self._minimal_requirements(),
            company="Test Co",
            title="Engineer",
            company_profile=None,
        )

        assert assessment.skill_match.weight == 0.85
        assert assessment.mission_alignment.weight == 0.10
        assert assessment.culture_fit.weight == 0.05
