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
- **Output schema unchanged** — CandidateProfile, SkillEntry, ProblemSolvingPattern, ProjectSummary stay as-is
- **Same CLI interface** — `sessions scan` still works
- **Each extractor reads the same JSONL files** independently
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
│   └── taxonomy.json         → Updated with content_patterns for all 85 entries
```

---

## Shared Interfaces

### SignalResult

```python
@dataclass
class SignalResult:
    """One extraction layer's output for a single session."""
    session_id: str
    session_date: datetime
    project_context: str
    git_branch: str | None
    skills: dict[str, SkillSignal]
    patterns: list[PatternSignal]
    project_signals: ProjectSignal | None
    metrics: dict[str, float]
```

### SkillSignal

```python
@dataclass
class SkillSignal:
    """A single skill detection from one extractor."""
    canonical_name: str
    source: Literal[
        "file_extension", "content_pattern", "import_statement",
        "package_command", "tool_usage", "agent_dispatch",
        "skill_invocation", "user_message", "git_workflow"
    ]
    confidence: float          # 0.0-1.0
    depth_hint: DepthLevel | None
    evidence_snippet: str
    evidence_type: Literal[
        "direct_usage", "architecture_decision", "debugging",
        "teaching", "evaluation", "integration", "refactor",
        "testing", "review", "planning"
    ]
    metadata: dict
```

### PatternSignal

```python
@dataclass
class PatternSignal:
    """A behavioral or communication pattern detection."""
    pattern_type: PatternType  # all 12 values now reachable
    session_ids: list[str]
    confidence: float
    description: str
    evidence_snippet: str
    metadata: dict
```

### ProjectSignal

```python
@dataclass
class ProjectSignal:
    """Project-level enrichment from a single session."""
    key_decisions: list[str]
    challenges: list[str]
    description_fragments: list[str]
```

---

## Code Signal Extractor (Tier 1)

### Detection Layers

**Layer 1: File extension mapping** (existing, unchanged)
- Current FILE_EXTENSION_MAP with 16 extensions
- Source: `"file_extension"`, confidence: 0.9

**Layer 2: Content patterns from taxonomy** (existing, massively expanded)
- Expand from 17/85 to 85/85 entries with content_patterns
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
| .md documentation edits | `"review"` |
| Brainstorm/plan Skill invocation | `"planning"` |
| Structure-only Edit | `"refactor"` |
| Default | `"direct_usage"` |

### Scope boundary
Only analyzes: tool_use structured events, file paths, Bash commands, git metadata, error flags, message sequencing.
Does NOT analyze: code content, user message text.

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

### Group 5: Agentic Learning Velocity

**Trackable agentic skills:**

| Skill | Sophistication Tiers |
|-------|---------------------|
| Agent orchestration | Basic: single, no type → Intermediate: parallel, typed → Advanced: teams, worktrees, plan-driven |
| Task decomposition | Basic: flat list → Intermediate: phased → Advanced: dependencies, file-level specificity |
| Skill workflows | Basic: single skill → Intermediate: chained → Advanced: full SDLC cycle |
| Context management | Basic: none → Intermediate: occasional resets → Advanced: structured handoffs + plan files |
| Worktree isolation | Binary: not used → used (cleanup discipline as bonus) |

**Process:**
1. Score each session (0-3 sophistication) per agentic skill — rule-based from structured tool_use metadata
2. Sort sessions chronologically, build time series per skill
3. Run `ruptures.Pelt` for change point detection (level-up events)
4. Output: `first_used`, `current_level`, `sessions_at_each_level`, `adoption_curve`, `levelup_events`

Without ML enrichment, a heuristic fallback: rolling average of last 5 sessions vs. first 5 → "demonstrated learning progression" if ≥ 1 tier improvement.

### Scope boundary
Only analyzes: user message text, message ordering/timing, command messages, Write tool paths for handoff docs.
Does NOT analyze: code content, tool_use metadata (except to identify steering context).

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
- Cross-extractor boost: +0.1 for 2 extractors, +0.15 for 3
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
| Taxonomy embedding (85 entries) | ~1s | Cached |
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

All 85 taxonomy entries get content_patterns. Pattern design rules:

| Category | Rule | Example |
|----------|------|---------|
| Languages | Import patterns, code-block-only | python: `"import ", "from ", "def ", "class "` |
| Frameworks | Import + API-specific | nextjs: `"next/", "getServerSideProps", "NextResponse"` |
| Platforms | CLI + SDK | aws: `"aws ", "boto3", "from aws_cdk"` |
| Tools | Command patterns | postgresql: `"psql", "pg_dump", "CREATE TABLE"` |
| Practices | 2+ co-occurring signals | ci-cd: `.github/workflows` path OR `"pipeline"` + `"deploy"` |
| Domains | Domain-specific terminology only | distributed-systems: `"consensus", "sharding", "replication"` |

**Anti-greedy rule:** If a single keyword matches >30% of sessions, require co-occurrence or code-block-only constraint.

New data file: `package_to_skill_map.json` (~200 entries mapping package names to canonical skills).

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
  4c. CommSignalExtractor (steering, scope, grill-me, handoffs, velocity)

Serial (integration):
  5. Signal merger integration
  6. ML enrichment layer
  7. Verify all success criteria
```
