"""
Dimension scoring helpers extracted from quick_match.py.

Contains eligibility inference, soft skill discounting, domain gap detection,
requirement scoring, skill detail builders, mission helpers, culture helpers,
weight computation, and result builders.

All function bodies are verbatim copies from quick_match.py —
only import sources have changed (constants now come from scoring.constants).
"""

from __future__ import annotations

import re

from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.fit_assessment import (
	DimensionScore,
	SkillMatchDetail,
	score_to_grade,
)
from claude_candidate.schemas.job_requirements import (
	QuickRequirement,
	RequirementPriority,
	PRIORITY_WEIGHT,
)
from claude_candidate.schemas.merged_profile import (
	EvidenceSource,
	MergedEvidenceProfile,
	MergedSkillEvidence,
)
from claude_candidate.scoring.constants import (
	# Eligibility
	ELIGIBILITY_SKILL_NAMES,
	ELIGIBILITY_DESCRIPTION_PATTERNS,
	# Soft skill discount
	SOFT_SKILL_DISCOUNT,
	# Domain keywords
	DOMAIN_KEYWORDS,
	# Status scoring
	STATUS_SCORE,
	STATUS_SCORE_NONE,
	STATUS_MARKER,
	# Display limits
	TOP_SKILL_DETAILS,
	MAX_TECH_OVERLAP_DISPLAY,
	# Rounding
	SCORE_PRECISION,
	# Confidence adjustment
	CONFIDENCE_FLOOR,
	# Years gradient
	YEARS_GRADIENT_FLOOR,
	# Mission constants
	MISSION_NEUTRAL_SCORE,
	MISSION_DOMAIN_BONUS,
	MISSION_TECH_OVERLAP_WEIGHT,
	MISSION_TEXT_OVERLAP_WEIGHT,
	MISSION_NO_ENRICHMENT_BASE,
	MISSION_NO_ENRICHMENT_RANGE,
	MISSION_DOMAIN_TAXONOMY,
	# Culture constants
	CULTURE_PATTERN_STRENGTH_SCORE,
	CULTURE_EMERGING_MATCH,
	# Adaptive weight tuples
	WEIGHTS_TECH_ONLY,
	WEIGHTS_WITH_MISSION,
	WEIGHTS_WITH_CULTURE,
	WEIGHTS_FULL,
)
from claude_candidate.scoring.matching import compute_match_confidence, _evidence_summary


# ---------------------------------------------------------------------------
# Eligibility inference
# ---------------------------------------------------------------------------


def _infer_eligibility(req: "QuickRequirement") -> bool:
	"""Heuristic fallback: classify a requirement as eligibility if it matches known patterns.

	Used for cached postings that predate the is_eligibility field.
	"""
	if req.is_eligibility:
		return True
	if any(s.lower() in ELIGIBILITY_SKILL_NAMES for s in req.skill_mapping):
		return True
	for pattern in ELIGIBILITY_DESCRIPTION_PATTERNS:
		if re.search(pattern, req.description):
			return True
	return False


# ---------------------------------------------------------------------------
# Soft skill discount
# ---------------------------------------------------------------------------


def _soft_skill_discount() -> float:
	"""Return the fixed soft skill weight discount.

	Soft skill requirements get reduced weight in Technical Fit because
	they are hard to evidence from code. The discount is a fixed 0.5.
	Culture influence flows exclusively through the Culture Fit dimension.
	"""
	return SOFT_SKILL_DISCOUNT


# ---------------------------------------------------------------------------
# Domain gap detection
# ---------------------------------------------------------------------------


