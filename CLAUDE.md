# claude-candidate

Privacy-first pipeline: Claude Code session logs + resume → evidence-backed job fit assessments.

## Quick Start

```bash
# Always use the venv — no bare python/pytest
.venv/bin/python -m pytest                    # Run tests (~7s, skips slow)
.venv/bin/python -m pytest --run-slow         # Full suite including integration tests (~5min)
.venv/bin/python -m pytest tests/test_foo.py  # Run one test file
.venv/bin/python -m claude_candidate.cli --help  # CLI entry point
```

## Tech Stack

- **Python 3.11+** (running 3.13 locally), pydantic v2, click, FastAPI
- **Testing:** pytest, pytest-asyncio (asyncio_mode=auto), hypothesis
- **Matching:** rapidfuzz for fuzzy skill resolution
- **Storage:** aiosqlite for assessments.db
- **Build:** hatchling (pyproject.toml)

## Architecture

### Core pipeline
```
Session JSONL files → sanitizer → extractor → CandidateProfile
Resume (PDF/DOCX)  → resume_parser → ResumeProfile
                                       ↓
                              merger → MergedEvidenceProfile
                                       ↓
Job posting → requirement_parser → QuickRequirement[]
                                       ↓
                          quick_match → FitAssessment
```

### Key modules
| Module | Purpose |
|--------|---------|
| `quick_match.py` | Scoring engine — matches profile skills against job requirements |
| `skill_taxonomy.py` | Canonical skill resolution (aliases, fuzzy, relationships) |
| `merger.py` | Combines session + resume evidence into unified profile |
| `extractor.py` | Extracts skills/patterns/projects from session logs |
| `server.py` | FastAPI server for browser extension |
| `cli.py` | Click CLI (`sessions scan`, `assess`, `export-fit`, etc.) |
| `pii_gate.py` | PII scrubbing before any output (DataFog + regex fallback) |

### Schemas (pydantic v2)
| Schema | Purpose |
|--------|---------|
| `candidate_profile.py` | Session-derived skills, patterns, projects |
| `resume_profile.py` | Parsed resume data |
| `merged_profile.py` | Combined evidence with provenance tracking |
| `job_requirements.py` | Parsed job posting requirements |
| `fit_assessment.py` | Scoring output with grades and action items |

### Data files
| File | Purpose |
|------|---------|
| `src/claude_candidate/data/taxonomy.json` | Skill taxonomy (104 entries: languages, frameworks, tools, platforms, domains, practices, soft skills) |
| `tests/golden_set/postings/*.json` | 47 real job postings for accuracy benchmarking (gitignored) |
| `tests/golden_set/expected_grades.json` | Expected grades for benchmark validation |
| `tests/golden_set/benchmark_accuracy.py` | Benchmark script with stage diagnosis |

### Local data (not in repo)
| Path | Purpose |
|------|---------|
| `~/.claude-candidate/assessments.db` | SQLite — cached postings, assessments, profiles |
| `~/.claude-candidate/candidate_profile.json` | Session-derived profile |
| `~/.claude-candidate/curated_resume.json` | Human-curated resume with skill depths + durations |
| `~/.claude-candidate/whitelist.json` | Project whitelist for session scanning |

## Conventions

- **Indentation:** Tabs (`ruff format` enforced via `[tool.ruff.format] indent-style = "tab"`)
- **Line length:** 100 (ruff)
- **Commits:** Brief imperative sentences. No Co-Authored-By trailers.
- **Tests:** Real data strongly preferred over mocks. Use fixture files in `tests/fixtures/`.
- **Taxonomy changes:** Always add corresponding tests in `tests/test_skill_taxonomy.py`
- **Matching changes:** Always add tests in `tests/test_quick_match.py`

## Test tiers

Tests are split into two tiers via `@pytest.mark.slow`:

| Command | Time | When to use |
|---------|------|-------------|
| `.venv/bin/python -m pytest` | ~7s | Every dev loop — after any code change |
| `.venv/bin/python -m pytest --run-slow` | ~5min | Before opening a PR; when touching modules listed below |

**Run `--run-slow` when you change:**
- `requirement_parser.py` — covered by `TestJobParseCommand` (calls real Claude CLI)
- `extractor.py` or `sanitizer.py` — covered by `TestSessionsScanCommand` (full JSONL scan)
- `evidence_compactor.py` — covered by `TestFallback::test_claude_failure_triggers_fallback`
- `server.py` `/api/assess/full` endpoint — covered by `TestAssessFullEndpoint`

**What slow tests cover that fast tests don't:** end-to-end subprocess calls, real Claude CLI invocations, full session extraction pipeline on real JSONL files, and the FastAPI full-assess flow with live async I/O. These are integration correctness checks — they don't need to run on every save, but must pass before merging.

## Running the benchmark

```bash
# Score all golden set postings against the merged profile
.venv/bin/python tests/golden_set/benchmark_accuracy.py

# Output includes: accuracy stats, stage diagnosis, per-posting scores
# Appends to tests/golden_set/benchmark_history.jsonl
```

## Browser extension

The `extension/` directory contains a Chrome MV3 extension that integrates with the FastAPI server for real-time job posting assessment on any job board.
