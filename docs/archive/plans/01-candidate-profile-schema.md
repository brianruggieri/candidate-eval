# Plan 01: CandidateProfile Schema

## Purpose

The `CandidateProfile` is the central intermediate representation (IR) of the claude-candidate pipeline. It is the structured output of Stage 2 (Extract Signal) and the primary input to Stage 4 (Match & Evaluate). Every upstream stage writes to it or its dependencies; every downstream stage reads from it. Getting this schema right is the single highest-leverage task in the project.

This plan defines the full data model: CandidateProfile, its component schemas, the companion JobRequirements and MatchEvaluation schemas, and the session metadata structures that connect claims to evidence.

## Design Goals

1. **Evidence-linked**: Every skill claim, pattern observation, and strength assessment must trace back to one or more specific session references. No orphan claims.
2. **Queryable**: The schema must support efficient filtering — "show me all sessions demonstrating async Python" or "which sessions best demonstrate architecture decision-making."
3. **Diff-friendly**: Profiles generated at different times (as new sessions are added) should produce meaningful diffs showing skill growth.
4. **Serializable**: Round-trips cleanly to/from JSON. All types are JSON-native or have obvious serialization (datetimes as ISO 8601 strings, enums as strings).
5. **Extensible**: New skill categories, pattern types, and evidence kinds can be added without breaking existing profiles.

## Schema Definitions

All schemas are defined as Pydantic v2 models. The canonical source is `src/claude_candidate/schemas/`. What follows is the full specification.

### Session Reference

The atomic unit of evidence. Every claim links to one or more of these.

```python
class SessionReference(BaseModel):
    """Pointer to a specific session that provides evidence for a claim."""

    session_id: str
    # Derived from filename or generated. Format: YYYY-MM-DD_HH-MM-SS_{project_hash}
    # Must match an entry in the SessionManifest (Plan 03).

    session_date: datetime
    # When the session occurred. Used for recency weighting and trajectory analysis.

    project_context: str
    # Brief description of what project/task the session was part of.
    # Extracted during Stage 2. Examples: "blog-a-claude pipeline development",
    # "teamchat React UI implementation", "obsidian-daily-digest plugin refactor"

    evidence_snippet: str
    # A sanitized excerpt (post-Stage-1) that demonstrates the claimed skill or pattern.
    # Maximum 500 characters. Must not contain secrets, PII, or proprietary code.
    # This is what could appear in Tier 2 (proof layer) disclosures.

    evidence_type: Literal[
        "direct_usage",        # Directly used the technology/skill
        "architecture_decision", # Made a design/architecture choice
        "debugging",           # Diagnosed and resolved an issue
        "teaching",            # Explained a concept (to the AI or in documentation)
        "evaluation",          # Evaluated tradeoffs between options
        "integration",         # Connected multiple systems/tools
        "refactor",            # Improved existing code/architecture
        "testing",             # Wrote or discussed tests
        "review",              # Reviewed code or designs
        "planning"             # Scoped or planned work
    ]

    confidence: float
    # 0.0–1.0. How clearly this session demonstrates the linked claim.
    # 1.0 = unambiguous direct evidence. 0.5 = tangential or implied.
    # Set by the extractor agent based on prompt quality and directness.
```

### Skill Entry

A single demonstrated technical skill with evidence.

```python
class DepthLevel(str, Enum):
    """How deeply the candidate has engaged with this skill."""
    MENTIONED = "mentioned"         # Referenced but not demonstrated
    USED = "used"                   # Used in a straightforward context
    APPLIED = "applied"             # Applied to solve a non-trivial problem
    DEEP = "deep"                   # Deep expertise: debugging internals, architectural decisions, teaching
    EXPERT = "expert"               # Expert: novel applications, framework-level thinking, performance optimization

class SkillEntry(BaseModel):
    """A single demonstrated technical skill."""

    name: str
    # Canonical name. Use lowercase, standard naming.
    # Examples: "python", "typescript", "react", "async-programming",
    # "git", "docker", "postgresql", "claude-api", "prompt-engineering"

    category: Literal[
        "language",
        "framework",
        "tool",
        "platform",
        "concept",        # e.g., "async-programming", "event-driven-architecture"
        "practice",       # e.g., "test-driven-development", "code-review"
        "domain",         # e.g., "ml-ops", "developer-tooling", "cli-design"
        "soft_skill"      # e.g., "technical-communication", "architecture-decision-making"
    ]

    depth: DepthLevel
    # Highest depth observed across all sessions.

    frequency: int
    # Number of distinct sessions where this skill was demonstrated.
    # Higher frequency + higher depth = stronger signal.

    recency: datetime
    # Most recent session demonstrating this skill.

    first_seen: datetime
    # Earliest session demonstrating this skill. Useful for trajectory analysis.

    evidence: list[SessionReference]
    # All sessions providing evidence. Sorted by confidence descending.
    # Minimum 1 reference required.

    context_notes: str | None = None
    # Optional. Brief note on how this skill was typically applied.
    # Example: "Used primarily for CLI tool development and data pipeline construction."
```

