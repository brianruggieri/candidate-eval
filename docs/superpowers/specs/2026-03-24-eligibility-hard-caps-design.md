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

Add one field:

```python
curated_eligibility: CandidateEligibility = field(default_factory=CandidateEligibility)
```

This is populated by the caller (`cli.py` `assess` command) from the loaded `CuratedResume.eligibility`. When no curated resume is loaded (e.g., tests), the default `CandidateEligibility()` is used — all defaults are permissive so assessments pass eligibility unless explicitly blocked.

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

Each requirement is classified by inspecting its `skill_mapping` entries (lowercased) against the groups below. The first matching group wins.

| Skill mapping matches | Resolves against | `met` when |
|---|---|---|
| `us-work-authorization`, `us_work_authorization`, `work-authorization`, `work_authorization`, `visa`, `visa-sponsorship` | `eligibility.us_work_authorized` | `True` |
| `security-clearance`, `clearance` | `eligibility.has_clearance` | `True` |
| `relocation` | `eligibility.willing_to_relocate` | `True` |
| `travel` | regex `\d+\s*%` in `req.description` vs `eligibility.max_travel_pct` | extracted % ≤ max |
| `english` | hardcoded | always `met` (native speaker) |
| any other known language (`spanish`, `french`, `german`, `mandarin`) | hardcoded | always `unmet` |
| `mission_alignment`, `mission-alignment` | — | always `unknown` (vibe check, not binary gate) |
| anything else | — | `unknown` |

**Travel parsing detail:** extract the first `\d+\s*%` from `req.description`. If no percentage is found, return `"unknown"`. If found, `met` when extracted % ≤ `eligibility.max_travel_pct`.

**Language detection:** "other known languages" means any skill name that matches the regex `^(spanish|french|german|mandarin)(-fluency|-proficiency)?$`. This is not an open-ended check — only these four are treated as hard unmet gates. Unrecognized language names → `"unknown"`.

**`visa`/`visa-sponsorship` rationale:** these appear on postings to indicate the candidate needs sponsorship. If `us_work_authorized=True`, the candidate does not need sponsorship → gate is `met`. If `False`, they do → `unmet`.

---

## Hard Cap Logic — Placement

The cap must be applied in **both** `_run_assessment()` (partial path) and the full assess equivalent, immediately after `_compute_overall_score()` and before calling `_build_assessment()`.

Exact insertion point in `_run_assessment()` (after line 1537, before line 1538):

```python
overall_score = _compute_overall_score(
    skill_dim,
    experience_dim=experience_dim,
    education_dim=education_dim,
)

# --- ELIGIBILITY CAP ---
pre_cap_grade: str | None = None
unmet_gates = [g for g in eligibility_gates if g.status == "unmet"]
if unmet_gates:
    pre_cap_grade = score_to_grade(overall_score)
    overall_score = 0.0
# -----------------------

partial_percentage = round(overall_score * 100, 1)
```

`pre_cap_grade` is then passed to `_build_assessment()` → `_assemble_fit_assessment()` as a new optional parameter.

---

## Passing `pre_cap_grade` through the call chain

### `_build_assessment()` signature change

Add:

```python
pre_cap_grade: str | None = None,
```

Pass it through to `_assemble_fit_assessment()`.

### `_assemble_fit_assessment()` signature change

Add:

```python
pre_cap_grade: str | None = None,
```

When `pre_cap_grade` is not None (meaning cap was applied), override summary and action items:

```python
if pre_cap_grade is not None:
    blocker_descriptions = "; ".join(g.description for g in (eligibility_gates or []) if g.status == "unmet")
    overall_summary = (
        f"Eligibility blocked: {blocker_descriptions}. "
        f"Skill fit would be {pre_cap_grade} if eligible."
    )
    action_items = [
        f"Eligibility: {blocker_descriptions} — skip this role",
        *action_items[:5],
    ]
```

The existing `_generate_summary()` and `_generate_action_items()` signatures are **not changed** — they run normally; their output is post-processed in `_assemble_fit_assessment` when a cap is active.

---

## Integration: `cli.py` caller

In the `assess` command, when building `AssessmentInput`, populate `curated_eligibility` from the loaded curated resume:

```python
curated_eligibility = curated_resume.eligibility if curated_resume else CandidateEligibility()
inp = AssessmentInput(
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
| `src/claude_candidate/quick_match.py` | Add `curated_eligibility` to `AssessmentInput`; replace `_evaluate_eligibility()` with `evaluate_gates()` call; add hard cap after `_compute_overall_score`; pass `pre_cap_grade` through `_build_assessment` → `_assemble_fit_assessment`; override summary/actions when cap is active |
| `src/claude_candidate/cli.py` | Populate `curated_eligibility` on `AssessmentInput` from loaded curated resume |
| `tests/test_eligibility_evaluator.py` | New test file — unit tests for each gate type |
| `tests/test_quick_match.py` | Tests for cap behavior, summary injection, action item prefix |

---

## Testing

### `test_eligibility_evaluator.py`

- `us_work_authorized=True` → gate for `us-work-authorization` → `met`
- `us_work_authorized=False` → `unmet`
- `us_work_authorized=True` → gate for `visa-sponsorship` → `met`
- `has_clearance=False` + clearance requirement → `unmet`
- `has_clearance=True` + clearance requirement → `met`; works for both `security-clearance` and `clearance` skill names
- `max_travel_pct=40` + "50% travel required" → `unmet`
- `max_travel_pct=40` + "30% travel required" → `met`
- travel requirement with no `%` in description → `unknown`
- `english` fluency requirement → always `met`
- `spanish` / `french` / `german` / `mandarin` requirement → always `unmet`
- `mission_alignment` requirement → always `unknown`
- unknown requirement type → `unknown`
- empty `reqs` list → empty gates list

### `test_quick_match.py` additions

- Unmet gate → `overall_grade == "F"`, `overall_score == 0.0`, `should_apply == "no"`
- Unmet gate → `overall_summary` starts with `"Eligibility blocked:"`
- Unmet gate → `action_items[0]` starts with `"Eligibility:"`
- Unmet gate + high skill score → counterfactual grade (e.g. `"B+"`) appears in `overall_summary`
- Multiple unmet gates → all descriptions appear in summary
- All gates `met` → score unchanged, grade reflects actual skill fit
- All gates `unknown` → score unchanged (no cap applied)
- No eligibility requirements → `eligibility_gates == []`, score unchanged
- Partial assess path (`_run_assessment`) → cap applies there too
