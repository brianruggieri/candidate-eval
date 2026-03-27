# claude-candidate — Architecture Reference (v0.8.2)

claude-candidate is a privacy-first pipeline that transforms a developer's Claude Code session logs, resume, and local git repositories into verifiable, job-specific fit assessments. It extracts demonstrated skills, problem-solving patterns, and technical depth from real development work, matches them against job postings, and generates tailored deliverables — all processed locally, with no raw session data persisted or transmitted.

---

## Pipeline Stages

```
Session JSONL files ──→ sanitizer ──→ extractor ──→ CandidateProfile ──┐
Resume (PDF/DOCX)   ──→ resume_parser ──→ CuratedResume ───────────────┤
Git repositories    ──→ repo_scanner ──→ RepoProfile ──────────────────┤
                                                                        ↓
                                                        merger → MergedEvidenceProfile
                                                                        ↓
Job Posting ──→ requirement_parser ──→ QuickRequirement[] ──→ scoring/ ──→ FitAssessment
                                                                        ↓
                                            generator ──→ resume bullets / cover letter
                                            site_renderer ──→ HTML assessment page
```

**Sanitizer** (`sanitizer.py`) — Privacy trust boundary. Strips API keys, auth tokens, emails, absolute file paths, and other secrets from raw JSONL session content before any further processing. Every redaction is logged with type and reason.

**Extractor** (`extractor.py`, `extractors/`) — Reads sanitized session content and produces a `CandidateProfile`. Three specialized extractors run in parallel: `CodeSignalExtractor` (languages, frameworks, tools from file extensions, imports, package manifests), `BehaviorSignalExtractor` (12 problem-solving pattern types, agent orchestration, git workflow, quality practice signals from structured `tool_use` metadata), and `CommSignalExtractor` (communication and working-style signals from human message content). The `SignalMerger` aggregates their results. Every skill claim is backed by a `SessionReference` with an evidence snippet. `evidence_compactor.py` reduces large profiles from ~49 MB to ~500 KB by selecting the top 3–5 evidence entries per skill.

**Resume Parser** (`resume_parser.py`) — Parses PDF and DOCX resumes into a structured `ResumeProfile`. The `resume onboard` CLI command produces a human-curated `CuratedResume` with manually verified skill depths and durations, which supersedes raw resume data in the merge step.

**Repo Scanner** (`repo_scanner.py`) — Scans a local directory tree to extract `RepoProfile` evidence: language usage (file extension mapping across 20+ languages), test coverage, CI configuration, dependency graphs, and AI-tooling maturity signals. Confirms or challenges resume skill claims without requiring GitHub API access.

**Merger** (`merger.py`) — Combines `CandidateProfile` (or `CuratedResume`) and `RepoProfile` into a `MergedEvidenceProfile` with provenance tracking. Skills are classified as `corroborated` (multiple sources), `sessions_only` (observed, not claimed), or `resume_only` (claimed, not observed). Corroborated skills are weighted most heavily downstream.

**Requirement Parser** (`requirement_parser.py`) — Parses job posting text into a `QuickRequirement[]` array using the Claude CLI. Falls back to a keyword parser if the CLI is unavailable. Each requirement includes priority (`must_have`, `strong_preference`, `nice_to_have`, `implied`) and an `is_eligibility` flag for non-skill logistical requirements.

**Scoring** (`scoring/`) — Scores the `MergedEvidenceProfile` against parsed requirements across five dimensions with adaptive weighting based on available company data. Produces a `FitAssessment` with a letter grade, dimension scores, per-skill match details, and eligibility gate results.

**Generator** (`generator.py`) — Calls `claude --print` CLI to produce resume bullets, cover letters, and interview prep notes from the `FitAssessment` and `MergedEvidenceProfile`. All output is run through `pii_gate.py` before leaving the tool.

---

## Module Map

### Core pipeline

