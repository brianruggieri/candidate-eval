# claude-candidate — Architecture Reference (v0.5.0)

claude-candidate is a privacy-first pipeline that transforms a developer's Claude Code session logs and resume into verifiable, job-specific fit assessments. It extracts demonstrated skills, problem-solving patterns, and technical depth from real development work, matches them against job postings, and generates tailored deliverables — all processed locally, with no raw session data persisted or transmitted.

---

## Pipeline Stages

```
Session JSONL files ──→ sanitizer ──→ extractor ──→ CandidateProfile ──┐
Resume (PDF/DOCX)   ──→ resume_parser ─────────────→ ResumeProfile ────┤
                                                                         ↓
                                                        merger → MergedEvidenceProfile
                                                                         ↓
Job Posting ──→ requirement_parser ──→ QuickRequirement[] ──→ quick_match ──→ FitAssessment
                                                                         ↓
                                            generator ──→ resume bullets / cover letter
                                            site_renderer ──→ HTML assessment page
                                            proof_generator ──→ proof package markdown
```

**Sanitizer** (`sanitizer.py`) — Privacy trust boundary. Strips API keys, auth tokens, emails, absolute file paths, and other secrets from raw JSONL session content before any further processing. Every redaction is logged with type and reason.

**Extractor** (`extractor.py`, `extractors/`) — Reads sanitized session content and produces a `CandidateProfile`. Uses four extraction layers — file extension mapping, taxonomy pattern matching, import parsing, and package manager parsing — plus behavioral and communication signal extractors. Every skill claim is backed by a `SessionReference` with an evidence snippet. The `evidence_compactor.py` module reduces large profiles from ~49 MB to ~500 KB by selecting the top 3–5 evidence entries per skill.

**Resume Parser** (`resume_parser.py`) — Parses PDF and DOCX resumes into a structured `ResumeProfile`. The `resume onboard` CLI command produces a human-curated `CuratedResume` with manually verified skill depths and durations, which supersedes raw resume data in the merge step.

**Merger** (`merger.py`) — Combines `CandidateProfile` (or `CuratedResume`) and `ResumeProfile` into a `MergedEvidenceProfile` with provenance tracking. Skills are classified as `corroborated` (both sources), `sessions_only` (observed, not claimed), or `resume_only` (claimed, not observed). Corroborated skills are weighted most heavily downstream.

**Requirement Parser** (`requirement_parser.py`) — Parses job posting text into a `QuickRequirement[]` array using the Claude CLI. Falls back to a keyword parser if the CLI is unavailable. Each requirement includes priority (`must_have`, `strong_preference`, `nice_to_have`, `implied`) and an `is_eligibility` flag for non-skill logistical requirements.

**Quick Match** (`quick_match.py`) — Scores the `MergedEvidenceProfile` against parsed requirements across three dimensions with adaptive weighting based on available company data:
- Skill gap analysis (50–85%)
- Company/mission alignment (10–25%)
- Culture fit signals (5–25%)

Produces a `FitAssessment` with a letter grade, dimension scores, per-skill match details, and eligibility gate results.

**Generator** (`generator.py`) — Calls `claude --print` CLI to produce resume bullets, cover letters, interview prep notes, and narrative verdicts from the `FitAssessment` and `MergedEvidenceProfile`. All output is run through `pii_gate.py` before leaving the tool.

---

## Module Map

### Core pipeline

| Module | Purpose |
|--------|---------|
| `sanitizer.py` | PII and secret stripping — first privacy boundary |
| `extractor.py` | Session signal extraction → `CandidateProfile` |
| `extractors/code_signals.py` | Language, framework, tool detection from code content |
| `extractors/behavior_signals.py` | Problem-solving patterns and AI-native skill detection |
| `extractors/comm_signals.py` | Communication and working-style signals |
| `extractors/signal_merger.py` | Aggregates all extractor results into a `CandidateProfile` |
| `evidence_compactor.py` | Reduces profile evidence from thousands of entries to 3–5 per skill |
| `resume_parser.py` | PDF/DOCX → `ResumeProfile` |
| `merger.py` | `CandidateProfile` + `ResumeProfile` → `MergedEvidenceProfile` |
| `requirement_parser.py` | Job posting text → `QuickRequirement[]` via Claude CLI |
| `quick_match.py` | Scoring engine — 3-dimension fit assessment |
| `generator.py` | Deliverable generation via Claude CLI |

### Supporting modules

