# HANDOFF: claude-candidate Implementation

## To the Team Lead

You are the orchestrating agent for the full implementation of `claude-candidate` — a privacy-first pipeline and browser extension that transforms Claude Code session logs and resume credentials into honest, evidence-backed job fit assessments.

**Read this document in full before delegating any work.** It contains everything you need: project context, what's already built, what remains, team structure, execution plan, dependency graph, quality standards, and a blog post narrative brief. The PROJECT.md, four plan files, and the existing PoC codebase in `src/` are your reference materials. This handoff prompt is your operating manual.

---

## What This Project Is

claude-candidate answers one question: "How well do I actually fit this job, based on what I've demonstrably done — not what I claim on a resume?"

It works by combining two evidence sources:
- **Resume**: The candidate's actual PDF/DOCX resume, parsed into structured data
- **Claude Code session logs**: JSONL files from Claude Code sessions, analyzed for demonstrated skills, problem-solving patterns, and working style

These sources are merged into a `MergedEvidenceProfile` that classifies every skill by provenance (corroborated by both sources, resume-only, sessions-only, or conflicting). The merged profile is then scored against job postings across three equally-weighted dimensions: skill gap analysis, company/mission alignment, and culture fit.

The daily-driver interface is a Chrome browser extension that extracts job posting text from LinkedIn, Greenhouse, Lever, Indeed, and other job boards, sends it to a local backend server, and displays a fit assessment card — all without any candidate data leaving localhost.

The full pipeline mode generates tailored resumes, cover letters, portfolio narratives, and a cryptographic proof package that verifies the evaluation chain from raw sessions to final deliverables.

**The meta property**: This project demonstrates the skills it evaluates. Session logs from building claude-candidate become input to claude-candidate evaluating the builder for AI engineering roles. The tool's quality is its own proof of concept. Preserve this recursive quality — it's a feature, not a curiosity.

---

## What's Already Built (v0.1 PoC)

The following is implemented, tested, and passing (91 tests, `pip install -e .` works):

### Schemas (8 files, all Pydantic v2)
- `CandidateProfile` — central IR with `SessionReference`, `SkillEntry`, `ProblemSolvingPattern`, `ProjectSummary`
- `JobRequirements` + `QuickRequirement` — full and lightweight job posting representations
- `MatchEvaluation` — full pipeline match output
- `SessionManifest` — cryptographic chain of custody with `SessionFileRecord`, `CorpusStatistics`, `RedactionSummary`
- `ResumeProfile` — structured resume with `ResumeSkill`, `ResumeRole`
- `MergedEvidenceProfile` — dual-source evidence with `EvidenceSource` provenance tracking
- `CompanyProfile` — public company information for enrichment
- `FitAssessment` — three-dimension assessment card with `DimensionScore`, `SkillMatchDetail`

### Core Modules (4 files)
- `manifest.py` — SHA-256 hashing (file, string, stable JSON), session scanning, manifest creation/verification, tamper detection
- `merger.py` — three merge modes (both profiles, candidate-only, resume-only), evidence source classification, confidence scoring, discovery skill detection
- `quick_match.py` — `QuickMatchEngine` with three-dimension scoring, pattern-type resolution (behavioral patterns matched against requirements), fuzzy skill matching, evidence summaries, action item generation
- `cli.py` — `assess`, `manifest create/verify`, `profile merge` commands with rich terminal output

### Test Suite (5 files, 91 tests)
- Schema round-trips, validation edge cases, depth ranking
- Manifest hashing (known vectors, key order invariance, tamper detection)
- Merger (evidence classification, discovery detection, provenance hashes)
- Quick match (scoring dimensions, missing skills, priority weighting, pattern matching)
- CLI integration (full end-to-end flow with fixtures)

### Fixtures (4 files)
- `sample_candidate_profile.json` — realistic profile based on the project author's actual public work (247 sessions, 14 skills, 7 patterns, 4 projects)
- `sample_resume_profile.json` — plausible resume with 12 skills, 2 roles, education
- `sample_job_posting.txt` — Senior AI Engineer role at a developer tools company
- `sample_job_posting.requirements.json` — 17 structured requirements extracted from the posting

### What the PoC Validates
The core thesis works. Running the CLI against the sample fixtures produces an honest assessment: 8/8 must-haves met, B on skills, discovers 9 skills the resume doesn't mention, flags 1 resume claim without session evidence. The scoring feels calibrated — not inflated, not pessimistic.

---

## What Remains to Build

