# Eligibility Hard Caps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make eligibility gates (work authorization, clearance, travel, language, relocation) actually block the grade — unmet gates force overall score to 0.0/F regardless of skill fit, with the reason surfaced in summary and action items.

**Architecture:** New `eligibility_evaluator.py` resolves each gate to met/unmet/unknown against a `CandidateEligibility` profile stored in `CuratedResume`. `quick_match.py` calls it, applies a hard cap after scoring, and injects a blocker message. `server.py` re-applies the cap after full-assess recomputation.

**Tech Stack:** Python 3.11+, pydantic v2, pytest. No new dependencies.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/claude_candidate/schemas/curated_resume.py` | Modify | Add `CandidateEligibility` model + `eligibility` field |
| `src/claude_candidate/eligibility_evaluator.py` | **Create** | Gate resolution logic — `evaluate_gates()` |
| `src/claude_candidate/quick_match.py` | Modify | Wire evaluator; add hard cap + UX injection |
| `src/claude_candidate/server.py` | Modify | Re-apply cap in full-assess path |
| `src/claude_candidate/cli.py` | Modify | Load curated resume + pass eligibility to engine |
| `tests/test_eligibility_evaluator.py` | **Create** | Unit tests for every gate type |
| `tests/test_quick_match.py` | Modify | Integration tests for cap behavior |

---

## Task 1: `CandidateEligibility` Schema

**Files:**
- Modify: `src/claude_candidate/schemas/curated_resume.py`
- Test: `tests/test_schemas.py` (add to existing file)

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_schemas.py`:

```python
class TestCandidateEligibility:
	def test_defaults(self):
		from claude_candidate.schemas.curated_resume import CandidateEligibility
		e = CandidateEligibility()
		assert e.us_work_authorized is True
		assert e.max_travel_pct == 40
		assert e.has_clearance is False
		assert e.willing_to_relocate is True

	def test_explicit_values(self):
		from claude_candidate.schemas.curated_resume import CandidateEligibility
		e = CandidateEligibility(us_work_authorized=False, has_clearance=True, max_travel_pct=0, willing_to_relocate=False)
		assert e.us_work_authorized is False
		assert e.has_clearance is True
		assert e.max_travel_pct == 0
		assert e.willing_to_relocate is False

	def test_curated_resume_gets_default_eligibility(self):
		"""CuratedResume JSON without 'eligibility' key loads with permissive defaults."""
		import json
		from claude_candidate.schemas.curated_resume import CandidateEligibility, CuratedResume, CuratedSkill
		from claude_candidate.schemas.candidate_profile import DepthLevel
		from datetime import datetime, timezone
		data = {
			"profile_version": "0.1.0",
			"parsed_at": datetime.now(tz=timezone.utc).isoformat(),
			"source_file_hash": "abc123",
			"source_format": "pdf",
			"curated_skills": [{"name": "python", "depth": "applied"}],
		}
		resume = CuratedResume.model_validate(data)
		# No 'eligibility' key in JSON → defaults kick in
		assert isinstance(resume.eligibility, CandidateEligibility)
		assert resume.eligibility.us_work_authorized is True

	def test_curated_resume_with_eligibility_block(self):
		"""CuratedResume JSON with 'eligibility' key loads correctly."""
		from claude_candidate.schemas.curated_resume import CandidateEligibility, CuratedResume
		from datetime import datetime, timezone
		data = {
			"profile_version": "0.1.0",
			"parsed_at": datetime.now(tz=timezone.utc).isoformat(),
			"source_file_hash": "abc123",
			"source_format": "pdf",
			"curated_skills": [{"name": "python", "depth": "applied"}],
			"eligibility": {
				"us_work_authorized": True,
				"max_travel_pct": 20,
				"has_clearance": False,
				"willing_to_relocate": False,
			},
		}
		resume = CuratedResume.model_validate(data)
		assert resume.eligibility.max_travel_pct == 20
		assert resume.eligibility.willing_to_relocate is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_schemas.py::TestCandidateEligibility -v
```

