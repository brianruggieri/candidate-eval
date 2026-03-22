# Session Extractor Overhaul — Design Spec

**Date:** 2026-03-21
**Status:** Approved
**Scope:** Tiers 1-3 (hard requirements) + 5 Tier 4 cherry-picks

## Problem

The session extractor (`src/claude_candidate/extractor.py`) extracts **15 skills from 853+ sessions**. It should extract **50-100+**. Only **3 skills are corroborated** between sessions and resume (should be 20+). The extractor is a 749-line monolith that only analyzes code content — it ignores behavioral metadata, AI-native signals, and communication patterns that are rich in the session logs.

## Signal Tiers

### Tier 1: Traditional Dev Skills (well-established extraction)
Languages, frameworks, tools, platforms from file extensions, imports, content patterns, and package commands.

### Tier 2: Developer Quality & Behavior (emerging patterns)
Testing sophistication, security awareness, performance consciousness, error handling maturity, refactoring discipline, git workflow, documentation habits, API design, code review practices, observability.

### Tier 3: AI-Native Skills (genuinely novel — no prior art)
Agent orchestration, task decomposition, skill/workflow invocation, prompt engineering, delegation patterns, context management, multi-session continuity, worktree usage, agent teams, hook/plugin authorship, cost awareness, multi-AI orchestration, correction/steering.

### Tier 4: Cherry-Picks (5 easy wins with high differentiation)
1. **Scope Management** — deferral language, phase-gating, knowing when to ship
2. **Adversarial Self-Review ("Grill Me")** — inviting critical feedback on own ideas
3. **Steering Precision** — surgical correction of AI output in minimal words
4. **Handoff Discipline** — clean session boundaries, state externalization
5. **Agentic Learning Velocity** — adoption curves showing progression from basic → advanced

## Architecture: Three Extractors + Merger + Optional ML Enrichment

### Overview

```
Session JSONL files
        │
        ├──→ CodeSignalExtractor     (Tier 1)
        ├──→ BehaviorSignalExtractor  (Tier 2+3)
        └──→ CommSignalExtractor      (Tier 3+4)
                │
                ▼
        SignalMerger  ──→  CandidateProfile (same schema as today)
                │
                ▼ (optional, if torch installed)
        MLEnrichmentLayer  ──→  Enriched CandidateProfile
```

### Constraints
- **Output schema unchanged** — CandidateProfile, SkillEntry, ProblemSolvingPattern, ProjectSummary stay as-is. One exception: `node.js` has `category: "runtime"` in taxonomy but SkillEntry only allows 8 categories — map `runtime → "platform"` during extraction.
- **Same CLI interface** — `sessions scan` still works
- **Each extractor reads the same JSONL files** independently. All extractors have access to raw JSONL event metadata (session_id, timestamp, cwd, gitBranch) as basic infrastructure — scope boundaries define which *signals* each extractor analyzes, not which fields it can read.
- **Graceful degradation** — ML layer is optional; without torch, full heuristic extraction still works (the 15→50+ improvement)

### File Structure

```
src/claude_candidate/
├── extractor.py              → refactored: thin orchestrator (~100 lines)
├── extractors/
│   ├── __init__.py           → ExtractorProtocol, SignalResult, shared types
│   ├── code_signals.py       → CodeSignalExtractor (~300 lines)
│   ├── behavior_signals.py   → BehaviorSignalExtractor (~400 lines)
│   ├── comm_signals.py       → CommSignalExtractor (~300 lines)
│   └── signal_merger.py      → SignalMerger (~200 lines)
├── enrichment/
│   ├── __init__.py           → enrichment_available() check
│   ├── embedding_matcher.py  → Semantic skill matching via MiniLM
│   ├── evidence_selector.py  → Embedding-based snippet selection
│   └── learning_velocity.py  → Embedding-enhanced sophistication classification
├── data/
│   ├── taxonomy.json         → Updated with content_patterns for all 78 entries
│   └── package_to_skill_map.json → ~200 package names → canonical skill mappings
```

---

## Shared Interfaces

All interface types use pydantic `BaseModel` (consistent with the rest of the codebase). Validation on confidence ranges, snippet lengths, etc. comes for free.

### ExtractorProtocol

