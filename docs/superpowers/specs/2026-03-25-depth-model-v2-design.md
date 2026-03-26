# Depth Model v2 — Design Spec

## Problem

The current depth inference system treats 8 Claude Code sessions as "expert." Rust (571 sessions) and TypeScript (572 sessions) are indistinguishable despite 0 years vs 8 years of real experience. Session count measures activity, not expertise. The matching engine inflates grades by matching generic skills like `software-engineering` against domain-specific requirements.

## Solution

Replace session-based depth inference with a three-source evidence model: **Resume** (anchor), **Repos** (receipts), **Sessions** (parked for v0.8). Redefine confidence as match quality, not evidence quality.

---

## Core Concepts

### Evidence Hierarchy

```
RESUME (anchor — years, depth, identity)
  The curated resume is the source of truth for skill depth and duration.
  40 skills with human-verified depths and durations.
  Cannot be replaced by any automated signal.

REPOS (receipts — verifiable, concrete)
  GitHub repos prove what you built. Languages, dependencies, tests,
  CI/CD, releases, architecture, AI engineering artifacts.
  Timeline scales naturally: (latest commit) - (earliest commit).
  Extends resume skills. Introduces new skills scoped to repo timeline.

SESSIONS (parked for v0.8)
  Session logs will power behavioral metrics in v0.8+:
  agentic orchestration maturity, debugging patterns, prompt
  sophistication, improvement velocity. Not used for depth in v0.7.
```

### Three Separated Concerns

**Depth** = How deep is the skill?
- Determined by resume (base) + repos (extension)
- Scale: mentioned → used → applied → deep → expert
- Resume provides the anchor. Repos can extend within their timeline scope.
- A 3-month repo window adds up to ~3 months of evidence. A 2-year window adds ~2 years.
- The timeline scales naturally — not hardcoded, not capped.

**Source** = Where does the evidence come from?
- `resume_only` | `repo_only` | `resume_and_repo` (corroborated)
- Informational/provenance — not a scoring penalty.
- Sessions are not a source in v0.7.

**Confidence** = How well does my skill match their requirement?
- Computed at match time in `quick_match.py`, NOT at merge time.
- Measures text-matching quality between candidate evidence and requirement description.
- "TypeScript" ↔ "TypeScript wizard who does blah blah" = high confidence.
- "React" ↔ "modern frontend framework" = medium confidence.
- If we can't map to a SPECIFIC skill, it's NO MATCH — not a low-confidence generic match.
- Edge toward failing uncertain matches. Honest gaps over inflated coverage.

### Requirement Distillation

Verbose job requirements often contain multiple distinct skills. The extraction step should break them apart:

*"5+ years building scalable distributed systems with expertise in message queues, event-driven architecture, and container orchestration"*

Becomes 4 individual skill requirements:
1. distributed-systems (5+ years)
2. message queues (specific)
3. event-driven architecture (design pattern)
4. container orchestration (kubernetes/docker)

Each matched individually. Some we'll have, some we won't. Confidence reflects how sure we are that our parsing captured what they're asking for. Claude analysis may be needed for complex/verbose requirements.

### No Session Languages

Session-derived language skills (Rust, Go, Kotlin, Java, C++) are removed from the profile entirely in v0.7. If a language is not on the resume or in a repo's actual codebase, it does not exist in the profile.

---

## New Module: Repo Scanner

### Input

`~/.claude-candidate/repos.json`:
```json
{
  "github_repos": [
    "brianruggieri/obsidian-daily-digest",
    "brianruggieri/claude-code-pulse",
    "brianruggieri/teamchat",
    "brianruggieri/garden-craft",
    "brianruggieri/roojerry.com",
    "brianruggieri/dog-playground",
    "brianruggieri/svg-playground",
    "brianruggieri/prompt-review",
    "brianruggieri/claude-personalities",
    "brianruggieri/scopework",
    "brianruggieri/skills"
  ],
  "local_repos": [
    "~/git/candidate-eval"
  ],
  "exclude": ["forks"]
}
```

