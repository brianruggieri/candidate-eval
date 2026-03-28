# Roadmap

Last updated: 2026-03-24

## Where We Are

**v0.8.2** — Core pipeline complete, scoring engine calibrated (47/47 within 1 grade), browser extension functional, CLI comprehensive. Dual evidence model (resume + repos), 104-skill taxonomy, eligibility gates, confidence scoring, and Chrome extension for real-time assessment. All major features shipped.

---

## Shipped

### v0.5 Core Features

| Feature | Status | Notes |
|---------|--------|-------|
| **Fit Landing Page / export-fit** | Shipped | `fit_exporter.py`, `export-fit` CLI command live |
| **Session Extractor Overhaul** | Shipped (PR #10) | 15 → 76 skills, all 12 patterns, AI-native signals (tool_use blocks, imports, file extensions) |
| **Job Posting Requirement Parser** | Shipped | `requirement_parser.py` with structured must-have/nice-to-have extraction |
| **Evidence Compaction** | Shipped | `evidence_compactor.py`, `--no-compact` flag in CLI |
| **Eligibility Filters** | Shipped | Location/work-auth gates in `quick_match.py` (PR #19) |
| **Adoption Velocity Scoring** | Shipped | Composite velocity score in `quick_match.py` (PR #16) |
| **Curated Resume Schema** | Shipped | `curated_resume.py`, single resume ingest path (PR #15) |
| **Soft Skill Discounting** | Shipped | 0.3→0.5 discount with culture signal modulation (PR #17) |
| **Taxonomy Expansion** | Shipped | 33 → 104 canonical skills across languages, frameworks, tools, platforms, domains, practices, soft skills (PR #18) |
| **Interactive Whitelist** | Shipped | `whitelist.py`, interactive CLI for session project filtering |
| **Interview Prep Deliverable** | Shipped | `generator.py` — talking points, gap questions, company research |
| **Browser Extension UX Polish** | Shipped | Popup redesign, responsiveness, loading states |
| **Public README** | Shipped | ~95 lines with architecture overview, quick start, privacy model, AI-agents hook |

### v0.5 Pipeline Polish (current branch `v0.5/plan1-readme`, pending merge)

| Fix | Status |
|-----|--------|
| Assessment timer covers full pipeline including requirement parsing | Shipped, pending merge |
| Per-deliverable-type timeouts (cover-letter: 300s, default: 180s) | Shipped, pending merge |
| Domain mismatch false positive filter (compliance removed from DOMAIN_KEYWORDS) | Shipped, pending merge |
| CONFLICTING-EXPERT confidence floor fix + ai-research taxonomy alias | Shipped, pending merge |
| Test tier split — `--run-slow` flag, dev loop 5min → 7s | Shipped, pending merge |
| Tutorial walkthrough design + execution plan | Shipped, pending merge |
| README AI-agents hook rewrite (5-reviewer synthesis) | Shipped, pending merge |

---

## Priorities

Organized by impact on the active job search.

---

### Tier 1: Distribution Readiness

#### 1.1 Demo Recording
**Status:** Not started

Create a 30-60 second screen recording or GIF showing: paste a job URL → extension detects it → assessment appears → click through to landing page. This becomes the hero asset for README, blog post, and job applications. The tool IS the proof — but only if someone can SEE it working.

**Depends on:** Landing page (shipped) + extension polish (shipped)

#### 1.2 Blog Post: The Accuracy Loop
**Status:** Draft material at `docs/accuracy-improvement-journey.md`

Publish the story of taking skill matching from 4/24 to 24/24. Two-act structure:
- Act 1: Scoring calibration (confidence ceiling, virtual inference, grade recalibration)
- Act 2: Extraction quality (3 → 76 skills, the deeper problem solved)

**Target audience:** AI engineers, hiring managers, anyone building evaluation systems.

**Depends on:** Demo recording preferred (Act 2 is now complete — story arc is ready)

---

### Tier 2: Incremental Improvements

#### 2.1 Incremental Session Scanning
**Status:** Filed as #7

Currently re-scans all 1857 sessions every time. Need delta detection: track which sessions have been processed (by manifest hash), only process new ones. Makes `sessions scan` practical as a daily command.

**Effort:** Small — add a processed_sessions table to assessments.db, skip sessions whose hash is already stored.

#### 2.2 Depth Calibration
**Status:** Noted as separate brainstorm — not planned

Calibrating skill depth signals (session count, recency, evidence weight) for more accurate depth scores. Kept as exploration item.

#### 2.3 Output Formats
**Status:** Markdown and HTML only

Add PDF export for:
- Tailored resume bullets
- Cover letter
- Proof package

**Depends on:** Landing page HTML → PDF via puppeteer/playwright

---

### Tier 3: v1.0 Distribution

#### 3.1 pip-installable Package
**Status:** pyproject.toml exists, hatchling configured

Publish to PyPI. Requires:
- Entry point configuration for CLI
- Clean dependency list (no dev deps in main)
- Version bumping strategy

#### 3.2 Chrome Web Store Listing
**Status:** Extension works locally, not published

Requires:
- Privacy policy
- Store listing copy + screenshots
- Review process (~1-2 weeks)

#### 3.3 Documentation Site
**Status:** Not started

GitHub Pages or similar with:
- Getting started guide
- Architecture deep dive
- Privacy model explanation
- API reference (FastAPI auto-docs)

---

### Future Exploration (post-v1.0)

These are ideas worth tracking but not on the critical path:

| Idea | Value | Complexity |
|------|-------|------------|
| **Reverse matching** — given a profile, find fitting postings | High | Medium (inverts the pipeline) |
| **Application lifecycle tracking** — assessed → applied → interview → offer | High | Low (extend watchlist) |
| **Skill trajectory** — compare profiles over time, show growth velocity | Medium | Medium (needs historical snapshots) |
| **Salary correlation** — surface compensation context alongside fit scores | Medium | Low (data exists in postings) |
| **Anonymized benchmarking** — percentile rankings across opt-in users | Low | High (privacy design needed) |
| **Team evaluation mode** — assess a team's collective profile | Low | Medium |
| **Signed manifests / timestamp attestation** | Low | Medium (cryptographic provenance) |
| **Agent Teams orchestration** | Deferred | Not planned — session-based workflow is sufficient |

---

## Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-18 | Identity is portfolio piece, not product | Code quality is a deliverable. Source code faces hiring teams. |
| 2026-03-18 | Privacy is structural, not policy | Raw data never persists outside user's machine. |
| 2026-03-20 | Prefer over-grading to under-grading | False negatives (missing good opportunities) cost more than false positives. |
| 2026-03-21 | Expected grades are a living document | System improvements can reveal initial grades were wrong. Principled recalibration > moving goalposts. |
| 2026-03-21 | Session extractor is the #1 remaining lever | Corroborated skills (3 at the time) should be 20+. Everything else is workarounds. |
| 2026-03-21 | Parallel tracks: landing page + extractor | Independent codepaths, extractor improves all downstream output. |
| 2026-03-21 | Blog post sequenced after extractor | Two-act story (calibration + extraction) is more publishable than Act 1 alone. |
| 2026-03-21 | Demo recording before README | The tool is the proof — showing beats describing. Hero asset for all distribution. |
| 2026-03-22 | Taxonomy expanded to 104 canonical skills | Broader coverage eliminates false negatives from narrow skill matching. |
| 2026-03-22 | Single curated resume path | Remove resume ingest complexity; human curation is more accurate than automated parsing. |
| 2026-03-22 | Adoption velocity in scoring | Adaptability is a strong signal for AI-adjacent roles; infer from new-tech adoption rate. |
| 2026-03-22 | Soft skill discounting to 0.5 with culture modulation | Soft skills are real but overrepresented in postings; discount prevents grade inflation. |
| 2026-03-22 | Eligibility filters as hard gates | Location/work-auth mismatches should fail early — no point scoring a non-starter. |
| 2026-03-24 | CONFLICTING-EXPERT confidence floor | Conflicting evidence should not collapse confidence to zero; floor at 0.4 preserves signal. |
| 2026-03-24 | Per-deliverable-type timeouts | Cover letters need longer generation time than other deliverables; uniform timeout was wrong. |
| 2026-03-24 | Test tier split with --run-slow | Dev loop at 7s vs 5min is a forcing function for fast iteration. Slow tests still run in CI. |
