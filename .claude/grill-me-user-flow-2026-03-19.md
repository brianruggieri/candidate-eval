# Grill Session: User Flow
Date: 2026-03-19
Branches explored: 17
Research dispatched: 3 (hiring manager reception, cover letter site content, Cloudflare deploy)

## Risk Tree (final state)

```
[x] 1. Extension flow: browse → grade
  [x] 1.1 Job posting extraction — personal tool, CLI fallback
  [x] 1.2 Progressive loading — 3-call architecture
  [x] 1.3 Partial popup — weighted % from skills/experience/education
  [x] 1.4 Full report card — dimension scores + narrative verdict + receptivity signal
  [x] 1.5 Renders in popup — no new tab
  [x] 1.6 Bookmark — shortlist with metadata, clipboard copy for spreadsheet
  [x] 1.7 Cache — 1 month TTL, no change detection
[x] 2. Generation flow: bookmark → deliverables
  [x] 2.1 Triggered from CLI, one at a time
  [x] 2.2 Cover letter site page
  [x] 2.3 Output — roojerry.com/apply/{company-slug}/
  [x] 2.4 Deploy — wrangler pages deploy
[x] 3. First-time setup — personal tool, not a product concern
[x] 4. Lifecycle
  [x] 4.1 Profile refresh — manual
  [x] 4.2 History — shortlist is the history
  [x] 4.3 Accessible from both extension and CLI
```

## Decisions

### 1. Three-phase user flow (MAJOR COURSE CORRECTION)
**Decision:** The user flow is three distinct phases, not a single pipeline:
1. **Browse & grade** (extension) — quick partial match → full report card
2. **Shortlist** (extension) — save jobs worth applying to
3. **Generate & deploy** (CLI, later) — produce cover letter site page for shortlisted jobs

**Rationale:** Deliverables are expensive and only needed for jobs the user actually applies to. Grading should be fast and lightweight. The previous flow generated deliverables immediately on full assessment, which was wasteful.
**Alternatives rejected:** Single-pipeline (assess + generate in one shot) — unnecessary Claude calls for jobs that don't make the cut.

### 2. Three-call Claude architecture
**Decision:** Three Claude calls with different purposes and caching:
- **Call 1:** Extract posting + structured requirements (on click, cached per URL)
- **Call 2a:** Company research — mission/culture/values (background, cached per company)
- **Call 2b:** AI engineering dimension scoring from session patterns (background, parallel with 2a)

Mission and culture grading happen locally using company research output — no additional LLM call needed.

**Rationale:** Company research is cacheable across postings at the same company. AI scoring is independent of company research. Running them in parallel reduces wall-clock time to max(2a, 2b) instead of sum.
**Alternatives rejected:** Single monolithic Claude call (can't parallelize, can't cache company research independently). Two calls (would serialize company research and AI scoring).

### 3. Partial popup shows weighted percentage, not letter grade
**Decision:** Partial result displays a weighted percentage (e.g., "72% match") from three locally-scorable dimensions: skills match, experience match, education/tech stack match. Each dimension is rolled up with expandable details. No mission, culture, or AI engineering scores shown until Claude finishes.

**Rationale:** Only show what you can actually score. The old partial view showed fake 50% D grades for mission and culture, which couldn't be computed locally. The percentage vs. letter grade distinction makes it visually obvious whether you're looking at partial or full results.
**Alternatives rejected:** Showing placeholder grades for unscored dimensions. Single overall number without dimension breakdown.

### 4. Full report card stays in popup
**Decision:** The full report card (all dimensions + narrative verdict + receptivity signal) renders in the extension popup. No new tab opens.

**Rationale:** With deliverables removed from the report card, there's not enough content to justify a full page. The report card is: dimension scores, a short narrative verdict, and a receptivity signal. That fits in a popup.
**Alternatives rejected:** Opening full report in a new browser tab (previous implementation).

### 5. Full report card content
**Decision:** The full report card adds to the partial result:
- Mission alignment (from company research)
- Culture fit (from company research)
- AI engineering score (folded into skills, from session pattern analysis)
- Narrative verdict: 2-3 sentence opinionated assessment from Claude
- Receptivity signal: high/medium/low flag for whether this company would value the AI-portfolio approach

