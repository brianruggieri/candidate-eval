# Eligibility Hard Caps — Design Spec

**Date:** 2026-03-24
**Branch:** feat/eligibility-hard-caps
**Status:** Approved

## Problem

The eligibility gate system detects requirements that are binary pass/fail conditions (work authorization, clearance, language, travel, relocation) and excludes them from skill scoring. However, `_evaluate_eligibility()` always returns `status="unknown"` because the profile carries no candidate eligibility data. As a result, `eligibility_passed=False` is never set and the grade is never affected by an unmet gate — a candidate who cannot legally take a role can still receive an A.

## Goals

1. Store candidate eligibility facts in `CuratedResume`
2. Resolve each eligibility gate to `"met"` / `"unmet"` / `"unknown"` against those facts
3. Cap the overall grade to F when any gate is `"unmet"` — in both the CLI path and the server full-assess path
4. Make the reason immediately apparent in the assessment output (summary + action items)

## Non-Goals

- Multi-language support beyond "English = native, everything else = not known"
- Tiered clearance levels
- UI changes to the Chrome extension
- Storing the counterfactual grade as a schema field (it appears in summary text only — deliberate to avoid schema churn)

---

## Schema Changes

### `schemas/curated_resume.py`

New model added above `CuratedResume`:

```python
class CandidateEligibility(BaseModel):
    us_work_authorized: bool = True
    max_travel_pct: int = 40       # candidate's tolerance ceiling (0–100)
    has_clearance: bool = False
    willing_to_relocate: bool = True
```

`max_travel_pct` is the candidate's tolerance ceiling. A requirement of 50% travel with `max_travel_pct=40` is **unmet**.

New field on `CuratedResume`:

```python
eligibility: CandidateEligibility = Field(default_factory=CandidateEligibility)
```

Using `default_factory` means all existing `curated_resume.json` files load without changes. `profile_version` stays `"0.1.0"` — no migration needed.

### `quick_match.py` — `AssessmentInput` dataclass

Add at the end of `AssessmentInput`:

```python
from dataclasses import dataclass, field
from claude_candidate.schemas.curated_resume import CandidateEligibility

@dataclass
class AssessmentInput:
    # ... existing fields ...
    curated_eligibility: CandidateEligibility = field(default_factory=CandidateEligibility)
```

Defaults are permissive so tests and callers without a curated resume continue to work unchanged.

### `QuickMatchEngine.assess()` method signature

Add one optional parameter:

```python
def assess(
    self,
    requirements: list[QuickRequirement],
    company: str,
    title: str,
    ...existing params...,
    curated_eligibility: CandidateEligibility | None = None,
) -> FitAssessment:
    inp = AssessmentInput(
        ...existing fields...,
        curated_eligibility=curated_eligibility or CandidateEligibility(),
    )
```

---

## New Module: `eligibility_evaluator.py`

`src/claude_candidate/eligibility_evaluator.py` — single public function:

```python
from claude_candidate.schemas.curated_resume import CandidateEligibility
from claude_candidate.schemas.fit_assessment import EligibilityGate
from claude_candidate.schemas.job_requirements import QuickRequirement

def evaluate_gates(
    reqs: list[QuickRequirement],
    eligibility: CandidateEligibility,
) -> list[EligibilityGate]:
```

### Gate resolution rules

Each requirement is classified by inspecting `req.skill_mapping` entries (lowercased). The first matching group wins.

| Skill mapping matches | Resolves against | `met` when |
|---|---|---|
| `us-work-authorization`, `us_work_authorization`, `work-authorization`, `work_authorization`, `visa`, `visa-sponsorship` | `eligibility.us_work_authorized` | `True` |
| `security-clearance`, `clearance` | `eligibility.has_clearance` | `True` |
| `relocation` | `eligibility.willing_to_relocate` | `True` |
| `travel` | regex `\d+\s*%` in `req.description` vs `eligibility.max_travel_pct` | extracted % ≤ max |
| `english` | hardcoded | always `met` (native speaker) |
| `spanish`, `french`, `german`, `mandarin` (and `-fluency`/`-proficiency` suffixes) | hardcoded | always `unmet` |
| `mission_alignment`, `mission-alignment` | — | always `unknown` (not a binary gate) |
| anything else | — | `unknown` |

**Travel parsing detail:** extract the first `\d+\s*%` from `req.description`. If no `%` is found, return `"unknown"`. `met` when extracted integer ≤ `eligibility.max_travel_pct`. "0% travel" is always `met`.

**`visa`/`visa-sponsorship` rationale:** these appear on postings to indicate the candidate needs sponsorship. If `us_work_authorized=True`, the candidate does not need it → `met`. If `False` → `unmet`.

---

## Hard Cap Logic — CLI path

The cap is applied in `_run_assessment()` immediately after `_compute_overall_score()`, before `_build_assessment()`.

