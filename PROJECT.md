# claude-candidate

## Product Vision

claude-candidate is a privacy-first, open-source pipeline that transforms a developer's Claude Code session logs into verifiable, job-specific hiring deliverables. It extracts demonstrated skills, problem-solving patterns, and technical depth from real development work, matches them against job postings, and generates tailored resumes, cover letters, portfolio narratives, and proof packages — all without ever exposing raw session data.

The core thesis: session logs are a richer hiring signal than any resume. They capture *how someone thinks* — architecture decisions, debugging strategies, tool selection rationale, iteration patterns, communication clarity, and the ability to recover from mistakes. claude-candidate makes that signal legible to hiring processes that still run on resumes and cover letters.

## The Meta Property

This project is self-referential by design. The pipeline that demonstrates AI engineering skill *is itself* an AI engineering project. Session logs from building claude-candidate become input to claude-candidate evaluating the builder for AI engineering roles. The tool's quality is its own proof of concept. This recursive property should be preserved and highlighted — it is a feature, not a curiosity.

## Problem Statement

### For the Candidate
- Resumes are lossy compressions of actual ability. They reward self-promotion over demonstrated skill.
- Tailoring a resume per application is tedious, error-prone, and rarely grounded in specific evidence.
- Developers who build in the open (public repos, session logs, blog posts) have rich evidence of their work but no way to connect it to specific job requirements.
- AI-assisted resume writing exists but operates on self-reported claims, not observed behavior.

### For the Hiring Side (Future)
- Technical interviews are expensive, noisy, and poorly correlated with job performance.
- Resume screening is keyword-matching theater. Strong candidates get filtered; weak candidates with good formatting pass.
- There is no standard format for "here's what I actually did and how I did it" beyond the portfolio, which is unstructured and hard to evaluate at scale.

### The Gap
No tool exists that starts from *observed development behavior*, extracts structured skill evidence, and maps it against specific job requirements with a verifiable chain of custody from raw data to final deliverable.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        claude-candidate                         │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │ Stage 0  │→ │ Stage 1  │→ │ Stage 2  │→ │   Stage 3    │   │
│  │ Select & │  │ Sanitize │  │ Extract  │  │ Ingest Job   │   │
│  │ Consent  │  │ & Audit  │  │ Signal   │  │   Posting    │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────┬───────┘   │
│                                    │               │            │
│                                    ▼               ▼            │
│                              ┌──────────────────────────┐      │
│                              │       Stage 4            │      │
│                              │   Match & Evaluate       │      │
│                              │  (CandidateProfile ×     │      │
│                              │   JobRequirements → IR)  │      │
│                              └────────────┬─────────────┘      │
│                                           │                     │
│                              ┌────────────┼────────────┐       │
│                              ▼            ▼            ▼       │
│                         ┌────────┐  ┌──────────┐ ┌─────────┐  │
│                         │Stage 5 │  │ Stage 5  │ │ Stage 5 │  │
│                         │Resume  │  │  Cover   │ │ Proof   │  │
│                         │Bullets │  │  Letter  │ │ Package │  │
│                         └────────┘  └──────────┘ └─────────┘  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Pipeline Stages

**Stage 0 — Select & Consent**
The user explicitly flags which sessions are eligible for processing. This is a manual gate — no session enters the pipeline without affirmative selection. Sessions from client work, personal matters, or anything the user wants excluded are never touched. Each selected session receives a SHA-256 content hash recorded in a manifest before any processing begins.

**Stage 1 — Sanitize & Audit**
Eligible sessions are cleaned: API keys, secrets, file paths, third-party PII, proprietary code blocks, and sensitive context are stripped. Every redaction is logged with type, reason, and before/after hashes. The output is a cleaned session corpus plus a redaction manifest that proves what was removed and why.

**Stage 2 — Extract Signal**
Cleaned sessions are analyzed to extract structured skill evidence. Technologies used (with frequency and depth indicators), problem-solving patterns, architecture decisions, debugging approaches, communication style, and project complexity markers are all captured into a `CandidateProfile` — the central intermediate representation (IR) of the pipeline. Every claim in the profile links back to specific session evidence.

