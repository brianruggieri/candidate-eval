"""
Constants, lookup tables, and data definitions extracted from quick_match.py.

All values are verbatim copies — no behavior changes, no new logic.
"""

from __future__ import annotations

import re

from claude_candidate.schemas.candidate_profile import DepthLevel
from claude_candidate.schemas.merged_profile import EvidenceSource
from claude_candidate.skill_taxonomy import SkillTaxonomy


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

# Confidence adjustment floor: how much a zero-confidence match is penalized.
# Old value was 0.90 (±10%). Widened to 0.70 (±30%) so match quality
# has meaningful scoring impact on fuzzy/related matches.
CONFIDENCE_FLOOR = 0.70

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

# Domain keyword taxonomy for mission alignment scoring.
# Maps product domains to related keywords that indicate domain relevance.
# Used to strengthen mission alignment when the candidate has domain-adjacent experience.
MISSION_DOMAIN_TAXONOMY: dict[str, list[str]] = {
	"developer-tools": [
		"developer",
		"devtools",
		"ide",
		"sdk",
		"api",
		"cli",
		"infrastructure",
		"platform",
		"tooling",
		"devops",
		"ci/cd",
		"deployment",
		"monitoring",
	],
	"ai": [
		"artificial intelligence",
		"machine learning",
		"ml",
		"llm",
		"nlp",
		"deep learning",
		"neural",
		"model",
		"inference",
		"training",
		"prompt",
		"agent",
		"agentic",
		"generative",
		"transformer",
		"embedding",
	],
	"fintech": [
		"financial",
		"fintech",
		"banking",
		"payments",
		"trading",
		"crypto",
		"blockchain",
		"defi",
		"insurance",
		"lending",
		"compliance",
	],
	"healthcare": [
		"health",
		"medical",
		"clinical",
		"patient",
		"biotech",
		"pharma",
		"genomic",
		"bioinformatics",
		"ehr",
		"telehealth",
		"diagnostic",
	],
	"education": [
		"education",
		"edtech",
		"learning",
		"teaching",
		"student",
		"course",
		"curriculum",
		"tutoring",
		"assessment",
		"classroom",
	],
	"e-commerce": [
		"commerce",
		"retail",
		"shopping",
		"marketplace",
		"merchant",
		"catalog",
		"inventory",
		"checkout",
		"fulfillment",
	],
	"gaming": [
		"game",
		"gaming",
		"unity",
		"unreal",
		"3d",
		"interactive",
		"multiplayer",
		"virtual",
		"simulation",
		"real-time",
	],
	"creative-tools": [
		"creative",
		"design",
		"media",
		"video",
		"audio",
		"music",
		"animation",
		"rendering",
		"content creation",
		"editor",
	],
	"security": [
		"security",
		"cybersecurity",
		"encryption",
		"authentication",
		"vulnerability",
		"threat",
		"compliance",
		"privacy",
		"zero trust",
	],
	"data": [
		"data",
		"analytics",
		"visualization",
		"dashboard",
		"metrics",
		"warehouse",
		"pipeline",
		"etl",
		"business intelligence",
	],
	"infrastructure": [
		"cloud",
		"infrastructure",
		"kubernetes",
		"containers",
		"serverless",
		"networking",
		"storage",
		"compute",
		"orchestration",
	],
	"collaboration": [
		"collaboration",
		"productivity",
		"communication",
		"team",
		"workflow",
		"project management",
		"remote work",
	],
}

# Culture fit score parameters
CULTURE_NEUTRAL_SCORE = 0.5
CULTURE_BASE_SCORE = 0.3
CULTURE_SIGNAL_WEIGHT = 0.6
CULTURE_ESTABLISHED_MATCH = 0.7
CULTURE_EMERGING_MATCH = 0.3
CULTURE_FULL_MATCH = 1
CULTURE_SCORE_MIN = 0.0
CULTURE_SCORE_MAX = 1.0

# Years gradient penalty floor (replaces separate experience dimension)
YEARS_GRADIENT_FLOOR = 0.6