```python
class ExtractorProtocol(Protocol):
    """Contract for all three extractors."""

    def extract_session(self, session: NormalizedSession) -> SignalResult:
        """Extract signals from a single normalized session."""
        ...

    def name(self) -> str:
        """Extractor identifier for logging and source tracking."""
        ...
```

`NormalizedSession` is a new container type that wraps the existing `NormalizedMessage` list (from `message_format.py`) with session-level metadata: `session_id`, `timestamp`, `cwd`, `gitBranch`, and the list of `NormalizedMessage` objects. It is NOT a rename of `NormalizedMessage` — it is a session-level wrapper. All three extractors receive the same `NormalizedSession` — each reads the fields relevant to its scope.

### SignalResult

```python
class SignalResult(BaseModel):
    """One extraction layer's output for a single session."""
    model_config = ConfigDict(frozen=True)

    session_id: str
    session_date: datetime
    project_context: str
    git_branch: str | None = None
    skills: dict[str, list[SkillSignal]] = {}   # canonical_name → signals (multiple per extractor possible)
    patterns: list[PatternSignal] = []
    project_signals: ProjectSignal | None = None
    metrics: dict[str, float] = {}
```

### SkillSignal

```python
class SkillSignal(BaseModel):
    """A single skill detection from one extractor."""
    model_config = ConfigDict(frozen=True)

    canonical_name: str
    source: Literal[
        "file_extension", "content_pattern", "import_statement",
        "package_command", "tool_usage", "agent_dispatch",
        "skill_invocation", "user_message", "git_workflow",
        "quality_signal"
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    depth_hint: DepthLevel | None = None
    evidence_snippet: str = Field(max_length=500)
    evidence_type: Literal[
        "direct_usage", "architecture_decision", "debugging",
        "teaching", "evaluation", "integration", "refactor",
        "testing", "review", "planning"
    ] = "direct_usage"
    metadata: dict = {}
```

### PatternSignal

```python
class PatternSignal(BaseModel):
    """A behavioral or communication pattern detection."""
    model_config = ConfigDict(frozen=True)

    pattern_type: PatternType  # all 12 values now reachable
    session_ids: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    description: str
    evidence_snippet: str = Field(max_length=500)
    metadata: dict = {}
```

Note: PatternSignal does NOT carry frequency/strength — those are computed by the SignalMerger during aggregation across sessions.

### ProjectSignal

```python
class ProjectSignal(BaseModel):
    """Project-level enrichment from a single session."""
    model_config = ConfigDict(frozen=True)

    key_decisions: list[str] = []
    challenges: list[str] = []
    description_fragments: list[str] = []
```

---

## Code Signal Extractor (Tier 1)

### Detection Layers

**Layer 1: File extension mapping** (existing, unchanged)
- Current FILE_EXTENSION_MAP with 16 extensions
- Source: `"file_extension"`, confidence: 0.9

**Layer 2: Content patterns from taxonomy** (existing, massively expanded)
- Expand from 15/78 to 78/78 entries with content_patterns
- Pattern precision rules by category:
  - **Languages**: import statement patterns, only in code blocks
  - **Frameworks**: import + API-specific patterns (e.g., nextjs: `"next/", "getServerSideProps"`)
  - **Platforms**: CLI commands + SDK imports (e.g., aws: `"aws ", "boto3", "from aws_cdk"`)
  - **Tools**: command patterns (e.g., postgresql: `"psql", "pg_dump", "CREATE TABLE"`)
  - **Practices**: require 2+ co-occurring signals (NOT single keywords)
  - **Domains**: conservative domain-specific terminology only
- Rule: if a single keyword would match >30% of sessions, it needs co-occurrence or code-block-only constraint
- Source: `"content_pattern"`, confidence: 0.75

**Layer 3: Import parsing** (new)
- Language-specific parsers for Python, JS/TS, Rust, Go import statements
- New `package_to_skill_map` (~200 common packages → canonical skills)
- Source: `"import_statement"`, confidence: 0.85

**Layer 4: Package manager commands** (new)
- Parse Bash tool_use inputs for: pip install, npm install, yarn add, pnpm add, bun add, cargo add, go get, brew install
- Same package_to_skill_map for resolution
- Source: `"package_command"`, confidence: 0.7

### Scope boundary
Only analyzes: file paths, code content in tool_use/text blocks, Bash command inputs.
Does NOT analyze: tool metadata, user messages, behavioral sequences.

