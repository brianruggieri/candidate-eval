# v0.5 User Flow Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the assessment pipeline from a single-pipeline (assess → generate deliverables) to a three-phase user flow (browse & grade → shortlist → generate & deploy), as defined in the grill session at `.claude/grill-me-user-flow-2026-03-19.md`.

**Architecture:** The extension popup shows a weighted percentage from three locally-scorable dimensions (skills, experience, education). In the background, two parallel Claude calls run: company research (cached per company) and AI engineering scoring. When both complete, mission/culture grades are computed locally from company research, and Claude generates a narrative verdict + receptivity signal. The popup updates in-place with a letter grade — no new tab. Deliverable generation is a separate CLI action triggered later from a shortlist. Generated pages auto-deploy to Cloudflare Pages via wrangler.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, Jinja2, Tailwind CSS (CDN), wrangler CLI (Cloudflare), Chrome Extension MV3

**Decision log:** `.claude/grill-me-user-flow-2026-03-19.md` (9 confirmed decisions)

**Builds on:** Completed delivery layer (Tasks 1-6 of `2026-03-18-v04-delivery-layer.md`). All existing infrastructure (PII gate, message format, site renderer, templates) is reused and modified.

---

## Dependency Graph

```
Phase A (parallel — no dependencies):
  Task 1: Enrich extraction prompt
  Task 2: Company research module
  Task 3: Rename watchlist → shortlist

Phase B (depends on Task 1):
  Task 4: Experience + education scoring dimensions
  Task 5: Partial assessment returns weighted %

Phase C (depends on Tasks 2, 4, 5):
  Task 6: Full assessment pipeline (separate from generation)
  Task 7: Narrative verdict + receptivity signal

Phase D (depends on Tasks 3, 6, 7 — parallel within phase):
  Task 8: Extension popup refactor (depends on 3, 6, 7)
  Task 9: Cover letter site template + CLI generate + deploy (depends on 3, 6, 7)
  Task 10: CLI shortlist command (depends on 3)
```

---

## File Structure

**New files:**
- `src/claude_candidate/company_research.py` — Company research Claude call + per-company caching
- `src/claude_candidate/templates/cover_letter_site.html` — New cover letter site page template
- `tests/test_company_research.py`

**Modified files:**
- `src/claude_candidate/server.py` — Enrich extraction, refactor /assess/full, add /research/company, rename watchlist endpoints
- `src/claude_candidate/schemas/job_requirements.py` — Add years_experience, education to QuickRequirement
- `src/claude_candidate/schemas/fit_assessment.py` — New dimensions, partial_percentage, narrative, receptivity
- `src/claude_candidate/schemas/merged_profile.py` — Add total_years_experience and education fields
- `src/claude_candidate/merger.py` — Propagate years/education from ResumeProfile to merged profile
- `src/claude_candidate/quick_match.py` — Experience + education scoring, partial % computation
- `src/claude_candidate/storage.py` — Rename watchlist → shortlist with migration, add salary/location/grade columns, add company_research cache
- `src/claude_candidate/site_renderer.py` — New render function for cover letter site page
- `src/claude_candidate/generator.py` — Add narrative generation, separate from deliverable generation
- `src/claude_candidate/cli.py` — Add shortlist command, refactor generate command + wrangler deploy, add null guards for optional dimensions
- `extension/popup.html` — Remove new tab button, add shortlist view, update dimension display
- `extension/popup.js` — Remove new tab flow, show % for partial, letter grade for full, clipboard button
- `extension/popup.css` — Updated styles for new layout
- `extension/background.js` — Refactor full assessment flow (no deliverables), pass enriched requirements to assessPartial
- `tests/test_server.py` — Update for new endpoints and response shapes
- `tests/test_quick_match.py` — Add experience/education dimension tests
- `tests/test_storage.py` — Add shortlist and company research cache tests
- `tests/test_site_renderer.py` — Add cover letter site template tests

---

### Task 1: Enrich Extraction Prompt with Structured Requirements

**Phase:** A (no dependencies, can run immediately)

**Files:**
- Modify: `src/claude_candidate/server.py:502-517` (`_build_extraction_prompt`)
- Modify: `src/claude_candidate/server.py:74-83` (`PostingExtraction` model)
- Modify: `src/claude_candidate/server.py:541-565` (response parsing in `extract_posting`)
- Modify: `src/claude_candidate/schemas/job_requirements.py:86-98` (`QuickRequirement`)
- Test: `tests/test_server.py`

**What:** The existing Claude extraction call at `/api/extract-posting` already parses company/title/description. Enrich it to also extract structured requirements — each with skill, years_experience, education_level, and priority. This gives the local scorer rich data to match against without adding a second Claude call.

- [ ] **Step 1: Update QuickRequirement schema**

Add `years_experience` and `education_level` fields to `QuickRequirement`:

```python
# src/claude_candidate/schemas/job_requirements.py
class QuickRequirement(BaseModel):
    description: str
    skill_mapping: list[str] = Field(min_length=1)
    priority: RequirementPriority
    source_text: str = ""
    years_experience: int | None = None  # NEW
    education_level: str | None = None  # NEW: "bachelor", "master", "phd", etc.
```

- [ ] **Step 2: Write failing test for enriched extraction**

```python
# tests/test_server.py
async def test_extract_posting_returns_structured_requirements(app_with_profile):
    async with AsyncClient(...) as client:
        resp = await client.post("/api/extract-posting", json={
            "url": "https://example.com/job",
            "title": "Senior AI Engineer",
            "text": "Requirements: 5+ years Python, MS in CS preferred, experience with LLMs...",
        })
        data = resp.json()
        assert "requirements" in data
        assert len(data["requirements"]) > 0
        req = data["requirements"][0]
        assert "skill_mapping" in req
        assert "priority" in req
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_server.py::test_extract_posting_returns_structured_requirements -v`
Expected: FAIL — `requirements` key not in response

- [ ] **Step 4: Update PostingExtraction model**

Add `requirements` field to `PostingExtraction` in `server.py`:

```python
class PostingExtraction(BaseModel):
    company: str = ""
    title: str = ""
    description: str = ""
    url: str = ""
    source: str = "web"
    location: str | None = None
    seniority: str | None = None
    remote: bool | None = None
    salary: str | None = None
    requirements: list[dict] | None = None  # NEW
```

- [ ] **Step 5: Update extraction prompt**