**Stage 3 — Ingest Job Posting**
The target job posting enters the system via pasted text, a public URL fetch, or structured manual input (company, title, requirements). The posting is parsed into a `JobRequirements` schema: required skills, preferred skills, responsibilities, seniority level, and culture/values signals.

**Stage 4 — Match & Evaluate**
The `CandidateProfile` and `JobRequirements` are compared. The output is a `MatchEvaluation`: a skill coverage matrix, gap analysis, strength highlights with evidence citations, and a qualitative fit assessment with reasoning. This IR powers all downstream deliverables.

**Stage 5 — Generate Deliverables**
The `MatchEvaluation` produces tailored outputs: resume bullet points grounded in session evidence, a cover letter connecting demonstrated work to job requirements, portfolio narratives for the strongest-fit sessions, interview preparation notes, and a proof package (session manifest, redaction summary, public repo cross-references, pipeline source link).

### Dual Evidence Model: Resume + Session Logs

The pipeline operates on two evidence sources simultaneously:

- **Resume**: The user's actual resume (PDF or DOCX), parsed into a structured `ResumeProfile`. This captures claimed skills, career history, education, and professional narrative — the authority of their professional record.
- **Session Logs**: Claude Code JSONL logs, extracted into a `CandidateProfile`. This captures demonstrated skills, problem-solving patterns, and working style — the precision of observed behavior.

These sources are merged into a `MergedEvidenceProfile` that classifies every skill by provenance:
- **Corroborated**: Both resume and sessions demonstrate it. Strongest signal.
- **Resume-only**: Resume claims it, sessions don't show it. Unverified.
- **Sessions-only**: Sessions demonstrate it, resume doesn't mention it. Undersold — a discovery opportunity.
- **Conflicting**: Resume and sessions give different depth signals.

This dual-source model ensures honesty: the tool surfaces where the resume understates demonstrated abilities and where resume claims lack session backing.

### Browser Extension Quick Match

The daily-driver feature is a Chrome browser extension that assesses job fit while the user browses postings. The extension extracts job posting text from the current page (LinkedIn, Greenhouse, Lever, Indeed, and others via generic fallback), sends it to a local backend server on `localhost:7429`, and displays a fit assessment card in the extension popup.

The assessment evaluates three equally-weighted dimensions:
1. **Skill Gap Analysis (33%)**: Demonstrated and credentialed skills vs. job requirements.
2. **Company/Mission Alignment (33%)**: What the company builds vs. what the user has been building.
3. **Culture Fit Signals (33%)**: How the company works vs. how the user works.

The backend also enriches each posting with public company information — about pages, engineering blogs, GitHub organizations, and recent news — to enable the mission and culture dimensions.

No candidate data ever leaves localhost. The extension only sends job posting text to the local backend.

## Execution Engine: Claude Code Agent Teams

The pipeline is orchestrated entirely through Claude Code CLI using Agent Teams. Each stage maps to one or more agents with focused CLAUDE.md context and instructions. Agents coordinate through the inbox/delegate pattern. This has three advantages over raw API calls:

1. **No API key management or billing separation** — runs on the user's existing Claude Code subscription.
2. **Interactive refinement** — the user can intervene, adjust, and steer at any stage.
3. **Dogfooding** — using Agent Teams to build a tool that demonstrates Agent Teams proficiency is the meta property in action.

The team configuration lives in `~/.claude/teams/candidate-eval/` with per-agent CLAUDE.md files defining scope, input/output contracts, and quality criteria.

## Trust & Verification Model

This is the foundational differentiator. The pipeline makes a strong claim — "this evaluation is derived from real development work" — and provides a verification framework without exposing private data.

### Three-Tier Transparency

**Tier 1 — The Deliverable (what hiring companies see)**
Tailored resume, cover letter, portfolio narratives, match summary. Traditional format, fits existing ATS and hiring workflows. Nothing unusual on the surface.

**Tier 2 — The Proof Layer (available on request)**
- Open-source pipeline code (the method is inspectable)
- Session manifest with SHA-256 hashes (proves specific data existed as input)
- Aggregate statistics (session count, date range, technology frequency)
- Public repo cross-references (independent corroboration)
- Selected sanitized session excerpts (hand-approved by the user)
- Redaction transparency report (what categories were removed and why)

