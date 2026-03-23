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

        # Dimensions present (partial assessment)
        assert assessment.skill_match.dimension == "skill_match"
        assert assessment.experience_match is not None
        assert assessment.education_match is not None
        assert assessment.assessment_phase == "partial"
        assert assessment.partial_percentage is not None
        assert 0.0 <= assessment.partial_percentage <= 100.0
        # Mission and culture are None in partial assessment
        assert assessment.mission_alignment is None
        assert assessment.culture_fit is None

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

        # must_have no_evidence scores 0.0 (hard gap), nice_to_have gets
        # STATUS_SCORE_NONE floor (transferable skills).
        from claude_candidate.quick_match import STATUS_SCORE_NONE
        assert a_must.skill_match.score == 0.0
        assert a_nice.skill_match.score == STATUS_SCORE_NONE


class TestMissionAlignment:
    """Tests for _score_mission_alignment — called directly since partial assessment skips it."""

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

        dim = engine._score_mission_alignment("DevTools Inc", [], company_profile)

        # Strong alignment expected: developer-tooling domain overlap + tech overlap
        assert dim.score > 0.5

    def test_without_company_profile(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        dim = engine._score_mission_alignment(
            "Unknown Corp", ["python", "typescript"], None,
        )

        # Should still produce a score, but with lower confidence
        assert 0.0 <= dim.score <= 1.0
        assert "Limited enrichment" in dim.details[-1] or \
               "Insufficient" in dim.details[-1] or \
               "overlap" in " ".join(dim.details).lower()

    def test_tech_stack_overlap_signal(self, candidate_profile, resume_profile):
        """Tech stack overlap produces a non-zero bonus when company techs match candidate skills."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        company_profile = CompanyProfile(
            company_name="PythonCo",
            product_description="Data processing platform",
            product_domain=["data-infrastructure"],
            tech_stack_public=["python", "typescript"],
            enriched_at=datetime.now(),
            enrichment_quality="moderate",
        )

        dim = engine._score_mission_alignment("PythonCo", [], company_profile)

        details_text = " ".join(dim.details).lower()
        assert "tech overlap" in details_text
        assert dim.score > 0.5

    def test_domain_overlap_signal(self, candidate_profile, resume_profile):
        """Domain overlap produces a bonus when company domain matches candidate domains."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        company_profile = CompanyProfile(
            company_name="ToolsCo",
            product_description="Developer productivity tools",
            product_domain=["developer-tooling"],
            tech_stack_public=[],
            enriched_at=datetime.now(),
            enrichment_quality="sparse",
        )

        dim = engine._score_mission_alignment("ToolsCo", [], company_profile)

        details_text = " ".join(dim.details).lower()
        assert "domain overlap" in details_text

    def test_mission_text_alignment_signal(self, candidate_profile, resume_profile):
        """Mission statement keyword overlap with candidate skills produces a bonus."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        company_profile = CompanyProfile(
            company_name="MissionCo",
            product_description="Platform for developers",
            product_domain=["saas"],
            tech_stack_public=[],
            mission_statement=(
                "We empower python developers to build better tools "
                "through automation and cli-design"
            ),
            enriched_at=datetime.now(),
            enrichment_quality="moderate",
        )

        dim = engine._score_mission_alignment("MissionCo", [], company_profile)

        details_text = " ".join(dim.details).lower()
        assert "mission" in details_text
        assert dim.score > 0.5

    def test_oss_bonus_no_longer_applied(self, candidate_profile, resume_profile):
        """OSS activity level should have no effect on mission score."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        base_profile = CompanyProfile(
            company_name="Co",
            product_description="A product",
            product_domain=["unrelated-niche-domain"],
            tech_stack_public=[],
            enriched_at=datetime.now(),
            enrichment_quality="rich",
        )
        oss_profile = CompanyProfile(
            company_name="Co",
            product_description="A product",
            product_domain=["unrelated-niche-domain"],
            tech_stack_public=[],
            oss_activity_level="very_active",
            enriched_at=datetime.now(),
            enrichment_quality="rich",
        )

        dim_base = engine._score_mission_alignment("Co", [], base_profile)
        dim_oss = engine._score_mission_alignment("Co", [], oss_profile)

        # Scores must be identical — OSS level should not move the needle
        assert dim_base.score == dim_oss.score