### Output: RepoEvidence (per repo)

```python
class RepoEvidence(BaseModel):
    name: str
    url: str | None                     # GitHub URL (verifiable receipt)
    description: str | None
    created_at: datetime
    last_pushed: datetime
    commit_span_days: int               # first commit → last commit

    # Tech stack (ground truth)
    languages: dict[str, int]           # language → bytes
    dependencies: list[str]             # resolved via package_to_skill_map
    dev_dependencies: list[str]         # test/build tooling

    # Maturity signals
    has_tests: bool
    test_framework: str | None          # jest, pytest, vitest, bun test, etc.
    test_file_count: int
    has_ci: bool
    ci_complexity: str                  # "basic" | "standard" | "advanced"
    releases: int
    has_changelog: bool

    # AI engineering signals
    has_claude_md: bool
    has_agents_md: bool
    has_copilot_instructions: bool
    llm_imports: list[str]              # anthropic, openai, langchain, etc.
    has_eval_framework: bool            # golden sets, benchmark scripts
    has_prompt_templates: bool

    # Agentic development sophistication
    claude_dir_exists: bool             # .claude/ directory
    claude_plans_count: int             # implementation plans
    claude_specs_count: int             # design specs
    claude_handoffs_count: int          # handoff documents
    claude_grill_sessions: int          # design review sessions
    claude_memory_files: int            # project memory files
    has_settings_local: bool            # .claude/settings.local.json
    has_ralph_loops: bool               # autonomous task loops
    has_superpowers_brainstorms: bool   # .superpowers/brainstorm/
    has_worktree_discipline: bool       # .worktrees/ or worktree refs

    # AI maturity composite
    ai_maturity_level: str              # "basic" | "intermediate" | "advanced" | "expert"

    # Architecture signals
    file_count: int
    directory_depth: int
    source_modules: int                 # distinct top-level source dirs
```

### Output: RepoProfile (aggregate)

```python
class RepoProfile(BaseModel):
    repos: list[RepoEvidence]
    scan_date: datetime
    repo_timeline_start: datetime       # earliest commit across all repos
    repo_timeline_end: datetime         # latest commit across all repos
    repo_timeline_days: int             # total span (scales naturally)

    # Aggregated per-skill evidence
    skill_evidence: dict[str, SkillRepoEvidence]
    # SkillRepoEvidence contains:
    #   repos: int              — count of repos with this skill
    #   total_bytes: int        — total code bytes across repos
    #   first_seen: datetime    — earliest commit with this skill
    #   last_seen: datetime     — latest commit with this skill
    #   frameworks: list[str]   — detected frameworks via dependencies
    #   test_coverage: bool     — tests exist for this skill's code
    # e.g., "typescript": {repos: 5, total_bytes: 2.8M,
    #        first_seen: 2026-01-30, last_seen: 2026-03-25,
    #        frameworks: ["react", "vitest", "bun"]}

    # Aggregated maturity
    repos_with_tests: int
    repos_with_ci: int
    repos_with_releases: int
    repos_with_ai_signals: int
```

### AI Maturity Level Derivation

| Level | Requirements |
|-------|-------------|
| basic | has_claude_md only |
| intermediate | + llm_imports + prompt_templates |
| advanced | + eval_framework + plans + specs + CI |
| expert | + handoff protocol + grill sessions + ralph loops + permission model + memory system |

### Extraction Approach

1. **Local-first:** Check `~/git/` (or configured paths) for existing clones matching the repo name. Most repos are already cloned — no need to re-download.
2. **Fallback to GitHub API:** For repos not found locally, use API for languages, SBOM, releases. Clone to a temp directory only if deeper signals are needed (test dirs, CI configs, CLAUDE.md). Temp clones go to `~/.claude-candidate/repo-cache/` and are reused on subsequent scans.
3. **Local repos get full scan:** filesystem analysis for all signals (dependencies, tests, CI, AI artifacts) — no API calls needed.
4. Resolve dependencies through existing `package_to_skill_map.json` (240+ mappings)

### CLI Commands

