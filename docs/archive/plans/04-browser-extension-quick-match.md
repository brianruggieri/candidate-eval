# Plan 04: Browser Extension Quick Match

## Purpose

This plan defines the daily-driver feature of claude-candidate: a browser extension that lets the user assess their fit against any job posting while browsing, with a single click. The assessment is grounded entirely in two evidence sources — the user's actual resume and their Claude Code session logs (via the cached `CandidateProfile`) — and evaluates three equally-weighted dimensions: skill gap analysis, company/mission alignment, and culture fit.

The extension communicates with a local backend server that holds the cached candidate data and performs the matching. No candidate data ever leaves the user's machine or touches any third-party server. The extension itself only extracts job posting text from the current page and sends it to localhost.

## Design Philosophy

### Evidence-Only Assessment

This tool makes one promise: every claim in the fit assessment is traceable to either the user's resume or their Claude Code session logs. There is no self-reported "rate your skill level" input. There is no optimistic interpolation. If the resume says "Python" and the sessions show 200 hours of Python work, that's strong evidence. If the resume says "Kubernetes" but no sessions demonstrate it, the tool flags that discrepancy honestly — the resume claims it, but session evidence doesn't corroborate it.

This dual-source model creates three evidence tiers:
1. **Corroborated**: Both resume and sessions demonstrate the skill. Strongest signal.
2. **Resume-only**: Resume claims it, sessions don't show it. Could mean the skill predates Claude Code usage, or is overstated.
3. **Sessions-only**: Sessions demonstrate it, resume doesn't mention it. Likely an undersold skill — a genuine discovery opportunity.

These tiers are surfaced in the assessment so the user can see where their resume undersells their demonstrated work and where their resume claims lack session backing.

### Three Equal Dimensions

The fit assessment weighs three dimensions equally:

**Skill Gap Analysis (33%)**: Do my demonstrated and credentialed skills match what the posting requires? This is the traditional skills-matching layer, enhanced by session depth evidence.

**Company/Mission Alignment (33%)**: Does what this company builds and cares about connect to what I've actually been building and care about? Measured by overlap between the company's product domain, tech blog themes, and open-source activity against the user's project portfolio and session topics.

**Culture Fit Signals (33%)**: Does how this company works match how I work? Remote vs. office, move-fast vs. careful-architecture, pair-programming vs. solo, open-source-friendly vs. proprietary — these are real compatibility signals detectable from public company information and session behavioral patterns.

The equal weighting is a deliberate design choice. A role where you match 100% on skills but 0% on mission is not a good fit. A role where you love the mission but lack core skills is also not a good fit. The tool should reflect this honestly.

## Architecture Overview

```
┌──────────────────────────────────────────────────────┐
│                    Browser                            │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │              Job Posting Page                    │ │
│  │  (LinkedIn, Greenhouse, Lever, Indeed, etc.)     │ │
│  └──────────────────────┬──────────────────────────┘ │
│                         │                             │
│  ┌──────────────────────▼──────────────────────────┐ │
│  │           Content Script                         │ │
│  │  • Detects job posting pages                     │ │
│  │  • Extracts posting text from DOM                │ │
│  │  • Extracts company name and posting URL         │ │
│  └──────────────────────┬──────────────────────────┘ │
│                         │                             │
│  ┌──────────────────────▼──────────────────────────┐ │
│  │           Extension Popup / Sidebar              │ │
│  │  • Shows fit assessment card                     │ │
│  │  • Watchlist management                          │ │
│  │  • "Generate Full Application" trigger           │ │
│  │  • Settings (backend URL, preferences)           │ │
│  └──────────────────────┬──────────────────────────┘ │
│                         │                             │
└─────────────────────────┼────────────────────────────┘
                          │ HTTP (localhost only)
                          │
┌─────────────────────────▼────────────────────────────┐
│              Local Backend Server                     │
│              (localhost:7429)                         │
│                                                       │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐ │
│  │   Resume     │  │  Candidate   │  │  Company    │ │
│  │   Profile    │  │  Profile     │  │  Enrichment │ │
│  │  (parsed)    │  │  (from logs) │  │  Engine     │ │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘ │
│         │                │                  │         │
│         └────────┬───────┘                  │         │
│                  ▼                          │         │
│         ┌────────────────┐                  │         │
│         │   Merged       │                  │         │
│         │   Evidence     │◄─────────────────┘         │
│         │   Profile      │                            │
│         └───────┬────────┘                            │
│                 ▼                                      │
│         ┌────────────────┐                            │
│         │  Quick Match   │                            │
│         │  Engine        │                            │
│         └───────┬────────┘                            │
│                 ▼                                      │
│         ┌────────────────┐                            │
│         │ Fit Assessment │                            │
│         │ Card JSON      │                            │
│         └────────────────┘                            │
│                                                       │
│  ┌─────────────────────────────────────────────────┐ │
│  │  Persistence Layer                               │ │
│  │  • SQLite: watchlist, assessment history          │ │
│  │  • JSON: cached profiles, company enrichment     │ │
│  └─────────────────────────────────────────────────┘ │
│                                                       │
└───────────────────────────────────────────────────────┘
```

## Component Specifications

### Component 1: Browser Extension

#### Manifest & Permissions (Manifest V3)

```json
{
  "manifest_version": 3,
  "name": "claude-candidate",
  "version": "0.1.0",
  "description": "Honest job fit assessment grounded in your resume and development history",
  "permissions": [
    "activeTab",
    "storage"
  ],
  "host_permissions": [
    "http://localhost:7429/*"
  ],
  "content_scripts": [
    {
      "matches": [
        "*://*.linkedin.com/jobs/*",
        "*://*.greenhouse.io/*",
        "*://*.lever.co/*",
        "*://*.indeed.com/viewjob*",
        "*://*.ashbyhq.com/*",
        "*://*.workday.com/*",
        "*://*.myworkdayjobs.com/*",
        "*://*.smartrecruiters.com/*",
        "*://*.jobs.apple.com/*",
        "*://*.careers.google.com/*",
        "*://boards.greenhouse.io/*"
      ],
      "js": ["content_script.js"],
      "run_at": "document_idle"
    }
  ],
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },
  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  }
}
```

Permissions rationale:
- `activeTab`: Access the current tab's DOM when the user clicks the extension. No background page access, no cross-tab reading.
- `storage`: Persist extension settings (backend URL, display preferences) locally.
- `host_permissions` limited to `localhost:7429`: The extension only talks to the local backend. No external network requests from the extension itself.

#### Content Script: Job Posting Extraction

The content script detects when the user is on a job posting page and extracts the relevant text. Each job board has a different DOM structure, so extraction is site-specific with a generic fallback.