# Display limits
TOP_SKILL_DETAILS = 5
MAX_TECH_OVERLAP_DISPLAY = 5
MAX_GAP_NAMES = 2
MAX_RESUME_ITEMS = 3
MAX_ACTION_ITEMS = 6

# Soft skill discount factor — reduces weight of soft skill requirements
SOFT_SKILL_DISCOUNT = 0.5

# Rounding precision
SCORE_PRECISION = 3
TIMING_PRECISION = 2

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

# ---------------------------------------------------------------------------
# Match-time confidence (v0.7)
# ---------------------------------------------------------------------------

_GENERIC_SKILLS = frozenset(
	{
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
	}
)

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
	"software-engineering": [
		"software development",
		"software developer",
		"engineering experience",
	],
	"project-management": [
		"project management",
		"manage projects",
		"technical project",
		"project management tools",
	],
	"testing": [
		"test",
		"quality assurance",
		"qa",
		"evaluation data",
		"attention to detail",
		"detail-oriented",
	],
	"product-development": [
		"shipping products",
		"building products",
		"ship products",
		"personal projects",
		"product quality",
	],
	"technology-research": [
		"passion for ai",
		"curiosity for ai",
		"keeps up with trends",
		"emerging innovations",
	],
}

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
	EvidenceSource.RESUME_AND_REPO: "Corroborated by both resume and repo",
	EvidenceSource.REPO_ONLY: "Demonstrated in repo (not on resume or in sessions)",
}

# Industry/domain keywords — non-technical terms that appear repeatedly in domain-specific JDs.
# If any of these appears in 3+ requirements but is absent from the candidate's profile,
# the grade is capped at B+ (domain fit cannot be proven without evidence).
DOMAIN_KEYWORDS: frozenset[str] = frozenset(
	{
		# Music / audio
		"music",
		"audio",
		"sound",
		"recording",
		"podcast",
		# Sports
		"sports",
		"baseball",
		"football",
		"basketball",
		"soccer",
		"athletics",
		# Healthcare / biotech
		"healthcare",
		"medical",
		"clinical",
		"patient",
		"biotech",
		"pharma",
		"bioinformatics",
		"genomics",
		# Finance
		"fintech",
		"banking",
		"financial",
		"trading",
		"insurance",
		# Legal
		"legal",
		"compliance",
		"regulatory",
		# Automotive
		"automotive",
		"vehicle",
		# Education
		"edtech",
		"educational",
		"curriculum",
		# Gaming / game engines
		"gaming",
		"esports",
		"gameplay",
		"unreal",
		# Real estate
		"real estate",
		"construction",
		# Energy
		"energy",
		"utilities",
		# Retail / logistics
		"retail",
		"ecommerce",
		"logistics",
		# Hardware / embedded
		"firmware",
		"embedded",
		# Native mobile platforms
		"ios",
		"android",
		# Data infrastructure
		"etl",
		"warehouse",
	}
)

# Pattern strength → culture match value
CULTURE_PATTERN_STRENGTH_SCORE: dict[str, float] = {
	"exceptional": 1.0,
	"strong": 1.0,
	"established": CULTURE_ESTABLISHED_MATCH,
	"emerging": CULTURE_EMERGING_MATCH,
}

# ---------------------------------------------------------------------------
# Virtual skill inference rules + pattern mappings
# ---------------------------------------------------------------------------