### Priority 1: Local Backend Server (Plan 04, Tasks 5-6)
**Why first**: The browser extension needs this to function. The scoring engine exists — this is wiring it to HTTP.
- FastAPI application with all endpoints from Plan 04 (`/api/assess`, `/api/profile/status`, `/api/watchlist`, etc.)
- CORS configuration for extension origins
- Profile auto-discovery from `~/.claude-candidate/`
- SQLite persistence for assessments and watchlist
- Async assessment pipeline with progressive result delivery
- Server start/stop CLI commands (`claude-candidate server start --daemon`)

### Priority 2: Resume Parser (Plan 04, Task 1)
**Why second**: Dual-source evidence is the key differentiator. Without resume parsing, all skills are "sessions-only."
- PDF text extraction via pdfplumber
- DOCX text extraction via python-docx
- Claude Code-powered structured parsing using the prompt template in Plan 04 (Section "Resume Parsing Prompt")
- Skill name normalization to canonical form
- Multi-column and creative layout handling
- Caching to `~/.claude-candidate/resume_profile.json`
- CLI command: `claude-candidate resume ingest /path/to/resume.pdf`

### Priority 3: Company Enrichment Engine (Plan 04, Task 3)
**Why third**: Enables the mission and culture dimensions. Without it, those dimensions default to 0.5 (neutral).
- URL discovery: company website, engineering blog, GitHub org
- Content fetching via httpx (public URLs only)
- Structured extraction via Claude Code
- 7-day cache in `~/.claude-candidate/company_cache/`
- Graceful degradation when enrichment data is sparse
- Rate limiting for GitHub API (unauthenticated: 60/hour)

### Priority 4: Browser Extension (Plan 04, Tasks 7-9)
**Why fourth**: Depends on the backend being stable.
- Chrome Manifest V3 extension
- Content scripts for LinkedIn, Greenhouse, Lever, Indeed + generic fallback
- Extension popup with all 6 states (no backend, no profile, not on job page, assessing, complete, error)
- Fit assessment card rendering in 400px popup
- Sidebar with detailed view and comparison
- Watchlist management
- "Generate Full Application" bridge to full pipeline
- Test harness with saved HTML fixtures (see Plan 04, "Content Script Test Harness")

### Priority 5: Public Repo Correlator (Plan 03, Task 4)
- GitHub API integration for commit history
- Filename, temporal, and content correlation detection
- Correlation scoring and classification
- Integration with manifest module

### Priority 6: Proof Package Generator (Plan 03, Task 5)
- Markdown generation from manifest data
- All sections: what this is, corpus overview, verification, public corroboration, redaction transparency, limitations, pipeline source, manifest reference
- Privacy audit: no raw content, no absolute paths, no secrets

### Priority 7: Full Pipeline Agent Orchestration (Plan 02)
- **RESEARCH FIRST**: Verify Claude Code Agent Teams CLI syntax (see Plan 02, "CRITICAL: Agent Invocation Research Task")
- Three fallback strategies documented if syntax differs from assumptions
- Team CLAUDE.md files already written for all 6 agents
- Pipeline flow with validation gates
- `--resume` flag for interrupted pipeline recovery
- Interactive session selector TUI

### Priority 8: Deliverable Generation (Plan 02, Writer Agent)
- Resume bullets grounded in session evidence
- Tailored cover letter using match evaluation themes
- Portfolio highlights from strongest-fit projects
- Interview prep with evidence-backed talking points
- Proof package integration

---

## Team Structure

### Agent Assignments

**Agent 1: Backend Engineer**
- Owns: FastAPI server, SQLite persistence, API endpoints, server CLI commands
- References: Plan 04 Components 2, 7; existing `quick_match.py` and `merger.py`
- Key constraint: All endpoints must validate I/O against Pydantic schemas. No untyped JSON.
- Deliverables: `server.py`, `storage.py`, server tests

**Agent 2: Data Engineer**
- Owns: Resume parser, company enrichment engine, public repo correlator
- References: Plan 04 Components 3, 5; Plan 03 Module 4; Plan 04 "Resume Parsing Prompt"
- Key constraint: All external data fetching uses httpx async. All results cached. Privacy-safe.
- Deliverables: `resume_parser.py`, `enrichment.py`, `correlator.py`, parser/enrichment tests

**Agent 3: Extension Developer**
- Owns: Chrome extension — content scripts, popup, sidebar, manifest.json
- References: Plan 04 Component 1; Plan 04 "Content Script Test Harness"
- Key constraint: Minimal permissions (activeTab + storage + localhost only). No external network requests from extension.
- Deliverables: `extension/` directory, content script test fixtures, extension tests

