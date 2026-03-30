"""
Backfill-on-read: recompute overall_score and overall_grade for stored assessments.

Pure function -- reads dimension scores from the JSON blob, applies current
weight system, re-applies grade caps.  Never mutates the input dict.
"""

from __future__ import annotations

import copy

from claude_candidate.schemas.fit_assessment import score_to_grade, score_to_verdict
from claude_candidate.scoring.dimensions import select_weights

_GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]
_B_PLUS_CEILING = 0.849


def _has_real_data(dim_dict: dict | None) -> bool:
	"""Return True if the dimension dict contains real scored data."""
	if dim_dict is None:
		return False
	if dim_dict.get("insufficient_data", False):
		return False
	return True


def _infer_avoid_count(culture_dim: dict | None) -> int:
	"""Infer culture avoid hit count from stored dimension details.

	The culture scorer stores avoid hits as detail strings like
	``"Avoid flags: crunch, hustle"``.  Count the comma-separated items
	in the first matching detail line.
	"""
	if culture_dim is None:
		return 0
	for detail in culture_dim.get("details", []):
		if isinstance(detail, str) and detail.startswith("Avoid flags:"):
			# "Avoid flags: crunch, hustle" → ["crunch", "hustle"]
			flags_part = detail.split(":", 1)[1].strip()
			return len([f for f in flags_part.split(",") if f.strip()])
	return 0


def recompute_overall(assessment: dict) -> dict:
	"""Recompute overall_score, overall_grade, and should_apply using current weights.

	Returns a deep copy -- never mutates the input dict.
	If the assessment lacks a skill_match dimension, returns a copy unchanged.
	"""
	result = copy.deepcopy(assessment)

	skill_dim = result.get("skill_match")
	if skill_dim is None:
		return result

	skill_score = skill_dim.get("score", 0.0)
	mission_dim = result.get("mission_alignment")
	culture_dim = result.get("culture_fit")

	has_mission = _has_real_data(mission_dim)
	has_culture = _has_real_data(culture_dim)

	# select_weights returns a TUPLE: (skill_w, mission_w, culture_w)
	skill_w, mission_w, culture_w = select_weights(has_mission, has_culture)

	overall = skill_score * skill_w
	if has_mission:
		overall += mission_dim["score"] * mission_w
	if has_culture:
		overall += culture_dim["score"] * culture_w

	overall = round(min(max(overall, 0.0), 1.0), 3)

	# --- Grade caps ---

	# Eligibility gate: unmet gates zero the score
	gates = result.get("eligibility_gates", [])
	if any(g.get("status") == "unmet" for g in gates):
		overall = 0.0

	# Domain gap cap: B+ ceiling when domain term is present
	domain_gap = result.get("domain_gap_term")
	if domain_gap and overall > 0.0:
		current_grade = score_to_grade(overall)
		if _GRADE_ORDER.index(current_grade) < _GRADE_ORDER.index("B+"):
			overall = min(overall, _B_PLUS_CEILING)

	# Education gap cap
	education_gap_cap = result.get("education_gap_cap")
	if education_gap_cap and overall > 0.0:
		from claude_candidate.eligibility_evaluator import _EDUCATION_GAP_CAPS

		# Find the score ceiling for this cap grade
		for _gap_size, (grade, score_cap) in _EDUCATION_GAP_CAPS.items():
			if grade == education_gap_cap:
				if overall > score_cap:
					overall = min(overall, score_cap)
				break

	# Culture avoid cap -- infer count from stored dimension details
	avoid_count = _infer_avoid_count(culture_dim)
	if avoid_count and overall > 0.0:
		from claude_candidate.scoring.constants import (
			CULTURE_AVOID_CAP_ONE,
			CULTURE_AVOID_CAP_TWO_PLUS,
		)

		if avoid_count >= 2:
			current_grade = score_to_grade(overall)
			if _GRADE_ORDER.index(current_grade) < _GRADE_ORDER.index("B-"):
				overall = min(overall, CULTURE_AVOID_CAP_TWO_PLUS)
		elif avoid_count == 1:
			current_grade = score_to_grade(overall)
			if _GRADE_ORDER.index(current_grade) < _GRADE_ORDER.index("B+"):
				overall = min(overall, CULTURE_AVOID_CAP_ONE)

	result["overall_score"] = overall
	result["overall_grade"] = score_to_grade(overall)
	result["should_apply"] = score_to_verdict(overall)

	return result
