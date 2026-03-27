# v0.8 Phase 0 + Phase 1 Prerequisites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Decompose quick_match.py (2,642 lines) into a `scoring/` subpackage with zero behavior change, then fix two pre-existing bugs (health check + server eligibility) as Phase 1 prerequisites.

**Architecture:** Phase 0 extracts quick_match.py into four modules under `src/claude_candidate/scoring/` — constants, matching, dimensions, engine — with backward-compatible re-exports via both `scoring/__init__.py` and the original `quick_match.py` (now a thin shim). Phase 1 prereqs fix two server bugs: health check validating the wrong file, and missing eligibility data in assessments.

**Tech Stack:** Python 3.11+, pydantic v2, pytest, FastAPI

---

## File Structure

### Phase 0: scoring/ subpackage

| File | Responsibility |
|------|---------------|
| `src/claude_candidate/scoring/__init__.py` | Public API re-exports (QuickMatchEngine, compute_match_confidence, etc.) |
| `src/claude_candidate/scoring/constants.py` | All named constants, lookup tables, frozensets, data definitions, taxonomy singleton |
| `src/claude_candidate/scoring/matching.py` | Skill resolution pipeline: exact/fuzzy/pattern/virtual/related matching, depth assessment, adoption velocity |
| `src/claude_candidate/scoring/dimensions.py` | Module-level scoring helpers: per-requirement scoring, skill detail builders, mission/culture/weight helpers, domain gap detection, eligibility inference |
| `src/claude_candidate/scoring/engine.py` | QuickMatchEngine class, dataclasses (AssessmentInput, SummaryInput), result builders |
| `src/claude_candidate/quick_match.py` | Backward-compat shim: `from claude_candidate.scoring.* import *` — all old import paths continue to work |

### Phase 1 prereqs: bug fixes

| File | Change |
|------|--------|
| `src/claude_candidate/server.py` | Fix health check to validate curated_resume; fix _run_quick_assess to pass curated_eligibility |
| `tests/test_server.py` | Add tests for both bug fixes |

---

## Task 1: Establish Baseline

Verify the starting state before making any changes.

**Files:** None modified

- [ ] **Step 1: Run full fast test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: 1286 tests pass, 0 failures