**Agent 4: Pipeline Architect**
- Owns: Full pipeline orchestration, agent team CLAUDE.md files, proof package generator, session sanitizer
- References: Plan 02 (full), Plan 03 Tasks 5-6
- Key constraint: Research Claude Code CLI syntax BEFORE implementing invoke_agent(). Use fallbacks if needed.
- Deliverables: `sanitizer.py`, `extractor.py`, `generator.py`, `proof_generator.py`, pipeline tests, team CLAUDE.md sync

**Agent 5: Quality & Integration**
- Owns: Cross-plan integration tests, type checking, documentation, CI setup
- References: PROJECT.md "Cross-Plan Integration Test Specification" (6 test scenarios)
- Key constraint: All 6 cross-plan integration tests must pass before any PR is merged.
- Deliverables: Integration tests, mypy strict pass, ruff clean, README expansion, CONTRIBUTING.md

### Coordination Rules

1. **Schema changes require team-wide review.** The schemas are the contract between all modules. Any change to `schemas/*.py` must be reviewed for downstream impact before merging.

2. **Each agent writes tests alongside code.** No PR without tests. The existing 91 tests set the bar — maintain or exceed that coverage ratio.

3. **Privacy is structural.** If you're unsure whether data should leave localhost, it shouldn't. Ask the team lead.

4. **Evidence or silence.** Any skill claim in any output must trace to a SessionReference or ResumeSkill. If you can't cite it, don't generate it.

5. **Honest gaps over inflated matches.** The tool's credibility depends on honesty. A "no_evidence" match status is more valuable than a fabricated "partial_match."

---

## Execution Plan

### Phase 1: Foundation (Week 1)
- Agent 1: FastAPI server skeleton + health check + profile status endpoint
- Agent 2: Resume parser (PDF + DOCX → ResumeProfile)
- Agent 3: Extension manifest.json + content script extractors (offline, against test fixtures)
- Agent 4: Research Claude Code CLI syntax, document findings
- Agent 5: Set up CI (pytest + mypy + ruff), expand test fixtures

### Phase 2: Core Features (Week 2)
- Agent 1: All API endpoints + SQLite persistence + watchlist CRUD
- Agent 2: Company enrichment engine with caching
- Agent 3: Extension popup (all 6 states) + backend connectivity
- Agent 4: Session sanitizer + signal extractor (single Claude Code pass for v0.2)
- Agent 5: Cross-plan integration tests 1-4

### Phase 3: Integration (Week 3)
- Agent 1: Progressive loading (show partial results while enrichment runs)
- Agent 2: Public repo correlator + proof package generator
- Agent 3: Extension sidebar + comparison view + watchlist UI
- Agent 4: Full pipeline end-to-end (sanitize → extract → match → generate)
- Agent 5: Cross-plan integration tests 5-6 + end-to-end acceptance tests

### Phase 4: Polish & Release (Week 4)
- Full team: Bug fixes, UX polish, documentation
- Agent 3: Chrome Web Store preparation (if publishing)
- Agent 4: "Generate Full Application" flow from extension to pipeline
- Agent 5: README, CONTRIBUTING.md, example evaluations, blog post coordination
- Team lead: Final review, version bump to v0.2.0, tag release

---

## Quality Standards

### Non-Negotiable
- `mypy --strict` passes on all Python code
- `ruff` clean (no warnings)
- Every Pydantic model has round-trip serialization tests
- No candidate data leaves localhost (except as Claude Code API context, same trust model as normal usage)
- No absolute file paths in any persisted output
- Every skill claim in any deliverable traces to evidence

### Target Metrics
- Assessment time: <1s for cached company, <30s for uncached
- Extension popup opens in <200ms
- Backend starts in <3s
- Test suite runs in <10s
- 100% of must-have acceptance criteria from each plan pass

---

## Key Files to Read

**Read these before starting work.** In this order:

1. `PROJECT.md` — Full product vision, architecture, roadmap, cross-plan integration test spec
2. `plans/01-candidate-profile-schema.md` — Schema spec (now implemented, use as reference)
3. `plans/04-browser-extension-quick-match.md` — The daily-driver feature spec (most work lives here)
4. `plans/02-agent-team-orchestration.md` — Agent CLAUDE.md files and pipeline flow
5. `plans/03-session-manifest-hashing.md` — Trust layer spec
6. `src/claude_candidate/` — The existing PoC code (read all 4 modules and all 8 schemas)
7. `tests/` — The existing test suite (understand the testing patterns)

---

## Blog Post Narrative Brief

### For the blog-a-claude Pipeline (or Manual Drafting)