**Tier 3 — The Vault (always private)**
- Raw session logs
- Full prompt history
- Client/employer work content
- Personal or sensitive context
- API keys, credentials, internal paths

### Verification Mechanisms

**Cryptographic anchoring**: Every session included in an evaluation is hashed before and after sanitization. The hash manifest is signed and timestamped. The user can reproduce any hash from the original file on demand.

**Public repo correlation**: The pipeline automatically identifies where session work resulted in public commits. Timestamps are cross-referenced: "Session from Feb 14 discusses implementing X; commit abc123 to repo Y on Feb 14 adds X." This is hard-to-fake evidence.

**Open method**: The pipeline source code is public. Anyone can inspect exactly how logs become evaluations. The transformation is deterministic given the same model and prompts.

**Redaction transparency**: Rather than hiding the fact that data was removed, the pipeline documents what *categories* of content were redacted. This communicates honesty.

### Honest Framing Language

The recommended presentation to hiring companies:

> "This application was generated by an open-source pipeline I built that analyzes my development session history and maps demonstrated skills to your job requirements. The pipeline source code is public at [repo link]. The underlying session data remains private, but skill claims are cross-referenced against my public GitHub work where possible. A cryptographic manifest of the source sessions is available on request."

This framing is honest, verifiable, transparent about limitations, and demonstrates the AI engineering thinking the candidate would be hired for.

## Technology Stack

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Language (backend) | Python 3.11+ | Consistent with claude-narrator, daily-claw; strong JSON/file handling |
| Language (extension) | TypeScript | Type safety for DOM manipulation; compiles to JS for extension |
| Orchestration | Claude Code Agent Teams | Dogfooding; no API key management; interactive refinement |
| Local server | FastAPI + uvicorn | Async, lightweight, auto-generated OpenAPI docs |
| Hashing | hashlib (SHA-256) | Standard library; no dependencies |
| Job posting fetch | httpx + readability-lxml | Lightweight; respects robots.txt |
| Resume parsing | pdfplumber + python-docx | Reliable PDF/DOCX text extraction |
| Schema validation | Pydantic v2 | Strict typing; JSON schema generation |
| CLI interface | Click | Consistent with existing tools |
| Persistence | SQLite | Standard library; zero-config; local-only |
| Output formats | Markdown + JSON | Human-readable and machine-parseable |
| Extension framework | Chrome Manifest V3 | Current standard; minimal permissions model |
| Distribution | pip install / pipx | Standard Python distribution |
| License | MIT | Consistent with existing repos |

## Data Flow & Privacy Guarantees

```
Raw JSONL logs (never leave disk except as API context)
    │
    ▼ [User selects eligible sessions — manual gate]
    │
    ▼ [SHA-256 hash recorded in manifest]
    │
    ▼ [Sanitization: secrets, PII, proprietary code stripped]
    │
    ▼ [Redaction manifest generated]
    │
    ▼ [Cleaned text sent to Claude Code agent as context]
    │
    ▼ [Structured extraction — CandidateProfile JSON]
    │
    ▼ [Profile persisted locally; raw context discarded from agent memory]
    │
    ▼ [Deliverables generated from Profile + JobRequirements only]
```

At no point does raw session content leave the user's machine in persistent form. Claude Code processes it in-context (same trust model as normal Claude Code usage), but the only persisted artifacts are the structured `CandidateProfile`, the `MatchEvaluation`, and the final deliverables.

## File Structure

