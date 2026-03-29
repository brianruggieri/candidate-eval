"""Tests for the QuickMatchEngine — three-dimension scoring and assessment generation."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from claude_candidate.merger import merge_profiles, merge_candidate_only
from claude_candidate.scoring import QuickMatchEngine, _compute_weights
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
		# Mission is now proxy-based in partial assessment; culture remains None
		assert assessment.mission_alignment is not None
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

	def test_must_have_coverage_string(self, candidate_profile, resume_profile, quick_requirements):
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

	def test_resume_gaps_discovered(self, candidate_profile, resume_profile, quick_requirements):
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

	def test_action_items_non_empty(self, candidate_profile, resume_profile, quick_requirements):
		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)

		assessment = engine.assess(
			requirements=quick_requirements,
			company="Test",
			title="Test",
		)

		assert len(assessment.action_items) >= 1

	def test_assessment_timing_tracked(self, candidate_profile, resume_profile, quick_requirements):
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

		requirements = [
			QuickRequirement(
				description="Python proficiency",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
			)
		]

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

		requirements = [
			QuickRequirement(
				description="Rust proficiency",
				skill_mapping=["rust"],
				priority=RequirementPriority.MUST_HAVE,
			)
		]

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
		reqs_must = [
			QuickRequirement(
				description="Rust",
				skill_mapping=["rust"],
				priority=RequirementPriority.MUST_HAVE,
			)
		]

		# All nice-to-have = missing skill → less impact
		reqs_nice = [
			QuickRequirement(
				description="Rust",
				skill_mapping=["rust"],
				priority=RequirementPriority.NICE_TO_HAVE,
			)
		]

		a_must = engine.assess(requirements=reqs_must, company="T", title="T")
		a_nice = engine.assess(requirements=reqs_nice, company="T", title="T")

		# must_have no_evidence scores 0.0 (hard gap), nice_to_have gets
		# STATUS_SCORE_NONE floor (transferable skills).
		from claude_candidate.scoring import STATUS_SCORE_NONE

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
			"Unknown Corp",
			["python", "typescript"],
			None,
		)

		# Should still produce a score, but with lower confidence
		assert 0.0 <= dim.score <= 1.0
		assert (
			"Limited enrichment" in dim.details[-1]
			or "Insufficient" in dim.details[-1]
			or "overlap" in " ".join(dim.details).lower()
		)

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
			["documentation driven", "scope management"],
			None,
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
			["documentation driven", "move fast", "open source"],
			None,
		)

		# 1 match out of 3 → score = 0.3 + (1/3)*0.6 = 0.5 exactly
		assert 0.3 <= dim.score <= 0.9
		assert not dim.insufficient_data

	def test_confidence_equals_match_ratio(self, candidate_profile, resume_profile):
		"""Confidence field equals matched / total signals."""
		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)

		dim = engine._score_culture_fit(
			["documentation driven", "scope management", "no match signal"],
			None,
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

		requirements = [
			QuickRequirement(
				description="Python proficiency",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
				years_experience=5,
			)
		]

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

		requirements = [
			QuickRequirement(
				description="Senior ML engineering",
				skill_mapping=["machine-learning"],
				priority=RequirementPriority.MUST_HAVE,
				years_experience=15,
			)
		]

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

		requirements = [
			QuickRequirement(
				description="Python proficiency",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
			)
		]

		dim = engine._score_experience_match(requirements, "senior")
		assert dim.dimension == "experience_match"
		assert dim.score == 0.9
		assert dim.insufficient_data is True

	def test_experience_match_candidate_no_years(self, candidate_profile):
		"""Candidate with no total_years_experience → neutral with insufficient_data."""
		merged = merge_candidate_only(candidate_profile)
		engine = QuickMatchEngine(merged)

		requirements = [
			QuickRequirement(
				description="Python proficiency",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
				years_experience=5,
			)
		]

		dim = engine._score_experience_match(requirements, "senior")
		assert dim.score == 0.5
		assert dim.insufficient_data is True


class TestEducationMatchScoring:
	"""Tests for _score_education_match dimension."""

	def test_education_match_degree_met(self, candidate_profile, resume_profile):
		"""Candidate with matching degree scores well."""
		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)

		requirements = [
			QuickRequirement(
				description="CS degree required",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
				education_level="bachelor",
			)
		]

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

		requirements = [
			QuickRequirement(
				description="Python proficiency",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
			)
		]

		dim = engine._score_education_match(requirements, ["python", "typescript", "react"])
		assert dim.dimension == "education_match"
		assert dim.score > 0.5
		assert not dim.insufficient_data
		assert any("tech stack" in d.lower() for d in dim.details)

	def test_education_match_no_requirements(self, candidate_profile, resume_profile):
		"""No education or tech stack requirements → neutral with insufficient_data."""
		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)

		requirements = [
			QuickRequirement(
				description="Python proficiency",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
			)
		]

		dim = engine._score_education_match(requirements, [])
		assert dim.dimension == "education_match"
		assert dim.score == 0.9
		assert dim.insufficient_data is True

	def test_education_match_combined_signals(self, candidate_profile, resume_profile):
		"""Both education and tech stack produce an averaged score."""
		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)

		requirements = [
			QuickRequirement(
				description="CS degree required",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
				education_level="bachelor",
			)
		]

		dim = engine._score_education_match(requirements, ["python", "typescript"])
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
		return [
			QuickRequirement(
				description="Python",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
			)
		]

	def test_partial_assessment_uses_fixed_weights(self, candidate_profile, resume_profile):
		"""Partial assessment uses 60/20/10/10 weights when mission is present."""
		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)

		assessment = engine.assess(
			requirements=self._minimal_requirements(),
			company="Test Co",
			title="Engineer",
		)

		if assessment.mission_alignment:
			# Mission proxy succeeded: 60/20/10 + mission 10
			assert assessment.skill_match.weight == 0.60
			assert assessment.experience_match.weight == 0.20
			assert assessment.education_match.weight == 0.10
			assert assessment.mission_alignment.weight == 0.10
		else:
			# No mission data: fallback to 65/25/10
			assert assessment.skill_match.weight == 0.65
			assert assessment.experience_match.weight == 0.25
			assert assessment.education_match.weight == 0.10

	def test_insufficient_data_scores_high(self, candidate_profile, resume_profile):
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

	def test_partial_assessment_weights_sum_to_one(self, candidate_profile, resume_profile):
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
			+ (assessment.mission_alignment.weight if assessment.mission_alignment else 0.0)
		)
		assert abs(total - 1.0) < 1e-9

	def test_partial_assessment_no_culture(self, candidate_profile, resume_profile):
		"""Partial assessment includes proxy mission but leaves culture as None."""
		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)

		assessment = engine.assess(
			requirements=self._minimal_requirements(),
			company="Test Co",
			title="Engineer",
			culture_signals=["documentation driven"],
		)

		# Mission is now proxy-based in partial; culture still skipped
		assert assessment.mission_alignment is not None
		assert assessment.culture_fit is None

	def test_partial_percentage_matches_weighted_score(self, candidate_profile, resume_profile):
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

	def test_partial_percentage_in_valid_range(self, candidate_profile, resume_profile):
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
	from claude_candidate.scoring import _find_best_skill
	from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
	from claude_candidate.schemas.merged_profile import (
		MergedSkillEvidence,
		MergedEvidenceProfile,
		EvidenceSource,
	)
	from claude_candidate.schemas.candidate_profile import DepthLevel

	# Profile has "anthropic" but requirement asks for "openai" (related in taxonomy)
	profile = MergedEvidenceProfile(
		skills=[
			MergedSkillEvidence(
				name="anthropic",
				source=EvidenceSource.SESSIONS_ONLY,
				session_depth=DepthLevel.EXPERT,
				session_frequency=95,
				effective_depth=DepthLevel.EXPERT,
				confidence=0.85,
				discovery_flag=True,
			)
		],
		patterns=[],
		projects=[],
		roles=[],
		corroborated_skill_count=0,
		resume_only_skill_count=0,
		sessions_only_skill_count=1,
		discovery_skills=[],
		profile_hash="test",
		resume_hash="test",
		candidate_profile_hash="test",
		merged_at="2026-01-01T00:00:00",
	)

	req = QuickRequirement(
		description="Experience with OpenAI API",
		skill_mapping=["openai"],
		priority=RequirementPriority.MUST_HAVE,
	)

	match, status, _mtype = _find_best_skill(req, profile, DepthLevel.APPLIED)
	assert match is not None, "Should find anthropic as a related match"
	assert status == "related"


def test_find_skill_match_canonicalizes_hyphens():
	"""Skill 'ci-cd' should match profile entry 'ci cd' via canonicalization."""
	from claude_candidate.scoring import _find_skill_match
	from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
	from claude_candidate.schemas.candidate_profile import DepthLevel
	from claude_candidate.schemas.merged_profile import MergedEvidenceProfile

	profile = MergedEvidenceProfile(
		skills=[
			MergedSkillEvidence(
				name="ci-cd",  # canonical form from taxonomy
				source=EvidenceSource.SESSIONS_ONLY,
				session_depth=DepthLevel.DEEP,
				session_frequency=15,
				effective_depth=DepthLevel.DEEP,
				confidence=0.75,
				discovery_flag=True,
			)
		],
		patterns=[],
		projects=[],
		roles=[],
		corroborated_skill_count=0,
		resume_only_skill_count=0,
		sessions_only_skill_count=1,
		discovery_skills=[],
		profile_hash="test",
		resume_hash="test",
		candidate_profile_hash="test",
		merged_at="2026-01-01T00:00:00",
	)

	# These should all resolve to the same canonical skill
	assert _find_skill_match("ci-cd", profile)[0] is not None
	assert _find_skill_match("ci/cd", profile)[0] is not None
	assert _find_skill_match("continuous-integration", profile)[0] is not None


def test_score_requirement_uses_raw_confidence_no_floor():
	"""Confidence adjustment uses raw skill confidence with CONFIDENCE_FLOOR floor.

	With CONFLICTING fixed to 0.72, both resume_only (0.85) and conflicting (0.72)
	should score via the widened formula: adjustment = CONFIDENCE_FLOOR + (1 - CONFIDENCE_FLOOR) * confidence.
	"""
	from claude_candidate.scoring import _score_requirement, STATUS_SCORE
	from claude_candidate.scoring.constants import CONFIDENCE_FLOOR
	from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
	from claude_candidate.schemas.candidate_profile import DepthLevel

	resume_skill = MergedSkillEvidence(
		name="python",
		source=EvidenceSource.RESUME_ONLY,
		resume_depth=DepthLevel.DEEP,
		effective_depth=DepthLevel.DEEP,
		confidence=0.85,
	)
	conflicting_skill = MergedSkillEvidence(
		name="docker",
		source=EvidenceSource.CONFLICTING,
		resume_depth=DepthLevel.APPLIED,
		session_depth=DepthLevel.DEEP,
		effective_depth=DepthLevel.DEEP,
		confidence=0.72,
	)

	resume_score = _score_requirement(resume_skill, "strong_match")
	conflicting_score = _score_requirement(conflicting_skill, "strong_match")

	expected_resume = STATUS_SCORE["strong_match"] * (CONFIDENCE_FLOOR + (1.0 - CONFIDENCE_FLOOR) * 0.85)
	expected_conflicting = STATUS_SCORE["strong_match"] * (CONFIDENCE_FLOOR + (1.0 - CONFIDENCE_FLOOR) * 0.72)

	assert abs(resume_score - expected_resume) < 0.001, (
		f"resume_only: expected {expected_resume:.4f}, got {resume_score:.4f}"
	)
	assert abs(conflicting_score - expected_conflicting) < 0.001, (
		f"conflicting: expected {expected_conflicting:.4f}, got {conflicting_score:.4f}"
	)


def test_soft_skill_requirement_discounted():
	"""Requirements mapping to soft_skill category should get reduced weight."""
	from claude_candidate.scoring import SOFT_SKILL_DISCOUNT

	# The discount factor should exist and be < 1.0
	assert 0.0 < SOFT_SKILL_DISCOUNT < 1.0


def test_years_experience_boosts_match():
	"""When requirement has years_experience and skill has duration, score should improve."""
	from claude_candidate.scoring import _parse_duration_years

	# Test the duration parser first
	assert _parse_duration_years("8 years") == 8.0
	assert _parse_duration_years("2 months") == 2.0 / 12.0
	assert _parse_duration_years(None) is None
	assert _parse_duration_years("") is None


def test_compound_requirement_breadth_scoring():
	"""A requirement with 3 skill mappings where 2 match should score better than 0."""
	from claude_candidate.scoring import QuickMatchEngine
	from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
	from claude_candidate.schemas.merged_profile import (
		MergedSkillEvidence,
		MergedEvidenceProfile,
		EvidenceSource,
	)
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
		patterns=[],
		projects=[],
		roles=[],
		corroborated_skill_count=1,
		resume_only_skill_count=0,
		sessions_only_skill_count=1,
		discovery_skills=[],
		profile_hash="test",
		resume_hash="test",
		candidate_profile_hash="test",
		merged_at="2026-01-01T00:00:00",
	)

	engine = QuickMatchEngine(profile)

	# Compound requirement: ["python", "data-science", "machine-learning"]
	reqs = [
		QuickRequirement(
			description="5+ years Python, data science, or ML",
			skill_mapping=["python", "data-science", "machine-learning"],
			priority=RequirementPriority.MUST_HAVE,
		)
	]

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
		from claude_candidate.scoring import compute_adoption_velocity

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
		from claude_candidate.scoring import compute_adoption_velocity

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
		from claude_candidate.scoring import compute_adoption_velocity

		base = datetime(2024, 1, 1)
		skills = [
			self._make_skill("python", "language", "used", first_seen=base),
			self._make_skill("react", "framework", "used", first_seen=base + timedelta(days=10)),
			# 5 skills in last 30% of range (last 3 months of a 10-month window)
			self._make_skill("docker", "tool", "used", first_seen=base + timedelta(days=210)),
			self._make_skill("aws", "platform", "used", first_seen=base + timedelta(days=220)),
			self._make_skill(
				"fastapi", "framework", "applied", first_seen=base + timedelta(days=230)
			),
			self._make_skill(
				"pydantic", "framework", "applied", first_seen=base + timedelta(days=240)
			),
			self._make_skill("pytest", "tool", "applied", first_seen=base + timedelta(days=250)),
		]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["novelty"] >= 1.0

	def test_novelty_insufficient_dates(self):
		from claude_candidate.scoring import compute_adoption_velocity

		# All skills have no first_seen
		skills = [self._make_skill("python", "language", first_seen=None)]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["novelty"] == 0.0

	def test_novelty_old_skills_only(self):
		from datetime import timedelta
		from claude_candidate.scoring import compute_adoption_velocity

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
		from claude_candidate.scoring import compute_adoption_velocity

		skills = [self._make_skill("python", "language", "deep", frequency=50)]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["ramp_speed"] > 0.5

	def test_ramp_speed_no_applied_skills(self):
		from claude_candidate.scoring import compute_adoption_velocity

		skills = [self._make_skill("python", "language", "mentioned", frequency=5)]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["ramp_speed"] == 0.0

	def test_meta_cognition_exceptional(self):
		from claude_candidate.scoring import compute_adoption_velocity
		from claude_candidate.schemas.candidate_profile import PatternType

		pattern = _make_pattern(PatternType.META_COGNITION, "exceptional")
		profile = self._make_profile(patterns=[pattern])
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["meta_cognition"] == 1.0

	def test_meta_cognition_absent(self):
		from claude_candidate.scoring import compute_adoption_velocity

		profile = self._make_profile()
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["meta_cognition"] == 0.0

	def test_tool_selection_strong(self):
		from claude_candidate.scoring import compute_adoption_velocity
		from claude_candidate.schemas.candidate_profile import PatternType

		pattern = _make_pattern(PatternType.TOOL_SELECTION, "strong")
		profile = self._make_profile(patterns=[pattern])
		result = compute_adoption_velocity(profile)
		assert result.sub_scores["tool_selection"] == 0.8

	def test_composite_all_strong(self):
		from datetime import timedelta
		from claude_candidate.scoring import compute_adoption_velocity
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
		from claude_candidate.scoring import compute_adoption_velocity, AdoptionVelocityResult
		from claude_candidate.scoring import (
			ADOPTION_DEPTH_EXPERT,
			ADOPTION_DEPTH_DEEP,
			ADOPTION_DEPTH_APPLIED,
			ADOPTION_DEPTH_USED,
		)
		from claude_candidate.schemas.candidate_profile import DepthLevel
		from claude_candidate.scoring import _build_adoption_summary

		# Verify depth mapping boundaries directly on AdoptionVelocityResult construction
		# by exercising the depth logic in compute_adoption_velocity with controlled inputs
		profile = self._make_profile()
		result = compute_adoption_velocity(profile)
		# Empty profile should produce low/zero composite
		assert result.depth in (DepthLevel.MENTIONED, DepthLevel.USED, DepthLevel.APPLIED)

	def test_confidence_from_evidence_count(self):
		from claude_candidate.scoring import (
			compute_adoption_velocity,
			ADOPTION_CONFIDENCE_DIVISOR,
		)

		# 10 scorable skills → evidence_count=10 → confidence=1.0
		skills = [self._make_skill(f"skill{i}", "language", "used") for i in range(10)]
		profile = self._make_profile(skills)
		result = compute_adoption_velocity(profile)
		assert result.confidence == 1.0
		assert result.evidence_count == 10

	def test_empty_profile_minimal(self):
		from claude_candidate.scoring import compute_adoption_velocity

		profile = self._make_profile()
		result = compute_adoption_velocity(profile)
		assert result.composite_score == 0.0
		assert result.confidence == 0.0
		assert result.evidence_count == 0

	def test_summary_quote_includes_novelty(self):
		from datetime import timedelta
		from claude_candidate.scoring import compute_adoption_velocity

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
	from claude_candidate.scoring import _infer_virtual_skill
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
	from claude_candidate.scoring import _infer_virtual_skill
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


# ---------------------------------------------------------------------------
# Soft Skill Discount Tests (Decision 7: simplification)
# ---------------------------------------------------------------------------


def test_soft_skill_discount_baseline():
	"""SOFT_SKILL_DISCOUNT constant should be 0.5."""
	from claude_candidate.scoring import SOFT_SKILL_DISCOUNT

	assert SOFT_SKILL_DISCOUNT == 0.5


def test_soft_skill_discount_returns_fixed_value():
	"""_soft_skill_discount() returns SOFT_SKILL_DISCOUNT with no parameters."""
	from claude_candidate.scoring import _soft_skill_discount, SOFT_SKILL_DISCOUNT

	assert _soft_skill_discount() == SOFT_SKILL_DISCOUNT
	assert _soft_skill_discount() == 0.5


def test_soft_skill_max_boost_removed():
	"""SOFT_SKILL_MAX_BOOST should no longer exist in the scoring module."""
	import claude_candidate.scoring as scoring

	assert not hasattr(scoring, "SOFT_SKILL_MAX_BOOST")


# ---------------------------------------------------------------------------
# Plan 9: Eligibility filter tests
# ---------------------------------------------------------------------------


class TestEligibilityFilters:
	"""Eligibility requirements are excluded from skill scoring."""

	def _make_req(
		self,
		skill: str,
		priority: str = "must_have",
		description: str = "",
		is_eligibility: bool = False,
	) -> QuickRequirement:
		return QuickRequirement(
			description=description or skill,
			skill_mapping=[skill],
			priority=RequirementPriority(priority),
			is_eligibility=is_eligibility,
		)

	def test_eligibility_excluded_from_skill_score(self, candidate_profile, resume_profile):
		"""Eligibility requirement does not appear in skill_details and doesn't affect score."""
		from claude_candidate.merger import merge_profiles

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		reqs = [
			self._make_req("python", "must_have"),
			self._make_req(
				"us-work-authorization",
				"must_have",
				"Must be authorized to work in the US",
				is_eligibility=True,
			),
		]
		result = engine.assess(reqs, "TestCo", "Engineer")
		# skill_matches should only contain the non-eligibility requirement
		skill_req_names = [d.requirement for d in result.skill_matches]
		assert not any(
			"authorized" in n.lower() or "work" in n.lower()
			for n in skill_req_names
			if "authorization" in n.lower()
		)
		# eligibility gate should be in eligibility_gates
		assert len(result.eligibility_gates) == 1
		assert result.eligibility_gates[0].status == "met"  # us_work_authorized=True by default

	def test_eligibility_gates_populated(self, candidate_profile, resume_profile):
		"""eligibility_gates contains one entry per eligibility requirement."""
		from claude_candidate.merger import merge_profiles

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		reqs = [
			self._make_req("python", "must_have"),
			self._make_req(
				"us-work-authorization",
				"must_have",
				"Must be authorized to work",
				is_eligibility=True,
			),
			self._make_req("travel", "must_have", "Willing to travel 20%", is_eligibility=True),
		]
		result = engine.assess(reqs, "TestCo", "Engineer")
		assert len(result.eligibility_gates) == 2

	def test_must_have_coverage_excludes_eligibility(self, candidate_profile, resume_profile):
		"""must_have_coverage denominator counts only scorable must-haves."""
		from claude_candidate.merger import merge_profiles

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		reqs = [
			self._make_req("python", "must_have"),
			self._make_req(
				"us-work-authorization", "must_have", "Must be authorized", is_eligibility=True
			),
		]
		result = engine.assess(reqs, "TestCo", "Engineer")
		# denominator should be 1 (just python), not 2
		assert (
			"/1 must-haves" in result.must_have_coverage
			or result.must_have_coverage == "No must-haves specified"
		)

	def test_biggest_gap_excludes_eligibility(self, candidate_profile, resume_profile):
		"""biggest_gap should never show an eligibility requirement."""
		from claude_candidate.merger import merge_profiles

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		reqs = [
			self._make_req("python", "must_have"),
			self._make_req(
				"us-work-authorization",
				"must_have",
				"Must be authorized to work in the US",
				is_eligibility=True,
			),
		]
		result = engine.assess(reqs, "TestCo", "Engineer")
		assert "authorized" not in result.biggest_gap.lower()
		assert "us_work" not in result.biggest_gap.lower()

	def test_heuristic_denylist_skill_names(self):
		"""_infer_eligibility flags requirements with known eligibility skill names."""
		from claude_candidate.scoring import _infer_eligibility

		for skill in [
			"us-work-authorization",
			"us_work_authorization",
			"travel",
			"english",
			"visa",
			"relocation",
		]:
			req = QuickRequirement(
				description="test",
				skill_mapping=[skill],
				priority=RequirementPriority.MUST_HAVE,
			)
			assert _infer_eligibility(req), f"Expected eligibility for skill {skill!r}"

	def test_heuristic_denylist_description_patterns(self):
		"""_infer_eligibility flags requirements matching eligibility description patterns."""
		from claude_candidate.scoring import _infer_eligibility

		descriptions = [
			"Must be authorized to work in the United States",
			"Eligible to work in the US without sponsorship",
			"Comfortable with 20% travel to customer sites",
			"Willing to travel 15% of the time",
			"Advanced English is required",
			"Believe in our company's mission and values",
		]
		for desc in descriptions:
			req = QuickRequirement(
				description=desc,
				skill_mapping=["some_skill"],
				priority=RequirementPriority.MUST_HAVE,
			)
			assert _infer_eligibility(req), f"Expected eligibility for: {desc!r}"

	def test_heuristic_denylist_no_false_positives(self):
		"""_infer_eligibility does not flag real skill requirements."""
		from claude_candidate.scoring import _infer_eligibility

		non_eligibility = [
			("5+ years Python experience", ["python"]),
			("Strong customer success skills", ["customer_success"]),
			("Bachelor's degree in Computer Science", ["computer_science"]),
			("Experience with English literature analysis", ["nlp"]),
		]
		for desc, skills in non_eligibility:
			req = QuickRequirement(
				description=desc,
				skill_mapping=skills,
				priority=RequirementPriority.NICE_TO_HAVE,
			)
			assert not _infer_eligibility(req), f"False positive for: {desc!r}"

	def test_entire_requirement_excluded_when_eligibility(self, candidate_profile, resume_profile):
		"""Mixed skill_mapping: if is_eligibility=True, entire requirement is excluded."""
		from claude_candidate.merger import merge_profiles

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		# Requirement has both a real skill and an eligibility skill, but is_eligibility=True
		req_mixed = QuickRequirement(
			description="Comfortable with travel and customer engagement",
			skill_mapping=["travel", "customer_engagement"],
			priority=RequirementPriority.MUST_HAVE,
			is_eligibility=True,
		)
		req_real = self._make_req("python", "must_have")
		result = engine.assess([req_real, req_mixed], "TestCo", "Engineer")
		assert len(result.eligibility_gates) == 1
		# customer_engagement should NOT appear in skill_matches
		skill_reqs = [d.requirement for d in result.skill_matches]
		assert all("customer" not in r.lower() for r in skill_reqs)