### Problem-Solving Pattern

Captures *how* the candidate works, not just *what* they know.

```python
class PatternType(str, Enum):
    """Categories of observable problem-solving behavior."""
    SYSTEMATIC_DEBUGGING = "systematic_debugging"
    # Methodical hypothesis-elimination approach to bugs.

    ARCHITECTURE_FIRST = "architecture_first"
    # Designs structure before writing implementation code.

    ITERATIVE_REFINEMENT = "iterative_refinement"
    # Builds working version, then improves through cycles.

    TRADEOFF_ANALYSIS = "tradeoff_analysis"
    # Explicitly evaluates pros/cons before deciding.

    SCOPE_MANAGEMENT = "scope_management"
    # Identifies what NOT to build; defers features; manages complexity.

    DOCUMENTATION_DRIVEN = "documentation_driven"
    # Writes docs/specs before or alongside implementation.

    RECOVERY_FROM_FAILURE = "recovery_from_failure"
    # How they respond when an approach fails — pivot speed, composure.

    TOOL_SELECTION = "tool_selection"
    # Evaluates and selects appropriate tools for the task.

    MODULAR_THINKING = "modular_thinking"
    # Decomposes problems into independent, composable units.

    TESTING_INSTINCT = "testing_instinct"
    # Proactively writes or considers tests without being prompted.

    META_COGNITION = "meta_cognition"
    # Reflects on their own process; identifies when they're stuck; adjusts approach.

    COMMUNICATION_CLARITY = "communication_clarity"
    # Explains technical concepts clearly and precisely.


class ProblemSolvingPattern(BaseModel):
    """An observed behavioral pattern in how the candidate approaches work."""

    pattern_type: PatternType

    frequency: Literal["rare", "occasional", "common", "dominant"]
    # How often this pattern appears across eligible sessions.
    # rare: <10% of sessions. occasional: 10-30%. common: 30-60%. dominant: >60%.

    strength: Literal["emerging", "established", "strong", "exceptional"]
    # Quality of execution when the pattern appears.
    # emerging: shows signs but inconsistent. established: reliable.
    # strong: high quality. exceptional: would impress senior engineers.

    description: str
    # 2-4 sentence narrative describing how this pattern manifests in the candidate's work.
    # Written by the extractor agent. Should be specific, not generic.
    # Example: "Consistently decomposes CLI tools into independent modules with clear
    # interfaces before writing implementation. In 8 of 12 project-start sessions,
    # the first action was drawing a module dependency diagram or writing interface stubs."

    evidence: list[SessionReference]
    # Sessions demonstrating this pattern. Minimum 2 for "occasional" and above.

    counter_evidence: list[SessionReference] | None = None
    # Optional. Sessions where the candidate notably did NOT exhibit this pattern
    # when it would have been expected. Honesty about inconsistency strengthens trust.
```

### Project Summary

Captures the candidate's project portfolio as demonstrated in sessions.