---

## Behavior Signal Extractor (Tier 2 + 3)

### Group 1: Problem-Solving Patterns (all 12 PatternType values)

| PatternType | Detection |
|-------------|-----------|
| ITERATIVE_REFINEMENT | (existing) write_count ≥ 2 AND bash_count ≥ 1 |
| ARCHITECTURE_FIRST | (existing) read_count ≥ 1 AND write_count ≥ 1 |
| TESTING_INSTINCT | (upgraded) test file touched OR test framework in Bash |
| MODULAR_THINKING | (existing) unique_extension_count ≥ 3 |
| SYSTEMATIC_DEBUGGING | (new) Grep→Read→Edit sequence + error in Bash output → targeted fix |
| TRADEOFF_ANALYSIS | (new) Explore/Plan Agent dispatched before implementation |
| SCOPE_MANAGEMENT | (new) TaskCreate with dependency chains, phased naming |
| DOCUMENTATION_DRIVEN | (new) .md file Write/Edit before or alongside code changes |
| RECOVERY_FROM_FAILURE | (new) Bash error → different approach within 3 turns (not retry) |
| TOOL_SELECTION | (new) Agent dispatches with explicit subagent_type, Skill invocations matching workflow phase |
| META_COGNITION | (new) /clear, /compact, model switching, handoff creation |
| COMMUNICATION_CLARITY | (new) cross-signal from CommSignalExtractor |

### Group 2: Agent Orchestration (Tier 3)

| Signal | Detection | Output |
|--------|-----------|--------|
| Agent dispatches | tool_use name="Agent", extract subagent_type | `agentic-workflows` skill with sophistication metadata |
| Subagent type diversity | Distinct subagent_types per session | depth signal: 1=basic, 3+=advanced |
| Parallel fan-out | Multiple Agent tool_use in same assistant message | orchestration sophistication |
| Plan-driven execution | Agent prompt references `.claude/plans/` | structured methodology |
| Agent Teams | `<teammate-message>` tags | multi-agent team design |
| Worktree isolation | git worktree commands, worktree directories | parallel development discipline |

### Group 3: Skill/Workflow Invocations

| Signal | Detection | Output |
|--------|-----------|--------|
| Skill invocations | tool_use name="Skill" | TOOL_SELECTION pattern |
| SDLC cycle | brainstorm→plan→execute sequence | `software-engineering` practice |
| Task decomposition | TaskCreate with file paths, phases, dependencies | project management signal |

### Group 4: Git Workflow

| Signal | Detection | Output |
|--------|-----------|--------|
| Branch naming | gitBranch field: feat/, fix/, cleanup/ | git depth + methodology |
| Worktree usage | git worktree commands | advanced git + parallel dev |
| PR workflow | gh pr create | ci-cd practice |

### Group 5: Quality Practice Signals (Tier 2)

| Signal | Detection | Output |
|--------|-----------|--------|
| Security awareness | File paths/content with sanitiz/secret/pii/auth/XSS/CORS | `security` practice |
| Testing sophistication | Multiple test frameworks, test file ops, test-before-ship | `testing` practice |
| Code review | gh pr, copilot review, code-reviewer Agent | code review practice |
| Error handling | try/except in Edit/Write, fallback chains | depth signal on skills |
| Performance | batch/parallel/cache/optimize in context | performance practice |

### Evidence Type Classification

Replaces hardcoded `"direct_usage"`:

| Context | evidence_type |
|---------|--------------|
| Grep→Read→Edit around error | `"debugging"` |
| Plan/Explore Agent dispatch | `"architecture_decision"` |
| Test file edits | `"testing"` |
| .md documentation edits | `"planning"` |
| Brainstorm/plan Skill invocation | `"planning"` |
| Structure-only Edit | `"refactor"` |
| Default | `"direct_usage"` |

### Scope boundary
Analyzes: tool_use structured events (name, input fields including file paths and content passed to Edit/Write/Bash), git metadata, error flags, message sequencing.
Does NOT analyze: free-text code blocks in assistant responses, user message text (natural language intent).
Note: reading `tool_use.input.content` (e.g., what was written to a file) is in scope — this is structured tool metadata, not free-text code analysis. The distinction is: BehaviorSignalExtractor looks at *what tools were used and on what*, not at the code's semantic meaning.

