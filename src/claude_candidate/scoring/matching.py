"""
Skill matching pipeline extracted from quick_match.py.

Contains match-time confidence computation, skill matching helpers,
adoption velocity, virtual skill inference, skill resolution,
depth assessment, and the main _find_best_skill orchestrator.

All function bodies are verbatim copies from quick_match.py —
only import sources have changed (constants now come from scoring.constants).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from claude_candidate.schemas.candidate_profile import DepthLevel, DEPTH_RANK, PatternType
from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.job_requirements import QuickRequirement
from claude_candidate.schemas.merged_profile import (
	EvidenceSource,
	MergedEvidenceProfile,
	MergedSkillEvidence,
)
from claude_candidate.scoring.constants import (
	# Taxonomy helper
	_get_taxonomy,
	# Pattern-based evidence thresholds
	PATTERN_CONFIDENCE_HIGH,
	PATTERN_CONFIDENCE_LOW,
	# Pattern frequency
	PATTERN_FREQ_OCCASIONAL,
	# Depth offset
	DEPTH_EXCEEDS_OFFSET,
	# Status rank lookup
	STATUS_RANK,
	# Source label
	SOURCE_LABEL,
	# Lookup tables
	PATTERN_STRENGTH_TO_DEPTH,
	PATTERN_FREQ_TO_COUNT,
	# Virtual skill rules and mappings
	VIRTUAL_SKILL_RULES,
	PATTERN_TO_SKILL,
	# Years thresholds
	YEARS_LEADERSHIP_THRESHOLD,
	YEARS_SOFTWARE_ENG_THRESHOLD,
	# Adoption velocity constants
	ADOPTION_BREADTH_WEIGHT,
	ADOPTION_NOVELTY_WEIGHT,
	ADOPTION_RAMP_WEIGHT,
	ADOPTION_META_WEIGHT,
	ADOPTION_TOOL_WEIGHT,
	ADOPTION_NOVELTY_RECENCY_CUTOFF,
	ADOPTION_NOVELTY_TARGET,
	ADOPTION_BREADTH_TARGET,
	ADOPTION_CONFIDENCE_DIVISOR,
	ADOPTION_RAMP_NORMALIZER,
	ADOPTION_DEPTH_EXPERT,
	ADOPTION_DEPTH_DEEP,
	ADOPTION_DEPTH_APPLIED,
	ADOPTION_DEPTH_USED,
	ADOPTION_STRENGTH_MAP,
	# Scale / AI constants
	_SCALE_KEYWORDS,
	_AI_KEYWORDS_RE,
	_AI_SKILL_NAMES,
	# Match-time confidence data
	_GENERIC_SKILLS,
	_SKILL_VARIANTS,
)


# ---------------------------------------------------------------------------
# Match-time confidence (v0.7)
# ---------------------------------------------------------------------------


def _is_generic_skill(skill: str) -> bool:
	"""Return True if the skill is a broad/generic term unlikely to match specific roles."""
	return skill in _GENERIC_SKILLS


def _skill_mentioned_in_text(skill: str, text: str) -> bool:
	"""Check if the skill or common variants appear in the text.

	Both ``skill`` and ``text`` must already be lowercased.
	Uses word-boundary matching for short terms (<=3 chars) to avoid
	false positives (e.g. "go" matching "good", "vue" matching "avenue").
	"""

	def _match(term: str) -> bool:
		if len(term) <= 3:
			return bool(re.search(r"\b" + re.escape(term) + r"\b", text))
		return term in text

	# Direct name check (also try hyphen↔space since canonical names use hyphens)
	if _match(skill):
		return True
	dehyphenated = skill.replace("-", " ")
	if dehyphenated != skill and _match(dehyphenated):
		return True
	# Common variant checks
	for variant in _SKILL_VARIANTS.get(skill, []):
		if _match(variant):
			return True
	return False


def compute_match_confidence(
	candidate_skill: str,
	requirement_text: str,
	match_type: str,
) -> float:
	"""Compute match-time confidence between a skill and a requirement.

	Confidence measures how precisely the candidate's skill maps to what
	the requirement is asking for.  This is NOT about evidence quality
	(that's handled by source/depth) — it's about match quality.

	Args:
		candidate_skill: Canonical skill name (e.g. "typescript").
		requirement_text: The full requirement description text.
		match_type: One of "exact", "alias", "fuzzy", "related", "none".

	Returns:
		A float in [0.0, 1.0] indicating match confidence.
	"""
	if match_type == "none" or not candidate_skill:
		return 0.0

	# Normalize for text matching
	skill_lower = candidate_skill.lower().strip()
	text_lower = requirement_text.lower()

	# Check if the skill name (or common variants) appears in the requirement text
	skill_in_text = _skill_mentioned_in_text(skill_lower, text_lower)

	if match_type == "exact":
		return 1.0 if skill_in_text else 0.70
	elif match_type == "alias":
		return 0.90 if skill_in_text else 0.65
	elif match_type == "fuzzy":
		if skill_in_text:
			return 0.80
		# Generic skills matching specific requirements → very low
		if _is_generic_skill(skill_lower):
			return 0.10
		return 0.50
	elif match_type == "related":
		if skill_in_text:
			return 0.65
		return 0.40

	return 0.0


# ---------------------------------------------------------------------------
# AdoptionVelocityResult dataclass
# ---------------------------------------------------------------------------


@dataclass
class AdoptionVelocityResult:
	"""Result of the adoption velocity composite computation."""

	composite_score: float  # 0.0-1.0
	depth: DepthLevel  # mapped from composite_score
	confidence: float  # evidence_count / ADOPTION_CONFIDENCE_DIVISOR, capped at 1.0
	evidence_count: int  # scorable skills + relevant pattern presence count
	summary_quote: str  # natural language summary for evidence display
	sub_scores: dict[str, float]  # breadth, novelty, ramp_speed, meta_cognition, tool_selection


# ---------------------------------------------------------------------------
# Skill matching helpers (module-level)
# ---------------------------------------------------------------------------


def _find_exact_match(
	normalized: str,
	profile: MergedEvidenceProfile,
) -> MergedSkillEvidence | None:
	"""Return an exact skill match from the profile."""
	return profile.get_skill(normalized)


def _find_fuzzy_match(
	normalized: str,
	profile: MergedEvidenceProfile,
) -> MergedSkillEvidence | None:
	"""Return a fuzzy skill match (substring or known variant).

	Requires minimum length of 3 characters for substring matching to avoid
	false positives like 'c' matching 'ci-cd' or 'r' matching 'react'.
	Rejects matches where both query and skill are distinct taxonomy entries
	(e.g. 'java' should not match 'javascript').
	"""
	MIN_SUBSTRING_LEN = 3
	taxonomy = _get_taxonomy()
	for skill in profile.skills:
		# Substring match only when the shorter string is long enough
		shorter_len = min(len(normalized), len(skill.name))
		if shorter_len >= MIN_SUBSTRING_LEN:
			if normalized in skill.name or skill.name in normalized:
				# Reject if both are distinct canonical taxonomy entries
				canon_query = taxonomy.canonicalize(normalized)
				canon_skill = taxonomy.canonicalize(skill.name)
				if canon_query != canon_skill and canon_query == normalized:
					continue  # e.g. "java" ≠ "javascript" — both canonical, skip
				return skill
		if _is_variant_match(normalized, skill.name):
			return skill
	return None


def _is_variant_match(query: str, skill_name: str) -> bool:
	"""Check whether query and skill_name are canonical equivalents (aliases only).

	Deliberately excludes 'related' skills (e.g. docker/kubernetes, react/javascript)
	to avoid inflating match scores. Related skills should map to 'adjacent' status,
	not be treated as the same skill.
	"""
	taxonomy = _get_taxonomy()
	canon_query = taxonomy.canonicalize(query)
	canon_skill = taxonomy.canonicalize(skill_name)
	return canon_query == canon_skill


def _pattern_confidence(strength: str) -> float:
	"""Return confidence score for a pattern strength level."""
	if strength in ("strong", "exceptional"):
		return PATTERN_CONFIDENCE_HIGH
	return PATTERN_CONFIDENCE_LOW


def _find_pattern_match(
	normalized: str,
	profile: MergedEvidenceProfile,
) -> MergedSkillEvidence | None:
	"""Synthesize a MergedSkillEvidence from a matching behavioral pattern."""
	for pattern in profile.patterns:
		if pattern.pattern_type.value != normalized:
			continue
		depth = PATTERN_STRENGTH_TO_DEPTH.get(pattern.strength, DepthLevel.APPLIED)
		freq = PATTERN_FREQ_TO_COUNT.get(pattern.frequency, PATTERN_FREQ_OCCASIONAL)
		return MergedSkillEvidence(
			name=pattern.pattern_type.value,
			source=EvidenceSource.SESSIONS_ONLY,
			session_depth=depth,
			session_frequency=freq,
			session_evidence_count=len(pattern.evidence),
			effective_depth=depth,
			confidence=_pattern_confidence(pattern.strength),
			discovery_flag=True,
		)
	return None


# ---------------------------------------------------------------------------
# Adoption velocity
# ---------------------------------------------------------------------------


def _build_adoption_summary(
	breadth_count: int,
	novelty_count: int,
	meta_strength: str | None,
	tool_strength: str | None,
	composite: float,
) -> str:
	"""Generate a natural language summary of adoption velocity signals."""
	parts: list[str] = []
	if novelty_count > 0:
		parts.append(
			f"adopted {novelty_count} new skill{'s' if novelty_count != 1 else ''} recently"
		)
	if breadth_count > 0:
		parts.append(
			f"applied+ depth across {breadth_count} skill categor{'ies' if breadth_count != 1 else 'y'}"
		)
	pattern_parts: list[str] = []
	if meta_strength:
		pattern_parts.append(f"{meta_strength} meta-cognition")
	if tool_strength:
		pattern_parts.append(f"{tool_strength} tool selection")
	if pattern_parts:
		parts.append(" and ".join(pattern_parts) + " patterns")
	if not parts:
		return f"Adoption velocity composite: {composite:.2f}"
	summary = ", ".join(parts)
	return summary[0].upper() + summary[1:]


def compute_adoption_velocity(
	profile: MergedEvidenceProfile,
) -> AdoptionVelocityResult:
	"""Compute a 5-signal composite score for learning agility (adoption velocity).

	Signals:
	  - Breadth (15%): distinct skill categories at applied+ depth
	  - Novelty (25%): skills acquired in the last 30% of the observed date range
	  - Ramp speed (30%): frequency-weighted depth achievement rate (log-scaled)
	  - Meta-cognition (15%): META_COGNITION pattern strength
	  - Tool selection (15%): TOOL_SELECTION pattern strength

	Returns an AdoptionVelocityResult with composite score, depth, confidence,
	evidence count, summary quote, and per-signal sub-scores.
	"""
	# Signal 1: Breadth
	distinct_categories = len(
		{
			s.category
			for s in profile.skills
			if s.category is not None
			and DEPTH_RANK.get(s.effective_depth, 0) >= DEPTH_RANK[DepthLevel.APPLIED]
		}
	)
	breadth_score = min(distinct_categories / ADOPTION_BREADTH_TARGET, 1.0)

	# Signal 2: Novelty
	skills_with_dates = [s for s in profile.skills if s.session_first_seen is not None]
	novelty_count = 0
	if len(skills_with_dates) >= 2:
		dates = sorted(s.session_first_seen for s in skills_with_dates)
		date_range = (dates[-1] - dates[0]).total_seconds()
		if date_range > 0:
			cutoff = dates[0] + timedelta(seconds=date_range * ADOPTION_NOVELTY_RECENCY_CUTOFF)
			novel_skills = [
				s
				for s in skills_with_dates
				if s.session_first_seen >= cutoff
				and DEPTH_RANK.get(s.effective_depth, 0) >= DEPTH_RANK[DepthLevel.USED]
			]
			novelty_count = len(novel_skills)
	novelty_score = min(novelty_count / ADOPTION_NOVELTY_TARGET, 1.0)

	# Signal 3: Ramp speed
	applied_plus = [
		s
		for s in profile.skills
		if DEPTH_RANK.get(s.effective_depth, 0) >= DEPTH_RANK[DepthLevel.APPLIED]
		and s.session_frequency is not None
		and s.session_frequency > 0
	]
	if not applied_plus:
		ramp_score = 0.0
	else:
		depth_weight = {DepthLevel.APPLIED: 1.0, DepthLevel.DEEP: 2.0, DepthLevel.EXPERT: 3.0}
		weighted_sum = 0.0
		weight_total = 0.0
		for s in applied_plus:
			depth_rank = max(DEPTH_RANK.get(s.effective_depth, 1), 1)
			ramp = math.log1p(s.session_frequency / depth_rank)
			w = depth_weight.get(s.effective_depth, 1.0)
			weighted_sum += ramp * w
			weight_total += w
		avg_ramp = weighted_sum / weight_total if weight_total > 0 else 0.0
		ramp_score = min(avg_ramp / ADOPTION_RAMP_NORMALIZER, 1.0)

	# Signals 4 & 5: Pattern strengths
	meta_pattern = next(
		(p for p in profile.patterns if p.pattern_type == PatternType.META_COGNITION), None
	)
	tool_pattern = next(
		(p for p in profile.patterns if p.pattern_type == PatternType.TOOL_SELECTION), None
	)
	meta_strength = meta_pattern.strength if meta_pattern else None
	tool_strength = tool_pattern.strength if tool_pattern else None
	meta_score = ADOPTION_STRENGTH_MAP.get(meta_strength or "", 0.0)
	tool_score = ADOPTION_STRENGTH_MAP.get(tool_strength or "", 0.0)

	# Composite
	composite = (
		breadth_score * ADOPTION_BREADTH_WEIGHT
		+ novelty_score * ADOPTION_NOVELTY_WEIGHT
		+ ramp_score * ADOPTION_RAMP_WEIGHT
		+ meta_score * ADOPTION_META_WEIGHT
		+ tool_score * ADOPTION_TOOL_WEIGHT
	)

	# Depth mapping
	if composite >= ADOPTION_DEPTH_EXPERT:
		depth = DepthLevel.EXPERT
	elif composite >= ADOPTION_DEPTH_DEEP:
		depth = DepthLevel.DEEP
	elif composite >= ADOPTION_DEPTH_APPLIED:
		depth = DepthLevel.APPLIED
	elif composite >= ADOPTION_DEPTH_USED:
		depth = DepthLevel.USED
	else:
		depth = DepthLevel.MENTIONED

	# Confidence: scorable skills + pattern presence
	scorable_skill_count = len(
		[
			s
			for s in profile.skills
			if s.category is not None
			and DEPTH_RANK.get(s.effective_depth, 0) >= DEPTH_RANK[DepthLevel.USED]
		]
	)
	pattern_count = sum(
		1
		for p in profile.patterns
		if p.pattern_type in (PatternType.META_COGNITION, PatternType.TOOL_SELECTION)
	)
	evidence_count = scorable_skill_count + pattern_count
	confidence = min(evidence_count / ADOPTION_CONFIDENCE_DIVISOR, 1.0)

	summary_quote = _build_adoption_summary(
		distinct_categories, novelty_count, meta_strength, tool_strength, composite
	)

	return AdoptionVelocityResult(
		composite_score=composite,
		depth=depth,
		confidence=confidence,
		evidence_count=evidence_count,
		summary_quote=summary_quote,
		sub_scores={
			"breadth": breadth_score,
			"novelty": novelty_score,
			"ramp_speed": ramp_score,
			"meta_cognition": meta_score,
			"tool_selection": tool_score,
		},
	)


# ---------------------------------------------------------------------------
# Virtual skill inference: synthesize compound skills from constituents
# ---------------------------------------------------------------------------


def _infer_virtual_skill(
	skill_name: str,
	profile: MergedEvidenceProfile,
) -> MergedSkillEvidence | None:
	"""Synthesize a virtual skill if the profile has constituent evidence.

	Checks three sources:
	1. Skill combination rules (VIRTUAL_SKILL_RULES)
	2. Behavioral pattern mappings (PATTERN_TO_SKILL)
	3. Years-of-experience thresholds for broad skills
	"""
	taxonomy = _get_taxonomy()
	canonical = taxonomy.match(skill_name)
	target = (canonical or skill_name).lower().strip()
	profile_names = {s.name.lower() for s in profile.skills}

	# Check virtual skill rules
	for rule_name, constituents, min_count, depth in VIRTUAL_SKILL_RULES:
		if rule_name != target:
			continue
		# Count how many constituents the profile has
		matched = sum(1 for c in constituents if c in profile_names)
		if matched >= min_count:
			# Derive source from the constituent skills that exist in the profile.
			# Prefer the most specific provenance: session > resume+repo > repo > resume.
			constituent_skills = [s for s in profile.skills if s.name.lower() in constituents]
			session_sources = {EvidenceSource.SESSIONS_ONLY, EvidenceSource.CORROBORATED}
			has_session_evidence = any(s.source in session_sources for s in constituent_skills)
			has_repo_evidence = any(
				s.source in {EvidenceSource.RESUME_AND_REPO, EvidenceSource.REPO_ONLY}
				for s in constituent_skills
			)
			if has_session_evidence:
				virtual_source = EvidenceSource.SESSIONS_ONLY
			elif has_repo_evidence:
				# Prefer RESUME_AND_REPO if any constituent has it, else REPO_ONLY
				if any(s.source is EvidenceSource.RESUME_AND_REPO for s in constituent_skills):
					virtual_source = EvidenceSource.RESUME_AND_REPO
				else:
					virtual_source = EvidenceSource.REPO_ONLY
			else:
				virtual_source = EvidenceSource.RESUME_ONLY
			return MergedSkillEvidence(
				name=rule_name,
				source=virtual_source,
				session_depth=depth if has_session_evidence else None,
				resume_depth=depth if not has_session_evidence else None,
				effective_depth=depth,
				confidence=min(0.7, 0.4 + matched * 0.1),
				discovery_flag=False,
			)

	# Check behavioral pattern mappings
	for pattern in profile.patterns:
		mappings = PATTERN_TO_SKILL.get(pattern.pattern_type.value, [])
		for mapped_name, mapped_depth in mappings:
			if mapped_name == target:
				return MergedSkillEvidence(
					name=mapped_name,
					source=EvidenceSource.SESSIONS_ONLY,
					session_depth=mapped_depth,
					effective_depth=mapped_depth,
					confidence=0.7,
					discovery_flag=False,
				)

	# Adoption velocity composite for adaptability
	if target == "adaptability":
		result = compute_adoption_velocity(profile)
		if result.composite_score >= ADOPTION_DEPTH_USED:
			return MergedSkillEvidence(
				name="adaptability",
				source=EvidenceSource.SESSIONS_ONLY,
				session_depth=result.depth,
				effective_depth=result.depth,
				confidence=result.confidence,
				discovery_flag=False,
				resume_context=result.summary_quote,
			)
		# Fallback: years-based when composite has insufficient session data
		total_yrs = profile.total_years_experience or 0
		if total_yrs >= 10.0:
			return MergedSkillEvidence(
				name="adaptability",
				source=EvidenceSource.RESUME_ONLY,
				resume_depth=DepthLevel.DEEP,
				effective_depth=DepthLevel.DEEP,
				confidence=0.6,
			)
		if total_yrs >= 5.0:
			return MergedSkillEvidence(
				name="adaptability",
				source=EvidenceSource.RESUME_ONLY,
				resume_depth=DepthLevel.APPLIED,
				effective_depth=DepthLevel.APPLIED,
				confidence=0.6,
			)
		return None

	# Years-based inference for broad skills and soft skills.
	# Depth scales with experience: senior professionals (10+ years)
	# get DEEP depth so they don't get partial_match on behavioral reqs.
	total = profile.total_years_experience or 0
	# (min_years_for_applied, min_years_for_deep)
	years_inferred: dict[str, tuple[float, float]] = {
		"leadership": (YEARS_LEADERSHIP_THRESHOLD, YEARS_LEADERSHIP_THRESHOLD),
		"software-engineering": (YEARS_SOFTWARE_ENG_THRESHOLD, YEARS_SOFTWARE_ENG_THRESHOLD),
		"communication": (3.0, 8.0),
		"collaboration": (3.0, 8.0),
		"problem-solving": (3.0, 8.0),
		"ownership": (5.0, 10.0),
		"technical-writing": (5.0, 10.0),
	}
	if target in years_inferred:
		min_applied, min_deep = years_inferred[target]
		depth = DepthLevel.DEEP if total >= min_deep else DepthLevel.APPLIED
		if total >= min_applied:
			return MergedSkillEvidence(
				name=target,
				source=EvidenceSource.RESUME_ONLY,
				resume_depth=depth,
				effective_depth=depth,
				confidence=0.6,
			)

	return None


# ---------------------------------------------------------------------------
# Skill resolution
# ---------------------------------------------------------------------------


def _find_skill_match(
	skill_name: str,
	profile: MergedEvidenceProfile,
) -> tuple[MergedSkillEvidence | None, str]:
	"""Find a skill in the merged profile via exact, fuzzy, pattern, or inference.

	Returns (skill, match_type) where match_type is:
	  "exact"  — canonical name or taxonomy alias resolved to an exact profile hit
	  "fuzzy"  — substring, pattern, or inferred virtual skill
	  "none"   — no match found
	"""
	taxonomy = _get_taxonomy()
	# Canonicalize through taxonomy first (handles aliases like ci/cd -> ci-cd)
	canonical = taxonomy.match(skill_name)
	if canonical:
		found = _find_exact_match(canonical.lower(), profile)
		if found:
			return found, "exact"

	# Fallback to original normalized form
	normalized = skill_name.lower().strip()
	exact = _find_exact_match(normalized, profile)
	if exact:
		return exact, "exact"
	fuzzy = _find_fuzzy_match(normalized, profile)
	if fuzzy:
		return fuzzy, "fuzzy"
	pattern = _find_pattern_match(normalized, profile)
	if pattern:
		return pattern, "fuzzy"
	inferred = _infer_virtual_skill(skill_name, profile)
	if inferred:
		return inferred, "fuzzy"
	return None, "none"


# ---------------------------------------------------------------------------
# Depth assessment
# ---------------------------------------------------------------------------


def _best_available_depth(skill: MergedSkillEvidence) -> DepthLevel:
	"""Return the most favorable depth for matching.

	For CONFLICTING skills (resume and session depths diverge by 2+ levels),
	the merger anchors to resume depth (sessions can boost by at most one rung).
	But when the resume claims a higher depth than effective_depth, we use it
	for matching — the resume is human-curated and the session extractor may
	under-detect skills.
	"""
	best = skill.effective_depth
	if skill.source == EvidenceSource.CONFLICTING and skill.resume_depth:
		resume_rank = DEPTH_RANK.get(skill.resume_depth, 0)
		effective_rank = DEPTH_RANK.get(best, 0)
		if resume_rank > effective_rank:
			best = skill.resume_depth
	return best


def _related_corroboration_boost(
	skill: MergedSkillEvidence,
	profile: MergedEvidenceProfile,
) -> int:
	"""Boost depth rank by 1 if 2+ related skills exist at deep+ depth.

	If a candidate has shallow depth on a skill but deep expertise in
	closely related areas, their capability is likely underestimated.
	E.g., agentic-workflows at "applied" + llm at "deep" + langchain at
	"deep" suggests true agentic depth is higher than "applied".
	"""
	taxonomy = _get_taxonomy()
	related = taxonomy.get_related(skill.name)
	if not related:
		return 0
	deep_count = 0
	for ps in profile.skills:
		canon = taxonomy.canonicalize(ps.name)
		if canon in related:
			ps_depth = DEPTH_RANK.get(_best_available_depth(ps), 0)
			if ps_depth >= DEPTH_RANK[DepthLevel.DEEP]:
				deep_count += 1
	return 1 if deep_count >= 2 else 0


def _assess_depth_match(
	skill: MergedSkillEvidence,
	required_depth: DepthLevel,
	profile: MergedEvidenceProfile | None = None,
) -> str:
	"""Assess how well a skill's depth matches a requirement."""
	actual_rank = DEPTH_RANK.get(_best_available_depth(skill), 0)
	if profile:
		actual_rank += _related_corroboration_boost(skill, profile)
	required_rank = DEPTH_RANK.get(required_depth, 0)

	if actual_rank >= required_rank + DEPTH_EXCEEDS_OFFSET:
		return "exceeds"
	if actual_rank >= required_rank:
		return "strong_match"
	if actual_rank >= required_rank - DEPTH_EXCEEDS_OFFSET:
		return "partial_match"
	return "adjacent"


def _evidence_summary(skill: MergedSkillEvidence) -> str:
	"""Generate a brief evidence summary for a matched skill."""
	parts = []
	label = SOURCE_LABEL.get(skill.source)
	if label:
		parts.append(label)
	if skill.session_frequency:
		parts.append(f"{skill.session_frequency} sessions")
	if skill.resume_years:
		parts.append(f"{skill.resume_years}y on resume")
	# Include adoption velocity summary quote for non-resume-only sources
	if skill.resume_context and skill.source != EvidenceSource.RESUME_ONLY:
		parts.append(skill.resume_context)
	parts.append(f"depth: {skill.effective_depth.value}")
	return ". ".join(parts)


def _parse_duration_years(duration: str | None) -> float | None:
	"""Parse duration string like '8 years', '2 months' into years."""
	if not duration:
		return None
	match = re.match(r"(\d+)\s*(year|month|yr|mo)", duration.lower())
	if not match:
		return None
	value = int(match.group(1))
	unit = match.group(2)
	if unit.startswith("mo"):
		return value / 12.0
	return float(value)


# ---------------------------------------------------------------------------
# Scale / AI helpers
# ---------------------------------------------------------------------------


def _detect_required_scale(text: str) -> str | None:
	"""Detect if a requirement specifies a scale level."""
	text_lower = text.lower()
	for keyword, scale in _SCALE_KEYWORDS:
		if keyword in text_lower:
			return scale
	return None


def _requirement_mentions_ai(text: str) -> bool:
	"""Return True if the requirement text contains AI/ML keywords (word-boundary matched)."""
	return bool(_AI_KEYWORDS_RE.search(text))


def _candidate_ai_scale(profile: MergedEvidenceProfile) -> str | None:
	"""Return the candidate's highest scale among AI-category skills.

	Looks for skills in _AI_SKILL_NAMES or domain-category skills whose canonical
	name overlaps with AI skill names. Returns the highest scale found, or 'personal'
	if no AI skills have explicit scale info.
	"""
	taxonomy = _get_taxonomy()
	_SCALE_RANK = {"personal": 0, "team": 1, "startup": 2, "enterprise": 3, "consumer": 4}

	best_rank: int | None = None

	for skill in profile.skills:
		canonical = taxonomy.canonicalize(skill.name) or skill.name.lower()
		is_ai_skill = canonical in _AI_SKILL_NAMES or skill.name.lower() in _AI_SKILL_NAMES
		if not is_ai_skill:
			# Also match domain-category skills whose canonical name overlaps AI terms
			cat = skill.category or taxonomy.get_category(canonical)
			if cat == "domain" and any(kw in canonical for kw in _AI_SKILL_NAMES):
				is_ai_skill = True
		if is_ai_skill and skill.scale:
			rank = _SCALE_RANK.get(skill.scale, 0)
			if best_rank is None or rank > best_rank:
				best_rank = rank

	if best_rank is None:
		return "personal"
	for scale_name, rank in _SCALE_RANK.items():
		if rank == best_rank:
			return scale_name
	return "personal"


# ---------------------------------------------------------------------------
# Best skill finder
# ---------------------------------------------------------------------------


def _find_best_skill(
	req: QuickRequirement,
	profile: MergedEvidenceProfile,
	depth_floor: DepthLevel,
) -> tuple[MergedSkillEvidence | None, str, str]:
	"""Find the best matching skill for a requirement across all mappings.

	Returns (best_match, best_status, match_type).
	match_type is "exact", "fuzzy", or "none".
	"""
	taxonomy = _get_taxonomy()
	best_match: MergedSkillEvidence | None = None
	best_status = "no_evidence"
	best_match_type = "none"

	for skill_name in req.skill_mapping:
		# Try direct match (exact, fuzzy, pattern)
		found, mtype = _find_skill_match(skill_name, profile)
		if found:
			status = _assess_depth_match(found, depth_floor, profile)
			if STATUS_RANK.get(status, 0) > STATUS_RANK.get(best_status, 0):
				best_match = found
				best_status = status
				best_match_type = mtype
			continue

		# Try related skill fallback — but don't cross categories for languages.
		# A language requirement (Go, Rust, etc.) should only match other languages,
		# not related tools (Docker, Kubernetes) that happen to be in the same ecosystem.
		canonical = taxonomy.match(skill_name)
		if not canonical:
			continue
		req_category = taxonomy.get_category(canonical)
		for profile_skill in profile.skills:
			profile_canonical = taxonomy.canonicalize(profile_skill.name)
			if taxonomy.are_related(canonical, profile_canonical):
				profile_category = taxonomy.get_category(profile_canonical)
				if req_category == "language" and profile_category != "language":
					continue  # Don't match a language req to a non-language skill
				if STATUS_RANK.get("related", 0) > STATUS_RANK.get(best_status, 0):
					best_match = profile_skill
					best_status = "related"
					best_match_type = "fuzzy"
				break  # Take first related match

	# AI-context penalty: requirements about AI teams or AI-powered metrics
	# shouldn't get full credit from generic leadership/product skills
	_AI_CONTEXT_WORDS = {"ai", "ml", "intelligence", "machine learning"}
	if best_match and best_match.name in (
		"leadership",
		"product-development",
		"problem-solving",
		"project-management",
	):
		req_lower = req.description.lower()
		has_ai_context = any(w in req_lower for w in _AI_CONTEXT_WORDS)
		has_team_or_scale = any(w in req_lower for w in ("team", "scale", "retention", "metrics"))
		if has_ai_context and has_team_or_scale:
			if STATUS_RANK.get(best_status, 0) > STATUS_RANK.get("partial_match", 0):
				best_status = "partial_match"

	# Years experience check: boost if candidate meets/exceeds, downgrade if short
	if req.years_experience and best_match and best_match.resume_duration:
		candidate_years = _parse_duration_years(best_match.resume_duration)
		if candidate_years:
			if candidate_years >= req.years_experience:
				# Boost status by one tier if not already exceeds
				if best_status == "partial_match":
					best_status = "strong_match"
				elif best_status == "adjacent":
					best_status = "partial_match"
			else:
				# Candidate has the skill but not enough years — downgrade
				# Use ratio: <50% of required → major, <100% → minor
				ratio = candidate_years / req.years_experience
				if ratio < 0.5:
					# Major shortfall (e.g. 3mo vs 2yr) — cap at partial_match
					if STATUS_RANK.get(best_status, 0) > STATUS_RANK.get("partial_match", 0):
						best_status = "partial_match"
				else:
					# Minor shortfall — cap at strong_match (no exceeds)
					if STATUS_RANK.get(best_status, 0) > STATUS_RANK.get("strong_match", 0):
						best_status = "strong_match"

	# Total years fallback: when no skill match but candidate has enough total experience
	if req.years_experience and best_status == "no_evidence":
		if (
			profile.total_years_experience
			and profile.total_years_experience >= req.years_experience
		):
			best_status = "related"
			best_match = MergedSkillEvidence(
				name="general_experience",
				source=EvidenceSource.RESUME_ONLY,
				effective_depth=DepthLevel.APPLIED,
				confidence=0.5,
			)
			best_match_type = "fuzzy"

	# Scale check: if requirement mentions consumer scale and skill is personal/team, downgrade
	if best_match and best_match.scale:
		required_scale = _detect_required_scale(req.description)
		if required_scale:
			_SCALE_RANK = {"personal": 0, "team": 1, "startup": 2, "enterprise": 3, "consumer": 4}
			skill_rank = _SCALE_RANK.get(best_match.scale, 2)
			req_rank = _SCALE_RANK.get(required_scale, 2)
			if req_rank - skill_rank >= 3:
				# Major scale gap (personal vs consumer) — cap at partial
				if STATUS_RANK.get(best_status, 0) > STATUS_RANK.get("partial_match", 0):
					best_status = "partial_match"
			elif req_rank - skill_rank >= 2:
				# Moderate gap (team vs consumer) — cap at strong_match
				if STATUS_RANK.get(best_status, 0) > STATUS_RANK.get("strong_match", 0):
					best_status = "strong_match"

	# AI-qualified scale check: when requirement mentions AI and a non-AI skill matched,
	# use the candidate's actual AI skill scale for the penalty instead.
	# This prevents general skills (system-design, product-development) with consumer
	# scale from masking that the candidate's AI experience is only at personal/team scale.
	if best_match and _requirement_mentions_ai(req.description):
		required_scale = _detect_required_scale(req.description)
		if required_scale:
			_SCALE_RANK = {"personal": 0, "team": 1, "startup": 2, "enterprise": 3, "consumer": 4}
			matched_rank = _SCALE_RANK.get(best_match.scale or "enterprise", 3)
			ai_scale = _candidate_ai_scale(profile)
			ai_rank = _SCALE_RANK.get(ai_scale or "personal", 0)
			req_rank = _SCALE_RANK.get(required_scale, 2)
			# Only override when AI scale is lower than the matched skill's scale
			# and the requirement's scale exceeds the AI scale
			if ai_rank < matched_rank and req_rank > ai_rank:
				gap = req_rank - ai_rank
				if gap >= 3:
					# Major AI scale gap — cap at partial_match
					if STATUS_RANK.get(best_status, 0) > STATUS_RANK.get("partial_match", 0):
						best_status = "partial_match"
				elif gap >= 2:
					# Moderate AI scale gap — cap at strong_match
					if STATUS_RANK.get(best_status, 0) > STATUS_RANK.get("strong_match", 0):
						best_status = "strong_match"

	return best_match, best_status, best_match_type