- [ ] **Step 2: Run benchmark**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py 2>&1 | tail -5`
Expected: 37/47 exact matches (record the exact number — this is the invariant)

- [ ] **Step 3: Commit baseline confirmation**

No code changes — just confirm the numbers. Move on.

---

## Task 2: Create scoring/constants.py

Extract all named constants, lookup tables, frozensets, and data definitions.

**Files:**
- Create: `src/claude_candidate/scoring/__init__.py` (empty initially)
- Create: `src/claude_candidate/scoring/constants.py`

- [ ] **Step 1: Create the scoring/ directory and empty __init__.py**

```bash
mkdir -p src/claude_candidate/scoring
touch src/claude_candidate/scoring/__init__.py
```

- [ ] **Step 2: Create scoring/constants.py with all constants extracted from quick_match.py**

Create `src/claude_candidate/scoring/constants.py` with the following content. This extracts lines 44-56 (taxonomy singleton), 60-155 (named constants), 160-189 (eligibility constants), 207-208 (rounding precision), 235-278 (generic skills, skill variants), 360-476 (lookup tables + domain keywords), 511-517 (culture pattern strength score), 660-797 (virtual skill rules, pattern-to-skill, years thresholds), 800-822 (adoption velocity constants), 1386-1420 (scale keywords, AI keywords, AI skill names), 1728-1734 (weight tuples):

```python
"""
Scoring constants, lookup tables, and data definitions.

All magic numbers and configuration data for the scoring engine live here.
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
EXPERIENCE_NO_REQUIREMENT_SCORE = 0.9
EXPERIENCE_NEUTRAL_SCORE = 0.5
EXPERIENCE_MET_BASE = 0.7
EXPERIENCE_EXCEED_BONUS = 0.3
EXPERIENCE_SCORE_MAX = 1.0

# Education match score parameters
EDUCATION_NO_REQUIREMENT_SCORE = 0.9
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

# Soft skill discount factor
SOFT_SKILL_DISCOUNT = 0.5
SOFT_SKILL_MAX_BOOST = 0.8

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
# Generic skills and skill variants
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
	"typescript": ["ts", "type script"],
	"javascript": ["js", "java script"],
	"python": ["py"],
	"react": ["react.js", "reactjs"],
	"vue": ["vue.js", "vuejs"],
	"angular": ["angular.js", "angularjs"],
	"node.js": ["nodejs", "node"],
	"postgresql": ["postgres", "psql"],
	"mongodb": ["mongo"],
	"kubernetes": ["k8s"],
	"ci-cd": ["ci/cd", "cicd", "continuous integration"],
	"machine-learning": ["ml"],
	"elasticsearch": ["elastic", "es"],
	"html-css": ["html", "css", "html/css"],
	"graphql": ["gql"],
	"terraform": ["tf"],
	"amazon-web-services": ["aws"],
	"google-cloud-platform": ["gcp"],
}

# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

SENIORITY_DEPTH_FLOOR: dict[str, DepthLevel] = {
	"junior": DepthLevel.USED,
	"mid": DepthLevel.APPLIED,
	"senior": DepthLevel.DEEP,
	"staff": DepthLevel.DEEP,
	"principal": DepthLevel.EXPERT,
	"director": DepthLevel.DEEP,
	"unknown": DepthLevel.APPLIED,
}

PATTERN_STRENGTH_TO_DEPTH: dict[str, DepthLevel] = {
	"emerging": DepthLevel.USED,
	"established": DepthLevel.APPLIED,
	"strong": DepthLevel.DEEP,
	"exceptional": DepthLevel.EXPERT,
}

PATTERN_FREQ_TO_COUNT: dict[str, int] = {
	"rare": PATTERN_FREQ_RARE,
	"occasional": PATTERN_FREQ_OCCASIONAL,
	"common": PATTERN_FREQ_COMMON,
	"dominant": PATTERN_FREQ_DOMINANT,
}

STATUS_SCORE: dict[str, float] = {
	"exceeds": STATUS_SCORE_EXCEEDS,
	"strong_match": STATUS_SCORE_STRONG,
	"partial_match": STATUS_SCORE_PARTIAL,
	"adjacent": STATUS_SCORE_ADJACENT,
	"related": STATUS_SCORE_RELATED,
	"no_evidence": STATUS_SCORE_NONE,
}

STATUS_RANK: dict[str, int] = {
	"exceeds": STATUS_RANK_EXCEEDS,
	"strong_match": STATUS_RANK_STRONG,
	"partial_match": STATUS_RANK_PARTIAL,
	"adjacent": STATUS_RANK_ADJACENT,
	"related": STATUS_RANK_RELATED,
	"no_evidence": STATUS_RANK_NONE,
}

STATUS_MARKER: dict[str, str] = {
	"exceeds": "++",
	"strong_match": "+",
	"partial_match": "~",
	"adjacent": "?",
	"related": "~?",
	"no_evidence": "-",
}

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

SOURCE_LABEL: dict[EvidenceSource, str] = {
	EvidenceSource.CORROBORATED: "Corroborated by both resume and sessions",
	EvidenceSource.SESSIONS_ONLY: "Demonstrated in sessions (not on resume)",
	EvidenceSource.RESUME_ONLY: "Listed on resume (no session evidence)",
	EvidenceSource.CONFLICTING: "Resume depth anchored; sessions provided additional signal",
}

DOMAIN_KEYWORDS: frozenset[str] = frozenset({
	"music", "audio", "sound", "recording", "podcast",
	"sports", "baseball", "football", "basketball", "soccer", "athletics",
	"healthcare", "medical", "clinical", "patient", "biotech", "pharma",
	"bioinformatics", "genomics",
	"fintech", "banking", "financial", "trading", "insurance",
	"legal", "compliance", "regulatory",
	"automotive", "vehicle",
	"edtech", "educational", "curriculum",
	"gaming", "esports", "gameplay", "unreal",
	"real estate", "construction",
	"energy", "utilities",
	"retail", "ecommerce", "logistics",
	"firmware", "embedded",
	"ios", "android",
	"etl", "warehouse",
})

# Pattern strength → culture match value
CULTURE_PATTERN_STRENGTH_SCORE: dict[str, float] = {
	"exceptional": 1.0,
	"strong": 1.0,
	"established": CULTURE_ESTABLISHED_MATCH,
	"emerging": CULTURE_EMERGING_MATCH,
}

# ---------------------------------------------------------------------------
# Virtual skill rules and pattern-to-skill mapping
# ---------------------------------------------------------------------------

VIRTUAL_SKILL_RULES: list[tuple[str, list[str], int, DepthLevel]] = [
	(
		"full-stack",
		[
			"react", "vue", "angular", "nextjs", "frontend-development",
			"node.js", "python", "fastapi", "api-design", "backend-development",
		],
		2,
		DepthLevel.DEEP,
	),
	(
		"software-engineering",
		[
			"python", "typescript", "javascript", "react", "node.js",
			"ci-cd", "git", "testing", "api-design",
		],
		3,
		DepthLevel.DEEP,
	),
	("frontend-development", ["react", "vue", "angular", "nextjs", "html-css"], 1, DepthLevel.DEEP),
	(
		"backend-development",
		["python", "node.js", "fastapi", "api-design", "postgresql", "sql"],
		2,
		DepthLevel.DEEP,
	),
	(
		"system-design",
		[
			"api-design", "distributed-systems", "cloud-infrastructure",
			"software-engineering", "postgresql", "docker", "kubernetes",
		],
		2,
		DepthLevel.APPLIED,
	),
	("testing", ["pytest", "ci-cd"], 1, DepthLevel.DEEP),
	(
		"devops",
		["docker", "kubernetes", "ci-cd", "terraform", "aws", "gcp", "azure"],
		2,
		DepthLevel.APPLIED,
	),
	(
		"cloud-infrastructure",
		["aws", "gcp", "azure", "docker", "kubernetes", "terraform"],
		2,
		DepthLevel.APPLIED,
	),
	("data-science", ["sql", "python", "metabase", "postgresql"], 2, DepthLevel.APPLIED),
	(
		"computer-science",
		["python", "typescript", "javascript", "sql", "api-design", "software-engineering"],
		3,
		DepthLevel.APPLIED,
	),
	(
		"product-development",
		["react", "node.js", "python", "prototyping", "api-design", "ci-cd", "full-stack"],
		2,
		DepthLevel.APPLIED,
	),
	(
		"production-systems",
		["ci-cd", "docker", "testing", "aws", "gcp", "azure", "postgresql", "devops"],
		2,
		DepthLevel.APPLIED,
	),
	(
		"startup-experience",
		["prototyping", "full-stack", "product-development", "ci-cd", "api-design", "ownership"],
		2,
		DepthLevel.APPLIED,
	),
	("metrics", ["metabase", "sql", "data-science", "postgresql"], 1, DepthLevel.APPLIED),
	(
		"developer-tools",
		["ci-cd", "git", "testing", "software-engineering", "api-design", "llm"],
		2,
		DepthLevel.DEEP,
	),
	(
		"open-source",
		["git", "ci-cd", "software-engineering", "collaboration"],
		2,
		DepthLevel.APPLIED,
	),
]

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
# Adoption velocity composite constants
# ---------------------------------------------------------------------------

ADOPTION_BREADTH_WEIGHT = 0.15
ADOPTION_NOVELTY_WEIGHT = 0.25
ADOPTION_RAMP_WEIGHT = 0.30
ADOPTION_META_WEIGHT = 0.15
ADOPTION_TOOL_WEIGHT = 0.15

ADOPTION_NOVELTY_RECENCY_CUTOFF = 0.7
ADOPTION_NOVELTY_TARGET = 5
ADOPTION_BREADTH_TARGET = 5
ADOPTION_CONFIDENCE_DIVISOR = 10.0
ADOPTION_RAMP_NORMALIZER = 2.87

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
# Scale and AI detection
# ---------------------------------------------------------------------------

_SCALE_KEYWORDS: list[tuple[str, str]] = [
	("consumer scale", "consumer"),
	("at consumer scale", "consumer"),
	("millions of users", "consumer"),
	("millions of conversations", "consumer"),
	("consumer-facing", "consumer"),
	("at scale", "enterprise"),
	("enterprise scale", "enterprise"),
	("production scale", "enterprise"),
]

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

# ---------------------------------------------------------------------------
# Adaptive dimension weighting
# ---------------------------------------------------------------------------

_WEIGHTS_RICH = (0.50, 0.25, 0.25)
_WEIGHTS_MODERATE = (0.60, 0.20, 0.20)
_WEIGHTS_SPARSE = (0.70, 0.15, 0.15)
_WEIGHTS_NONE = (0.85, 0.10, 0.05)
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `.venv/bin/python -c "from claude_candidate.scoring.constants import STATUS_SCORE, QuickMatchEngine; print('FAIL')" 2>&1 || echo "OK - expected import error"`
Run: `.venv/bin/python -c "from claude_candidate.scoring.constants import STATUS_SCORE; print('OK:', STATUS_SCORE)"`
Expected: First command fails (QuickMatchEngine isn't in constants). Second prints the dict.

- [ ] **Step 4: Commit**

```bash
git add src/claude_candidate/scoring/__init__.py src/claude_candidate/scoring/constants.py
git commit -m "refactor: extract scoring/constants.py from quick_match.py"
```

---

## Task 3: Create scoring/matching.py

Extract the entire skill resolution pipeline: exact/fuzzy/pattern/virtual matching, depth assessment, adoption velocity, scale/AI helpers.

**Files:**
- Create: `src/claude_candidate/scoring/matching.py`

- [ ] **Step 1: Create scoring/matching.py**

This file contains all skill matching functions from quick_match.py. Key functions and their original line ranges:

- `compute_match_confidence` + `_skill_mentioned_in_text` + `_is_generic_skill` (lines 281-357)
- `_find_exact_match`, `_find_fuzzy_match`, `_is_variant_match` (lines 573-620)
- `_pattern_confidence`, `_find_pattern_match` (lines 623-650)
- `_build_adoption_summary`, `compute_adoption_velocity` (lines 825-988)
- `_infer_virtual_skill` (lines 991-1111)
- `_find_skill_match` (lines 1113-1147)
- `_best_available_depth`, `_related_corroboration_boost`, `_assess_depth_match` (lines 1149-1210)
- `_evidence_summary`, `_parse_duration_years` (lines 1212-1241)
- `_find_best_skill` (lines 1248-1383)
- `_detect_required_scale`, `_requirement_mentions_ai`, `_candidate_ai_scale` (lines 1386-1459)

```python
"""
Skill matching pipeline: resolution, depth assessment, and adoption velocity.