---

## Communication Signal Extractor (Tier 3 + 4 cherry-picks)

### Input Filtering
Only actual human messages — filter out tool_result messages masquerading as user role (86.9% of "user" messages are automated tool results). Include /clear, /compact, /model command messages.

### Group 1: Steering Precision

| Signal | Detection |
|--------|-----------|
| Correction messages | Short (< 150 chars) following long assistant output (> 1000 chars) with redirect language |
| Redirect keywords | "no", "not that", "instead", "actually", "only", "just", "don't" as leading words |
| Precision corrections | "only one change", "just the X", "X not Y" patterns |

Output: COMMUNICATION_CLARITY pattern, metadata: `steering_count`, `steering_precision_ratio`.

### Group 2: Scope Management

| Signal | Detection |
|--------|-----------|
| Deferral language | "not yet", "later", "just X for now", "let's not", "park that", "out of scope" |
| Phase-gating | "phase 1", "step 1 first", "before we move on" |
| Session boundaries | "save the session", "pick up fresh", "clean slate", "wrap up" |
| Scope narrowing | "nothing fancy", "keep it simple", "minimal" |

Output: SCOPE_MANAGEMENT pattern, metadata: `deferral_count`, `phase_gates`, `clean_exits`.

### Group 3: Adversarial Self-Review ("Grill Me")

| Signal | Detection |
|--------|-----------|
| Grill requests | "grill me", "grill as needed" |
| Honesty requests | "be honest", "be critical", "poke holes" |
| Feedback invitations | "what am I missing", "what could go wrong", "any concerns" |
| Self-assessment | "are we in good shape", "how does this look" |

Output: META_COGNITION pattern, metadata: `grill_count`, `honesty_requests`, `self_assessments`.

### Group 4: Handoff Discipline

| Signal | Detection |
|--------|-----------|
| Handoff language | "handoff", "pick up fresh", "leave context for" |
| Handoff doc creation | Write tool to files matching `*handoff*`/`*HANDOFF*` |
| Context resets | /clear followed by structured opening (bullets, file refs, numbered steps) |
| Plan file references | User message contains `.claude/plans/` path |

Output: DOCUMENTATION_DRIVEN pattern, metadata: `handoff_count`, `context_resets`, `plan_references`.

### Scope boundary
Analyzes: user message text content, message ordering/timing, command messages (/clear, /compact, /model), Write tool file paths (for handoff doc detection).
Does NOT analyze: code content in assistant responses, tool_use execution logic.
Note: checking Write tool file paths for `*handoff*` patterns is in scope — this is a lightweight metadata check to detect handoff discipline, not deep tool_use analysis.

---

## Signal Merger

### Pipeline

```
Per-session SignalResults (3 extractors × N sessions)
  → Skill Aggregation → Depth Scoring → Pattern Aggregation → Project Enrichment → Profile Assembly
```

### Skill Aggregation
- Union of evidence, deduplicate by session_id + source
- Max confidence across all signals
- Cross-extractor boost: +0.1 for 2 extractors, +0.15 for 3. Final confidence capped at 1.0.
- Preserve source tracking for transparency

### Depth Scoring

Base: existing frequency + tool_count heuristics (retained).

Modifiers:

| Signal | Effect |
|--------|--------|
| Debugging evidence on this skill | +1 level |
| Architecture discussion on this skill | +1 level |
| Multi-source detection (2+ extractors) | +1 level |
| Import only, no other evidence | cap at USED |
| Package install only | cap at MENTIONED |

Ceiling: EXPERT. Floor: MENTIONED. Cumulative but capped.

### Pattern Aggregation
- Merge session lists across extractors for same PatternType
- Frequency: ≥5 dominant, ≥3 common, ≥2 occasional, ≥1 rare
- Strength incorporates sophistication level
- Replace generic descriptions with best evidence snippet

### Project Enrichment

| Field | Source | Replaces |
|-------|--------|----------|
| description | CommSignalExtractor description_fragments | "Project X with N sessions" |
| key_decisions | BehaviorSignalExtractor architecture signals | Always-empty list |
| challenges_overcome | BehaviorSignalExtractor RECOVERY_FROM_FAILURE | Always-empty list |
| technologies | CodeSignalExtractor full skill set | Existing but richer |

