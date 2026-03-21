# Roadmap

Last updated: 2026-03-21

## Where We Are

**v0.5** — Core pipeline complete, scoring engine calibrated (24/24 within 1 grade), browser extension functional, CLI comprehensive. The tool works end-to-end for Brian's job search. Main gaps are extraction quality, UX polish, and distribution readiness.

## Priorities

Organized by impact on the active job search. Tier 1 items run in parallel.

---

### Tier 1: Daily Driver (this week)

Make the tool practical for daily use during active job search. Items 1.1 and 1.2 are independent and run in parallel.

#### 1.1 Fit Landing Page
**Status:** In progress on `feat/export-fit` (spec at `docs/superpowers/specs/2026-03-21-fit-landing-page-design.md`)

Generate a polished, shareable HTML page per job posting showing fit assessment, skill evidence, and talking points. This is the "proof package" that makes the tool's output useful beyond a CLI grade.

**Depends on:** Nothing (builds on existing `site_renderer.py` + `proof_generator.py`)

#### 1.2 Session Extractor Overhaul
**Status:** Not started. **Biggest remaining accuracy lever.**

The extractor found TypeScript in 1 out of ~1000+ sessions. Python in 3 out of ~500+. The current approach looks at conversation text but misses the strongest signals: file types edited, imports used, tool calls made, error messages debugged.

**Approach:**
- Parse tool_use blocks for file extensions (.ts, .py, .rs → language detection)
- Parse code blocks for import statements (import React → react, from fastapi → fastapi)
- Weight depth by what the user DID vs what the AI discussed
- Count unique sessions per skill, not just evidence snippets

**Impact:** Would dramatically increase corroborated skill count (currently 3, should be 20+). This directly improves scoring accuracy because corroborated skills get higher confidence. Also makes the landing page content richer and the blog post story stronger.

**Depends on:** Nothing (extractor.py is independent). Runs in parallel with 1.1.

#### 1.3 Incremental Session Scanning
**Status:** Filed as #7

Currently re-scans all 1857 sessions every time. Need delta detection: track which sessions have been processed (by manifest hash), only process new ones. Makes `sessions scan` practical as a daily command.

**Effort:** Small — add a processed_sessions table to assessments.db, skip sessions whose hash is already stored.

**Depends on:** Nothing. Best done after 1.2 so the new extractor benefits from incremental scanning immediately.

#### 1.4 Extension UX Polish
**Status:** Functional but rough edges

- LinkedIn URL detection should auto-trigger assessment
- Loading states need better feedback
- "Generate full application" button should link to CLI command or landing page
- Assessment card should show top 3 strengths + top 3 gaps

**Depends on:** 1.1 (landing page to link to)

---

### Tier 2: Accuracy & Quality (next sprint)

Improve the fidelity of assessments.

#### 2.1 LinkedIn-Specific Requirement Parser
**Status:** Generic fallback only

LinkedIn postings have consistent HTML structure. A dedicated parser would extract:
- Structured requirements (must-have vs nice-to-have from bullet formatting)
- Years of experience from specific phrases
- Education requirements
- Remote/hybrid/on-site from location field
- Salary band when shown

**Depends on:** Nothing (extension content.js + requirement_parser.py)

#### 2.2 Location & Remote Scoring
**Status:** Data exists, not scored

Postings have `location` and `remote` fields. The candidate is in Athens, GA — remote-only strongly preferred. This should factor into the overall grade:
- Remote: no penalty
- Hybrid with occasional travel: minor penalty
- On-site required (SF/NYC): significant penalty
- On-site required (other): major penalty

**Depends on:** Nothing (quick_match.py addition)

---

### Tier 3: Portfolio & Distribution (before v1.0)

Make the project presentable as the showpiece it's meant to be.

#### 3.1 Demo Recording
**Status:** Not started

Create a 30-60 second screen recording or GIF showing: paste a job URL → extension detects it → assessment appears → click through to landing page. This becomes the hero asset for README, blog post, and job applications. The tool IS the proof — but only if someone can SEE it working.