Handles exact, fuzzy, pattern, virtual, and related skill matching.
"""

from __future__ import annotations

import math
import re
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
	ADOPTION_BREADTH_TARGET,
	ADOPTION_BREADTH_WEIGHT,
	ADOPTION_CONFIDENCE_DIVISOR,
	ADOPTION_DEPTH_APPLIED,
	ADOPTION_DEPTH_DEEP,
	ADOPTION_DEPTH_EXPERT,
	ADOPTION_DEPTH_USED,
	ADOPTION_META_WEIGHT,
	ADOPTION_NOVELTY_RECENCY_CUTOFF,
	ADOPTION_NOVELTY_TARGET,
	ADOPTION_NOVELTY_WEIGHT,
	ADOPTION_RAMP_NORMALIZER,
	ADOPTION_RAMP_WEIGHT,
	ADOPTION_STRENGTH_MAP,
	ADOPTION_TOOL_WEIGHT,
	DEPTH_EXCEEDS_OFFSET,
	PATTERN_CONFIDENCE_HIGH,
	PATTERN_CONFIDENCE_LOW,
	PATTERN_FREQ_TO_COUNT,
	PATTERN_FREQ_OCCASIONAL,
	PATTERN_STRENGTH_TO_DEPTH,
	PATTERN_TO_SKILL,
	SOURCE_LABEL,
	STATUS_RANK,
	STATUS_SCORE,
	STATUS_SCORE_NONE,
	VIRTUAL_SKILL_RULES,
	YEARS_LEADERSHIP_THRESHOLD,
	YEARS_SOFTWARE_ENG_THRESHOLD,
	_AI_KEYWORDS_RE,
	_AI_SKILL_NAMES,
	_GENERIC_SKILLS,
	_SCALE_KEYWORDS,
	_SKILL_VARIANTS,
	_get_taxonomy,
)
```

Then paste the function bodies **verbatim** from quick_match.py — every function listed above, preserving exact logic. The only change is that imports come from `scoring.constants` instead of being defined inline.

The complete file content is too long for this plan cell but the instruction is: **copy every function body character-for-character from quick_match.py, changing only the import source.**

- [ ] **Step 2: Verify matching.py imports cleanly**

Run: `.venv/bin/python -c "from claude_candidate.scoring.matching import compute_match_confidence, _find_skill_match, compute_adoption_velocity; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/claude_candidate/scoring/matching.py
git commit -m "refactor: extract scoring/matching.py from quick_match.py"
```

---

## Task 4: Create scoring/dimensions.py

Extract module-level scoring helpers: per-requirement scoring, skill detail builders, mission/culture/domain/weight helpers.

**Files:**
- Create: `src/claude_candidate/scoring/dimensions.py`

- [ ] **Step 1: Create scoring/dimensions.py**

This file contains scoring helpers that the engine class calls. Key functions and their original line ranges:

- `_infer_eligibility` (lines 192-204)
- `_soft_skill_discount` (lines 212-232)
- `_detect_domain_gap` (lines 479-509)
- `_score_requirement` (lines 1461-1489)
- `_build_skill_detail`, `_format_detail_point`, `_build_skill_dimension` (lines 1492-1551)
- `_candidate_domain_set`, `_candidate_skill_names` (lines 1559-1591)
- `_score_domain_overlap`, `_score_tech_overlap` (lines 1593-1634)
- `_score_mission_text_alignment`, `_mission_from_posting` (lines 1636-1693)
- `_match_signal_to_pattern` (lines 1700-1723)
- `_redistribute_culture_weight`, `_compute_weights` (lines 1737-1774)
- `_compute_overall_score` (lines 1782-1794)
- `_must_have_coverage`, `_strongest_and_gap` (lines 1797-1819)
- `_discover_resume_gaps`, `_find_resume_unverified` (lines 1821-1855)

```python
"""
Dimension scoring helpers: requirement scoring, skill detail builders,
mission/culture/domain/weight computation, and result assembly helpers.
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
	CULTURE_BASE_SCORE,
	CULTURE_EMERGING_MATCH,
	CULTURE_NEUTRAL_SCORE,
	CULTURE_PATTERN_STRENGTH_SCORE,
	CULTURE_SIGNAL_WEIGHT,
	DOMAIN_KEYWORDS,
	ELIGIBILITY_DESCRIPTION_PATTERNS,
	ELIGIBILITY_SKILL_NAMES,
	MAX_GAP_NAMES,
	MAX_RESUME_ITEMS,
	MAX_TECH_OVERLAP_DISPLAY,
	MISSION_DOMAIN_BONUS,
	MISSION_NEUTRAL_SCORE,
	MISSION_NO_ENRICHMENT_BASE,
	MISSION_NO_ENRICHMENT_RANGE,
	MISSION_SCORE_MAX,
	MISSION_TECH_OVERLAP_WEIGHT,
	MISSION_TEXT_OVERLAP_WEIGHT,
	SCORE_PRECISION,
	SOFT_SKILL_DISCOUNT,
	SOFT_SKILL_MAX_BOOST,
	SOURCE_LABEL,
	STATUS_MARKER,
	STATUS_SCORE,
	STATUS_SCORE_NONE,
	TOP_SKILL_DETAILS,
	_WEIGHTS_MODERATE,
	_WEIGHTS_NONE,
	_WEIGHTS_RICH,
	_WEIGHTS_SPARSE,
)
from claude_candidate.scoring.matching import compute_match_confidence
```

Then paste each function body **verbatim** from quick_match.py. The only change is import sources.

- [ ] **Step 2: Verify dimensions.py imports cleanly**

Run: `.venv/bin/python -c "from claude_candidate.scoring.dimensions import _compute_weights, _score_requirement, _infer_eligibility; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/claude_candidate/scoring/dimensions.py
git commit -m "refactor: extract scoring/dimensions.py from quick_match.py"
```

---

## Task 5: Create scoring/engine.py

Extract the QuickMatchEngine class, dataclasses, and all remaining functions.

**Files:**
- Create: `src/claude_candidate/scoring/engine.py`

- [ ] **Step 1: Create scoring/engine.py**

This file contains:

- `AssessmentInput` dataclass (lines 525-538)
- `SummaryInput` dataclass (lines 541-553)
- `QuickMatchEngine` class (lines 1857-2643) — all methods verbatim

**Note:** `AdoptionVelocityResult` (lines 556-565) lives in `scoring/matching.py`, NOT here — it is returned by `compute_adoption_velocity()` which is defined in matching.py.

```python
"""
QuickMatchEngine: the main scoring engine class.

Produces FitAssessments by comparing a MergedEvidenceProfile against
a parsed job posting and optional company profile.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from claude_candidate.schemas.candidate_profile import DepthLevel
from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.curated_resume import CandidateEligibility
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
from claude_candidate.scoring.constants import (
	CULTURE_BASE_SCORE,
	CULTURE_NEUTRAL_SCORE,
	CULTURE_SCORE_MAX,
	CULTURE_SCORE_MIN,
	CULTURE_SIGNAL_WEIGHT,
	DEGREE_RANKING,
	EDUCATION_MET_SCORE,
	EDUCATION_NO_MATCH_SCORE,
	EDUCATION_NO_REQUIREMENT_SCORE,
	EDUCATION_NEUTRAL_SCORE,
	EDUCATION_PARTIAL_SCORE,
	EXPERIENCE_EXCEED_BONUS,
	EXPERIENCE_MET_BASE,
	EXPERIENCE_NEUTRAL_SCORE,
	EXPERIENCE_NO_REQUIREMENT_SCORE,
	EXPERIENCE_SCORE_MAX,
	MAX_ACTION_ITEMS,
	MAX_GAP_NAMES,
	MAX_RESUME_ITEMS,
	MAX_TECH_OVERLAP_DISPLAY,
	SCORE_PRECISION,
	SENIORITY_DEPTH_FLOOR,
	TIMING_PRECISION,
	VERDICT_TEXT,
	_get_taxonomy,
)
from claude_candidate.scoring.matching import (
	_assess_depth_match,
	_find_best_skill,
	_find_skill_match,
	compute_match_confidence,
)
from claude_candidate.scoring.dimensions import (
	_build_skill_detail,
	_build_skill_dimension,
	_candidate_domain_set,
	_candidate_skill_names,
	_compute_overall_score,
	_compute_weights,
	_detect_domain_gap,
	_discover_resume_gaps,
	_find_resume_unverified,
	_infer_eligibility,
	_match_signal_to_pattern,
	_mission_from_posting,
	_must_have_coverage,
	_redistribute_culture_weight,
	_score_domain_overlap,
	_score_mission_text_alignment,
	_score_requirement,
	_score_tech_overlap,
	_soft_skill_discount,
	_strongest_and_gap,
)
```

Then paste the three dataclasses and the entire QuickMatchEngine class **verbatim**. The only change: imports come from `scoring.constants`, `scoring.matching`, and `scoring.dimensions` instead of being defined in-module.

`AdoptionVelocityResult` goes in `scoring/matching.py` (alongside `compute_adoption_velocity` which returns it). `AssessmentInput` and `SummaryInput` go in `scoring/engine.py`.

- [ ] **Step 2: Verify engine.py imports cleanly**

Run: `.venv/bin/python -c "from claude_candidate.scoring.engine import QuickMatchEngine, AssessmentInput; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/claude_candidate/scoring/engine.py
git commit -m "refactor: extract scoring/engine.py from quick_match.py"
```

---

## Task 6: Wire up scoring/__init__.py

Set up the public API re-exports so `from claude_candidate.scoring import X` works for all public symbols.

**Files:**
- Modify: `src/claude_candidate/scoring/__init__.py`

- [ ] **Step 1: Write scoring/__init__.py with all public re-exports**

```python
"""
Scoring subpackage — public API.