```python
class ProjectComplexity(str, Enum):
    TRIVIAL = "trivial"         # Single file, simple task
    SIMPLE = "simple"           # Few files, straightforward logic
    MODERATE = "moderate"       # Multiple modules, some architectural decisions
    COMPLEX = "complex"         # System-level thinking, multiple interacting components
    AMBITIOUS = "ambitious"     # Novel approach, significant technical challenges, multi-session

class ProjectSummary(BaseModel):
    """A project the candidate worked on, as evidenced by sessions."""

    project_name: str
    # Canonical project name. Use repo name if public.

    description: str
    # 2-4 sentence description of what the project does and why.

    public_repo_url: str | None = None
    # GitHub/GitLab URL if the project is public. Critical for verification.

    complexity: ProjectComplexity

    technologies: list[str]
    # Skill names (matching SkillEntry.name) used in this project.

    session_count: int
    # Number of sessions associated with this project.

    date_range: tuple[datetime, datetime]
    # First and last session dates for this project.

    key_decisions: list[str]
    # Notable architecture/design decisions made during this project.
    # Each entry is 1-2 sentences. Maximum 5 entries.

    challenges_overcome: list[str]
    # Specific technical challenges faced and resolved.
    # Each entry is 1-2 sentences. Maximum 5 entries.

    evidence: list[SessionReference]
    # Representative sessions for this project.
```

### The CandidateProfile Itself

The top-level IR.

```python
class CandidateProfile(BaseModel):
    """
    The central intermediate representation of a candidate's demonstrated abilities.

    Generated by Stage 2 (Extract Signal) from sanitized session logs.
    Consumed by Stage 4 (Match & Evaluate) alongside a JobRequirements instance.

    Every field in this profile is backed by session evidence.
    No claim exists without a traceable reference.
    """

    # === Metadata ===

    profile_version: str = "0.1.0"
    # Schema version. Increment on breaking changes.

    generated_at: datetime
    # When this profile was generated.

    generator_version: str
    # Version of claude-candidate that produced this profile.

    session_count: int
    # Total number of sessions that were processed to create this profile.

    date_range: tuple[datetime, datetime]
    # Earliest and latest session dates in the corpus.

    manifest_hash: str
    # SHA-256 hash of the SessionManifest (Plan 03) used as input.
    # Enables verification that this profile was derived from a specific set of sessions.

    # === Skills ===

    skills: list[SkillEntry]
    # All demonstrated skills, sorted by (depth descending, frequency descending).
    # The extractor agent populates this from session analysis.

    primary_languages: list[str]
    # Top 3-5 programming languages by combined depth × frequency score.
    # Derived from skills where category == "language".

    primary_domains: list[str]
    # Top 3-5 domain areas. Derived from skills where category == "domain".

    # === Patterns ===

    problem_solving_patterns: list[ProblemSolvingPattern]
    # Observed behavioral patterns. Sorted by (strength descending, frequency descending).

    working_style_summary: str
    # 3-5 sentence narrative synthesizing the candidate's overall working style.
    # Written by the extractor agent. Should read like a senior engineer's assessment
    # after pair-programming for a week.

    # === Projects ===

    projects: list[ProjectSummary]
    # Projects evidenced in sessions. Sorted by complexity descending.

    # === Communication ===

    communication_style: str
    # 2-3 sentence assessment of how the candidate communicates technical concepts.
    # Based on how they prompt, explain, and discuss with Claude.

    documentation_tendency: Literal["minimal", "moderate", "thorough", "extensive"]
    # How much the candidate tends to document their work and decisions.

    # === Growth Indicators ===

    skill_trajectory: list[SkillTrajectoryPoint] | None = None
    # Optional. If sessions span enough time, tracks skill depth changes over time.

    learning_velocity_notes: str | None = None
    # Optional. Observations about how quickly the candidate picks up new tools/concepts.
    # Only populated if there's clear evidence of learning within the session corpus.

    # === Integrity ===

    extraction_notes: str
    # Candid notes from the extraction process about data quality, gaps,
    # or limitations. Example: "Sessions heavily skewed toward Python CLI work.
    # Limited evidence of frontend or database skills — absence of evidence
    # is not evidence of absence."

    confidence_assessment: Literal["low", "moderate", "high", "very_high"]
    # Overall confidence in the profile's accuracy, based on:
    # - Session count (more = higher)
    # - Date range (broader = higher)
    # - Diversity of projects (more = higher)
    # - Consistency of evidence (coherent = higher)


class SkillTrajectoryPoint(BaseModel):
    """A snapshot of a skill's depth at a point in time."""
    skill_name: str
    depth: DepthLevel
    as_of: datetime
    session_id: str  # The session that established this depth level
```

### JobRequirements Schema

