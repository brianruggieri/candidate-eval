# v0.3 Agent Team Design Spec

**Date:** 2026-03-16
**Status:** Approved
**Approach:** Lead + Rolling Specialists (Option A)
**Pipeline:** Rolling (Option C) — P1 first, P2+P3 when P1 scanner works, P4+P5 when P2/P3 produce outputs
**Checkpoints:** Milestone-based (Option A) with active collaboration (Option C) between gates
**Code standards:** Refactor on contact (Option B) — new code complies, touched modules get refactored
**Visual testing:** Both surfaces (Option C) — Chrome extension popup + generated documents
**Testing philosophy:** Real data as much as possible. No mocks unless external API constraints require it.

---

## 1. Team Architecture

5 agents total. Only 2-3 active at any time (Lead + current feature agent + QA).

### Lead Architect

- **Model:** Opus
- **Lifetime:** Entire session
- **Owns:** Design specs, team coordination, milestone reviews, decision surfacing
- **Creates:** Tasks, spawns teammates, writes specs to `docs/superpowers/specs/`
- **Reviews:** All commits before each checkpoint. Runs integration tests across features.
- **Shared files (exclusive access):** `cli.py`, `server.py`, `schemas/*.py`, `pyproject.toml`, `conftest.py`, `extension/*`
- **Surfaces to user:** Design trade-offs, ambiguous requirements, milestone completion, visual QA results

### Session Pipeline Agent

- **Model:** Opus
- **Starts:** Phase 1 (immediately)
- **Priority:** P1
- **Files owned:**
  - `src/claude_candidate/session_scanner.py`
  - `src/claude_candidate/sanitizer.py`
  - `src/claude_candidate/extractor.py`
  - `tests/test_session_scanner.py`
  - `tests/test_sanitizer.py`
  - `tests/test_extractor.py`
  - `tests/fixtures/sessions/`
- **Modifies (via Lead):** `cli.py` (adds `sessions scan` command), `schemas/candidate_profile.py` (if new fields needed)
- **Done when:** Tests pass, ruff clean, real session data produces a valid CandidateProfile, no raw content leaks

### Intelligence Agent

- **Model:** Opus
- **Starts:** Phase 2 (when P1 scanner is functional)
- **Priorities:** P2 + P3
- **Files owned:**
  - `src/claude_candidate/requirement_parser.py`
  - `src/claude_candidate/correlator.py`
  - `tests/test_requirement_parser.py`
  - `tests/test_correlator.py`
  - `tests/cassettes/`
  - `tests/fixtures/claude_responses/`
  - `scripts/record_claude_fixtures.py`
- **Modifies (via Lead):** `quick_match.py` (swap keyword matching for Claude-parsed reqs — logic changes only), `cli.py` (adds `job parse` and `match correlate` commands)
- **Done when:** Tests pass, ruff clean, real job postings produce structured requirements, GitHub repos correlate with sessions

### Output Agent

- **Model:** Opus
- **Starts:** Phase 3 (when P2/P3 produce outputs)
- **Priorities:** P4 + P5
- **Files owned:**
  - `src/claude_candidate/proof_generator.py`
  - `src/claude_candidate/generator.py`
  - `tests/test_proof_generator.py`
  - `tests/test_generator.py`
  - `tests/fixtures/golden_outputs/`
- **Modifies (via Lead):** `server.py` (adds proof/deliverable endpoints), `cli.py` (adds `generate` and `proof` commands)
- **Done when:** Tests pass, ruff clean, generated outputs render well visually, evidence chain is verifiable

### QA Agent

- **Model:** Sonnet
- **Starts:** Phase 1 (immediately, runs throughout all phases)
- **Priority:** Cross-cutting
- **Responsibilities:**
  - Run full test suite after each feature lands
  - Refactor-on-contact: bring touched modules up to code standards
  - Visual QA: test Chrome extension popup via Playwright, review generated documents in browser
  - Integration tests: verify cross-feature data flows
  - Ruff + type checking enforcement
- **Files owned:**
  - `tests/test_integration.py` (extends existing 9 tests)
  - `tests/test_visual_*.py` (new Playwright tests)
  - `tests/__snapshots__/`
  - `tests/strategies.py` (hypothesis strategies)
  - Any module being refactored for compliance
- **Reports to:** Lead — flags test failures, visual issues, compliance violations

---

## 2. Rolling Pipeline Phases

### Phase 1: Foundation

**Active agents:** Lead + Session Pipeline + QA

**Session Pipeline Agent work:**
1. Design spec for scanner/sanitizer/extractor
2. TDD: write tests first against sanitized real session fixtures
3. Implement session scanner (find JSONL files in `~/.claude/projects/`)
4. Implement sanitizer (strip secrets, API keys, PII, proprietary code)
5. Implement extractor (technologies used, problem-solving patterns, project summaries)
6. CLI command: `claude-candidate sessions scan [--session-dir PATH] [--output PATH]`