Expected: `ImportError` or `AttributeError` — `CandidateEligibility` doesn't exist yet.

- [ ] **Step 3: Implement `CandidateEligibility` in `schemas/curated_resume.py`**

Add the model directly above the `CuratedResume` class definition:

```python
class CandidateEligibility(BaseModel):
	"""Candidate's binary eligibility facts — checked against job gate requirements."""

	us_work_authorized: bool = True
	max_travel_pct: int = 40       # candidate's tolerance ceiling (0–100)
	has_clearance: bool = False
	willing_to_relocate: bool = True
```

Add the field to `CuratedResume` (after `curated: bool = True`):

```python
eligibility: CandidateEligibility = Field(default_factory=CandidateEligibility)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_schemas.py::TestCandidateEligibility -v
```

Expected: 4 tests PASS.

- [ ] **Step 5: Run full fast suite to confirm no regressions**

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/schemas/curated_resume.py tests/test_schemas.py
git commit -m "feat: add CandidateEligibility model to CuratedResume schema"
```

---

## Task 2: `eligibility_evaluator.py` Module

**Files:**
- Create: `src/claude_candidate/eligibility_evaluator.py`
- Create: `tests/test_eligibility_evaluator.py`

- [ ] **Step 1: Write all failing tests**

Create `tests/test_eligibility_evaluator.py`:

```python
"""Unit tests for eligibility gate evaluation."""
from __future__ import annotations

import pytest

from claude_candidate.schemas.curated_resume import CandidateEligibility
from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority


def make_req(skill: str, description: str = "") -> QuickRequirement:
	"""Helper: build a minimal eligibility QuickRequirement."""
	return QuickRequirement(
		description=description or skill,
		skill_mapping=[skill],
		priority=RequirementPriority.MUST_HAVE,
		is_eligibility=True,
		source_text=description or skill,
	)


class TestWorkAuthorization:
	def test_us_work_auth_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("us-work-authorization")], CandidateEligibility(us_work_authorized=True))
		assert gates[0].status == "met"

	def test_us_work_auth_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("us-work-authorization")], CandidateEligibility(us_work_authorized=False))
		assert gates[0].status == "unmet"

	def test_work_authorization_alias(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("work-authorization")], CandidateEligibility(us_work_authorized=True))
		assert gates[0].status == "met"

	def test_visa_sponsorship_maps_to_work_auth(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("visa-sponsorship")], CandidateEligibility(us_work_authorized=True))
		assert gates[0].status == "met"

	def test_visa_sponsorship_unmet_when_unauthorized(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("visa-sponsorship")], CandidateEligibility(us_work_authorized=False))
		assert gates[0].status == "unmet"


class TestSecurityClearance:
	def test_clearance_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("security-clearance")], CandidateEligibility(has_clearance=True))
		assert gates[0].status == "met"

	def test_clearance_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("security-clearance")], CandidateEligibility(has_clearance=False))
		assert gates[0].status == "unmet"

	def test_clearance_alias_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("clearance")], CandidateEligibility(has_clearance=True))
		assert gates[0].status == "met"


class TestTravel:
	def test_travel_unmet_when_over_max(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("travel", "50% travel required")],
			CandidateEligibility(max_travel_pct=40),
		)
		assert gates[0].status == "unmet"

	def test_travel_met_when_under_max(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("travel", "30% travel required")],
			CandidateEligibility(max_travel_pct=40),
		)
		assert gates[0].status == "met"

	def test_travel_met_when_equal_to_max(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("travel", "40% travel required")],
			CandidateEligibility(max_travel_pct=40),
		)
		assert gates[0].status == "met"

	def test_travel_unknown_when_no_pct(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates(
			[make_req("travel", "Willingness to travel required")],
			CandidateEligibility(max_travel_pct=40),
		)
		assert gates[0].status == "unknown"


class TestLanguage:
	def test_english_always_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		for skill in ["english", "english-fluency", "english-proficiency"]:
			gates = evaluate_gates([make_req(skill)], CandidateEligibility())
			assert gates[0].status == "met", f"Expected met for {skill}"

	def test_foreign_languages_always_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		for skill in ["spanish", "french", "german", "mandarin"]:
			gates = evaluate_gates([make_req(skill)], CandidateEligibility())
			assert gates[0].status == "unmet", f"Expected unmet for {skill}"

	def test_language_with_fluency_suffix_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("spanish-fluency")], CandidateEligibility())
		assert gates[0].status == "unmet"