Exact insertion point — after line 1537 (`overall_score = _compute_overall_score(...)`), before line 1538 (`partial_percentage = ...`):

```python
pre_cap_grade: str | None = None
unmet_gates = [g for g in eligibility_gates if g.status == "unmet"]
if unmet_gates:
    pre_cap_grade = score_to_grade(overall_score)
    overall_score = 0.0
```

`pre_cap_grade` is then passed down: `_run_assessment` → `_build_assessment` → `_assemble_fit_assessment` as a new optional parameter (`pre_cap_grade: str | None = None`).

In `_assemble_fit_assessment`, when `pre_cap_grade is not None`:

```python
if pre_cap_grade is not None:
    blocker_descriptions = "; ".join(
        g.description for g in (eligibility_gates or []) if g.status == "unmet"
    )
    overall_summary = (
        f"Eligibility blocked: {blocker_descriptions}. "
        f"Skill fit would be {pre_cap_grade} if eligible."
    )
    action_items = [
        f"Eligibility: {blocker_descriptions} — skip this role",
        *action_items[:5],
    ]
    # Total: 1 blocker + up to 5 original items = up to 6 (matches MAX_ACTION_ITEMS)
```

The existing `_generate_summary()` and `_generate_action_items()` are **not changed** — they run normally; their output is post-processed in `_assemble_fit_assessment` when the cap is active.

---

## Hard Cap Logic — Server full-assess path

`server.py` `/api/assess/full` endpoint recomputes `overall_score` independently (line ~500) and does not use `_run_assessment`. The stored partial assessment already contains `eligibility_gates` (as a list of dicts). After recomputing `overall_score`, add:

```python
# Re-apply eligibility cap if any gate was unmet in the partial assessment
stored_gates = data.get("eligibility_gates", [])
if any(g.get("status") == "unmet" for g in stored_gates):
    overall_score = 0.0
    overall_grade = "F"
```

This must be inserted between lines 500-501 and the narrative generation block. No new parameters are needed — `data` is already in scope.

---

## Integration: `cli.py` caller

In the `assess` command, load `curated_resume.eligibility` and pass it to `engine.assess()`:

```python
curated_eligibility = curated_resume.eligibility if curated_resume else None
result = engine.assess(
    requirements=requirements,
    ...,
    curated_eligibility=curated_eligibility,
)
```

---

## Files Touched

| File | Change |
|---|---|
| `src/claude_candidate/schemas/curated_resume.py` | Add `CandidateEligibility` model + `eligibility` field on `CuratedResume` |
| `src/claude_candidate/eligibility_evaluator.py` | New module — `evaluate_gates()` |
| `src/claude_candidate/quick_match.py` | Add `curated_eligibility` to `AssessmentInput` + `assess()` signature; replace `_evaluate_eligibility()` with `evaluate_gates()`; add hard cap after `_compute_overall_score`; pass `pre_cap_grade` through `_build_assessment` → `_assemble_fit_assessment`; override summary/actions when cap is active |
| `src/claude_candidate/server.py` | Re-apply eligibility cap after `overall_score` is recomputed in full-assess path |
| `src/claude_candidate/cli.py` | Pass `curated_eligibility` to `engine.assess()` |
| `tests/test_eligibility_evaluator.py` | New test file — unit tests for each gate type |
| `tests/test_quick_match.py` | Tests for cap behavior, summary injection, action item prefix |

---

## Testing

### `test_eligibility_evaluator.py`

- `us_work_authorized=True` → gate for `us-work-authorization` → `met`
- `us_work_authorized=False` → `unmet`
- `us_work_authorized=True` → gate for `visa-sponsorship` → `met`
- `has_clearance=False` + clearance requirement → `unmet`
- `has_clearance=True` + clearance requirement (both `security-clearance` and `clearance` aliases) → `met`
- `max_travel_pct=40` + "50% travel required" → `unmet`
- `max_travel_pct=40` + "30% travel required" → `met`
- travel requirement with no `%` in description → `unknown`
- `english` / `english-fluency` requirement → always `met`
- `spanish` / `french` / `german` / `mandarin` requirement → always `unmet`
- `mission_alignment` requirement → always `unknown`
- unknown requirement type → `unknown`
- empty `reqs` list → returns `[]`

### `test_quick_match.py` additions

- Unmet gate → `overall_grade == "F"`, `overall_score == 0.0`, `should_apply == "no"`
- Unmet gate → `overall_summary` starts with `"Eligibility blocked:"`
- Unmet gate → `action_items[0]` starts with `"Eligibility:"`
- Unmet gate + high pre-cap skill score → counterfactual grade appears in `overall_summary`
- Multiple unmet gates → all descriptions appear in summary and action item
- All gates `met` → score unchanged, grade reflects actual skill fit
- All gates `unknown` → score unchanged (no cap applied)
- No eligibility requirements → `eligibility_gates == []`, score unchanged
- Partial assess path (`_run_assessment`) → cap applies correctly
