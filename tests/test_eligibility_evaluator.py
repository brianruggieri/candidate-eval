"""Unit tests for eligibility gate evaluation."""
from __future__ import annotations

from claude_candidate.schemas.curated_resume import CandidateEligibility
from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority


def make_req(skill: str, description: str = "") -> QuickRequirement:
	"""Helper: build a minimal eligibility QuickRequirement."""
	return QuickRequirement(
		description=description or skill,
		skill_mapping=[skill],
		priority=RequirementPriority.MUST_HAVE,
		is_eligibility=True,
		source_text=description or skill,
	)


class TestWorkAuthorization:
	def test_us_work_auth_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("us-work-authorization")],
			CandidateEligibility(us_work_authorized=True),
		)
		assert gates[0].status == "met"

	def test_us_work_auth_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("us-work-authorization")],
			CandidateEligibility(us_work_authorized=False),
		)
		assert gates[0].status == "unmet"

	def test_work_authorization_alias(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("work-authorization")],
			CandidateEligibility(us_work_authorized=True),
		)
		assert gates[0].status == "met"

	def test_visa_sponsorship_maps_to_work_auth(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("visa-sponsorship")],
			CandidateEligibility(us_work_authorized=True),
		)
		assert gates[0].status == "met"

	def test_visa_sponsorship_unmet_when_unauthorized(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("visa-sponsorship")],
			CandidateEligibility(us_work_authorized=False),
		)
		assert gates[0].status == "unmet"

	def test_visa_maps_to_work_auth(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("visa")],
			CandidateEligibility(us_work_authorized=True),
		)
		assert gates[0].status == "met"


class TestSecurityClearance:
	def test_clearance_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("security-clearance")],
			CandidateEligibility(has_clearance=True),
		)
		assert gates[0].status == "met"

	def test_clearance_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("security-clearance")],
			CandidateEligibility(has_clearance=False),
		)
		assert gates[0].status == "unmet"

	def test_clearance_alias_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("clearance")],
			CandidateEligibility(has_clearance=True),
		)
		assert gates[0].status == "met"


class TestTravel:
	def test_travel_unmet_when_over_max(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("travel", "50% travel required")],
			CandidateEligibility(max_travel_pct=40),
		)
		assert gates[0].status == "unmet"

	def test_travel_met_when_under_max(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("travel", "30% travel required")],
			CandidateEligibility(max_travel_pct=40),
		)
		assert gates[0].status == "met"

	def test_travel_met_when_equal_to_max(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("travel", "40% travel required")],
			CandidateEligibility(max_travel_pct=40),
		)
		assert gates[0].status == "met"

	def test_travel_unknown_when_no_pct(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("travel", "Willingness to travel required")],
			CandidateEligibility(max_travel_pct=40),
		)
		assert gates[0].status == "unknown"


class TestLanguage:
	def test_english_always_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		for skill in ["english", "english-fluency", "english-proficiency"]:
			gates = evaluate_gates([make_req(skill)], CandidateEligibility())
			assert gates[0].status == "met", f"Expected met for {skill}"

	def test_foreign_languages_always_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		for skill in ["spanish", "french", "german", "mandarin"]:
			gates = evaluate_gates([make_req(skill)], CandidateEligibility())
			assert gates[0].status == "unmet", f"Expected unmet for {skill}"

	def test_language_with_fluency_suffix_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("spanish-fluency")], CandidateEligibility())
		assert gates[0].status == "unmet"

	def test_language_with_proficiency_suffix_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("spanish-proficiency")], CandidateEligibility())
		assert gates[0].status == "unmet"