```
claude-candidate/
├── PROJECT.md                          # This file
├── README.md                           # Public-facing project description
├── plans/
│   ├── 01-candidate-profile-schema.md  # CandidateProfile IR spec
│   ├── 02-agent-team-orchestration.md  # Claude Code Agent Teams config
│   ├── 03-session-manifest-hashing.md  # Trust/verification module
│   └── 04-browser-extension-quick-match.md  # Extension, server, and daily-driver feature
├── src/
│   └── claude_candidate/
│       ├── __init__.py
│       ├── cli.py                      # Click CLI entrypoint
│       ├── server.py                   # FastAPI local backend (localhost:7429)
│       ├── selector.py                 # Stage 0: session selection & consent
│       ├── sanitizer.py                # Stage 1: cleaning & redaction
│       ├── extractor.py                # Stage 2: signal extraction
│       ├── job_parser.py               # Stage 3: job posting ingestion
│       ├── matcher.py                  # Stage 4: match evaluation
│       ├── generator.py                # Stage 5: deliverable generation
│       ├── manifest.py                 # Trust layer: hashing & verification
│       ├── resume_parser.py            # Resume PDF/DOCX ingestion
│       ├── merger.py                   # Resume + session profile merging
│       ├── enrichment.py               # Company enrichment engine
│       ├── quick_match.py              # Quick match engine (3-dimension scoring)
│       ├── correlator.py               # Public repo correlation detection
│       ├── proof_generator.py          # Proof package markdown generation
│       ├── storage.py                  # SQLite persistence (assessments, watchlist)
│       ├── schemas/
│       │   ├── candidate_profile.py    # Pydantic CandidateProfile model
│       │   ├── job_requirements.py     # Pydantic JobRequirements model
│       │   ├── match_evaluation.py     # Pydantic MatchEvaluation model
│       │   ├── session_manifest.py     # Pydantic manifest models
│       │   ├── resume_profile.py       # Pydantic ResumeProfile model
│       │   ├── merged_profile.py       # Pydantic MergedEvidenceProfile model
│       │   ├── company_profile.py      # Pydantic CompanyProfile model
│       │   └── fit_assessment.py       # Pydantic FitAssessment model
│       └── agents/
│           ├── team_config.py          # Agent team setup & coordination
│           └── prompts/
│               ├── sanitizer.md        # Sanitizer agent instructions
│               ├── extractor.md        # Extractor agent instructions
│               ├── matcher.md          # Matcher agent instructions
│               └── writer.md           # Writer agent instructions
├── extension/
│   ├── manifest.json                   # Chrome Extension Manifest V3
│   ├── content_script.ts              # Job posting DOM extraction
│   ├── popup.html                      # Extension popup UI
│   ├── popup.js                        # Popup logic
│   ├── popup.css                       # Popup styles
│   ├── sidebar.html                    # Sidebar detail view
│   ├── sidebar.js                      # Sidebar logic
│   ├── icons/
│   │   ├── icon16.png
│   │   ├── icon48.png
│   │   └── icon128.png
│   └── extractors/
│       ├── linkedin.ts                 # LinkedIn-specific DOM extraction
│       ├── greenhouse.ts               # Greenhouse-specific extraction
│       ├── lever.ts                    # Lever-specific extraction
│       ├── indeed.ts                   # Indeed-specific extraction
│       └── generic.ts                  # Generic fallback extractor
├── teams/
│   └── candidate-eval/
│       ├── CLAUDE.md                   # Team-level shared context
│       └── agents/
│           ├── sanitizer/CLAUDE.md
│           ├── extractor/CLAUDE.md
│           ├── matcher/CLAUDE.md
│           └── writer/CLAUDE.md
├── tests/
│   ├── test_sanitizer.py
│   ├── test_extractor.py
│   ├── test_manifest.py
│   ├── test_job_parser.py
│   ├── test_matcher.py
│   ├── test_resume_parser.py
│   ├── test_merger.py
│   ├── test_enrichment.py
│   ├── test_quick_match.py
│   ├── test_server.py
│   ├── test_storage.py
│   └── fixtures/
│       ├── sample_session.jsonl
│       ├── sample_job_posting.txt
│       ├── sample_resume.pdf
│       └── expected_profile.json
├── pyproject.toml
└── LICENSE
```

## Versioning & Roadmap

### v0.1 — Proof of Concept (Current Target)
- Manual session selection (file paths as CLI args)
- Basic regex sanitization (secrets, API keys, file paths)
- Single-pass extraction via Claude Code (no agent teams yet)
- Paste-only job posting input
- Resume ingestion (PDF/DOCX → ResumeProfile)
- Merged evidence profile (resume + sessions)
- Markdown output: match summary + resume bullets
- SHA-256 session manifest