def _detect_domain_gap(
	requirements: "list[QuickRequirement]",
	profile: "MergedEvidenceProfile",
) -> str | None:
	"""Return the first domain keyword in 3+ requirements that is absent from the profile.

	Checks candidate skills, project names (word-split), and role domains.
	Returns the keyword string if a gap is detected, None otherwise.
	"""
	# Build a single text blob for substring matching — handles both single-word
	# and multi-word phrase keywords (e.g. "real estate") correctly.
	candidate_parts: list[str] = []
	for skill in profile.skills:
		candidate_parts.append(skill.name.lower())
	for project in profile.projects or []:
		candidate_parts.append(project.project_name.lower())
	for role in profile.roles or []:
		if role.domain:
			candidate_parts.append(role.domain.lower())
	candidate_text = " ".join(candidate_parts)

	# Find the domain keyword with the HIGHEST occurrence count (above threshold)
	# to determine severity correctly — e.g. "genomic" (6x) beats "bioinformatics" (3x).
	best_kw: str | None = None
	best_count = 0
	for kw in sorted(DOMAIN_KEYWORDS):  # sorted for deterministic tiebreaking
		count = sum(1 for r in requirements if kw in r.description.lower())
		if count >= 3 and kw not in candidate_text and count > best_count:
			best_kw = kw
			best_count = count
	return best_kw


# ---------------------------------------------------------------------------
# Requirement scoring
# ---------------------------------------------------------------------------


def _score_requirement(
	best_match: MergedSkillEvidence | None,
	best_status: str,
	priority: RequirementPriority = RequirementPriority.MUST_HAVE,
	years_ratio: float | None = None,
) -> float:
	"""Compute the score for one requirement given its best match.

	Match status drives the score. Confidence applies as a minor adjustment
	(±10%) rather than a multiplicative penalty, since match status already
	encodes quality and the old confidence × status multiplication created
	an artificial ceiling around A-.

	No-evidence scoring is priority-dependent:
	- must_have/strong_preference: 0.0 (hard gaps should hurt)
	- nice_to_have/implied: STATUS_SCORE_NONE floor (transferable skills)

	Years gradient penalty: when years_ratio < 1.0, a gradient multiplier
	penalises shortfalls proportionally instead of using cliff-based downgrades.
	"""
	if best_status == "no_evidence":
		if priority in (RequirementPriority.MUST_HAVE, RequirementPriority.STRONG_PREFERENCE):
			return 0.0
		return STATUS_SCORE_NONE

	req_score = STATUS_SCORE.get(best_status, STATUS_SCORE_NONE)
	if best_match:
		# Apply confidence as a ±30% adjustment to the base status score.
		# confidence may be None (v0.7 merge_triad) — default to 1.0 (no penalty).
		conf = best_match.confidence if best_match.confidence is not None else 1.0
		adjustment = CONFIDENCE_FLOOR + (1.0 - CONFIDENCE_FLOOR) * conf
		req_score *= adjustment

	# Years gradient penalty: proportional penalty for experience shortfalls
	if years_ratio is not None and years_ratio < 1.0:
		gradient = YEARS_GRADIENT_FLOOR + (1.0 - YEARS_GRADIENT_FLOOR) * years_ratio
		req_score *= gradient

	return req_score


# ---------------------------------------------------------------------------
# Skill detail builders
# ---------------------------------------------------------------------------


def _build_skill_detail(
	req: QuickRequirement,
	best_match: MergedSkillEvidence | None,
	best_status: str,
	match_type: str = "exact",
) -> SkillMatchDetail:
	"""Build a SkillMatchDetail for one requirement."""
	# Use match-time confidence (v0.7) — measures how well the skill maps to
	# the requirement text. Falls back to merge-time confidence for legacy profiles.
	if best_match and best_status != "no_evidence":
		conf = compute_match_confidence(
			candidate_skill=best_match.name,
			requirement_text=req.description,
			match_type=match_type,
		)
	else:
		conf = 0.0
	return SkillMatchDetail(
		requirement=req.description,
		priority=req.priority.value,
		match_status=best_status,
		candidate_evidence=(_evidence_summary(best_match) if best_match else "No evidence found"),
		evidence_source=(best_match.source if best_match else EvidenceSource.RESUME_ONLY),
		confidence=conf,
		matched_skill=best_match.name if best_match else None,
		match_type=match_type,
		parent_id=req.parent_id,
	)