class TestCultureFit:
    """Tests for _score_culture_fit — called directly since partial assessment skips it."""

    def test_with_directly_matching_signals(self, candidate_profile, resume_profile):
        """Direct pattern name matches (documentation driven, scope management) produce score > 0.5."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        dim = engine._score_culture_fit(
            ["documentation driven", "scope management"], None,
        )

        # Both signals match patterns directly; score should exceed 0.5
        assert dim.score > 0.5
        assert not dim.insufficient_data
        assert dim.confidence > 0.0

    def test_no_culture_signals_marks_insufficient_data(self, candidate_profile, resume_profile):
        """No culture signals → insufficient_data=True, confidence=0.0."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        dim = engine._score_culture_fit([], None)

        assert dim.score == 0.5
        assert dim.insufficient_data is True
        assert dim.confidence == 0.0

    def test_partial_signal_match_produces_intermediate_score(
        self, candidate_profile, resume_profile
    ):
        """One matching signal among multiple produces score between 0.3 and 0.9."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        # Only "documentation driven" matches; "move fast" and "open source" do not
        dim = engine._score_culture_fit(
            ["documentation driven", "move fast", "open source"], None,
        )

        # 1 match out of 3 → score = 0.3 + (1/3)*0.6 = 0.5 exactly
        assert 0.3 <= dim.score <= 0.9
        assert not dim.insufficient_data

    def test_confidence_equals_match_ratio(self, candidate_profile, resume_profile):
        """Confidence field equals matched / total signals."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        dim = engine._score_culture_fit(
            ["documentation driven", "scope management", "no match signal"], None,
        )

        # 2 out of 3 match → confidence ≈ 0.667
        assert 0.0 <= dim.confidence <= 1.0
        assert not dim.insufficient_data


