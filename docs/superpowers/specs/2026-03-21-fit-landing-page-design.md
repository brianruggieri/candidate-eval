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

### No Changes To

- `baseof.html` — fit pages extend it, override nav block
- `design-system.css` — reuse existing variables (only add `--color-amber: #F59E0B`)
- `hugo.toml` sections array — fit is NOT a homepage section
- Existing layouts, partials, JS — untouched

### Content File Structure

Each assessment is `content/fit/<slug>.md` with all data in front matter:

```yaml
---
title: "Staff Engineer"
company: "Anthropic"
slug: "staff-engineer-anthropic"
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

### Template Layout (single.html)

Seven sections, top to bottom:

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
  - B-range: `#F59E0B` (amber)
  - C and below: `#64748B` (slate)
- Grade letter in center: Saira Extra Condensed, 700, ~5rem

**3. Skill Match Grid**
- 3-column responsive grid (3 → 2 → 1 on mobile)
- Glassmorphic cards with 3px left accent stripe
- Stripe color by status:
  - `strong_match` / `exceeds`: `#89C45A` (green)
  - `partial_match`: `#F59E0B` (amber)
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
# Unlisted fit pages are noindexed individually
# This is belt-and-suspenders for crawlers that ignore meta tags
User-agent: *
Disallow: /fit/
Allow: /fit/$
```
Note: `Allow: /fit/$` permits crawling the index page itself (which only shows public entries).

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
| Partial match / moderate | `#F59E0B` | **New** — add as `--color-amber` |
| Adjacent / neutral | `#8BBAC1` | Existing cyan |
| Gap / growing | `#64748B` | New — slate gray |
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

### List Page (list.html)

A simple card grid at `/fit/` showing only public assessments:
- Each card: company name, role title, grade badge (small), one-line summary
- Links to the full fit page
- If no public pages, show nothing (or a minimal "No public assessments" message)

---

## Repo 2: claude-candidate (CLI Export)

### New Command

`cli.py export-fit <posting-id> [--output-dir PATH]`

**Location:** Add to existing `cli.py` Click group.

**Dependencies:** Reads from `assessments.db` (FitAssessment) and merged profile (MergedEvidenceProfile).

### Behavior

1. Load FitAssessment from DB by posting ID
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
5. Write markdown file to `--output-dir` (default: `../roojerry/content/fit/`)
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
2. Export fit page:    .venv/bin/python -m claude_candidate.cli export-fit <posting-id>
3. Review markdown:    cat ../roojerry/content/fit/<slug>.md
4. (Optional) Set:     public: true
5. Build site:         cd ../roojerry && npm run build
6. Deploy:             (existing GitHub Actions / rsync)
7. Share URL:          roojerry.com/fit/<slug>
```