def _format_detail_point(detail: SkillMatchDetail) -> str:
	"""Format a single skill detail into a display string."""
	marker = STATUS_MARKER.get(detail.match_status, "?")
	status_label = detail.match_status.replace("_", " ")
	return f"[{marker}] {detail.requirement}: {status_label}"


def _build_skill_dimension(
	score: float,
	details: list[SkillMatchDetail],
) -> DimensionScore:
	"""Build the skill_match DimensionScore from scored details."""
	met = sum(1 for d in details if d.match_status in ("strong_match", "exceeds"))
	partial = sum(1 for d in details if d.match_status == "partial_match")
	missing = sum(1 for d in details if d.match_status == "no_evidence")
	summary = f"{met} requirements strongly matched, {partial} partial, {missing} gaps."

	sorted_details = sorted(
		details,
		key=lambda x: PRIORITY_WEIGHT.get(RequirementPriority(x.priority), 0),
		reverse=True,
	)[:TOP_SKILL_DETAILS]
	detail_points = [_format_detail_point(d) for d in sorted_details]

	return DimensionScore(
		dimension="skill_match",
		score=round(score, SCORE_PRECISION),
		grade=score_to_grade(score),
		summary=summary,
		details=detail_points or ["No requirements to evaluate"],
	)


# ---------------------------------------------------------------------------
# Mission alignment helpers
# ---------------------------------------------------------------------------


def _candidate_domain_set(profile: MergedEvidenceProfile) -> set[str]:
	"""Collect candidate domain keywords from projects, roles, and skills.

	Scans multiple sources to build a comprehensive domain signal:
	- Project technologies (session-derived)
	- Role domain field (if populated)
	- Role company names and descriptions (tokenized)
	- Skill names (especially domain-category skills)
	"""
	domains: set[str] = set()
	for proj in profile.projects:
		for tech in proj.technologies:
			domains.add(tech.lower())
	for role in profile.roles:
		if role.domain:
			domains.add(role.domain.lower())
		# Scan company name and description for domain keywords
		role_text = f"{role.company} {role.description or ''}".lower()
		for word in role_text.split():
			# Clean punctuation from tokens
			clean = word.strip(".,;:()[]{}\"'")
			if len(clean) >= 3:
				domains.add(clean)
	# Include skill names — covers domain skills like edtech, healthcare, etc.
	for skill in profile.skills:
		domains.add(skill.name.lower())
	return domains


def _candidate_skill_names(profile: MergedEvidenceProfile) -> set[str]:
	"""Return the set of candidate skill names."""
	return {s.name for s in profile.skills}


def _score_domain_overlap(
	profile: MergedEvidenceProfile,
	company_profile: CompanyProfile,
) -> tuple[float, list[str]]:
	"""Score domain overlap; return (bonus, detail_lines).

	Uses both exact set intersection and substring matching to handle
	compound domain terms (e.g. 'edtech' matching 'education' or 'educational').
	"""
	candidate_domains = _candidate_domain_set(profile)
	company_domains = {d.lower() for d in company_profile.product_domain}
	# Exact match first
	overlap = candidate_domains & company_domains
	if overlap:
		return MISSION_DOMAIN_BONUS, [f"Domain overlap: {', '.join(sorted(overlap))}"]
	# Substring match: check if any company domain appears in any candidate token
	# or vice versa (e.g. "edtech" in "educational", "education" in "edtech")
	for cd in company_domains:
		if len(cd) < 3:
			continue
		for token in candidate_domains:
			if len(token) < 3:
				continue
			if cd in token or token in cd:
				return MISSION_DOMAIN_BONUS, [f"Domain match: {cd} ↔ {token}"]
	return 0.0, []


