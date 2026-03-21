# Fit Landing Page — Cover Letter Replacement

**Date:** 2026-03-21
**Status:** Draft
**Repos:** `claude-candidate` (CLI export), `roojerry` (Hugo template + rendering)

## Overview

A per-company landing page that replaces a traditional cover letter. Each page lives at `roojerry.com/fit/<slug>` and shows an evidence-backed fit assessment — how the candidate's verified skills, behavioral patterns, and project history match a specific company's job requirements. Every claim is backed by session data, not self-reported.

The audience is a hiring manager or recruiter evaluating a senior software engineer.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Layout source | Stitch HTML restyled with roojerry.com design system | Structure from Stitch, brand from roojerry |
| Platform | Web, desktop-first | Recruiters evaluate at a desk |
| Data flow | CLI export writes markdown to Hugo content dir | Decoupled repos, one-command workflow |
| URL structure | `/fit/<tight-slug>` (e.g., `/fit/staff-engineer-anthropic`) | Short, clean, role + company |
| Visibility | Unlisted by default, `public: true` flag for index | Protect weak matches, showcase strong ones |
| Company logo | None — company name in heading font | Zero maintenance, avoids trademark issues |
| Navigation | Standalone sticky nav with section anchors | Keeps recruiter focused, no portfolio distraction |
| CTA | Cal.com booking link | Low friction scheduling, free tier |
| Portfolio link | Subtle footer link only | Available for curious recruiters, not prominent |
| Privacy | `noindex` meta + sitemap exclusion + robots.txt disallow | Well-behaved crawlers won't index unlisted pages |

---

## Repo 1: roojerry (Hugo Template + Rendering)

### New Files

| File | Purpose |
|------|---------|
| `content/fit/_index.md` | Section config — title, description for the list page |
| `layouts/fit/single.html` | The fit page template |
| `layouts/fit/list.html` | Public assessment index (only `public: true` pages) |
| `static/css/fit.css` | Fit-specific styles (grade badge, status colors, amber token) |

### Template Strategy