All symbols that were previously importable from claude_candidate.quick_match
are re-exported here for the scoring/ subpackage public API.
"""

# Engine (primary public API)
from claude_candidate.scoring.engine import (
	AssessmentInput,
	QuickMatchEngine,
	SummaryInput,
)

# Matching (public functions)
from claude_candidate.scoring.matching import (
	AdoptionVelocityResult,
	compute_adoption_velocity,
	compute_match_confidence,
	_build_adoption_summary,
	_find_best_skill,
	_find_skill_match,
	_assess_depth_match,
	_best_available_depth,
	_evidence_summary,
	_find_exact_match,
	_find_fuzzy_match,
	_find_pattern_match,
	_infer_virtual_skill,
	_is_variant_match,
	_parse_duration_years,
	_candidate_ai_scale,
	_detect_required_scale,
	_requirement_mentions_ai,
)

# Dimensions (module-level helpers used by tests)
from claude_candidate.scoring.dimensions import (
	_build_skill_detail,
	_build_skill_dimension,
	_compute_overall_score,
	_compute_weights,
	_detect_domain_gap,
	_discover_resume_gaps,
	_find_resume_unverified,
	_infer_eligibility,
	_match_signal_to_pattern,
	_mission_from_posting,
	_must_have_coverage,
	_redistribute_culture_weight,
	_score_domain_overlap,
	_score_mission_text_alignment,
	_score_requirement,
	_score_tech_overlap,
	_soft_skill_discount,
	_strongest_and_gap,
)

# Constants (re-export everything tests and consumers use)
from claude_candidate.scoring.constants import (
	ADOPTION_BREADTH_TARGET,
	ADOPTION_BREADTH_WEIGHT,
	ADOPTION_CONFIDENCE_DIVISOR,
	ADOPTION_DEPTH_APPLIED,
	ADOPTION_DEPTH_DEEP,
	ADOPTION_DEPTH_EXPERT,
	ADOPTION_DEPTH_USED,
	ADOPTION_META_WEIGHT,
	ADOPTION_NOVELTY_RECENCY_CUTOFF,
	ADOPTION_NOVELTY_TARGET,
	ADOPTION_NOVELTY_WEIGHT,
	ADOPTION_RAMP_NORMALIZER,
	ADOPTION_RAMP_WEIGHT,
	ADOPTION_STRENGTH_MAP,
	ADOPTION_TOOL_WEIGHT,
	CULTURE_BASE_SCORE,
	CULTURE_EMERGING_MATCH,
	CULTURE_ESTABLISHED_MATCH,
	CULTURE_FULL_MATCH,
	CULTURE_NEUTRAL_SCORE,
	CULTURE_PATTERN_STRENGTH_SCORE,
	CULTURE_SCORE_MAX,
	CULTURE_SCORE_MIN,
	CULTURE_SIGNAL_WEIGHT,
	DEGREE_RANKING,
	DEPTH_EXCEEDS_OFFSET,
	DOMAIN_KEYWORDS,
	EDUCATION_MET_SCORE,
	EDUCATION_NEUTRAL_SCORE,
	EDUCATION_NO_MATCH_SCORE,
	EDUCATION_NO_REQUIREMENT_SCORE,
	EDUCATION_PARTIAL_SCORE,
	ELIGIBILITY_DESCRIPTION_PATTERNS,
	ELIGIBILITY_SKILL_NAMES,
	EXPERIENCE_EXCEED_BONUS,
	EXPERIENCE_MET_BASE,
	EXPERIENCE_NEUTRAL_SCORE,
	EXPERIENCE_NO_REQUIREMENT_SCORE,
	EXPERIENCE_SCORE_MAX,
	MAX_ACTION_ITEMS,
	MAX_GAP_NAMES,
	MAX_RESUME_ITEMS,
	MAX_TECH_OVERLAP_DISPLAY,
	MISSION_DOMAIN_BONUS,
	MISSION_NEUTRAL_SCORE,
	MISSION_NO_ENRICHMENT_BASE,
	MISSION_NO_ENRICHMENT_RANGE,
	MISSION_SCORE_MAX,
	MISSION_TECH_OVERLAP_WEIGHT,
	MISSION_TEXT_OVERLAP_WEIGHT,
	PATTERN_CONFIDENCE_HIGH,
	PATTERN_CONFIDENCE_LOW,
	PATTERN_FREQ_COMMON,
	PATTERN_FREQ_DOMINANT,
	PATTERN_FREQ_OCCASIONAL,
	PATTERN_FREQ_RARE,
	PATTERN_FREQ_TO_COUNT,
	PATTERN_STRENGTH_TO_DEPTH,
	PATTERN_TO_SKILL,
	SCORE_PRECISION,
	SENIORITY_DEPTH_FLOOR,
	SOFT_SKILL_DISCOUNT,
	SOFT_SKILL_MAX_BOOST,
	SOURCE_LABEL,
	STATUS_MARKER,
	STATUS_RANK,
	STATUS_RANK_ADJACENT,
	STATUS_RANK_EXCEEDS,
	STATUS_RANK_NONE,
	STATUS_RANK_PARTIAL,
	STATUS_RANK_RELATED,
	STATUS_RANK_STRONG,
	STATUS_SCORE,
	STATUS_SCORE_ADJACENT,
	STATUS_SCORE_EXCEEDS,
	STATUS_SCORE_NONE,
	STATUS_SCORE_PARTIAL,
	STATUS_SCORE_RELATED,
	STATUS_SCORE_STRONG,
	TIMING_PRECISION,
	TOP_SKILL_DETAILS,
	VERDICT_TEXT,
	VIRTUAL_SKILL_RULES,
	YEARS_LEADERSHIP_THRESHOLD,
	YEARS_SOFTWARE_ENG_THRESHOLD,
	_AI_KEYWORDS_RE,
	_AI_SKILL_NAMES,
	_GENERIC_SKILLS,
	_SCALE_KEYWORDS,
	_SKILL_VARIANTS,
	_WEIGHTS_MODERATE,
	_WEIGHTS_NONE,
	_WEIGHTS_RICH,
	_WEIGHTS_SPARSE,
	_get_taxonomy,
)
```

- [ ] **Step 2: Verify key imports work through scoring package**

Run: `.venv/bin/python -c "from claude_candidate.scoring import QuickMatchEngine, compute_match_confidence, STATUS_SCORE, _compute_weights; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/claude_candidate/scoring/__init__.py
git commit -m "refactor: wire scoring/__init__.py re-exports"
```

---

## Task 7: Convert quick_match.py to Backward-Compat Shim

Replace the 2,642-line quick_match.py with a thin module that re-exports everything from scoring/.

**Files:**
- Modify: `src/claude_candidate/quick_match.py`

- [ ] **Step 1: Replace quick_match.py contents with shim**

Replace the entire contents of `src/claude_candidate/quick_match.py` with:

```python
"""
Backward-compatibility shim for claude_candidate.quick_match.