def _score_tech_overlap(
	profile: MergedEvidenceProfile,
	company_profile: CompanyProfile,
) -> tuple[float, list[str]]:
	"""Score tech-stack overlap; return (bonus, detail_lines)."""
	company_techs = {t.lower() for t in company_profile.tech_stack_public}
	candidate_techs = _candidate_skill_names(profile)
	overlap = company_techs & candidate_techs
	if overlap:
		ratio = len(overlap) / max(len(company_techs), 1)
		detail = f"Tech overlap: {', '.join(sorted(overlap)[:MAX_TECH_OVERLAP_DISPLAY])}"
		return ratio * MISSION_TECH_OVERLAP_WEIGHT, [detail]
	return 0.0, []


def _score_mission_text_alignment(
	profile: MergedEvidenceProfile,
	company_profile: CompanyProfile,
) -> tuple[float, list[str]]:
	"""Score mission text alignment using domain-aware keyword taxonomy.

	Expands matching beyond raw skill names by including domain taxonomy keywords
	when the candidate has skills in a recognized domain. This catches cases where
	a company's mission mentions domain concepts (e.g., 'developer tools') that
	don't exactly match skill names (e.g., 'ci-cd', 'git').
	"""
	text_sources = []
	if company_profile.mission_statement:
		text_sources.append(company_profile.mission_statement)
	text_sources.append(company_profile.product_description)
	if not text_sources:
		return 0.0, []

	combined_text = " ".join(text_sources).lower()

	# Build candidate keywords from skills + project techs
	candidate_keywords: set[str] = {s.name.lower() for s in profile.skills}
	for proj in profile.projects:
		for tech in proj.technologies:
			candidate_keywords.add(tech.lower())

	# Expand with domain taxonomy: if candidate has skills in a domain,
	# include that domain's keywords for matching against mission text.
	expanded_keywords: set[str] = set(candidate_keywords)
	for domain, domain_keywords in MISSION_DOMAIN_TAXONOMY.items():
		domain_kw_set = set(domain_keywords)
		skill_overlap = candidate_keywords & domain_kw_set
		if skill_overlap or domain.lower() in candidate_keywords:
			expanded_keywords.update(domain_keywords)

	# Match expanded keywords against mission text (3+ chars, word boundary)
	matched = {
		kw
		for kw in expanded_keywords
		if len(kw) >= 3 and re.search(rf"\b{re.escape(kw)}\b", combined_text)
	}
	if not matched:
		return 0.0, []

	# Score based on ratio of matched to candidate keywords
	# Cap at 1.0 since expanded keywords can exceed original count
	ratio = min(len(matched) / max(len(candidate_keywords), 1), 1.0)
	detail = f"Mission text overlap: {', '.join(sorted(matched)[:MAX_TECH_OVERLAP_DISPLAY])}"
	return ratio * MISSION_TEXT_OVERLAP_WEIGHT, [detail]


def _mission_from_posting(
	profile: MergedEvidenceProfile,
	tech_stack: list[str],
) -> tuple[float, list[str]]:
	"""Score mission alignment from the posting tech stack alone."""
	score = MISSION_NEUTRAL_SCORE
	details: list[str] = []
	if tech_stack:
		posting_techs = {t.lower() for t in tech_stack}
		candidate_techs = _candidate_skill_names(profile)
		overlap = posting_techs & candidate_techs
		if overlap:
			ratio = len(overlap) / max(len(posting_techs), 1)
			score = MISSION_NO_ENRICHMENT_BASE + ratio * MISSION_NO_ENRICHMENT_RANGE
			details.append(
				f"Tech stack overlap: {', '.join(sorted(overlap)[:MAX_TECH_OVERLAP_DISPLAY])}"
			)
	details.append("Limited enrichment data — score based on posting tech stack only")
	return score, details


# ---------------------------------------------------------------------------
# Culture helpers
# ---------------------------------------------------------------------------


