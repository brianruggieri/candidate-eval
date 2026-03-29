"""
Evaluate eligibility gates against candidate eligibility profile.

Resolves each eligibility QuickRequirement to "met" / "unmet" / "unknown"
by comparing skill_mapping entries against CandidateEligibility facts.

Also provides education degree gap detection for grade capping.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from claude_candidate.schemas.curated_resume import CandidateEligibility
from claude_candidate.schemas.fit_assessment import EligibilityGate
from claude_candidate.schemas.job_requirements import QuickRequirement


# ---------------------------------------------------------------------------
# Degree ranking and education gap detection
# ---------------------------------------------------------------------------

DEGREE_RANKING: dict[str, int] = {
	"bachelor": 1,
	"bs": 1,
	"ba": 1,
	"b.s.": 1,
	"b.a.": 1,
	"master": 2,
	"ms": 2,
	"ma": 2,
	"m.s.": 2,
	"m.a.": 2,
	"mba": 2,
	"phd": 3,
	"ph.d.": 3,
	"doctorate": 3,
}

_EDUCATION_GAP_CAPS: dict[int, tuple[str, float]] = {
	1: ("B+", 0.849),
	2: ("B-", 0.749),
	3: ("C+", 0.699),
}


@dataclass(frozen=True)
class EducationGapResult:
	"""Result of education gap detection — describes the gap and grade cap."""

	gap: int
	cap_grade: str
	cap_score: float
	required_label: str
	candidate_label: str


def _highest_degree_rank(education: list[str]) -> int:
	"""Extract the highest degree rank from a list of education strings."""
	best = 0
	for entry in education:
		entry_lower = entry.lower()
		for keyword, rank in DEGREE_RANKING.items():
			if keyword in entry_lower:
				best = max(best, rank)
	return best


def _rank_to_label(rank: int) -> str:
	"""Convert a degree rank back to a human label."""
	_RANK_LABELS = {1: "bachelor", 2: "master", 3: "phd"}
	return _RANK_LABELS.get(rank, "none")


def detect_education_gap(
	reqs: list[QuickRequirement],
	candidate_education: list[str],
) -> EducationGapResult | None:
	"""Detect education degree gap between requirements and candidate.

	Returns None if no education requirement exists or if the candidate
	meets/exceeds the requirement. Otherwise returns an EducationGapResult
	with the gap size and corresponding grade cap.
	"""
	# Find the highest required degree rank across all requirements
	required_rank = 0
	for req in reqs:
		if req.education_level:
			rank = DEGREE_RANKING.get(req.education_level.lower(), 0)
			required_rank = max(required_rank, rank)

	if required_rank == 0:
		return None  # No education requirement

	candidate_rank = _highest_degree_rank(candidate_education)

	if candidate_rank >= required_rank:
		return None  # Requirement met or exceeded

	gap = required_rank - candidate_rank
	# Clamp to max gap of 3
	gap = min(gap, 3)

	cap_grade, cap_score = _EDUCATION_GAP_CAPS[gap]
	return EducationGapResult(
		gap=gap,
		cap_grade=cap_grade,
		cap_score=cap_score,
		required_label=_rank_to_label(required_rank),
		candidate_label=_rank_to_label(candidate_rank) if candidate_rank > 0 else "none",
	)

_WORK_AUTH_SKILLS: frozenset[str] = frozenset({
	"us-work-authorization",
	"us_work_authorization",
	"work-authorization",
	"work_authorization",
	"visa",
	"visa-sponsorship",
})

_CLEARANCE_SKILLS: frozenset[str] = frozenset({"security-clearance", "clearance"})
_RELOCATION_SKILLS: frozenset[str] = frozenset({"relocation"})
_TRAVEL_SKILLS: frozenset[str] = frozenset({"travel"})
_ENGLISH_SKILLS: frozenset[str] = frozenset({"english", "english-fluency", "english-proficiency"})
_MISSION_SKILLS: frozenset[str] = frozenset({"mission_alignment", "mission-alignment"})

_FOREIGN_LANGUAGE_PATTERN: re.Pattern[str] = re.compile(
	r"^(spanish|french|german|mandarin)(-fluency|-proficiency)?$"
)
_PCT_PATTERN: re.Pattern[str] = re.compile(r"(\d+)\s*%")


def _classify(skill: str) -> str:
	s = skill.lower()
	if s in _WORK_AUTH_SKILLS:
		return "work_auth"
	if s in _CLEARANCE_SKILLS:
		return "clearance"
	if s in _RELOCATION_SKILLS:
		return "relocation"
	if s in _TRAVEL_SKILLS:
		return "travel"
	if s in _ENGLISH_SKILLS:
		return "english"
	if _FOREIGN_LANGUAGE_PATTERN.match(s):
		return "foreign_language"
	if s in _MISSION_SKILLS:
		return "mission"
	return "unknown"


_BLOCKING_CATEGORIES: frozenset[str] = frozenset({
	"work_auth", "clearance", "relocation", "travel", "foreign_language",
})


def _resolve(req: QuickRequirement, eligibility: CandidateEligibility) -> str:
	"""Scan all skill_mapping entries and apply precedence: unmet > met > unknown.

	Evaluating all entries (rather than returning on the first match) prevents
	list order from affecting the outcome — e.g. ["english", "spanish"] correctly
	resolves to "unmet" because "spanish" blocks regardless of position.
	"""
	blocking_unmet = False
	any_met = False
	any_unknown = False

	for skill in req.skill_mapping:
		category = _classify(skill)
		status: str

		if category == "work_auth":
			status = "met" if eligibility.us_work_authorized else "unmet"
		elif category == "clearance":
			status = "met" if eligibility.has_clearance else "unmet"
		elif category == "relocation":
			status = "met" if eligibility.willing_to_relocate else "unmet"
		elif category == "travel":
			m = _PCT_PATTERN.search(req.description)
			if m:
				status = "met" if int(m.group(1)) <= eligibility.max_travel_pct else "unmet"
			else:
				status = "unknown"
		elif category == "english":
			status = "met"
		elif category == "foreign_language":
			status = "unmet"
		elif category == "mission":
			status = "unknown"
		else:
			continue  # Unrecognized category — skip, doesn't affect aggregate

		if status == "unmet" and category in _BLOCKING_CATEGORIES:
			blocking_unmet = True
		elif status == "met":
			any_met = True
		elif status == "unknown":
			any_unknown = True

	if blocking_unmet:
		return "unmet"
	if any_met:
		return "met"
	if any_unknown:
		return "unknown"
	return "unknown"


def evaluate_gates(
	reqs: list[QuickRequirement],
	eligibility: CandidateEligibility,
) -> list[EligibilityGate]:
	"""Evaluate eligibility requirements against candidate facts.

	Returns one EligibilityGate per requirement with status resolved to
	"met" / "unmet" / "unknown".
	"""
	return [
		EligibilityGate(
			description=req.description,
			status=_resolve(req, eligibility),
			requirement_text=req.source_text or req.description,
		)
		for req in reqs
	]