### Agentic Learning Velocity (computed in Merger)

Learning velocity analysis lives in the Merger — not in any single extractor — because it needs chronologically sorted data across all sessions and draws on signals from both BehaviorSignalExtractor (agent dispatches, task decomposition, worktree usage) and CommSignalExtractor (handoff patterns, context management).

**Trackable agentic skills:**

| Skill | Sophistication Tiers (0-3) |
|-------|---------------------------|
| Agent orchestration | 0: none → 1: single agent, no type → 2: parallel, typed subagents → 3: teams, worktrees, plan-driven fan-out |
| Task decomposition | 0: none → 1: flat task list → 2: phased with naming → 3: dependency chains, file-level specificity |
| Skill workflows | 0: none → 1: single skill invocation → 2: chained skills → 3: full SDLC cycle (brainstorm→plan→execute→review) |
| Context management | 0: none → 1: occasional /clear → 2: /clear + structured reopening → 3: handoff documents + plan file contracts |
| Worktree isolation | 0: not used → 1: single worktree → 2: multi-worktree parallel agents → 3: cleanup discipline (remove + prune + branch delete) |

**Process:**
1. Sort all sessions chronologically across all projects
2. For each agentic skill, score each session 0-3 using rule-based heuristics on `SignalResult.metrics` from BehaviorSignalExtractor and `PatternSignal.metadata` from CommSignalExtractor
3. Build time series per skill
4. Run `ruptures.Pelt` (L2 cost, BIC penalty) for change point detection → level-up events
5. Output: `first_used`, `current_level`, `sessions_at_each_level`, `adoption_curve` (list of {date, score}), `levelup_events` (list of {date, from_level, to_level})

**Minimum data requirements:** Requires ≥ 10 sessions with non-zero score for a given skill to run change point detection. For skills with 5-9 sessions, use simple comparison: mean of last 3 vs. first 3. For < 5 sessions, report `first_used` and `current_level` only, no velocity claim.

**Heuristic fallback (no ruptures):** If `ruptures` import fails, fall back to: rolling average of last 5 sessions vs. first 5 → "demonstrated learning progression" if ≥ 1 tier improvement.

### Profile Assembly

| Field | New Behavior |
|-------|-------------|
| skills | 50+ entries (from 15), diverse evidence types, accurate depth |
| primary_languages | Top 5 by frequency (more data) |
| primary_domains | Actual domains, not frameworks-as-proxy |
| problem_solving_patterns | All 12 PatternType values, real descriptions |
| working_style_summary | Generated from top patterns + agentic profile |
| projects | Real descriptions, populated key_decisions/challenges |
| communication_style | Derived from CommSignalExtractor (replaces hardcoded string) |
| skill_trajectory | Adoption curves per agentic skill (previously never populated) |
| learning_velocity_notes | Summary of level-up events (previously never populated) |
| confidence_assessment | Incorporates cross-extractor corroboration |

---

## ML Enrichment Layer (Optional)

### Gate

```python
def enrichment_available() -> bool:
    try:
        import torch
        import sentence_transformers
        return True
    except ImportError:
        return False
```

If false, entire layer is a no-op. No warnings, no errors.

### Pass 1: Semantic Skill Matching (`embedding_matcher.py`)

- Model: `all-MiniLM-L6-v2` (80MB, 384-dim)
- Pre-compute taxonomy embeddings (cached to `~/.claude-candidate/embeddings_cache.npz`, invalidates on taxonomy.json hash change)
- Enrich taxonomy entries with aliases + descriptions for better embedding surface
- Hybrid: rapidfuzz first (exact matches win), embedding fallback for confidence < 0.7 or unresolved skills
- Threshold: cosine similarity ≥ 0.4
- Expected gain: ~10-15 additional skill matches ("containerization"→"docker", "k8s"→"kubernetes")

### Pass 2: Evidence Snippet Selection (`evidence_selector.py`)

- Same model (reuse loaded instance)
- Embed skill label + each candidate snippet
- Pre-filter: drop snippets < 100 chars and pure questions
- Score by cosine similarity, pick top per session
- Optional cross-encoder reranking (`ms-marco-MiniLM-L-6-v2`, 80MB) for top-5

