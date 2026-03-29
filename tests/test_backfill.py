"""Tests for backfill-on-read recomputation of stored assessments."""

from __future__ import annotations

import pytest

from claude_candidate.schemas.fit_assessment import score_to_grade, score_to_verdict
from claude_candidate.scoring.backfill import recompute_overall, _has_real_data, _infer_avoid_count
from claude_candidate.scoring.constants import (
	CULTURE_AVOID_CAP_ONE,
	CULTURE_AVOID_CAP_TWO_PLUS,
	WEIGHTS_FULL,
	WEIGHTS_TECH_ONLY,
	WEIGHTS_WITH_CULTURE,
	WEIGHTS_WITH_MISSION,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_dim(dimension: str, score: float, **overrides) -> dict:
	"""Build a minimal dimension dict for testing."""
	d = {
		"dimension": dimension,
		"score": score,
		"grade": score_to_grade(score),
		"weight": 0.333,
		"summary": f"Test {dimension}",
		"details": [f"{dimension} detail"],
		"confidence": 1.0,
		"insufficient_data": False,
	}
	d.update(overrides)
	return d


def _make_assessment(
	skill_score: float = 0.85,
	mission_score: float | None = None,
	culture_score: float | None = None,
	culture_details: list[str] | None = None,
	culture_insufficient: bool = False,
	mission_insufficient: bool = False,
	eligibility_gates: list[dict] | None = None,
	domain_gap_term: str | None = None,
	education_gap_cap: str | None = None,
	overall_score: float | None = None,
	overall_grade: str | None = None,
	should_apply: str | None = None,
	**extra,
) -> dict:
	"""Build a minimal assessment dict for testing."""
	a: dict = {
		"skill_match": _make_dim("skill_match", skill_score),
	}
	if mission_score is not None:
		a["mission_alignment"] = _make_dim(
			"mission_alignment",
			mission_score,
			insufficient_data=mission_insufficient,
		)
	if culture_score is not None:
		details = culture_details or ["Culture detail"]
		a["culture_fit"] = _make_dim(
			"culture_fit",
			culture_score,
			details=details,
			insufficient_data=culture_insufficient,
		)
	if eligibility_gates is not None:
		a["eligibility_gates"] = eligibility_gates
	if domain_gap_term is not None:
		a["domain_gap_term"] = domain_gap_term
	if education_gap_cap is not None:
		a["education_gap_cap"] = education_gap_cap
	# Stale overall (what was stored)
	a["overall_score"] = overall_score if overall_score is not None else 0.5
	a["overall_grade"] = overall_grade or "C"
	a["should_apply"] = should_apply or "maybe"
	a.update(extra)
	return a


# ---------------------------------------------------------------------------
# Weight state detection
# ---------------------------------------------------------------------------


class TestWeightStateDetection:
	"""Verify that recompute_overall selects the correct weight tuple based
	on data availability flags in the stored dimension dicts."""

	def test_tech_only_no_mission_no_culture(self):
		"""No mission or culture dims → 100% skill weight."""
		a = _make_assessment(skill_score=0.80)
		result = recompute_overall(a)
		# With 100% skill weight, overall = skill_score
		assert result["overall_score"] == 0.80

	def test_mission_insufficient_treated_as_absent(self):
		"""Mission dim with insufficient_data=True → treated as no mission."""
		a = _make_assessment(
			skill_score=0.80,
			mission_score=0.60,
			mission_insufficient=True,
		)
		result = recompute_overall(a)
		# Mission insufficient → tech_only weights → 100% skill
		assert result["overall_score"] == 0.80

	def test_mission_real_data(self):
		"""Real mission data → WEIGHTS_WITH_MISSION split."""
		skill_s, mission_s = 0.80, 0.60
		a = _make_assessment(skill_score=skill_s, mission_score=mission_s)
		result = recompute_overall(a)
		sk_w, ms_w, _ = WEIGHTS_WITH_MISSION
		expected = round(skill_s * sk_w + mission_s * ms_w, 3)
		assert result["overall_score"] == expected

	def test_culture_real_data(self):
		"""Real culture data → WEIGHTS_WITH_CULTURE split."""
		skill_s, culture_s = 0.80, 0.70
		a = _make_assessment(skill_score=skill_s, culture_score=culture_s)
		result = recompute_overall(a)
		sk_w, _, cu_w = WEIGHTS_WITH_CULTURE
		expected = round(skill_s * sk_w + culture_s * cu_w, 3)
		assert result["overall_score"] == expected

	def test_both_mission_and_culture(self):
		"""Both mission and culture → WEIGHTS_FULL split."""
		skill_s, mission_s, culture_s = 0.90, 0.70, 0.80
		a = _make_assessment(
			skill_score=skill_s,
			mission_score=mission_s,
			culture_score=culture_s,
		)
		result = recompute_overall(a)
		sk_w, ms_w, cu_w = WEIGHTS_FULL
		expected = round(skill_s * sk_w + mission_s * ms_w + culture_s * cu_w, 3)
		assert result["overall_score"] == expected

	def test_culture_insufficient_treated_as_absent(self):
		"""Culture dim with insufficient_data=True → treated as no culture."""
		a = _make_assessment(
			skill_score=0.80,
			culture_score=0.70,
			culture_insufficient=True,
		)
		result = recompute_overall(a)
		# Culture insufficient → tech_only weights → 100% skill
		assert result["overall_score"] == 0.80


# ---------------------------------------------------------------------------
# Legacy dimensions (experience_match, education_match)
# ---------------------------------------------------------------------------


class TestLegacyDimensions:
	"""Old assessments may contain experience_match or education_match dims.
	These should be ignored in weight computation but preserved in the blob."""

	def test_experience_match_preserved_but_ignored(self):
		"""experience_match in the blob should not affect overall calculation."""
		a = _make_assessment(skill_score=0.80)
		a["experience_match"] = _make_dim("skill_match", 0.95)  # reuse dim type for testing
		result = recompute_overall(a)
		# Should still be 100% skill
		assert result["overall_score"] == 0.80
		# Legacy dim preserved
		assert "experience_match" in result

	def test_education_match_preserved_but_ignored(self):
		"""education_match in the blob should not affect overall calculation."""
		a = _make_assessment(skill_score=0.80)
		a["education_match"] = _make_dim("skill_match", 0.90)
		result = recompute_overall(a)
		assert result["overall_score"] == 0.80
		assert "education_match" in result


# ---------------------------------------------------------------------------
# Grade caps
# ---------------------------------------------------------------------------


class TestGradeCaps:
	"""Verify that grade caps (eligibility, domain gap, education gap,
	culture avoid) are correctly re-applied during backfill."""

	def test_eligibility_unmet_zeroes_score(self):
		"""Unmet eligibility gate → score = 0.0."""
		a = _make_assessment(
			skill_score=0.90,
			eligibility_gates=[{"description": "US work auth", "status": "unmet"}],
		)
		result = recompute_overall(a)
		assert result["overall_score"] == 0.0
		assert result["overall_grade"] == "F"

	def test_domain_gap_caps_at_b_plus(self):
		"""Domain gap term present → A-range capped to B+."""
		a = _make_assessment(
			skill_score=0.95,
			domain_gap_term="genomics",
		)
		result = recompute_overall(a)
		# 0.95 would be A+, but domain gap caps to 0.849
		assert result["overall_score"] == 0.849
		assert result["overall_grade"] == "B+"

	def test_domain_gap_no_cap_when_already_below(self):
		"""Domain gap should not affect scores already at or below B+."""
		a = _make_assessment(
			skill_score=0.75,
			domain_gap_term="genomics",
		)
		result = recompute_overall(a)
		assert result["overall_score"] == 0.75

	def test_eligibility_overrides_domain_gap(self):
		"""Eligibility gate zeroes score regardless of domain gap."""
		a = _make_assessment(
			skill_score=0.95,
			domain_gap_term="genomics",
			eligibility_gates=[{"description": "Clearance", "status": "unmet"}],
		)
		result = recompute_overall(a)
		assert result["overall_score"] == 0.0

	def test_education_gap_cap_applied(self):
		"""Education gap cap grade limits the score."""
		a = _make_assessment(
			skill_score=0.90,
			education_gap_cap="B+",
		)
		result = recompute_overall(a)
		assert result["overall_score"] == 0.849
		assert result["overall_grade"] == "B+"

	def test_education_gap_cap_b_minus(self):
		"""Education gap cap at B- limits appropriately."""
		a = _make_assessment(
			skill_score=0.90,
			education_gap_cap="B-",
		)
		result = recompute_overall(a)
		assert result["overall_score"] == 0.749
		assert result["overall_grade"] == "B-"

	def test_culture_avoid_one_caps_at_b_plus(self):
		"""One culture avoid flag → caps at CULTURE_AVOID_CAP_ONE."""
		a = _make_assessment(
			skill_score=0.95,
			culture_score=0.80,
			culture_details=["Culture detail", "Avoid flags: crunch"],
		)
		result = recompute_overall(a)
		assert result["overall_score"] <= CULTURE_AVOID_CAP_ONE

	def test_culture_avoid_two_caps_at_b_minus(self):
		"""Two+ culture avoid flags → caps at CULTURE_AVOID_CAP_TWO_PLUS."""
		a = _make_assessment(
			skill_score=0.95,
			culture_score=0.80,
			culture_details=["Culture detail", "Avoid flags: crunch, hustle"],
		)
		result = recompute_overall(a)
		assert result["overall_score"] <= CULTURE_AVOID_CAP_TWO_PLUS


# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class TestOutputContract:
	"""Verify structural guarantees of recompute_overall output."""

	def test_returns_new_dict(self):
		"""Must not mutate the input."""
		a = _make_assessment(skill_score=0.80)
		original_score = a["overall_score"]
		result = recompute_overall(a)
		assert result is not a
		assert a["overall_score"] == original_score

	def test_grade_matches_score(self):
		"""overall_grade must match score_to_grade(overall_score)."""
		a = _make_assessment(skill_score=0.85)
		result = recompute_overall(a)
		assert result["overall_grade"] == score_to_grade(result["overall_score"])

	def test_should_apply_updated(self):
		"""should_apply must match score_to_verdict(overall_score)."""
		a = _make_assessment(skill_score=0.90)
		result = recompute_overall(a)
		assert result["should_apply"] == score_to_verdict(result["overall_score"])

	def test_score_clamped_zero_to_one(self):
		"""Score must be in [0.0, 1.0] even with extreme inputs."""
		a = _make_assessment(skill_score=1.0, mission_score=1.0, culture_score=1.0)
		result = recompute_overall(a)
		assert 0.0 <= result["overall_score"] <= 1.0

	def test_no_skill_match_passthrough(self):
		"""Assessment without skill_match returns copy unchanged."""
		a = {"overall_score": 0.5, "overall_grade": "C", "should_apply": "maybe"}
		result = recompute_overall(a)
		assert result is not a
		assert result == a

	def test_all_original_fields_preserved(self):
		"""Extra fields in the assessment dict survive recomputation."""
		a = _make_assessment(skill_score=0.80)
		a["job_title"] = "Staff Engineer"
		a["company_name"] = "Acme Corp"
		a["custom_field"] = "preserved"
		result = recompute_overall(a)
		assert result["job_title"] == "Staff Engineer"
		assert result["company_name"] == "Acme Corp"
		assert result["custom_field"] == "preserved"


# ---------------------------------------------------------------------------
# _has_real_data helper
# ---------------------------------------------------------------------------


class TestHasRealData:
	def test_none_returns_false(self):
		assert _has_real_data(None) is False

	def test_insufficient_data_returns_false(self):
		assert _has_real_data({"insufficient_data": True, "score": 0.5}) is False

	def test_normal_dim_returns_true(self):
		assert _has_real_data({"insufficient_data": False, "score": 0.5}) is True

	def test_missing_flag_returns_true(self):
		assert _has_real_data({"score": 0.5}) is True


# ---------------------------------------------------------------------------
# _infer_avoid_count helper
# ---------------------------------------------------------------------------


class TestInferAvoidCount:
	def test_none_returns_zero(self):
		assert _infer_avoid_count(None) == 0

	def test_no_avoid_detail_returns_zero(self):
		dim = {"details": ["Some other detail"]}
		assert _infer_avoid_count(dim) == 0

	def test_one_avoid_flag(self):
		dim = {"details": ["Culture detail", "Avoid flags: crunch"]}
		assert _infer_avoid_count(dim) == 1

	def test_two_avoid_flags(self):
		dim = {"details": ["Avoid flags: crunch, hustle"]}
		assert _infer_avoid_count(dim) == 2

	def test_three_avoid_flags(self):
		dim = {"details": ["Avoid flags: crunch, hustle, burnout"]}
		assert _infer_avoid_count(dim) == 3

	def test_empty_details_returns_zero(self):
		dim = {"details": []}
		assert _infer_avoid_count(dim) == 0
