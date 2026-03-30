# Assessment Pipeline Consolidation

**Date:** 2026-03-30
**Branch:** `feat/scoring-consolidation-v09`
**Status:** Design approved

## Problem

Four `engine.assess()` call sites each wire different subsets of inputs, producing inconsistent scoring behavior:

| Call site | `work_preferences` | `company_profile` | `culture_signals` | `tech_stack` |
|-----------|--------------------|--------------------|-------------------|--------------|
| CLI `assess` (cli.py:149) | missing | missing | missing | missing |
| Server `/api/assess/partial` (server.py:478) | missing | missing | passed | passed |
| Server enrichment full (server.py:560-729) | **bypasses engine** | **bypasses engine** | n/a | n/a |
| Server reassess batch (server.py:881) | missing | missing | passed | passed |

The enrichment endpoint is the worst: it manually calls `_score_culture_preferences`, runs its own `select_weights`, computes `weighted_total`, and patches the stored dict — duplicating ~60 lines of orchestration that already lives in `engine._run_assessment()`.

Result: CLI assessments never score culture. Server partial assessments never score culture. Server full assessments score culture but through a separate code path that can drift from the engine.

## Solution

### Shared helper: `prepare_assess_inputs()`

One function that resolves the common inputs every call site needs but currently forgets or handles ad-hoc.

**Location:** `src/claude_candidate/scoring/__init__.py`

```python
def prepare_assess_inputs(
    company: str,
    *,
    culture_signals: list[str] | None = None,
    tech_stack: list[str] | None = None,
    company_profile: CompanyProfile | None = None,
) -> dict:
    """Resolve work_preferences and company_profile for engine.assess().

    Returns dict with keys: work_preferences, company_profile.
    Designed to be **kwargs'd into engine.assess().
    """
    from claude_candidate.schemas.work_preferences import WorkPreferences
    from claude_candidate.schemas.company_profile import CompanyProfile

    # 1. Load work preferences from canonical path
    prefs_path = Path.home() / ".claude-candidate" / "work_preferences.json"
    work_preferences = WorkPreferences.load(prefs_path)

    # 2. Build minimal CompanyProfile from signals if none provided
    if company_profile is None and (culture_signals or tech_stack):
        company_profile = CompanyProfile(
            company_name=company,
            culture_keywords=culture_signals or [],
            tech_stack_public=tech_stack or [],
        )

    return {
        "work_preferences": work_preferences,
        "company_profile": company_profile,
    }
```

### Changes per call site

#### 1. CLI `assess` (cli.py:148-158)

Add `prepare_assess_inputs()` call and spread into `engine.assess()`:

```python
from claude_candidate.scoring import prepare_assess_inputs

extras = prepare_assess_inputs(company)
engine = QuickMatchEngine(merged)
assessment = engine.assess(
    requirements=requirements,
    company=company,
    title=title,
    posting_url=None,
    source="cli",
    seniority=seniority,
    elapsed=elapsed,
    curated_eligibility=curated_eligibility,
    **extras,
)
```

No CLI flag changes. Preferences load from the canonical path automatically.

#### 2. Server `/api/assess/partial` (server.py:476-488)

Same pattern, passing request-provided signals:

```python
from claude_candidate.scoring import prepare_assess_inputs

extras = prepare_assess_inputs(
    req.company,
    culture_signals=req.culture_signals,
    tech_stack=req.tech_stack,
)
engine = QuickMatchEngine(merged)
assessment = engine.assess(
    requirements=requirements,
    company=req.company,
    title=req.title,
    posting_url=req.posting_url,
    source="api",
    seniority=req.seniority,
    curated_eligibility=curated_eligibility,
    **extras,
)
```

#### 3. Server enrichment full (server.py:560-729) — major refactor

Replace the manual scoring block (lines 619-676) with a re-assessment through the engine:

1. Company research + `CompanyProfile` construction stays the same (lines 560-617)
2. Instead of manually scoring mission/culture/weights, call `engine.assess()`:

```python
extras = prepare_assess_inputs(
    company,
    company_profile=company_profile,
)
engine = QuickMatchEngine(merged_profile)
assessment = engine.assess(
    requirements=original_requirements,  # from stored input_requirements
    company=company,
    title=data.get("job_title", ""),
    posting_url=data.get("posting_url"),
    source="enrich",
    seniority=original_meta.get("seniority", "unknown"),
    curated_eligibility=curated_eligibility,
    **extras,
)
```

3. Overwrite the stored assessment with the engine's output
4. Narrative verdict generation remains a post-engine step (it's presentation, not scoring)

**What gets deleted from enrichment:**
- Manual `_score_culture_preferences()` call (line 641)
- Manual `_score_mission_alignment()` call (line 629)
- Manual `select_weights()` call (line 657)
- Manual `weighted_total` computation (lines 659-663)
- Manual eligibility re-application (lines 667-669)
- Manual weight patching (lines 673-676)
- Manual `score_to_grade` / `score_to_verdict` (lines 664, 699)

All of this is already handled by `engine._run_assessment()`.

#### 4. Server reassess batch (server.py:881-891)

Same pattern as partial:

```python
extras = prepare_assess_inputs(
    meta.get("company") or data.get("company_name", ""),
    culture_signals=meta.get("culture_signals"),
    tech_stack=meta.get("tech_stack"),
)
assessment = engine.assess(
    requirements=reqs,
    company=meta.get("company") or data.get("company_name", ""),
    title=meta.get("title") or data.get("job_title", ""),
    posting_url=meta.get("posting_url") or data.get("posting_url"),
    source="reassess",
    seniority=meta.get("seniority", "unknown"),
    curated_eligibility=curated_eligibility,
    **extras,
)
```

### What stays unchanged

- `engine.assess()` signature — already accepts all required parameters
- `AssessmentInput` dataclass — no changes
- `engine._run_assessment()` orchestration — no changes
- Two-pass flow (partial then full) — preserved; both passes use the engine
- Company research — still async, cached, only in server enrichment flow
- Narrative verdict — still a post-engine best-effort step in enrichment
- `_build_merged_profile()` — no changes
- All existing tests — behavior should be identical for call sites that already worked

### Enrichment: recovering stored inputs

The enrichment endpoint needs two things to re-run through the engine:

1. **Original requirements** — already stored as `input_requirements` on every assessment (server.py:493). Deserialize back into `QuickRequirement` objects, same as reassess batch already does.
2. **Curated eligibility** — load from `get_profiles()["curated_resume"]` the same way `/api/assess/partial` does. The enrichment endpoint currently skips this because it relied on gates stored from the partial pass, but the engine needs it to evaluate gates canonically.

### Test plan

1. **Unit test `prepare_assess_inputs()`** — verify it loads preferences, builds CompanyProfile from signals, passes through an existing CompanyProfile
2. **CLI assessment with preferences** — run `assess` with `work_preferences.json` present, verify culture_fit dimension appears in output
3. **Server partial with preferences** — verify culture scoring activates when preferences exist
4. **Server enrichment** — verify full assessment produces identical scores whether going through the old manual path or the new engine path (regression check against stored golden set assessments)
5. **Server reassess batch** — verify preferences are included in re-scored assessments
6. **Golden set benchmark** — run `benchmark_accuracy.py` before and after, verify no grade regressions