| Module | Purpose |
|--------|---------|
| `sanitizer.py` | PII and secret stripping — first privacy boundary |
| `extractor.py` | Orchestrates session signal extraction → `CandidateProfile` |
| `extractors/code_signals.py` | Language, framework, tool detection from code content |
| `extractors/behavior_signals.py` | Problem-solving patterns and AI-native skill detection from tool_use metadata |
| `extractors/comm_signals.py` | Communication and working-style signals from human messages |
| `extractors/signal_merger.py` | Aggregates all extractor results into a `CandidateProfile` |
| `evidence_compactor.py` | Reduces profile evidence from thousands of entries to 3–5 per skill |
| `resume_parser.py` | PDF/DOCX → `ResumeProfile` |
| `repo_scanner.py` | Local git repo filesystem scan → `RepoProfile` |
| `merger.py` | `CandidateProfile` + `CuratedResume` + `RepoProfile` → `MergedEvidenceProfile` |
| `requirement_parser.py` | Job posting text → `QuickRequirement[]` via Claude CLI |
| `generator.py` | Deliverable generation via Claude CLI |

### Scoring subpackage (`scoring/`)

| Module | Purpose |
|--------|---------|
| `scoring/__init__.py` | Public API — re-exports all symbols from submodules |
| `scoring/constants.py` | All scoring thresholds, weights, and lookup tables |
| `scoring/matching.py` | Skill resolution (exact, fuzzy, pattern, virtual), confidence computation, adoption velocity |
| `scoring/dimensions.py` | Dimension scoring (skills, experience, education, mission, culture fit), eligibility inference |
| `scoring/engine.py` | `QuickMatchEngine` — orchestrates matching + dimension scoring → `FitAssessment` |

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
| `company_research.py` | Claude CLI-powered company research for mission/values/culture data |
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
| `repo_profile.py` | `RepoProfile` — repo-scanned evidence (languages, test coverage, CI, AI tooling) |
| `merged_profile.py` | `MergedEvidenceProfile` — combined evidence with provenance tags |
| `job_requirements.py` | `QuickRequirement[]` — parsed job posting requirements with priority |
| `fit_assessment.py` | `FitAssessment` — scored output with grade, dimension scores, skill details |
| `company_profile.py` | `CompanyProfile` — enriched company data (mission, values, tech stack) |
| `session_manifest.py` | `SessionManifest` — SHA-256 hashes and corpus statistics for chain-of-custody |
| `match_evaluation.py` | `MatchEvaluation` — intermediate evaluation representation |

---

## Browser Extension Architecture

The Chrome extension (`extension/`, Manifest V3) is the daily-driver interface for assessing job postings while browsing.

**Components:**

| File | Purpose |
|------|---------|
| `popup.html/js/css` | Assessment display with expandable skill evidence drill-down per skill |
| `dashboard.html/js` | Tab-based dashboard (Assessments \| Shortlist) with per-posting status tracking |
| `background.js` | Message routing, API calls, batch assessment orchestration |
| `content.js` | Job posting text extraction from active tab |
| `utils.js` | URL normalization, per-URL keyed storage, stale profile detection |

**Assessment flow:**

1. User clicks the extension popup on a job posting page.
2. `popup.js` injects `content.js` into the active tab via `chrome.scripting.executeScript`.
3. `content.js` expands truncated content sections (LinkedIn "…more" buttons), grabs visible page text up to 15,000 characters, and returns it with the URL and title.
4. `popup.js` sends extracted text to `localhost:7429/assess`.
5. The server parses requirements, scores against the merged profile, and returns a `FitAssessment`.
6. The popup renders the fit grade, dimension scores, and per-skill match details with expandable evidence chains.
7. The shortlist tab in `dashboard.js` deduplicates saved postings by URL and tracks application status.

**Stale profile detection:** `utils.js` computes a hash of the current profile on each assess and compares it to the hash stored at last-save time. If the profile has changed since the assessment was cached, a yellow banner prompts the user to re-assess.

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

3. User runs `claude-candidate repo scan ~/git/`
      └─ repo_scanner walks each repo directory
      └─ extracts language usage, CI, test coverage, AI tooling signals
      └─ RepoProfile saved to ~/.claude-candidate/repo_profile.json

4. User runs `claude-candidate assess` (or uses Chrome extension)
      └─ merger combines CandidateProfile + CuratedResume + RepoProfile → MergedEvidenceProfile
      └─ company_enrichment + company_research populate CompanyProfile
      └─ requirement_parser extracts QuickRequirement[] from job posting
      └─ scoring/engine.py scores profile against requirements → FitAssessment
      └─ FitAssessment saved to assessments.db via storage.py
      └─ On reopen in extension: stale detection compares profile hash → yellow banner if changed