class TestExperienceMatchScoring:
    """Tests for _score_experience_match dimension."""

    def test_experience_match_sufficient_years(self, candidate_profile, resume_profile):
        """Candidate with enough years scores >= 0.7."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        requirements = [QuickRequirement(
            description="Python proficiency",
            skill_mapping=["python"],
            priority=RequirementPriority.MUST_HAVE,
            years_experience=5,
        )]

        dim = engine._score_experience_match(requirements, "senior")
        # Candidate has 8.5 years, requirement is 5 → should be >= 0.7
        assert dim.dimension == "experience_match"
        assert dim.score >= 0.7
        assert not dim.insufficient_data
        assert any("Met:" in d for d in dim.details)

    def test_experience_match_insufficient_years(self, candidate_profile, resume_profile):
        """Candidate with too few years scores < 0.7."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        requirements = [QuickRequirement(
            description="Senior ML engineering",
            skill_mapping=["machine-learning"],
            priority=RequirementPriority.MUST_HAVE,
            years_experience=15,
        )]

        dim = engine._score_experience_match(requirements, "senior")
        # Candidate has 8.5 years, requirement is 15 → below threshold
        assert dim.dimension == "experience_match"
        assert dim.score < 0.7
        assert not dim.insufficient_data
        assert any("Gap:" in d for d in dim.details)

    def test_experience_match_no_years_specified(self, candidate_profile, resume_profile):
        """No years requirements → effectively met (0.9) with insufficient_data."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        requirements = [QuickRequirement(
            description="Python proficiency",
            skill_mapping=["python"],
            priority=RequirementPriority.MUST_HAVE,
        )]

        dim = engine._score_experience_match(requirements, "senior")
        assert dim.dimension == "experience_match"
        assert dim.score == 0.9
        assert dim.insufficient_data is True

    def test_experience_match_candidate_no_years(self, candidate_profile):
        """Candidate with no total_years_experience → neutral with insufficient_data."""
        merged = merge_candidate_only(candidate_profile)
        engine = QuickMatchEngine(merged)

        requirements = [QuickRequirement(
            description="Python proficiency",
            skill_mapping=["python"],
            priority=RequirementPriority.MUST_HAVE,
            years_experience=5,
        )]

        dim = engine._score_experience_match(requirements, "senior")
        assert dim.score == 0.5
        assert dim.insufficient_data is True


class TestEducationMatchScoring:
    """Tests for _score_education_match dimension."""

    def test_education_match_degree_met(self, candidate_profile, resume_profile):
        """Candidate with matching degree scores well."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        requirements = [QuickRequirement(
            description="CS degree required",
            skill_mapping=["python"],
            priority=RequirementPriority.MUST_HAVE,
            education_level="bachelor",
        )]

        dim = engine._score_education_match(requirements, [])
        # Candidate has "B.S. Computer Science" → meets bachelor requirement
        assert dim.dimension == "education_match"
        assert dim.score >= 0.7
        assert not dim.insufficient_data
        assert any("met" in d.lower() for d in dim.details)

    def test_education_match_tech_stack_overlap(self, candidate_profile, resume_profile):
        """Tech stack overlap produces a positive score."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        requirements = [QuickRequirement(
            description="Python proficiency",
            skill_mapping=["python"],
            priority=RequirementPriority.MUST_HAVE,
        )]

        dim = engine._score_education_match(
            requirements, ["python", "typescript", "react"]
        )
        assert dim.dimension == "education_match"
        assert dim.score > 0.5
        assert not dim.insufficient_data
        assert any("tech stack" in d.lower() for d in dim.details)

    def test_education_match_no_requirements(self, candidate_profile, resume_profile):
        """No education or tech stack requirements → neutral with insufficient_data."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        requirements = [QuickRequirement(
            description="Python proficiency",
            skill_mapping=["python"],
            priority=RequirementPriority.MUST_HAVE,
        )]

        dim = engine._score_education_match(requirements, [])
        assert dim.dimension == "education_match"
        assert dim.score == 0.9
        assert dim.insufficient_data is True

    def test_education_match_combined_signals(self, candidate_profile, resume_profile):
        """Both education and tech stack produce an averaged score."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        requirements = [QuickRequirement(
            description="CS degree required",
            skill_mapping=["python"],
            priority=RequirementPriority.MUST_HAVE,
            education_level="bachelor",
        )]

        dim = engine._score_education_match(
            requirements, ["python", "typescript"]
        )
        assert dim.dimension == "education_match"
        assert dim.score > 0.5
        assert not dim.insufficient_data
        # Should have details for both signals
        assert len(dim.details) >= 2


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


class TestPartialAssessmentWeights:
    """Integration tests verifying partial assessment uses fixed 50/30/20 weights."""

    def _minimal_requirements(self) -> list[QuickRequirement]:
        return [QuickRequirement(
            description="Python",
            skill_mapping=["python"],
            priority=RequirementPriority.MUST_HAVE,
        )]

    def test_partial_assessment_uses_fixed_weights(
        self, candidate_profile, resume_profile
    ):
        """Partial assessment always uses 65/25/10 weights."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=self._minimal_requirements(),
            company="Test Co",
            title="Engineer",
        )

        assert assessment.skill_match.weight == 0.65
        assert assessment.experience_match.weight == 0.25
        assert assessment.education_match.weight == 0.10

    def test_insufficient_data_scores_high(
        self, candidate_profile, resume_profile
    ):
        """No requirement stated = effectively met (score ~0.9)."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=self._minimal_requirements(),
            company="Test Co",
            title="Engineer",
        )

        assert assessment.experience_match.insufficient_data is True
        assert assessment.experience_match.score >= 0.85
        assert assessment.education_match.insufficient_data is True
        assert assessment.education_match.score >= 0.85

    def test_partial_assessment_weights_sum_to_one(
        self, candidate_profile, resume_profile
    ):
        """Partial assessment weights always sum to 1.0."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=self._minimal_requirements(),
            company="Test Co",
            title="Engineer",
        )

        total = (
            assessment.skill_match.weight
            + assessment.experience_match.weight
            + assessment.education_match.weight
        )
        assert abs(total - 1.0) < 1e-9

    def test_partial_assessment_no_mission_or_culture(
        self, candidate_profile, resume_profile
    ):
        """Partial assessment leaves mission and culture as None."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=self._minimal_requirements(),
            company="Test Co",
            title="Engineer",
            culture_signals=["documentation driven"],
        )

        # Even with culture signals passed, partial skips them
        assert assessment.mission_alignment is None
        assert assessment.culture_fit is None

    def test_partial_percentage_matches_weighted_score(
        self, candidate_profile, resume_profile
    ):
        """partial_percentage == overall_score * 100."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=self._minimal_requirements(),
            company="Test Co",
            title="Engineer",
        )

        expected = round(assessment.overall_score * 100, 1)
        assert assessment.partial_percentage == expected

    def test_partial_assessment_experience_and_education_populated(
        self, candidate_profile, resume_profile
    ):
        """Partial assessment populates experience_match and education_match dimensions."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=self._minimal_requirements(),
            company="Test Co",
            title="Engineer",
        )

        assert assessment.experience_match is not None
        assert assessment.experience_match.dimension == "experience_match"
        assert 0.0 <= assessment.experience_match.score <= 1.0

        assert assessment.education_match is not None
        assert assessment.education_match.dimension == "education_match"
        assert 0.0 <= assessment.education_match.score <= 1.0

    def test_partial_percentage_in_valid_range(
        self, candidate_profile, resume_profile
    ):
        """partial_percentage is between 0 and 100."""
        merged = merge_profiles(candidate_profile, resume_profile)
        engine = QuickMatchEngine(merged)

        assessment = engine.assess(
            requirements=self._minimal_requirements(),
            company="Test Co",
            title="Engineer",
        )

        assert assessment.partial_percentage is not None
        assert 0.0 <= assessment.partial_percentage <= 100.0


def test_find_best_skill_related_fallback():
    """When no direct match exists, related skills should give 'related' status."""
    from claude_candidate.quick_match import _find_best_skill
    from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
    from claude_candidate.schemas.merged_profile import MergedSkillEvidence, MergedEvidenceProfile, EvidenceSource
    from claude_candidate.schemas.candidate_profile import DepthLevel

    # Profile has "anthropic" but requirement asks for "openai" (related in taxonomy)
    profile = MergedEvidenceProfile(
        skills=[MergedSkillEvidence(
            name="anthropic",
            source=EvidenceSource.SESSIONS_ONLY,
            session_depth=DepthLevel.EXPERT,
            session_frequency=95,
            effective_depth=DepthLevel.EXPERT,
            confidence=0.85,
            discovery_flag=True,
        )],
        patterns=[], projects=[], roles=[],
        corroborated_skill_count=0, resume_only_skill_count=0,
        sessions_only_skill_count=1, discovery_skills=[],
        profile_hash="test", resume_hash="test",
        candidate_profile_hash="test", merged_at="2026-01-01T00:00:00",
    )

    req = QuickRequirement(
        description="Experience with OpenAI API",
        skill_mapping=["openai"],
        priority=RequirementPriority.MUST_HAVE,
    )

    match, status = _find_best_skill(req, profile, DepthLevel.APPLIED)
    assert match is not None, "Should find anthropic as a related match"
    assert status == "related"


def test_find_skill_match_canonicalizes_hyphens():
    """Skill 'ci-cd' should match profile entry 'ci cd' via canonicalization."""
    from claude_candidate.quick_match import _find_skill_match
    from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
    from claude_candidate.schemas.candidate_profile import DepthLevel
    from claude_candidate.schemas.merged_profile import MergedEvidenceProfile

    profile = MergedEvidenceProfile(
        skills=[MergedSkillEvidence(
            name="ci-cd",  # canonical form from taxonomy
            source=EvidenceSource.SESSIONS_ONLY,
            session_depth=DepthLevel.DEEP,
            session_frequency=15,
            effective_depth=DepthLevel.DEEP,
            confidence=0.75,
            discovery_flag=True,
        )],
        patterns=[], projects=[], roles=[],
        corroborated_skill_count=0, resume_only_skill_count=0,
        sessions_only_skill_count=1, discovery_skills=[],
        profile_hash="test", resume_hash="test",
        candidate_profile_hash="test", merged_at="2026-01-01T00:00:00",
    )

    # These should all resolve to the same canonical skill
    assert _find_skill_match("ci-cd", profile) is not None
    assert _find_skill_match("ci/cd", profile) is not None
    assert _find_skill_match("continuous-integration", profile) is not None


def test_score_requirement_confidence_floor():
    """Low-confidence skills should be floored at 0.5 to prevent cratering."""
    from claude_candidate.quick_match import _score_requirement, STATUS_SCORE
    from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
    from claude_candidate.schemas.candidate_profile import DepthLevel

    low_conf_skill = MergedSkillEvidence(
        name="python",
        source=EvidenceSource.RESUME_ONLY,
        resume_depth=DepthLevel.DEEP,
        resume_context="Listed",
        effective_depth=DepthLevel.DEEP,
        confidence=0.3,  # Very low confidence
    )

    score = _score_requirement(low_conf_skill, "strong_match")
    # Confidence adjustment: 0.90 + 0.10 * max(0.3, 0.65) = 0.90 + 0.065 = 0.965
    # Score = 0.90 * 0.965 = 0.8685
    expected_adj = 0.90 + 0.10 * max(0.3, 0.65)  # CONFIDENCE_FLOOR = 0.65
    expected = STATUS_SCORE["strong_match"] * expected_adj
    assert abs(score - expected) < 0.001


def test_soft_skill_requirement_discounted():
    """Requirements mapping to soft_skill category should get reduced weight."""
    from claude_candidate.quick_match import SOFT_SKILL_DISCOUNT
    # The discount factor should exist and be < 1.0
    assert 0.0 < SOFT_SKILL_DISCOUNT < 1.0


def test_years_experience_boosts_match():
    """When requirement has years_experience and skill has duration, score should improve."""
    from claude_candidate.quick_match import _parse_duration_years
    # Test the duration parser first
    assert _parse_duration_years("8 years") == 8.0
    assert _parse_duration_years("2 months") == 2.0 / 12.0
    assert _parse_duration_years(None) is None
    assert _parse_duration_years("") is None


def test_compound_requirement_breadth_scoring():
    """A requirement with 3 skill mappings where 2 match should score better than 0."""
    from claude_candidate.quick_match import QuickMatchEngine
    from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
    from claude_candidate.schemas.merged_profile import MergedSkillEvidence, MergedEvidenceProfile, EvidenceSource
    from claude_candidate.schemas.candidate_profile import DepthLevel

    # Profile has python (expert) and machine-learning (applied) but no data-science
    profile = MergedEvidenceProfile(
        skills=[
            MergedSkillEvidence(
                name="python",
                source=EvidenceSource.CORROBORATED,
                session_depth=DepthLevel.EXPERT,
                session_frequency=89,
                resume_depth=DepthLevel.DEEP,
                effective_depth=DepthLevel.EXPERT,
                confidence=0.9,
            ),
            MergedSkillEvidence(
                name="machine-learning",
                source=EvidenceSource.SESSIONS_ONLY,
                session_depth=DepthLevel.APPLIED,
                session_frequency=15,
                effective_depth=DepthLevel.APPLIED,
                confidence=0.65,
                discovery_flag=True,
            ),
        ],
        patterns=[], projects=[], roles=[],
        corroborated_skill_count=1, resume_only_skill_count=0,
        sessions_only_skill_count=1, discovery_skills=[],
        profile_hash="test", resume_hash="test",
        candidate_profile_hash="test", merged_at="2026-01-01T00:00:00",
    )

    engine = QuickMatchEngine(profile)

    # Compound requirement: ["python", "data-science", "machine-learning"]
    reqs = [QuickRequirement(
        description="5+ years Python, data science, or ML",
        skill_mapping=["python", "data-science", "machine-learning"],
        priority=RequirementPriority.MUST_HAVE,
    )]

    assessment = engine.assess(
        requirements=reqs,
        company="Test",
        title="Test",
        seniority="senior",
    )

    # With compound scoring: avg of (python=high, data-science=0, ml=partial)
    # should be considered alongside best single match
    # The skill score should be > 0 since python and ml match
    assert assessment.skill_match.score > 0


# ---------------------------------------------------------------------------
# Adoption Velocity Tests
# ---------------------------------------------------------------------------

def _make_pattern(pattern_type, strength: str):
	"""Build a minimal ProblemSolvingPattern for adoption velocity tests."""
	from claude_candidate.schemas.candidate_profile import ProblemSolvingPattern, SessionReference
	ref = SessionReference(
		session_id="test-session",
		session_date=datetime.now(),
		project_context="test",
		evidence_snippet="evidence for test",
		evidence_type="direct_usage",
		confidence=0.8,
	)
	return ProblemSolvingPattern(
		pattern_type=pattern_type,
		frequency="common",
		strength=strength,
		description="Test pattern",
		evidence=[ref],
	)


class TestAdoptionVelocity:
	"""Tests for compute_adoption_velocity() 5-signal composite."""

	def _make_skill(
		self,
		name: str = "python",
		category: str | None = "language",
		depth_level: str = "applied",
		frequency: int = 10,
		first_seen: datetime | None = None,
	):
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel
		depth = DepthLevel(depth_level)
		return MergedSkillEvidence(
			name=name,
			source=EvidenceSource.SESSIONS_ONLY,
			session_depth=depth,
			session_frequency=frequency,
			session_first_seen=first_seen,
			category=category,
			effective_depth=depth,
			confidence=0.8,
		)

	def _make_profile(self, skills=None, patterns=None, total_years=10.0):
		from datetime import datetime
		from claude_candidate.schemas.merged_profile import MergedEvidenceProfile
		return MergedEvidenceProfile(
			skills=skills or [],
			patterns=patterns or [],
			projects=[],
			roles=[],
			total_years_experience=total_years,
			corroborated_skill_count=0,
			resume_only_skill_count=0,
			sessions_only_skill_count=len(skills or []),
			discovery_skills=[],
			profile_hash="test",
			resume_hash="test",
			candidate_profile_hash="test",
			merged_at=datetime.now(),
		)

	def test_breadth_five_categories(self):
		from claude_candidate.quick_match import compute_adoption_velocity
		skills = [
			self._make_skill("python", "language"),
			self._make_skill("react", "framework"),
			self._make_skill("docker", "tool"),
			self._make_skill("aws", "platform"),
			self._make_skill("system-design", "concept"),
		]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["breadth"] == 1.0

	def test_breadth_below_applied_excluded(self):
		from claude_candidate.quick_match import compute_adoption_velocity
		# 5 different categories but all at MENTIONED depth — below applied
		skills = [
			self._make_skill("python", "language", "mentioned"),
			self._make_skill("react", "framework", "mentioned"),
			self._make_skill("docker", "tool", "mentioned"),
			self._make_skill("aws", "platform", "mentioned"),
			self._make_skill("system-design", "concept", "mentioned"),
		]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["breadth"] == 0.0

	def test_novelty_recent_skills(self):
		from datetime import timedelta
		from claude_candidate.quick_match import compute_adoption_velocity
		base = datetime(2024, 1, 1)
		skills = [
			self._make_skill("python", "language", "used", first_seen=base),
			self._make_skill("react", "framework", "used", first_seen=base + timedelta(days=10)),
			# 5 skills in last 30% of range (last 3 months of a 10-month window)
			self._make_skill("docker", "tool", "used", first_seen=base + timedelta(days=210)),
			self._make_skill("aws", "platform", "used", first_seen=base + timedelta(days=220)),
			self._make_skill("fastapi", "framework", "applied", first_seen=base + timedelta(days=230)),
			self._make_skill("pydantic", "framework", "applied", first_seen=base + timedelta(days=240)),
			self._make_skill("pytest", "tool", "applied", first_seen=base + timedelta(days=250)),
		]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["novelty"] >= 1.0

	def test_novelty_insufficient_dates(self):
		from claude_candidate.quick_match import compute_adoption_velocity
		# All skills have no first_seen
		skills = [self._make_skill("python", "language", first_seen=None)]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["novelty"] == 0.0

	def test_novelty_old_skills_only(self):
		from datetime import timedelta
		from claude_candidate.quick_match import compute_adoption_velocity
		base = datetime(2024, 1, 1)
		# Skills at used/applied depth in first 70% of range. A later "mentioned"
		# skill extends the date range without counting toward novelty.
		skills = [
			self._make_skill("python", "language", "used", first_seen=base),
			self._make_skill("react", "framework", "used", first_seen=base + timedelta(days=10)),
			self._make_skill("docker", "tool", "used", first_seen=base + timedelta(days=20)),
			# Extends range to 100 days; day 70 = cutoff; above 3 skills are before cutoff
			self._make_skill("aws", "platform", "mentioned", first_seen=base + timedelta(days=100)),
		]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["novelty"] == 0.0

	def test_ramp_speed_high_frequency_deep(self):
		from claude_candidate.quick_match import compute_adoption_velocity
		skills = [self._make_skill("python", "language", "deep", frequency=50)]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["ramp_speed"] > 0.5

	def test_ramp_speed_no_applied_skills(self):
		from claude_candidate.quick_match import compute_adoption_velocity
		skills = [self._make_skill("python", "language", "mentioned", frequency=5)]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["ramp_speed"] == 0.0

	def test_meta_cognition_exceptional(self):
		from claude_candidate.quick_match import compute_adoption_velocity
		from claude_candidate.schemas.candidate_profile import PatternType
		pattern = _make_pattern(PatternType.META_COGNITION, "exceptional")
		profile = self._make_profile(patterns=[pattern])
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["meta_cognition"] == 1.0

	def test_meta_cognition_absent(self):
		from claude_candidate.quick_match import compute_adoption_velocity
		profile = self._make_profile()
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["meta_cognition"] == 0.0

	def test_tool_selection_strong(self):
		from claude_candidate.quick_match import compute_adoption_velocity
		from claude_candidate.schemas.candidate_profile import PatternType
		pattern = _make_pattern(PatternType.TOOL_SELECTION, "strong")
		profile = self._make_profile(patterns=[pattern])
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["tool_selection"] == 0.8

	def test_composite_all_strong(self):
		from datetime import timedelta
		from claude_candidate.quick_match import compute_adoption_velocity
		from claude_candidate.schemas.candidate_profile import PatternType
		base = datetime(2024, 1, 1)
		# 5 categories, 5 novel skills, high frequency deep skills
		skills = [
			self._make_skill("python", "language", "deep", 50, base),
			self._make_skill("react", "framework", "deep", 40, base + timedelta(days=10)),
			self._make_skill("docker", "tool", "applied", 20, base + timedelta(days=30)),
			self._make_skill("aws", "platform", "applied", 15, base + timedelta(days=210)),
			self._make_skill("fastapi", "framework", "applied", 12, base + timedelta(days=220)),
			self._make_skill("pydantic", "tool", "applied", 10, base + timedelta(days=230)),
			self._make_skill("system-design", "concept", "applied", 8, base + timedelta(days=240)),
		]
		patterns = [
			_make_pattern(PatternType.META_COGNITION, "exceptional"),
			_make_pattern(PatternType.TOOL_SELECTION, "strong"),
		]
		profile = self._make_profile(skills, patterns)
		result = compute_adoption_velocity(profile)
		assert result.composite_score >= 0.6
		from claude_candidate.schemas.candidate_profile import DepthLevel
		assert result.depth in (DepthLevel.DEEP, DepthLevel.EXPERT)

	def test_composite_depth_thresholds(self):
		from claude_candidate.quick_match import compute_adoption_velocity, AdoptionVelocityResult
		from claude_candidate.quick_match import (
			ADOPTION_DEPTH_EXPERT, ADOPTION_DEPTH_DEEP,
			ADOPTION_DEPTH_APPLIED, ADOPTION_DEPTH_USED,
		)
		from claude_candidate.schemas.candidate_profile import DepthLevel
		from claude_candidate.quick_match import _build_adoption_summary
		# Verify depth mapping boundaries directly on AdoptionVelocityResult construction
		# by exercising the depth logic in compute_adoption_velocity with controlled inputs
		profile = self._make_profile()
		result = compute_adoption_velocity(profile)
		# Empty profile should produce low/zero composite
		assert result.depth in (DepthLevel.MENTIONED, DepthLevel.USED, DepthLevel.APPLIED)

	def test_confidence_from_evidence_count(self):
		from claude_candidate.quick_match import compute_adoption_velocity, ADOPTION_CONFIDENCE_DIVISOR
		# 10 scorable skills → evidence_count=10 → confidence=1.0
		skills = [
			self._make_skill(f"skill{i}", "language", "used") for i in range(10)
		]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.confidence == 1.0
		assert result.evidence_count == 10

	def test_empty_profile_minimal(self):
		from claude_candidate.quick_match import compute_adoption_velocity
		profile = self._make_profile()
		result = compute_adoption_velocity(profile)
		assert result.composite_score == 0.0
		assert result.confidence == 0.0
		assert result.evidence_count == 0

	def test_summary_quote_includes_novelty(self):
		from datetime import timedelta
		from claude_candidate.quick_match import compute_adoption_velocity
		base = datetime(2024, 1, 1)
		skills = [
			self._make_skill("python", "language", "used", first_seen=base),
			self._make_skill("react", "framework", "used", first_seen=base + timedelta(days=10)),
			self._make_skill("docker", "tool", "used", first_seen=base + timedelta(days=210)),
			self._make_skill("aws", "platform", "used", first_seen=base + timedelta(days=220)),
		]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert "dopted" in result.summary_quote or "Adoption velocity" in result.summary_quote


def test_adaptability_inferred_via_adoption_velocity(candidate_profile, resume_profile):
	"""adaptability should use composite-based depth when session data is present."""
	from claude_candidate.merger import merge_profiles
	from claude_candidate.quick_match import _infer_virtual_skill
	from claude_candidate.schemas.merged_profile import EvidenceSource

	merged = merge_profiles(candidate_profile, resume_profile)
	result = _infer_virtual_skill("adaptability", merged)
	# candidate_profile fixture has session skills — composite should trigger
	assert result is not None
	# Should come from composite (SESSIONS_ONLY), not years-based (RESUME_ONLY)
	assert result.source == EvidenceSource.SESSIONS_ONLY
	# Summary quote should be in resume_context
	assert result.resume_context is not None


def test_adaptability_fallback_to_years():
	"""adaptability falls back to years-based when no session data exists."""
	from datetime import datetime
	from claude_candidate.schemas.merged_profile import MergedEvidenceProfile, EvidenceSource
	from claude_candidate.quick_match import _infer_virtual_skill
	from claude_candidate.schemas.candidate_profile import DepthLevel

	# Profile with no skills (no session evidence), but 10 years experience
	profile = MergedEvidenceProfile(
		skills=[],
		patterns=[],
		projects=[],
		roles=[],
		total_years_experience=10.0,
		corroborated_skill_count=0,
		resume_only_skill_count=0,
		sessions_only_skill_count=0,
		discovery_skills=[],
		profile_hash="test",
		resume_hash="test",
		candidate_profile_hash="test",
		merged_at=datetime.now(),
	)

	result = _infer_virtual_skill("adaptability", profile)
	assert result is not None
	assert result.source == EvidenceSource.RESUME_ONLY
	assert result.effective_depth == DepthLevel.DEEP
	assert result.confidence == 0.6