# Maps a virtual skill name to (required_any, min_count, inferred_depth, min_constituent_depth).
# If the profile contains >= min_count skills from required_any (at or above
# min_constituent_depth if set), the virtual skill is inferred at inferred_depth.
VIRTUAL_SKILL_RULES: list[tuple[str, list[str], int, DepthLevel, DepthLevel | None]] = [
	# full-stack: need frontend + backend evidence at APPLIED+ depth
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
		3,
		DepthLevel.DEEP,
		DepthLevel.APPLIED,
	),
	# software-engineering: need multiple programming skills at APPLIED+ depth
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
		5,
		DepthLevel.DEEP,
		DepthLevel.APPLIED,
	),
	# frontend-development: need a frontend framework at APPLIED+ depth
	(
		"frontend-development",
		["react", "vue", "angular", "nextjs", "html-css"],
		2,
		DepthLevel.DEEP,
		DepthLevel.APPLIED,
	),
	# backend-development: need a backend stack
	(
		"backend-development",
		["python", "node.js", "fastapi", "api-design", "postgresql", "sql"],
		3,
		DepthLevel.DEEP,
		DepthLevel.APPLIED,
	),
	# system-design: architecture + system skills at APPLIED+
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
		3,
		DepthLevel.APPLIED,
		DepthLevel.APPLIED,
	),
	# testing: testing pattern or pytest (narrow — no depth requirement)
	("testing", ["pytest", "ci-cd"], 1, DepthLevel.DEEP, None),
	# devops: container/infra tooling
	(
		"devops",
		["docker", "kubernetes", "ci-cd", "terraform", "aws", "gcp", "azure"],
		2,
		DepthLevel.APPLIED,
		None,
	),
	# cloud-infrastructure: cloud providers
	(
		"cloud-infrastructure",
		["aws", "gcp", "azure", "docker", "kubernetes", "terraform"],
		2,
		DepthLevel.APPLIED,
		None,
	),
	# data-science: analytics background
	("data-science", ["sql", "python", "metabase", "postgresql"], 2, DepthLevel.APPLIED, None),
	# computer-science: implied by deep engineering experience
	(
		"computer-science",
		["python", "typescript", "javascript", "sql", "api-design", "software-engineering"],
		3,
		DepthLevel.APPLIED,
		None,
	),
	# product-development: full-stack + shipping evidence at APPLIED+
	(
		"product-development",
		["react", "node.js", "python", "prototyping", "api-design", "ci-cd", "full-stack"],
		3,
		DepthLevel.APPLIED,
		DepthLevel.APPLIED,
	),
	# production-systems: deployment + testing + infra
	(
		"production-systems",
		["ci-cd", "docker", "testing", "aws", "gcp", "azure", "postgresql", "devops"],
		2,
		DepthLevel.APPLIED,
		None,
	),
	# startup-experience: prototyping + shipping evidence
	(
		"startup-experience",
		["prototyping", "full-stack", "product-development", "ci-cd", "api-design", "ownership"],
		2,
		DepthLevel.APPLIED,
		None,
	),
	# metrics: analytics tools + data skills
	("metrics", ["metabase", "sql", "data-science", "postgresql"], 1, DepthLevel.APPLIED, None),
	# developer-tools: builds tools for developers
	(
		"developer-tools",
		["ci-cd", "git", "testing", "software-engineering", "api-design", "llm"],
		2,
		DepthLevel.DEEP,
		None,
	),
	# open-source: git + collaborative development
	(
		"open-source",
		["git", "ci-cd", "software-engineering", "collaboration"],
		2,
		DepthLevel.APPLIED,
		None,
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

# ---------------------------------------------------------------------------
# Adoption velocity constants
# ---------------------------------------------------------------------------

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

# ---------------------------------------------------------------------------
# Scale / AI detection constants
# ---------------------------------------------------------------------------

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

_AI_KEYWORDS_RE = re.compile(
	r"\b(ai|ml|machine\s+learning|intelligence|llm|deep\s+learning|neural|model|generative|agentic)\b",
	re.IGNORECASE,
)

_AI_SKILL_NAMES: frozenset[str] = frozenset(
	{
		"llm",
		"machine-learning",
		"agentic-workflows",
		"prompt-engineering",
		"rag",
		"embeddings",
		"generative-ai",
	}
)

# ---------------------------------------------------------------------------
# Adaptive dimension weighting
# ---------------------------------------------------------------------------

# Weight tuples: (skill, mission, culture)
_WEIGHTS_RICH = (0.50, 0.25, 0.25)
_WEIGHTS_MODERATE = (0.60, 0.20, 0.20)
_WEIGHTS_SPARSE = (0.70, 0.15, 0.15)
_WEIGHTS_NONE = (0.85, 0.10, 0.05)