**Depends on:** 1.1 (landing page) + 1.4 (extension polish)

#### 3.2 Blog Post: The Accuracy Loop
**Status:** Draft material at `docs/accuracy-improvement-journey.md`

Publish the story of taking skill matching from 4/24 to 24/24. Two-act structure:
- Act 1: Scoring calibration (confidence ceiling, virtual inference, grade recalibration)
- Act 2: Extraction quality (3 → 20+ corroborated skills, the deeper problem)

**Target audience:** AI engineers, hiring managers, anyone building evaluation systems.

**Depends on:** 1.2 (extractor overhaul completes the story arc)

#### 3.3 Public README
**Status:** Current README is 17 lines

Write a proper README with:
- What it does (2 sentences)
- Demo GIF/video (from 3.1)
- Quick start (install, scan sessions, assess a posting)
- Architecture diagram
- The meta property (tool evaluates its own builder)
- Privacy model
- Contributing guide

**Depends on:** 3.1 (demo recording for hero asset)

#### 3.4 Interview Prep Module
**Status:** In PROJECT.md roadmap, not started

Given a FitAssessment, generate:
- Talking points for each matched skill (with session evidence)
- Anticipated gap questions + prepared responses
- Company research summary
- Questions to ask the interviewer

**Depends on:** Core pipeline (done), enrichment.py (done)

#### 3.5 Output Formats
**Status:** Markdown only

Add PDF and DOCX export for:
- Tailored resume bullets
- Cover letter
- Proof package

**Depends on:** 1.1 (landing page HTML → PDF via puppeteer/playwright)

---

### Tier 4: v1.0 Distribution

#### 4.1 pip-installable Package
**Status:** pyproject.toml exists, hatchling configured

Publish to PyPI. Requires:
- Entry point configuration for CLI
- Clean dependency list (no dev deps in main)
- Version bumping strategy

#### 4.2 Chrome Web Store Listing
**Status:** Extension works locally, not published

Requires:
- Privacy policy
- Store listing copy + screenshots
- Review process (~1-2 weeks)

#### 4.3 Documentation Site
**Status:** Not started

GitHub Pages or similar with:
- Getting started guide
- Architecture deep dive
- Privacy model explanation
- API reference (FastAPI auto-docs)

---

### Future Exploration (post-v1.0)

These are ideas from PROJECT.md worth tracking but not on the critical path:

| Idea | Value | Complexity |
|------|-------|------------|
| **Reverse matching** — given a profile, find fitting postings | High | Medium (inverts the pipeline) |
| **Application lifecycle tracking** — assessed → applied → interview → offer | High | Low (extend watchlist) |
| **Skill trajectory** — compare profiles over time, show growth velocity | Medium | Medium (needs historical snapshots) |
| **Salary correlation** — surface compensation context alongside fit scores | Medium | Low (data exists in postings) |
| **Anonymized benchmarking** — percentile rankings across opt-in users | Low | High (privacy design needed) |
| **Team evaluation mode** — assess a team's collective profile | Low | Medium |

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-18 | Identity is portfolio piece, not product | Code quality is a deliverable. Source code faces hiring teams. |
| 2026-03-18 | Privacy is structural, not policy | Raw data never persists outside user's machine. |
| 2026-03-20 | Prefer over-grading to under-grading | False negatives (missing good opportunities) cost more than false positives. |
| 2026-03-21 | Expected grades are a living document | System improvements can reveal initial grades were wrong. Principled recalibration > moving goalposts. |
| 2026-03-21 | Session extractor is the #1 remaining lever | Corroborated skills (3 currently) should be 20+. Everything else is workarounds. |
| 2026-03-21 | Parallel tracks: landing page + extractor | Independent codepaths, extractor improves all downstream output. CEO review decision. |
| 2026-03-21 | Blog post sequenced after extractor | Two-act story (calibration + extraction) is more publishable than Act 1 alone. |
| 2026-03-21 | Demo recording before README | The tool is the proof — showing beats describing. Hero asset for all distribution. |