The structured representation of a job posting. Input to Stage 4.

```python
class RequirementPriority(str, Enum):
    MUST_HAVE = "must_have"           # Explicitly required; deal-breaker if missing
    STRONG_PREFERENCE = "strong_preference"  # Strongly preferred but not absolute
    NICE_TO_HAVE = "nice_to_have"     # Bonus; mentioned but not emphasized
    IMPLIED = "implied"               # Not stated but inferable from context

class JobRequirement(BaseModel):
    """A single requirement or preference from a job posting."""

    description: str
    # What the requirement is. Examples: "5+ years Python experience",
    # "Experience with distributed systems", "Strong communication skills"

    skill_mapping: list[str]
    # Canonical skill names (matching SkillEntry.name or PatternType values)
    # that would satisfy this requirement. May be multiple.
    # Example: ["python"] or ["distributed-systems", "microservices", "kubernetes"]

    priority: RequirementPriority

    years_experience: int | None = None
    # If the posting specifies years, capture it. None if not mentioned.

    evidence_needed: str
    # What kind of evidence would demonstrate this requirement.
    # Example: "Multiple sessions showing Python debugging at framework/internals level"

class JobRequirements(BaseModel):
    """Structured representation of a job posting."""

    # === Source ===

    company: str
    title: str
    posting_url: str | None = None
    posting_text_hash: str
    # SHA-256 of the raw posting text, for reproducibility.

    ingested_at: datetime
    seniority_level: Literal["junior", "mid", "senior", "staff", "principal", "director", "unknown"]

    # === Requirements ===

    requirements: list[JobRequirement]
    # All extracted requirements, sorted by priority descending.

    responsibilities: list[str]
    # Key job responsibilities. 1 sentence each.

    # === Culture & Context ===

    tech_stack_mentioned: list[str]
    # Technologies explicitly named in the posting. Canonical names.

    team_context: str | None = None
    # Any info about the team: size, methodology, reporting structure.

    culture_signals: list[str]
    # Values, work style, or culture indicators from the posting.
    # Examples: "move fast", "remote-first", "pair programming", "open source contributor"

    red_flags: list[str] | None = None
    # Anything in the posting that seems concerning or contradictory.
    # The matcher agent can use this for honest assessment.
```

### MatchEvaluation Schema

The output of Stage 4. Input to Stage 5 (deliverable generation).

```python
class SkillMatch(BaseModel):
    """How a specific job requirement maps to candidate evidence."""

    requirement: JobRequirement
    # The requirement being evaluated.

    match_status: Literal[
        "strong_match",     # Clear, strong evidence of meeting this requirement
        "partial_match",    # Some evidence but gaps in depth or breadth
        "adjacent",         # Related skills demonstrated but not exact match
        "no_evidence",      # No relevant sessions found
        "exceeds"           # Candidate demonstrably exceeds this requirement
    ]

    supporting_evidence: list[SessionReference]
    # Sessions that support the match. Empty for "no_evidence".

    public_corroboration: list[str] | None = None
    # URLs to public repos/commits that independently verify this skill.

    narrative: str
    # 2-3 sentence explanation of the match assessment.
    # Must be honest about gaps. Written for a human reader.

    gap_description: str | None = None
    # If partial_match or no_evidence: what's missing and how significant is it.


class MatchEvaluation(BaseModel):
    """
    The result of comparing a CandidateProfile against JobRequirements.
    This is the IR that drives all deliverable generation.
    """

    # === Metadata ===

    profile_hash: str
    # SHA-256 of the CandidateProfile JSON. Links this evaluation to a specific profile.

    job_hash: str
    # SHA-256 of the JobRequirements JSON. Links to a specific posting.

    evaluated_at: datetime

    # === Match Results ===

    skill_matches: list[SkillMatch]
    # One entry per JobRequirement, sorted by requirement priority.

    overall_fit: Literal["strong", "good", "moderate", "weak", "poor"]
    # Holistic assessment considering all matches, patterns, and context.

    fit_reasoning: str
    # 4-6 sentence explanation of the overall fit assessment.
    # Must acknowledge both strengths and gaps.

    # === Strengths & Gaps ===

    top_strengths: list[str]
    # 3-5 bullet points: the candidate's strongest selling points for this specific role.
    # Each grounded in evidence.

    notable_gaps: list[str]
    # Honest list of gaps between the candidate and the requirements.
    # Each with an assessment of severity.

    differentiators: list[str]
    # Things the candidate brings that aren't in the requirements but add value.
    # Example: "Built open-source developer tooling — demonstrates product thinking
    # and user empathy beyond typical backend engineering."

    # === Strategic Recommendations ===

    resume_emphasis: list[str]
    # Which skills/projects to emphasize in resume bullets for this role.

    cover_letter_themes: list[str]
    # 2-3 narrative themes the cover letter should develop.

    interview_prep_topics: list[str]
    # Topics the candidate should prepare to discuss in depth.

    risk_mitigation: list[str]
    # How to address gaps proactively (in cover letter or interview).
    # Example: "No Kubernetes evidence in sessions, but Docker and CI/CD
    # patterns demonstrate containerization familiarity. Frame as adjacent skill."
```

