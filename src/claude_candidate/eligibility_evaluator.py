"""
Evaluate eligibility gates against candidate eligibility profile.

Resolves each eligibility QuickRequirement to "met" / "unmet" / "unknown"
by comparing skill_mapping entries against CandidateEligibility facts.
"""
from __future__ import annotations

import re

from claude_candidate.schemas.curated_resume import CandidateEligibility
from claude_candidate.schemas.fit_assessment import EligibilityGate
from claude_candidate.schemas.job_requirements import QuickRequirement

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