All scoring logic now lives in the claude_candidate.scoring subpackage.
This module re-exports the public API so existing import paths continue to work.

Scheduled for removal at end of Phase 3 (v0.8.2).
"""

# Re-export everything from the scoring subpackage.
# This allows `from claude_candidate.quick_match import X` to continue working.
from claude_candidate.scoring import *  # noqa: F401, F403
from claude_candidate.scoring import (  # explicit re-exports for type checkers
	AdoptionVelocityResult,
	AssessmentInput,
	QuickMatchEngine,
	SummaryInput,
	compute_adoption_velocity,
	compute_match_confidence,
)
```

- [ ] **Step 2: Run full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: 1286 tests pass, 0 failures. Every existing `from claude_candidate.quick_match import X` continues to work because the shim re-exports all symbols.

- [ ] **Step 3: Run benchmark**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py 2>&1 | tail -5`
Expected: Same exact match count as baseline (37/47). Zero behavior change.

- [ ] **Step 4: Commit**

```bash
git add src/claude_candidate/quick_match.py
git commit -m "refactor: convert quick_match.py to backward-compat shim"
```

---

## Task 8: Final Phase 0 Verification

Comprehensive verification that the refactor is behavior-identical.

**Files:** None modified

- [ ] **Step 1: Run full fast test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: 1286 tests pass, 0 failures

- [ ] **Step 2: Run benchmark**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py 2>&1 | tail -5`
Expected: 37/47 exact matches (unchanged from baseline)

- [ ] **Step 3: Verify old import paths work**

Run: `.venv/bin/python -c "
from claude_candidate.quick_match import QuickMatchEngine
from claude_candidate.quick_match import compute_match_confidence
from claude_candidate.quick_match import _compute_weights
from claude_candidate.quick_match import STATUS_SCORE
from claude_candidate.quick_match import SOFT_SKILL_DISCOUNT
from claude_candidate.quick_match import _find_best_skill
from claude_candidate.quick_match import _find_skill_match
from claude_candidate.quick_match import _score_requirement
from claude_candidate.quick_match import compute_adoption_velocity, AdoptionVelocityResult
from claude_candidate.quick_match import _infer_virtual_skill
from claude_candidate.quick_match import _infer_eligibility
from claude_candidate.quick_match import _detect_domain_gap, DOMAIN_KEYWORDS
from claude_candidate.quick_match import _build_skill_detail
from claude_candidate.quick_match import _parse_duration_years
from claude_candidate.quick_match import _soft_skill_discount, SOFT_SKILL_MAX_BOOST
from claude_candidate.quick_match import _build_adoption_summary
from claude_candidate.quick_match import STATUS_SCORE_NONE
print('All old import paths work')
"`
Expected: `All old import paths work`

- [ ] **Step 4: Verify new import paths work**

Run: `.venv/bin/python -c "
from claude_candidate.scoring import QuickMatchEngine
from claude_candidate.scoring.constants import STATUS_SCORE
from claude_candidate.scoring.matching import compute_match_confidence
from claude_candidate.scoring.dimensions import _compute_weights
from claude_candidate.scoring.engine import QuickMatchEngine as QME2
assert QuickMatchEngine is QME2
print('All new import paths work')
"`
Expected: `All new import paths work`

- [ ] **Step 5: Check file sizes (sanity check)**

Run: `wc -l src/claude_candidate/scoring/*.py src/claude_candidate/quick_match.py`
Expected: quick_match.py is ~15 lines. Each scoring/ module is 200-800 lines. Total lines across scoring/ should be ~2,650 (matching the original).

Phase 0 is complete. No version bump (it's a pure refactor with no behavioral change).

---

## Task 9: Fix Health Check Bug (Phase 1 Prereq)

The `/api/health` endpoint checks for `candidate_profile.json` but v0.7's primary path uses `curated_resume.json` + `repo_profile.json`. Health check reports `profile_loaded: false` even when the triad path works.

**Files:**
- Modify: `src/claude_candidate/server.py:351-359`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_server.py` inside the existing `TestHealthEndpoint` class. Follow the existing fixture pattern — `create_app(data_dir=tmp_path)` + `LifespanManager` + `AsyncClient`:

```python
# Add a new fixture to tests/test_server.py (module level, near the other fixtures):

@pytest.fixture
def app_with_curated_resume(tmp_path: Path):
	"""App with only curated_resume (v0.7 primary path, no candidate_profile.json)."""
	curated = {
		"skills": [
			{"name": "python", "depth": "expert", "years": 10, "context": "Backend"}
		],
		"roles": [
			{
				"company": "Test Corp",
				"title": "Engineer",
				"start_date": "2020-01",
				"end_date": "2024-01",
			}
		],
		"eligibility": {},
	}
	(tmp_path / "curated_resume.json").write_text(json.dumps(curated))
	return create_app(data_dir=tmp_path)


@pytest.fixture
async def client_with_curated_resume(app_with_curated_resume):
	async with LifespanManager(app_with_curated_resume) as manager:
		transport = ASGITransport(app=manager.app)
		async with AsyncClient(transport=transport, base_url="http://test") as c:
			yield c
```

Then add the test to `TestHealthEndpoint`:

```python
# Inside class TestHealthEndpoint:

async def test_health_profile_loaded_true_with_curated_resume(
	self, client_with_curated_resume: AsyncClient
):
	"""v0.7 primary path: curated_resume alone should report profile_loaded=True."""
	resp = await client_with_curated_resume.get("/api/health")
	assert resp.json()["profile_loaded"] is True
```

The existing `test_health_profile_loaded_false_without_profile` already covers the empty case.

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestHealthEndpoint::test_health_profile_loaded_true_with_curated_resume -v`
Expected: FAIL — health check only checks `profiles.get("candidate")`, not `curated_resume`

- [ ] **Step 3: Fix the health check**

In `src/claude_candidate/server.py`, modify the health endpoint (line ~354):

Change:
```python
profile_loaded = bool(profiles.get("candidate"))
```

To:
```python
profile_loaded = bool(
	profiles.get("curated_resume") or profiles.get("candidate")
)
```

This checks for the v0.7 primary profile (curated_resume) first, falling back to the legacy candidate_profile.json.

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestHealthEndpoint -v`
Expected: All health tests PASS (including the new curated_resume test)

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: All tests pass (1286+ with the new ones)

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/server.py tests/test_server.py
git commit -m "fix: health check validates curated_resume (v0.7 primary path)"
```

---

## Task 10: Fix Server Eligibility Bug (Phase 1 Prereq)

The `_run_quick_assess()` function never passes `curated_eligibility` to `engine.assess()`. All server assessments use empty `CandidateEligibility()` defaults, meaning eligibility gates never fail.

**Files:**
- Modify: `src/claude_candidate/server.py:416-461`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write the failing test**

Add a new fixture and test class to `tests/test_server.py`, following the existing `LifespanManager` + `AsyncClient` pattern:

```python
# New fixture (module level):

@pytest.fixture
def app_with_restrictive_eligibility(tmp_path: Path):
	"""App with curated_resume that has restrictive eligibility (no relocation)."""
	curated = {
		"skills": [
			{"name": "python", "depth": "expert", "years": 10, "context": "Backend dev"}
		],
		"roles": [
			{
				"company": "Test Corp",
				"title": "Engineer",
				"start_date": "2020-01",
				"end_date": "2024-01",
			}
		],
		"eligibility": {
			"us_work_authorized": True,
			"has_clearance": False,
			"max_travel_pct": 10,
			"willing_to_relocate": False,
		},
	}
	(tmp_path / "curated_resume.json").write_text(json.dumps(curated))
	# repo_profile for merge_triad
	repo = {"repos": [], "scan_metadata": {"scanned_at": "2026-01-01T00:00:00"}}
	(tmp_path / "repo_profile.json").write_text(json.dumps(repo))
	return create_app(data_dir=tmp_path)


@pytest.fixture
async def client_with_restrictive_eligibility(app_with_restrictive_eligibility):
	async with LifespanManager(app_with_restrictive_eligibility) as manager:
		transport = ASGITransport(app=manager.app)
		async with AsyncClient(transport=transport, base_url="http://test") as c:
			yield c
```

Then add the test class:

```python
class TestServerEligibility:
	"""Tests for eligibility data loading in server assessments."""

	async def test_assess_passes_curated_eligibility(
		self, client_with_restrictive_eligibility: AsyncClient
	):
		"""Server assessments should use eligibility from curated_resume.json.

		With willing_to_relocate=False and a relocation requirement,
		the gate should be "unmet".
		"""
		resp = await client_with_restrictive_eligibility.post(
			"/api/assess",
			json={
				"posting_text": "Must relocate to NYC",
				"company": "Test Corp",
				"title": "Engineer",
				"requirements": [
					{
						"description": "Must be willing to relocate to New York",
						"skill_mapping": ["relocation"],
						"priority": "must_have",
						"is_eligibility": True,
					},
					{
						"description": "Python backend development",
						"skill_mapping": ["python"],
						"priority": "must_have",
					},
				],
			},
		)
		assert resp.status_code == 200
		body = resp.json()
		gates = body.get("eligibility_gates", [])
		unmet = [g for g in gates if g.get("status") == "unmet"]
		assert len(unmet) > 0, (
			f"Expected unmet eligibility gates but got: {gates}"
		)
```

The key assertion is: when `curated_resume.json` has `willing_to_relocate: False` and the posting requires relocation, the eligibility gate should be "unmet".

- [ ] **Step 2: Run the test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestServerEligibility -v`
Expected: FAIL — currently all gates resolve to "met" because `CandidateEligibility()` defaults to `willing_to_relocate=True`

- [ ] **Step 3: Implement the fix**

In `src/claude_candidate/server.py`, modify `_run_quick_assess()` (around line 450-461):

After `merged = _build_merged_profile()` and before `engine = QuickMatchEngine(merged)`, add eligibility loading:

```python
# Load curated eligibility for gate evaluation
from claude_candidate.schemas.curated_resume import CandidateEligibility, CuratedResume
from pydantic import ValidationError

curated_eligibility: CandidateEligibility | None = None
curated_data = get_profiles().get("curated_resume")
if curated_data:
	try:
		curated = CuratedResume.model_validate(curated_data)
		curated_eligibility = curated.eligibility
	except (ValidationError, Exception):
		pass  # Malformed curated resume — use defaults
```

Then update the `engine.assess()` call to pass the eligibility:

```python
assessment = engine.assess(
	requirements=requirements,
	company=req.company,
	title=req.title,
	posting_url=req.posting_url,
	source="api",
	seniority=req.seniority,
	culture_signals=req.culture_signals,
	tech_stack=req.tech_stack,
	curated_eligibility=curated_eligibility,
)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestServerEligibility -v`
Expected: PASS

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: All tests pass

- [ ] **Step 6: Run benchmark (verify no scoring changes)**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py 2>&1 | tail -5`
Expected: 37/47 exact (unchanged — benchmark uses CLI path which already passes eligibility)

- [ ] **Step 7: Commit**

```bash
git add src/claude_candidate/server.py tests/test_server.py
git commit -m "fix: server assessments now load curated eligibility for gate evaluation"
```

---

## Dependency Notes

- **Tasks 2-6 are sequential** — each module depends on the previous one compiling.
- **Task 7 depends on Tasks 2-6** — the shim can only work when all modules exist.
- **Task 9 and Task 10 are independent** of each other but both depend on Phase 0 completion (Task 8).
- **Task 9 and Task 10 can be parallelized** — they touch different parts of server.py (health endpoint vs assess endpoint).

## What's NOT in this plan

- Version bump (Phase 0 is patch-eligible but per CEO plan uses v0.7.19 — defer to the Phase 1 plan which bumps to v0.8.0)
- Test import migration (old `from claude_candidate.quick_match import` paths stay — migrated incrementally in Phase 1-3 feature branches per CEO plan)
- CLAUDE.md updates (scoring/ subpackage will be documented after Phase 1 when the architecture stabilizes)
- Extension changes (#7 per-URL storage — separate Phase 1 feature)
