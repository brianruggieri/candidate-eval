# HANDOFF: claude-candidate v0.3 Implementation

## To the Next Team Lead

You are picking up an active, working project. Read this document fully before delegating any work. The codebase is real, tested, and deployed to the developer's local machine.

---

## Current State (v0.2.0)

**12 commits, 195 tests passing, ~6,600 lines of Python, working Chrome extension.**

### What's Built and Working

| Component | Files | Tests | Status |
|-----------|-------|-------|--------|
| Pydantic v2 Schemas (8) | `src/claude_candidate/schemas/` | 25 | Production-ready |
| Manifest Module | `manifest.py` | 21 | SHA-256 hashing, session scanning, verification |
| Profile Merger | `merger.py` | 21 | Three merge modes, evidence provenance |
| Quick Match Engine | `quick_match.py` | 15 | Three-dimension scoring (skills/mission/culture) |
| SQLite Storage | `storage.py` | 26 | Assessments, watchlist, profiles CRUD |
| FastAPI Server | `server.py` | 32 | 10 endpoints on localhost:7429 |
| Resume Parser | `resume_parser.py` | 19 | pymupdf extraction, handles two-column PDFs |
| Company Enrichment | `enrichment.py` | 27 | Heuristic extraction, 7-day cache |
| Chrome Extension | `extension/` | — | MV3, LinkedIn/Greenhouse/Lever/Indeed extractors |
| CLI | `cli.py` | 9 | assess, manifest, profile, resume, server commands |

### What's Using Sample Data