| Module | Purpose |
|--------|---------|
| `skill_taxonomy.py` | Canonical skill resolution — alias lookup, fuzzy matching via rapidfuzz |
| `pii_gate.py` | Second PII layer — scrubs NER-detectable PII from generated output via DataFog |
| `storage.py` | SQLite persistence for assessments, shortlist, and profiles (aiosqlite) |
| `server.py` | FastAPI backend on `localhost:7429` — serves the Chrome extension |
| `cli.py` | Click CLI entrypoint (`sessions scan`, `assess`, `resume onboard`, etc.) |
| `claude_cli.py` | Thin wrapper around `claude --print` subprocess calls |
| `company_enrichment.py` | Heuristic web scraping of company public pages — 7-day cache |
| `company_research.py` | Claude CLI-powered company research for mission/values/culture |
| `session_scanner.py` | Discovers JSONL session log files from `~/.claude/projects/` |
| `whitelist.py` | Persists project whitelist — controls which sessions are eligible |
| `manifest.py` | SHA-256 hashing and manifest creation for the trust/verification layer |
| `correlator.py` | GitHub public repo cross-reference detection |
| `extraction_cache.py` | Incremental extraction cache — skips unchanged session files |
| `message_format.py` | Normalizes raw JSONL event types into a consistent message shape |
| `ai_scoring.py` | Scores session messages across five AI engineering depth dimensions |
| `fit_exporter.py` | Exports `FitAssessment` as Hugo-compatible markdown |
| `site_renderer.py` | Renders `FitAssessment` as HTML using Jinja2 templates |
| `proof_generator.py` | Generates proof package markdown with evidence-linked skill claims |
| `cli_prompts.py` | Interactive CLI prompts shared across commands |

### Enrichment subpackage (`enrichment/`)

| Module | Purpose |
|--------|---------|
| `embedding_matcher.py` | Semantic skill matching via sentence-transformers (all-MiniLM-L6-v2) |
| `evidence_selector.py` | Embedding-based evidence snippet relevance scoring |
| `learning_velocity.py` | Agentic tool-use sophistication classification via embeddings |

---

## Schema Map

All Pydantic v2 models live in `src/claude_candidate/schemas/`.

| Schema | Purpose |
|--------|---------|
| `candidate_profile.py` | `CandidateProfile` — session-derived skills, patterns, projects with evidence |
| `resume_profile.py` | `ResumeProfile` — parsed resume data (roles, education, claimed skills) |
| `curated_resume.py` | `CuratedResume` — human-curated skills with verified depths and durations |
| `merged_profile.py` | `MergedEvidenceProfile` — combined evidence with provenance tags |
| `job_requirements.py` | `QuickRequirement[]` — parsed job posting requirements with priority |
| `fit_assessment.py` | `FitAssessment` — scored output with grade, dimension scores, skill details |
| `company_profile.py` | `CompanyProfile` — enriched company data (mission, values, tech stack) |
| `session_manifest.py` | `SessionManifest` — SHA-256 hashes, corpus statistics, repo correlations |
| `match_evaluation.py` | `MatchEvaluation` — intermediate evaluation representation |

---

## Browser Extension Architecture

The Chrome extension (`extension/`, Manifest V3) is the daily-driver interface for assessing job postings while browsing.

**How it works:**

1. `popup.js` handles the extension UI and user interaction.
2. On assess, `popup.js` injects `content.js` into the active tab via `chrome.scripting.executeScript`.
3. `content.js` expands truncated content sections (e.g. LinkedIn "…more" buttons), grabs visible page text up to 15,000 characters, and returns it with the page URL and title.
4. `popup.js` sends the extracted text to the local FastAPI server at `localhost:7429/assess`.
5. The server parses requirements, scores against the merged profile, and returns a `FitAssessment`.
6. The popup renders the fit grade, dimension scores, and skill match details.
7. `background.js` handles tab management and event routing.

**Key design point:** `content.js` is a generic text grabber — it grabs `document.body.innerText` with no site-specific CSS selectors beyond a small list of LinkedIn "show more" button patterns. There are no per-board TypeScript extractors. The extension targets LinkedIn via `host_permissions` and uses a generic heuristic fallback for other pages.

No candidate data leaves localhost. The extension sends only job posting text to `localhost:7429`.

---

## Data Flow

```
1. User runs `claude-candidate sessions scan`
      └─ session_scanner discovers JSONL files in ~/.claude/projects/
      └─ whitelist filters to approved projects
      └─ extraction_cache skips unchanged files
      └─ sanitizer strips secrets and PII
      └─ extractor builds CandidateProfile (session evidence per skill)
      └─ evidence_compactor trims to top 3–5 snippets per skill
      └─ profile saved to ~/.claude-candidate/candidate_profile.json

2. User runs `claude-candidate resume onboard path/to/resume.pdf`
      └─ resume_parser produces ResumeProfile
      └─ CLI prompts user to verify/adjust skill depths
      └─ CuratedResume saved to ~/.claude-candidate/curated_resume.json

3. User runs `claude-candidate assess` (or uses Chrome extension)
      └─ merger combines CandidateProfile + CuratedResume → MergedEvidenceProfile
      └─ company_enrichment + company_research populate CompanyProfile
      └─ requirement_parser extracts QuickRequirement[] from job posting
      └─ quick_match scores profile against requirements → FitAssessment
      └─ FitAssessment saved to assessments.db via storage.py

4. User runs `claude-candidate export-fit` or generation commands
      └─ generator calls claude --print → resume bullets / cover letter / interview prep
      └─ pii_gate scrubs all deliverable output
      └─ site_renderer optionally produces HTML assessment page
      └─ proof_generator produces evidence-linked proof package markdown
```