```typescript
// content_script.ts

interface ExtractedPosting {
  title: string;
  company: string;
  location: string | null;
  posting_text: string;
  posting_url: string;
  source: string;          // "linkedin" | "greenhouse" | "lever" | "indeed" | "generic"
  extracted_at: string;    // ISO 8601
  confidence: number;      // 0-1, how confident the extractor is in the result
}

/**
 * Site-specific extractors. Each returns an ExtractedPosting or null.
 * Extractors are ordered by specificity — the first match wins.
 */
const extractors: Record<string, () => ExtractedPosting | null> = {

  linkedin: () => {
    // LinkedIn renders job descriptions in specific containers.
    // The exact selectors change periodically — this is the maintenance cost.
    // Primary targets:
    //   - .jobs-description__content (logged-in job view)
    //   - .description__text (public job view)
    //   - .show-more-less-html__markup (description body)
    // Title: .jobs-unified-top-card__job-title or h1.t-24
    // Company: .jobs-unified-top-card__company-name or a[data-tracking-control-name="public_jobs_topcard-org-name"]
    // Location: .jobs-unified-top-card__bullet

    const descEl = document.querySelector(
      '.jobs-description__content, .description__text, .show-more-less-html__markup'
    );
    const titleEl = document.querySelector(
      '.jobs-unified-top-card__job-title, h1.t-24, h1.topcard__title'
    );
    const companyEl = document.querySelector(
      '.jobs-unified-top-card__company-name a, a[data-tracking-control-name="public_jobs_topcard-org-name"]'
    );

    if (!descEl || !titleEl) return null;

    return {
      title: titleEl.textContent?.trim() || "Unknown Title",
      company: companyEl?.textContent?.trim() || "Unknown Company",
      location: document.querySelector('.jobs-unified-top-card__bullet')?.textContent?.trim() || null,
      posting_text: descEl.textContent?.trim() || "",
      posting_url: window.location.href,
      source: "linkedin",
      extracted_at: new Date().toISOString(),
      confidence: descEl.textContent ? 0.9 : 0.3,
    };
  },

  greenhouse: () => {
    // Greenhouse uses consistent structure: #content for the main posting area
    const descEl = document.querySelector('#content, .content');
    const titleEl = document.querySelector('.app-title, h1.heading');
    const companyEl = document.querySelector('.company-name, span.company-name');

    if (!descEl || !titleEl) return null;

    return {
      title: titleEl.textContent?.trim() || "Unknown Title",
      company: companyEl?.textContent?.trim() || "Unknown Company",
      location: document.querySelector('.location')?.textContent?.trim() || null,
      posting_text: descEl.textContent?.trim() || "",
      posting_url: window.location.href,
      source: "greenhouse",
      extracted_at: new Date().toISOString(),
      confidence: 0.95,
    };
  },

  lever: () => {
    const descEl = document.querySelector('.section-wrapper.page-full-width');
    const titleEl = document.querySelector('.posting-headline h2');
    const companyEl = document.querySelector('.posting-headline .sort-by-time');

    if (!descEl || !titleEl) return null;

    return {
      title: titleEl.textContent?.trim() || "Unknown Title",
      company: companyEl?.textContent?.trim() || window.location.hostname.split('.')[0],
      location: document.querySelector('.posting-categories .sort-by-time')?.textContent?.trim() || null,
      posting_text: descEl.textContent?.trim() || "",
      posting_url: window.location.href,
      source: "lever",
      extracted_at: new Date().toISOString(),
      confidence: 0.95,
    };
  },

  indeed: () => {
    const descEl = document.querySelector('#jobDescriptionText, .jobsearch-JobComponent-description');
    const titleEl = document.querySelector('.jobsearch-JobInfoHeader-title, h1[data-testid="jobsearch-JobInfoHeader-title"]');
    const companyEl = document.querySelector('[data-testid="inlineHeader-companyName"], .jobsearch-InlineCompanyRating-companyHeader');

    if (!descEl || !titleEl) return null;

    return {
      title: titleEl.textContent?.trim() || "Unknown Title",
      company: companyEl?.textContent?.trim() || "Unknown Company",
      location: document.querySelector('[data-testid="inlineHeader-companyLocation"]')?.textContent?.trim() || null,
      posting_text: descEl.textContent?.trim() || "",
      posting_url: window.location.href,
      source: "indeed",
      extracted_at: new Date().toISOString(),
      confidence: 0.9,
    };
  },

  generic: () => {
    // Fallback: look for the largest text block on the page that likely contains
    // a job description. Use heuristics:
    // 1. Find all text containers with >200 words
    // 2. Prefer elements with common job posting keywords
    // 3. Take the largest qualifying block

    const allBlocks = Array.from(document.querySelectorAll('article, main, .content, .job-description, [role="main"], .posting'))
      .filter(el => (el.textContent?.split(/\s+/).length || 0) > 200);

    if (allBlocks.length === 0) return null;

    const best = allBlocks.sort((a, b) =>
      (b.textContent?.length || 0) - (a.textContent?.length || 0)
    )[0];

    const titleEl = document.querySelector('h1');

    return {
      title: titleEl?.textContent?.trim() || document.title,
      company: "Unknown Company",
      location: null,
      posting_text: best.textContent?.trim() || "",
      posting_url: window.location.href,
      source: "generic",
      extracted_at: new Date().toISOString(),
      confidence: 0.5,
    };
  }
};

/**
 * Detect which site we're on and run the appropriate extractor.
 */
function extractJobPosting(): ExtractedPosting | null {
  const hostname = window.location.hostname;

  if (hostname.includes('linkedin.com')) return extractors.linkedin();
  if (hostname.includes('greenhouse.io') || hostname.includes('boards.greenhouse.io')) return extractors.greenhouse();
  if (hostname.includes('lever.co')) return extractors.lever();
  if (hostname.includes('indeed.com')) return extractors.indeed();

  // Try generic fallback for any other job board
  return extractors.generic();
}
```

**Maintenance consideration**: LinkedIn's DOM changes frequently. The content script selectors will need periodic updates. This is the primary maintenance cost of the extension. Mitigations:
- Use multiple fallback selectors (primary, secondary, tertiary)
- Log extraction failures with the failing selector for quick diagnosis
- Version the extractor configs separately from the extension so they can be hot-updated
- The generic fallback ensures partial functionality even when specific extractors break

#### Content Script Test Harness

**This is a required deliverable — not optional.** Content scripts that break silently are the primary risk to the extension's reliability. The test harness validates extraction against saved HTML snapshots.

**Directory**: `extension/test_fixtures/`
```
extension/test_fixtures/
├── linkedin/
│   ├── logged_in_job_view.html       # Full page HTML saved from authenticated LinkedIn
│   ├── public_job_view.html          # Unauthenticated LinkedIn job page
│   └── expected.json                 # Expected ExtractedPosting for each HTML file
├── greenhouse/
│   ├── standard_posting.html
│   └── expected.json
├── lever/
│   ├── standard_posting.html
│   └── expected.json
├── indeed/
│   ├── standard_posting.html
│   └── expected.json
└── generic/
    ├── company_careers_page.html     # A typical company career page (non-standard)
    └── expected.json
```

**How to capture fixtures:**
1. Navigate to a real job posting in a browser
2. Open DevTools → Elements → right-click `<html>` → Copy → Copy outerHTML
3. Save as the appropriate `.html` file
4. Run the extractor against it and verify the output
5. Save verified output as `expected.json`
6. Redact any PII from the saved HTML (email addresses, profile names)

**Test runner** (`extension/test_extractors.ts`):
```typescript
// Uses jsdom to simulate DOM in Node.js
// For each fixture directory:
//   1. Load the HTML into a jsdom Document
//   2. Set window.location.hostname appropriately
//   3. Run extractJobPosting()
//   4. Compare output against expected.json
//   5. Report: pass, fail (with diff), or skip (if fixture missing)
```