class TestMiscGates:
	def test_relocation_met(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("relocation")], CandidateEligibility(willing_to_relocate=True))
		assert gates[0].status == "met"

	def test_relocation_unmet(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("relocation")], CandidateEligibility(willing_to_relocate=False))
		assert gates[0].status == "unmet"

	def test_mission_alignment_always_unknown(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		for skill in ["mission_alignment", "mission-alignment"]:
			gates = evaluate_gates([make_req(skill)], CandidateEligibility())
			assert gates[0].status == "unknown"

	def test_unknown_skill_unknown(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([make_req("some-weird-requirement")], CandidateEligibility())
		assert gates[0].status == "unknown"

	def test_empty_reqs_returns_empty_list(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		gates = evaluate_gates([], CandidateEligibility())
		assert gates == []

	def test_gate_description_matches_requirement(self):
		from claude_candidate.eligibility_evaluator import evaluate_gates
		req = make_req("security-clearance", "Must hold active TS/SCI clearance")
		gates = evaluate_gates([req], CandidateEligibility())
		assert gates[0].description == "Must hold active TS/SCI clearance"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_eligibility_evaluator.py -v
```

Expected: `ModuleNotFoundError: No module named 'claude_candidate.eligibility_evaluator'`

- [ ] **Step 3: Create `src/claude_candidate/eligibility_evaluator.py`**

```python
"""
Evaluate eligibility gates against candidate eligibility profile.

Resolves each eligibility QuickRequirement to "met" / "unmet" / "unknown"
by comparing skill_mapping entries against CandidateEligibility facts.
"""
from __future__ import annotations

import re

from claude_candidate.schemas.curated_resume import CandidateEligibility
from claude_candidate.schemas.fit_assessment import EligibilityGate
from claude_candidate.schemas.job_requirements import QuickRequirement

_WORK_AUTH_SKILLS: frozenset[str] = frozenset({
	"us-work-authorization",
	"us_work_authorization",
	"work-authorization",
	"work_authorization",
	"visa",
	"visa-sponsorship",
})

_CLEARANCE_SKILLS: frozenset[str] = frozenset({"security-clearance", "clearance"})
_RELOCATION_SKILLS: frozenset[str] = frozenset({"relocation"})
_TRAVEL_SKILLS: frozenset[str] = frozenset({"travel"})
_ENGLISH_SKILLS: frozenset[str] = frozenset({"english", "english-fluency", "english-proficiency"})
_MISSION_SKILLS: frozenset[str] = frozenset({"mission_alignment", "mission-alignment"})

_FOREIGN_LANGUAGE_PATTERN: re.Pattern[str] = re.compile(
	r"^(spanish|french|german|mandarin)(-fluency|-proficiency)?$"
)
_PCT_PATTERN: re.Pattern[str] = re.compile(r"(\d+)\s*%")


def _classify(skill: str) -> str:
	s = skill.lower()
	if s in _WORK_AUTH_SKILLS:
		return "work_auth"
	if s in _CLEARANCE_SKILLS:
		return "clearance"
	if s in _RELOCATION_SKILLS:
		return "relocation"
	if s in _TRAVEL_SKILLS:
		return "travel"
	if s in _ENGLISH_SKILLS:
		return "english"
	if _FOREIGN_LANGUAGE_PATTERN.match(s):
		return "foreign_language"
	if s in _MISSION_SKILLS:
		return "mission"
	return "unknown"


def _resolve(req: QuickRequirement, eligibility: CandidateEligibility) -> str:
	for skill in req.skill_mapping:
		category = _classify(skill)
		if category == "work_auth":
			return "met" if eligibility.us_work_authorized else "unmet"
		if category == "clearance":
			return "met" if eligibility.has_clearance else "unmet"
		if category == "relocation":
			return "met" if eligibility.willing_to_relocate else "unmet"
		if category == "travel":
			m = _PCT_PATTERN.search(req.description)
			if m:
				return "met" if int(m.group(1)) <= eligibility.max_travel_pct else "unmet"
			return "unknown"
		if category == "english":
			return "met"
		if category == "foreign_language":
			return "unmet"
		if category == "mission":
			return "unknown"
	return "unknown"


def evaluate_gates(
	reqs: list[QuickRequirement],
	eligibility: CandidateEligibility,
) -> list[EligibilityGate]:
	"""Evaluate eligibility requirements against candidate facts.

	Returns one EligibilityGate per requirement with status resolved to
	"met" / "unmet" / "unknown".
	"""
	return [
		EligibilityGate(
			description=req.description,
			status=_resolve(req, eligibility),
			requirement_text=req.source_text or req.description,
		)
		for req in reqs
	]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv/bin/python -m pytest tests/test_eligibility_evaluator.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full fast suite**

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/eligibility_evaluator.py tests/test_eligibility_evaluator.py
git commit -m "feat: add eligibility_evaluator module with evaluate_gates()"
```

---

## Task 3: Wire Evaluator into `quick_match.py`

**Files:**
- Modify: `src/claude_candidate/quick_match.py:345-358` (`AssessmentInput`), `1461-1486` (`assess()`), `1500-1503` (`_run_assessment` — replace `_evaluate_eligibility` call)

This task wires up the new evaluator but does **not** add the hard cap yet. All existing tests must still pass after this task — the behavior is identical to before (gates still don't affect the grade), but the evaluator is now running.

- [ ] **Step 1: Verify baseline tests pass before touching anything**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py -v
```

Expected: all tests pass. Note the count.

- [ ] **Step 2: Add `curated_eligibility` to `AssessmentInput`**

In `quick_match.py`, add this import near the top of the file (with other dataclass imports):

```python
from dataclasses import dataclass, field
```

(Only if `field` is not already imported — check first. `dataclass` is already imported.)

Then in the `AssessmentInput` dataclass (around line 345), add the new field at the end:

```python
curated_eligibility: CandidateEligibility = field(default_factory=CandidateEligibility)
```

Also add the import at the top of the file (with other schema imports):

```python
from claude_candidate.schemas.curated_resume import CandidateEligibility
```

- [ ] **Step 3: Add `curated_eligibility` parameter to `assess()`**

In the `assess()` method (line 1461), add the new parameter before `elapsed`:

```python
curated_eligibility: CandidateEligibility | None = None,
```

And in the `AssessmentInput(...)` constructor call (line 1475), add:

```python
curated_eligibility=curated_eligibility or CandidateEligibility(),
```

- [ ] **Step 4: Replace `_evaluate_eligibility()` with `evaluate_gates()`**

In `_run_assessment()` (around line 1502), replace:

```python
eligibility_gates = _evaluate_eligibility(eligibility_reqs)
```

with:

```python
from claude_candidate.eligibility_evaluator import evaluate_gates
eligibility_gates = evaluate_gates(eligibility_reqs, inp.curated_eligibility)
```

Delete the old `_evaluate_eligibility()` function entirely (lines 205–217).

- [ ] **Step 5: Run tests to verify no regressions**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py -v
```

Expected: same count as Step 1, all pass. The existing eligibility tests now get `"unknown"` status via the evaluator (since default `CandidateEligibility` leaves clearance/auth unresolved for requirements that don't match any gate).

**Important:** The existing test at `test_eligibility_excluded_from_skill_score` asserts `result.eligibility_gates[0].status == "unknown"` — this must still hold because it uses a `us-work-authorization` requirement and `CandidateEligibility` defaults to `us_work_authorized=True` → gate is `"met"`, not `"unknown"`.

Wait — check: the existing test passes `is_eligibility=True` with `skill_mapping=["us-work-authorization"]`. With `us_work_authorized=True` (default), `evaluate_gates` will return `"met"`, not `"unknown"`. **The existing test assertion `status == "unknown"` will fail.**

Update the failing assertion in `tests/test_quick_match.py` for `test_eligibility_excluded_from_skill_score` and `test_eligibility_gates_populated`:

```python
# Old:
assert result.eligibility_gates[0].status == "unknown"
# New:
assert result.eligibility_gates[0].status == "met"  # us_work_authorized=True is default
```

- [ ] **Step 6: Run full fast suite**

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/claude_candidate/quick_match.py tests/test_quick_match.py
git commit -m "feat: wire eligibility_evaluator into quick_match, remove _evaluate_eligibility()"
```

---

## Task 4: Hard Cap + UX Injection

**Files:**
- Modify: `src/claude_candidate/quick_match.py:1533-1556` (cap insertion), `1558-1615` (`_build_assessment`), `1617-1683` (`_assemble_fit_assessment`)
- Modify: `tests/test_quick_match.py` (add `TestEligibilityHardCap` class)

- [ ] **Step 1: Write failing integration tests**

Add a new class to `tests/test_quick_match.py`. Place it after the existing eligibility test class:

```python
class TestEligibilityHardCap:
	"""Tests that unmet eligibility gates force grade to F."""

	def _make_req(self, skill: str, description: str = "", priority: str = "must_have", is_eligibility: bool = False) -> QuickRequirement:
		return QuickRequirement(
			description=description or skill,
			skill_mapping=[skill],
			priority=RequirementPriority(priority),
			is_eligibility=is_eligibility,
			source_text=description or skill,
		)

	def _clearance_req(self) -> QuickRequirement:
		return self._make_req(
			"security-clearance",
			"Must hold active security clearance",
			is_eligibility=True,
		)

	def test_unmet_gate_forces_f(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.quick_match import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		result = engine.assess(
			requirements=[self._clearance_req(), self._make_req("python", priority="must_have")],
			company="GovCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(has_clearance=False),
		)
		assert result.overall_grade == "F"
		assert result.overall_score == 0.0
		assert result.should_apply == "no"
		assert result.eligibility_passed is False

	def test_unmet_gate_summary_starts_with_blocker(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.quick_match import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		result = engine.assess(
			requirements=[self._clearance_req()],
			company="GovCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(has_clearance=False),
		)
		assert result.overall_summary.startswith("Eligibility blocked:")

	def test_unmet_gate_first_action_item_is_eligibility(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.quick_match import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		result = engine.assess(
			requirements=[self._clearance_req()],
			company="GovCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(has_clearance=False),
		)
		assert result.action_items[0].startswith("Eligibility:")

	def test_counterfactual_grade_in_summary(self, candidate_profile, resume_profile):
		"""Summary includes 'if eligible' clause with counterfactual grade."""
		from claude_candidate.merger import merge_profiles
		from claude_candidate.quick_match import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		result = engine.assess(
			requirements=[self._clearance_req()],
			company="GovCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(has_clearance=False),
		)
		assert "if eligible" in result.overall_summary

	def test_met_gates_no_cap(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.quick_match import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		req = self._make_req(
			"us-work-authorization",
			"Must be authorized to work in the US",
			is_eligibility=True,
		)
		result = engine.assess(
			requirements=[req, self._make_req("python", priority="must_have")],
			company="TestCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(us_work_authorized=True),
		)
		assert result.overall_grade != "F"
		assert result.overall_score > 0.0
		assert not result.overall_summary.startswith("Eligibility blocked:")

	def test_unknown_gates_no_cap(self, candidate_profile, resume_profile):
		"""mission_alignment gates are always unknown — must not trigger cap."""
		from claude_candidate.merger import merge_profiles
		from claude_candidate.quick_match import QuickMatchEngine
		from claude_candidate.schemas.curated_resume import CandidateEligibility

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		mission_req = self._make_req("mission_alignment", "Belief in our mission", is_eligibility=True)
		result = engine.assess(
			requirements=[mission_req, self._make_req("python", priority="must_have")],
			company="TestCo",
			title="Engineer",
			curated_eligibility=CandidateEligibility(),
		)
		assert result.overall_grade != "F"

	def test_no_eligibility_reqs_no_cap(self, candidate_profile, resume_profile):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.quick_match import QuickMatchEngine

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		result = engine.assess(
			requirements=[self._make_req("python", priority="must_have")],
			company="TestCo",
			title="Engineer",
		)
		assert result.eligibility_gates == []
		assert result.overall_grade != "F"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::TestEligibilityHardCap -v
```

Expected: `test_unmet_gate_forces_f` fails — grade is not F (cap not implemented yet).

- [ ] **Step 3: Add cap logic in `_run_assessment()`**

In `quick_match.py`, after the `overall_score = _compute_overall_score(...)` call (line ~1533-1537) and before `partial_percentage = round(...)`, insert:

```python
pre_cap_grade: str | None = None
unmet_gates = [g for g in eligibility_gates if g.status == "unmet"]
if unmet_gates:
	pre_cap_grade = score_to_grade(overall_score)
	overall_score = 0.0
```

- [ ] **Step 4: Thread `pre_cap_grade` through `_build_assessment`**

In `_build_assessment()` signature (line ~1558), add:

```python
pre_cap_grade: str | None = None,
```

In the `_run_assessment()` call to `_build_assessment()` (line ~1542), add:

```python
pre_cap_grade=pre_cap_grade,
```

In `_build_assessment()`'s call to `_assemble_fit_assessment()` (line ~1596), add:

```python
pre_cap_grade=pre_cap_grade,
```

- [ ] **Step 5: Override summary and action items in `_assemble_fit_assessment()`**

In `_assemble_fit_assessment()` signature (line ~1617), add:

```python
pre_cap_grade: str | None = None,
```

At the bottom of `_assemble_fit_assessment()`, immediately before the `return FitAssessment(...)` call, add:

```python
overall_summary = self._generate_summary(summary_inp)
action_items = self._generate_action_items(
	overall_score,
	gaps,
	resume_gaps,
	resume_unverified,
	inp.company,
)
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
```

Then update the `return FitAssessment(...)` call to use the local `overall_summary` and `action_items` variables instead of calling `self._generate_summary(summary_inp)` and `self._generate_action_items(...)` inline. Remove the inline calls that were already there.

- [ ] **Step 6: Run the cap tests**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::TestEligibilityHardCap -v
```

Expected: all tests PASS.

- [ ] **Step 7: Run full fast suite**

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/claude_candidate/quick_match.py tests/test_quick_match.py
git commit -m "feat: hard cap grade to F when eligibility gate is unmet"
```

---

## Task 5: Server Full-Assess Path

**Files:**
- Modify: `src/claude_candidate/server.py:500-501`
- Modify: `tests/test_server.py` (add one test)

- [ ] **Step 1: Write the failing test**

Find the existing full-assess test class in `tests/test_server.py` (search for `assess/full` or `full_assess`). Add:

```python
def test_full_assess_respects_eligibility_cap(self, ...):
	"""When the stored partial assessment has an unmet eligibility gate,
	the full-assess recomputation must not undo the F grade."""
	# Build a mock partial-assessment data dict with an unmet gate
	# and call the full-assess endpoint, assert overall_grade == "F"
	# (Adapt fixture setup to match the existing test pattern in this class)
```

Look at the existing test class setup to match the pattern. The key assertion is:
```python
assert response.json()["overall_grade"] == "F"
```

- [ ] **Step 2: Run the test to verify it fails**

```bash
.venv/bin/python -m pytest tests/test_server.py -k "eligibility_cap" -v
```

Expected: test fails — `overall_grade` is not F (server ignores stored gates).

- [ ] **Step 3: Implement the fix in `server.py`**

After line 501 (`overall_grade = score_to_grade(overall_score)`), add:

```python
# Re-apply eligibility cap if any gate was unmet in the partial assessment
stored_gates = data.get("eligibility_gates", [])
if any(g.get("status") == "unmet" for g in stored_gates):
	overall_score = 0.0
	overall_grade = "F"
```

- [ ] **Step 4: Run the test to verify it passes**

```bash
.venv/bin/python -m pytest tests/test_server.py -k "eligibility_cap" -v
```

Expected: PASS.

- [ ] **Step 5: Run full fast suite**

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/server.py tests/test_server.py
git commit -m "fix: re-apply eligibility cap in server full-assess path"
```

---

## Task 6: CLI Integration

**Files:**
- Modify: `src/claude_candidate/cli.py:45-134` (`assess` command)

- [ ] **Step 1: Add `--curated-resume` option and wire to engine**

In the `assess` command (around line 45), add a new click option after the `--resume` option:

```python
@click.option(
	"--curated-resume",
	type=click.Path(exists=True),
	required=False,
	default=None,
	help="Path to curated resume JSON (default: ~/.claude-candidate/curated_resume.json)",
)
```

Add `curated_resume: str | None` to the `assess()` function signature.

Inside the function body, after loading `rp` (around line 90), add:

```python
from claude_candidate.schemas.curated_resume import CandidateEligibility, CuratedResume

curated_eligibility: CandidateEligibility | None = None
curated_resume_path = Path(curated_resume) if curated_resume else Path.home() / ".claude-candidate" / "curated_resume.json"
if curated_resume_path.exists():
	try:
		curated_r = CuratedResume.from_file(curated_resume_path)
		curated_eligibility = curated_r.eligibility
	except Exception:
		pass  # Malformed curated resume — silently fall back to defaults
```

Then update the `engine.assess()` call (line ~126) to pass `curated_eligibility`:

```python
assessment = engine.assess(
	requirements=requirements,
	company=company,
	title=title,
	posting_url=None,
	source="cli",
	seniority=seniority,
	elapsed=elapsed,
	curated_eligibility=curated_eligibility,
)
```

- [ ] **Step 2: Run full fast suite**

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass.

- [ ] **Step 3: Smoke-test the CLI help to confirm new option appears**

```bash
.venv/bin/python -m claude_candidate.cli assess --help
```

Expected: `--curated-resume` option is listed.

- [ ] **Step 4: Commit**

```bash
git add src/claude_candidate/cli.py
git commit -m "feat: pass curated eligibility to engine.assess() from CLI assess command"
```

---

## Final Verification

- [ ] **Run the full fast suite one last time**

```bash
.venv/bin/python -m pytest
```

Expected: all tests pass, no regressions.

- [ ] **Check git log looks clean**

```bash
git log --oneline -6
```

Expected: 6 commits in clean sequence:
```
feat: pass curated eligibility to engine.assess() from CLI assess command
fix: re-apply eligibility cap in server full-assess path
feat: hard cap grade to F when eligibility gate is unmet
feat: wire eligibility_evaluator into quick_match, remove _evaluate_eligibility()
feat: add eligibility_evaluator module with evaluate_gates()
feat: add CandidateEligibility model to CuratedResume schema
```