Modify `_build_extraction_prompt()` in `server.py` to also request structured requirements:

```python
def _build_extraction_prompt(title: str, text: str) -> str:
    truncated = text[:MAX_EXTRACTION_TEXT]
    return (
        "Extract the job posting from this web page text. "
        "Return ONLY valid JSON with these fields:\n"
        '- company: string (the hiring company name)\n'
        '- title: string (the job title)\n'
        '- description: string (full job description)\n'
        '- location: string or null\n'
        '- seniority: string or null (one of: junior, mid, senior, staff, principal, director)\n'
        '- remote: boolean or null\n'
        '- salary: string or null\n'
        '- requirements: array of objects, each with:\n'
        '  - description: string (the requirement as stated)\n'
        '  - skill_mapping: array of strings (normalized skill names)\n'
        '  - priority: string (one of: must_have, strong_preference, nice_to_have, implied)\n'
        '  - years_experience: integer or null (years required, e.g. 5 for "5+ years")\n'
        '  - education_level: string or null (one of: bachelor, master, phd, or null)\n\n'
        "Extract every requirement, qualification, and preferred skill as a separate requirement object. "
        "If this page does not contain a job posting, return all fields as null.\n\n"
        f"Page title: {title}\n"
        f"Page text:\n{truncated}"
    )
```

- [ ] **Step 6: Update response parsing in extract_posting**

Parse `requirements` from Claude response and include in `PostingExtraction`:

```python
result = PostingExtraction(
    company=parsed.get("company") or "",
    title=parsed.get("title") or "",
    description=parsed.get("description") or "",
    url=req.url,
    source=source,
    location=parsed.get("location"),
    seniority=parsed.get("seniority"),
    remote=parsed.get("remote"),
    salary=parsed.get("salary"),
    requirements=parsed.get("requirements"),  # NEW
)
```

- [ ] **Step 7: Update _run_quick_assess to prefer enriched requirements**

In `server.py`, update the requirement building logic (~line 246-250) to use enriched requirements from the extraction if available:

```python
if req.requirements:
    requirements = [QuickRequirement(**r) for r in req.requirements]
else:
    requirements = _extract_basic_requirements(req.posting_text)
```

This already exists — `req.requirements` now comes from the enriched extraction passed by the extension.

- [ ] **Step 8: Run tests, fix breakage**

Run: `pytest tests/test_server.py -v`
Expected: All pass including new test

- [ ] **Step 9: Commit**

```bash
git add src/claude_candidate/schemas/job_requirements.py src/claude_candidate/server.py tests/test_server.py
git commit -m "Enrich extraction prompt with structured requirements"
```

---

### Task 2: Company Research Module

**Phase:** A (no dependencies, can run in parallel with Task 1)

**Files:**
- Create: `src/claude_candidate/company_research.py`
- Create: `tests/test_company_research.py`
- Modify: `src/claude_candidate/storage.py` (add company_research_cache table)
- Test: `tests/test_storage.py`

**What:** New module that calls Claude to research a company's mission, values, culture, and tech philosophy. Results are cached per company name so multiple postings at the same company don't trigger redundant research. This runs in the background parallel to AI engineering scoring.

- [ ] **Step 1: Add company research cache table to storage**

Write failing test:

```python
# tests/test_storage.py
async def test_company_research_cache_roundtrip(store):
    data = {"mission": "Build AI tools", "values": ["transparency"]}
    await store.cache_company_research("anthropic", data)
    cached = await store.get_cached_company_research("anthropic")
    assert cached is not None
    assert cached["mission"] == "Build AI tools"

async def test_company_research_cache_miss(store):
    cached = await store.get_cached_company_research("nonexistent")
    assert cached is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_storage.py::test_company_research_cache_roundtrip -v`

- [ ] **Step 3: Implement storage methods**

Add to `storage.py` in the `initialize()` method:

```python
await self._conn.execute("""
    CREATE TABLE IF NOT EXISTS company_research (
        company_key TEXT PRIMARY KEY,
        company_name TEXT NOT NULL,
        data TEXT NOT NULL,
        researched_at TEXT DEFAULT (datetime('now'))
    )
""")
```

Add methods:

```python
async def cache_company_research(self, company_name: str, data: dict) -> None:
    key = company_name.strip().lower()
    await self._conn.execute(
        "INSERT OR REPLACE INTO company_research (company_key, company_name, data) VALUES (?, ?, ?)",
        (key, company_name, json.dumps(data)),
    )
    await self._conn.commit()

async def get_cached_company_research(self, company_name: str) -> dict | None:
    key = company_name.strip().lower()
    row = await self._conn.execute_fetchone(
        "SELECT data, researched_at FROM company_research WHERE company_key = ? "
        "AND (julianday('now') - julianday(researched_at)) * 86400 < ?",
        (key, 30 * 86400),  # 30-day TTL
    )
    if row is None:
        return None
    return json.loads(row[0])
```

- [ ] **Step 4: Run storage tests**

Run: `pytest tests/test_storage.py -v`

- [ ] **Step 5: Write company research module**

Write failing test:

```python
# tests/test_company_research.py
from unittest.mock import patch

def test_research_company_returns_structured_data():
    mock_response = '{"mission": "Build safe AI", "values": ["safety", "transparency"], "culture_signals": ["remote-first"], "tech_philosophy": "Research-driven", "ai_native": true}'
    with patch("claude_candidate.claude_cli.call_claude", return_value=mock_response):
        from claude_candidate.company_research import research_company
        result = research_company("Anthropic")
        assert result["mission"] == "Build safe AI"
        assert "safety" in result["values"]
        assert result["ai_native"] is True
```

- [ ] **Step 6: Run test to verify it fails**

Run: `pytest tests/test_company_research.py::test_research_company_returns_structured_data -v`

- [ ] **Step 7: Implement company_research.py**