`layouts/fit/single.html` is a **fully standalone template** — it does NOT extend `baseof.html`. This avoids loading the canvas background, physics field, coin flip, jQuery, Bootstrap JS, and other portfolio-specific resources (~200KB of JS the fit page doesn't need). The fit template provides its own `<html>`, `<head>`, and `<body>` with only the CSS and fonts it needs.

### No Changes To

- `baseof.html` — untouched, fit pages don't extend it
- `design-system.css` — reuse existing variables via `@import` in `fit.css`
- `hugo.toml` sections array — fit is NOT a homepage section
- Existing layouts, partials, JS — untouched

### Content File Structure

Each assessment is `content/fit/<slug>.md` with all data in front matter:

```yaml
---
title: "Staff Engineer"
company: "Anthropic"
slug: "staff-engineer-anthropic"
description: "Evidence-backed fit assessment for Staff Engineer at Anthropic"
posting_url: "https://linkedin.com/jobs/..."
date: 2026-03-20
public: false
cal_link: "https://cal.com/brianruggieri/30min"

overall_grade: "A+"
overall_score: 0.97
should_apply: "strong_yes"
overall_summary: "Exceptional fit for staff-level agent orchestration..."

skill_matches:
  - skill: "TypeScript"
    status: "strong_match"
    priority: "must_have"
    depth: "Expert"
    sessions: 995
    source: "corroborated"
    discovery: false
  - skill: "Python"
    status: "strong_match"
    priority: "must_have"
    depth: "Expert"
    sessions: 551
    source: "sessions_only"
    discovery: true

evidence_highlights:
  - heading: "React Architecture"
    quote: "Implemented custom React + Tailwind chat interface..."
    project: "TeamChat UI"
    date: "Feb 2026"
    tags: ["React", "Tailwind"]

patterns:
  - name: "Architecture First"
    strength: "Exceptional"
    frequency: "Dominant"
  - name: "Testing Instinct"
    strength: "Strong"
    frequency: "Common"

projects:
  - name: "claude-candidate"
    description: "Evidence-backed job fit assessment engine..."
    complexity: "Ambitious"
    technologies: ["Python", "FastAPI", "Pydantic"]
    sessions: 42
    date_range: "2026"
    callout: "Designed skill taxonomy with fuzzy matching..."

gaps:
  - requirement: "Kubernetes"
    status: "Adjacent experience with Docker, not direct K8s"
    action: "Completing CKA certification Q2 2026"
---
```

### Data Mapping (CLI Export → Front Matter)

The export command joins data from `FitAssessment` (via `SkillMatchDetail`) and `MergedEvidenceProfile` (via `MergedSkillEvidence`). The join key is the canonical skill name: `SkillMatchDetail.requirement` ↔ `MergedSkillEvidence.name`.

**skill_matches:**

| Front matter field | Source model | Source field | Transform |
|---|---|---|---|
| `skill` | `SkillMatchDetail` | `requirement` | Direct |
| `status` | `SkillMatchDetail` | `match_status` | Direct (enum value) |
| `priority` | `SkillMatchDetail` | `priority` | Direct (enum value) |
| `depth` | `MergedSkillEvidence` | `effective_depth` | Title case (`EXPERT` → `"Expert"`) |
| `sessions` | `MergedSkillEvidence` | `session_evidence_count` | Direct (int) |
| `source` | `SkillMatchDetail` | `evidence_source` | Direct (enum value) |
| `discovery` | `MergedSkillEvidence` | `discovery_flag` | Direct (bool) |

**evidence_highlights:**

Select the top 3 `SkillMatchDetail` entries with `match_status='strong_match'`, preferring `evidence_source='corroborated'` then `'sessions_only'`. For each, look up the matching `SkillEntry` in `CandidateProfile.skills` by name (not `MergedEvidenceProfile` — session references live on `CandidateProfile.SkillEntry.evidence[]`), then find the highest-confidence `SessionReference`:

| Front matter field | Source |
|---|---|
| `heading` | `SkillMatchDetail.requirement` (title cased) |
| `quote` | `SessionReference.evidence_snippet` |
| `project` | `SessionReference.project_context` |
| `date` | `SessionReference.session_date` (formatted as "Mon YYYY") |
| `tags` | Technologies from the parent `ProjectSummary` if available, else `[requirement]` |

**patterns:**

From `MergedEvidenceProfile.patterns`:

| Front matter field | Source field | Transform |
|---|---|---|
| `name` | `pattern_type` | Snake case → Title Case (`architecture_first` → `"Architecture First"`) |
| `strength` | `strength` | Capitalize (`exceptional` → `"Exceptional"`) |
| `frequency` | `frequency` | Capitalize |

**projects:**

From `MergedEvidenceProfile.projects` (type `ProjectSummary`):

| Front matter field | Source field | Transform |
|---|---|---|
| `name` | `project_name` | Direct |
| `description` | `description` | Direct |
| `complexity` | `complexity` | Capitalize |
| `technologies` | `technologies` | Direct (list) |
| `sessions` | `session_count` | Direct (int) |
| `date_range` | `date_range_start` + `date_range_end` | Format as "YYYY" or "YYYY — YYYY" |
| `callout` | `key_decisions[0]` | First key decision as the callout quote |

**gaps:**

Constructed from `FitAssessment.skill_matches` — select entries where `match_status` is `no_evidence` or `adjacent` AND `priority` is `must_have` or `strong_preference`. For each:

| Front matter field | Source | Transform |
|---|---|---|
| `requirement` | `SkillMatchDetail.requirement` | Title case |
| `status` | `SkillMatchDetail.candidate_evidence` | Direct — this field contains the "Adjacent experience with..." narrative |
| `action` | `FitAssessment.action_items` | Match the most relevant action item by keyword overlap with the requirement |

### Template Layout (single.html)

Eight sections, top to bottom:

**1. Sticky Nav Bar**
- Glassmorphic: `rgba(45,74,82,0.85)` + `backdrop-filter: blur(12px)`
- Left: "Brian Ruggieri" text
- Center: section anchors — Match / Skills / Evidence / Projects / Gaps
- Right: "Let's Talk" button → `{{ .Params.cal_link }}`

**2. Hero / Match Summary**
- Company name + role title as primary heading (Saira Extra Condensed, 700)
- Subtext: `{{ .Params.overall_summary }}`
- Confidence label: maps `should_apply` to display text (strong_yes → "Strong Yes")
- Must-have coverage stat (derived: count skill_matches where priority=must_have AND status!=gap)
- Grade badge (right side): circular, ~16rem, ring border colored by grade range
  - A-range: `#89C45A` (accent green)
  - B-range: `#f0b429` (amber — existing `--status-amber`)
  - C and below: `#64748B` (slate)
- Grade letter in center: Saira Extra Condensed, 700, ~5rem

**3. Skill Match Grid**
- 3-column responsive grid (3 → 2 → 1 on mobile)
- Glassmorphic cards with 3px left accent stripe
- Stripe color by status:
  - `strong_match`: `#89C45A` (green)
  - `exceeds`: `#23759E` (brand blue — distinct from strong match)
  - `partial_match`: `#f0b429` (amber — existing `--status-amber`)
  - `adjacent`: `#8BBAC1` (cyan)
  - `gap`: `#64748B` (slate)
- Card content: skill name (bold), status tag (pill, status color bg), priority label (small caps), depth + session count, source badge
- Discovery flag: subtle highlight badge "Found in sessions, not on resume"

**4. Evidence Highlights**
- Full-width cards
- Each: heading, quote in italics, project context, date
- Tech tags as teardrop cyan pills (existing roojerry tag style)

**5. Behavioral Patterns**
- Horizontal row of 4-5 glassmorphic cards
- Pattern name in Saira Extra Condensed
- Strength level + frequency below

**6. Projects Showcase**
- Timeline layout: left border + dot markers
- Cards: project name, description, complexity badge, tech pills, session count, date range
- One callout quote per project (accent green left border)

**7. Gap Transparency**
- Section title: "Where I'm Growing"
- Background: `#EEF4F6` (existing mid-tone)
- Each gap: requirement name, current status, action plan
- Confident tone — slate/cyan tones, no red
- Trending-up icon as subtle background element

**8. Footer**
- "Let's Talk" CTA button → Cal.com
- Links: GitHub, LinkedIn, "View full portfolio" → roojerry.com
- Credit: "Generated by claude-candidate"
- Copyright

### SEO / Privacy

In `single.html` head block:
```html
{{ if not .Params.public }}
<meta name="robots" content="noindex, nofollow">
{{ end }}
```

In `list.html`, only render cards where `public: true`:
```html
{{ range where .Pages ".Params.public" true }}
```

Add to `static/robots.txt` or Hugo-generated robots.txt:
```
# Unlisted fit pages are noindexed individually via meta tags
# This disallow is belt-and-suspenders for crawlers that ignore meta tags
User-agent: *
Disallow: /fit/
```
Note: The `/fit/` index page is also disallowed by this rule, but since it only renders public entries and those entries link to their own pages, discoverability comes from direct links shared with recruiters, not search engines. This is intentional — the fit section is not meant to be browsed organically.

### Design Token Mapping

**Typography:**

| Element | Font | Weight | Notes |
|---------|------|--------|-------|
| h1, h2, section titles | Saira Extra Condensed | 700 | Uppercase |
| Card titles, pattern names | Saira Extra Condensed | 700 | Uppercase |
| Labels, badges, small caps | Saira Extra Condensed | 600 | Uppercase, tracked |
| Body, descriptions, quotes | Open Sans | 400 | |
| Grade letter | Saira Extra Condensed | 700 | ~5rem |

**Colors:**

| Role | Value | Source |
|------|-------|--------|
| Strong match / positive | `#89C45A` | Existing accent green |
| Partial match / moderate | `#f0b429` | Existing `--status-amber` |
| Adjacent / neutral | `#8BBAC1` | Existing cyan |
| Gap / growing | `#64748B` | New — add as `--color-slate` in `fit.css` |
| Exceeds | `#23759E` | Existing brand blue |
| Headings | `#2D4A52` | Existing brand dark |
| Body text | `#6E6C70` | Existing muted gray |
| Page background | `#F4F4F2` | Existing off-white |
| Card background | `rgba(255,255,255,0.45)` | Existing glass |
| Card border | `rgba(29,53,64,0.14)` | Existing shadow tint |

**Cards:**
- Background: `rgba(255,255,255,0.45)`
- Border: 1px `rgba(29,53,64,0.14)` + 3px left accent stripe
- Border-radius: 12px
- Shadow: `0 1px 3px rgb(29 53 64 / 0.06), 0 6px 24px rgb(29 53 64 / 0.10)`
- Hover: `translateY(-4px)` + enhanced shadow (0.25s ease)

**Tags:**
- Tech tags: teardrop cyan pills (existing style)
- Status tags: pill with status color bg, white text
- Priority labels: Saira Extra Condensed, 600, small caps

### Accessibility

- All hover transitions (card lift, shadow enhance) respect `@media (prefers-reduced-motion: reduce)` — set transition duration to 0
- Grade badge has `aria-label` (e.g., `aria-label="Overall grade: A plus"`)
- Sticky nav section anchors are keyboard-navigable with visible focus outlines (`2px solid var(--color-accent)`)
- Status color tags include text labels (not color-only) — already the case since tags show "Strong Match", "Partial", etc.
- Sufficient color contrast: all text on glass cards meets WCAG AA (dark text on light semi-transparent bg)
- Landmark roles: `<nav>` for sticky nav, `<main>` for content, `<section aria-label="...">` for each section
- Skip-to-content link: hidden link before nav, visible on keyboard focus → jumps to `#match-summary`
- Touch targets: nav links and CTA buttons minimum 44px tap area on mobile

### Responsive Breakpoints

Desktop-first, with intentional layout changes per viewport.

**Desktop (>1024px):** Full layout as described above. 3-column skill grid. Horizontal pattern row. Timeline projects.

**Tablet (768–1024px):**
- Skill grid: 2 columns
- Hero grade badge: reduce from 16rem to 12rem
- Pattern cards: 2×2 grid instead of horizontal row
- Nav: keep section anchors, reduce font size

**Mobile (<768px):**
- Skill grid: single column
- Hero grade badge: reduce to 8rem, stack below heading (not beside it)
- Sticky nav: hide section anchors, show only "Brian Ruggieri" + "Let's Talk" CTA
- Typography: h1 scales from ~3rem to ~2rem, body stays 1rem
- Evidence cards: full width, reduce padding
- Projects timeline: remove left border, stack vertically as simple cards
- Pattern cards: single column
- Footer CTA: full-width button

### Print Stylesheet

`@media print` rules in `fit.css`:
- Hide sticky nav entirely
- White background (no glassmorphic effects)
- No box shadows
- Grade badge: solid border instead of colored ring
- Full-width single-column layout
- Page break avoidance on cards (`break-inside: avoid`)
- Show URLs after links (`a[href]:after { content: " (" attr(href) ")"; }`)
- Hide CTA buttons (Cal.com links not useful in print)

### Export Minimum Thresholds

The CLI `export-fit` command enforces minimum content thresholds. If a section doesn't meet its minimum, the export fails with a descriptive error telling the user what's missing.

| Section | Minimum | Rationale |
|---------|---------|-----------|
| Skill matches | 3 | Fewer than 3 means the assessment is too sparse to present |
| Evidence highlights | 0 (optional) | Section hidden if empty — extractor may not have quotes |
| Behavioral patterns | 0 (optional) | Section hidden if empty |
| Projects | 1 | At least one project needed for credibility |
| Gaps | 0 (optional) | Section hidden if 0 gaps (celebrated, not shown) |

Sections with 0 items are omitted from the page entirely (template uses `{{ with }}` guards). The CLI warns: "Note: Evidence Highlights section will be hidden (no session quotes available)."

### Hero Credibility Subtitle

Below the role title, a single line of derived stats provides instant context:

`13 years engineering · 995 TypeScript sessions · Evidence-backed fit assessment`

Format: `{total_years} years engineering · {top_skill_sessions} {top_skill} sessions · Evidence-backed fit assessment`

Where `top_skill` is the skill with the highest `session_evidence_count` in the merged profile. This line uses Open Sans 400, muted gray (`#6E6C70`), smaller than the summary text.

### List Page (list.html)

A simple card grid at `/fit/` showing only public assessments:
- Each card: company name, role title, grade badge (small), one-line summary
- Links to the full fit page
- If no public pages, show nothing (or a minimal "No public assessments" message)

---

## Repo 2: claude-candidate (CLI Export)

### New Command

`cli.py export-fit <assessment-id> [--output-dir PATH]`

**Location:** Add to existing `cli.py` Click group.

**Dependencies:** Reads from three data sources:
1. `assessments.db` — `FitAssessment` by `assessment_id` primary key (skill matches, grades, action items)
2. `~/.claude-candidate/merged_profile.json` — `MergedEvidenceProfile` (patterns, projects, skill depth/source)
3. `~/.claude-candidate/candidate_profile.json` — `CandidateProfile` (session references for evidence highlights)

### Behavior

1. Load FitAssessment from DB by `assessment_id`
2. Load MergedEvidenceProfile for pattern + project data
3. Generate slug:
   - Drop seniority prefixes except highest-level (Sr. Staff → Staff)
   - Drop suffixes (I, II, III, IV)
   - Truncate role to 2-3 words max
   - Lowercase, hyphenate
   - Append company name (first word only)
   - Examples: `staff-engineer-anthropic`, `eng-manager-substack`, `frontend-lead-adobe`
4. Select content:
   - Top 8-10 skill matches (sorted by priority desc, then score desc)
   - Top 3 evidence highlights (highest confidence, prefer corroborated)
   - Top 4-5 behavioral patterns (by strength desc)
   - Top 3-4 projects (prefer those with technology overlap with job requirements)
   - 2-3 gaps (must_have or strong_preference with no_evidence or adjacent status)
5. Write markdown file to `--output-dir` (required — no default; validate directory exists before writing)
6. Print: slug, file path, and the URL it will be at

### Slug Generation

```python
def generate_slug(title: str, company: str) -> str:
    """Generate a tight, clean slug from job title + company."""
    # Strip seniority prefixes, keep highest
    # Strip roman numeral suffixes
    # Truncate to 2-3 core words
    # Append first word of company name
    # Lowercase, hyphenate
```

### Output Format

YAML front matter matching the content file structure defined in Repo 1 above. No markdown body.

### Testing

- Test slug generation with edge cases (long titles, multi-word companies, seniority stacking)
- Test content selection (correct number of items, priority sorting)
- Test file output (valid YAML front matter, parseable by Hugo)

---

## Workflow

```
1. Run assessment:     .venv/bin/python -m claude_candidate.cli assess <posting-url>
2. Export fit page:    .venv/bin/python -m claude_candidate.cli export-fit <assessment-id> --output-dir ../roojerry/content/fit/
3. Review markdown:    cat ../roojerry/content/fit/<slug>.md
4. (Optional) Set:     public: true
5. Build site:         cd ../roojerry && npm run build
6. Deploy:             (existing GitHub Actions / rsync)
7. Share URL:          roojerry.com/fit/<slug>
```