### v0.2 — Agent Team Pipeline + Quick Match
- Full agent team orchestration with 4 specialized agents
- Interactive session selector with preview
- URL-based job posting ingestion
- Cover letter generation
- Redaction manifest with categorized audit trail
- Public repo cross-reference detection
- Local backend server (FastAPI, localhost:7429)
- Quick match engine with three-dimension scoring
- Company enrichment engine (website, blog, GitHub)

### v0.3 — Browser Extension + Trust Layer
- Chrome extension (Manifest V3) with content scripts for LinkedIn, Greenhouse, Lever, Indeed
- Extension popup with fit assessment card
- Extension sidebar with detailed view
- Watchlist and comparison features
- Signed manifests with timestamp attestation
- Portfolio narrative generation (integration with claude-narrator)
- Git history correlation engine

### v0.4 — Polish & Completeness
- Interview prep module
- Configurable output formats (markdown, docx, PDF)
- Firefox extension compatibility
- Generic fallback extractor improvements
- Assessment history and trend tracking
- "Generate Full Application" flow from extension to full pipeline

### v1.0 — Distribution
- pip-installable package
- Chrome Web Store listing (unlisted or public)
- Comprehensive test suite
- Documentation site
- Example evaluations (from building claude-candidate itself)
- Blog post generated by blog-a-claude documenting the build

### Future Exploration
- **Structured candidate profile API**: a standardized format that hiring tools could ingest directly, bypassing the resume entirely
- **Team evaluation mode**: process an entire team's logs to identify collective strengths and gaps for team composition planning
- **Skill trajectory tracking**: compare profiles over time to show growth velocity, not just current state
- **Anonymized benchmarking**: opt-in aggregate statistics ("this candidate's architecture decision frequency is in the 90th percentile among users who've processed their logs") — requires careful privacy design
- **Reverse matching**: given a CandidateProfile, search for job postings that are strong fits (invert the pipeline direction)
- **Application lifecycle tracking**: assessed → watchlisted → applied → interview → offer — turn the watchlist into a lightweight ATS
- **Salary correlation**: surface compensation context from public data alongside fit scores

## Design Principles

1. **Privacy is structural, not policy.** Raw data never persists outside the user's machine. The architecture makes exposure impossible, not merely prohibited.

2. **Evidence over assertion.** Every skill claim traces back to a specific session. "Proficient in Python" becomes "Demonstrated async pipeline debugging across 47 sessions, including architectural refactors in 12."

3. **Honesty is the feature.** Redaction transparency, open-source method, cryptographic anchoring — the trust model is the product differentiator, not an afterthought.

4. **Modular and composable.** Each stage is independently useful. The sanitizer works without the extractor. The extractor works without the matcher. The manifest works with any data pipeline.

5. **Dogfooding as proof.** The project demonstrates the skills it evaluates. The session logs from building it are valid input to it.

## Agent Team Lead Handoff Notes

This PROJECT.md provides full context for the product vision. Four detailed plan files follow, each scoped to a workstream:

- **Plan 01 (CandidateProfile Schema)**: Defines the central data model — the IR that every stage reads or writes. Start here because everything depends on it.
- **Plan 02 (Agent Team Orchestration)**: Defines the Claude Code Agent Teams configuration — how the pipeline actually runs. Depends on Plan 01 for schema contracts.
- **Plan 03 (Session Manifest & Hashing)**: Defines the trust/verification layer — the cryptographic proof system. Can proceed independently of Plan 02 but needs Plan 01's session metadata schema.
- **Plan 04 (Browser Extension Quick Match)**: Defines the daily-driver feature — browser extension, local backend server, resume ingestion, merged evidence profile, company enrichment, quick match engine, watchlist, and comparison. Depends on Plan 01 for schemas and extends them with ResumeProfile, MergedEvidenceProfile, CompanyProfile, and FitAssessment. This is the primary user-facing surface.

Recommended execution order: Plan 01 first (schema is foundational), then Plans 02, 03, and 04's schema/backend work in parallel, with the browser extension starting once the backend API is stable. Integration testing once all four converge.