class TestMiscGates:
	def test_relocation_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("relocation")],
			CandidateEligibility(willing_to_relocate=True),
		)
		assert gates[0].status == "met"

	def test_relocation_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("relocation")],
			CandidateEligibility(willing_to_relocate=False),
		)
		assert gates[0].status == "unmet"

	def test_mission_alignment_always_unknown(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		for skill in ["mission_alignment", "mission-alignment"]:
			gates = evaluate_gates([make_req(skill)], CandidateEligibility())
			assert gates[0].status == "unknown"

	def test_unknown_skill_unknown(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("some-weird-requirement")], CandidateEligibility())
		assert gates[0].status == "unknown"

	def test_empty_reqs_returns_empty_list(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([], CandidateEligibility())
		assert gates == []

	def test_gate_description_matches_requirement(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		req = make_req("security-clearance", "Must hold active TS/SCI clearance")
		gates = evaluate_gates([req], CandidateEligibility())
		assert gates[0].description == "Must hold active TS/SCI clearance"


class TestEducationGate:
	"""Tests for detect_education_gap — degree gap detection for grade capping."""

	def _make_edu_req(
		self,
		education_level: str,
		description: str = "Degree required",
	) -> QuickRequirement:
		return QuickRequirement(
			description=description,
			skill_mapping=["python"],
			priority=RequirementPriority.MUST_HAVE,
			education_level=education_level,
		)

	def test_no_education_requirement_returns_none(self):
		"""No education_level on any requirement = no cap."""
		from claude_candidate.eligibility_evaluator import detect_education_gap

		reqs = [
			QuickRequirement(
				description="Python proficiency",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
			)
		]
		result = detect_education_gap(reqs, ["B.S. Computer Science"])
		assert result is None

	def test_requirement_met_returns_none(self):
		"""Candidate meets degree = no cap."""
		from claude_candidate.eligibility_evaluator import detect_education_gap

		result = detect_education_gap(
			[self._make_edu_req("bachelor")],
			["B.S. Computer Science"],
		)
		assert result is None

	def test_requirement_exceeded_returns_none(self):
		"""Candidate exceeds = no cap."""
		from claude_candidate.eligibility_evaluator import detect_education_gap

		result = detect_education_gap(
			[self._make_edu_req("bachelor")],
			["M.S. Computer Science"],
		)
		assert result is None

	def test_ms_gap_returns_b_plus_cap(self):
		"""Requires MS, have BS = B+ cap (score 0.849)."""
		from claude_candidate.eligibility_evaluator import detect_education_gap

		result = detect_education_gap(
			[self._make_edu_req("master")],
			["B.S. Computer Science"],
		)
		assert result is not None
		assert result.gap == 1
		assert result.cap_grade == "B+"
		assert result.cap_score == 0.849

	def test_phd_minus_one_returns_b_minus_cap(self):
		"""Requires PhD, have MS = B- cap (score 0.749)."""
		from claude_candidate.eligibility_evaluator import detect_education_gap

		result = detect_education_gap(
			[self._make_edu_req("phd")],
			["M.S. Computer Science"],
		)
		assert result is not None
		assert result.gap == 1
		assert result.cap_grade == "B+"
		assert result.cap_score == 0.849

	def test_phd_minus_two_returns_c_plus_cap(self):
		"""Requires PhD, have BS = C+ cap (score 0.699)."""
		from claude_candidate.eligibility_evaluator import detect_education_gap

		result = detect_education_gap(
			[self._make_edu_req("phd")],
			["B.S. Computer Science"],
		)
		assert result is not None
		assert result.gap == 2
		assert result.cap_grade == "B-"
		assert result.cap_score == 0.749

	def test_phd_minus_two_no_degree(self):
		"""Requires PhD, no degree = C+ cap."""
		from claude_candidate.eligibility_evaluator import detect_education_gap

		result = detect_education_gap(
			[self._make_edu_req("phd")],
			[],
		)
		assert result is not None
		assert result.gap == 3
		assert result.cap_grade == "C+"
		assert result.cap_score == 0.699

	def test_no_candidate_education_with_bs_requirement(self):
		"""Requires BS, no education = B+ cap."""
		from claude_candidate.eligibility_evaluator import detect_education_gap

		result = detect_education_gap(
			[self._make_edu_req("bachelor")],
			[],
		)
		assert result is not None
		assert result.gap == 1
		assert result.cap_grade == "B+"
		assert result.cap_score == 0.849

	def test_highest_requirement_wins(self):
		"""Multiple reqs, highest degree determines cap."""
		from claude_candidate.eligibility_evaluator import detect_education_gap

		reqs = [
			self._make_edu_req("bachelor"),
			self._make_edu_req("master"),
		]
		result = detect_education_gap(reqs, ["B.S. Computer Science"])
		assert result is not None
		assert result.gap == 1
		assert result.cap_grade == "B+"

	def test_degree_ranking_aliases(self):
		"""Various degree string formats recognized."""
		from claude_candidate.eligibility_evaluator import detect_education_gap

		# BS alias for bachelor
		result = detect_education_gap(
			[self._make_edu_req("bs")],
			["B.S. Computer Science"],
		)
		assert result is None  # met

		# MBA alias for master
		result = detect_education_gap(
			[self._make_edu_req("mba")],
			["B.A. Liberal Arts"],
		)
		assert result is not None
		assert result.gap == 1

		# ph.d. alias for phd
		result = detect_education_gap(
			[self._make_edu_req("ph.d.")],
			["M.S. Physics"],
		)
		assert result is not None
		assert result.gap == 1
