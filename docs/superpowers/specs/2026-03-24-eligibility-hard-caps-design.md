# Eligibility Hard Caps — Design Spec

**Date:** 2026-03-24
**Branch:** feat/eligibility-hard-caps
**Status:** Approved

## Problem

The eligibility gate system detects requirements that are binary pass/fail conditions (work authorization, clearance, language, travel, relocation) and excludes them from skill scoring. However, `_evaluate_eligibility()` always returns `status="unknown"` because the profile carries no candidate eligibility data. As a result, `eligibility_passed=False` is never set and the grade is never affected by an unmet gate — a candidate who cannot legally take a role can still receive an A.

## Goals

1. Store candidate eligibility facts in `CuratedResume`
2. Resolve each eligibility gate to `"met"` / `"unmet"` / `"unknown"` against those facts
3. Cap the overall grade to F when any gate is `"unmet"`
4. Make the reason immediately apparent in the assessment output (summary + action items)

## Non-Goals

- Multi-language support beyond "English = native, everything else = not known"
- Tiered clearance levels
- UI changes to the Chrome extension

---

## Schema Changes

### `schemas/curated_resume.py`

New model added above `CuratedResume`:

```python
class CandidateEligibility(BaseModel):
    us_work_authorized: bool = True
    max_travel_pct: int = 40       # 0–100; candidate's maximum acceptable travel
    has_clearance: bool = False
    willing_to_relocate: bool = True
```

New field on `CuratedResume`:

```python
eligibility: CandidateEligibility = Field(default_factory=CandidateEligibility)
```

Using `default_factory` means all existing `curated_resume.json` files load without changes. `profile_version` stays `"0.1.0"` — no migration needed.

---

## New Module: `eligibility_evaluator.py`

`src/claude_candidate/eligibility_evaluator.py` — single public function:

```python
def evaluate_gates(
    reqs: list[QuickRequirement],
    eligibility: CandidateEligibility,
) -> list[EligibilityGate]:
```

### Gate resolution rules

| Skill mapping contains | Resolves against | Result |
|---|---|---|
| `us-work-authorization`, `work-authorization` | `eligibility.us_work_authorized` | `met` / `unmet` |
| `security-clearance` | `eligibility.has_clearance` | `met` / `unmet` |
| `relocation` | `eligibility.willing_to_relocate` | `met` / `unmet` |
| `travel-requirement` | regex-parsed `%` from `req.description` vs `eligibility.max_travel_pct` | `met` / `unmet` |
| `english` or `english-fluency` | hardcoded `True` (native speaker) | always `met` |
| `spanish` / any other language skill | hardcoded `False` | always `unmet` |
| anything else | no match | `unknown` |

**Travel parsing:** extract the first `\d+\s*%` from `req.description`. If no percentage is found, return `"unknown"` (can't evaluate without a number). If found, `met` when extracted % ≤ `eligibility.max_travel_pct`.

### `quick_match.py` integration

Replace the current call to `_evaluate_eligibility(eligibility_reqs)` with:

```python
from claude_candidate.eligibility_evaluator import evaluate_gates
eligibility_gates = evaluate_gates(eligibility_reqs, inp.curated_eligibility)
```

`inp.curated_eligibility` is a `CandidateEligibility` instance loaded from the curated resume (or defaulted if no curated resume is provided).

The existing `_evaluate_eligibility()` function is deleted.

---

## Hard Cap Logic

After `overall_score` is computed and before `_assemble_fit_assessment` is called:

```python
unmet_gates = [g for g in eligibility_gates if g.status == "unmet"]
if unmet_gates:
    pre_cap_grade = score_to_grade(overall_score)
    overall_score = 0.0
```

`score_to_grade(0.0)` → `"F"`, `score_to_verdict(0.0)` → `"no"`. No new parameters needed in `_assemble_fit_assessment`.

---

## UX: Making the Reason Apparent

The extension renders grade → summary → action items. When eligibility fails, both surfaces must lead with the reason.

### Summary injection

When `unmet_gates` is non-empty, `overall_summary` is replaced entirely (not prepended):

> `"Eligibility blocked: role requires security clearance (you do not have one). Skill fit would be B+ if eligible."`

The counterfactual grade (`pre_cap_grade`) is included so the technical signal is preserved.

### Action items

The blocker is injected as `action_items[0]`:

> `"Eligibility: requires security clearance — skip this role"`

Existing action item generation fills slots 1–5 normally. The `min_length=1` constraint on `action_items` is satisfied by the blocker alone if no other items are generated.

---

## Language Stripping

Language requirements (`english`, `spanish`, etc.) map to entries in `ELIGIBILITY_SKILL_NAMES` and are already routed into `eligibility_reqs` by `_infer_eligibility`. They never reach `_score_skill_match` and do not inflate or deflate skill match percentage. No additional work needed.

---

## Files Touched

| File | Change |
|---|---|
| `src/claude_candidate/schemas/curated_resume.py` | Add `CandidateEligibility` model + `eligibility` field on `CuratedResume` |
| `src/claude_candidate/eligibility_evaluator.py` | New module — `evaluate_gates()` |
| `src/claude_candidate/quick_match.py` | Replace `_evaluate_eligibility()` with `evaluate_gates()` call; add hard cap + summary/action injection |
| `tests/test_eligibility_evaluator.py` | New test file — unit tests for each gate type |
| `tests/test_quick_match.py` | Add tests for cap behavior, summary injection, action item prefix |

---

## Testing

### `test_eligibility_evaluator.py`

- `us_work_authorized=True` → gate for `us-work-authorization` resolves `met`
- `us_work_authorized=False` → resolves `unmet`
- `has_clearance=False` + clearance requirement → `unmet`
- `max_travel_pct=40` + "50% travel required" → `unmet`
- `max_travel_pct=40` + "30% travel required" → `met`
- travel requirement with no % in description → `unknown`
- English fluency requirement → always `met`
- Spanish requirement → always `unmet`
- Unknown requirement type → `unknown`

### `test_quick_match.py` additions

- Unmet gate → `overall_grade == "F"`, `overall_score == 0.0`, `should_apply == "no"`
- Unmet gate → `overall_summary` starts with `"Eligibility blocked:"`
- Unmet gate → `action_items[0]` starts with `"Eligibility:"`
- Unmet gate + high skill score → counterfactual grade appears in summary
- All gates `met` → score unchanged, grade reflects actual skill fit
- All gates `unknown` → score unchanged (no cap)
- No eligibility requirements → score unchanged
