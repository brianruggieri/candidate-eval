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


def _resolve(req: QuickRequirement, eligibility: CandidateEligibility) -> str:
	for skill in req.skill_mapping:
		category = _classify(skill)
		if category == "work_auth":
			return "met" if eligibility.us_work_authorized else "unmet"
		if category == "clearance":
			return "met" if eligibility.has_clearance else "unmet"
		if category == "relocation":
			return "met" if eligibility.willing_to_relocate else "unmet"
		if category == "travel":
			m = _PCT_PATTERN.search(req.description)
			if m:
				return "met" if int(m.group(1)) <= eligibility.max_travel_pct else "unmet"
			return "unknown"
		if category == "english":
			return "met"
		if category == "foreign_language":
			return "unmet"
		if category == "mission":
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