```python
"""Company research via Claude CLI. Results cached per company."""

from __future__ import annotations

import json

import claude_candidate.claude_cli as _claude_cli


def _build_research_prompt(company_name: str) -> str:
    return (
        f"Research the company '{company_name}' and return ONLY valid JSON with:\n"
        "- mission: string (company mission statement or core purpose)\n"
        "- values: array of strings (stated or inferred company values)\n"
        "- culture_signals: array of strings (work style indicators: remote, async, etc.)\n"
        "- tech_philosophy: string (how they approach technology and engineering)\n"
        "- ai_native: boolean (true if the company builds with or on AI as a core part of their product)\n"
        "- product_domains: array of strings (what domains their products serve)\n"
        "- team_size_signal: string or null (startup, growth, enterprise, unknown)\n\n"
        "Base your response on publicly available information. "
        "If you cannot find information about this company, return reasonable inferences "
        "from the company name with lower confidence."
    )


def research_company(company_name: str, *, timeout: int = 60) -> dict:
    """Call Claude to research a company. Returns structured dict."""
    prompt = _build_research_prompt(company_name)
    raw = _claude_cli.call_claude(prompt, timeout=timeout)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    return json.loads(cleaned.strip())
```

- [ ] **Step 8: Run tests**

Run: `pytest tests/test_company_research.py -v`

- [ ] **Step 9: Commit**

```bash
git add src/claude_candidate/company_research.py src/claude_candidate/storage.py tests/test_company_research.py tests/test_storage.py
git commit -m "Add company research module with per-company caching"
```

---

### Task 3: Rename Watchlist to Shortlist + Add Fields

**Phase:** A (no dependencies, can run in parallel with Tasks 1 and 2)

**Files:**
- Modify: `src/claude_candidate/storage.py` (rename table, add columns)
- Modify: `src/claude_candidate/server.py` (rename endpoints and models)
- Test: `tests/test_storage.py`, `tests/test_server.py`

**What:** Rename the watchlist concept to shortlist throughout. Add salary, location, and overall_grade columns. The shortlist is a holding pen for jobs the user wants to generate materials for later.

- [ ] **Step 1: Write failing tests for shortlist storage**

```python
# tests/test_storage.py
async def test_add_to_shortlist_with_salary_and_location(store):
    sid = await store.add_to_shortlist(
        company_name="Anthropic",
        job_title="AI Engineer",
        posting_url="https://example.com",
        salary="200-250k",
        location="Remote",
        overall_grade="B+",
    )
    assert sid > 0
    items = await store.list_shortlist()
    assert len(items) == 1
    assert items[0]["salary"] == "200-250k"
    assert items[0]["location"] == "Remote"
    assert items[0]["overall_grade"] == "B+"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py::test_add_to_shortlist_with_salary_and_location -v`

- [ ] **Step 3: Update storage.py with migration**

Add migration logic in `initialize()` to rename existing `watchlist` table if present, then create new schema. Rename all methods from `*_watchlist` to `*_shortlist`. Add `salary`, `location`, `overall_grade` parameters:

```python
# Migration: rename existing watchlist table to shortlist
async with self._conn.execute(
    "SELECT name FROM sqlite_master WHERE type='table' AND name='watchlist'"
) as cursor:
    if await cursor.fetchone():
        await self._conn.execute("ALTER TABLE watchlist RENAME TO shortlist")
        # Add new columns to migrated table
        for col in ["salary TEXT", "location TEXT", "overall_grade TEXT"]:
            try:
                await self._conn.execute(f"ALTER TABLE shortlist ADD COLUMN {col}")
            except Exception:
                pass  # Column already exists
        # Update default status from 'watching' to 'shortlisted'
        await self._conn.execute(
            "UPDATE shortlist SET status = 'shortlisted' WHERE status = 'watching'"
        )
        await self._conn.commit()

# Create table for fresh installs
await self._conn.execute("""
    CREATE TABLE IF NOT EXISTS shortlist (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT NOT NULL,
        job_title TEXT NOT NULL,
        posting_url TEXT,
        assessment_id TEXT REFERENCES assessments(assessment_id),
        salary TEXT,
        location TEXT,
        overall_grade TEXT,
        notes TEXT,
        status TEXT NOT NULL DEFAULT 'shortlisted',
        added_at TEXT DEFAULT (datetime('now'))
    )
""")
await self._conn.execute(
    "CREATE INDEX IF NOT EXISTS idx_shortlist_status ON shortlist(status)"
);
```

Rename methods: `add_to_watchlist` → `add_to_shortlist`, `list_watchlist` → `list_shortlist`, `update_watchlist` → `update_shortlist`, `remove_from_watchlist` → `remove_from_shortlist`.

- [ ] **Step 4: Run storage tests, fix breakage**

Run: `pytest tests/test_storage.py -v`
Fix any tests still referencing watchlist methods.

- [ ] **Step 5: Update server.py models and endpoints**

Rename `WatchlistAddRequest` → `ShortlistAddRequest`, add `salary`, `location`, `overall_grade` fields.
Rename `WatchlistUpdateRequest` → `ShortlistUpdateRequest`.
Rename endpoints: `/api/watchlist` → `/api/shortlist`.
Update handler function names.

- [ ] **Step 6: Update server tests**

Rename all watchlist references in `tests/test_server.py` to shortlist.

- [ ] **Step 7: Run all tests**

Run: `pytest tests/test_server.py tests/test_storage.py -v`

- [ ] **Step 8: Commit**

```bash
git add src/claude_candidate/storage.py src/claude_candidate/server.py tests/test_storage.py tests/test_server.py
git commit -m "Rename watchlist to shortlist, add salary/location/grade fields"
```

---

### Task 4: Experience + Education Scoring Dimensions

**Phase:** B (depends on Task 1 — needs enriched requirements with years_experience)

**Files:**
- Modify: `src/claude_candidate/schemas/merged_profile.py` (add total_years_experience, education fields)
- Modify: `src/claude_candidate/merger.py` (propagate years/education from ResumeProfile)
- Modify: `src/claude_candidate/quick_match.py` (add two new scoring methods)
- Modify: `src/claude_candidate/schemas/fit_assessment.py` (expand DimensionScore literal)
- Test: `tests/test_quick_match.py`, `tests/test_merger.py`

**What:** Add two new locally-scorable dimensions to the QuickMatchEngine: experience match (years required vs. candidate years) and education/tech stack match (degree requirements + tech stack overlap). These, together with the existing skill_match, form the partial assessment percentage.

**Prerequisites:** `MergedEvidenceProfile` currently has no `total_years_experience` or `education` fields — those live on `ResumeProfile` only. This task must first propagate them through the merger before the scoring methods can reference `self.profile.total_years_experience`.

- [ ] **Step 0: Add total_years_experience and education to MergedEvidenceProfile**

Add fields to `MergedEvidenceProfile` in `schemas/merged_profile.py`:

```python
# src/claude_candidate/schemas/merged_profile.py
class MergedEvidenceProfile(BaseModel):
    # ... existing fields ...
    total_years_experience: float | None = None  # NEW: from ResumeProfile
    education: list[str] = Field(default_factory=list)  # NEW: from ResumeProfile
```

Update `merge_profiles()` in `merger.py` to propagate from `ResumeProfile`:

```python
# In merge_profiles(), after building the merged profile:
merged.total_years_experience = resume.total_years_experience
merged.education = resume.education
```

Update `merge_candidate_only()` to leave them as None/empty (no resume data available).

Write test in `tests/test_merger.py`:

```python
def test_merged_profile_has_years_and_education():
    merged = merge_profiles(candidate, resume)
    assert merged.total_years_experience == resume.total_years_experience
    assert merged.education == resume.education
```

Run: `pytest tests/test_merger.py -v`

- [ ] **Step 1: Update DimensionScore to accept new dimension names**

```python
# src/claude_candidate/schemas/fit_assessment.py
class DimensionScore(BaseModel):
    dimension: Literal[
        "skill_match", "experience_match", "education_match",
        "mission_alignment", "culture_fit",
    ]
    # ... rest unchanged
```

- [ ] **Step 2: Write failing tests for experience scoring**

```python
# tests/test_quick_match.py
def test_experience_match_sufficient_years():
    """Candidate with 12 years vs. requirement of 5+ years should score high."""
    # Build a MergedEvidenceProfile with total_years_experience=12
    # Build requirements with years_experience=5
    # Score should be >= 0.8

def test_experience_match_insufficient_years():
    """Candidate with 2 years vs. requirement of 10+ years should score low."""

def test_experience_match_no_requirement():
    """When no years are specified in requirements, score neutral."""
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_quick_match.py::test_experience_match_sufficient_years -v`

- [ ] **Step 4: Implement _score_experience_match**

Add to `QuickMatchEngine` in `quick_match.py`:

```python
def _score_experience_match(
    self,
    requirements: list[QuickRequirement],
    seniority: str,
) -> DimensionScore:
    """Score experience alignment: candidate years vs. required years."""
    # Collect all years_experience values from requirements
    required_years = [r.years_experience for r in requirements if r.years_experience]

    if not required_years:
        return DimensionScore(
            dimension="experience_match",
            score=0.5,  # Neutral when no years specified
            grade=score_to_grade(0.5),
            summary="No specific experience requirements stated.",
            details=["No years of experience specified in posting."],
            insufficient_data=True,
        )

    max_required = max(required_years)
    candidate_years = self.profile.total_years_experience or 0

    if candidate_years >= max_required:
        ratio = min(candidate_years / max_required, 1.5) / 1.5
        score = 0.7 + (ratio * 0.3)  # 0.7-1.0 range
    else:
        ratio = candidate_years / max_required
        score = ratio * 0.7  # 0.0-0.7 range

    # Also check per-requirement years alignment
    details = []
    for r in requirements:
        if r.years_experience:
            met = candidate_years >= r.years_experience
            details.append(
                f"{'Met' if met else 'Gap'}: {r.description} "
                f"(requires {r.years_experience}+ yrs, have {candidate_years})"
            )

    return DimensionScore(
        dimension="experience_match",
        score=round(score, 3),
        grade=score_to_grade(score),
        summary=f"{'Meets' if candidate_years >= max_required else 'Below'} experience requirement: {candidate_years} yrs vs. {max_required}+ required.",
        details=details[:5] or ["Experience comparison completed."],
    )
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_quick_match.py -v`

- [ ] **Step 6: Write failing tests for education scoring**

```python
def test_education_match_degree_met():
    """Candidate with MS vs. requirement of bachelor should score high."""

def test_education_match_tech_stack_overlap():
    """High tech stack overlap between posting and candidate should boost score."""

def test_education_match_no_requirements():
    """When no education specified, score based on tech stack overlap only."""
```

- [ ] **Step 7: Implement _score_education_match**

Add to `QuickMatchEngine`:

```python
def _score_education_match(
    self,
    requirements: list[QuickRequirement],
    tech_stack: list[str] | None,
) -> DimensionScore:
    """Score education/tech stack alignment."""
    details = []
    score_components = []

    # Education requirements from enriched requirements
    edu_reqs = [r for r in requirements if r.education_level]
    if edu_reqs:
        DEGREE_RANK = {"bachelor": 1, "master": 2, "phd": 3}
        candidate_edu = self.profile.education or []
        candidate_max_rank = 0
        for edu in candidate_edu:
            edu_lower = edu.lower()
            if "phd" in edu_lower or "doctorate" in edu_lower:
                candidate_max_rank = max(candidate_max_rank, 3)
            elif "master" in edu_lower or "ms " in edu_lower or "m.s." in edu_lower:
                candidate_max_rank = max(candidate_max_rank, 2)
            elif "bachelor" in edu_lower or "bs " in edu_lower or "b.s." in edu_lower:
                candidate_max_rank = max(candidate_max_rank, 1)

        max_required_rank = max(DEGREE_RANK.get(r.education_level, 0) for r in edu_reqs)
        if candidate_max_rank >= max_required_rank:
            score_components.append(1.0)
            details.append(f"Education requirement met.")
        elif candidate_max_rank > 0:
            score_components.append(0.5)
            details.append(f"Partial education match.")
        else:
            score_components.append(0.2)
            details.append(f"Education requirement not clearly met.")

    # Tech stack overlap
    if tech_stack:
        candidate_skills = {s.name for s in self.profile.skills}
        overlap = set(s.lower() for s in tech_stack) & candidate_skills
        if tech_stack:
            tech_ratio = len(overlap) / len(tech_stack)
            score_components.append(tech_ratio)
            details.append(f"Tech stack overlap: {len(overlap)}/{len(tech_stack)} technologies matched.")

    if not score_components:
        return DimensionScore(
            dimension="education_match",
            score=0.5,
            grade=score_to_grade(0.5),
            summary="No specific education or tech stack requirements.",
            details=["No education requirements specified."],
            insufficient_data=True,
        )

    score = sum(score_components) / len(score_components)
    return DimensionScore(
        dimension="education_match",
        score=round(score, 3),
        grade=score_to_grade(score),
        summary=f"Education/tech stack match: {score_to_grade(score)}.",
        details=details[:5],
    )
```

- [ ] **Step 8: Run tests**

Run: `pytest tests/test_quick_match.py -v`