- `claude-candidate repos scan` — scan configured repos, write `~/.claude-candidate/repo_profile.json`
- `claude-candidate repos list` — show configured repos and last scan date
- `claude-candidate profile rebuild` — re-merge resume + repos into fresh merged profile

---

## Merger Redesign

### New Merge Function

`merge_triad(curated_resume, repo_profile) → MergedEvidenceProfile`

The existing `merge_with_curated()` stays as a fallback for users without repos. Sessions are not an input in v0.7.

### Merge Rules

**For LANGUAGE / FRAMEWORK / TOOL / PLATFORM skills:**

| Evidence | Depth Treatment |
|----------|----------------|
| Resume says expert, 8 years | Expert. Resume is the anchor. |
| Resume says deep, 2 years + repos confirm 5 projects | Deep. Repo confirms but doesn't override. |
| Not on resume, but in repos | Depth scales with repo timeline: ≤3 months → Applied, 6+ months → Deep, 18+ months → Expert. Not capped — grows naturally with sustained evidence. |
| Not on resume, not in repos | Does not exist in profile. |

**For PRACTICE / DOMAIN skills:**

| Evidence | Depth Treatment |
|----------|----------------|
| Resume says deep + repos show tests/CI/releases | Deep, strong evidence. |
| Not on resume, repos show consistent testing across 7 repos | Applied. Inferred from repo signals. |
| Repos show AI maturity level = expert | Agentic-workflows: Expert (repo-evidenced). |

**For AGENTIC ORCHESTRATION (new):**

| Evidence | Depth Treatment |
|----------|----------------|
| ai_maturity_level = expert (from repo scan) | Expert. Repos ARE the evidence. |
| ai_maturity_level = advanced | Deep. |
| ai_maturity_level = intermediate | Applied. |
| ai_maturity_level = basic | Used. |

### Repo Timeline Scaling

The repo evidence window is always computed dynamically:
```
repo_timeline_days = (latest_commit_across_all_repos) - (earliest_commit_across_all_repos)
```

- March 2026: ~60 days of repo evidence
- March 2027: ~425 days → approaching "1+ years"
- March 2028: ~790 days → approaching "2+ years"

Skills introduced during the repo window are scoped to this timeline. Not hardcoded. Not capped. Grows with the actual journey.

### MergedSkillEvidence Changes

```python
class MergedSkillEvidence(BaseModel):
    name: str
    source: EvidenceSource              # resume_only | repo_only | resume_and_repo

    # Resume evidence
    resume_depth: DepthLevel | None
    resume_duration: str | None         # "8 years", "2 months"

    # Repo evidence (NEW)
    repo_count: int | None              # repos where this skill appears
    repo_bytes: int | None              # total bytes across repos
    repo_first_seen: datetime | None    # earliest repo commit with this skill
    repo_last_seen: datetime | None     # latest repo commit with this skill
    repo_frameworks: list[str] | None   # frameworks detected via dependencies
    repo_confirmed: bool = False        # skill found in repo evidence

    # Merged assessment
    effective_depth: DepthLevel
    category: str | None

    # REMOVED from merge time:
    # confidence — moves to match time
    # session_depth, session_frequency, session_evidence_count, session_recency
    # session_first_seen, discovery_flag
```

### EvidenceSource Enum Changes

```python
class EvidenceSource(str, Enum):
    RESUME_ONLY = "resume_only"         # On resume, not in repos
    REPO_ONLY = "repo_only"             # In repos, not on resume
    RESUME_AND_REPO = "resume_and_repo" # Both — strongest evidence
    # SESSIONS_ONLY — removed in v0.7
    # CORROBORATED — renamed to RESUME_AND_REPO
    # CONFLICTING — removed (resume is always the anchor, no conflict)
```

---

## Matching Engine Changes

### Confidence = Match Quality

Confidence moves from merge time to match time. It measures how precisely a candidate skill maps to a job requirement's text.