**Regression test workflow:**
- Run `npm test` before every extension release
- When a user reports extraction failure on a specific site:
  1. Capture the broken HTML as a new fixture
  2. Add it to the test suite with the *expected* output
  3. Fix the selector until the test passes
  4. The fixture prevents future regressions on that page variant

**Selector health monitoring (v0.3+):**
The extension can optionally report extraction confidence scores (not page content) to a local log. If confidence drops below 0.5 on a known site, the user gets a notification: "Extraction quality may have degraded on LinkedIn — check for extension updates."

#### Extension Popup UI

The popup is the primary UI surface. It shows the fit assessment card, provides manual paste input as a fallback, and offers watchlist management.

**States:**

1. **No backend detected**: Shows setup instructions (how to start the local server).
2. **No profile loaded**: Backend is running but no CandidateProfile or resume has been ingested. Shows onboarding flow.
3. **Not on a job page**: Shows the manual paste interface and recent watchlist.
4. **On a job page, not yet assessed**: Shows the extracted posting title/company with an "Assess Fit" button.
5. **Assessment in progress**: Loading spinner with stage indicators.
6. **Assessment complete**: The fit assessment card (detailed below).

**Technology**: Vanilla HTML/CSS/JS or Preact (lightweight React alternative suitable for extension popups). No heavy framework — the popup must open instantly.

**Popup dimensions**: 400px wide × dynamic height (max 600px with scroll). Standard Chrome extension popup constraints.

#### Extension Sidebar (Alternative View)

For detailed assessment review, the extension can open a sidebar panel (`chrome.sidePanel` API, Manifest V3) that provides more space for the full assessment, comparison view, and watchlist. The popup provides the quick glance; the sidebar provides the deep dive.

### Component 2: Local Backend Server

#### Server Framework & Configuration

```python
# src/claude_candidate/server.py

"""
Local backend server for the claude-candidate browser extension.

Runs on localhost:7429 (mnemonic: "7" looks like a candidate standing,
"429" is HTTP "Too Many Requests" which is what job searching feels like).

No external network binding. Listens on 127.0.0.1 only.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(
    title="claude-candidate",
    description="Local job fit assessment engine",
    version="0.1.0",
)

# CORS: Only allow the browser extension origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "chrome-extension://*",     # Chrome extensions
        "moz-extension://*",        # Firefox extensions
        "http://localhost:7429",     # Local dev
    ],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)
```

#### API Endpoints

```
POST /api/assess
  Body: ExtractedPosting JSON
  Returns: FitAssessment JSON
  Description: The primary endpoint. Receives a job posting, runs quick match,
               returns fit assessment. Triggers company enrichment if not cached.

POST /api/assess/paste
  Body: { "text": "...", "company": "...", "title": "...", "url": "..." }
  Returns: FitAssessment JSON
  Description: Manual paste fallback. Same logic as /assess but accepts
               raw text instead of ExtractedPosting.

GET /api/profile/status
  Returns: { "has_resume": bool, "has_candidate_profile": bool,
             "profile_session_count": int, "profile_last_updated": datetime,
             "resume_last_updated": datetime }
  Description: Extension checks this to determine which UI state to show.

POST /api/profile/resume
  Body: Resume file (PDF or DOCX, multipart upload)
  Returns: ResumeProfile JSON
  Description: Ingest and parse the user's resume.

POST /api/profile/update
  Body: { "session_paths": [...] }
  Returns: { "status": "updating", "estimated_minutes": int }
  Description: Trigger a CandidateProfile rebuild from session logs.
               Runs asynchronously; extension polls /profile/status.

GET /api/watchlist
  Returns: List of saved FitAssessments with metadata
  Description: Retrieve all watchlisted job postings.

POST /api/watchlist
  Body: { "assessment_id": "..." }
  Returns: { "status": "saved" }
  Description: Add an assessment to the watchlist.

DELETE /api/watchlist/{assessment_id}
  Returns: { "status": "removed" }

GET /api/watchlist/compare
  Query: ?ids=id1,id2,id3
  Returns: Comparison matrix JSON
  Description: Side-by-side comparison of multiple assessments.

POST /api/generate-application
  Body: { "assessment_id": "..." }
  Returns: { "status": "started", "run_id": "..." }
  Description: Triggers the full pipeline (Plan 02) for a specific posting.
               Runs asynchronously. Returns the run_id for status polling.

GET /api/generate-application/{run_id}/status
  Returns: Pipeline progress and deliverable links when complete.

GET /api/health
  Returns: { "status": "ok", "version": "0.1.0" }
  Description: Health check for extension connectivity detection.
```

#### Server Startup

```bash
# Start the backend
claude-candidate server start

# Start with custom port
claude-candidate server start --port 7429

# Start in background (daemon mode)
claude-candidate server start --daemon

# Stop background server
claude-candidate server stop
```

The server auto-discovers the cached CandidateProfile and ResumeProfile from `~/.claude-candidate/` on startup. If neither exists, it runs in "onboarding mode" — all assessment endpoints return a helpful error directing the user to ingest their resume and build their profile first.

### Component 3: Resume Profile

#### Why Resume Alongside Session Logs

Session logs capture recent, demonstrated work — but they don't capture everything. Skills from previous roles, formal education, certifications, years of experience at a technology, and career narrative all live in the resume. The dual-source model uses both:

- **Resume**: What the candidate claims, with the authority of their professional history
- **Sessions**: What the candidate demonstrably does, with the precision of observed behavior

Where they agree, confidence is highest. Where they diverge, the divergence itself is informative.

#### ResumeProfile Schema

```python
class ResumeSkill(BaseModel):
    """A skill extracted from the resume."""

    name: str
    # Canonical name, normalized to match SkillEntry naming conventions.

    source_context: str
    # Where on the resume this skill appeared.
    # Example: "Listed in Skills section", "Mentioned in Senior Engineer role at Acme Corp",
    # "Described in project: Distributed Data Pipeline"

    implied_depth: DepthLevel
    # Depth inferred from resume context:
    # - Listed in skills section without context → "used"
    # - Described in a role with specific accomplishments → "applied" or "deep"
    # - Featured in multiple roles or as a primary technology → "deep" or "expert"

    years_experience: float | None = None
    # If the resume provides explicit years, capture it. None otherwise.

    recency: Literal["current_role", "previous_role", "historical", "unknown"]
    # How recently the resume indicates this skill was used.


class ResumeRole(BaseModel):
    """A role/position extracted from the resume."""

    title: str
    company: str
    start_date: str        # "YYYY-MM" or "YYYY"
    end_date: str | None   # None if current role
    duration_months: int | None

    description: str
    # Brief summary of the role as described on the resume.

    technologies: list[str]
    # Technologies mentioned in this role's description.

    achievements: list[str]
    # Quantified achievements or key accomplishments.

    domain: str | None
    # Business domain: "fintech", "developer-tooling", "e-commerce", etc.


class ResumeProfile(BaseModel):
    """
    Structured representation of the user's resume.

    Parsed from PDF or DOCX upload. All data comes directly from
    the resume — no inference beyond normalizing skill names and
    estimating depth from context.
    """

    # === Metadata ===
    profile_version: str = "0.1.0"
    parsed_at: datetime
    source_file_hash: str     # SHA-256 of the uploaded resume file
    source_format: str        # "pdf" or "docx"

    # === Identity (minimal, user-controlled) ===
    name: str | None = None
    current_title: str | None = None
    location: str | None = None

    # === Experience ===
    roles: list[ResumeRole]
    total_years_experience: float | None = None

    # === Skills ===
    skills: list[ResumeSkill]
    # All skills mentioned anywhere on the resume, deduplicated and normalized.

    # === Education ===
    education: list[str]
    # Degree descriptions. Example: "B.S. Computer Science, MIT, 2018"

    # === Certifications ===
    certifications: list[str]

    # === Summary ===
    professional_summary: str | None = None
    # If the resume has a summary/objective section, capture it verbatim.
```