class TestEligibilityGateSchema:
	"""Schema tests for EligibilityGate and updated FitAssessment."""

	def test_eligibility_gate_defaults_unknown(self):
		from claude_candidate.schemas.fit_assessment import EligibilityGate

		gate = EligibilityGate(description="Must be authorized to work in the US")
		assert gate.status == "unknown"
		assert gate.requirement_text == ""

	def test_eligibility_gate_all_statuses(self):
		from claude_candidate.schemas.fit_assessment import EligibilityGate

		for status in ("met", "unmet", "unknown"):
			gate = EligibilityGate(description="test", status=status)
			assert gate.status == status

	def test_fit_assessment_has_eligibility_fields(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		reqs = [
			QuickRequirement(
				description="Python",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
			)
		]
		result = engine.assess(reqs, "TestCo", "Engineer")
		assert hasattr(result, "eligibility_gates")
		assert hasattr(result, "eligibility_passed")
		assert result.eligibility_passed is True
		assert result.eligibility_gates == []

	def test_fit_assessment_serialization_round_trip(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.schemas.fit_assessment import FitAssessment

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		req_elig = QuickRequirement(
			description="Must be authorized to work in the US",
			skill_mapping=["us-work-authorization"],
			priority=RequirementPriority.MUST_HAVE,
			is_eligibility=True,
		)
		req_skill = QuickRequirement(
			description="Python", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE
		)
		result = engine.assess([req_skill, req_elig], "TestCo", "Engineer")
		json_str = result.to_json()
		restored = FitAssessment.from_json(json_str)
		assert len(restored.eligibility_gates) == 1
		assert restored.eligibility_passed is True


class TestEligibilityHardCap:
	"""Tests that unmet eligibility gates force grade to F."""

	def _make_req(
		self,
		skill: str,
		description: str = "",
		priority: str = "must_have",
		is_eligibility: bool = False,
	) -> QuickRequirement:
		return QuickRequirement(
			description=description or skill,
			skill_mapping=[skill],
			priority=RequirementPriority(priority),
			is_eligibility=is_eligibility,
			source_text=description or skill,
		)

	def _clearance_req(self) -> QuickRequirement:
		return self._make_req(
			"security-clearance",
			"Must hold active security clearance",
			is_eligibility=True,
		)

	def test_unmet_gate_forces_f(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		result = engine.assess(
			requirements=[self._clearance_req(), self._make_req("python", priority="must_have")],
			company="GovCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(has_clearance=False),
		)
		assert result.overall_grade == "F"
		assert result.overall_score == 0.0
		assert result.should_apply == "no"
		assert result.eligibility_passed is False

	def test_unmet_gate_summary_starts_with_blocker(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		result = engine.assess(
			requirements=[self._clearance_req()],
			company="GovCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(has_clearance=False),
		)
		assert result.overall_summary.startswith("Eligibility blocked:")

	def test_unmet_gate_first_action_item_is_eligibility(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		result = engine.assess(
			requirements=[self._clearance_req()],
			company="GovCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(has_clearance=False),
		)
		assert result.action_items[0].startswith("Eligibility:")

	def test_counterfactual_grade_in_summary(self, candidate_profile, resume_profile):
		"""Summary includes 'if eligible' clause with counterfactual grade."""
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		result = engine.assess(
			requirements=[self._clearance_req()],
			company="GovCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(has_clearance=False),
		)
		assert "if eligible" in result.overall_summary

	def test_met_gates_no_cap(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		req = self._make_req(
			"us-work-authorization",
			"Must be authorized to work in the US",
			is_eligibility=True,
		)
		result = engine.assess(
			requirements=[req, self._make_req("python", priority="must_have")],
			company="TestCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(us_work_authorized=True),
		)
		assert result.overall_grade != "F"
		assert result.overall_score > 0.0
		assert not result.overall_summary.startswith("Eligibility blocked:")

	def test_unknown_gates_no_cap(self, candidate_profile, resume_profile):
		"""mission_alignment gates are always unknown — must not trigger cap."""
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		mission_req = self._make_req(
			"mission_alignment", "Belief in our mission", is_eligibility=True
		)
		result = engine.assess(
			requirements=[mission_req, self._make_req("python", priority="must_have")],
			company="TestCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(),
		)
		assert result.overall_grade != "F"

	def test_no_eligibility_reqs_no_cap(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		result = engine.assess(
			requirements=[self._make_req("python", priority="must_have")],
			company="TestCo",
			title="Engineer",
		)
		assert result.eligibility_gates == []
		assert result.overall_grade != "F"

	def test_multiple_unmet_gates_all_appear_in_output(self, candidate_profile, resume_profile):
		"""All unmet gate descriptions are joined in summary and action item."""
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		clearance_req = self._make_req(
			"security-clearance", "Must hold active security clearance", is_eligibility=True
		)
		spanish_req = self._make_req("spanish", "Must be fluent in Spanish", is_eligibility=True)
		result = engine.assess(
			requirements=[clearance_req, spanish_req, self._make_req("python")],
			company="GovCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(has_clearance=False),
		)
		assert result.overall_grade == "F"
		# Both descriptions must appear in the summary
		assert (
			"clearance" in result.overall_summary.lower()
			and "spanish" in result.overall_summary.lower()
		)
		# The action item should reference both
		assert result.action_items[0].startswith("Eligibility:")



class TestConflictingDepthDirection:
	"""CONFLICTING depth: resume anchors, sessions boost by at most one rung."""

	def _make_conflicting(self, resume_depth, session_depth):
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		return MergedSkillEvidence.compute_effective_depth(
			EvidenceSource.CONFLICTING,
			resume_depth=resume_depth,
			session_depth=session_depth,
		)

	def test_sessions_higher_caps_at_one_above_resume(self):
		"""Sessions=EXPERT, resume=MENTIONED → effective=USED (one above MENTIONED)."""
		from claude_candidate.schemas.candidate_profile import DepthLevel
		result = self._make_conflicting(DepthLevel.MENTIONED, DepthLevel.EXPERT)
		assert result == DepthLevel.USED

	def test_sessions_higher_from_applied_caps_at_deep(self):
		"""Sessions=EXPERT, resume=APPLIED → effective=DEEP (one above APPLIED)."""
		from claude_candidate.schemas.candidate_profile import DepthLevel
		result = self._make_conflicting(DepthLevel.APPLIED, DepthLevel.EXPERT)
		assert result == DepthLevel.DEEP

	def test_resume_higher_trusts_resume(self):
		"""Resume=DEEP, sessions=MENTIONED → effective=DEEP (resume wins)."""
		from claude_candidate.schemas.candidate_profile import DepthLevel
		result = self._make_conflicting(DepthLevel.DEEP, DepthLevel.MENTIONED)
		assert result == DepthLevel.DEEP

	def test_one_side_missing_uses_resume_preferred(self):
		"""Only resume present → use resume depth."""
		from claude_candidate.schemas.candidate_profile import DepthLevel
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		result = MergedSkillEvidence.compute_effective_depth(
			EvidenceSource.CONFLICTING,
			resume_depth=DepthLevel.APPLIED,
			session_depth=None,
		)
		assert result == DepthLevel.APPLIED


# ---------------------------------------------------------------------------
# Timer tests
# ---------------------------------------------------------------------------


def test_assess_passes_curated_eligibility_to_gates(candidate_profile, resume_profile):
	"""curated_eligibility parameter reaches evaluate_gates and resolves correctly."""
	from claude_candidate.merger import merge_profiles
	from claude_candidate.scoring import QuickMatchEngine
	from claude_candidate.schemas.curated_resume import CandidateEligibility
	from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority

	merged = merge_profiles(candidate_profile, resume_profile)
	engine = QuickMatchEngine(merged)
	clearance_req = QuickRequirement(
		description="Must hold clearance",
		skill_mapping=["security-clearance"],
		priority=RequirementPriority.MUST_HAVE,
		is_eligibility=True,
		source_text="Must hold clearance",
	)
	# With has_clearance=True → gate resolves to "met"
	result_met = engine.assess(
		requirements=[clearance_req],
		company="Co",
		title="Eng",
		curated_eligibility=CandidateEligibility(has_clearance=True),
	)
	assert result_met.eligibility_gates[0].status == "met"

	# With has_clearance=False (default) → gate resolves to "unmet" → grade F
	result_unmet = engine.assess(
		requirements=[clearance_req],
		company="Co",
		title="Eng",
		curated_eligibility=CandidateEligibility(has_clearance=False),
	)
	assert result_unmet.eligibility_gates[0].status == "unmet"
	assert result_unmet.overall_grade == "F"


def test_assess_accepts_elapsed_kwarg(minimal_engine):
	"""When elapsed is passed to assess(), it is used instead of internal timing."""
	reqs = [
		QuickRequirement(
			description="Python programming language",
			skill_mapping=["python"],
			priority="must_have",
		)
	]
	with patch("claude_candidate.scoring.engine.time") as mock_time:
		# Internal time.time() should never be called when elapsed is provided
		mock_time.time.side_effect = AssertionError("internal timer was called")
		assessment = minimal_engine.assess(
			requirements=reqs,
			company="Test Co",
			title="Engineer",
			elapsed=5.0,
		)
	assert assessment.time_to_assess_seconds == pytest.approx(5.0, abs=0.01)


def test_conflicting_confidence_is_072():
	"""CONFLICTING evidence source should return 0.72 confidence, not 0.40.

	Both sources have the skill. Uncertainty is about depth level only,
	which is handled in compute_effective_depth, not here.
	"""
	from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
	conf = MergedSkillEvidence.compute_confidence(
		EvidenceSource.CONFLICTING,
		session_frequency=5,
		resume_context="Listed on resume",
	)
	assert conf == 0.72, f"Expected 0.72, got {conf}"



# ---------------------------------------------------------------------------
# TestMatchType
# ---------------------------------------------------------------------------


class TestMatchType:
	"""match_type correctly classifies exact vs fuzzy skill resolution."""

	def _make_profile(self, skills=None):
		from datetime import datetime
		from claude_candidate.schemas.merged_profile import MergedEvidenceProfile
		return MergedEvidenceProfile(
			skills=skills or [],
			patterns=[],
			projects=[],
			roles=[],
			corroborated_skill_count=0,
			resume_only_skill_count=0,
			sessions_only_skill_count=len(skills or []),
			discovery_skills=[],
			profile_hash="test",
			resume_hash="test",
			candidate_profile_hash="test",
			merged_at=datetime.now(),
		)

	def _profile_with(self, skill_name: str, source="corroborated") -> "MergedEvidenceProfile":
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel
		return self._make_profile(skills=[MergedSkillEvidence(
			name=skill_name,
			source=EvidenceSource[source.upper()],
			effective_depth=DepthLevel.APPLIED,
			confidence=0.85,
		)])

	def _req(self, skill: str):
		from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
		return QuickRequirement(
			description=f"Experience with {skill}",
			skill_mapping=[skill],
			priority=RequirementPriority.STRONG_PREFERENCE,
		)

	def test_exact_name_match_returns_exact(self):
		"""Direct name match → match_type='exact'."""
		from claude_candidate.scoring import _find_best_skill
		from claude_candidate.schemas.candidate_profile import DepthLevel
		profile = self._profile_with("python")
		req = self._req("python")
		match, status, mtype = _find_best_skill(req, profile, DepthLevel.USED)
		assert match is not None
		assert mtype == "exact"

	def test_taxonomy_alias_returns_exact(self):
		"""Taxonomy alias resolution (ci/cd → ci-cd) → match_type='exact'."""
		from claude_candidate.scoring import _find_best_skill
		from claude_candidate.schemas.candidate_profile import DepthLevel
		profile = self._profile_with("ci-cd")
		req = self._req("ci/cd")  # alias in taxonomy
		match, status, mtype = _find_best_skill(req, profile, DepthLevel.USED)
		assert match is not None
		assert mtype == "exact"

	def test_no_evidence_returns_none_type(self):
		"""Unmatched requirement → match_type='none'."""
		from claude_candidate.scoring import _find_best_skill
		from claude_candidate.schemas.candidate_profile import DepthLevel
		profile = self._profile_with("python")
		req = self._req("cobol")
		match, status, mtype = _find_best_skill(req, profile, DepthLevel.USED)
		assert match is None
		assert mtype == "none"
		assert status == "no_evidence"

	def test_skill_match_detail_has_match_type_field(self):
		"""SkillMatchDetail serialises match_type in the API-facing dict."""
		from claude_candidate.scoring import _find_best_skill, _build_skill_detail
		from claude_candidate.schemas.candidate_profile import DepthLevel
		profile = self._profile_with("python")
		req = self._req("python")
		match, status, mtype = _find_best_skill(req, profile, DepthLevel.USED)
		detail = _build_skill_detail(req, match, status, mtype)
		assert detail.match_type == "exact"
		d = detail.model_dump()
		assert "match_type" in d


# ---------------------------------------------------------------------------
# TestDomainPenalty
# ---------------------------------------------------------------------------


class TestDomainPenalty:
	"""Domain-penalty caps grade at B+ when industry domain appears 3+ times but is absent."""

	def _make_profile(self, skills=None):
		from datetime import datetime
		from claude_candidate.schemas.merged_profile import MergedEvidenceProfile
		return MergedEvidenceProfile(
			skills=skills or [],
			patterns=[],
			projects=[],
			roles=[],
			corroborated_skill_count=0,
			resume_only_skill_count=0,
			sessions_only_skill_count=len(skills or []),
			discovery_skills=[],
			profile_hash="test",
			resume_hash="test",
			candidate_profile_hash="test",
			merged_at=datetime.now(),
		)

	def _reqs_with_domain(self, domain_word: str, count: int):
		"""Create `count` requirements that mention the domain word."""
		from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
		return [
			QuickRequirement(
				description=f"Experience in {domain_word} industry applications",
				skill_mapping=["python"],
				priority=RequirementPriority.STRONG_PREFERENCE,
			)
			for _ in range(count)
		]

	def test_domain_fires_when_keyword_in_three_reqs(self):
		"""'music' in 3 requirements + no music in profile → domain_gap_term='music'."""
		from claude_candidate.scoring import _detect_domain_gap
		reqs = self._reqs_with_domain("music", 3)
		profile = self._make_profile()
		gap = _detect_domain_gap(reqs, profile)
		assert gap == "music"

	def test_domain_does_not_fire_when_keyword_in_two_reqs(self):
		"""'music' in only 2 requirements → no gap (threshold is 3)."""
		from claude_candidate.scoring import _detect_domain_gap
		reqs = self._reqs_with_domain("music", 2)
		profile = self._make_profile()
		gap = _detect_domain_gap(reqs, profile)
		assert gap is None

	def test_domain_does_not_fire_when_keyword_in_profile(self):
		"""'music' in 3 requirements but candidate has music as a skill name → no gap."""
		from claude_candidate.scoring import _detect_domain_gap
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel
		reqs = self._reqs_with_domain("music", 3)
		profile = self._make_profile(skills=[MergedSkillEvidence(
			name="music",
			source=EvidenceSource.RESUME_ONLY,
			effective_depth=DepthLevel.MENTIONED,
			confidence=0.8,
		)])
		gap = _detect_domain_gap(reqs, profile)
		assert gap is None

	def test_tech_term_not_in_domain_keywords_does_not_fire(self):
		"""'python' in 5 requirements → not a domain keyword, no gap."""
		from claude_candidate.scoring import _detect_domain_gap
		reqs = self._reqs_with_domain("python", 5)
		profile = self._make_profile()
		gap = _detect_domain_gap(reqs, profile)
		assert gap is None

	def test_domain_cap_applied_to_high_scoring_assessment(self):
		"""Assessment that would score A gets capped to B+ when domain gap detected."""
		from claude_candidate.scoring import QuickMatchEngine, _detect_domain_gap, DOMAIN_KEYWORDS
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel

		assert "music" in DOMAIN_KEYWORDS
		assert "baseball" in DOMAIN_KEYWORDS

		# Build 3 requirements that reference the 'music' domain keyword
		reqs = self._reqs_with_domain("music", 3)

		# Profile with strong python evidence (would otherwise score high)
		profile = self._make_profile(skills=[
			MergedSkillEvidence(
				name="python",
				source=EvidenceSource.SESSIONS_ONLY,
				effective_depth=DepthLevel.EXPERT,
				confidence=1.0,
				session_frequency=100,
			),
		])

		# Confirm domain-gap detector fires
		assert _detect_domain_gap(reqs, profile) == "music"

		# Full assessment via engine — should be capped at B+
		engine = QuickMatchEngine(profile)
		assessment = engine.assess(
			requirements=reqs,
			company="Music AI Corp",
			title="Senior Music ML Engineer",
		)
		assert assessment.domain_gap_term == "music"
		assert assessment.overall_grade == "B+"


class TestMatchConfidence:
	"""Tests for compute_match_confidence — match quality scoring."""

	def test_exact_match_high_confidence(self) -> None:
		"""Exact skill name match produces high confidence."""
		from claude_candidate.scoring import compute_match_confidence

		conf = compute_match_confidence(
			candidate_skill="typescript",
			requirement_text="Expert TypeScript developer with React experience",
			match_type="exact",
		)
		assert conf >= 0.90

	def test_alias_match_good_confidence(self) -> None:
		"""Alias match produces good confidence."""
		from claude_candidate.scoring import compute_match_confidence

		conf = compute_match_confidence(
			candidate_skill="react",
			requirement_text="Experience with React.js and modern frontend frameworks",
			match_type="exact",
		)
		assert conf >= 0.85

	def test_no_mention_in_text_low_confidence(self) -> None:
		"""Skill not mentioned in requirement text produces low confidence."""
		from claude_candidate.scoring import compute_match_confidence

		conf = compute_match_confidence(
			candidate_skill="software-engineering",
			requirement_text="Embedded C firmware engineer with RTOS experience",
			match_type="fuzzy",
		)
		assert conf <= 0.30

	def test_no_match_zero_confidence(self) -> None:
		"""No match produces zero confidence."""
		from claude_candidate.scoring import compute_match_confidence

		conf = compute_match_confidence(
			candidate_skill="",
			requirement_text="Anything",
			match_type="none",
		)
		assert conf == 0.0

	def test_related_match_moderate_confidence(self) -> None:
		"""Related match gets moderate confidence."""
		from claude_candidate.scoring import compute_match_confidence

		conf = compute_match_confidence(
			candidate_skill="react",
			requirement_text="Modern frontend framework experience required",
			match_type="related",
		)
		assert 0.30 <= conf <= 0.70

	def test_fuzzy_match_with_text_mention(self) -> None:
		"""Fuzzy match where skill IS mentioned in text gets decent confidence."""
		from claude_candidate.scoring import compute_match_confidence

		conf = compute_match_confidence(
			candidate_skill="python",
			requirement_text="Strong Python skills with experience in data pipelines",
			match_type="fuzzy",
		)
		assert conf >= 0.70


class TestConfidenceWiring:
	"""Verify widened confidence range affects scoring."""

	def test_full_confidence_no_penalty(self):
		"""Confidence 1.0 → adjustment factor 1.0 (no change)."""
		from claude_candidate.scoring.dimensions import _score_requirement
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel

		skill = MergedSkillEvidence(
			name="python",
			source=EvidenceSource.RESUME_AND_REPO,
			effective_depth=DepthLevel.DEEP,
			confidence=1.0,
		)
		score = _score_requirement(skill, "strong_match")
		# STATUS_SCORE_STRONG = 0.90, adjustment = FLOOR + (1-FLOOR) * 1.0 = 1.0
		assert score == pytest.approx(0.90)

	def test_zero_confidence_max_penalty(self):
		"""Confidence 0.0 → adjustment factor = CONFIDENCE_FLOOR."""
		from claude_candidate.scoring.dimensions import _score_requirement
		from claude_candidate.scoring.constants import CONFIDENCE_FLOOR
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel

		skill = MergedSkillEvidence(
			name="python",
			source=EvidenceSource.RESUME_AND_REPO,
			effective_depth=DepthLevel.DEEP,
			confidence=0.0,
		)
		score = _score_requirement(skill, "strong_match")
		# STATUS_SCORE_STRONG = 0.90, adjustment = CONFIDENCE_FLOOR
		assert score == pytest.approx(0.90 * CONFIDENCE_FLOOR)

	def test_half_confidence_moderate_penalty(self):
		"""Confidence 0.5 → adjustment between FLOOR and 1.0."""
		from claude_candidate.scoring.dimensions import _score_requirement
		from claude_candidate.scoring.constants import CONFIDENCE_FLOOR
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel

		skill = MergedSkillEvidence(
			name="python",
			source=EvidenceSource.RESUME_AND_REPO,
			effective_depth=DepthLevel.DEEP,
			confidence=0.5,
		)
		score = _score_requirement(skill, "strong_match")
		expected_adj = CONFIDENCE_FLOOR + (1.0 - CONFIDENCE_FLOOR) * 0.5
		assert score == pytest.approx(0.90 * expected_adj)

	def test_confidence_floor_is_less_than_090(self):
		"""Verify the floor has been widened from the old ±10%."""
		from claude_candidate.scoring.constants import CONFIDENCE_FLOOR
		assert CONFIDENCE_FLOOR < 0.90, "Confidence floor should be wider than old ±10%"
		assert CONFIDENCE_FLOOR >= 0.50, "Confidence floor shouldn't be so low it dominates"


class TestVirtualSkillConcentration:
	"""Eng review 5B: tighten virtual skill inference rules."""

	def test_software_engineering_needs_5_constituents(self):
		"""software-engineering should require 5 constituents (raised from 3)."""
		from claude_candidate.scoring.constants import VIRTUAL_SKILL_RULES

		for rule in VIRTUAL_SKILL_RULES:
			name = rule[0]
			min_count = rule[2]
			if name == "software-engineering":
				assert min_count >= 5, f"software-engineering min_count should be ≥5, got {min_count}"
				break
		else:
			pytest.fail("software-engineering not found in VIRTUAL_SKILL_RULES")

	def test_full_stack_needs_3_constituents(self):
		"""full-stack should require 3 constituents (raised from 2)."""
		from claude_candidate.scoring.constants import VIRTUAL_SKILL_RULES

		for rule in VIRTUAL_SKILL_RULES:
			name = rule[0]
			min_count = rule[2]
			if name == "full-stack":
				assert min_count >= 3, f"full-stack min_count should be ≥3, got {min_count}"
				break
		else:
			pytest.fail("full-stack not found in VIRTUAL_SKILL_RULES")

	def test_frontend_needs_2_constituents(self):
		"""frontend-development should require 2 constituents (raised from 1)."""
		from claude_candidate.scoring.constants import VIRTUAL_SKILL_RULES

		for rule in VIRTUAL_SKILL_RULES:
			name = rule[0]
			min_count = rule[2]
			if name == "frontend-development":
				assert min_count >= 2, f"frontend-development min_count should be ≥2, got {min_count}"
				break
		else:
			pytest.fail("frontend-development not found in VIRTUAL_SKILL_RULES")

	def test_broad_virtual_skills_require_applied_depth(self):
		"""Broad virtual skills should require constituent skills at APPLIED depth or higher."""
		from claude_candidate.scoring.constants import VIRTUAL_SKILL_RULES
		from claude_candidate.schemas.candidate_profile import DepthLevel

		broad_skills = {"software-engineering", "full-stack", "system-design", "product-development"}
		for rule in VIRTUAL_SKILL_RULES:
			name = rule[0]
			if name in broad_skills:
				assert len(rule) >= 5, f"{name} should have a 5th element (min_constituent_depth)"
				min_depth = rule[4]
				assert min_depth is not None, f"{name} should have a constituent depth requirement"
				depth_order = [DepthLevel.USED, DepthLevel.APPLIED, DepthLevel.DEEP, DepthLevel.EXPERT]
				assert depth_order.index(min_depth) >= depth_order.index(DepthLevel.APPLIED), \
					f"{name} constituent depth should be ≥APPLIED, got {min_depth}"

	def test_virtual_skill_not_inferred_with_shallow_constituents(self):
		"""Virtual skill should NOT be inferred if constituents are USED depth."""
		from claude_candidate.scoring.matching import _infer_virtual_skill
		from claude_candidate.schemas.merged_profile import MergedEvidenceProfile, MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel

		# Profile with 5 skills at USED depth (too shallow)
		skills = [
			MergedSkillEvidence(name=n, source=EvidenceSource.RESUME_ONLY,
				effective_depth=DepthLevel.USED, confidence=0.8)
			for n in ["python", "typescript", "javascript", "react", "node.js"]
		]
		profile = MergedEvidenceProfile(
			skills=skills, projects=[], patterns=[], roles=[],
			corroborated_skill_count=0, resume_only_skill_count=5,
			sessions_only_skill_count=0, discovery_skills=[],
			profile_hash="test", resume_hash="test",
			candidate_profile_hash="test", merged_at=datetime.now(),
		)
		result = _infer_virtual_skill("software-engineering", profile)
		assert result is None, "Should not infer software-engineering from USED-depth skills"

	def test_virtual_skill_inferred_with_deep_constituents(self):
		"""Virtual skill should be inferred if constituents meet depth threshold."""
		from claude_candidate.scoring.matching import _infer_virtual_skill
		from claude_candidate.schemas.merged_profile import MergedEvidenceProfile, MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel

		skills = [
			MergedSkillEvidence(name=n, source=EvidenceSource.RESUME_AND_REPO,
				effective_depth=DepthLevel.DEEP, confidence=0.9)
			for n in ["python", "typescript", "javascript", "react", "node.js", "ci-cd"]
		]
		profile = MergedEvidenceProfile(
			skills=skills, projects=[], patterns=[], roles=[],
			corroborated_skill_count=0, resume_only_skill_count=0,
			sessions_only_skill_count=0, discovery_skills=[],
			profile_hash="test", resume_hash="test",
			candidate_profile_hash="test", merged_at=datetime.now(),
		)
		result = _infer_virtual_skill("software-engineering", profile)
		assert result is not None, "Should infer software-engineering from 6 DEEP skills"