```python
# In quick_match.py, during _find_best_skill():

confidence = compute_match_confidence(
    candidate_skill=matched_skill,     # e.g., "typescript"
    requirement_text=req.description,  # e.g., "TypeScript wizard who builds..."
    match_type=match_type,             # exact | alias | fuzzy | related | none
)

# Confidence scale:
# 1.00 — exact canonical match ("typescript" ↔ requirement mentions typescript)
# 0.90 — alias match ("React.js" ↔ "react")
# 0.70 — strong contextual match (requirement clearly asks for this skill)
# 0.40 — weak/tangential match (requirement partially related)
# 0.00 — no match. If we can't map to a SPECIFIC skill, it's no match.
```

### Match Honesty

Generic fallback matches are eliminated:
- `software-engineering` no longer matches domain-specific requirements
- If a requirement asks for "embedded C firmware" and the candidate has no `c` or firmware-related skill, it's `no_evidence` — not a partial match to `software-engineering`
- Edge toward failing uncertain requirements

### Requirement Distillation

For verbose/complex requirements, use Claude analysis to break them into individual skill requirements before matching. Each sub-requirement matched independently.

### Cleanup: Remove Ralph Loop Band-aids

These quick_match.py patches from the ralph loop are removed — they were fixing symptoms of bad depth data:
- Domain gap keyword expansion (keep core mechanism, remove expanded keywords)
- Skill concentration penalty
- Weak must-have ratio penalty
- Sessions-only language cap
- Session depth cap by session count

With accurate depth data from resume + repos, these aren't needed.

---

## Cleanup: Dead Code and Data Fixes

### Dead Code Removal (~430 lines)

| Item | File | Lines |
|------|------|-------|
| `build_candidate_profile()` | extractor.py | 803-851 |
| `_build_skill_entries()` + 5 helpers | extractor.py | 531-657 |
| `_signals_to_normalized_session()` | extractor.py | 732-800 |
| `CATEGORY_MAP` | extractor.py | 92-118 |
| `SkillEntry.context_notes` | candidate_profile.py | 85 |
| `ProblemSolvingPattern.counter_evidence` | candidate_profile.py | 120 |
| Unused `session` variable | extractor.py | 384 |

### Curated Resume Fixes

| Fix | Current | Corrected |
|-----|---------|-----------|
| Truncated skill | `llm integration (anthropic` | → `llm` (canonical) |
| Unmatchable skill | `ai provider abstraction` | → add as alias for `agentic-workflows` |
| Unmatchable skill | `ai-augmented development tooling` | → add as alias for `developer-tools` |

### Taxonomy Additions

Add aliases to support curated resume skill names and repo-detected skills:
- `agentic-workflows`: add `"ai provider abstraction"` alias
- `developer-tools`: add `"ai-augmented development tooling"` alias

---

## What Stays the Same

- **Taxonomy and alias system** — well-designed, no changes needed
- **Virtual skill inference** — on-demand synthesis of meta-skills (full-stack, frontend-dev, etc.)
- **Pattern-to-skill mapping** — behavioral patterns → skill evidence
- **AI composite scoring** — 5-dimension scoring for agentic skills (future use in v0.8)
- **FitAssessment output schema** — downstream consumers unaffected
- **Extension and server** — consume the same assessment output
- **Golden set benchmark** — retains all 47 postings for regression testing

---

## Migration Path

1. Build `repo_scanner.py` module + CLI commands
2. Create `repos.json` config pointing to GitHub repos
3. Run `claude-candidate repos scan` → produces `repo_profile.json`
4. Implement `merge_triad()` in `merger.py`
5. Update `quick_match.py`: move confidence to match time, remove band-aids
6. Fix curated resume (3 orphaned skills)
7. Remove dead code
8. Re-run golden set benchmark → expect significant improvement
9. Calibrate any remaining mismatches

## Success Criteria

- All 47 golden set postings grade within ±1 step of expected
- Zero false language expertise (no Rust/Go/Kotlin/Java/C++ in profile)
- Resume depth is never overridden by automated signals
- Confidence reflects match quality, not evidence quality
- Tests pass (1224+)
- Repo timeline scales naturally with time