#### Resume Parsing Pipeline

```python
def parse_resume(file_path: Path) -> ResumeProfile:
    """
    Parse a resume file into a ResumeProfile.

    Supported formats: PDF, DOCX, TXT.

    Pipeline:
    1. Extract text from file (pdfplumber for PDF, python-docx for DOCX, direct read for TXT)
    2. Send extracted text to Claude Code for structured parsing
    3. Claude extracts roles, skills, education, certifications
    4. Normalize skill names to canonical form (matching SkillEntry conventions)
    5. Estimate depth for each skill based on context
    6. Validate against ResumeProfile schema
    7. Persist to ~/.claude-candidate/resume_profile.json
    """
    ...
```

#### Resume Text Extraction — Multi-Format Handling

**PDF extraction (pdfplumber):**
```python
def extract_text_from_pdf(path: Path) -> str:
    """
    Extract text from PDF, handling common resume layouts.

    Strategy:
    1. Try pdfplumber's default text extraction (works for ~80% of resumes)
    2. If result is mostly empty or garbled, try page-by-page with layout=True
    3. If the PDF has tables (common for skills sections), extract tables separately
       and merge with body text
    4. Strip excess whitespace while preserving paragraph boundaries

    Known limitations:
    - Image-only PDFs (scanned resumes) require OCR — not supported in v0.1.
      If detected (zero text extracted), return an error message directing
      the user to upload a text-based PDF or DOCX.
    - Multi-column layouts may interleave columns. pdfplumber handles most
      two-column layouts correctly, but three-column or creative designs may
      produce garbled text. The Claude parsing step is robust to some garbling.
    - Headers/footers repeat on each page — deduplicate before sending to parser.
    """
    import pdfplumber

    full_text = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                full_text.append(text)
            # Also extract tables on this page
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row:
                        full_text.append(" | ".join(cell or "" for cell in row))

    result = "\n\n".join(full_text)
    if not result.strip():
        raise ValueError(
            "No text could be extracted from this PDF. "
            "It may be image-only (scanned). Please upload a text-based PDF or DOCX."
        )
    return result
```

**DOCX extraction (python-docx):**
```python
def extract_text_from_docx(path: Path) -> str:
    """
    Extract text from DOCX, preserving structure.

    Extracts paragraphs, tables, and header/footer text.
    DOCX is generally more reliable than PDF for text extraction
    because the text layer is explicit.
    """
    from docx import Document

    doc = Document(str(path))
    parts = []

    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)

    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    return "\n\n".join(parts)
```

#### Resume Parsing Prompt

The extracted text is sent to Claude Code with the following structured prompt. This prompt is the core of resume parsing quality and should be iterated on with real resumes.

```markdown
# Resume Parsing Task

You are parsing a resume into a structured JSON format. Extract ONLY what is explicitly stated in the resume — do not infer, hallucinate, or add information that isn't present.

## Input
The following text was extracted from a resume document:

<resume_text>
{extracted_text}
</resume_text>

## Output Format
Respond with ONLY a JSON object matching this exact structure. No preamble, no markdown fencing, no explanation.

{
  "name": "Full name or null if not found",
  "current_title": "Most recent job title or null",
  "location": "Location if mentioned or null",
  "professional_summary": "Summary/objective section text verbatim, or null",
  "roles": [
    {
      "title": "Job Title",
      "company": "Company Name",
      "start_date": "YYYY-MM or YYYY",
      "end_date": "YYYY-MM or YYYY or null if current",
      "duration_months": null,
      "description": "2-3 sentence summary of the role's responsibilities",
      "technologies": ["lowercase-tech-names"],
      "achievements": ["Achievement bullet points, keep quantified where possible"],
      "domain": "industry-domain or null"
    }
  ],
  "total_years_experience": null,
  "skills": [
    {
      "name": "lowercase-canonical-name",
      "source_context": "Where/how this skill appears on the resume",
      "implied_depth": "mentioned|used|applied|deep|expert",
      "years_experience": null,
      "recency": "current_role|previous_role|historical|unknown"
    }
  ],
  "education": ["Degree, Institution, Year"],
  "certifications": ["Certification Name, Issuer"]
}

## Skill Name Normalization Rules
- Always lowercase, hyphenated for multi-word: "machine-learning", "test-driven-development"
- Use canonical names: "python" not "Python 3.x", "typescript" not "TS"
- Frameworks by standard name: "react" not "React.js", "fastapi" not "FastAPI"
- Map common variations: "JS" → "javascript", "K8s" → "kubernetes"

## Depth Assessment Rules
- "mentioned": Listed in a skills section with no context
- "used": Mentioned in a role but without specific accomplishments
- "applied": Specific work described using this technology
- "deep": Multiple roles using it, OR specific deep accomplishments (optimization, architecture)
- "expert": Primary focus across career, OR notable achievements (led adoption, built frameworks)

## Recency Rules
- "current_role": Appears in the most recent / current position
- "previous_role": Appears in the second-most-recent position
- "historical": Appears only in older positions
- "unknown": Listed in skills section without role association
```

**Prompt quality validation:** After implementing, test with at least 5 real resumes of varying formats (simple, multi-column, creative, academic CV, ATS-optimized) and manually verify the output. Document misparses and adjust the prompt. This is an iterative process.

The resume is parsed once and cached. The user can re-upload at any time to update. The `source_file_hash` enables detecting when the source file has changed.

### Component 4: Merged Evidence Profile

The quick match engine doesn't operate on the CandidateProfile or ResumeProfile separately — it operates on a merged view that combines both sources and tracks provenance.

