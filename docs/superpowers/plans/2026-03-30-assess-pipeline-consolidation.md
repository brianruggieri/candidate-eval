# Assessment Pipeline Consolidation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate scoring divergence between CLI, server partial, server full, and reassess batch by routing all four through the same `engine.assess()` path with a shared input preparation helper.

**Architecture:** A new `prepare_assess_inputs()` function in `src/claude_candidate/scoring/__init__.py` resolves `work_preferences` and `company_profile` once. All four call sites spread the result into `engine.assess()`. The server enrichment endpoint stops doing manual scoring and instead re-runs the engine with the newly available `CompanyProfile`.

**Tech Stack:** Python 3.11+, pydantic v2, FastAPI, pytest, click

---

### Task 1: Add `prepare_assess_inputs()` helper

**Files:**
- Modify: `src/claude_candidate/scoring/__init__.py`
- Create: `tests/test_prepare_assess_inputs.py`

- [ ] **Step 1: Write failing tests for `prepare_assess_inputs()`**

Create `tests/test_prepare_assess_inputs.py`:

```python
"""Tests for the shared prepare_assess_inputs() helper."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.work_preferences import WorkPreferences
from claude_candidate.scoring import prepare_assess_inputs


class TestPrepareAssessInputs:
	def test_loads_work_preferences_from_file(self, tmp_path, monkeypatch):
		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
		)
		prefs_path = tmp_path / "work_preferences.json"
		prefs.save(prefs_path)
		monkeypatch.setenv("HOME", str(tmp_path))
		# prepare_assess_inputs uses Path.home() / ".claude-candidate" / "work_preferences.json"
		cc_dir = tmp_path / ".claude-candidate"
		cc_dir.mkdir()
		prefs.save(cc_dir / "work_preferences.json")

		result = prepare_assess_inputs("TestCo")
		assert result["work_preferences"] is not None
		assert result["work_preferences"].remote_preference == "remote_first"

	def test_returns_none_preferences_when_file_missing(self, tmp_path, monkeypatch):
		monkeypatch.setenv("HOME", str(tmp_path))
		result = prepare_assess_inputs("TestCo")
		assert result["work_preferences"] is None

	def test_builds_company_profile_from_culture_signals(self, tmp_path, monkeypatch):
		monkeypatch.setenv("HOME", str(tmp_path))
		result = prepare_assess_inputs(
			"TestCo",
			culture_signals=["collaborative", "fast-paced"],
			tech_stack=["python", "react"],
		)
		cp = result["company_profile"]
		assert cp is not None
		assert cp.company_name == "TestCo"
		assert "collaborative" in cp.culture_keywords
		assert "python" in cp.tech_stack_public

	def test_no_company_profile_when_no_signals(self, tmp_path, monkeypatch):
		monkeypatch.setenv("HOME", str(tmp_path))
		result = prepare_assess_inputs("TestCo")
		assert result["company_profile"] is None

	def test_passes_through_existing_company_profile(self, tmp_path, monkeypatch):
		monkeypatch.setenv("HOME", str(tmp_path))
		existing = CompanyProfile(
			company_name="TestCo",
			mission_statement="We build things",
			culture_keywords=["innovation"],
		)
		result = prepare_assess_inputs("TestCo", company_profile=existing)
		assert result["company_profile"] is existing
		assert result["company_profile"].mission_statement == "We build things"

	def test_existing_company_profile_takes_precedence_over_signals(self, tmp_path, monkeypatch):
		monkeypatch.setenv("HOME", str(tmp_path))
		existing = CompanyProfile(
			company_name="TestCo",
			culture_keywords=["existing"],
		)
		result = prepare_assess_inputs(
			"TestCo",
			culture_signals=["ignored"],
			company_profile=existing,
		)
		assert result["company_profile"].culture_keywords == ["existing"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_prepare_assess_inputs.py -v`
Expected: `ImportError: cannot import name 'prepare_assess_inputs'`

- [ ] **Step 3: Implement `prepare_assess_inputs()`**

Add to the bottom of `src/claude_candidate/scoring/__init__.py`, before the `__all__` list:

```python
# ---------------------------------------------------------------------------
# Shared assessment input preparation
# ---------------------------------------------------------------------------
from pathlib import Path as _Path


def prepare_assess_inputs(
	company: str,
	*,
	culture_signals: list[str] | None = None,
	tech_stack: list[str] | None = None,
	company_profile: "CompanyProfile | None" = None,
) -> dict:
	"""Resolve work_preferences and company_profile for engine.assess().

	Returns dict with keys: work_preferences, company_profile.
	Designed to be **kwargs'd into engine.assess().
	"""
	from claude_candidate.schemas.company_profile import CompanyProfile as _CP
	from claude_candidate.schemas.work_preferences import WorkPreferences

	prefs_path = _Path.home() / ".claude-candidate" / "work_preferences.json"
	work_preferences = WorkPreferences.load(prefs_path)

	if company_profile is None and (culture_signals or tech_stack):
		company_profile = _CP(
			company_name=company,
			culture_keywords=culture_signals or [],
			tech_stack_public=tech_stack or [],
		)

	return {
		"work_preferences": work_preferences,
		"company_profile": company_profile,
	}
```

Also add `"prepare_assess_inputs"` to the `__all__` list.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_prepare_assess_inputs.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_prepare_assess_inputs.py src/claude_candidate/scoring/__init__.py
git commit -m "Add prepare_assess_inputs() shared helper for assessment pipeline"
```

---

### Task 2: Wire CLI `assess` through `prepare_assess_inputs()`

**Files:**
- Modify: `src/claude_candidate/cli.py:79-158`
- Modify: `tests/test_integration.py`

- [ ] **Step 1: Write failing test for CLI assess with preferences**

Add to `tests/test_integration.py` in `TestAssessCommand`:

```python
def test_assess_includes_culture_fit_when_preferences_exist(self, fixtures_dir, tmp_path):
	"""CLI assess should produce culture_fit when work_preferences.json exists."""
	output = tmp_path / "assessment.json"

	# Create a work_preferences.json in the fake home
	fake_home = tmp_path / "home"
	cc_dir = fake_home / ".claude-candidate"
	cc_dir.mkdir(parents=True)
	prefs = {
		"remote_preference": "remote_first",
		"company_size": ["startup"],
		"culture_values": ["transparency"],
		"culture_avoid": [],
	}
	(cc_dir / "work_preferences.json").write_text(json.dumps(prefs))

	runner = CliRunner()
	with patch.dict("os.environ", {"HOME": str(fake_home)}):
		result = runner.invoke(
			main,
			[
				"assess",
				"--profile",
				str(fixtures_dir / "sample_candidate_profile.json"),
				"--resume",
				str(fixtures_dir / "sample_resume_profile.json"),
				"--job",
				str(fixtures_dir / "sample_job_posting.txt"),
				"--company",
				"AI Tools Corp",
				"--title",
				"Senior AI Engineer",
				"--seniority",
				"senior",
				"--output",
				str(output),
			],
		)

	assert result.exit_code == 0, f"CLI failed: {result.output}"
	data = json.loads(output.read_text())
	# Culture fit should be populated (not None) when preferences exist
	# Note: culture_fit may still be None if no company signals exist,
	# but work_preferences should at least be passed to the engine.
	# Check app_version to confirm v0.9 pipeline ran.
	assert data["app_version"] == "0.9.0"
```

Note: Add `from unittest.mock import patch` to the test file imports if not already present.

- [ ] **Step 2: Run test to verify it fails (or passes with wrong reason)**

Run: `.venv/bin/python -m pytest tests/test_integration.py::TestAssessCommand::test_assess_includes_culture_fit_when_preferences_exist -v`

- [ ] **Step 3: Wire `prepare_assess_inputs()` into CLI assess**

In `src/claude_candidate/cli.py`, modify the `assess` function. After the `engine = QuickMatchEngine(merged)` line (around line 148), add the helper call and spread:

Replace the block at lines 148-158:
```python
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
	)