- [ ] **Step 9: Commit**

```bash
git add src/claude_candidate/quick_match.py src/claude_candidate/schemas/fit_assessment.py src/claude_candidate/schemas/merged_profile.py src/claude_candidate/merger.py tests/test_quick_match.py tests/test_merger.py
git commit -m "Add experience and education scoring dimensions for partial assessment"
```

---

### Task 5: Partial Assessment Returns Weighted Percentage

**Phase:** B (depends on Task 4)

**Files:**
- Modify: `src/claude_candidate/schemas/fit_assessment.py` (add partial fields)
- Modify: `src/claude_candidate/quick_match.py` (`assess()` method)
- Modify: `src/claude_candidate/server.py` (`_run_quick_assess`, `/api/assess/partial`)
- Test: `tests/test_quick_match.py`, `tests/test_server.py`

**What:** The partial assessment computes a weighted percentage from three local dimensions (skills, experience, education) instead of the old three-dimension letter grade. The `FitAssessment` schema gets new fields to distinguish partial from full. Mission and culture scores are omitted from the partial result.

- [ ] **Step 1: Update FitAssessment schema**

```python
# src/claude_candidate/schemas/fit_assessment.py
class FitAssessment(BaseModel):
    # ... existing identification fields ...

    # Assessment phase
    assessment_phase: Literal["partial", "full"] = "partial"  # NEW

    # Partial dimensions (locally scored)
    partial_percentage: float | None = None  # NEW: 0-100 weighted %
    skill_match: DimensionScore
    experience_match: DimensionScore | None = None  # NEW
    education_match: DimensionScore | None = None  # NEW

    # Full dimensions (Claude-powered, None until full assessment)
    mission_alignment: DimensionScore | None = None  # Changed: now optional
    culture_fit: DimensionScore | None = None  # Changed: now optional

    # Overall (letter grade only populated on full)
    overall_score: float = Field(ge=0.0, le=1.0)
    overall_grade: str
    overall_summary: str

    # Full-only fields
    narrative_verdict: str | None = None  # NEW
    receptivity_level: Literal["high", "medium", "low"] | None = None  # NEW
    receptivity_reason: str | None = None  # NEW

    # ... rest unchanged ...
```

- [ ] **Step 2: Write failing test for partial percentage**

```python
def test_partial_assessment_returns_percentage():
    """Partial assessment should return partial_percentage 0-100, no mission/culture."""
    engine = QuickMatchEngine(merged_profile)
    result = engine.assess(requirements=reqs, company="Test", title="Eng")
    assert result.partial_percentage is not None
    assert 0 <= result.partial_percentage <= 100
    assert result.assessment_phase == "partial"
    assert result.mission_alignment is None
    assert result.culture_fit is None
```

- [ ] **Step 3: Run test to verify it fails**

- [ ] **Step 4: Update QuickMatchEngine.assess()**

Modify the `assess()` method to:
1. Score three local dimensions: skill_match, experience_match, education_match
2. Compute weighted percentage: skills 50%, experience 30%, education 20%
3. Set `assessment_phase = "partial"`
4. Set `partial_percentage` from weighted average
5. Set `overall_score` from partial percentage (divided by 100)
6. Do NOT compute mission_alignment or culture_fit (leave as None)
7. Set `overall_grade` from the partial score

- [ ] **Step 5: Update _run_quick_assess in server.py**

Pass `tech_stack` and `culture_signals` through to the engine but don't use them for partial scoring. Ensure the response includes `partial_percentage` and `assessment_phase`.

- [ ] **Step 6: Run all tests, fix breakage**

Run: `pytest tests/ -v`

Making `mission_alignment` and `culture_fit` optional will break many call sites beyond tests. All of these need null guards:

- `quick_match.py`: `SummaryInput` dataclass requires `mission_dim` and `culture_dim` — make optional
- `quick_match.py`: `_compute_overall_score()` — handle None dimensions in weighted average
- `quick_match.py`: `_generate_summary()` — skip mission/culture when None
- `cli.py`: `_print_rich_card()` and `_print_plain_card()` — guard `.score` access
- `cli.py`: any `assessment.mission_alignment.grade` references — guard with `if assessment.mission_alignment`
- `templates/assessment.html`: the `{% for dim in [assessment.skill_match, assessment.mission_alignment, assessment.culture_fit] %}` loop — filter out None values
- `proof_generator.py`: dimension score table — skip None dimensions

Update each to handle the optional case gracefully. For partial assessments, omit mission/culture from summaries and output entirely.

- [ ] **Step 7: Commit**

```bash
git add src/claude_candidate/schemas/fit_assessment.py src/claude_candidate/quick_match.py src/claude_candidate/server.py tests/
git commit -m "Partial assessment returns weighted percentage from local dimensions only"
```

---

### Task 6: Full Assessment Pipeline (Separate from Generation)

**Phase:** C (depends on Tasks 2, 4, 5)

**Files:**
- Modify: `src/claude_candidate/server.py` (refactor `/api/assess/full`)
- Modify: `src/claude_candidate/quick_match.py` (add full scoring method)
- Test: `tests/test_server.py`

**What:** `/api/assess/full` no longer generates deliverables. Instead, it: (1) runs company research (from cache or Claude), (2) runs AI engineering scoring in parallel, (3) computes mission/culture from company research locally, (4) merges all dimensions into a final letter grade. Deliverable generation moves to a separate endpoint/CLI command.

- [ ] **Step 1: Write failing test for refactored full assessment**