```python
class EvidenceSource(str, Enum):
    RESUME_ONLY = "resume_only"           # Claimed on resume, not demonstrated in sessions
    SESSIONS_ONLY = "sessions_only"       # Demonstrated in sessions, not on resume
    CORROBORATED = "corroborated"         # Both resume and sessions agree
    CONFLICTING = "conflicting"           # Resume and sessions give different depth signals


class MergedSkillEvidence(BaseModel):
    """A skill with evidence from both resume and session logs."""

    name: str
    source: EvidenceSource

    # Resume evidence
    resume_depth: DepthLevel | None = None
    resume_context: str | None = None
    resume_years: float | None = None

    # Session evidence
    session_depth: DepthLevel | None = None
    session_frequency: int | None = None
    session_evidence_count: int | None = None
    session_recency: datetime | None = None

    # Merged assessment
    effective_depth: DepthLevel
    # The depth used for matching. Logic:
    # - corroborated: max(resume_depth, session_depth) — both sources agree, use strongest
    # - resume_only: resume_depth, but flagged as unverified
    # - sessions_only: session_depth — demonstrated is stronger than claimed
    # - conflicting: session_depth (observed behavior > self-report)

    confidence: float
    # 0.0–1.0. Based on source type and evidence quality.
    # corroborated + high frequency → 0.9–1.0
    # resume_only with vague context → 0.3–0.5
    # sessions_only with single session → 0.4–0.6
    # sessions_only with high frequency → 0.8–0.9

    discovery_flag: bool = False
    # True if this skill is sessions_only — indicates the resume undersells this skill.
    # The UI highlights these as "Skills your resume doesn't mention."


class MergedEvidenceProfile(BaseModel):
    """
    Combined view of resume and session evidence.

    This is the primary input to the quick match engine. It provides
    a single, deduplicated skill list with provenance tracking and
    merged depth assessments.
    """

    skills: list[MergedSkillEvidence]
    patterns: list[ProblemSolvingPattern]    # From CandidateProfile (sessions only)
    projects: list[ProjectSummary]           # From CandidateProfile (sessions only)
    roles: list[ResumeRole]                  # From ResumeProfile (resume only)

    # Aggregate stats
    corroborated_skill_count: int
    resume_only_skill_count: int
    sessions_only_skill_count: int
    discovery_skills: list[str]              # Skills the resume should probably mention

    profile_hash: str                        # Hash of the merged profile for cache invalidation
    resume_hash: str                         # Source resume file hash
    candidate_profile_hash: str              # Source CandidateProfile manifest hash
    merged_at: datetime


def merge_profiles(
    candidate_profile: CandidateProfile,
    resume_profile: ResumeProfile,
) -> MergedEvidenceProfile:
    """
    Merge CandidateProfile and ResumeProfile into a unified evidence view.

    Algorithm:
    1. Collect all unique skill names from both sources
    2. For each skill:
       a. Check presence in resume skills
       b. Check presence in session skills
       c. Classify as corroborated, resume_only, sessions_only, or conflicting
       d. Compute effective_depth and confidence
    3. Carry over patterns and projects from CandidateProfile
    4. Carry over roles from ResumeProfile
    5. Compute aggregate statistics
    6. Identify discovery skills (sessions_only with depth >= "applied")
    """
    ...
```

### Component 5: Company Enrichment Engine

When a job posting is assessed, the backend automatically enriches it with public company information.

```python
class CompanyProfile(BaseModel):
    """Public information about a company, used for mission and culture assessment."""

    company_name: str
    company_url: str | None = None

    # === Mission & Product ===
    mission_statement: str | None = None
    # From the company's about page or mission page.

    product_description: str
    # What the company builds. 2-3 sentences.

    product_domain: list[str]
    # Domain tags: "developer-tooling", "fintech", "healthcare", "ai-infrastructure", etc.

    # === Engineering Culture ===
    engineering_blog_url: str | None = None
    recent_blog_topics: list[str]
    # Titles/themes of the last 5-10 engineering blog posts. Rich culture signal.

    tech_stack_public: list[str]
    # Technologies mentioned on the engineering blog, careers page, or GitHub.

    github_org_url: str | None = None
    public_repos_count: int | None = None
    primary_languages_github: list[str]
    # Languages most used across public repos.

    oss_activity_level: Literal["very_active", "active", "minimal", "none", "unknown"]
    # Based on public repo count, commit frequency, and whether they publish OSS projects.

    # === Work Style ===
    remote_policy: Literal["remote_first", "hybrid", "in_office", "unknown"]
    company_size: str | None = None    # "startup", "growth", "enterprise", or employee count
    funding_stage: str | None = None   # "seed", "series_a", "series_b", "public", etc.

    # === Signals ===
    culture_keywords: list[str]
    # Extracted from careers page, about page, and blog.
    # Examples: "open source", "move fast", "customer obsession", "remote-first",
    #           "pair programming", "documentation culture"

    red_flags: list[str]
    # Potentially concerning signals. Examples:
    # "47 open engineering roles with 200 total employees"
    # "No engineering blog posts in 18 months"
    # "Primary product pivot announced 2 months ago"

    # === Metadata ===
    enriched_at: datetime
    sources: list[str]     # URLs that were fetched to build this profile
    enrichment_quality: Literal["rich", "moderate", "sparse"]
    # rich: multiple sources available. moderate: some gaps. sparse: minimal public info.


class CompanyEnrichmentEngine:
    """
    Fetches and structures public company information.

    Sources (in priority order):
    1. Company website (about page, careers page, team page)
    2. Company engineering blog
    3. Company GitHub organization
    4. Recent news (via web search)

    All fetches are standard HTTP GET requests to public URLs.
    Results are cached in ~/.claude-candidate/company_cache/ with a 7-day TTL.
    """

    CACHE_TTL_DAYS = 7
    CACHE_DIR = Path.home() / ".claude-candidate" / "company_cache"

    async def enrich(self, company_name: str, company_url: str | None = None) -> CompanyProfile:
        """
        Build a CompanyProfile from public sources.

        Steps:
        1. Check cache (by normalized company name)
        2. If cached and fresh, return cached profile
        3. If not cached or stale:
           a. Resolve company website URL (from posting URL domain or web search)
           b. Fetch and parse about/mission page
           c. Fetch and parse careers/team page
           d. Discover and fetch engineering blog
           e. Discover GitHub org and fetch repo metadata
           f. Search recent news
           g. Send all fetched content to Claude Code for structured extraction
           h. Cache and return
        """
        ...

    async def discover_company_url(self, company_name: str) -> str | None:
        """
        Find the company's primary website URL.

        Strategy: web search "{company_name} official site" and take the
        first non-job-board, non-social-media result.
        """
        ...

    async def discover_engineering_blog(self, company_url: str) -> str | None:
        """
        Find the company's engineering blog.

        Strategy: check common paths (/blog, /engineering, /tech-blog, /eng)
        and web search "{company_name} engineering blog".
        """
        ...

    async def discover_github_org(self, company_name: str) -> str | None:
        """
        Find the company's GitHub organization.

        Strategy: web search "site:github.com {company_name}" and verify
        the org matches (not a user account or unrelated repo).
        """
        ...
```

### Component 6: Quick Match Engine

The core matching logic that produces fit assessments.

