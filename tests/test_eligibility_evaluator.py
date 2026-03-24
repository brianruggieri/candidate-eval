"""Unit tests for eligibility gate evaluation."""
from __future__ import annotations

import pytest

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
		gates = evaluate_gates([make_req("us-work-authorization")], CandidateEligibility(us_work_authorized=True))
		assert gates[0].status == "met"

	def test_us_work_auth_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("us-work-authorization")], CandidateEligibility(us_work_authorized=False))
		assert gates[0].status == "unmet"

	def test_work_authorization_alias(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("work-authorization")], CandidateEligibility(us_work_authorized=True))
		assert gates[0].status == "met"

	def test_visa_sponsorship_maps_to_work_auth(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("visa-sponsorship")], CandidateEligibility(us_work_authorized=True))
		assert gates[0].status == "met"

	def test_visa_sponsorship_unmet_when_unauthorized(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("visa-sponsorship")], CandidateEligibility(us_work_authorized=False))
		assert gates[0].status == "unmet"


class TestSecurityClearance:
	def test_clearance_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("security-clearance")], CandidateEligibility(has_clearance=True))
		assert gates[0].status == "met"

	def test_clearance_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("security-clearance")], CandidateEligibility(has_clearance=False))
		assert gates[0].status == "unmet"

	def test_clearance_alias_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("clearance")], CandidateEligibility(has_clearance=True))
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


class TestMiscGates:
	def test_relocation_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("relocation")], CandidateEligibility(willing_to_relocate=True))
		assert gates[0].status == "met"

	def test_relocation_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("relocation")], CandidateEligibility(willing_to_relocate=False))
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