```python
async def test_assess_full_returns_grade_not_deliverables(app_with_profile):
    """Full assessment should return letter grade and narrative, NOT deliverables."""
    # First create a partial assessment
    partial = await client.post("/api/assess/partial", json={...})
    aid = partial.json()["assessment_id"]

    # Run full assessment
    full = await client.post("/api/assess/full", json={"assessment_id": aid})
    data = full.json()

    assert data["assessment_phase"] == "full"
    assert data["overall_grade"] in ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]
    assert data["mission_alignment"] is not None
    assert data["culture_fit"] is not None
    assert data["narrative_verdict"] is not None
    assert data["receptivity_level"] in ["high", "medium", "low"]
    assert "deliverables" not in data  # No deliverables!
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Refactor /api/assess/full endpoint**

Replace the current implementation (which generates deliverables) with:

```python
@app.post("/api/assess/full")
async def assess_full(req: AssessFullRequest):
    store = get_store()
    row = await store.get_assessment(req.assessment_id)
    if not row:
        raise HTTPException(404, "Assessment not found")

    assessment_data = row["data"] if "data" in row else row
    company = assessment_data.get("company_name", "")

    import asyncio

    # Run company research and AI scoring in parallel
    loop = asyncio.get_event_loop()

    async def get_company_research():
        cached = await store.get_cached_company_research(company)
        if cached:
            return cached
        from claude_candidate.company_research import research_company
        result = await loop.run_in_executor(None, lambda: research_company(company))
        await store.cache_company_research(company, result)
        return result

    async def get_ai_score():
        # AI engineering scoring uses compute_ai_engineering_score(messages)
        # which requires NormalizedMessage list, not a profile.
        # The AI score was already computed during session extraction and
        # stored in the CandidateProfile. Load it from the profile data.
        from claude_candidate.ai_scoring import compute_ai_engineering_score
        profiles = get_profiles()
        candidate = profiles.get("candidate")
        if not candidate:
            return None
        # If AI scores were pre-computed during profile build, return them.
        # Otherwise, return None — session messages aren't stored at assessment time.
        ai_data = candidate.get("ai_engineering_scores")
        return ai_data

    research, ai_score = await asyncio.gather(
        get_company_research(),
        get_ai_score(),
    )

    # Compute mission/culture locally from company research
    # Merge all dimensions into final letter grade
    # Generate narrative verdict + receptivity signal (see Task 7)
    # Update assessment in store
    # Return updated assessment
```

- [ ] **Step 4: Add /api/generate as the deliverable generation endpoint**

The existing `/api/generate` endpoint already generates individual deliverables — it stays as-is. Remove deliverable generation from `/api/assess/full` only.

- [ ] **Step 5: Run tests, fix breakage**

Run: `pytest tests/test_server.py -v`
Update any tests that expected deliverables from `/api/assess/full`.

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/server.py tests/test_server.py
git commit -m "Separate full assessment from deliverable generation"
```

---

### Task 7: Narrative Verdict + Receptivity Signal

**Phase:** C (depends on Task 6)

**Files:**
- Modify: `src/claude_candidate/generator.py` (add narrative generation)
- Modify: `src/claude_candidate/server.py` (wire narrative into full assessment)
- Test: `tests/test_generator.py`

**What:** After company research and AI scoring complete, Claude generates a 2-3 sentence narrative verdict ("why this is or isn't a good fit") and a receptivity signal (high/medium/low for whether this company would value the AI-portfolio approach). This is a lightweight Claude call — not full deliverable generation.

- [ ] **Step 1: Write failing test for narrative generation**

```python
# tests/test_generator.py
def test_generate_narrative_verdict():
    mock_response = '{"narrative": "Strong technical fit. Your TypeScript depth exceeds requirements...", "receptivity": "high", "receptivity_reason": "AI-native company building LLM tools"}'
    with patch("claude_candidate.claude_cli.call_claude", return_value=mock_response):
        from claude_candidate.generator import generate_narrative_verdict
        result = generate_narrative_verdict(assessment_data, company_research)
        assert "narrative" in result
        assert result["receptivity"] in ["high", "medium", "low"]
        assert "receptivity_reason" in result
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement generate_narrative_verdict**

Add to `generator.py`:

```python
def generate_narrative_verdict(
    assessment: dict,
    company_research: dict,
) -> dict:
    """Generate narrative verdict and receptivity signal via Claude."""
    prompt = (
        "Based on this job assessment and company research, return ONLY valid JSON with:\n"
        "- narrative: string (2-3 sentences: why this is or isn't a good fit, "
        "the candidate's strongest angle, and what gap is most likely to come up)\n"
        "- receptivity: string (high, medium, or low — would this company value "
        "a transparent AI-powered portfolio application?)\n"
        "- receptivity_reason: string (one sentence explaining the receptivity rating)\n\n"
        f"Assessment: skill match {assessment.get('overall_grade', 'N/A')}, "
        f"company: {assessment.get('company_name', 'Unknown')}, "
        f"role: {assessment.get('job_title', 'Unknown')}\n"
        f"Skill matches: {json.dumps(assessment.get('skill_matches', [])[:5])}\n"
        f"Company research: {json.dumps(company_research)}\n"
    )
    raw = _claude_cli.call_claude(prompt, timeout=30)
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    result = json.loads(cleaned.strip())
    result["narrative"] = scrub_deliverable(result.get("narrative", ""))
    return result
```

- [ ] **Step 4: Wire into full assessment endpoint**

After company research and AI scoring complete, call `generate_narrative_verdict()` and merge results into the assessment.

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_generator.py tests/test_server.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/generator.py src/claude_candidate/server.py tests/test_generator.py
git commit -m "Add narrative verdict and receptivity signal to full assessment"
```

---

### Task 8: Extension Popup Refactor

**Phase:** D (depends on Tasks 3, 6, 7)

**Files:**
- Modify: `extension/popup.html`
- Modify: `extension/popup.js`
- Modify: `extension/popup.css`
- Modify: `extension/background.js`

**What:** Major extension refactor:
1. Partial result shows weighted percentage (e.g., "72%") from skills/experience/education
2. Full result replaces percentage with letter grade, adds narrative + receptivity
3. No new tab — everything stays in popup
4. "Save to Watchlist" becomes "Add to Shortlist" with salary/location capture
5. Clipboard copy button for spreadsheet row
6. Remove "Full Details" button and "Generating full report..." banner logic

- [ ] **Step 1: Update popup.html structure**

Remove:
- `#btn-full-details` button
- `#banner-full-loading` banner
- Old three-dimension display (skills/mission/culture bars)
- `#state-full-details` state

Add:
- Partial percentage display (large number: "72%")
- Three local dimension rows (skills, experience, education) with expandable details
- Full dimensions section (mission, culture — hidden until full completes)
- Narrative verdict text area
- Receptivity badge
- "Add to Shortlist" button (replaces "Save to Watchlist")
- Clipboard copy button (📋 icon)

- [ ] **Step 2: Update popup.js renderResults()**

Replace current `renderResults()` to:
- Show `partial_percentage` as the hero number when `assessment_phase === "partial"`
- Show `overall_grade` as the hero when `assessment_phase === "full"`
- Render `skill_match`, `experience_match`, `education_match` as the three visible dimensions
- When full data arrives: show `mission_alignment`, `culture_fit`, `narrative_verdict`, `receptivity_level`