def _match_signal_to_pattern(
	signal: str,
	profile: MergedEvidenceProfile,
) -> tuple[float, str | None]:
	"""Match a single culture signal directly to a candidate pattern by name.

	Checks whether any of the candidate's observed patterns have a pattern_type
	whose value (the enum string) appears as a substring of the culture signal,
	or the culture signal appears as a substring of the pattern_type value.
	Returns (match_value, detail_or_None).
	"""
	signal_lower = signal.lower()
	for pat in profile.patterns:
		pt_value = pat.pattern_type.value  # e.g. "documentation_driven"
		# Normalize pattern type to words for comparison
		pt_words = pt_value.replace("_", " ")
		if pt_words in signal_lower or signal_lower in pt_words:
			score = CULTURE_PATTERN_STRENGTH_SCORE.get(pat.strength, CULTURE_EMERGING_MATCH)
			if pat.strength in ("strong", "exceptional"):
				return score, f"Strong {pt_words} pattern aligns with '{signal}'"
			if pat.strength == "established":
				return score, f"Established {pt_words} pattern aligns with '{signal}'"
			return score, None
	return 0.0, None


# ---------------------------------------------------------------------------
# Weight computation
# ---------------------------------------------------------------------------


def select_weights(
	has_mission: bool,
	has_culture: bool,
) -> tuple[float, float, float]:
	"""Return (skill_weight, mission_weight, culture_weight) based on data availability.

	Four states:
	  both     → 60/25/15
	  mission  → 75/25/0
	  culture  → 85/0/15
	  neither  → 100/0/0
	"""
	if has_mission and has_culture:
		return WEIGHTS_FULL
	if has_mission:
		return WEIGHTS_WITH_MISSION
	if has_culture:
		return WEIGHTS_WITH_CULTURE
	return WEIGHTS_TECH_ONLY


# ---------------------------------------------------------------------------
# Assessment result builders
# ---------------------------------------------------------------------------


def _compute_overall_score(
	skill_dim: DimensionScore,
	mission_dim: DimensionScore | None = None,
	culture_dim: DimensionScore | None = None,
) -> float:
	"""Compute weighted overall score from available dimensions."""
	total = skill_dim.score * skill_dim.weight
	for dim in (mission_dim, culture_dim):
		if dim is not None:
			total += dim.score * dim.weight
	return total


def _must_have_coverage(details: list[SkillMatchDetail]) -> str:
	"""Summarize must-have requirement coverage."""
	must_haves = [d for d in details if d.priority == "must_have"]
	if not must_haves:
		return "No must-haves specified"
	met = sum(1 for d in must_haves if d.match_status in ("strong_match", "exceeds"))
	return f"{met}/{len(must_haves)} must-haves met"


def _strongest_and_gap(
	details: list[SkillMatchDetail],
) -> tuple[str, str]:
	"""Identify the strongest match and biggest gap from skill details."""
	strong = [d for d in details if d.match_status in ("strong_match", "exceeds")]
	gaps = [
		d
		for d in details
		if d.match_status == "no_evidence" and d.priority in ("must_have", "strong_preference")
	]
	strongest = strong[0].requirement if strong else "None identified"
	biggest_gap = gaps[0].requirement if gaps else "None — all requirements addressed"
	return strongest, biggest_gap


def _discover_resume_gaps(
	profile: MergedEvidenceProfile,
	requirements: list[QuickRequirement],
) -> list[str]:
	"""Find skills demonstrated in sessions but missing from resume."""
	return [
		s.name
		for s in profile.skills
		if s.discovery_flag
		and any(
			s.name in r.skill_mapping or any(s.name in sm for sm in r.skill_mapping)
			for r in requirements
		)
	]


def _find_resume_unverified(
	profile: MergedEvidenceProfile,
	requirements: list[QuickRequirement],
) -> list[str]:
	"""Find resume skills relevant to the role without session backing."""
	all_required: set[str] = set()
	for req in requirements:
		all_required.update(s.lower() for s in req.skill_mapping)
	return [
		s.name
		for s in profile.skills
		if s.source == EvidenceSource.RESUME_ONLY and s.name in all_required
	]