**QA Agent work (parallel):**
1. Request new dev dependencies via SendMessage to Lead (Lead applies to `pyproject.toml`): vcrpy, pytest-recording, syrupy, hypothesis, pytest-subprocess
2. Set up Playwright for Chrome extension testing
3. Write baseline visual tests for existing extension popup
4. Audit existing code for new standards compliance (identify refactor-on-contact candidates)
5. Create `tests/strategies.py` with hypothesis strategies for existing Pydantic models

**Lead work:**
1. Wire `sessions scan` CLI command into `cli.py`
2. Update schemas if new fields needed
3. Surface design decisions to user

**Checkpoint 1 — User reviews:**
- Real session data produces a valid CandidateProfile (user's actual Claude Code sessions)
- Sanitizer proves no raw content leaks (user verifies privacy)
- All existing 195 tests + new P1 tests pass
- QA baseline visual tests for extension

**Gate:** User approves the real CandidateProfile before downstream features start consuming it.

### Phase 2: Intelligence

**Active agents:** Lead + Intelligence + QA (Session Pipeline shuts down)

**Intelligence Agent work:**
1. Build requirement parser using `claude --print` CLI for NLP parsing
2. Build GitHub repo correlator (API fetch, filename/temporal/content matching)
3. Update `quick_match.py` logic to use Claude-parsed requirements (logic changes only — QA handles structural refactoring)
4. CLI commands: `job parse`, `match correlate` (follows existing group-subcommand pattern)

**QA Agent work (parallel):**
1. Record VCR cassettes for GitHub API calls (`pytest --record-mode=once`)
2. Record golden file fixtures for `claude --print` outputs
3. Refactor `quick_match.py` for code standards compliance after Intelligence Agent finishes logic changes (20-line functions, complexity limits)
4. Integration tests: session data -> merge -> Claude-parsed match
5. Test correlator against user's real GitHub repos
6. Visual test: extension shows improved match scores

**Lead work:**
1. Wire `job parse` and `match correlate` CLI commands
2. Update server endpoints if needed
3. Surface quality comparison (Claude-parsed vs. keyword matching) to user

**Checkpoint 2 — User reviews:**
- Claude-parsed requirements vs. old keyword matching — quality comparison on real postings
- GitHub correlations make sense for user's repos
- Match scores are more accurate with real data + NLP parsing
- Extension popup reflects improved scoring

**Gate:** User approves the intelligence layer quality before output generation uses it.

### Phase 3: Output

**Active agents:** Lead + Output + QA (Intelligence shuts down)

**Output Agent work:**
1. Build proof package generator (markdown report, evidence chain, manifest hash verification)
2. Build deliverable generator (tailored resume bullets, cover letter, interview prep)
3. Server endpoints for proof/deliverable generation
4. CLI commands: `proof`, `generate`

**QA Agent work (parallel):**
1. Visual QA: proof packages render well in browser (render markdown to HTML, Playwright checks)
2. Visual QA: cover letters and resume bullets look professional
3. Snapshot tests (syrupy) on generated outputs
4. Full end-to-end integration test: scan -> merge -> match -> proof -> deliverable
5. Evidence chain tests: every claim in proof links back to valid SessionReference

**Lead work:**
1. Wire `proof` and `generate` CLI commands
2. Update extension with proof/deliverable access buttons
3. Surface generated outputs for user review

**Checkpoint 3 — User reviews:**
- Proof package for a real job posting — would user send this to a hiring manager?
- Generated cover letter and resume bullets — do they represent user well?
- Interview prep notes — are they useful?
- Visual quality of all rendered outputs

**Gate:** User approves the output quality. This is what employers see.

### Final: Polish & Ship

**Active agents:** Lead + QA only (all feature agents shut down)

**QA Agent work:**
1. Full regression suite (target ~300+ tests)
2. Visual QA pass on extension + all generated documents
3. Code standards audit on all touched modules
4. Final integration test: complete pipeline end-to-end

**Lead work:**
1. Version bump to 0.3.0
2. Update README
3. End-to-end demo for user
4. Clean up team

**Checkpoint 4 — Final review:**
- Full end-to-end demo: scan sessions -> parse job -> match -> proof package -> deliverables
- All tests pass (195 existing + all new)
- All touched modules comply with code standards
- Chrome extension visual QA passes
- Version bump to 0.3.0, updated README

**Gate:** User approves v0.3.0 for daily use.

---

## 3. Quality Gates

### Automated Gates (enforced on every commit)

| Gate | Requirement |
|------|------------|
| All tests pass | 195 existing + all new tests. Zero regressions. |
| Ruff clean | `ruff check` with zero violations. |
| Code standards | Refactor-on-contact: touched modules comply with limits (functions <= 20 lines, cyclomatic complexity <= 5, cognitive complexity <= 8, positional params <= 3, no magic numbers, no single-letter vars). |
| Pydantic round-trip | Every new/modified Pydantic model has `model_dump_json` -> `model_validate_json` tests. |
| Privacy check | No absolute paths in output. No raw session content. Evidence snippets <= 500 chars. Sanitizer tests verify redaction. |
| Evidence chain | Every skill claim traces to a `SessionReference`. Tests verify no orphaned claims. |

### Three Invariants (from HANDOFF-V03.md)

1. **Evidence chain:** Every assessment claim traces back through SessionReference -> SessionManifest -> original file hash. Break the chain, break the product.
2. **Honesty calibration:** Scores reflect reality. A "strong_yes" that leads to a bad interview is worse than a "maybe" that sets correct expectations.
3. **Privacy model:** No candidate data leaves localhost. No raw session content in outputs. Sanitizer is the trust boundary.

---

## 4. Real-Data Testing Strategy

### Principle

Test with real data as much as possible. Only mock when external API constraints (cost, rate limits, non-determinism) make real calls impractical — and even then, use recorded real responses rather than hand-written mocks.

### New Test Libraries

| Library | Purpose | How it avoids mocks |
|---------|---------|-------------------|
| `vcrpy >= 8.0` + `pytest-recording >= 0.13` | HTTP record/replay for GitHub API (P3), enrichment | Records real HTTP responses on first run, replays from cassette files |
| `syrupy >= 4.0` | Snapshot testing for assessments, profiles, generated outputs | Captures real output on first run, detects regressions |
| `hypothesis >= 6.100` | Property-based testing for Pydantic schemas, scoring edge cases | Generates random valid model instances |
| `pytest-subprocess >= 1.5` | Subprocess replay for `claude --print` calls (P2) | Replays golden file outputs recorded from real Claude runs |

### Per-Feature Testing

| Feature | Test approach |
|---------|--------------|
| P1: Session Extractor | Sanitized real session fixtures committed to `tests/fixtures/sessions/`. Edge cases: empty sessions, malformed JSON, no tech signals, very long sessions. |
| P2: Requirement Parser | Golden file fixtures from real `claude --print` runs. A `scripts/record_claude_fixtures.py` script regenerates them. Fallback to keyword matching tested separately. |
| P3: Repo Correlator | VCR.py cassettes from real GitHub API. First run with `--record-mode=once` hits real API. Auth headers filtered from cassettes. |
| P4: Proof Generator | Snapshot testing (syrupy) on generated markdown. Visual QA via Playwright renders to HTML. Evidence chain verification. |
| P5: Deliverables | Golden files + snapshots from real Claude-generated content. Visual QA checks formatting. Tests verify no template placeholders leak. |

### What still gets mocked (2 things only)

1. **`claude --print` subprocess:** Golden file fixtures from real runs. Can't call Claude API in CI (cost, latency, non-determinism).
2. **GitHub API in CI:** VCR cassettes from real responses. Rate limits make real calls unreliable in CI.

Everything else — SQLite, ASGI app, file I/O, CLI, business logic, Pydantic models — stays fully real.

### Test Count Target

- Starting: 195 tests
- P1 target: +40-50 tests (scanner, sanitizer, extractor)
- P2+P3 target: +25-35 tests (parser, correlator)
- P4+P5 target: +20-30 tests (generators)
- Integration + visual: +15-20 tests
- **Expected total: ~300-330 tests by v0.3.0**

---

## 5. Orchestration

### Team Configuration

| Setting | Value |
|---------|-------|
| Team name | `candidate-eval-v03` |
| Display mode | In-process (`Shift+Down` to cycle agents) |
| Shared task list | All agents see the same board. Tasks have dependencies. |
| Agent messaging | `SendMessage` for coordination. Lead broadcasts phase transitions. |
| Permission mode | `plan` initially (read-only). Lead switches to `acceptEdits` after spec approval. |

### File Ownership

Each agent owns specific files. No two agents edit the same file.

**Session Pipeline Agent:** `session_scanner.py`, `sanitizer.py`, `extractor.py`, corresponding tests, `fixtures/sessions/`

**Intelligence Agent:** `requirement_parser.py`, `correlator.py`, corresponding tests, `cassettes/`, `fixtures/claude_responses/`

**Output Agent:** `proof_generator.py`, `generator.py`, corresponding tests, `fixtures/golden_outputs/`

**QA Agent:** `test_integration.py`, `test_visual_*.py`, `__snapshots__/`, `strategies.py`

**Lead only (serialized access):** `cli.py`, `server.py`, `schemas/*.py`, `pyproject.toml`, `conftest.py`, `extension/*`

Feature agents request changes to shared files via SendMessage. Lead applies them to prevent merge conflicts.

### Communication Patterns

| Direction | Content |
|-----------|---------|
| Feature -> Lead | "I need a new schema field for X" / "CLI command spec ready" / "Blocked on unclear requirement" |
| Lead -> User | Trade-offs, design decisions, checkpoint summaries, visual QA screenshots, unexpected findings |
| QA -> Lead | Test results, compliance violations, visual regressions, integration failures |
| Lead -> Feature | Schema changes applied, shared file updates done, "your CLI command is wired up" |
| Lead -> QA | "Feature X just landed, run integration tests" / "Refactor this module for standards" |

### Git Strategy

- Single feature branch: `feat/v0.3-agent-pipeline`
- Agents commit directly (no inter-agent PRs)
- Lead reviews commits before each checkpoint
- One PR at the end merges full v0.3 into main
- No Co-Authored-By trailers on commits (per user CLAUDE.md)
- Brief imperative commit messages ("Add session scanner", "Fix sanitizer regex")

### "Modifies via Lead" Protocol

When a feature agent needs changes to a Lead-owned file:

1. Agent sends a `SendMessage` to Lead with: the file to modify, the change needed (code block or description), and why
2. Lead reviews the request, applies the change, and runs tests
3. Lead confirms completion via `SendMessage` back to the agent
4. If the change conflicts with another agent's work, Lead resolves and notifies both

### Gate Failure Protocol

If a user rejects a checkpoint:

1. Lead identifies the failing criteria from user feedback
2. Lead creates new tasks scoped to the specific issues (not a full phase restart)
3. The relevant agent (feature or QA) picks up the fix tasks
4. QA re-runs the relevant test suite after fixes
5. Lead re-presents the checkpoint to the user
6. If the same checkpoint fails 3 times, Lead escalates to the user for scope re-evaluation

### New Directories

These directories will be created during v0.3 (they do not exist yet):

- `tests/fixtures/sessions/` — sanitized real session JSONL files (P1)
- `tests/fixtures/claude_responses/` — golden file outputs from real Claude runs (P2)
- `tests/cassettes/` — VCR.py HTTP response recordings (P3)
- `tests/fixtures/golden_outputs/` — snapshot reference outputs for generators (P4/P5)
- `tests/__snapshots__/` — syrupy snapshot files
- `scripts/` — utility scripts (fixture recording, etc.)

---

## 6. Active Collaboration Points

Between checkpoints, the Lead surfaces these to the user:

- **Design trade-offs** (e.g., "sanitizer can be aggressive or conservative — which do you prefer?")
- **Ambiguous requirements** (e.g., "should proof packages include session dates or just date ranges?")
- **Unexpected discoveries** (e.g., "your sessions show a skill not on your resume — should we highlight it?")
- **Visual QA screenshots** for quick feedback
- **Quality comparisons** (e.g., Claude-parsed vs. keyword matching results side-by-side)

---

## 7. Code Standards (Refactor on Contact)

When a new feature touches an existing module, that module gets refactored to comply:

| Standard | Limit |
|----------|-------|
| Function length | <= 20 lines |
| Cyclomatic complexity | <= 5 per function |
| Cognitive complexity | <= 8 per function |
| Positional parameters | <= 3 per function |
| Line width | 100 characters |
| Imports | Absolute only |
| Magic numbers | Named constants (except 0, 1, -1) |
| Commented-out code | Delete it |
| Single-letter variables | Only in loop iterators |
| Indentation | 4 spaces (project convention — 15/17 source files use spaces) |

Modules not touched by v0.3 features are left as-is.

---

## 8. Fixture Strategy

Session test fixtures are **sanitized from real data**, not synthetic:

1. Run the sanitizer against real `~/.claude/projects/` JSONL files
2. The sanitizer strips PII, secrets, API keys, and proprietary code
3. Preserve structure, message types, and technology signals
4. Truncate long sessions to representative length
5. Commit sanitized fixtures to `tests/fixtures/sessions/`

This gives us real data structure and signal patterns without privacy exposure.

### Playwright Chrome Extension Testing

Chrome extension testing via Playwright requires a persistent browser context with the extension loaded:

```python
context = await browser.new_context(
    args=[f"--load-extension={extension_path}", "--disable-extensions-except={extension_path}"]
)
```

QA Agent should set this up in Phase 1 as part of the Playwright baseline work. The extension popup is tested by navigating to the extension's popup URL within the persistent context.