- [ ] **Step 3: Update background.js**

**Critical:** Update `handleAssessPartial` to pass enriched requirements from the extraction result. Currently it only sends `posting_text`, `company`, `title`, `posting_url`. After Task 1 enriches the extraction, the extraction result contains `requirements` — these must be forwarded to `/api/assess/partial` so the local scorer uses Claude-parsed requirements instead of the crude keyword fallback:

```javascript
async function handleAssessPartial(payload) {
    const body = {
        posting_text: payload.description || '',
        company: payload.company || 'Unknown Company',
        title: payload.title || 'Unknown Position',
        posting_url: payload.url || null,
        requirements: payload.requirements || null,  // NEW: from enriched extraction
        seniority: payload.seniority || 'unknown',   // NEW: from extraction
    };
    // ...
}
```

Also: remove `handleStartFullAssess` deliverables check (`result.deliverables`).
Update `handleAssessFull` to expect the new response shape (no deliverables, has narrative + receptivity).
Remove `handleOpenReport` (no new tab).

Update completion check:
```javascript
if (result.success && result.assessment_phase === 'full') {
    chrome.storage.local.set({
        fullAssessmentReady: {
            assessmentId: result.assessment_id,
            data: result,
            completedAt: Date.now(),
        }
    });
}
```

- [ ] **Step 4: Update popup.js polling**

Replace polling for `fullReportReady` with polling for `fullAssessmentReady`.
When found, call `renderResults(ready.data)` to update popup in-place instead of showing a button.

- [ ] **Step 5: Add shortlist button**

Rename "Save to Watchlist" to "Add to Shortlist".
Update `addToWatchlist` message to `addToShortlist`.
Include `salary`, `location`, `overall_grade` from the assessment data.

- [ ] **Step 6: Add clipboard copy button**

```javascript
const btnCopy = el('btn-clipboard');
btnCopy.addEventListener('click', () => {
    const data = currentAssessment;
    const posting = currentPosting;
    const row = [
        data.company_name || '',
        data.job_title || '',
        posting.location || '',
        posting.salary || '',
        posting.url || '',
        data.overall_grade || '',
        new Date().toLocaleDateString(),
    ].join('\t');
    navigator.clipboard.writeText(row);
    btnCopy.textContent = 'Copied!';
    setTimeout(() => { btnCopy.textContent = '📋'; }, 1500);
});
```

- [ ] **Step 7: Update background.js message routing**

Rename `addToWatchlist` → `addToShortlist`.
Update API call from `/api/watchlist` → `/api/shortlist`.
Remove `openReport` handler.

- [ ] **Step 8: Manual test the extension flow**

Load extension in Chrome, test against a real job posting:
1. Click extension → see percentage + three local dimensions
2. Wait for full → see letter grade, narrative, receptivity (in-place update)
3. Click "Add to Shortlist" → confirm save
4. Click clipboard button → paste into Google Sheets

- [ ] **Step 9: Commit**

```bash
git add extension/
git commit -m "Refactor extension popup: percentage partial, letter grade full, no new tab"
```

---

### Task 9: Cover Letter Site Template + CLI Generate + Deploy

**Phase:** D (depends on Tasks 6, 7 — can run parallel with Tasks 8 and 10)

**Files:**
- Create: `src/claude_candidate/templates/cover_letter_site.html`
- Modify: `src/claude_candidate/site_renderer.py`
- Modify: `src/claude_candidate/generator.py` (narrative for site page)
- Modify: `src/claude_candidate/cli.py` (refactor generate command + deploy)
- Test: `tests/test_site_renderer.py`

**What:** New cover letter site page template based on grill session decisions. The page has: hero with transparency badge, skills match grid, Claude-generated narrative, evidence highlights, How This Works explainer, and CTA. No inline resume. The CLI `generate` command renders the page and auto-deploys via `wrangler pages deploy`.

- [ ] **Step 1: Write failing test for new template**

```python
# tests/test_site_renderer.py
def test_cover_letter_site_has_transparency_badge(tmp_path):
    """Cover letter site should have a 'Built with claude-candidate' badge near hero."""
    render_cover_letter_site(assessment, narrative, evidence_highlights, output_dir=tmp_path)
    html = (tmp_path / "apply" / "acme-corp" / "index.html").read_text()
    assert "claude-candidate" in html
    assert "Built with" in html or "Powered by" in html

def test_cover_letter_site_has_no_resume_section(tmp_path):
    """Cover letter site should NOT have an inline resume."""
    render_cover_letter_site(assessment, narrative, evidence_highlights, output_dir=tmp_path)
    html = (tmp_path / "apply" / "acme-corp" / "index.html").read_text()
    assert "Tailored Resume" not in html

def test_cover_letter_site_has_narrative(tmp_path):
    """Cover letter site should contain the generated narrative."""
    render_cover_letter_site(assessment, "I bring deep AI expertise...", [], output_dir=tmp_path)
    html = (tmp_path / "apply" / "acme-corp" / "index.html").read_text()
    assert "I bring deep AI expertise" in html

def test_cover_letter_site_has_receptivity_signal(tmp_path):
    """Cover letter site should show receptivity level."""
    assessment.receptivity_level = "high"
    render_cover_letter_site(assessment, narrative, [], output_dir=tmp_path)
    html = (tmp_path / "apply" / "acme-corp" / "index.html").read_text()
    # Receptivity is for internal use (report card), not the public page
    # The transparency badge serves this purpose on the site
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Create cover_letter_site.html template**

New Jinja2 template following the grill session design:

Sections:
1. **Hero** — Job title, company, fit score visualization, "Built with claude-candidate" badge
2. **Skills Match** — Grid mapping requirements → candidate evidence (from skill_matches)
3. **Why This Role** — Claude-generated narrative (150-250 words)
4. **Evidence Highlights** — 2-3 curated session/project examples
5. **How This Works** — 3-sentence explainer + GitHub link
6. **CTA** — Contact info, optional resume PDF download link
7. **Footer** — Private page notice, noindex/nofollow

- [ ] **Step 4: Add render_cover_letter_site() to site_renderer.py**

```python
def render_cover_letter_site(
    assessment: FitAssessment,
    narrative: str,
    evidence_highlights: list[dict],
    output_dir: Path | str,
    resume_pdf_path: str | None = None,
) -> Path:
    """Render the cover letter site page for a company."""
    env = _build_env()
    template = env.get_template("cover_letter_site.html")
    slug = _make_slug(assessment.company_name)

    html = template.render(
        assessment=assessment,
        narrative=narrative,
        evidence_highlights=evidence_highlights,
        resume_pdf_path=resume_pdf_path,
    )
    html = scrub_deliverable(html)

    out_dir = Path(output_dir) / "apply" / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "index.html"
    out_path.write_text(html)
    return out_path