```python
class DimensionScore(BaseModel):
    """Score for a single fit dimension."""

    dimension: Literal["skill_match", "mission_alignment", "culture_fit"]
    score: float              # 0.0–1.0
    grade: str                # "A", "B+", "B", "C+", "C", "D", "F"
    weight: float = 0.333     # Equal weighting
    summary: str              # 2-3 sentence explanation
    details: list[str]        # Supporting points, 3-5 items


class SkillMatchDetail(BaseModel):
    """Detailed skill-by-skill match result."""

    requirement: str              # From job posting
    priority: str                 # must_have, strong_preference, nice_to_have
    match_status: str             # strong_match, partial_match, adjacent, no_evidence, exceeds
    candidate_evidence: str       # Brief evidence summary
    evidence_source: EvidenceSource   # Where the evidence comes from
    confidence: float


class FitAssessment(BaseModel):
    """
    The complete fit assessment for a job posting.

    This is the primary output of the quick match engine and the
    data model rendered in the extension popup/sidebar.
    """

    # === Identification ===
    assessment_id: str             # UUID
    assessed_at: datetime

    job_title: str
    company_name: str
    posting_url: str | None
    source: str                    # "linkedin", "greenhouse", etc.

    # === Overall Score ===
    overall_score: float           # 0.0–1.0, weighted average of dimensions
    overall_grade: str             # Letter grade
    overall_summary: str           # 3-4 sentence holistic assessment

    # === Dimension Scores ===
    skill_match: DimensionScore
    mission_alignment: DimensionScore
    culture_fit: DimensionScore

    # === Skill Detail ===
    skill_matches: list[SkillMatchDetail]
    must_have_coverage: str        # "5/7 must-haves met"
    strongest_match: str           # Single strongest skill overlap
    biggest_gap: str               # Single biggest gap

    # === Discovery ===
    resume_gaps_discovered: list[str]
    # Skills demonstrated in sessions but missing from resume that are relevant to this role.
    # Actionable: "Consider adding X to your resume — you've demonstrated it in Y sessions."

    resume_unverified: list[str]
    # Resume skills relevant to this role that have no session corroboration.
    # Informational: "Your resume claims X but your sessions don't demonstrate it."

    # === Company Context ===
    company_profile_summary: str   # 2-3 sentence company description
    company_enrichment_quality: str

    # === Actionability ===
    should_apply: Literal["strong_yes", "yes", "maybe", "probably_not", "no"]
    # Blunt recommendation based on overall fit.

    action_items: list[str]
    # 2-4 concrete next steps. Examples:
    # "Strong fit — generate full application"
    # "Update resume to include TypeScript (demonstrated in 23 sessions)"
    # "Research their recent pivot to AI infrastructure before applying"
    # "Gap in Kubernetes — consider a quick project to build evidence"

    # === Metadata ===
    profile_hash: str              # MergedEvidenceProfile hash used
    time_to_assess_seconds: float  # Performance tracking


class QuickMatchEngine:
    """
    Produces FitAssessments by comparing a MergedEvidenceProfile
    against a parsed job posting and enriched company profile.
    """

    def __init__(self, merged_profile: MergedEvidenceProfile):
        self.profile = merged_profile

    async def assess(
        self,
        posting: ExtractedPosting,
        company_profile: CompanyProfile | None = None,
    ) -> FitAssessment:
        """
        Run the three-dimensional fit assessment.

        1. Parse the job posting into lightweight requirements
           (faster than full JobRequirements — optimized for quick match)
        2. Score skill_match dimension
        3. Score mission_alignment dimension
        4. Score culture_fit dimension
        5. Compute overall score and grade
        6. Generate actionable recommendations
        7. Identify resume gaps and unverified claims
        """
        ...

    def _score_skill_match(
        self,
        requirements: list[QuickRequirement],
    ) -> DimensionScore:
        """
        Score skill gap analysis.

        For each requirement:
        1. Find matching MergedSkillEvidence entries
        2. Assess depth match
        3. Weight by requirement priority (must_have = 3x, strong_pref = 2x, nice_to_have = 1x)
        4. Factor in evidence source (corroborated > sessions_only > resume_only)
        5. Compute weighted coverage score

        Score bands:
        0.9–1.0 → A  (exceeds or matches nearly all requirements)
        0.8–0.9 → B+ (strong match with minor gaps)
        0.7–0.8 → B  (good match with some gaps)
        0.6–0.7 → C+ (moderate match, notable gaps)
        0.5–0.6 → C  (partial match, significant gaps)
        0.3–0.5 → D  (weak match, major gaps)
        0.0–0.3 → F  (fundamental misalignment)
        """
        ...

    def _score_mission_alignment(
        self,
        posting_text: str,
        company_profile: CompanyProfile | None,
    ) -> DimensionScore:
        """
        Score company/mission alignment.

        Signals:
        1. Product domain overlap: does the company build things in domains
           the candidate has worked in? (From projects and roles)
        2. Technology philosophy overlap: does the company use/value the same
           technologies the candidate is deep in?
        3. Open source alignment: if the candidate has strong OSS activity
           and the company values OSS, that's a positive signal
        4. Problem space interest: do the candidate's session topics suggest
           genuine interest in the problems this company solves?

        If no company_profile is available, this dimension is scored
        based on posting text alone (lower confidence).
        """
        ...

    def _score_culture_fit(
        self,
        posting_text: str,
        company_profile: CompanyProfile | None,
    ) -> DimensionScore:
        """
        Score culture/working style fit.

        Compares company culture signals against candidate behavioral patterns:

        Company signal → Candidate evidence
        ─────────────────────────────────────────────────────────
        "move fast"     → iterative_refinement pattern frequency
        "quality first" → testing_instinct, documentation_driven
        "collaborative" → communication_clarity, teaching evidence
        "autonomous"    → scope_management, meta_cognition
        "open source"   → public repos, OSS contribution patterns
        "documentation" → documentation_driven pattern
        "pair programming" → communication style, teaching evidence
        "remote"        → async communication patterns in sessions

        Also considers:
        - Seniority alignment (candidate experience vs. role level)
        - Team size fit (startup vs. enterprise experience)
        - Domain transition friction (moving between industries)
        """
        ...
```

### Component 7: Persistence Layer

```python
"""
Local persistence for assessments, watchlist, and cached data.

Uses SQLite for structured data (assessments, watchlist) and
JSON files for profiles and company cache.

All data stored in ~/.claude-candidate/
"""

# Directory structure:
# ~/.claude-candidate/
# ├── candidate_profile.json       # Cached CandidateProfile
# ├── resume_profile.json          # Parsed ResumeProfile
# ├── merged_profile.json          # Cached MergedEvidenceProfile
# ├── resume_source.pdf            # Copy of uploaded resume
# ├── assessments.db               # SQLite: assessments and watchlist
# ├── company_cache/               # Cached CompanyProfiles (JSON, 7-day TTL)
# │   ├── acme_corp.json
# │   └── ...
# └── pipeline_output/             # Full pipeline run outputs
#     └── {run_id}/
#         └── ...

# SQLite schema:
"""
CREATE TABLE assessments (
    id TEXT PRIMARY KEY,
    job_title TEXT NOT NULL,
    company_name TEXT NOT NULL,
    posting_url TEXT,
    source TEXT,
    overall_score REAL NOT NULL,
    overall_grade TEXT NOT NULL,
    skill_score REAL NOT NULL,
    mission_score REAL NOT NULL,
    culture_score REAL NOT NULL,
    should_apply TEXT NOT NULL,
    assessment_json TEXT NOT NULL,     -- Full FitAssessment JSON
    assessed_at TEXT NOT NULL,
    watchlisted INTEGER DEFAULT 0,
    watchlisted_at TEXT,
    applied INTEGER DEFAULT 0,
    applied_at TEXT,
    notes TEXT                         -- User's personal notes
);

CREATE TABLE assessment_tags (
    assessment_id TEXT REFERENCES assessments(id),
    tag TEXT NOT NULL
);

CREATE INDEX idx_assessments_watchlisted ON assessments(watchlisted);
CREATE INDEX idx_assessments_score ON assessments(overall_score DESC);
CREATE INDEX idx_assessments_company ON assessments(company_name);
"""
```

