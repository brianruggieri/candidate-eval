# claude-candidate

Privacy-first pipeline: Claude Code session logs + resume → evidence-backed job fit assessments.

## Quick Start

```bash
# Always use the venv — no bare python/pytest
.venv/bin/python -m pytest                    # Run tests
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
| `src/claude_candidate/data/taxonomy.json` | Skill taxonomy (33 entries: languages, frameworks, tools, platforms, domains, practices, soft skills) |
| `tests/golden_set/postings/*.json` | 24 real LinkedIn postings for accuracy benchmarking |
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

- **Indentation:** Tabs (defer to editor config)
- **Line length:** 100 (ruff)
- **Commits:** Brief imperative sentences. No Co-Authored-By trailers.
- **Tests:** Real data strongly preferred over mocks. Use fixture files in `tests/fixtures/`.
- **Taxonomy changes:** Always add corresponding tests in `tests/test_skill_taxonomy.py`
- **Matching changes:** Always add tests in `tests/test_quick_match.py`

## Running the benchmark

```bash
# Score all golden set postings against the merged profile
.venv/bin/python tests/golden_set/benchmark_accuracy.py

# Output includes: accuracy stats, stage diagnosis, per-posting scores
# Appends to tests/golden_set/benchmark_history.jsonl
```

## Browser extension

The `extension/` directory contains a Chrome MV3 extension that integrates with the FastAPI server for real-time job posting assessment on LinkedIn.