---

## Key Design Decisions

**Privacy is structural.** Raw session content never persists outside the user's machine. The sanitizer runs before extraction; the pii_gate runs before any deliverable leaves the tool. The architecture makes exposure impossible, not merely prohibited.

**No raw data transmission.** The Chrome extension sends only job posting text to localhost. Generation commands (`generator.py`) include assessment summaries in Claude prompts, not raw session logs or resume files.

**Dual evidence model.** Skills are classified by provenance at merge time: `corroborated` (sessions + resume), `sessions_only` (observed, not claimed), `resume_only` (claimed, not observed). The quick match engine weights corroborated skills most heavily. Resume-only skills are not penalized in confidence — depth accuracy handles that, not confidence scores.

**Claude CLI, not API.** All Claude-powered steps (`requirement_parser.py`, `generator.py`, `company_research.py`, `evidence_compactor.py`) call `claude --print` via subprocess. This uses the user's existing Claude Code subscription with no separate API key management or billing.

**Incremental extraction.** `extraction_cache.py` tracks SHA-256 hashes of session files so unchanged sessions are skipped on re-runs. Only new or modified sessions are re-extracted.

**Evidence compaction.** After extraction, profiles can reach ~49 MB with thousands of evidence snippets. `evidence_compactor.py` reduces this to ~500 KB by selecting the 3–5 best snippets per skill using either Claude-powered selection or a local composite heuristic (evidence type, recency, confidence, diversity).

**Adaptive scoring weights.** `quick_match.py` adjusts dimension weights based on available company data richness. With a full `CompanyProfile`, mission and culture each carry 25%. With minimal company data, skill scoring expands to 85% of the total weight.

**Eligibility gates.** Non-skill logistical requirements (work authorization, visa sponsorship, location, security clearance) are flagged as `is_eligibility` in `QuickRequirement` and handled separately in `FitAssessment` — they can fail a candidacy regardless of skill score.

---

## What Is Not Implemented

**Agent Teams orchestration.** `PROJECT.md` described a Claude Code Agent Teams pipeline with per-stage agents coordinated via inbox/delegate patterns. This was never built. The `teams/candidate-eval/` directory contains only empty placeholder subdirectories. All pipeline stages run as direct Python function calls, not as coordinated agents.

**Site-specific TypeScript extractors.** `PROJECT.md` described per-board extractors (`linkedin.ts`, `greenhouse.ts`, `lever.ts`, `indeed.ts`). These were never built. The extension uses a single generic `content.js` with a small set of LinkedIn-specific "show more" button selectors.

**Stage 0 selector.** `PROJECT.md` described a manual consent gate where the user explicitly flags eligible sessions. In practice, session eligibility is managed via `whitelist.py` (project-level allow/deny) and the `sessions scan` CLI command. There is no separate consent-stage module.

**Signed manifests with timestamp attestation.** The trust model includes SHA-256 hashing and manifest generation (`manifest.py`), but cryptographic signing and timestamp attestation were not implemented.

**Portfolio narrative generation / claude-narrator integration.** Mentioned in the roadmap but not built. `generator.py` generates resume bullets, cover letters, and interview prep — not portfolio narratives.

---

## Local Data (Not in Repo)

| Path | Purpose |
|------|---------|
| `~/.claude-candidate/assessments.db` | SQLite — cached postings, assessments, shortlist |
| `~/.claude-candidate/candidate_profile.json` | Session-derived `CandidateProfile` |
| `~/.claude-candidate/curated_resume.json` | Human-curated `CuratedResume` |
| `~/.claude-candidate/whitelist.json` | Project whitelist for session scanning |
| `~/.claude-candidate/extraction_cache.json` | Per-file hashes for incremental extraction |

---

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.11+ (3.13 locally) |
| Schema validation | Pydantic v2 |
| CLI | Click |
| Local server | FastAPI + uvicorn |
| Persistence | aiosqlite (SQLite) |
| Skill matching | rapidfuzz (fuzzy), sentence-transformers (semantic) |
| PII scrubbing | DataFog + supplemental regex |
| Hashing | hashlib SHA-256 (stdlib) |
| Session parsing | orjson, ahocorasick |
| Resume parsing | pdfplumber, python-docx |
| Template rendering | Jinja2 |
| Testing | pytest, pytest-asyncio, hypothesis |
| Build | hatchling (pyproject.toml) |
| Extension | Chrome Manifest V3 (plain JS) |