## Implementation Tasks

### Task 1: Set Up Schema Module
**File**: `src/claude_candidate/schemas/__init__.py`
- Create the schemas package
- Export all public models
- Add module-level docstring explaining the schema hierarchy

### Task 2: Implement Core Models
**Files**: `src/claude_candidate/schemas/candidate_profile.py`, `job_requirements.py`, `match_evaluation.py`, `session_manifest.py`
- Implement all Pydantic v2 models as specified above
- Add field validators:
  - `SessionReference.confidence` must be 0.0–1.0
  - `SessionReference.evidence_snippet` max 500 chars
  - `SkillEntry.evidence` must have at least 1 entry
  - `CandidateProfile.primary_languages` max 5 entries
  - `MatchEvaluation.top_strengths` must have 3–5 entries
- Add `model_config` with JSON schema generation settings
- Add `to_json()` and `from_json()` convenience methods on top-level models

### Task 3: JSON Schema Export
**File**: `src/claude_candidate/schemas/export.py`
- Generate JSON Schema from each Pydantic model
- Write to `schemas/json/` directory for external consumption
- These schemas can be published alongside the repo for anyone who wants to build compatible tools

### Task 4: Schema Validation Tests
**File**: `tests/test_schemas.py`
- Round-trip serialization tests (model → JSON → model)
- Validation tests (invalid data raises appropriate errors)
- Edge cases: empty evidence lists, boundary confidence values, maximum-length strings
- Fixture: a realistic `CandidateProfile` populated with sample data (from the candidate's actual public project work)

### Task 5: Sample Profile Fixture
**File**: `tests/fixtures/expected_profile.json`
- A complete, realistic CandidateProfile JSON based on the project author's known public work
- Used as golden file for extraction quality testing
- Should include entries for: Python, TypeScript, React, Claude Code, prompt engineering, CLI design, tmux, macOS automation, agent teams, session log processing
- Should include patterns for: modular_thinking, architecture_first, documentation_driven, meta_cognition

## Acceptance Criteria

1. All Pydantic models pass `mypy --strict` type checking.
2. JSON Schema files generate correctly and validate against sample data.
3. Round-trip serialization is lossless for all models.
4. The sample fixture represents a realistic, populated profile.
5. No model permits a claim without at least one SessionReference.
6. Every enum value has a docstring or inline comment explaining its meaning.
7. The schema supports the full pipeline: extraction → matching → generation without requiring schema changes.

## Dependencies

- Python 3.11+
- pydantic >= 2.0
- No other external dependencies for the schema module itself.

## Notes for Agent Team Lead

This schema is the contract between all pipeline stages. Changes here ripple everywhere. The implementation should be conservative — add fields only when there's a clear consumer. The `| None` optional fields exist for progressive enhancement (trajectory analysis, learning velocity) that may not be populated in v0.1 but should be structurally supported from the start.

The `SessionReference` is deliberately verbose because trust depends on traceability. Every shortcut in the evidence chain weakens the proof model. If an agent finds it tedious to populate evidence references, that's a feature — it forces the extraction to be grounded.

Pay special attention to the `evidence_type` enum in SessionReference. This classification drives the matcher's ability to distinguish "mentioned Python once" from "architecturally designed a Python system." The depth signal comes from evidence type × confidence × frequency, not from any single field.