The candidate profile at `~/.claude-candidate/candidate_profile.json` is a **sample fixture** — not the developer's real Claude Code session logs. This means:
- Skills marked "sessions-only" are from fake data
- Resume claims flagged as "unverified" may actually be demonstrated in real sessions
- The dual-source evidence chain (the product's key differentiator) is not yet functional

### Key Files to Read First

1. `PROJECT.md` — Full product vision and architecture
2. `plans/04-browser-extension-quick-match.md` — Daily-driver feature spec
3. `plans/02-agent-team-orchestration.md` — Pipeline agent architecture
4. `plans/03-session-manifest-hashing.md` — Trust layer spec
5. `src/claude_candidate/schemas/` — All 8 schema files (the data contracts)
6. `src/claude_candidate/quick_match.py` — The scoring engine
7. `tests/` — Testing patterns to follow

---

## What Remains to Build

### Priority 1: Session Log Extractor (HIGHEST VALUE)

**Why first:** Without this, all assessments are resume-only. This is the feature that makes claude-candidate unique — demonstrating skills through actual Claude Code session evidence.

**What it does:**
1. Scan `~/.claude/projects/` for JSONL session log files
2. Sanitize each session (strip secrets, API keys, PII, proprietary code)
3. Extract signals: technologies used (with frequency/depth), problem-solving patterns, project summaries, decision-making evidence
4. Build a real `CandidateProfile` from the extracted signals
5. Save to `~/.claude-candidate/candidate_profile.json`

**Files to create:**
- `src/claude_candidate/session_scanner.py` — Find and read JSONL session files
- `src/claude_candidate/sanitizer.py` — Redact secrets, paths, PII
- `src/claude_candidate/extractor.py` — Extract skills, patterns, projects from sanitized sessions
- `tests/test_session_scanner.py`
- `tests/test_sanitizer.py`
- `tests/test_extractor.py`

**Implementation approach:**
- The session JSONL files contain conversation turns with role/content pairs
- Technology detection: regex-match file extensions, import statements, tool names, CLI commands
- Pattern detection: look for debugging sequences, architecture discussions, test-writing, refactoring
- Project detection: group sessions by `project_context` path, extract project names and descriptions
- Depth calibration: frequency across sessions matters more than single mentions
- The `CandidateProfile` schema already exists — populate it from extracted data

**CLI command:** `claude-candidate sessions scan [--session-dir PATH] [--output PATH]`

**Key constraint:** No raw session content in the output. Only structured summaries and evidence snippets (max 500 chars per `SessionReference.evidence_snippet`).

**Testing:** Create synthetic JSONL session fixtures in `tests/fixtures/` with known technologies and patterns. Verify extraction produces expected skills and patterns.

### Priority 2: Claude-Powered Requirement Parsing

**Why second:** The current keyword-based requirement extraction (`_extract_basic_requirements` in `cli.py`) only catches skills that appear as exact keyword matches. Job postings describe requirements in natural language ("experience with distributed systems at scale") that keyword matching misses entirely.

**What it does:**
- Send job posting text to Claude via `claude --print` CLI
- Get back structured `QuickRequirement` list with skill mappings and priorities
- Cache results by posting text hash

**Files to create/modify:**
- `src/claude_candidate/requirement_parser.py` — Claude-powered parsing
- Modify `server.py` — use Claude parser when `requirements` not provided in request

**Implementation approach:**
```python
import subprocess, json

def parse_requirements_with_claude(posting_text: str) -> list[dict]:
    prompt = f"""Extract job requirements from this posting as JSON...
    {posting_text}
    """
    result = subprocess.run(
        ["claude", "--print", "-p", prompt],
        capture_output=True, text=True, timeout=30
    )
    return json.loads(result.stdout)
```

**Key constraint:** This adds latency (5-15s for Claude call). Use progressive loading — show skill-match scores immediately with keyword extraction, then update with Claude-parsed requirements when ready.

### Priority 3: Public Repo Correlator

**Why third:** Cross-references public GitHub repos with session evidence. When a session mentions files that appear in a public repo, the correlation strengthens the trust proof.

**What it does:**
- Accept GitHub username or org URL
- Fetch public repos via GitHub API (unauthenticated: 60 req/hour)
- For each repo: get commit history, file list
- Correlate: filename matches, temporal overlap (commits near session dates), content references
- Produce `PublicRepoCorrelation` records for the manifest

**Files to create:**
- `src/claude_candidate/correlator.py`
- `tests/test_correlator.py`

**The `PublicRepoCorrelation` schema already exists** in `schemas/session_manifest.py`.

### Priority 4: Proof Package Generator

**Why fourth:** Generates the Tier 2 transparency deliverable — a markdown report that hiring managers can review to verify the evaluation chain.

**What it does:**
- Takes a `SessionManifest` and `FitAssessment`
- Generates a markdown document with: corpus overview, verification instructions, public repo cross-references, redaction transparency, pipeline source link, limitations

**Files to create:**
- `src/claude_candidate/proof_generator.py`
- `tests/test_proof_generator.py`

### Priority 5: Deliverable Generation

**Why last:** These are the "nice" outputs that make the tool portfolio-ready, but the core assessment works without them.

**What it does:**
- Generate tailored resume bullets grounded in session evidence
- Generate cover letter using match evaluation themes
- Generate interview prep notes with evidence-backed talking points
- All deliverables trace claims to `SessionReference` evidence

**Files to create:**
- `src/claude_candidate/generator.py` — Uses Claude via `claude --print`
- `tests/test_generator.py`

---

## Team Structure

### Recommended Agent Assignments

**Agent 1: Session Pipeline Engineer**
- Owns: session_scanner.py, sanitizer.py, extractor.py
- Deliverables: Working `claude-candidate sessions scan` that produces a real CandidateProfile from actual session logs
- Key constraint: No raw session content in output. Privacy is structural.
- Test with real sessions from `~/.claude/projects/`

**Agent 2: Intelligence Engineer**
- Owns: requirement_parser.py, correlator.py
- Deliverables: Claude-powered requirement parsing, GitHub repo correlation
- Key constraint: Handle Claude CLI invocation failures gracefully. Cache aggressively.

**Agent 3: Output Engineer**
- Owns: proof_generator.py, generator.py
- Deliverables: Proof package markdown, tailored resume/cover letter generation
- Key constraint: Every claim traces to a SessionReference. Evidence or silence.

**Agent 4: Quality & Integration**
- Owns: Cross-component integration tests, extension improvements
- Deliverables: End-to-end test (scan → extract → merge → assess → generate), extension polish
- Key constraint: All existing 195 tests must continue passing

### Coordination Rules

1. **Schema changes require team-wide review.** The schemas are contracts.
2. **Each agent writes tests alongside code.** The 195-test bar must be maintained or exceeded.
3. **Privacy is structural.** No candidate data leaves localhost.
4. **Evidence or silence.** Any skill claim must trace to evidence.
5. **Commit early and often.** The current repo has 12 clean commits — maintain that discipline.

---

## Execution Order

```
Phase 1 (Critical Path):
  Agent 1: Session scanner + sanitizer + extractor
  Agent 2: Claude-powered requirement parser

Phase 2 (After Phase 1):
  Agent 1: Integration with server (auto-scan on startup)
  Agent 2: Public repo correlator
  Agent 3: Proof package generator

Phase 3 (Polish):
  Agent 3: Deliverable generation (resume, cover letter, interview prep)
  Agent 4: Integration tests, extension improvements, documentation
```

### Dependencies
- Requirement parser is independent (can start immediately)
- Session extractor is independent (can start immediately)
- Correlator depends on session extractor (needs SessionFileRecords)
- Proof generator depends on correlator (optional) and manifest
- Deliverable generator depends on session extractor (needs real CandidateProfile)

---

## Development Environment

```bash
cd ~/git/candidate-eval
source .venv/bin/activate
python -m pytest tests/ -v          # Run tests (should show 195 passing)
claude-candidate --version           # Should show 0.2.0
claude-candidate server start        # Start backend on localhost:7429
ruff check src/ tests/               # Lint (should be clean)
```

**Python:** 3.13 via Homebrew (project requires >=3.11)
**Key deps:** pydantic>=2.0, fastapi, pymupdf, httpx, aiosqlite, rich, click
**Entry point:** `src/claude_candidate/cli.py`

---

## Quality Standards

### Non-Negotiable
- All existing 195 tests pass after every change
- `ruff check` clean
- Every Pydantic model has round-trip serialization tests
- No candidate data leaves localhost
- No absolute file paths in persisted output
- Every skill claim traces to evidence

### Commit Style
- Brief imperative sentences ("Add session scanner", "Fix requirement parser caching")
- No Co-Authored-By trailers
- Commit after each logical chunk (not mega-commits)

---

## Three Things to Protect

1. **The evidence chain.** Every claim → SessionReference → manifest hash. If a new module generates claims without evidence links, it's a bug.

2. **The honesty calibration.** The scoring engine was tuned to avoid inflation. A strong candidate against a strong-fit posting gets a B+, not an A+. Don't adjust thresholds to look better.

3. **The privacy model.** No candidate data leaves localhost. No absolute paths in outputs. No raw session content in deliverables. These are structural invariants.