### Pass 3: Enhanced Sophistication Classification (`learning_velocity.py`)

- Embed agent dispatch prompts to classify sophistication semantically (beyond rule-based)
- Embed task descriptions to classify decomposition quality
- Re-run change point detection on improved scores
- Note: base `ruptures` change point detection runs in the main pipeline (not torch-dependent); this pass upgrades the input signal quality

### Performance

| Operation | Cold start | Warm (cached) |
|-----------|-----------|---------------|
| Model download | ~30s (80MB) | 0 |
| Taxonomy embedding (78 entries) | ~1s | Cached |
| Evidence re-scoring (50 skills × 10 snippets) | ~3s | Per-run |
| Total enrichment overhead | ~35s first run | ~4s subsequent |

### Dependencies

```
# Base pipeline (always required)
ruptures >= 1.1.8       # 5MB, change point detection

# ML enrichment (optional)
torch >= 2.2            # ~2GB, MPS support
sentence-transformers >= 3.0  # ~50MB + model downloads
scikit-learn >= 1.4     # ~30MB, cosine similarity
```

---

## Taxonomy Expansion

All 78 taxonomy entries get content_patterns (currently 15/78 have them). Pattern design rules:

| Category | Rule | Example |
|----------|------|---------|
| Languages | Import patterns, code-block-only | python: `"import ", "from ", "def ", "class "` |
| Frameworks | Import + API-specific | nextjs: `"next/", "getServerSideProps", "NextResponse"` |
| Platforms | CLI + SDK | aws: `"aws ", "boto3", "from aws_cdk"` |
| Tools | Command patterns | postgresql: `"psql", "pg_dump", "CREATE TABLE"` |
| Practices | 2+ co-occurring signals | ci-cd: `.github/workflows` path OR `"pipeline"` + `"deploy"` |
| Domains | Domain-specific terminology only | distributed-systems: `"consensus", "sharding", "replication"` |

**Anti-greedy rule:** If a single keyword matches >30% of sessions, require co-occurrence or code-block-only constraint. **Validation:** after adding patterns, run extraction on full session corpus and assert no single pattern triggers in >30% of sessions. Add this as a test in `tests/test_taxonomy_patterns.py`.

New data file: `data/package_to_skill_map.json` (~200 entries mapping package names to canonical skills).

---

## Dependency Changes

### Added to `[project.dependencies]` in pyproject.toml:
- `ruptures >= 1.1.8` — change point detection for learning velocity (5MB, pure Python, no native deps)

### Added to `[project.optional-dependencies]` as `ml` extra:
- `torch >= 2.2`
- `sentence-transformers >= 3.0`
- `scikit-learn >= 1.4`

Install with: `pip install -e ".[ml]"` for ML enrichment, or plain `pip install -e ".[dev]"` for heuristic-only.

---

## Success Criteria

1. **Extracted skills: 50+** (from 15)
2. **Corroborated skills: 15+** (from 3)
3. **All existing tests pass** — no regressions
4. **Benchmark: 24/24 within 1 grade**
5. **All 12 PatternType values reachable** (from 4)
6. **Evidence highlights populate** on fit landing pages
7. **Project descriptions are real** — not generic
8. **Agentic learning velocity data** populates skill_trajectory
9. **ML enrichment is optional** — pipeline works without torch

## Anti-Patterns

- No Claude API calls — runs locally, no API costs
- Don't change quick_match.py (scoring engine) — calibrated and working
- Don't change fit exporter or CLI command interfaces
- Don't add greedy content patterns (>30% session match rate)
- Don't break the benchmark — run before and after every change

## Implementation Approach

Subagent-driven development with 3 parallel worktrees after serial setup:

```
Serial (define interfaces):
  1. Shared types (ExtractorProtocol, SignalResult, SkillSignal, etc.)
  2. Merger contract
  3. Refactor existing extractor into new structure (keep working)

Parallel (3 subagents, 3 worktrees):
  4a. CodeSignalExtractor (taxonomy expansion, imports, packages)
  4b. BehaviorSignalExtractor (tool patterns, agent orchestration, git, quality)
  4c. CommSignalExtractor (steering, scope, grill-me, handoffs)

Serial (integration):
  5. Signal merger integration + agentic learning velocity computation
  6. ML enrichment layer
  7. Verify all success criteria
```
