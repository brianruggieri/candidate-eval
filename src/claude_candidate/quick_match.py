"""
QuickMatchEngine: Produces FitAssessments by comparing a MergedEvidenceProfile
against a parsed job posting and optional company profile.

Scores three dimensions with adaptive weighting based on company data richness:
1. Skill gap analysis (50–85% depending on data availability)
2. Company/mission alignment (10–25%)
3. Culture fit signals (5–25%)
"""

from __future__ import annotations

import math
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from claude_candidate.schemas.candidate_profile import DepthLevel, DEPTH_RANK, PatternType
from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.curated_resume import CandidateEligibility
from claude_candidate.skill_taxonomy import SkillTaxonomy
from claude_candidate.schemas.fit_assessment import (
	DimensionScore,
	EligibilityGate,
	FitAssessment,
	SkillMatchDetail,
	score_to_grade,
	score_to_verdict,
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
from claude_candidate.eligibility_evaluator import evaluate_gates


# ---------------------------------------------------------------------------
# Lazy-loaded taxonomy (module-level singleton)
# ---------------------------------------------------------------------------

_taxonomy: SkillTaxonomy | None = None


def _get_taxonomy() -> SkillTaxonomy:
	global _taxonomy
	if _taxonomy is None:
		_taxonomy = SkillTaxonomy.load_default()
	return _taxonomy


# ---------------------------------------------------------------------------
# Named constants (no magic numbers)
# ---------------------------------------------------------------------------

# Confidence thresholds for pattern-based evidence
PATTERN_CONFIDENCE_HIGH = 0.85
PATTERN_CONFIDENCE_LOW = 0.6

# Pattern frequency synthetic counts
PATTERN_FREQ_RARE = 3
PATTERN_FREQ_OCCASIONAL = 10
PATTERN_FREQ_COMMON = 25
PATTERN_FREQ_DOMINANT = 50

# Depth match rank offsets
DEPTH_EXCEEDS_OFFSET = 1

# Skill match status scores
STATUS_SCORE_EXCEEDS = 1.0
STATUS_SCORE_STRONG = 0.90
STATUS_SCORE_PARTIAL = 0.65
STATUS_SCORE_ADJACENT = 0.50
STATUS_SCORE_RELATED = 0.35
# No evidence floor: an experienced engineer has transferable skills
# even in areas not directly in their profile. 0.0 was too punitive.
STATUS_SCORE_NONE = 0.10

# Status ranking for "best match" selection
STATUS_RANK_EXCEEDS = 5
STATUS_RANK_STRONG = 4
STATUS_RANK_PARTIAL = 3
STATUS_RANK_ADJACENT = 2
STATUS_RANK_RELATED = 1
STATUS_RANK_NONE = 0

# Mission alignment score adjustments
MISSION_NEUTRAL_SCORE = 0.5
MISSION_DOMAIN_BONUS = 0.15
MISSION_TECH_OVERLAP_WEIGHT = 0.2
MISSION_TEXT_OVERLAP_WEIGHT = 0.15
MISSION_NO_ENRICHMENT_BASE = 0.3
MISSION_NO_ENRICHMENT_RANGE = 0.4
MISSION_SCORE_MAX = 1.0

# Culture fit score parameters
CULTURE_NEUTRAL_SCORE = 0.5
CULTURE_BASE_SCORE = 0.3
CULTURE_SIGNAL_WEIGHT = 0.6
CULTURE_ESTABLISHED_MATCH = 0.7
CULTURE_EMERGING_MATCH = 0.3
CULTURE_FULL_MATCH = 1
CULTURE_SCORE_MIN = 0.0
CULTURE_SCORE_MAX = 1.0

# Experience match score parameters
EXPERIENCE_NO_REQUIREMENT_SCORE = 0.9  # No requirement stated = effectively met
EXPERIENCE_NEUTRAL_SCORE = 0.5
EXPERIENCE_MET_BASE = 0.7
EXPERIENCE_EXCEED_BONUS = 0.3  # Bonus range for exceeding requirement
EXPERIENCE_SCORE_MAX = 1.0

# Education match score parameters
EDUCATION_NO_REQUIREMENT_SCORE = 0.9  # No requirement stated = effectively met
EDUCATION_NEUTRAL_SCORE = 0.5
EDUCATION_MET_SCORE = 0.9
EDUCATION_PARTIAL_SCORE = 0.5
EDUCATION_NO_MATCH_SCORE = 0.2

# Degree ranking for education comparison
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

# Display limits
TOP_SKILL_DETAILS = 5
MAX_TECH_OVERLAP_DISPLAY = 5
MAX_GAP_NAMES = 2
MAX_RESUME_ITEMS = 3
MAX_ACTION_ITEMS = 6

# Soft skill discount factor — reduces weight of soft skill requirements
SOFT_SKILL_DISCOUNT = 0.5
SOFT_SKILL_MAX_BOOST = 0.8  # maximum discount when culture signals fully align

# ---------------------------------------------------------------------------
# Eligibility filters — requirements that are gates, not skills
# ---------------------------------------------------------------------------

ELIGIBILITY_SKILL_NAMES: set[str] = {
	"us-work-authorization",
	"us_work_authorization",
	"work-authorization",
	"work_authorization",
	"travel",
	"relocation",
	"security-clearance",
	"clearance",
	"english",
	"mission_alignment",
	"mission-alignment",
	"visa",
	"visa-sponsorship",
}

ELIGIBILITY_DESCRIPTION_PATTERNS: list[str] = [
	r"(?i)authorized?\s+to\s+work",
	r"(?i)eligible\s+to\s+work",
	r"(?i)work\s+authorization",
	r"(?i)\d+%\s+travel",
	r"(?i)travel\s+\d+%",
	r"(?i)willing(ness)?\s+to\s+travel",
	r"(?i)comfortable\s+with\s+.*\s*travel",
	r"(?i)security\s+clearance",
	r"(?i)believe\s+in.*mission",
	r"(?i)(advanced|fluent|native)\s+(english|spanish|french|german|mandarin)",
	r"(?i)must\s+be\s+(a\s+)?us\s+(citizen|resident)",
	r"(?i)relo(cate|cation)",
]


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


# Rounding precision
SCORE_PRECISION = 3
TIMING_PRECISION = 2


def _soft_skill_discount(
	culture_signals: list[str] | None,
	company_profile: "CompanyProfile | None",
) -> float:
	"""Compute soft skill weight discount, modulated by culture signal strength.

	Base discount is SOFT_SKILL_DISCOUNT (0.5). When a CompanyProfile with
	culture_keywords is available, the discount is boosted up to SOFT_SKILL_MAX_BOOST (0.8)
	based on the overlap ratio between posting culture_signals and company culture_keywords.
	"""
	if not company_profile or not company_profile.culture_keywords:
		return SOFT_SKILL_DISCOUNT
	if not culture_signals:
		return SOFT_SKILL_DISCOUNT
	company_kw = {kw.lower() for kw in company_profile.culture_keywords}
	posting_signals = {s.lower() for s in culture_signals}
	if not posting_signals:
		return SOFT_SKILL_DISCOUNT
	overlap = len(posting_signals & company_kw)
	ratio = overlap / len(posting_signals)
	return SOFT_SKILL_DISCOUNT + ratio * (SOFT_SKILL_MAX_BOOST - SOFT_SKILL_DISCOUNT)


# ---------------------------------------------------------------------------
# Match-time confidence (v0.7)
# ---------------------------------------------------------------------------

_GENERIC_SKILLS = frozenset({
	"software-engineering",
	"computer-science",
	"problem-solving",
	"communication",
	"collaboration",
	"leadership",
	"ownership",
	"adaptability",
	"agile",
	"metrics",
})

_SKILL_VARIANTS: dict[str, list[str]] = {
	# Languages / frameworks
	"typescript": ["ts", "type script"],
	"javascript": ["js", "java script"],
	"python": ["py"],
	"react": ["react.js", "reactjs"],
	"vue": ["vue.js", "vuejs"],
	"angular": ["angular.js", "angularjs"],
	"node": ["node.js", "nodejs"],
	"cpp": ["c++"],
	"csharp": ["c#"],
	"golang": ["go lang"],
	# Soft skills — morphological variants so "adaptability" matches "adaptable"
	"adaptability": ["adaptable", "adapt quickly", "quick learner"],
	"collaboration": ["collaborate", "collaborative", "cross-functional"],
	"communication": ["communicate", "communicator"],
	"leadership": ["lead", "leading", "led teams", "team lead"],
	"ownership": ["own", "end-to-end ownership", "take ownership"],
	"problem-solving": ["problem solver", "solve problems", "analytical"],
	"agile": ["scrum", "sprint", "kanban", "iterative"],
	# Practices
	"software-engineering": ["software development", "software developer", "engineering experience"],
	"project-management": ["project management", "manage projects", "technical project"],
	"testing": ["test", "quality assurance", "qa", "evaluation data"],
	"product-development": ["shipping products", "building products", "ship products", "personal projects"],
	"technology-research": ["passion for ai", "curiosity for ai", "keeps up with trends", "emerging innovations"],
}


def _is_generic_skill(skill: str) -> bool:
	"""Return True if the skill is a broad/generic term unlikely to match specific roles."""
	return skill in _GENERIC_SKILLS


def _skill_mentioned_in_text(skill: str, text: str) -> bool:
	"""Check if the skill or common variants appear in the text.

	Both ``skill`` and ``text`` must already be lowercased.
	"""
	# Direct name check (also try hyphen↔space since canonical names use hyphens)
	if skill in text:
		return True
	dehyphenated = skill.replace("-", " ")
	if dehyphenated != skill and dehyphenated in text:
		return True
	# Common variant checks
	for variant in _SKILL_VARIANTS.get(skill, []):
		if variant in text:
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
# Lookup tables
# ---------------------------------------------------------------------------

# Minimum depth required for each seniority level
SENIORITY_DEPTH_FLOOR: dict[str, DepthLevel] = {
	"junior": DepthLevel.USED,
	"mid": DepthLevel.APPLIED,
	"senior": DepthLevel.DEEP,
	"staff": DepthLevel.DEEP,
	"principal": DepthLevel.EXPERT,
	"director": DepthLevel.DEEP,
	"unknown": DepthLevel.APPLIED,
}

# Pattern strength → DepthLevel
PATTERN_STRENGTH_TO_DEPTH: dict[str, DepthLevel] = {
	"emerging": DepthLevel.USED,
	"established": DepthLevel.APPLIED,
	"strong": DepthLevel.DEEP,
	"exceptional": DepthLevel.EXPERT,
}

# Pattern frequency → synthetic session count
PATTERN_FREQ_TO_COUNT: dict[str, int] = {
	"rare": PATTERN_FREQ_RARE,
	"occasional": PATTERN_FREQ_OCCASIONAL,
	"common": PATTERN_FREQ_COMMON,
	"dominant": PATTERN_FREQ_DOMINANT,
}

# Match status → numeric score
STATUS_SCORE: dict[str, float] = {
	"exceeds": STATUS_SCORE_EXCEEDS,
	"strong_match": STATUS_SCORE_STRONG,
	"partial_match": STATUS_SCORE_PARTIAL,
	"adjacent": STATUS_SCORE_ADJACENT,
	"related": STATUS_SCORE_RELATED,
	"no_evidence": STATUS_SCORE_NONE,
}

# Match status → rank for comparison
STATUS_RANK: dict[str, int] = {
	"exceeds": STATUS_RANK_EXCEEDS,
	"strong_match": STATUS_RANK_STRONG,
	"partial_match": STATUS_RANK_PARTIAL,
	"adjacent": STATUS_RANK_ADJACENT,
	"related": STATUS_RANK_RELATED,
	"no_evidence": STATUS_RANK_NONE,
}

# Match status → display marker
STATUS_MARKER: dict[str, str] = {
	"exceeds": "++",
	"strong_match": "+",
	"partial_match": "~",
	"adjacent": "?",
	"related": "~?",
	"no_evidence": "-",
}

# Verdict → explanatory text
VERDICT_TEXT: dict[str, str] = {
	"strong_yes": "This is a strong fit worth pursuing.",
	"yes": "This is a solid fit that merits an application.",
	"maybe": (
		"This is a mixed fit — worth applying if the role excites you, but expect gaps to come up."
	),
	"probably_not": (
		"Significant gaps exist. Consider whether the role aligns "
		"with your growth goals before applying."
	),
	"no": ("Fundamental misalignment between your profile and this role's requirements."),
}

# Evidence source → human-readable label
SOURCE_LABEL: dict[EvidenceSource, str] = {
	EvidenceSource.CORROBORATED: "Corroborated by both resume and sessions",
	EvidenceSource.SESSIONS_ONLY: "Demonstrated in sessions (not on resume)",
	EvidenceSource.RESUME_ONLY: "Listed on resume (no session evidence)",
	EvidenceSource.CONFLICTING: "Resume depth anchored; sessions provided additional signal",
}

# Industry/domain keywords — non-technical terms that appear repeatedly in domain-specific JDs.
# If any of these appears in 3+ requirements but is absent from the candidate's profile,
# the grade is capped at B+ (domain fit cannot be proven without evidence).
DOMAIN_KEYWORDS: frozenset[str] = frozenset({
	# Music / audio
	"music", "audio", "sound", "recording", "podcast",
	# Sports
	"sports", "baseball", "football", "basketball", "soccer", "athletics",
	# Healthcare / biotech
	"healthcare", "medical", "clinical", "patient", "biotech", "pharma",
	"bioinformatics", "genomics",
	# Finance
	"fintech", "banking", "financial", "trading", "insurance",
	# Legal
	"legal", "compliance", "regulatory",
	# Automotive
	"automotive", "vehicle",
	# Education
	"edtech", "educational", "curriculum",
	# Gaming / game engines
	"gaming", "esports", "gameplay", "unreal",
	# Real estate
	"real estate", "construction",
	# Energy
	"energy", "utilities",
	# Retail / logistics
	"retail", "ecommerce", "logistics",
	# Hardware / embedded
	"firmware", "embedded",
	# Native mobile platforms
	"ios", "android",
	# Data infrastructure
	"etl", "warehouse",
})


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
	for project in (profile.projects or []):
		candidate_parts.append(project.project_name.lower())
	for role in (profile.roles or []):
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

# Pattern strength → culture match value
CULTURE_PATTERN_STRENGTH_SCORE: dict[str, float] = {
	"exceptional": 1.0,
	"strong": 1.0,
	"established": CULTURE_ESTABLISHED_MATCH,
	"emerging": CULTURE_EMERGING_MATCH,
}


# ---------------------------------------------------------------------------
# Data transfer objects (reduce positional parameter counts)
# ---------------------------------------------------------------------------


@dataclass
class AssessmentInput:
	"""Groups the inputs for an assessment to keep parameter counts low."""

	requirements: list[QuickRequirement]
	company: str
	title: str
	posting_url: str | None = None
	source: str = "paste"
	seniority: str = "unknown"
	culture_signals: list[str] | None = None
	tech_stack: list[str] | None = None
	company_profile: CompanyProfile | None = None
	curated_eligibility: CandidateEligibility = field(default_factory=CandidateEligibility)


@dataclass
class SummaryInput:
	"""Groups summary-generation inputs."""

	overall_score: float
	skill_dim: DimensionScore
	company: str
	title: str
	must_coverage: str
	mission_dim: DimensionScore | None = None
	culture_dim: DimensionScore | None = None
	experience_dim: DimensionScore | None = None
	education_dim: DimensionScore | None = None


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
	"""
	MIN_SUBSTRING_LEN = 3
	for skill in profile.skills:
		# Substring match only when the shorter string is long enough
		shorter_len = min(len(normalized), len(skill.name))
		if shorter_len >= MIN_SUBSTRING_LEN:
			if normalized in skill.name or skill.name in normalized:
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
# Virtual skill inference: synthesize compound skills from constituents
# ---------------------------------------------------------------------------

# Maps a virtual skill name to (required_any, min_count, inferred_depth).
# If the profile contains >= min_count skills from required_any, the virtual
# skill is inferred at inferred_depth.
VIRTUAL_SKILL_RULES: list[tuple[str, list[str], int, DepthLevel]] = [
	# full-stack: need frontend + backend evidence
	(
		"full-stack",
		[
			"react",
			"vue",
			"angular",
			"nextjs",
			"frontend-development",
			"node.js",
			"python",
			"fastapi",
			"api-design",
			"backend-development",
		],
		2,
		DepthLevel.DEEP,
	),
	# software-engineering: need multiple programming skills
	(
		"software-engineering",
		[
			"python",
			"typescript",
			"javascript",
			"react",
			"node.js",
			"ci-cd",
			"git",
			"testing",
			"api-design",
		],
		3,
		DepthLevel.DEEP,
	),
	# frontend-development: need a frontend framework
	("frontend-development", ["react", "vue", "angular", "nextjs", "html-css"], 1, DepthLevel.DEEP),
	# backend-development: need a backend stack
	(
		"backend-development",
		["python", "node.js", "fastapi", "api-design", "postgresql", "sql"],
		2,
		DepthLevel.DEEP,
	),
	# system-design: architecture pattern or multiple system skills
	(
		"system-design",
		[
			"api-design",
			"distributed-systems",
			"cloud-infrastructure",
			"software-engineering",
			"postgresql",
			"docker",
			"kubernetes",
		],
		2,
		DepthLevel.APPLIED,
	),
	# testing: testing pattern or pytest
	("testing", ["pytest", "ci-cd"], 1, DepthLevel.DEEP),
	# devops: container/infra tooling
	(
		"devops",
		["docker", "kubernetes", "ci-cd", "terraform", "aws", "gcp", "azure"],
		2,
		DepthLevel.APPLIED,
	),
	# cloud-infrastructure: cloud providers
	(
		"cloud-infrastructure",
		["aws", "gcp", "azure", "docker", "kubernetes", "terraform"],
		2,
		DepthLevel.APPLIED,
	),
	# data-science: analytics background
	("data-science", ["sql", "python", "metabase", "postgresql"], 2, DepthLevel.APPLIED),
	# computer-science: implied by deep engineering experience
	(
		"computer-science",
		["python", "typescript", "javascript", "sql", "api-design", "software-engineering"],
		3,
		DepthLevel.APPLIED,
	),
	# product-development: full-stack + shipping evidence
	(
		"product-development",
		["react", "node.js", "python", "prototyping", "api-design", "ci-cd", "full-stack"],
		2,
		DepthLevel.APPLIED,
	),
	# production-systems: deployment + testing + infra
	(
		"production-systems",
		["ci-cd", "docker", "testing", "aws", "gcp", "azure", "postgresql", "devops"],
		2,
		DepthLevel.APPLIED,
	),
	# startup-experience: prototyping + shipping evidence
	(
		"startup-experience",
		["prototyping", "full-stack", "product-development", "ci-cd", "api-design", "ownership"],
		2,
		DepthLevel.APPLIED,
	),
	# metrics: analytics tools + data skills
	("metrics", ["metabase", "sql", "data-science", "postgresql"], 1, DepthLevel.APPLIED),
	# developer-tools: builds tools for developers
	(
		"developer-tools",
		["ci-cd", "git", "testing", "software-engineering", "api-design", "llm"],
		2,
		DepthLevel.DEEP,
	),
	# open-source: git + collaborative development
	(
		"open-source",
		["git", "ci-cd", "software-engineering", "collaboration"],
		2,
		DepthLevel.APPLIED,
	),
]

# Maps behavioral pattern types to taxonomy skills they imply.
PATTERN_TO_SKILL: dict[str, list[tuple[str, DepthLevel]]] = {
	"architecture_first": [
		("system-design", DepthLevel.DEEP),
		("software-engineering", DepthLevel.DEEP),
	],
	"testing_instinct": [("testing", DepthLevel.DEEP)],
	"modular_thinking": [("software-engineering", DepthLevel.DEEP)],
	"iterative_refinement": [("agile", DepthLevel.APPLIED), ("prototyping", DepthLevel.APPLIED)],
}

# Minimum total years for leadership/software-engineering inference
YEARS_LEADERSHIP_THRESHOLD = 8.0
YEARS_SOFTWARE_ENG_THRESHOLD = 5.0

# Adoption velocity composite constants
ADOPTION_BREADTH_WEIGHT = 0.15
ADOPTION_NOVELTY_WEIGHT = 0.25
ADOPTION_RAMP_WEIGHT = 0.30
ADOPTION_META_WEIGHT = 0.15
ADOPTION_TOOL_WEIGHT = 0.15

ADOPTION_NOVELTY_RECENCY_CUTOFF = 0.7  # last 30% of date range is "recent"
ADOPTION_NOVELTY_TARGET = 5  # 5+ novel skills = 1.0 novelty score
ADOPTION_BREADTH_TARGET = 5  # 5+ categories at applied+ = 1.0 breadth score
ADOPTION_CONFIDENCE_DIVISOR = 10.0  # evidence_count / 10 = confidence
ADOPTION_RAMP_NORMALIZER = 2.87  # log1p(50/3): benchmark for a strong ramp

ADOPTION_DEPTH_EXPERT = 0.8
ADOPTION_DEPTH_DEEP = 0.6
ADOPTION_DEPTH_APPLIED = 0.4
ADOPTION_DEPTH_USED = 0.2

ADOPTION_STRENGTH_MAP: dict[str, float] = {
	"exceptional": 1.0,
	"strong": 0.8,
	"established": 0.6,
	"emerging": 0.3,
}


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
			# If any matched constituent has session evidence, the virtual skill is
			# session-derived; otherwise it is inferred from resume/repo evidence only.
			# This prevents sessions_only labels when sessions are parked (merge_triad).
			session_sources = {EvidenceSource.SESSIONS_ONLY, EvidenceSource.CORROBORATED}
			has_session_evidence = any(
				s.source in session_sources
				for s in profile.skills
				if s.name.lower() in constituents
			)
			virtual_source = (
				EvidenceSource.SESSIONS_ONLY if has_session_evidence else EvidenceSource.RESUME_ONLY
			)
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
# Skill scoring helpers
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
	if best_match and best_match.name in ("leadership", "product-development", "problem-solving", "project-management"):
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


_SCALE_KEYWORDS: list[tuple[str, str]] = [
	("consumer scale", "consumer"),
	("at consumer scale", "consumer"),
	("millions of users", "consumer"),
	("millions of conversations", "consumer"),
	("consumer-facing", "consumer"),
	("at scale", "enterprise"),  # generic "at scale" → enterprise minimum
	("enterprise scale", "enterprise"),
	("production scale", "enterprise"),
]


def _detect_required_scale(text: str) -> str | None:
	"""Detect if a requirement specifies a scale level."""
	text_lower = text.lower()
	for keyword, scale in _SCALE_KEYWORDS:
		if keyword in text_lower:
			return scale
	return None


_AI_KEYWORDS_RE = re.compile(
	r"\b(ai|ml|machine\s+learning|intelligence|llm|deep\s+learning|neural|model|generative|agentic)\b",
	re.IGNORECASE,
)

_AI_SKILL_NAMES: frozenset[str] = frozenset({
	"llm",
	"machine-learning",
	"agentic-workflows",
	"prompt-engineering",
	"rag",
	"embeddings",
	"generative-ai",
})


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


def _score_requirement(
	best_match: MergedSkillEvidence | None,
	best_status: str,
	priority: RequirementPriority = RequirementPriority.MUST_HAVE,
) -> float:
	"""Compute the score for one requirement given its best match.

	Match status drives the score. Confidence applies as a minor adjustment
	(±10%) rather than a multiplicative penalty, since match status already
	encodes quality and the old confidence × status multiplication created
	an artificial ceiling around A-.

	No-evidence scoring is priority-dependent:
	- must_have/strong_preference: 0.0 (hard gaps should hurt)
	- nice_to_have/implied: STATUS_SCORE_NONE floor (transferable skills)
	"""
	if best_status == "no_evidence":
		if priority in (RequirementPriority.MUST_HAVE, RequirementPriority.STRONG_PREFERENCE):
			return 0.0
		return STATUS_SCORE_NONE

	req_score = STATUS_SCORE.get(best_status, STATUS_SCORE_NONE)
	if best_match:
		# Apply confidence as a minor (±10%) adjustment to the base status score.
		# confidence may be None (v0.7 merge_triad) — default to 1.0 (no penalty).
		conf = best_match.confidence if best_match.confidence is not None else 1.0
		adjustment = 0.90 + 0.10 * conf
		req_score *= adjustment
	return req_score


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
	"""Score mission text alignment; return (bonus, detail_lines).

	Computes keyword overlap between the company's mission statement /
	product description and the candidate's skill names and project technologies.
	Uses word-boundary matching to avoid false positives (e.g. "go" inside "good").
	Only keywords of 3+ characters are considered to reduce noise.
	"""
	text_sources = []
	if company_profile.mission_statement:
		text_sources.append(company_profile.mission_statement)
	text_sources.append(company_profile.product_description)
	if not text_sources:
		return 0.0, []

	combined_text = " ".join(text_sources).lower()
	candidate_keywords: set[str] = {s.name.lower() for s in profile.skills}
	for proj in profile.projects:
		for tech in proj.technologies:
			candidate_keywords.add(tech.lower())

	# Filter out very short keywords and use word-boundary matching
	matched = {
		kw
		for kw in candidate_keywords
		if len(kw) >= 3 and re.search(rf"\b{re.escape(kw)}\b", combined_text)
	}
	if not matched:
		return 0.0, []

	ratio = len(matched) / max(len(candidate_keywords), 1)
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
# Culture fit helpers
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
# Adaptive dimension weighting
# ---------------------------------------------------------------------------

# Weight tuples: (skill, mission, culture)
_WEIGHTS_RICH = (0.50, 0.25, 0.25)
_WEIGHTS_MODERATE = (0.60, 0.20, 0.20)
_WEIGHTS_SPARSE = (0.70, 0.15, 0.15)
_WEIGHTS_NONE = (0.85, 0.10, 0.05)


def _redistribute_culture_weight(
	skill_w: float,
	mission_w: float,
	culture_w: float,
) -> tuple[float, float]:
	"""Redistribute culture weight proportionally to skill and mission.

	Returns (new_skill_w, new_mission_w) — culture weight becomes 0 at call site.
	"""
	total_remaining = skill_w + mission_w
	if total_remaining == 0.0:
		# Degenerate case: split evenly
		half = culture_w / 2.0
		return skill_w + half, mission_w + half
	skill_ratio = skill_w / total_remaining
	mission_ratio = mission_w / total_remaining
	return skill_w + culture_w * skill_ratio, mission_w + culture_w * mission_ratio


def _compute_weights(
	company_profile: CompanyProfile | None,
) -> tuple[float, float, float]:
	"""Return (skill_weight, mission_weight, culture_weight) based on company data richness.

	Tiers (based on CompanyProfile.enrichment_quality):
	  rich     → 50/25/25
	  moderate → 60/20/20
	  sparse   → 70/15/15
	  None     → 85/10/5   (no company data at all)
	"""
	if company_profile is None:
		return _WEIGHTS_NONE
	quality = company_profile.enrichment_quality
	if quality == "rich":
		return _WEIGHTS_RICH
	if quality == "moderate":
		return _WEIGHTS_MODERATE
	return _WEIGHTS_SPARSE


# ---------------------------------------------------------------------------
# Assessment result builders
# ---------------------------------------------------------------------------


def _compute_overall_score(
	skill_dim: DimensionScore,
	mission_dim: DimensionScore | None = None,
	culture_dim: DimensionScore | None = None,
	experience_dim: DimensionScore | None = None,
	education_dim: DimensionScore | None = None,
) -> float:
	"""Compute weighted overall score from available dimensions."""
	total = skill_dim.score * skill_dim.weight
	for dim in (mission_dim, culture_dim, experience_dim, education_dim):
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


# ---------------------------------------------------------------------------
# QuickMatchEngine
# ---------------------------------------------------------------------------


class QuickMatchEngine:
	"""
	Produces FitAssessments against a cached MergedEvidenceProfile.

	The profile is loaded once; multiple job postings can be assessed against it.
	"""

	def __init__(self, profile: MergedEvidenceProfile):
		self.profile = profile

	def assess(
		self,
		requirements: list[QuickRequirement],
		company: str,
		title: str,
		posting_url: str | None = None,
		source: str = "paste",
		seniority: str = "unknown",
		culture_signals: list[str] | None = None,
		tech_stack: list[str] | None = None,
		company_profile: CompanyProfile | None = None,
		curated_eligibility: CandidateEligibility | None = None,
		elapsed: float | None = None,
	) -> FitAssessment:
		"""Run the three-dimensional fit assessment."""
		inp = AssessmentInput(
			requirements=requirements,
			company=company,
			title=title,
			posting_url=posting_url,
			source=source,
			seniority=seniority,
			culture_signals=culture_signals,
			tech_stack=tech_stack,
			company_profile=company_profile,
			curated_eligibility=curated_eligibility or CandidateEligibility(),
		)
		return self._run_assessment(inp, elapsed=elapsed)

	# -- orchestration ------------------------------------------------------

	def _run_assessment(self, inp: AssessmentInput, elapsed: float | None = None) -> FitAssessment:
		"""Orchestrate scoring dimensions and assemble the result.

		Partial assessment: scores skill_match (50%), experience_match (30%),
		education_match (20%) — mission and culture are left as None.
		"""
		start_time = time.time() if elapsed is None else 0.0

		# Partition: separate eligibility gates from scorable requirements.
		# Apply heuristic denylist as fallback for cached pre-Plan-9 postings.
		eligibility_reqs = [r for r in inp.requirements if _infer_eligibility(r)]
		scorable_reqs = [r for r in inp.requirements if not _infer_eligibility(r)]
		eligibility_gates = evaluate_gates(eligibility_reqs, inp.curated_eligibility)
		eligibility_passed = not any(g.status == "unmet" for g in eligibility_gates)

		skill_dim, skill_details = self._score_skill_match(
			scorable_reqs,
			inp.seniority,
			culture_signals=inp.culture_signals,
			company_profile=inp.company_profile,
		)
		experience_dim = self._score_experience_match(
			scorable_reqs,
			inp.seniority,
		)
		education_dim = self._score_education_match(
			scorable_reqs,
			inp.tech_stack or [],
		)

		# Partial-assessment weights: skill-heavy so unmatched technical
		# requirements properly suppress scores. Experience/education default
		# to 0.9 when not stated, so lower their weight to avoid inflating.
		skill_dim.weight = 0.65
		experience_dim.weight = 0.25
		education_dim.weight = 0.10

		# Cap experience/education scores when skill match is weak.
		# Prevents generic experience from rescuing a poor technical fit.
		if skill_dim.score < 0.55:
			experience_dim.score = min(experience_dim.score, skill_dim.score + 0.2)
			education_dim.score = min(education_dim.score, skill_dim.score + 0.2)

		overall_score = _compute_overall_score(
			skill_dim,
			experience_dim=experience_dim,
			education_dim=education_dim,
		)
		pre_cap_grade: str | None = None
		unmet_gates = [g for g in eligibility_gates if g.status == "unmet"]
		if unmet_gates:
			pre_cap_grade = score_to_grade(overall_score)
			overall_score = 0.0

		# Domain penalty: cap at B+ if industry domain appears 3+ times in requirements
		# but is absent from the candidate's profile.
		_GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]
		domain_gap_term = _detect_domain_gap(scorable_reqs, self.profile)
		if domain_gap_term and not unmet_gates:  # eligibility cap already zeros score; skip
			candidate_grade = score_to_grade(overall_score)
			if _GRADE_ORDER.index(candidate_grade) < _GRADE_ORDER.index("B+"):
				if pre_cap_grade is None:
					pre_cap_grade = candidate_grade
				# Drop score to top of B+ band (just below A- threshold of 0.85)
				overall_score = min(overall_score, 0.849)

		partial_percentage = round(overall_score * 100, 1)

		if elapsed is None:
			elapsed = time.time() - start_time
		return self._build_assessment(
			inp,
			skill_dim,
			None,
			None,
			skill_details,
			overall_score,
			elapsed,
			experience_dim=experience_dim,
			education_dim=education_dim,
			partial_percentage=partial_percentage,
			eligibility_gates=eligibility_gates,
			eligibility_passed=eligibility_passed,
			scorable_reqs=scorable_reqs,
			pre_cap_grade=pre_cap_grade,
			domain_gap_term=domain_gap_term,
		)

	def _build_assessment(
		self,
		inp: AssessmentInput,
		skill_dim: DimensionScore,
		mission_dim: DimensionScore | None,
		culture_dim: DimensionScore | None,
		skill_details: list[SkillMatchDetail],
		overall_score: float,
		elapsed: float,
		experience_dim: DimensionScore | None = None,
		education_dim: DimensionScore | None = None,
		partial_percentage: float | None = None,
		eligibility_gates: list[EligibilityGate] | None = None,
		eligibility_passed: bool = True,
		scorable_reqs: list[QuickRequirement] | None = None,
		pre_cap_grade: str | None = None,
		domain_gap_term: str | None = None,
	) -> FitAssessment:
		"""Assemble the final FitAssessment from scored dimensions."""
		reqs_for_gaps = scorable_reqs if scorable_reqs is not None else inp.requirements
		must_cov = _must_have_coverage(skill_details)
		strongest, biggest_gap = _strongest_and_gap(skill_details)
		resume_gaps = _discover_resume_gaps(self.profile, reqs_for_gaps)
		resume_unverified = _find_resume_unverified(self.profile, reqs_for_gaps)
		gaps = [
			d
			for d in skill_details
			if d.match_status == "no_evidence" and d.priority in ("must_have", "strong_preference")
		]
		summary_inp = SummaryInput(
			overall_score=overall_score,
			skill_dim=skill_dim,
			company=inp.company,
			title=inp.title,
			must_coverage=must_cov,
			mission_dim=mission_dim,
			culture_dim=culture_dim,
			experience_dim=experience_dim,
			education_dim=education_dim,
		)
		return self._assemble_fit_assessment(
			inp,
			summary_inp,
			skill_dim,
			mission_dim,
			culture_dim,
			skill_details,
			strongest,
			biggest_gap,
			resume_gaps,
			resume_unverified,
			gaps,
			overall_score,
			elapsed,
			experience_dim=experience_dim,
			education_dim=education_dim,
			partial_percentage=partial_percentage,
			eligibility_gates=eligibility_gates or [],
			eligibility_passed=eligibility_passed,
			pre_cap_grade=pre_cap_grade,
			domain_gap_term=domain_gap_term,
		)

	def _assemble_fit_assessment(
		self,
		inp: AssessmentInput,
		summary_inp: SummaryInput,
		skill_dim: DimensionScore,
		mission_dim: DimensionScore | None,
		culture_dim: DimensionScore | None,
		skill_details: list[SkillMatchDetail],
		strongest: str,
		biggest_gap: str,
		resume_gaps: list[str],
		resume_unverified: list[str],
		gaps: list[SkillMatchDetail],
		overall_score: float,
		elapsed: float,
		experience_dim: DimensionScore | None = None,
		education_dim: DimensionScore | None = None,
		partial_percentage: float | None = None,
		eligibility_gates: list[EligibilityGate] | None = None,
		eligibility_passed: bool = True,
		pre_cap_grade: str | None = None,
		domain_gap_term: str | None = None,
	) -> FitAssessment:
		"""Construct the FitAssessment pydantic model."""
		is_partial = mission_dim is None and culture_dim is None
		overall_summary = self._generate_summary(summary_inp)
		action_items = self._generate_action_items(
			overall_score,
			gaps,
			resume_gaps,
			resume_unverified,
			inp.company,
		)
		if pre_cap_grade is not None:
			blocker_descriptions = "; ".join(
				g.description for g in (eligibility_gates or []) if g.status == "unmet"
			)
			overall_summary = (
				f"Eligibility blocked: {blocker_descriptions}. "
				f"Skill fit would be {pre_cap_grade} if eligible."
			)
			action_items = [
				f"Eligibility: {blocker_descriptions} — skip this role",
				*action_items[:5],
			]
		return FitAssessment(
			assessment_id=str(uuid.uuid4()),
			assessed_at=datetime.now(),
			job_title=inp.title,
			company_name=inp.company,
			posting_url=inp.posting_url,
			source=inp.source,
			assessment_phase="partial" if is_partial else "full",
			partial_percentage=partial_percentage,
			overall_score=round(overall_score, SCORE_PRECISION),
			overall_grade=score_to_grade(overall_score),
			overall_summary=overall_summary,
			skill_match=skill_dim,
			experience_match=experience_dim,
			education_match=education_dim,
			mission_alignment=mission_dim,
			culture_fit=culture_dim,
			skill_matches=skill_details,
			must_have_coverage=summary_inp.must_coverage,
			strongest_match=strongest,
			biggest_gap=biggest_gap,
			resume_gaps_discovered=resume_gaps,
			resume_unverified=resume_unverified,
			company_profile_summary=(
				inp.company_profile.product_description
				if inp.company_profile
				else f"No enrichment data available for {inp.company}"
			),
			company_enrichment_quality=(
				inp.company_profile.enrichment_quality if inp.company_profile else "none"
			),
			eligibility_gates=eligibility_gates or [],
			eligibility_passed=eligibility_passed,
			domain_gap_term=domain_gap_term,
			should_apply=score_to_verdict(overall_score),
			action_items=action_items,
			profile_hash=self.profile.profile_hash,
			time_to_assess_seconds=round(elapsed, TIMING_PRECISION),
		)

	# -- dimension 1: skill match -------------------------------------------

	def _score_skill_match(
		self,
		requirements: list[QuickRequirement],
		seniority: str,
		culture_signals: list[str] | None = None,
		company_profile: CompanyProfile | None = None,
	) -> tuple[DimensionScore, list[SkillMatchDetail]]:
		"""Score the skill gap analysis dimension."""
		depth_floor = SENIORITY_DEPTH_FLOOR.get(seniority, DepthLevel.APPLIED)
		details: list[SkillMatchDetail] = []
		weighted_score = 0.0
		total_weight = 0.0
		taxonomy = _get_taxonomy()
		effective_discount = _soft_skill_discount(culture_signals, company_profile)

		for req in requirements:
			weight = PRIORITY_WEIGHT.get(req.priority, 1.0)

			# Discount soft skill requirements
			is_soft_skill = False
			for skill_name in req.skill_mapping:
				canonical = taxonomy.match(skill_name)
				if canonical and taxonomy.get_category(canonical) == "soft_skill":
					is_soft_skill = True
					break
			if is_soft_skill:
				weight *= effective_discount

			total_weight += weight
			best_match, best_status, best_match_type = _find_best_skill(
				req,
				self.profile,
				depth_floor,
			)
			req_score = _score_requirement(best_match, best_status, req.priority)

			# Compound scoring: also check average of all constituent skills
			if len(req.skill_mapping) > 1:
				all_scores = []
				for skill_name in req.skill_mapping:
					found, _mtype = _find_skill_match(skill_name, self.profile)
					if found:
						status = _assess_depth_match(found, depth_floor, self.profile)
						conf = found.confidence if found.confidence is not None else 1.0
						adj = 0.90 + 0.10 * conf
						all_scores.append(STATUS_SCORE.get(status, 0.0) * adj)
					else:
						all_scores.append(0.0)
				avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
				req_score = max(req_score, avg_score)

			weighted_score += req_score * weight
			details.append(_build_skill_detail(req, best_match, best_status, best_match_type))

		score = weighted_score / total_weight if total_weight > 0 else 0.0
		return _build_skill_dimension(score, details), details

	# -- dimension 2: mission alignment -------------------------------------

	def _score_mission_alignment(
		self,
		company: str,
		tech_stack: list[str],
		company_profile: CompanyProfile | None,
	) -> DimensionScore:
		"""Score company/mission alignment."""
		if company_profile:
			score, details = self._mission_with_profile(company_profile)
		else:
			score, details = _mission_from_posting(self.profile, tech_stack)

		if not details:
			details = ["Insufficient data for mission alignment assessment"]

		return DimensionScore(
			dimension="mission_alignment",
			score=round(score, SCORE_PRECISION),
			grade=score_to_grade(score),
			summary=f"Mission alignment with {company}: {score_to_grade(score)}",
			details=details,
		)

	def _mission_with_profile(
		self,
		company_profile: CompanyProfile,
	) -> tuple[float, list[str]]:
		"""Score mission alignment using three signals when a company profile is available.

		Signals:
		1. Tech stack overlap — company's known technologies vs candidate skills
		2. Industry/domain match — company's product domain vs candidate project domains
		3. Mission text alignment — keyword overlap between mission text and candidate skills
		"""
		score = MISSION_NEUTRAL_SCORE
		details: list[str] = []

		domain_bonus, domain_details = _score_domain_overlap(
			self.profile,
			company_profile,
		)
		score += domain_bonus
		details.extend(domain_details)

		tech_bonus, tech_details = _score_tech_overlap(
			self.profile,
			company_profile,
		)
		score += tech_bonus
		details.extend(tech_details)

		text_bonus, text_details = _score_mission_text_alignment(
			self.profile,
			company_profile,
		)
		score += text_bonus
		details.extend(text_details)

		return min(score, MISSION_SCORE_MAX), details

	# -- dimension 3: culture fit -------------------------------------------

	def _score_culture_fit(
		self,
		culture_signals: list[str],
		company_profile: CompanyProfile | None,
	) -> DimensionScore:
		"""Score culture/working style fit via direct pattern matching.

		Compares each culture signal to the candidate's observed behavioral
		patterns. If no signals are present, or if the candidate has no
		patterns, marks insufficient_data=True.
		"""
		all_signals = self._collect_culture_signals(
			culture_signals,
			company_profile,
		)
		if not self.profile.patterns:
			return None  # No behavioral data (sessions parked) — omit dimension
		if not all_signals:
			return self._neutral_culture_dimension()

		matches, total_signals, details = self._evaluate_culture_signals(
			all_signals,
		)
		score = self._compute_culture_score(matches, total_signals)

		if company_profile and company_profile.remote_policy != "unknown":
			policy = company_profile.remote_policy.replace("_", " ")
			details.append(f"Work policy: {policy}")

		if not details:
			details = ["Culture alignment assessment based on available signals"]

		confidence = matches / total_signals if total_signals > 0 else 0.0

		return DimensionScore(
			dimension="culture_fit",
			score=round(score, SCORE_PRECISION),
			grade=score_to_grade(score),
			summary=f"Culture fit based on {total_signals} pattern signals",
			details=details[:7],
			confidence=round(confidence, SCORE_PRECISION),
		)

	def _collect_culture_signals(
		self,
		culture_signals: list[str],
		company_profile: CompanyProfile | None,
	) -> list[str]:
		"""Merge culture signals from the posting and company profile."""
		all_signals = list(culture_signals)
		if company_profile:
			all_signals.extend(company_profile.culture_keywords)
		return all_signals

	def _neutral_culture_dimension(self) -> DimensionScore:
		"""Return a neutral culture dimension when data is insufficient."""
		return DimensionScore(
			dimension="culture_fit",
			score=CULTURE_NEUTRAL_SCORE,
			grade=score_to_grade(CULTURE_NEUTRAL_SCORE),
			summary="Insufficient culture data for assessment",
			details=["No culture signals or candidate patterns available"],
			confidence=0.0,
			insufficient_data=True,
		)

	def _evaluate_culture_signals(
		self,
		signals: list[str],
	) -> tuple[float, int, list[str]]:
		"""Match culture signals directly against candidate patterns.

		Returns (total_match_value, signal_count, detail_lines).
		"""
		matches = 0.0
		total_signals = len(signals)
		details: list[str] = []

		for signal in signals:
			value, detail = _match_signal_to_pattern(signal, self.profile)
			matches += value
			if detail:
				details.append(detail)

		return matches, total_signals, details

	def _compute_culture_score(self, matches: float, total: int) -> float:
		"""Compute bounded culture fit score from match ratio."""
		if total > 0:
			score = CULTURE_BASE_SCORE + (matches / total) * CULTURE_SIGNAL_WEIGHT
		else:
			score = CULTURE_NEUTRAL_SCORE
		return min(max(score, CULTURE_SCORE_MIN), CULTURE_SCORE_MAX)

	# -- dimension 4: experience match ---------------------------------------

	def _score_experience_match(
		self,
		requirements: list[QuickRequirement],
		seniority: str,
	) -> DimensionScore:
		"""Score experience-years alignment between candidate and requirements.

		Compares the candidate's total_years_experience against the maximum
		years_experience specified across all requirements. Returns a neutral
		score when no requirements specify years.
		"""
		# Collect years requirements from enriched QuickRequirements
		years_reqs: list[tuple[str, int]] = []
		for req in requirements:
			if req.years_experience is not None:
				years_reqs.append((req.description, req.years_experience))

		if not years_reqs:
			return DimensionScore(
				dimension="experience_match",
				score=EXPERIENCE_NO_REQUIREMENT_SCORE,
				grade=score_to_grade(EXPERIENCE_NO_REQUIREMENT_SCORE),
				summary="No specific experience-years required — effectively met",
				details=["No years requirement stated; no bar to clear"],
				insufficient_data=True,
			)

		candidate_years = self.profile.total_years_experience
		if candidate_years is None:
			return DimensionScore(
				dimension="experience_match",
				score=EXPERIENCE_NEUTRAL_SCORE,
				grade=score_to_grade(EXPERIENCE_NEUTRAL_SCORE),
				summary="Candidate experience years unknown",
				details=["No total years of experience on candidate profile"],
				insufficient_data=True,
			)

		max_required = max(yrs for _, yrs in years_reqs)
		details: list[str] = []

		if candidate_years >= max_required:
			# Candidate meets or exceeds — score in 0.7-1.0 range
			ratio = min(candidate_years / max_required, 2.0)  # Cap at 2x
			score = EXPERIENCE_MET_BASE + (ratio - 1.0) * EXPERIENCE_EXCEED_BONUS
			score = min(score, EXPERIENCE_SCORE_MAX)
		else:
			# Candidate below — proportional score in 0.0-0.7 range
			ratio = candidate_years / max_required if max_required > 0 else 0.0
			score = ratio * EXPERIENCE_MET_BASE

		for desc, yrs in years_reqs:
			if candidate_years >= yrs:
				details.append(f"Met: {yrs}+ years {desc} (have {candidate_years:.0f} yrs)")
			else:
				details.append(f"Gap: {yrs}+ years {desc} (have {candidate_years:.0f} yrs)")

		if not details:
			details = ["Experience evaluation completed"]

		return DimensionScore(
			dimension="experience_match",
			score=round(score, SCORE_PRECISION),
			grade=score_to_grade(score),
			summary=f"Experience: {candidate_years:.0f} yrs vs {max_required}+ required",
			details=details[:7],
		)

	# -- dimension 5: education match ----------------------------------------

	def _score_education_match(
		self,
		requirements: list[QuickRequirement],
		tech_stack: list[str],
	) -> DimensionScore:
		"""Score education and tech-stack alignment.

		Combines two signals when available:
		1. Education level match (candidate degree vs required degree)
		2. Tech stack overlap (posting tech stack vs candidate skills)

		Returns a neutral score when neither signal is available.
		"""
		edu_score = self._score_education_level(requirements)
		tech_score, tech_details = self._score_tech_stack_overlap(tech_stack)

		scores: list[float] = []
		details: list[str] = []

		if edu_score is not None:
			scores.append(edu_score[0])
			details.extend(edu_score[1])

		if tech_score is not None:
			scores.append(tech_score)
			details.extend(tech_details)

		if not scores:
			return DimensionScore(
				dimension="education_match",
				score=EDUCATION_NO_REQUIREMENT_SCORE,
				grade=score_to_grade(EDUCATION_NO_REQUIREMENT_SCORE),
				summary="No specific education or tech stack required — effectively met",
				details=["No education or tech stack requirement stated; no bar to clear"],
				insufficient_data=True,
			)

		score = sum(scores) / len(scores)
		if not details:
			details = ["Education/tech evaluation completed"]

		return DimensionScore(
			dimension="education_match",
			score=round(score, SCORE_PRECISION),
			grade=score_to_grade(score),
			summary=f"Education & tech stack alignment: {score_to_grade(score)}",
			details=details[:7],
		)

	def _score_education_level(
		self,
		requirements: list[QuickRequirement],
	) -> tuple[float, list[str]] | None:
		"""Score education level match. Returns None if no education requirements."""
		# Collect education requirements
		edu_reqs: list[str] = []
		for req in requirements:
			if req.education_level:
				edu_reqs.append(req.education_level.lower())

		if not edu_reqs:
			return None

		candidate_edu = self.profile.education
		if not candidate_edu:
			return (0.2, ["No education listed on candidate profile"])

		# Parse candidate's highest degree
		candidate_rank = self._highest_degree_rank(candidate_edu)
		# Parse highest required degree
		required_rank = max(DEGREE_RANKING.get(edu, 0) for edu in edu_reqs)

		details: list[str] = []
		if candidate_rank >= required_rank:
			score = EDUCATION_MET_SCORE
			details.append(
				f"Education met: have {self._rank_to_label(candidate_rank)}, "
				f"need {self._rank_to_label(required_rank)}"
			)
		elif candidate_rank > 0:
			score = EDUCATION_PARTIAL_SCORE
			details.append(
				f"Education partial: have {self._rank_to_label(candidate_rank)}, "
				f"need {self._rank_to_label(required_rank)}"
			)
		else:
			score = EDUCATION_NO_MATCH_SCORE
			details.append("Education requirement not met")

		return (score, details)

	def _score_tech_stack_overlap(
		self,
		tech_stack: list[str],
	) -> tuple[float | None, list[str]]:
		"""Score tech stack overlap. Returns (None, []) if no tech stack specified."""
		if not tech_stack:
			return None, []

		posting_techs = {t.lower() for t in tech_stack}
		candidate_techs = {s.name for s in self.profile.skills}
		overlap = posting_techs & candidate_techs

		if not overlap:
			return 0.3, [f"No tech stack overlap (0/{len(posting_techs)} match)"]

		ratio = len(overlap) / len(posting_techs)
		score = 0.3 + ratio * 0.7  # Maps 0..1 ratio to 0.3..1.0
		details = [
			f"Tech stack: {len(overlap)}/{len(posting_techs)} match "
			f"({', '.join(sorted(overlap)[:MAX_TECH_OVERLAP_DISPLAY])})"
		]
		return score, details

	@staticmethod
	def _highest_degree_rank(education: list[str]) -> int:
		"""Extract the highest degree rank from a list of education strings."""
		best = 0
		for entry in education:
			entry_lower = entry.lower()
			for keyword, rank in DEGREE_RANKING.items():
				if keyword in entry_lower:
					best = max(best, rank)
		return best

	@staticmethod
	def _rank_to_label(rank: int) -> str:
		"""Convert a degree rank back to a human label."""
		for label, r in DEGREE_RANKING.items():
			if r == rank:
				return label
		return "unknown"

	# -- summary & action items ---------------------------------------------

	def _generate_summary(self, inp: SummaryInput) -> str:
		"""Generate the overall summary paragraph."""
		grade = score_to_grade(inp.overall_score)
		verdict = score_to_verdict(inp.overall_score)
		strongest, weakest = self._strongest_weakest_dims(inp)
		return (
			f"Overall {grade} fit for {inp.title} at {inp.company}. "
			f"{inp.must_coverage}. "
			f"Strongest dimension: {strongest[0]} ({score_to_grade(strongest[1])}). "
			f"Weakest dimension: {weakest[0]} ({score_to_grade(weakest[1])}). "
			f"{VERDICT_TEXT.get(verdict, '')}"
		)

	def _strongest_weakest_dims(
		self,
		inp: SummaryInput,
	) -> tuple[tuple[str, float], tuple[str, float]]:
		"""Find the strongest and weakest dimension by score."""
		dims: list[tuple[str, float]] = [
			("Skills", inp.skill_dim.score),
		]
		if inp.experience_dim is not None:
			dims.append(("Experience", inp.experience_dim.score))
		if inp.education_dim is not None:
			dims.append(("Education", inp.education_dim.score))
		if inp.mission_dim is not None:
			dims.append(("Mission", inp.mission_dim.score))
		if inp.culture_dim is not None:
			dims.append(("Culture", inp.culture_dim.score))
		return max(dims, key=lambda x: x[1]), min(dims, key=lambda x: x[1])

	def _generate_action_items(
		self,
		overall_score: float,
		gaps: list[SkillMatchDetail],
		resume_gaps: list[str],
		resume_unverified: list[str],
		company: str,
	) -> list[str]:
		"""Generate concrete next-step action items."""
		items: list[str] = []
		verdict = score_to_verdict(overall_score)
		self._add_verdict_actions(items, verdict, company)
		self._add_gap_actions(items, gaps, resume_gaps, resume_unverified)
		if not items:
			items.append("Review the detailed skill breakdown for more context")
		return items[:MAX_ACTION_ITEMS]

	def _add_verdict_actions(
		self,
		items: list[str],
		verdict: str,
		company: str,
	) -> None:
		"""Append action items driven by the overall verdict."""
		if verdict in ("strong_yes", "yes"):
			items.append("Generate full application package for this role")
		if verdict in ("maybe", "probably_not"):
			items.append(
				f"Research {company}'s engineering blog and recent projects before deciding"
			)

	def _add_gap_actions(
		self,
		items: list[str],
		gaps: list[SkillMatchDetail],
		resume_gaps: list[str],
		resume_unverified: list[str],
	) -> None:
		"""Append action items related to gaps and unverified claims."""
		if resume_gaps:
			names = ", ".join(resume_gaps[:MAX_RESUME_ITEMS])
			items.append(
				f"Update resume to include: {names} "
				f"(demonstrated in sessions but missing from resume)"
			)
		if gaps:
			gap_names = [g.requirement for g in gaps[:MAX_GAP_NAMES]]
			items.append(f"Key gaps to address: {', '.join(gap_names)}")
		if resume_unverified:
			names = ", ".join(resume_unverified[:MAX_RESUME_ITEMS])
			items.append(
				f"Resume claims without session evidence: {names} "
				f"— prepare to discuss these in interviews"
			)