Letter grade replaces the percentage when full results land. Partial data persists as part of the larger picture.

**Rationale:** The report card answers two questions: "Is this worth my effort?" (grades + narrative) and "Would my AI-powered application approach land here?" (receptivity signal).
**Alternatives rejected:** Including talking points or gap framing on the report card (that's deliverable generation territory).

### 6. Shortlist replaces watchlist
**Decision:** Rename "watchlist" to "shortlist." Saves: company, title, location, salary, posting URL, date saved, grade, pointer to cached assessment. Includes a clipboard button that copies a tab-separated row matching the user's existing Google Sheets tracking spreadsheet.

**Rationale:** "Watchlist" implies passive monitoring of something that changes. Job postings don't change. This is a shortlist for later generation. The clipboard button is lowest-lift way to bridge into the existing spreadsheet workflow.
**Alternatives rejected:** CSV export (file management overhead). Full application tracker with statuses (scope creep — the spreadsheet handles that).

### 7. Cover letter site page content and philosophy
**Decision:** The generated page at roojerry.com/apply/{company-slug}/ contains:
1. Hero with fit score + "Built with claude-candidate" transparency badge (immediately visible, approachable)
2. Skills match grid mapping their requirements to candidate evidence
3. Tailored narrative (150-250 words, Claude-generated, evidence-grounded)
4. Evidence highlights (2-3 curated session/project examples)
5. How This Works explainer + GitHub repo link
6. CTA (contact info, resume PDF download if it fits the design)
7. Footer (private page notice, assessment metadata)

No inline resume. No resume bullets section. Resume is at most a PDF download link.

**Rationale:** The page IS the demonstration of AI engineering skill. The medium is the message. A hiring manager seeing "this candidate built the AI system that generated this page" is more compelling than any resume bullet. The transparency badge goes near the hero because in a trust-depleted hiring landscape (65% of hiring managers have caught deceptive AI use), being upfront is contrarian and attention-getting.
**Alternatives rejected:** Including full resume inline (dilutes the focused pitch). Hiding AI generation (loses the core differentiator).

### 8. Deploy mechanism
**Decision:** `wrangler pages deploy ./site --project-name=roojerry` runs automatically at the end of `claude-candidate generate --job <id>`. One command generates the page and deploys it.

**Rationale:** Simplest option — no git ceremony, no CI/CD pipeline, no repo bloat from generated HTML. Direct upload to Cloudflare CDN. One-time setup is just `wrangler login`.
**Alternatives rejected:** GitHub repo + auto-deploy on push (unnecessary git ceremony). Raw Cloudflare API (reinventing wrangler). CI/CD pipeline (overkill for personal tool).

### 9. Cache and lifecycle
**Decision:** Assessments cached for 1 month per URL hash. No change detection on postings. Candidate profile refresh is manual. Shortlist serves as history — shows grades alongside job details, accessible from both extension popup and CLI (`claude-candidate shortlist`).

**Rationale:** Job postings rarely stay up for a month. Profile changes when the user decides to re-scan, not on a schedule. The shortlist is the natural place to review past assessments since it already has all the metadata.
**Alternatives rejected:** Auto-refresh of profile. Staleness detection on postings. Separate history view.

## Accepted Risks
- ATS systems won't click the site link — mitigated by still submitting a traditional resume through the portal. The site is a supplement for warm outreach, not a replacement for ATS submission.
- ~20% of hiring managers auto-reject AI-generated content regardless of transparency — acceptable given the target audience is AI-native companies where this is a feature, not a bug.
- Job posting extraction may fail on some sites — acceptable for personal tool, CLI fallback exists.

## Key Divergence from Current Codebase
The current implementation conflates assessment and generation:
- `/api/assess/full` generates deliverables (resume bullets, cover letter, interview prep)
- Extension opens a new tab for full report
- Popup shows mission/culture scores that can't be computed locally
- "Watchlist" naming implies monitoring

All of these need to change to match the revised flow.