```

---

## Scoring Architecture

The `scoring/` subpackage scores across five dimensions. Weights adapt based on the richness of available company data.

| Dimension | Weight range | Source |
|-----------|-------------|--------|
| Skill match | 50–85% | `MergedEvidenceProfile` vs `QuickRequirement[]` |
| Experience match | fixed | Years + seniority from `CuratedResume` |
| Education / tech match | fixed | Degree + tech overlap from profile |
| Mission alignment | 0–25% | `CompanyProfile` domain + mission text overlap |
| Culture fit | 0–25% | Session behavioral signals vs company culture signals |

**Skill matching strategy** (`scoring/matching.py`): each requirement is resolved via a four-layer cascade — exact canonical name match, fuzzy match via rapidfuzz, pattern-based inference (e.g. TDD patterns → "testing"), virtual skill inference (derived from combinations of other skills). Confidence is computed from evidence depth, source provenance, and recency.

**Adoption velocity** (`scoring/matching.py`): measures how fast and broadly the candidate adopts new tools — computed from breadth (number of distinct tools used), novelty (recency of first use), ramp speed, and meta-tool usage.

**Domain gap penalty** (`scoring/dimensions.py`): if the job domain is substantially outside the candidate's demonstrated domain set, the overall score is penalized.

**Soft skill discount** (`scoring/constants.py`): soft skills (communication, leadership, etc.) contribute at a discounted rate to prevent over-inflation of skill scores.

**Eligibility gates**: non-skill logistical requirements (work authorization, visa sponsorship, location, security clearance) are flagged `is_eligibility` in `QuickRequirement` and evaluated separately. A failed eligibility gate fails the candidacy regardless of skill score.

---

## Key Design Decisions

**Privacy is structural.** Raw session content never persists outside the user's machine. The sanitizer runs before extraction; `pii_gate.py` runs before any deliverable leaves the tool. The architecture makes exposure impossible, not merely prohibited.

**Triple evidence model.** Skills are classified by provenance at merge time: `corroborated` (multiple sources), `sessions_only` (observed, not claimed), `resume_only` (claimed, not observed). The scoring engine weights corroborated skills most heavily. Resume-only skills are not penalized in confidence — depth accuracy handles that, not confidence scores.

**Repo-as-receipt.** `repo_scanner.py` treats local git repositories as ground truth for confirming or challenging resume skill claims. Language files, CI configs, test presence, and dependency manifests provide objective corroboration independent of session behavior.

**Claude CLI, not API.** All Claude-powered steps (`requirement_parser.py`, `generator.py`, `company_research.py`, `evidence_compactor.py`) call `claude --print` via subprocess. This uses the user's existing Claude Code subscription with no separate API key or billing.

**Adaptive scoring weights.** `scoring/engine.py` adjusts dimension weights based on available company data richness. With a full `CompanyProfile`, mission and culture each carry up to 25%. With no company data, skill scoring expands to 85% of total weight.

**Profile hash staleness detection.** The extension's `utils.js` compares a hash of the current profile against the hash stored at assessment time. If the profile changed (new session scan, resume update, repo scan), a yellow banner prompts re-assessment rather than silently serving stale results.

**Eligibility gates.** Non-skill logistical requirements are separated from skill requirements in both parsing and scoring. They can veto an otherwise strong fit assessment.

**Incremental extraction.** `extraction_cache.py` tracks SHA-256 hashes of session files so unchanged sessions are skipped on re-runs. Only new or modified sessions are re-extracted.

---

## Local Data (Not in Repo)

| Path | Purpose |
|------|---------|
| `~/.claude-candidate/assessments.db` | SQLite — cached postings, assessments, shortlist |
| `~/.claude-candidate/candidate_profile.json` | Session-derived `CandidateProfile` |
| `~/.claude-candidate/curated_resume.json` | Human-curated `CuratedResume` |
| `~/.claude-candidate/repo_profile.json` | Repo-scanned `RepoProfile` |
| `~/.claude-candidate/whitelist.json` | Project whitelist for session scanning |
| `~/.claude-candidate/extraction_cache.json` | Per-file hashes for incremental extraction |

---

## Tech Stack

| Component | Choice |
|-----------|--------|
| Language | Python 3.13 |
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