```

- [ ] **Step 5: Run tests**

Run: `pytest tests/test_site_renderer.py -v`

- [ ] **Step 6: Add narrative generation for site page**

Add to `generator.py`:

```python
def generate_site_narrative(assessment: dict, company_research: dict) -> str:
    """Generate 150-250 word pitch narrative for the cover letter site page."""
    prompt = (
        "Write a 150-250 word pitch for a cover letter page. "
        "Frame it as 'what I would bring to this role' — confident, specific, evidence-grounded. "
        "Not a traditional cover letter tone. More like a confident assessment.\n\n"
        f"Role: {assessment.get('job_title')} at {assessment.get('company_name')}\n"
        f"Company context: {json.dumps(company_research)}\n"
        f"Strongest skills: {assessment.get('strongest_match', 'N/A')}\n"
        f"Biggest gap: {assessment.get('biggest_gap', 'None')}\n"
        f"Skill matches: {json.dumps(assessment.get('skill_matches', [])[:5])}\n\n"
        "Write in first person. No fluff. Lead with the strongest match."
    )
    raw = _claude_cli.call_claude(prompt, timeout=60)
    return scrub_deliverable(raw.strip())
```

- [ ] **Step 7: Refactor CLI generate command**

Update `cli.py` to:
1. Accept `--job <shortlist-id>` or `--assessment <assessment-id>`
2. Load assessment from store
3. Load or run company research
4. Generate site narrative via Claude
5. Select evidence highlights from session data
6. Render cover letter site page
7. Run `wrangler pages deploy ./site --project-name=roojerry`

```python
@main.command()
@click.option("--job", "shortlist_id", type=int, help="Shortlist ID to generate for")
@click.option("--output-dir", default="site", help="Output directory")
@click.option("--deploy/--no-deploy", default=True, help="Auto-deploy via wrangler")
def generate(shortlist_id: int, output_dir: str, deploy: bool) -> None:
    """Generate cover letter site page for a shortlisted job and deploy."""
    import asyncio
    from claude_candidate.storage import AssessmentStore
    from claude_candidate.site_renderer import render_cover_letter_site
    from claude_candidate.generator import generate_site_narrative
    from claude_candidate.company_research import research_company

    # Load shortlist entry → assessment
    # Load or fetch company research
    # Generate narrative
    # Select evidence highlights
    # Render page
    # Deploy if --deploy

    if deploy:
        import subprocess
        click.echo("Deploying to Cloudflare Pages...")
        subprocess.run(
            ["npx", "wrangler", "pages", "deploy", output_dir, "--project-name=roojerry"],
            check=True,
        )
        click.echo(f"Deployed to roojerry.com/apply/{slug}/")
```

- [ ] **Step 8: Run tests**

Run: `pytest tests/ -v`

- [ ] **Step 9: Commit**

```bash
git add src/claude_candidate/templates/cover_letter_site.html src/claude_candidate/site_renderer.py src/claude_candidate/generator.py src/claude_candidate/cli.py tests/test_site_renderer.py
git commit -m "Add cover letter site page with transparency badge and auto-deploy"
```

---

### Task 10: CLI Shortlist Command

**Phase:** D (depends on Task 3 — can run parallel with Tasks 8 and 9)

**Files:**
- Modify: `src/claude_candidate/cli.py`
- Test: `tests/test_integration.py`

**What:** Add `claude-candidate shortlist` CLI command that prints a table of shortlisted jobs with grades, company, title, location, salary, and date added. Same data the extension shows in the shortlist view.

- [ ] **Step 1: Write failing test**

```python
# tests/test_integration.py
def test_shortlist_command_shows_table(runner, db_with_shortlist):
    result = runner.invoke(main, ["shortlist"])
    assert result.exit_code == 0
    assert "Anthropic" in result.output
    assert "B+" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

- [ ] **Step 3: Implement shortlist command**

```python
@main.command()
@click.option("--db", default=None, help="Database path")
def shortlist(db: str | None) -> None:
    """List shortlisted jobs with grades."""
    import asyncio
    from claude_candidate.storage import AssessmentStore

    async def _list():
        data_dir = Path(db) if db else Path.home() / ".claude-candidate"
        store = AssessmentStore(data_dir / "assessments.db")
        await store.initialize()
        items = await store.list_shortlist()
        await store.close()
        return items

    items = asyncio.run(_list())

    if not items:
        click.echo("No shortlisted jobs.")
        return

    # Print table header
    click.echo(f"{'Grade':<6} {'Company':<20} {'Title':<30} {'Location':<15} {'Salary':<15} {'Added':<12}")
    click.echo("-" * 100)
    for item in items:
        click.echo(
            f"{item.get('overall_grade', '--'):<6} "
            f"{item['company_name'][:19]:<20} "
            f"{item['job_title'][:29]:<30} "
            f"{(item.get('location') or '--')[:14]:<15} "
            f"{(item.get('salary') or '--')[:14]:<15} "
            f"{item.get('added_at', '--')[:10]:<12}"
        )
```

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_integration.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/cli.py tests/test_integration.py
git commit -m "Add CLI shortlist command for listing shortlisted jobs"
```

---

## Verification Gate

After all 10 tasks:

1. `POST /api/extract-posting` returns structured requirements with years and education
2. `POST /api/assess/partial` returns weighted percentage from skills/experience/education — no mission/culture
3. `POST /api/assess/full` returns letter grade with all dimensions + narrative + receptivity — NO deliverables
4. Company research is cached per company (30-day TTL)
5. AI scoring runs parallel with company research
6. Extension popup shows % for partial, letter grade for full, no new tab opens
7. "Add to Shortlist" saves with salary, location, grade
8. Clipboard button copies tab-separated row for Google Sheets
9. `claude-candidate shortlist` prints a table of shortlisted jobs
10. `claude-candidate generate --job <id>` renders cover letter site page with transparency badge and auto-deploys via wrangler
11. Cover letter site page has no inline resume
12. Full test suite passes