### Component 8: Watchlist & Comparison

The watchlist is a saved set of assessments the user is interested in tracking.

```python
class WatchlistEntry(BaseModel):
    """A watchlisted job posting with assessment."""

    assessment: FitAssessment
    watchlisted_at: datetime
    notes: str | None = None
    tags: list[str] = []         # User-defined tags: "top_pick", "reach", "safety", etc.
    applied: bool = False
    applied_at: datetime | None = None


class ComparisonMatrix(BaseModel):
    """
    Side-by-side comparison of multiple job postings.

    Used in the extension sidebar to help the user decide between
    multiple opportunities.
    """

    assessments: list[FitAssessment]

    # Comparison dimensions
    overall_ranking: list[str]        # Assessment IDs sorted by overall_score
    skill_ranking: list[str]          # Sorted by skill_match score
    mission_ranking: list[str]        # Sorted by mission_alignment score
    culture_ranking: list[str]        # Sorted by culture_fit score

    common_gaps: list[str]
    # Skills that are gaps across ALL compared postings — high priority to address.

    unique_strengths: dict[str, list[str]]
    # Per-assessment strengths that don't appear in others.
    # Key: assessment_id, Value: unique strength descriptions.

    recommendation: str
    # 3-5 sentence comparative analysis. "Based on your profile, Role X at Company A
    # is the strongest overall fit because... However, Role Y at Company B has better
    # mission alignment if you prioritize working in developer tooling."
```

## Extension UI Specification

### Fit Assessment Card (Popup)

The card is the primary UI element. It must communicate the assessment clearly in a 400px-wide popup.

```
┌──────────────────────────────────────────┐
│  claude-candidate                    [⚙] │
├──────────────────────────────────────────┤
│                                          │
│  Acme Corp                               │
│  Senior AI Engineer                      │
│  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│                                          │
│  Overall: B+  (0.83)                     │
│  ████████████████░░░░                    │
│                                          │
│  Skills     ████████████████████░  A-    │
│  Mission    ██████████████░░░░░░░  B     │
│  Culture    █████████████████░░░░  B+    │
│                                          │
│  ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄  │
│                                          │
│  ✓ Must-haves: 5/7 met                  │
│  ★ Strongest: Multi-agent orchestration  │
│  △ Gap: Kubernetes, Go                   │
│                                          │
│  💡 2 skills your resume doesn't mention │
│     but your sessions demonstrate         │
│                                          │
│  Verdict: STRONG YES — Apply             │
│                                          │
│  ┌──────────────┐ ┌─────────────────┐   │
│  │ 📋 Watchlist │ │ 📄 Full App    │   │
│  └──────────────┘ └─────────────────┘   │
│                                          │
│  [View Details ↗]                        │
│                                          │
└──────────────────────────────────────────┘
```

### Sidebar Detail View

The sidebar expands on the popup card with:
- Full skill-by-skill match breakdown with evidence source indicators
- Company profile section (mission, blog themes, tech stack, culture signals)
- Resume gap discoveries (actionable suggestions)
- Comparison tab (if 2+ items are watchlisted)
- History of all assessed postings

### Color Coding

```
Grade colors (background tints):
A  range → green    (#22c55e / 15% opacity)
B  range → blue     (#3b82f6 / 15% opacity)
C  range → yellow   (#eab308 / 15% opacity)
D  range → orange   (#f97316 / 15% opacity)
F         → red     (#ef4444 / 15% opacity)

Evidence source indicators:
● Corroborated  → solid green dot
◐ Sessions only → half-filled blue dot
○ Resume only   → hollow orange dot
⚠ Conflicting   → warning yellow triangle
```

## CLI Integration

Plan 04 adds these commands to the existing CLI:

```bash
# Server management
claude-candidate server start [--port 7429] [--daemon]
claude-candidate server stop
claude-candidate server status

# Resume management
claude-candidate resume ingest /path/to/resume.pdf
claude-candidate resume status
claude-candidate resume update /path/to/updated_resume.pdf

# Profile merging (after CandidateProfile and ResumeProfile both exist)
claude-candidate profile merge
claude-candidate profile status

# Quick match (CLI alternative to browser extension)
claude-candidate match --posting job.txt [--company-url https://acme.com]
claude-candidate match --url https://boards.greenhouse.io/acme/jobs/12345

# Watchlist
claude-candidate watchlist list [--sort score|date|company]
claude-candidate watchlist compare id1 id2 id3
claude-candidate watchlist export [--format json|csv|md]
```

## Implementation Tasks

### Task 1: ResumeProfile Schema & Parser
**Files**: `src/claude_candidate/schemas/resume_profile.py`, `src/claude_candidate/resume_parser.py`
- Implement Pydantic models for ResumeProfile, ResumeSkill, ResumeRole
- Implement PDF text extraction (pdfplumber)
- Implement DOCX text extraction (python-docx)
- Implement Claude Code-based structured parsing of resume text
- Implement skill name normalization (canonical form matching SkillEntry)
- Tests with sample resume fixtures

### Task 2: MergedEvidenceProfile
**Files**: `src/claude_candidate/schemas/merged_profile.py`, `src/claude_candidate/merger.py`
- Implement MergedSkillEvidence and MergedEvidenceProfile schemas
- Implement merge_profiles() algorithm
- Implement evidence source classification
- Implement confidence scoring
- Implement discovery skill detection
- Tests: merge with overlapping skills, disjoint skills, conflicting depths

### Task 3: Company Enrichment Engine
**File**: `src/claude_candidate/enrichment.py`
- Implement CompanyProfile schema
- Implement URL discovery (company site, engineering blog, GitHub org)
- Implement content fetching and parsing
- Implement structured extraction via Claude Code
- Implement caching with TTL
- Tests with known companies (Anthropic, Vercel, etc.)

### Task 4: Quick Match Engine
**File**: `src/claude_candidate/quick_match.py`
- Implement FitAssessment, DimensionScore, SkillMatchDetail schemas
- Implement three scoring dimensions
- Implement overall score computation and grading
- Implement action item generation
- Implement resume gap detection
- Tests: assess against sample job postings with known expected scores

### Task 5: Local Backend Server
**File**: `src/claude_candidate/server.py`
- Implement FastAPI application with all endpoints
- Implement CORS for extension origins
- Implement profile auto-discovery on startup
- Implement async assessment pipeline
- Implement health check and status endpoints
- Tests: endpoint integration tests

### Task 6: Persistence Layer
**Files**: `src/claude_candidate/storage.py`
- Implement SQLite schema and migrations
- Implement assessment CRUD operations
- Implement watchlist operations
- Implement comparison matrix generation
- Implement company cache management
- Tests: storage round-trips, watchlist operations, cache expiry

### Task 7: Browser Extension — Content Scripts
**Directory**: `extension/`
- Implement manifest.json (Manifest V3)
- Implement content_script.ts with all site-specific extractors
- Implement extractor fallback chain
- Implement extraction confidence scoring
- Tests: mock DOM extraction for each supported site