```

With:
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_integration.py::TestAssessCommand -v`
Expected: All tests PASS (including existing ones — no regression)

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/cli.py tests/test_integration.py
git commit -m "Wire CLI assess through prepare_assess_inputs()"
```

---

### Task 3: Wire server `/api/assess/partial` through `prepare_assess_inputs()`

**Files:**
- Modify: `src/claude_candidate/server.py:476-488`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write failing test for partial assess with preferences**

Add to `tests/test_server.py` in `TestAssessPartialEndpoint`:

```python
async def test_assess_partial_includes_culture_when_preferences_exist(
	self, client_with_profile: AsyncClient
):
	"""Partial assessment should include culture_fit when preferences are loaded."""
	from claude_candidate.schemas.work_preferences import WorkPreferences

	mock_prefs = WorkPreferences(
		remote_preference="remote_first",
		company_size=["startup"],
		culture_values=["transparency"],
	)
	payload = dict(SAMPLE_ASSESS_PAYLOAD)
	payload["culture_signals"] = ["collaborative", "remote-friendly"]

	with patch(
		"claude_candidate.scoring.WorkPreferences.load",
		return_value=mock_prefs,
	):
		resp = await client_with_profile.post("/api/assess/partial", json=payload)

	assert resp.status_code == 200
	data = resp.json()
	# With preferences AND culture signals, culture_fit should be scored
	assert data.get("culture_fit") is not None
	assert "score" in data["culture_fit"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestAssessPartialEndpoint::test_assess_partial_includes_culture_when_preferences_exist -v`
Expected: FAIL — `culture_fit` is None because preferences aren't passed

- [ ] **Step 3: Wire `prepare_assess_inputs()` into partial endpoint**

In `src/claude_candidate/server.py`, in `_run_quick_assess()`, replace the block at lines 476-488:

```python
		# Run assessment
		engine = QuickMatchEngine(merged)
		assessment = engine.assess(
			requirements=requirements,
			company=req.company,
			title=req.title,
			posting_url=req.posting_url,
			source="api",
			seniority=req.seniority,
			culture_signals=req.culture_signals,
			tech_stack=req.tech_stack,
			curated_eligibility=curated_eligibility,
		)
```

With:

```python
		# Run assessment
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

Note: `culture_signals` and `tech_stack` are no longer passed directly — they flow through `prepare_assess_inputs()` into `company_profile`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestAssessPartialEndpoint -v`
Expected: All tests PASS

- [ ] **Step 5: Run full server test suite for regression**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/server.py tests/test_server.py
git commit -m "Wire server partial assess through prepare_assess_inputs()"
```

---

### Task 4: Refactor server enrichment (`/api/assess/full`) to use engine

**Files:**
- Modify: `src/claude_candidate/server.py:531-729`
- Modify: `tests/test_server.py`

This is the largest change. The enrichment endpoint currently does manual scoring outside the engine. We replace that with a re-run through `engine.assess()`.

- [ ] **Step 1: Write a regression test for enrichment output shape**

Add to `tests/test_server.py` in `TestAssessFullEndpoint`:

```python
async def test_assess_full_engine_produces_consistent_output(
	self, client_with_profile: AsyncClient
):
	"""Full assessment via engine should have same structure as partial."""
	partial_resp = await client_with_profile.post(
		"/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD
	)
	aid = partial_resp.json()["assessment_id"]
	partial_keys = set(partial_resp.json().keys())

	from claude_candidate.schemas.work_preferences import WorkPreferences

	mock_prefs = WorkPreferences(
		remote_preference="remote_first",
		company_size=["startup"],
		culture_values=["transparency"],
	)
	with (
		patch(
			"claude_candidate.company_research.research_company",
			return_value={
				"mission": "Building developer tools",
				"values": ["transparency", "impact"],
				"culture_signals": ["collaborative", "remote-friendly"],
				"tech_philosophy": "Python-first",
				"ai_native": True,
				"product_domains": ["developer-tooling"],
				"team_size_signal": "startup (<50)",
			},
		),
		patch(
			"claude_candidate.schemas.work_preferences.WorkPreferences.load",
			return_value=mock_prefs,
		),
	):
		full_resp = await client_with_profile.post(
			"/api/assess/full", json={"assessment_id": aid}
		)

	full_data = full_resp.json()
	assert full_data["assessment_phase"] == "full"
	# Core assessment fields must be present
	assert "overall_score" in full_data
	assert "overall_grade" in full_data
	assert "skill_match" in full_data
	assert "skill_matches" in full_data
	assert "must_have_coverage" in full_data
	# Mission and culture should be populated with rich research
	assert full_data["mission_alignment"] is not None
	assert full_data["culture_fit"] is not None
```

- [ ] **Step 2: Run test to verify it passes (baseline — existing code)**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestAssessFullEndpoint::test_assess_full_engine_produces_consistent_output -v`
Expected: PASS (this tests the current behavior as a baseline)

- [ ] **Step 3: Refactor the enrichment endpoint**

In `src/claude_candidate/server.py`, replace the manual scoring block in `assess_full()`. The section from "# 4. Build merged profile and engine" (line 619) through "# Update skill weight for consistency" (line 714) gets replaced.

Keep lines 531-617 (company research + CompanyProfile construction) unchanged.

Replace lines 619-727 with:

```python
		# 4. Re-run full assessment through the engine with enriched company profile
		merged_profile = _build_merged_profile()
		if merged_profile is None:
			raise HTTPException(
				status_code=422,
				detail="No candidate profile loaded.",
			)

		# Recover original requirements from stored assessment
		from claude_candidate.schemas.job_requirements import QuickRequirement

		stored_reqs = data.get("input_requirements", [])
		requirements = []
		for r in stored_reqs:
			try:
				requirements.append(QuickRequirement(**r))
			except Exception:
				continue

		if not requirements:
			raise HTTPException(
				status_code=422,
				detail="No stored requirements found — cannot re-score.",
			)

		# Load curated eligibility (same pattern as partial endpoint)
		from claude_candidate.schemas.curated_resume import CandidateEligibility
		from pydantic import ValidationError

		curated_eligibility: CandidateEligibility | None = None
		curated_data = get_profiles().get("curated_resume")
		if isinstance(curated_data, dict):
			try:
				curated_eligibility = CandidateEligibility.model_validate(
					curated_data.get("eligibility", {})
				)
			except ValidationError:
				logger.debug("Could not parse curated eligibility — using defaults")

		# Run through canonical engine path
		from claude_candidate.scoring import prepare_assess_inputs

		meta = data.get("input_meta") or {}
		extras = prepare_assess_inputs(company, company_profile=company_profile)
		engine = QuickMatchEngine(merged_profile)
		assessment = engine.assess(
			requirements=requirements,
			company=company,
			title=data.get("job_title", ""),
			posting_url=data.get("posting_url"),
			source="enrich",
			seniority=meta.get("seniority", "unknown"),
			curated_eligibility=curated_eligibility,
			**extras,
		)

		# Convert engine output to dict for storage
		updated = json.loads(assessment.to_json())
		updated["assessment_phase"] = "full"

		# Carry forward stored input_requirements and input_meta
		updated["input_requirements"] = data.get("input_requirements", [])
		updated["input_meta"] = meta

		# AI engineering scores from candidate profile (pre-computed, optional)
		profiles = get_profiles()
		candidate_data = profiles.get("candidate")
		if candidate_data:
			ai_scores = candidate_data.get("ai_engineering_scores")
			if ai_scores:
				updated["ai_engineering_scores"] = ai_scores
```

Keep the narrative verdict section (lines ~678-692) but update it to use `updated` dict:

```python
		# 5. Narrative verdict + receptivity signal (best-effort)
		narrative_result = None
		try:
			from claude_candidate.generator import generate_narrative_verdict

			loop = asyncio.get_event_loop()
			research_data = research or {}
			narrative_result = await loop.run_in_executor(
				None,
				lambda: generate_narrative_verdict(updated, research_data),
			)
		except Exception:
			pass  # Narrative is best-effort

		if narrative_result:
			updated["narrative_verdict"] = narrative_result.get("narrative")
			updated["receptivity_level"] = narrative_result.get("receptivity")
			updated["receptivity_reason"] = narrative_result.get("receptivity_reason")

		# Company enrichment metadata
		updated["company_profile_summary"] = (
			company_profile.product_description if company_profile else "No enrichment data available"
		)
		updated["company_enrichment_quality"] = (
			company_profile.enrichment_quality if company_profile else "none"
		)
```

Keep the storage section (lines ~716-727) but use the engine's output directly:

```python
		# 6. Save updated assessment to store
		flat: dict[str, Any] = {
			"assessment_id": data.get("assessment_id", req.assessment_id),
			"assessed_at": data.get("assessed_at"),
			"job_title": updated.get("job_title"),
			"company_name": company,
			"posting_url": data.get("posting_url"),
			"overall_score": updated["overall_score"],
			"overall_grade": updated["overall_grade"],
			"should_apply": updated.get("should_apply"),
			"data": updated,
		}
		await store.save_assessment(flat)

		return updated
```

- [ ] **Step 4: Run the full endpoint test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestAssessFullEndpoint -v`
Expected: All tests PASS

- [ ] **Step 5: Run the full server test suite**

Run: `.venv/bin/python -m pytest tests/test_server.py -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/server.py tests/test_server.py
git commit -m "Refactor server enrichment to re-run through engine.assess()"
```

---

### Task 5: Wire server reassess batch through `prepare_assess_inputs()`

**Files:**
- Modify: `src/claude_candidate/server.py:859-901`

- [ ] **Step 1: Wire `prepare_assess_inputs()` into reassess batch**

In `src/claude_candidate/server.py`, in the `_run_batch()` function, replace lines 880-891:

```python
				meta = data.get("input_meta") or {}
				assessment = engine.assess(
					requirements=reqs,
					company=meta.get("company") or data.get("company_name", ""),
					title=meta.get("title") or data.get("job_title", ""),
					posting_url=meta.get("posting_url") or data.get("posting_url"),
					source="reassess",
					seniority=meta.get("seniority", "unknown"),
					culture_signals=meta.get("culture_signals"),
					tech_stack=meta.get("tech_stack"),
					curated_eligibility=curated_eligibility,
				)
```

With:

```python
				meta = data.get("input_meta") or {}
				company_name = meta.get("company") or data.get("company_name", "")
				extras = prepare_assess_inputs(
					company_name,
					culture_signals=meta.get("culture_signals"),
					tech_stack=meta.get("tech_stack"),
				)
				assessment = engine.assess(
					requirements=reqs,
					company=company_name,
					title=meta.get("title") or data.get("job_title", ""),
					posting_url=meta.get("posting_url") or data.get("posting_url"),
					source="reassess",
					seniority=meta.get("seniority", "unknown"),
					curated_eligibility=curated_eligibility,
					**extras,
				)
```

Also add the import at the top of `_run_batch()` (or alongside existing imports in the reassess endpoint):

```python
from claude_candidate.scoring import prepare_assess_inputs
```

- [ ] **Step 2: Run reassess tests**

Run: `.venv/bin/python -m pytest tests/test_server.py -k reassess -v`
Expected: All reassess tests PASS

- [ ] **Step 3: Commit**

```bash
git add src/claude_candidate/server.py
git commit -m "Wire server reassess batch through prepare_assess_inputs()"
```

---

### Task 6: Full test suite + golden set regression check

**Files:**
- No code changes — verification only

- [ ] **Step 1: Run the full fast test suite**

Run: `.venv/bin/python -m pytest -q --tb=short`
Expected: All tests PASS, no regressions

- [ ] **Step 2: Run the golden set benchmark**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Expected: No grade regressions from pre-change baseline. Record the results.

- [ ] **Step 3: Run a CLI assessment with preferences to verify end-to-end**

Run:
```bash
.venv/bin/claude-candidate assess \
  --profile ~/.claude-candidate/candidate_profile.json \
  --resume ~/.claude-candidate/curated_resume.json \
  --job /tmp/anthropic-posting.txt \
  --company "Anthropic" \
  --title "Software Engineer, Claude Code" \
  --seniority mid \
  -o /tmp/anthropic-v091.json
```

Verify: `culture_fit` field in output is no longer `null` (if preferences file exists).

- [ ] **Step 4: Commit test results if benchmark_history.jsonl changed**

```bash
git add tests/golden_set/benchmark_history.jsonl
git commit -m "Record benchmark results after pipeline consolidation"
```

---

### Task 7: Version bump + documentation update

**Files:**
- Modify: `pyproject.toml`
- Modify: `extension/manifest.json`
- Modify: `src/claude_candidate/__init__.py`
- Modify: `CLAUDE.md`
- Modify: `.claude/full-runthrough.md`

- [ ] **Step 1: Bump version to 0.9.1**

In `pyproject.toml`, change:
```toml
version = "0.9.1"
```

In `extension/manifest.json`, change:
```json
"version": "0.9.1",
```

In `src/claude_candidate/__init__.py`, change:
```python
__version__ = "0.9.1"
```

- [ ] **Step 2: Update CLAUDE.md architecture table**

In `CLAUDE.md`, update the `quick_match.py` row in the Key modules table:

```markdown
| `quick_match.py` | Scoring engine — matches profile skills against job requirements |
```

Replace with:

```markdown
| `quick_match.py` | Scoring engine — matches profile skills against job requirements |
| `scoring/__init__.py` | Public API + `prepare_assess_inputs()` shared helper for CLI/server |
```

- [ ] **Step 3: Update full-runthrough.md Phase 6**

In `.claude/full-runthrough.md`, update Phase 6 to note that assessments now include culture scoring when preferences exist. After the "This prints a fit card" line, add:

```markdown
If `~/.claude-candidate/work_preferences.json` exists (from Phase 5), the assessment includes culture fit scoring. The same scoring pipeline runs in both CLI and server modes.
```

- [ ] **Step 4: Update full-runthrough.md version expectation**

In `.claude/full-runthrough.md`, update Phase 0:

```bash
.venv/bin/claude-candidate --version
# Expected: 0.9.1
```

And update test count expectation if it changed.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml extension/manifest.json src/claude_candidate/__init__.py CLAUDE.md .claude/full-runthrough.md
git commit -m "Bump version to 0.9.1, update docs for pipeline consolidation"
```