This section captures the full narrative arc of the conversation that produced claude-candidate. It's designed to feed into the blog-a-claude pipeline or serve as a detailed outline for manual blog post creation.

### Post Title Options
- "Building a Tool That Evaluates Me: claude-candidate and the Recursive Portfolio"
- "Session Logs Are the New Resume: How I Built an Honest Job Fit Assessor"
- "From Prompt History to Proof of Work: The claude-candidate Story"

### The Narrative Arc

**Act 1: The Idea Spark**

The conversation opened with a raw, unpolished idea — what if you could feed your Claude Code session logs and resume into a system that honestly evaluates your fit for a specific job posting? Not the usual AI resume optimizer that inflates claims, but something grounded in *what you actually did* versus *what the job actually needs*.

The key insight: session logs are a richer hiring signal than any resume. They capture how someone thinks — architecture decisions, debugging strategies, tool selection rationale, iteration patterns, the ability to recover from mistakes. A resume says "proficient in Python." Session logs show you debugging async race conditions at 2am across a 200-line pipeline you designed from scratch.

The initial question wasn't just "can this be built" — it was "what form should the output take?" Direct hiring-agent handoff (evaluation report) or traditional deliverables (resume, cover letter)? The answer: build the evaluation as an internal intermediate representation, then generate traditional deliverables from it. The IR is reusable across applications. The deliverables fit existing hiring workflows. Best of both worlds.

**Act 2: The Trust Problem**

The conversation took its most important turn when the question of honesty and proof came up. Anyone can claim "AI analyzed my logs and says I'm great." The harder question: how do you prove the evaluation is genuinely derived from real work, without exposing that work?

This led to the three-tier transparency model:
- **Tier 1 (what companies see)**: Tailored resume, cover letter, match summary. Traditional format.
- **Tier 2 (available on request)**: Open-source pipeline code, session manifest with SHA-256 hashes, public repo cross-references, redaction transparency report. The method is inspectable; the evidence is hashable; the corroboration is independent.
- **Tier 3 (always private)**: Raw session logs, full prompt history, client work. Never exposed.

The cryptographic manifest doesn't prove identity (session files aren't identity-bound). It proves integrity (these specific files were the input, this specific pipeline produced the output, any tampering is detectable). The plan is honest about what it proves and what it doesn't — and that honesty is itself the strongest trust signal.

**Act 3: The Architecture Takes Shape**

Four plan documents were written in rapid succession, totaling ~22,000 words:

1. **CandidateProfile Schema** — The central data model where every skill claim links to session evidence. No orphan claims. The `SessionReference` is deliberately verbose because trust depends on traceability.

2. **Agent Team Orchestration** — Six specialized Claude Code agents (sanitizer, extractor, job parser, matcher, writer, manifest) coordinated through a sequential pipeline with validation gates between every stage. Model mixing: Opus for judgment, Sonnet for structure.

3. **Session Manifest & Hashing** — The cryptographic trust layer. SHA-256 hash chain from raw files through sanitization, extraction, and evaluation to final deliverables. Public repo correlation engine for independent verification.

4. **Browser Extension Quick Match** — The daily-driver feature. A Chrome extension that assesses job fit while browsing, with a local backend server, company enrichment, and three-dimension scoring (skills, mission, culture — equally weighted).

**Act 4: The Dual Evidence Innovation**

The most important architectural decision emerged from a simple question: should the assessment be based on session logs, or on the resume, or both?

The answer — both, with provenance tracking — created the project's key differentiator. The `MergedEvidenceProfile` classifies every skill:
- **Corroborated**: Both resume and sessions demonstrate it. Highest confidence.
- **Sessions-only**: Demonstrated in logs but missing from resume. *Discovery* — "your resume should mention this."
- **Resume-only**: Claimed on resume but not demonstrated in sessions. *Unverified* — "prepare to discuss this in interviews."
- **Conflicting**: Resume and sessions disagree on depth. Sessions win (observed behavior over self-report).