### Task 8: Browser Extension — Popup UI
**Files**: `extension/popup.html`, `extension/popup.js`, `extension/popup.css`
- Implement all popup states (no backend, no profile, not on job page, assessing, complete)
- Implement fit assessment card rendering
- Implement watchlist quick-add
- Implement "Generate Full Application" trigger
- Implement settings panel (backend URL configuration)

### Task 9: Browser Extension — Sidebar
**Files**: `extension/sidebar.html`, `extension/sidebar.js`
- Implement detailed assessment view
- Implement skill-by-skill breakdown with evidence indicators
- Implement company profile section
- Implement comparison tab
- Implement assessment history view

### Task 10: End-to-End Integration
- Full flow: install extension → start server → ingest resume → build profile → assess job posting → watchlist → compare → generate application
- Performance testing: assessment should complete in under 30 seconds
- Extension installation testing on Chrome and Firefox
- Error handling: backend down, malformed posting, enrichment failure

### Latency Budget

The 30-second target breaks down as follows:

```
Phase                          Target     Notes
────────────────────────────────────────────────────────────
Content script extraction      <100ms     DOM queries only, no network
Extension → backend POST       <50ms      Localhost, no network hop
Job text parsing               <500ms     Regex/keyword extraction (v0.1)
                                          Claude Code call (v0.2): +5-15s
Company enrichment (cached)    <10ms      SQLite/JSON cache hit
Company enrichment (uncached)  5-20s      Network fetch + Claude parse
                                          — ASYNC, show partial results while running
Profile merge (if needed)      <50ms      In-memory computation
Quick match scoring            <100ms     Pure computation, no I/O
FitAssessment serialization    <10ms      JSON serialization
Backend → extension response   <50ms      Localhost
────────────────────────────────────────────────────────────
Total (cached company)         <1s        Typical case for repeat companies
Total (uncached company)       5-20s      First assessment for a new company
Total (v0.2 with Claude parse) 10-30s     When Claude Code parses requirements
```

**Progressive loading strategy:**

The extension popup should NOT wait for the full assessment. Instead, show results incrementally:

1. **T+0ms**: "Analyzing posting..." — show extracted title/company immediately
2. **T+500ms**: Show skill dimension score (available from local matching)
3. **T+1s**: If company cached, show all three dimensions. If not: show skill score + "Enriching company data..."
4. **T+5-20s**: Company enrichment completes → update mission and culture scores
5. **Final**: Full assessment card with all three dimensions

This means the user sees *something useful* within 1 second for most assessments. The mission/culture dimensions may update asynchronously for new companies, but the skill dimension (which is the most actionable) is always fast.

**Implementation pattern:**
```typescript
// Extension popup
const result = await fetch('http://localhost:7429/api/assess', { body: posting });
const data = await result.json();

// If enrichment is still running, poll for updates
if (data.enrichment_status === 'pending') {
  showPartialCard(data);
  const poll = setInterval(async () => {
    const updated = await fetch(`http://localhost:7429/api/assess/${data.assessment_id}`);
    const updatedData = await updated.json();
    updateCard(updatedData);
    if (updatedData.enrichment_status === 'complete') clearInterval(poll);
  }, 2000);
}
```

## Acceptance Criteria

1. Extension installs cleanly on Chrome (Manifest V3) and extracts job postings from LinkedIn, Greenhouse, Lever, and Indeed.
2. Generic fallback extractor works on arbitrary job pages with >50% accuracy.
3. Local backend starts in under 3 seconds and serves assessments in under 30 seconds.
4. Resume ingestion correctly parses PDF and DOCX formats into structured ResumeProfile.
5. Profile merge correctly identifies corroborated, resume-only, sessions-only, and conflicting skills.
6. Company enrichment fetches and structures data from company websites, blogs, and GitHub orgs.
7. Fit assessment produces scores across all three dimensions with evidence-backed explanations.
8. Watchlist persists across server restarts (SQLite).
9. Comparison view produces meaningful differentiation between 2-5 watchlisted postings.
10. No candidate data leaves localhost. Extension only sends job posting text to the local backend.
11. "Generate Full Application" correctly triggers the full pipeline from Plans 01-03.
12. Assessment card renders correctly in the 400px popup constraint.

## Dependencies

### Backend
- Python 3.11+
- fastapi + uvicorn (server)
- pydantic >= 2.0 (schemas)
- pdfplumber (PDF parsing)
- python-docx (DOCX parsing)
- httpx (async HTTP for enrichment)
- sqlite3 (standard library, persistence)
- click (CLI)
- Claude Code CLI (structured extraction and matching)

### Extension
- TypeScript (compiled to JS for extension)
- No framework for popup (vanilla or Preact for minimal bundle)
- Chrome Extension Manifest V3 APIs
- No external dependencies shipped with extension

## Security & Privacy Considerations

1. **The extension has minimal permissions.** `activeTab` + `storage` + localhost access only. It cannot read arbitrary tabs, access browsing history, or make external network requests.

2. **Job posting text flows one way**: from the browser to localhost. The backend never pushes data to the extension beyond assessment results.

3. **Company enrichment uses public data only.** All fetched URLs are public websites, public GitHub repos, and public search results. No authentication, no login, no scraping behind walls.

4. **All candidate data stays in `~/.claude-candidate/`.** The backend binds to 127.0.0.1 only. No external access.

5. **The extension does not phone home.** No analytics, no telemetry, no update checks to external servers.

## Future Enhancements (Post v1)

- **Firefox support**: Manifest V3 is supported but some APIs differ. Budget a compatibility pass.
- **Auto-detection of new postings**: Monitor job board feeds and auto-assess new postings matching saved search criteria.
- **Salary correlation**: If salary data is available (Levels.fyi, Glassdoor), surface compensation context alongside fit.
- **Application tracking**: Track the full lifecycle: assessed → watchlisted → applied → interview → offer. Turn the watchlist into a lightweight ATS.
- **Team sharing mode**: Share anonymized fit assessments with career coaches or mentors for feedback.
- **Bookmarklet fallback**: For users who don't want to install an extension, a bookmarklet that sends the current page's text to localhost.

## Notes for Agent Team Lead

This plan is the user-facing surface of the entire project. Everything in Plans 01-03 is infrastructure that this plan makes visible and useful. Prioritize accordingly:

1. **The popup card must feel instant.** If assessment takes 30 seconds, show a meaningful loading state with progressive information (company detected, enrichment running, matching skills...). Never show a blank spinner.

2. **Content script maintenance is the long-term cost.** LinkedIn changes their DOM regularly. Build the extractor architecture to make updating selectors trivial — a config file, not a code change. The generic fallback is the safety net.

3. **The merged evidence profile is the key innovation.** The dual-source (resume + sessions) model with provenance tracking is what makes this tool different from every other job matching service. The discovery skills feature ("your resume doesn't mention TypeScript but you've used it in 23 sessions") is the highest-value insight the tool produces. Make it prominent.

4. **Company enrichment quality varies wildly.** Anthropic has a great engineering blog. A 20-person startup might have nothing. Design the UI to degrade gracefully — mission and culture scores should have lower confidence when enrichment is sparse, and the UI should communicate this.

5. **The "Generate Full Application" button bridges Plans 01-04.** It's the on-ramp from casual browsing to committed application. The handoff from FitAssessment to the full pipeline (carrying over the parsed job requirements and company context) should be seamless — no re-entry of information.