This dual-source model doesn't just assess fit — it improves the candidate's resume by revealing undersold skills and flagging unsubstantiated claims. The "discovery skills" feature (sessions show TypeScript expertise across 23 sessions, but the resume doesn't mention TypeScript) is the highest-value insight the tool produces.

**Act 5: From Spec to Working Software**

The conversation shifted from planning to building. A working proof-of-concept was implemented: 3,778 lines of Python, 8 schema files, 4 core modules, a CLI, realistic fixtures, and 91 tests — all passing.

The moment of truth: running the CLI against a sample profile and job posting. The first output showed 65% skill match because requirements mapping to behavioral patterns (like "modular thinking") weren't being matched against the candidate's problem-solving patterns — only against explicit skills. A fix was implemented (pattern-type resolution in the skill matcher), and the score jumped to 78% with 8/8 must-haves met.

The assessment card surfaced real insights:
- 9 skills the resume doesn't mention but sessions demonstrate (including Claude API, CLI design, developer tooling)
- 1 resume claim without session evidence (Docker)
- Action items: "Update resume to include claude-api, cli-design, developer-tooling"

This is the tool working as intended — not telling the candidate they're perfect, but telling them exactly where they're strong, where they're weak, and what to do about it.

**Act 6: The Recursive Property**

The project's deepest quality is self-reference. The session logs from building claude-candidate — the architecture discussions, the schema design, the scoring engine implementation, the honest gap analysis — are themselves valid input to claude-candidate. If the tool evaluates its builder for an AI engineering role and produces a strong match, the tool has validated itself. If it finds gaps, those gaps are real.

This recursive property extends to the blog post. The blog-a-claude pipeline (which ingests session logs and generates blog posts) could process the sessions from building claude-candidate to generate a blog post *about* building claude-candidate. The tool that documents its own construction documents the construction of a tool that evaluates its own builder.

**Act 7: The Handoff**

The final act is meta-operational. The conversation produced not just a product spec and working code, but a complete handoff document for an agent team to continue the build. The handoff itself demonstrates the project's core values: structured thinking, clear contracts between components, honest assessment of what's done and what remains, and evidence-backed claims about quality (91 tests passing, not "the code works").

### Blog Post Tone & Style

- **Technical but personal.** This isn't a product announcement — it's a builder's narrative about creating something from a conversation.
- **Show the thinking, not just the result.** The most interesting parts are the decisions: why dual evidence? Why equal weighting on three dimensions? Why cryptographic manifests?
- **Honest about limitations.** The tool can't prove identity. Session selection is voluntary. The trust model has boundaries. Saying so makes the project more credible, not less.
- **Code snippets welcome.** Show the assessment card terminal output. Show the evidence classification logic. Show the hash chain diagram. These are more compelling than prose claims.
- **End with the recursive frame.** The blog post about building claude-candidate was generated by a pipeline that ingests session logs from building claude-candidate, which evaluates the builder of claude-candidate. The snake eats its tail — and that's the point.

### Key Quotes / Moments to Reference

- The initial idea framing: "session logs are a richer hiring signal than any resume"
- The trust model: "privacy is structural, not policy"
- The dual evidence innovation: "corroborated, resume-only, sessions-only, conflicting"
- The discovery feature: "9 skills your resume doesn't mention but your sessions demonstrate"
- The honest gap: session scoring at 65% initially because patterns weren't being matched — fixed, jumped to 78%
- The meta property: "the tool that demonstrates your AI engineering skills *is itself* an AI engineering project"

### Blog Post Reminders & Action Items

1. **Capture session logs from this implementation work.** The sessions where agents build claude-candidate are high-value input for both the blog post and for claude-candidate's own self-evaluation. Ensure JSONL logging is active during the build.

2. **Run claude-candidate against an AI engineering job posting using the session logs from building it.** This is the "eat your own dogfood" moment. Include the assessment card output in the blog post.

3. **Screenshot the rich terminal card output.** The colored assessment card with skill/mission/culture bars is the hero image for the blog post.

4. **Include the file/test count as proof of work.** "3,778 lines of Python, 91 tests, 4 plan documents totaling 22,000 words" — these numbers ground the narrative.

5. **Link to the public repo.** The open-source pipeline code is itself the proof layer. The blog post should link to it and invite readers to inspect the method.

6. **Consider a "before/after" section.** Show what a traditional resume says about the candidate vs. what claude-candidate's assessment reveals. The delta is the value proposition.

---

## Final Notes to the Team Lead

This project was conceived, specified, and partially built in a single extended conversation. The quality of what exists is high — the schemas are tight, the tests are thorough, the scoring engine produces honest results. Your job is to extend this foundation without breaking its integrity.

Three things to protect:

1. **The evidence chain.** Every claim → SessionReference → manifest hash. If a new module generates claims without evidence links, it's a bug.

2. **The honesty calibration.** The scoring engine was deliberately tuned to avoid inflation. A strong candidate against a strong-fit posting gets a B+, not an A+. Resist the temptation to adjust thresholds to make results "look better."

3. **The privacy model.** No candidate data leaves localhost. No absolute paths in outputs. No raw session content in deliverables. These aren't guidelines — they're structural invariants.

Build well. The sessions from your build become input to the tool you're building.
