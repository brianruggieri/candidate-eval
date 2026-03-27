# v0.8 Phase 1 (v0.8.0): Accuracy + Correctness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship 6 features that improve scoring accuracy, fix extension correctness bugs, and unify the requirement parsing pipeline — the foundation for all v0.8 accuracy work.

**Architecture:** Parsing pipeline unification creates a single canonical Claude prompt for requirement extraction in `requirement_parser.py`, replacing the server's duplicate. Distillation splits compound requirements at parse time, preserving total weight via `weight_override`. Confidence wiring widens the `compute_match_confidence` impact from ±10% to ±30%. Virtual skill concentration tightens inference thresholds. Per-URL storage fixes cross-tab contamination in the extension. Mission reanalysis adds domain-aware keyword taxonomy and a partial-path proxy.

**Tech Stack:** Python 3.13, pydantic v2, FastAPI, pytest, Chrome MV3 extension (vanilla JS), vitest (new for extension)

**Source Documents:**
- CEO plan: `~/.gstack/projects/brianruggieri-candidate-eval/ceo-plans/2026-03-26-v08-feature-list.md`
- Eng review: `~/.claude/plans/wobbly-brewing-newt.md`
- Phase 0 plan (reference): `docs/superpowers/plans/2026-03-26-v08-phase0-phase1-prereqs.md`

**Parallelization:** Tasks 1-2 are serial (distillation depends on parsing unification). Tasks 3-6 are independent and can run in parallel with each other AND with Tasks 1-2 (eng review decision 2C). Task 7 runs last after all features land.

**Benchmark strategy (eng review 9C):** Each feature predicts which grades shift before implementation. After implementation, verify only predicted grades changed. Recalibrate `expected_grades.json` at end of Phase 1.

---

## File Structure

### New Files
| File | Responsibility |
|------|---------------|
| `extension/utils.js` | Shared `normalizeUrl()` + URL-keyed storage helpers |
| `extension/package.json` | Extension dev dependencies (vitest) |
| `extension/vitest.config.js` | Vitest configuration for extension tests |
| `extension/__tests__/storage.test.js` | URL-keyed storage unit tests |
| `extension/__tests__/chrome-mock.js` | Minimal chrome.storage/chrome.tabs mock |
| `tests/test_distillation.py` | Distillation weight invariant + prompt integration tests |
| `tests/test_mission_reanalysis.py` | Mission taxonomy + partial-path proxy tests |
| `tests/test_pipeline_integration.py` | Full-pipeline integration test (raw text → parser → scoring) |

### Modified Files
| File | Changes |
|------|---------|
| `src/claude_candidate/requirement_parser.py` | Add `build_extraction_prompt()`, `extract_posting_with_claude()`, `compute_distillation_weights()`, distillation prompt instructions |
| `src/claude_candidate/schemas/job_requirements.py` | Add `parent_id`, `weight_override` to `QuickRequirement` |
| `src/claude_candidate/schemas/fit_assessment.py` | Add `parent_id` to `SkillMatchDetail` |
| `src/claude_candidate/server.py` | Replace `_build_extraction_prompt()` with call to `requirement_parser`, add cache version key |
| `src/claude_candidate/scoring/constants.py` | Add `CONFIDENCE_FLOOR`, `MISSION_DOMAIN_TAXONOMY`, raise virtual skill `min_count` thresholds, add `VIRTUAL_SKILL_CONSTITUENT_DEPTH` |
| `src/claude_candidate/scoring/dimensions.py` | Update `_score_requirement()` confidence range, improve `_score_mission_text_alignment()` with domain taxonomy |
| `src/claude_candidate/scoring/matching.py` | Add constituent depth check to `_infer_virtual_skill()` |
| `src/claude_candidate/scoring/engine.py` | Use `weight_override` in `_score_skill_match()`, add mission to partial path |
| `extension/popup.js` | Import `utils.js`, use URL-keyed storage, add distillation preview grouping |
| `extension/background.js` | Import `utils.js`, use URL-keyed storage |
| `extension/popup.html` | Add `<script src="utils.js">` |
| `tests/test_quick_match.py` | Add confidence wiring + concentration tests |
| `tests/test_requirement_parser.py` | Add distillation parsing tests |
| `tests/golden_set/expected_grades.json` | Recalibrate at end of Phase 1 |

## Pre-existing Functions Referenced (do NOT redefine)

These functions already exist in the codebase and are called by new code in this plan:

| Function | Location | Purpose |
|----------|----------|---------|
| `call_claude(prompt, timeout)` | `src/claude_candidate/claude_cli.py` | Calls Claude CLI, returns response string |
| `_strip_markdown_fences(text)` | `src/claude_candidate/requirement_parser.py:85-93` | Removes \`\`\`json fences from Claude output |
| `_validate_requirements(data)` | `src/claude_candidate/requirement_parser.py:108-116` | Converts raw dicts to QuickRequirement objects |
| `normalize_skill_mappings(reqs)` | `src/claude_candidate/requirement_parser.py:177-200` | Normalizes skill names through taxonomy |
| `_auto_tag_education(reqs)` | `src/claude_candidate/server.py` | Tags education-level requirements (server-only) |
| `_compute_overall_score(...)` | `src/claude_candidate/scoring/dimensions.py:480-492` | Weighted sum of dimension scores (already accepts mission_dim) |

---

### Task 1: Parsing Pipeline Unification

**Files:**
- Modify: `src/claude_candidate/requirement_parser.py`
- Modify: `src/claude_candidate/server.py:879-1018`
- Create: `tests/test_pipeline_integration.py`
- Test: `tests/test_requirement_parser.py`

**Benchmark prediction:** No grade changes expected — this is a structural refactor of prompt location, not prompt content. The server's extraction prompt moves verbatim into requirement_parser.py.

- [ ] **Step 1: Write test for `build_extraction_prompt()`**

Add a test that verifies the new function produces the expected prompt structure.

```python
# tests/test_requirement_parser.py — add to existing file

class TestBuildExtractionPrompt:
	def test_returns_string_with_required_fields(self):
		from claude_candidate.requirement_parser import build_extraction_prompt

		prompt = build_extraction_prompt(title="Software Engineer", text="We need Python...")
		assert "company" in prompt
		assert "title" in prompt
		assert "requirements" in prompt
		assert "skill_mapping" in prompt
		assert "is_eligibility" in prompt
		assert "Software Engineer" in prompt
		assert "We need Python" in prompt

	def test_truncates_long_text(self):
		from claude_candidate.requirement_parser import build_extraction_prompt

		long_text = "x" * 20000
		prompt = build_extraction_prompt(title="Test", text=long_text)
		# MAX_EXTRACTION_TEXT = 15000
		assert len(long_text) > 15000
		assert "x" * 15000 in prompt
		assert "x" * 15001 not in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_requirement_parser.py::TestBuildExtractionPrompt -v`
Expected: FAIL with `ImportError: cannot import name 'build_extraction_prompt'`

- [ ] **Step 3: Implement `build_extraction_prompt()` and `extract_posting_with_claude()`**

Move the extraction prompt from `server.py:879-910` into `requirement_parser.py`. Add the full extraction function that handles JSON parsing and skill normalization.

```python
# src/claude_candidate/requirement_parser.py — add after existing imports

MAX_EXTRACTION_TEXT = 15_000
CACHE_PROMPT_VERSION = "v1"  # Bump when prompt changes to invalidate 7-day cache


def build_extraction_prompt(title: str, text: str) -> str:
	"""Build the full posting extraction prompt (company + metadata + requirements).

	Used by both the server (via extract_posting_with_claude) and can be used
	by CLI for full-posting extraction. This is the canonical prompt — do not
	duplicate in server.py.
	"""
	truncated = text[:MAX_EXTRACTION_TEXT]
	return (
		"Extract the job posting from this web page text. "
		"Return ONLY valid JSON with these fields:\n"
		"- company: string (the hiring company name)\n"
		"- title: string (the job title)\n"
		"- description: string (full job description including requirements and qualifications)\n"
		"- location: string or null\n"
		"- seniority: string or null (one of: junior, mid, senior, staff, principal, director)\n"
		"- remote: boolean or null\n"
		"- salary: string or null\n"
		"- requirements: array of objects, each with:\n"
		"  - description: string (human-readable requirement)\n"
		'  - skill_mapping: array of strings (normalized skill names, e.g. ["python", "django"])\n'
		"  - priority: string (one of: must_have, strong_preference, nice_to_have, implied)\n"
		'  - years_experience: integer or null (e.g. 5 for "5+ years")\n'
		'  - education_level: string or null (e.g. "bachelor", "master", "phd")\n'
		"  - source_text: the verbatim sentence or phrase from the posting\n"
		"  - is_eligibility: boolean, true ONLY for non-skill logistical/eligibility requirements\n"
		"    (work authorization, visa sponsorship, travel willingness, language proficiency,\n"
		"    relocation, security clearance, mission/values alignment statements). False for technical\n"
		"    skills, domain experience, and education requirements. Education (bachelor/master/PhD) is\n"
		"    NOT eligibility. Split mixed requirements into separate entries.\n\n"
		"For requirements, extract every qualification, skill, or experience mentioned in the posting. "
		"Use must_have for requirements labeled required/must/essential, "
		"strong_preference for strongly preferred/highly desired, "
		"nice_to_have for preferred/bonus/plus, "
		"and implied for unlabeled qualifications that are clearly expected.\n\n"
		"If this page does not contain a job posting, return all fields as null.\n\n"
		f"Page title: {title}\n"
		f"Page text:\n{truncated}"
	)


def extract_posting_with_claude(title: str, text: str) -> dict:
	"""Extract a full job posting using the canonical extraction prompt.

	Returns a dict with company, title, description, location, seniority,
	remote, salary, and requirements (list of dicts with normalized skill_mapping).

	Raises ClaudeCLIError on CLI failure. Raises ValueError on invalid JSON.
	"""
	prompt = build_extraction_prompt(title, text)
	raw = call_claude(prompt, timeout=120)

	cleaned = _strip_markdown_fences(raw)
	parsed = json.loads(cleaned)
	if not isinstance(parsed, dict):
		raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")

	# Normalize skill mappings through taxonomy + auto-tag education
	if "requirements" in parsed and isinstance(parsed["requirements"], list):
		normalize_skill_mappings(parsed["requirements"])

	return parsed
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_requirement_parser.py::TestBuildExtractionPrompt -v`
Expected: PASS

- [ ] **Step 5: Write test for server integration**

```python
# tests/test_pipeline_integration.py — new file

"""Integration tests for the unified parsing pipeline."""

import pytest
from claude_candidate.requirement_parser import (
	build_extraction_prompt,
	CACHE_PROMPT_VERSION,
)


class TestCachePromptVersion:
	"""Verify the cache version key exists and is a non-empty string."""

	def test_cache_version_is_string(self):
		assert isinstance(CACHE_PROMPT_VERSION, str)
		assert len(CACHE_PROMPT_VERSION) > 0

	def test_prompt_includes_all_requirement_fields(self):
		"""Both CLI and server prompts must extract the same requirement fields."""
		prompt = build_extraction_prompt("Test", "Some job posting text")
		# Fields that must appear in the extraction prompt
		for field in ["description", "skill_mapping", "priority", "years_experience",
					  "education_level", "is_eligibility", "source_text"]:
			assert field in prompt, f"Missing field '{field}' in extraction prompt"
```

- [ ] **Step 6: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_pipeline_integration.py -v`
Expected: PASS

- [ ] **Step 7: Update server to use `requirement_parser.extract_posting_with_claude()`**

Replace `_build_extraction_prompt()` in server.py with a call to the shared function. Add cache version to the cache key.

In `src/claude_candidate/server.py`, replace the `_build_extraction_prompt` function (lines 879-910) and update `extract_posting` (lines 912-1018):

```python
# server.py — replace _build_extraction_prompt and update extract_posting

# Delete the _build_extraction_prompt function entirely (lines 879-910).
# In extract_posting, replace:
#   prompt = _build_extraction_prompt(req.title, req.text)
# with:
from claude_candidate.requirement_parser import (
	extract_posting_with_claude,
	CACHE_PROMPT_VERSION,
)

# Update the cache key to include prompt version:
#   url_hash = hashlib.sha256(cache_url.encode()).hexdigest()[:16]
# becomes:
#   url_hash = hashlib.sha256(f"{CACHE_PROMPT_VERSION}:{cache_url}".encode()).hexdigest()[:16]

# Replace the Claude call + JSON parsing block (lines 927-963) with:
#   try:
#       parsed = await asyncio.get_event_loop().run_in_executor(
#           None, lambda: extract_posting_with_claude(req.title, req.text)
#       )
#   except _claude_cli.ClaudeCLIError as exc:
#       logger.warning("extract-posting: Claude CLI error for %s: %s", cache_url[:80], exc)
#       raise HTTPException(status_code=503, detail=f"Claude CLI error: {exc}") from exc
#   except (json.JSONDecodeError, ValueError) as exc:
#       logger.warning("extract-posting: invalid JSON from Claude for %s", cache_url[:80])
#       raise HTTPException(
#           status_code=502,
#           detail="Extraction failed: invalid response from Claude",
#       ) from exc

# Remove the normalize_skill_mappings call (lines 966-970) — now handled inside
# extract_posting_with_claude(). KEEP the _auto_tag_education call (lines 970) —
# _auto_tag_education is defined in server.py and is NOT part of the parser.
# After extract_posting_with_claude returns, apply _auto_tag_education:
#   if "requirements" in parsed and isinstance(parsed["requirements"], list):
#       _auto_tag_education(parsed["requirements"])
```

- [ ] **Step 8: Run full test suite to verify no regressions**

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass. The server now delegates to requirement_parser for extraction.

- [ ] **Step 9: Commit**

```bash
git add src/claude_candidate/requirement_parser.py src/claude_candidate/server.py tests/test_requirement_parser.py tests/test_pipeline_integration.py
git commit -m "refactor: unify parsing pipeline — extraction prompt in requirement_parser.py"
```

---

### Task 2: Requirement Distillation (#1)

**Files:**
- Modify: `src/claude_candidate/schemas/job_requirements.py:84-99`
- Modify: `src/claude_candidate/schemas/fit_assessment.py:37-47`
- Modify: `src/claude_candidate/requirement_parser.py`
- Modify: `src/claude_candidate/scoring/engine.py:435-475`
- Modify: `src/claude_candidate/scoring/dimensions.py:196-219`
- Modify: `extension/popup.js:292-345`
- Create: `tests/test_distillation.py`

**Benchmark prediction:** Compound requirements that previously scored as `max(best_single, avg_all)` will now be individual scored requirements. Postings with heavy compound requirements (e.g., "Python AND React AND Node") may shift ±1 grade. Expect 2-4 postings to change. Postings with simple single-skill requirements should be unchanged.

- [ ] **Step 1: Write test for QuickRequirement schema changes**

```python
# tests/test_distillation.py — new file

"""Tests for requirement distillation: compound splitting and weight preservation."""

import pytest
from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority, PRIORITY_WEIGHT


class TestQuickRequirementDistillationFields:
	"""Verify new schema fields for distillation."""

	def test_parent_id_defaults_to_none(self):
		req = QuickRequirement(
			description="Python experience",
			skill_mapping=["python"],
			priority=RequirementPriority.MUST_HAVE,
		)
		assert req.parent_id is None

	def test_weight_override_defaults_to_none(self):
		req = QuickRequirement(
			description="Python experience",
			skill_mapping=["python"],
			priority=RequirementPriority.MUST_HAVE,
		)
		assert req.weight_override is None

	def test_parent_id_set(self):
		req = QuickRequirement(
			description="Python experience",
			skill_mapping=["python"],
			priority=RequirementPriority.MUST_HAVE,
			parent_id="compound-1",
		)
		assert req.parent_id == "compound-1"

	def test_weight_override_set(self):
		req = QuickRequirement(
			description="Python experience",
			skill_mapping=["python"],
			priority=RequirementPriority.MUST_HAVE,
			weight_override=1.5,
		)
		assert req.weight_override == 1.5

	def test_serialization_roundtrip(self):
		req = QuickRequirement(
			description="Python",
			skill_mapping=["python"],
			priority=RequirementPriority.MUST_HAVE,
			parent_id="compound-1",
			weight_override=1.5,
		)
		data = req.model_dump()
		restored = QuickRequirement(**data)
		assert restored.parent_id == "compound-1"
		assert restored.weight_override == 1.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_distillation.py::TestQuickRequirementDistillationFields -v`
Expected: FAIL — `parent_id` and `weight_override` don't exist on `QuickRequirement`

- [ ] **Step 3: Add schema fields to QuickRequirement**

```python
# src/claude_candidate/schemas/job_requirements.py — update QuickRequirement (line 84-99)

class QuickRequirement(BaseModel):
	"""
	Lightweight requirement for fast matching in the browser extension flow.

	Stripped-down version of JobRequirement that skips evidence_needed
	for speed. Produced by the QuickMatchEngine's internal parser or
	the enriched extraction prompt rather than the full Job Parser agent.
	"""

	description: str
	skill_mapping: list[str] = Field(min_length=1)
	priority: RequirementPriority
	years_experience: int | None = None
	education_level: str | None = None  # "bachelor", "master", "phd", etc.
	source_text: str = ""  # Original text fragment this was extracted from
	is_eligibility: bool = False  # True = binary gate (work auth, travel, language), not scored
	parent_id: str | None = None  # Links distilled sub-reqs to compound parent group
	weight_override: float | None = None  # When set, overrides PRIORITY_WEIGHT lookup
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_distillation.py::TestQuickRequirementDistillationFields -v`
Expected: PASS

- [ ] **Step 5: Write test for `compute_distillation_weights()`**

```python
# tests/test_distillation.py — add to existing file

from claude_candidate.requirement_parser import compute_distillation_weights


class TestComputeDistillationWeights:
	"""Weight invariant: total weight before == total weight after distillation."""

	def test_non_distilled_requirements_unchanged(self):
		"""Requirements without parent_id get no weight_override."""
		reqs = [
			QuickRequirement(description="Python", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE),
			QuickRequirement(description="React", skill_mapping=["react"], priority=RequirementPriority.NICE_TO_HAVE),
		]
		compute_distillation_weights(reqs)
		assert reqs[0].weight_override is None
		assert reqs[1].weight_override is None

	def test_distilled_pair_splits_weight(self):
		"""Two sub-reqs from a must_have compound each get 3.0/2 = 1.5."""
		reqs = [
			QuickRequirement(description="Python", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
			QuickRequirement(description="React", skill_mapping=["react"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
		]
		compute_distillation_weights(reqs)
		assert reqs[0].weight_override == pytest.approx(1.5)
		assert reqs[1].weight_override == pytest.approx(1.5)

	def test_distilled_triple_splits_weight(self):
		"""Three sub-reqs from a strong_preference compound each get 2.0/3."""
		reqs = [
			QuickRequirement(description="A", skill_mapping=["python"], priority=RequirementPriority.STRONG_PREFERENCE, parent_id="c2"),
			QuickRequirement(description="B", skill_mapping=["react"], priority=RequirementPriority.STRONG_PREFERENCE, parent_id="c2"),
			QuickRequirement(description="C", skill_mapping=["docker"], priority=RequirementPriority.STRONG_PREFERENCE, parent_id="c2"),
		]
		compute_distillation_weights(reqs)
		expected = 2.0 / 3
		for req in reqs:
			assert req.weight_override == pytest.approx(expected)

	def test_weight_invariant(self):
		"""Total effective weight before distillation == total after."""
		# Before: one must_have compound = weight 3.0
		# After: two sub-reqs each at 1.5 = total 3.0
		reqs = [
			QuickRequirement(description="Python", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
			QuickRequirement(description="React", skill_mapping=["react"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
			QuickRequirement(description="Docker", skill_mapping=["docker"], priority=RequirementPriority.NICE_TO_HAVE),
		]
		compute_distillation_weights(reqs)
		total = 0.0
		for req in reqs:
			w = req.weight_override if req.weight_override is not None else PRIORITY_WEIGHT[req.priority]
			total += w
		# Expected: 1.5 + 1.5 + 1.0 = 4.0 (same as 3.0 + 1.0 original)
		assert total == pytest.approx(4.0)

	def test_mixed_groups(self):
		"""Multiple compound groups get independent weight splits."""
		reqs = [
			QuickRequirement(description="A", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
			QuickRequirement(description="B", skill_mapping=["react"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
			QuickRequirement(description="C", skill_mapping=["docker"], priority=RequirementPriority.NICE_TO_HAVE, parent_id="c2"),
			QuickRequirement(description="D", skill_mapping=["k8s"], priority=RequirementPriority.NICE_TO_HAVE, parent_id="c2"),
		]
		compute_distillation_weights(reqs)
		assert reqs[0].weight_override == pytest.approx(1.5)  # 3.0/2
		assert reqs[1].weight_override == pytest.approx(1.5)
		assert reqs[2].weight_override == pytest.approx(0.5)  # 1.0/2
		assert reqs[3].weight_override == pytest.approx(0.5)
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_distillation.py::TestComputeDistillationWeights -v`
Expected: FAIL with `ImportError: cannot import name 'compute_distillation_weights'`

- [ ] **Step 7: Implement `compute_distillation_weights()`**

```python
# src/claude_candidate/requirement_parser.py — add after normalize_skill_mappings

def compute_distillation_weights(requirements: list[QuickRequirement]) -> list[QuickRequirement]:
	"""Compute weight_override for distilled requirements.

	For requirements sharing a parent_id, weight_override = base_priority_weight / group_size.
	This preserves the total weight of the original compound requirement.
	Requirements without parent_id are left unchanged.

	Mutates in place and returns the list for chaining.
	"""
	groups: dict[str, list[QuickRequirement]] = {}
	for req in requirements:
		if req.parent_id:
			groups.setdefault(req.parent_id, []).append(req)
	for group in groups.values():
		base_weight = PRIORITY_WEIGHT.get(group[0].priority, 1.0)
		override = base_weight / len(group)
		for req in group:
			req.weight_override = override
	return requirements
```

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_distillation.py::TestComputeDistillationWeights -v`
Expected: PASS

- [ ] **Step 9: Update extraction prompt with distillation instructions**

Add distillation instructions to `build_extraction_prompt()` in `requirement_parser.py`. Insert after the `is_eligibility` field definition and before "For requirements, extract every qualification...":

```python
# Add to the prompt string in build_extraction_prompt(), after the is_eligibility definition:

"  - parent_id: string or null. If this requirement was split from a compound requirement\n"
"    that mentions multiple distinct skills (e.g., '5+ years of Python and React'), set\n"
"    parent_id to a shared identifier (e.g., 'compound-1') linking all parts. Each split\n"
"    requirement should have only ONE skill in skill_mapping. Simple single-skill\n"
"    requirements should have parent_id: null.\n\n"
```

Also update `PARSE_PROMPT_TEMPLATE` (the CLI requirements-only prompt) with the same distillation instruction. Add after the `is_eligibility` field:

```python
# Add to PARSE_PROMPT_TEMPLATE, after the is_eligibility field definition:

"  - parent_id: string or null. If a requirement mentions multiple distinct skills\n"
"    (e.g., 'Python and React'), split it into separate requirements with one skill each.\n"
"    Set parent_id to a shared identifier (e.g., 'compound-1') linking all parts of the\n"
"    original compound. Simple requirements: parent_id null.\n"
```

- [ ] **Step 10: Update `extract_posting_with_claude()` to compute distillation weights**

After `normalize_skill_mappings`, call `compute_distillation_weights`:

```python
# In extract_posting_with_claude(), after normalize_skill_mappings:

	if "requirements" in parsed and isinstance(parsed["requirements"], list):
		normalize_skill_mappings(parsed["requirements"])
		# Convert raw dicts to QuickRequirement for weight computation, then back
		validated = _validate_requirements(parsed["requirements"])
		if validated:
			compute_distillation_weights(validated)
			parsed["requirements"] = [r.model_dump() for r in validated]
```

Also update `parse_requirements_with_claude()` to compute weights:

```python
# In parse_requirements_with_claude(), after parse_requirements_from_response:

	try:
		results = parse_requirements_from_response(raw)
		if results:
			compute_distillation_weights(results)
			return results
```

- [ ] **Step 11: Write test for scoring engine weight_override support**

```python
# tests/test_distillation.py — add to existing file

from tests.conftest import *  # noqa: F403 — pulls in shared fixtures


class TestScoringWeightOverride:
	"""Scoring engine uses weight_override when present."""

	def test_weight_override_used_in_scoring(self, minimal_engine):
		"""Distilled requirement's weight_override replaces PRIORITY_WEIGHT."""
		reqs = [
			QuickRequirement(
				description="Python",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
				weight_override=1.5,  # Distilled: 3.0/2
			),
			QuickRequirement(
				description="React",
				skill_mapping=["react"],
				priority=RequirementPriority.MUST_HAVE,
				weight_override=1.5,
			),
		]
		# Score should use 1.5 weight per req, not 3.0
		dim, details = minimal_engine._score_skill_match(reqs, "senior")
		assert len(details) == 2

	def test_non_distilled_uses_priority_weight(self, minimal_engine):
		"""Normal requirements still use PRIORITY_WEIGHT."""
		reqs = [
			QuickRequirement(
				description="Python",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
			),
		]
		dim, details = minimal_engine._score_skill_match(reqs, "senior")
		assert len(details) == 1
```

- [ ] **Step 12: Run test to verify it passes structurally**

Run: `.venv/bin/python -m pytest tests/test_distillation.py::TestScoringWeightOverride -v`
Expected: PASS — tests verify structural behavior (detail count). The weight_override field exists on QuickRequirement (Step 3) but scoring ignores it until Step 13 wires it into `_score_skill_match`. These tests establish a baseline; Step 13 makes weight_override affect the actual weight calculation.

- [ ] **Step 13: Wire weight_override into `_score_skill_match()`**

In `src/claude_candidate/scoring/engine.py`, update the weight lookup in `_score_skill_match()` (line 436):

```python
# Replace:
		weight = PRIORITY_WEIGHT.get(req.priority, 1.0)
# With:
		weight = req.weight_override if req.weight_override is not None else PRIORITY_WEIGHT.get(req.priority, 1.0)
```

- [ ] **Step 14: Add `parent_id` to SkillMatchDetail and wire through**

In `src/claude_candidate/schemas/fit_assessment.py`, add to `SkillMatchDetail` (after `match_type` field at line 47):

```python
	parent_id: str | None = None  # Links distilled sub-reqs to compound parent group
```

In `src/claude_candidate/scoring/dimensions.py`, update `_build_skill_detail()` (around line 213) to pass `parent_id`:

```python
# In _build_skill_detail, add parent_id to the SkillMatchDetail constructor:
	return SkillMatchDetail(
		requirement=req.description,
		priority=req.priority.value,
		match_status=best_status,
		candidate_evidence=(_evidence_summary(best_match) if best_match else "No evidence found"),
		evidence_source=(best_match.source if best_match else EvidenceSource.RESUME_ONLY),
		confidence=conf,
		parent_id=req.parent_id,
	)
```

- [ ] **Step 15: Run full test suite**

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass.

- [ ] **Step 16: Add distillation preview to extension popup**

In `extension/popup.js`, update the skill matches rendering (around line 303) to group distilled requirements:

```javascript
// In the skill matches rendering section, replace the simple forEach with grouping logic:

	// Group distilled requirements by parent_id for compound display
	const groups = new Map(); // parent_id → [match indices]
	matches.forEach((m, i) => {
		if (m.parent_id) {
			if (!groups.has(m.parent_id)) groups.set(m.parent_id, []);
			groups.get(m.parent_id).push(i);
		}
	});
	const renderedAsChild = new Set();
	groups.forEach(indices => indices.forEach(i => renderedAsChild.add(i)));

	matches.forEach((m, i) => {
		const status = m.match_status || '';
		const iconClass = status.includes('strong') || status === 'exceeds' ? 'hit'
			: status === 'no_evidence' ? 'miss' : 'partial';
		const iconChar = iconClass === 'hit' ? '+' : iconClass === 'miss' ? 'x' : '~';
		const cat = categorizeSkill(m);
		const isMissing = cat === 'missing';
		const conf = m.confidence || 0;
		const confFill = conf >= 0.75 ? 'high' : conf >= 0.50 ? 'medium' : 'low';
		const confDisplay = isMissing ? '—' : conf.toFixed(2);
		const confValStyle = isMissing ? ' style="color:#d1d5db"' : '';
		const sourceHtml = isMissing
			? `<span style="font-family:'SF Mono','Fira Code',monospace;font-size:9px;color:#d1d5db;flex-shrink:0">—</span>`
			: `<span class="source-chip ${cat}">${cat}</span>`;

		// Skip children that will be rendered inside compound group
		if (renderedAsChild.has(i)) return;

		const div = document.createElement('div');
		div.className = 'match-item' + (!isMissing && conf <= 0.70 ? ' low-conf' : '');
		div.innerHTML = `
			<span class="match-icon ${iconClass}">${iconChar}</span>
			<span class="match-name">${escHtml(m.requirement || '')}</span>
			<div class="conf-bar-wrap">
				<div class="conf-bar">
					<div class="conf-bar-fill ${isMissing ? '' : confFill}" style="width:${isMissing ? 0 : Math.round(conf * 100)}%"></div>
				</div>
				<span class="conf-val"${confValStyle}>${confDisplay}</span>
			</div>
			${sourceHtml}
		`;
		matchList.appendChild(div);
	});

	// Render compound groups as collapsible sections
	groups.forEach((indices, parentId) => {
		const children = indices.map(i => matches[i]);
		const sourceText = children[0]?.source_text || children.map(c => c.requirement).join(' + ');
		const wrapper = document.createElement('details');
		wrapper.className = 'compound-group';
		const allHit = children.every(c => {
			const s = c.match_status || '';
			return s.includes('strong') || s === 'exceeds';
		});
		const anyMiss = children.some(c => c.match_status === 'no_evidence');
		const groupIcon = allHit ? '+' : anyMiss ? 'x' : '~';
		const groupClass = allHit ? 'hit' : anyMiss ? 'miss' : 'partial';
		wrapper.innerHTML = `<summary class="match-item compound-header">
			<span class="match-icon ${groupClass}">${groupIcon}</span>
			<span class="match-name">Compound: ${escHtml(sourceText)}</span>
			<span class="compound-count">${children.length} skills</span>
		</summary>`;
		children.forEach(child => {
			const cs = child.match_status || '';
			const cIcon = cs.includes('strong') || cs === 'exceeds' ? '+' : cs === 'no_evidence' ? 'x' : '~';
			const cClass = cs.includes('strong') || cs === 'exceeds' ? 'hit' : cs === 'no_evidence' ? 'miss' : 'partial';
			const cCat = categorizeSkill(child);
			const cMissing = cCat === 'missing';
			const cConf = child.confidence || 0;
			const cFill = cConf >= 0.75 ? 'high' : cConf >= 0.50 ? 'medium' : 'low';
			const childDiv = document.createElement('div');
			childDiv.className = 'match-item compound-child';
			childDiv.innerHTML = `
				<span class="match-icon ${cClass}">${cIcon}</span>
				<span class="match-name">${escHtml(child.requirement || '')}</span>
				<div class="conf-bar-wrap">
					<div class="conf-bar">
						<div class="conf-bar-fill ${cMissing ? '' : cFill}" style="width:${cMissing ? 0 : Math.round(cConf * 100)}%"></div>
					</div>
					<span class="conf-val">${cMissing ? '—' : cConf.toFixed(2)}</span>
				</div>
				${cMissing ? '<span style="font-family:monospace;font-size:9px;color:#d1d5db">—</span>' : `<span class="source-chip ${cCat}">${cCat}</span>`}
			`;
			wrapper.appendChild(childDiv);
		});
		matchList.appendChild(wrapper);
	});
```

Add CSS for compound groups in `extension/popup.css`:

```css
/* Compound distillation preview */
.compound-group { border: 1px solid #e5e7eb; border-radius: 6px; margin: 2px 0; }
.compound-group[open] { background: #f9fafb; }
.compound-header { cursor: pointer; }
.compound-header::-webkit-details-marker { display: none; }
.compound-count { font-size: 10px; color: #9ca3af; margin-left: auto; }
.compound-child { padding-left: 24px; border-top: 1px solid #f3f4f6; }
```

- [ ] **Step 17: Run full test suite**

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass.

- [ ] **Step 18: Run benchmark with predicted deltas**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Record results. Compare against baseline (37/47 exact). Note which postings changed and verify they are compound-requirement-heavy postings.

- [ ] **Step 19: Commit**

```bash
git add src/claude_candidate/schemas/job_requirements.py src/claude_candidate/schemas/fit_assessment.py \
  src/claude_candidate/requirement_parser.py src/claude_candidate/scoring/engine.py \
  src/claude_candidate/scoring/dimensions.py tests/test_distillation.py \
  extension/popup.js extension/popup.css
git commit -m "feat: requirement distillation — compound splitting with weight preservation (#1)"
```

---

### Task 3: Per-URL Keyed Storage (#7)

**Files:**
- Create: `extension/utils.js`
- Create: `extension/package.json`
- Create: `extension/vitest.config.js`
- Create: `extension/__tests__/chrome-mock.js`
- Create: `extension/__tests__/storage.test.js`
- Modify: `extension/popup.js:402-537`
- Modify: `extension/background.js:109-129`
- Modify: `extension/popup.html`
- Modify: `extension/manifest.json` (add utils.js to web_accessible_resources if needed)

**Benchmark prediction:** No grade changes — this is an extension-only correctness fix.

- [ ] **Step 1: Set up extension test infrastructure**

```json
// extension/package.json
{
	"name": "candidate-eval-extension",
	"private": true,
	"type": "module",
	"devDependencies": {
		"vitest": "^3.0.0"
	},
	"scripts": {
		"test": "vitest run",
		"test:watch": "vitest"
	}
}
```

```javascript
// extension/vitest.config.js
import { defineConfig } from 'vitest/config';

export default defineConfig({
	test: {
		environment: 'node',
		include: ['__tests__/**/*.test.js'],
	},
});
```

```javascript
// extension/__tests__/chrome-mock.js
/**
 * Minimal chrome.storage.local mock for vitest.
 * Stores data in a plain Map. All callbacks are synchronous for test simplicity.
 */
const store = new Map();

export function resetStore() {
	store.clear();
}

export const chrome = {
	storage: {
		local: {
			get(keys, cb) {
				const result = {};
				const keyList = Array.isArray(keys) ? keys : [keys];
				for (const k of keyList) {
					if (store.has(k)) result[k] = structuredClone(store.get(k));
				}
				if (cb) cb(result);
				return Promise.resolve(result);
			},
			set(items, cb) {
				for (const [k, v] of Object.entries(items)) {
					store.set(k, structuredClone(v));
				}
				if (cb) cb();
				return Promise.resolve();
			},
			remove(keys, cb) {
				const keyList = Array.isArray(keys) ? keys : [keys];
				for (const k of keyList) store.delete(k);
				if (cb) cb();
				return Promise.resolve();
			},
		},
	},
	tabs: {
		query(opts, cb) {
			const tabs = [{ url: 'https://www.linkedin.com/jobs/view/12345' }];
			if (cb) cb(tabs);
			return Promise.resolve(tabs);
		},
	},
};
```

- [ ] **Step 2: Install vitest**

Run: `cd /Users/brianruggieri/git/candidate-eval/extension && source ~/.nvm/nvm.sh && nvm use && npm install`

- [ ] **Step 3: Create `extension/utils.js` with URL normalization and storage helpers**

```javascript
// extension/utils.js
/**
 * Shared utilities for URL normalization and per-URL keyed storage.
 * Imported by popup.js and background.js.
 */

const TRACKING_PARAMS = /^(utm_\w+|trk|eBP|trackingId|tracking_id|refId|fbclid|gclid|mc_[ce]id|_hsenc|_hsmi)$/i;

/**
 * Normalize a URL for use as a storage key.
 * Strips tracking params, hash fragments, and trailing slashes. Sorts remaining params.
 */
export function normalizeUrl(u) {
	try {
		const url = new URL(u || '');
		[...url.searchParams.keys()].forEach(k => {
			if (TRACKING_PARAMS.test(k)) url.searchParams.delete(k);
		});
		url.searchParams.sort();
		url.hash = '';
		return url.origin + url.pathname.replace(/\/+$/, '') + url.search;
	} catch {
		return (u || '').replace(/[?#].*$/, '').replace(/\/+$/, '');
	}
}

/**
 * Build a per-URL storage key: "prefix:{normalizedUrl}"
 */
function urlKey(prefix, url) {
	return `${prefix}:${normalizeUrl(url)}`;
}

/**
 * Get a value scoped to a URL from chrome.storage.local.
 * Returns null if not found.
 */
export async function getForUrl(prefix, url) {
	const key = urlKey(prefix, url);
	const result = await chrome.storage.local.get(key);
	return result[key] || null;
}

/**
 * Set a value scoped to a URL in chrome.storage.local.
 */
export async function setForUrl(prefix, url, value) {
	const key = urlKey(prefix, url);
	await chrome.storage.local.set({ [key]: value });
}

/**
 * Remove a value scoped to a URL from chrome.storage.local.
 */
export async function removeForUrl(prefix, url) {
	const key = urlKey(prefix, url);
	await chrome.storage.local.remove(key);
}
```

- [ ] **Step 4: Write storage tests**

```javascript
// extension/__tests__/storage.test.js
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { chrome, resetStore } from './chrome-mock.js';

// Make chrome global for utils.js
globalThis.chrome = chrome;

// Dynamic import so globalThis.chrome is set first
const { normalizeUrl, getForUrl, setForUrl, removeForUrl } = await import('../utils.js');

beforeEach(() => {
	resetStore();
});

describe('normalizeUrl', () => {
	it('strips tracking parameters', () => {
		const url = 'https://linkedin.com/jobs/view/123?utm_source=google&trk=abc';
		expect(normalizeUrl(url)).toBe('https://linkedin.com/jobs/view/123');
	});

	it('preserves non-tracking parameters', () => {
		const url = 'https://example.com/jobs?id=42&ref=apply';
		expect(normalizeUrl(url)).toContain('id=42');
	});

	it('strips hash fragments', () => {
		const url = 'https://example.com/jobs/123#section';
		expect(normalizeUrl(url)).toBe('https://example.com/jobs/123');
	});

	it('strips trailing slashes', () => {
		const url = 'https://example.com/jobs/123/';
		expect(normalizeUrl(url)).toBe('https://example.com/jobs/123');
	});

	it('sorts query parameters for stable keys', () => {
		const url1 = 'https://example.com/jobs?b=2&a=1';
		const url2 = 'https://example.com/jobs?a=1&b=2';
		expect(normalizeUrl(url1)).toBe(normalizeUrl(url2));
	});

	it('handles invalid URLs gracefully', () => {
		expect(normalizeUrl('not-a-url')).toBe('not-a-url');
	});

	it('handles empty/null input', () => {
		expect(normalizeUrl('')).toBe('');
		expect(normalizeUrl(null)).toBe('');
	});
});

describe('URL-keyed storage', () => {
	const url = 'https://linkedin.com/jobs/view/123?utm_source=google';

	it('setForUrl + getForUrl roundtrip', async () => {
		await setForUrl('posting', url, { company: 'Acme' });
		const result = await getForUrl('posting', url);
		expect(result).toEqual({ company: 'Acme' });
	});

	it('different URLs get different values', async () => {
		await setForUrl('posting', 'https://example.com/job/1', { company: 'A' });
		await setForUrl('posting', 'https://example.com/job/2', { company: 'B' });
		expect(await getForUrl('posting', 'https://example.com/job/1')).toEqual({ company: 'A' });
		expect(await getForUrl('posting', 'https://example.com/job/2')).toEqual({ company: 'B' });
	});

	it('URLs differing only in tracking params share a key', async () => {
		await setForUrl('posting', 'https://example.com/job/1?utm_source=x', { company: 'A' });
		const result = await getForUrl('posting', 'https://example.com/job/1');
		expect(result).toEqual({ company: 'A' });
	});

	it('removeForUrl clears the value', async () => {
		await setForUrl('posting', url, { company: 'Acme' });
		await removeForUrl('posting', url);
		expect(await getForUrl('posting', url)).toBeNull();
	});

	it('getForUrl returns null for missing key', async () => {
		expect(await getForUrl('posting', url)).toBeNull();
	});

	it('different prefixes are independent', async () => {
		await setForUrl('posting', url, { company: 'Acme' });
		await setForUrl('assessment', url, { grade: 'A' });
		expect(await getForUrl('posting', url)).toEqual({ company: 'Acme' });
		expect(await getForUrl('assessment', url)).toEqual({ grade: 'A' });
	});
});
```

- [ ] **Step 5: Run extension tests**

Run: `cd /Users/brianruggieri/git/candidate-eval/extension && source ~/.nvm/nvm.sh && nvm use && npx vitest run`
Expected: All tests pass.

- [ ] **Step 6: Migrate popup.js to URL-keyed storage**

In `extension/popup.html`, add the utils.js script before popup.js:

```html
<script src="utils.js"></script>
```

Since the extension is not using ES modules (MV3 popup scripts can't use `import`), change `utils.js` to use global assignment instead of `export`:

```javascript
// extension/utils.js — top of file, replace export statements with:
// Attach to globalThis for use in popup.js and background.js (non-module context)
```

Remove `export` keywords and instead assign to `globalThis` at the bottom:

```javascript
// Bottom of utils.js:
globalThis.normalizeUrl = normalizeUrl;
globalThis.getForUrl = getForUrl;
globalThis.setForUrl = setForUrl;
globalThis.removeForUrl = removeForUrl;
```

In `extension/popup.js`, replace the inline `normalizeUrl` definition (lines 420-429) and update all storage calls:

```javascript
// Remove the inline normalizeUrl and TRACKING_PARAMS (lines 419-429) — now in utils.js

// Replace singleton storage reads (line 410-415):
// OLD:
//   chrome.storage.local.get(['currentPosting', 'lastAssessment', 'fullAssessmentReady'], res => r(res));
// NEW:
const [stored, lastAssessment, fullReady] = await Promise.all([
	getForUrl('posting', currentTabUrl),
	getForUrl('assessment', currentTabUrl),
	getForUrl('fullReady', currentTabUrl),
]);

// Replace singleton storage writes:
// OLD (line 483): chrome.storage.local.set({ currentPosting: posting });
// NEW:            setForUrl('posting', currentTabUrl, posting);

// OLD (line 504): chrome.storage.local.remove('fullAssessmentReady');
// NEW:            removeForUrl('fullReady', currentTabUrl);

// OLD (line 513): chrome.storage.local.set({ lastAssessment: { url: posting.url, data: partial } });
// NEW:            setForUrl('assessment', currentTabUrl, { url: posting.url, data: partial });

// Replace fullAssessmentReady polling (lines 446-453, 527-536):
// OLD:  chrome.storage.local.get('fullAssessmentReady', res => r(res.fullAssessmentReady || null));
// NEW:  const ready = await getForUrl('fullReady', currentTabUrl);

// Remove URL validation checks that are now unnecessary:
// The cacheMatchesTab check (line 430) is no longer needed — storage IS per-URL.
// Simplify to: const fresh = stored && stored.extractedAt && (Date.now() - stored.extractedAt) < POSTING_TTL_MS;
```

- [ ] **Step 7: Migrate background.js to URL-keyed storage**

In `extension/background.js`, update `handleStartFullAssess` (lines 109-129):

```javascript
// Import utils.js in service worker
importScripts('utils.js');

// In handleStartFullAssess, replace:
// OLD: chrome.storage.local.remove('fullAssessmentReady');
// NEW: if (postingUrl) removeForUrl('fullReady', postingUrl);

// OLD: chrome.storage.local.set({ fullAssessmentReady: { ... } });
// NEW: if (postingUrl) setForUrl('fullReady', postingUrl, { ... });
```

- [ ] **Step 8: Run extension tests to verify**

Run: `cd /Users/brianruggieri/git/candidate-eval/extension && source ~/.nvm/nvm.sh && nvm use && npx vitest run`
Expected: All tests pass.

- [ ] **Step 9: Run Python test suite to verify no regressions**

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass.

- [ ] **Step 10: Commit**

```bash
git add extension/utils.js extension/package.json extension/vitest.config.js \
  extension/__tests__/chrome-mock.js extension/__tests__/storage.test.js \
  extension/popup.js extension/popup.html extension/background.js
git commit -m "fix: per-URL keyed storage — eliminate cross-tab contamination (#7)"
```

---

### Task 4: Confidence Wiring (#2)

**Files:**
- Modify: `src/claude_candidate/scoring/constants.py:34-36`
- Modify: `src/claude_candidate/scoring/dimensions.py:160-188`
- Test: `tests/test_quick_match.py`

**Benchmark prediction:** Widening confidence from ±10% to ±30% penalizes low-confidence (fuzzy/related) matches more. Expect 1-3 postings with fuzzy-dominated matches to drop by one grade notch. Postings with exact/alias matches should be unchanged.

- [ ] **Step 1: Write tests for widened confidence range**

```python
# tests/test_quick_match.py — add to TestMatchConfidence class

class TestConfidenceWiring:
	"""Verify widened confidence range affects scoring."""

	def test_full_confidence_no_penalty(self):
		"""Confidence 1.0 → adjustment factor 1.0 (no change)."""
		from claude_candidate.scoring.dimensions import _score_requirement
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel

		skill = MergedSkillEvidence(
			name="python",
			source=EvidenceSource.RESUME_AND_REPO,
			effective_depth=DepthLevel.DEEP,
			confidence=1.0,
		)
		score = _score_requirement(skill, "strong_match")
		# STATUS_SCORE_STRONG = 0.90, adjustment = FLOOR + (1-FLOOR) * 1.0 = 1.0
		assert score == pytest.approx(0.90)

	def test_zero_confidence_max_penalty(self):
		"""Confidence 0.0 → adjustment factor = CONFIDENCE_FLOOR."""
		from claude_candidate.scoring.dimensions import _score_requirement
		from claude_candidate.scoring.constants import CONFIDENCE_FLOOR
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel

		skill = MergedSkillEvidence(
			name="python",
			source=EvidenceSource.RESUME_AND_REPO,
			effective_depth=DepthLevel.DEEP,
			confidence=0.0,
		)
		score = _score_requirement(skill, "strong_match")
		# STATUS_SCORE_STRONG = 0.90, adjustment = CONFIDENCE_FLOOR
		assert score == pytest.approx(0.90 * CONFIDENCE_FLOOR)

	def test_half_confidence_moderate_penalty(self):
		"""Confidence 0.5 → adjustment between FLOOR and 1.0."""
		from claude_candidate.scoring.dimensions import _score_requirement
		from claude_candidate.scoring.constants import CONFIDENCE_FLOOR
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel

		skill = MergedSkillEvidence(
			name="python",
			source=EvidenceSource.RESUME_AND_REPO,
			effective_depth=DepthLevel.DEEP,
			confidence=0.5,
		)
		score = _score_requirement(skill, "strong_match")
		expected_adj = CONFIDENCE_FLOOR + (1.0 - CONFIDENCE_FLOOR) * 0.5
		assert score == pytest.approx(0.90 * expected_adj)

	def test_confidence_floor_is_less_than_090(self):
		"""Verify the floor has been widened from the old 0.90."""
		from claude_candidate.scoring.constants import CONFIDENCE_FLOOR
		assert CONFIDENCE_FLOOR < 0.90, "Confidence floor should be wider than old ±10%"
		assert CONFIDENCE_FLOOR >= 0.50, "Confidence floor shouldn't be so low it dominates"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_quick_match.py::TestConfidenceWiring -v`
Expected: FAIL — `CONFIDENCE_FLOOR` doesn't exist, and old formula uses 0.90+0.10*conf

- [ ] **Step 3: Add `CONFIDENCE_FLOOR` constant**

```python
# src/claude_candidate/scoring/constants.py — add after PATTERN_CONFIDENCE_LOW (line 36)

# Confidence adjustment floor: how much a zero-confidence match is penalized.
# Old value was 0.90 (±10%). Widened to 0.70 (±30%) so match quality
# has meaningful scoring impact on fuzzy/related matches.
CONFIDENCE_FLOOR = 0.70
```

- [ ] **Step 4: Update `_score_requirement()` to use `CONFIDENCE_FLOOR`**

```python
# src/claude_candidate/scoring/dimensions.py — update _score_requirement (lines 182-188)

# Add import at top of file:
from claude_candidate.scoring.constants import (
	# ... existing imports ...
	CONFIDENCE_FLOOR,
)

# Replace the confidence adjustment block (lines 182-187):
# OLD:
#	if best_match:
#		conf = best_match.confidence if best_match.confidence is not None else 1.0
#		adjustment = 0.90 + 0.10 * conf
#		req_score *= adjustment
# NEW:
	if best_match:
		conf = best_match.confidence if best_match.confidence is not None else 1.0
		adjustment = CONFIDENCE_FLOOR + (1.0 - CONFIDENCE_FLOOR) * conf
		req_score *= adjustment
```

Also update the compound scoring confidence adjustment in `engine.py` (line 464) to use the same formula:

```python
# src/claude_candidate/scoring/engine.py — update line 464:
# OLD:
#	adj = 0.90 + 0.10 * conf
# NEW:
	from claude_candidate.scoring.constants import CONFIDENCE_FLOOR
	adj = CONFIDENCE_FLOOR + (1.0 - CONFIDENCE_FLOOR) * conf
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_quick_match.py::TestConfidenceWiring -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass. Some existing confidence-related tests may need threshold adjustments if they assert exact values.

- [ ] **Step 7: Run benchmark with predicted deltas**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Record results. Verify only fuzzy-match-heavy postings shifted. Note deltas for recalibration.

- [ ] **Step 8: Commit**

```bash
git add src/claude_candidate/scoring/constants.py src/claude_candidate/scoring/dimensions.py \
  src/claude_candidate/scoring/engine.py tests/test_quick_match.py
git commit -m "feat: widen confidence adjustment to ±30% for meaningful match quality impact (#2)"
```

---

### Task 5: Virtual Skill Concentration Limit (#3)

**Files:**
- Modify: `src/claude_candidate/scoring/constants.py:411-533`
- Modify: `src/claude_candidate/scoring/matching.py:438-488`
- Test: `tests/test_quick_match.py`

**Benchmark prediction:** Tightening virtual skill thresholds makes broad skills harder to infer. Postings that relied heavily on virtual skills like "software-engineering" matching with only 3 constituents will see a grade drop of ~1 notch. Expect 2-5 postings to shift downward (stricter = fewer virtual matches).

- [ ] **Step 1: Write tests for tightened virtual skill rules**

```python
# tests/test_quick_match.py — add new test class

class TestVirtualSkillConcentration:
	"""Eng review 5B: tighten virtual skill inference rules."""

	def test_software_engineering_needs_5_constituents(self):
		"""software-engineering should require 5 constituents (raised from 3)."""
		from claude_candidate.scoring.constants import VIRTUAL_SKILL_RULES

		for name, constituents, min_count, depth, *rest in VIRTUAL_SKILL_RULES:
			if name == "software-engineering":
				assert min_count >= 5, f"software-engineering min_count should be ≥5, got {min_count}"
				break
		else:
			pytest.fail("software-engineering not found in VIRTUAL_SKILL_RULES")

	def test_full_stack_needs_3_constituents(self):
		"""full-stack should require 3 constituents (raised from 2)."""
		from claude_candidate.scoring.constants import VIRTUAL_SKILL_RULES

		for name, constituents, min_count, depth, *rest in VIRTUAL_SKILL_RULES:
			if name == "full-stack":
				assert min_count >= 3, f"full-stack min_count should be ≥3, got {min_count}"
				break
		else:
			pytest.fail("full-stack not found in VIRTUAL_SKILL_RULES")

	def test_frontend_needs_2_constituents(self):
		"""frontend-development should require 2 constituents (raised from 1)."""
		from claude_candidate.scoring.constants import VIRTUAL_SKILL_RULES

		for name, constituents, min_count, depth, *rest in VIRTUAL_SKILL_RULES:
			if name == "frontend-development":
				assert min_count >= 2, f"frontend-development min_count should be ≥2, got {min_count}"
				break
		else:
			pytest.fail("frontend-development not found in VIRTUAL_SKILL_RULES")

	def test_broad_virtual_skills_require_applied_depth(self):
		"""Broad virtual skills should require constituent skills at APPLIED depth or higher."""
		from claude_candidate.scoring.constants import VIRTUAL_SKILL_RULES
		from claude_candidate.schemas.candidate_profile import DepthLevel

		broad_skills = {"software-engineering", "full-stack", "system-design", "product-development"}
		for name, constituents, min_count, depth, *rest in VIRTUAL_SKILL_RULES:
			if name in broad_skills:
				min_depth = rest[0] if rest else None
				assert min_depth is not None, f"{name} should have a constituent depth requirement"
				assert min_depth.value >= DepthLevel.APPLIED.value, \
					f"{name} constituent depth should be ≥APPLIED, got {min_depth}"

	def test_virtual_skill_not_inferred_with_shallow_constituents(self):
		"""Virtual skill should NOT be inferred if constituents are USED depth."""
		from claude_candidate.scoring.matching import _infer_virtual_skill
		from claude_candidate.schemas.merged_profile import MergedEvidenceProfile, MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel

		# Profile with 5 skills at USED depth (too shallow)
		skills = [
			MergedSkillEvidence(name=n, source=EvidenceSource.RESUME_ONLY,
				effective_depth=DepthLevel.USED, confidence=0.8)
			for n in ["python", "typescript", "javascript", "react", "node.js"]
		]
		profile = MergedEvidenceProfile(skills=skills, projects=[], patterns=[])
		result = _infer_virtual_skill("software-engineering", profile)
		assert result is None, "Should not infer software-engineering from USED-depth skills"

	def test_virtual_skill_inferred_with_deep_constituents(self):
		"""Virtual skill should be inferred if constituents meet depth threshold."""
		from claude_candidate.scoring.matching import _infer_virtual_skill
		from claude_candidate.schemas.merged_profile import MergedEvidenceProfile, MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel

		skills = [
			MergedSkillEvidence(name=n, source=EvidenceSource.RESUME_AND_REPO,
				effective_depth=DepthLevel.DEEP, confidence=0.9)
			for n in ["python", "typescript", "javascript", "react", "node.js", "ci-cd"]
		]
		profile = MergedEvidenceProfile(skills=skills, projects=[], patterns=[])
		result = _infer_virtual_skill("software-engineering", profile)
		assert result is not None, "Should infer software-engineering from 6 DEEP skills"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_quick_match.py::TestVirtualSkillConcentration -v`
Expected: FAIL — min_count assertions fail (old values), depth requirement doesn't exist

- [ ] **Step 3: Update VIRTUAL_SKILL_RULES with raised thresholds and depth requirements**

Change the tuple format to include an optional minimum constituent depth. Update `src/claude_candidate/scoring/constants.py`:

```python
# src/claude_candidate/scoring/constants.py — update VIRTUAL_SKILL_RULES

# New format: (skill_name, constituents, min_count, inferred_depth, min_constituent_depth)
# min_constituent_depth: minimum effective_depth required for constituents to count.
# None means any depth counts (preserves old behavior for narrow skills).
VIRTUAL_SKILL_RULES: list[tuple[str, list[str], int, DepthLevel, DepthLevel | None]] = [
	# full-stack: need frontend + backend evidence at APPLIED+ depth
	(
		"full-stack",
		["react", "vue", "angular", "nextjs", "frontend-development",
		 "node.js", "python", "fastapi", "api-design", "backend-development"],
		3, DepthLevel.DEEP, DepthLevel.APPLIED,
	),
	# software-engineering: need multiple programming skills at APPLIED+ depth
	(
		"software-engineering",
		["python", "typescript", "javascript", "react", "node.js",
		 "ci-cd", "git", "testing", "api-design"],
		5, DepthLevel.DEEP, DepthLevel.APPLIED,
	),
	# frontend-development: need a frontend framework at APPLIED+ depth
	(
		"frontend-development",
		["react", "vue", "angular", "nextjs", "html-css"],
		2, DepthLevel.DEEP, DepthLevel.APPLIED,
	),
	# backend-development: need a backend stack
	(
		"backend-development",
		["python", "node.js", "fastapi", "api-design", "postgresql", "sql"],
		3, DepthLevel.DEEP, DepthLevel.APPLIED,
	),
	# system-design: architecture + system skills at APPLIED+
	(
		"system-design",
		["api-design", "distributed-systems", "cloud-infrastructure",
		 "software-engineering", "postgresql", "docker", "kubernetes"],
		3, DepthLevel.APPLIED, DepthLevel.APPLIED,
	),
	# testing: testing pattern or pytest (narrow — no depth requirement)
	("testing", ["pytest", "ci-cd"], 1, DepthLevel.DEEP, None),
	# devops: container/infra tooling
	(
		"devops",
		["docker", "kubernetes", "ci-cd", "terraform", "aws", "gcp", "azure"],
		2, DepthLevel.APPLIED, None,
	),
	# cloud-infrastructure: cloud providers
	(
		"cloud-infrastructure",
		["aws", "gcp", "azure", "docker", "kubernetes", "terraform"],
		2, DepthLevel.APPLIED, None,
	),
	# data-science: analytics background
	("data-science", ["sql", "python", "metabase", "postgresql"], 2, DepthLevel.APPLIED, None),
	# computer-science: implied by deep engineering experience
	(
		"computer-science",
		["python", "typescript", "javascript", "sql", "api-design", "software-engineering"],
		3, DepthLevel.APPLIED, None,
	),
	# product-development: full-stack + shipping evidence at APPLIED+
	(
		"product-development",
		["react", "node.js", "python", "prototyping", "api-design", "ci-cd", "full-stack"],
		3, DepthLevel.APPLIED, DepthLevel.APPLIED,
	),
	# production-systems: deployment + testing + infra
	(
		"production-systems",
		["ci-cd", "docker", "testing", "aws", "gcp", "azure", "postgresql", "devops"],
		2, DepthLevel.APPLIED, None,
	),
	# startup-experience: prototyping + shipping evidence
	(
		"startup-experience",
		["prototyping", "full-stack", "product-development", "ci-cd", "api-design", "ownership"],
		2, DepthLevel.APPLIED, None,
	),
	# metrics: analytics tools
	("metrics", ["metabase", "sql", "data-science", "postgresql"], 1, DepthLevel.APPLIED, None),
	# developer-tools: builds tools for developers
	(
		"developer-tools",
		["ci-cd", "git", "testing", "software-engineering", "api-design", "llm"],
		2, DepthLevel.DEEP, None,
	),
	# open-source: git + collaborative development
	(
		"open-source",
		["git", "ci-cd", "software-engineering", "collaboration"],
		2, DepthLevel.APPLIED, None,
	),
]
```

- [ ] **Step 4: Update `_infer_virtual_skill()` to check constituent depth**

In `src/claude_candidate/scoring/matching.py`, update the virtual skill rule check (lines 454-488):

```python
# Replace the constituent counting block (lines 454-488):

	for rule_name, constituents, min_count, depth, *rest in VIRTUAL_SKILL_RULES:
		if rule_name != target:
			continue
		min_constituent_depth = rest[0] if rest else None

		# Count constituents that meet the depth requirement
		profile_skill_map = {s.name.lower(): s for s in profile.skills}
		matched = 0
		for c in constituents:
			if c not in profile_skill_map:
				continue
			skill = profile_skill_map[c]
			if min_constituent_depth is not None:
				# Check effective_depth meets minimum
				if skill.effective_depth is None:
					continue
				depth_order = [DepthLevel.USED, DepthLevel.APPLIED, DepthLevel.DEEP, DepthLevel.EXPERT]
				skill_rank = depth_order.index(skill.effective_depth) if skill.effective_depth in depth_order else -1
				min_rank = depth_order.index(min_constituent_depth) if min_constituent_depth in depth_order else 0
				if skill_rank < min_rank:
					continue
			matched += 1

		if matched >= min_count:
			# Derive source from the constituent skills that exist in the profile.
			constituent_skills = [s for s in profile.skills if s.name.lower() in constituents]
			session_sources = {EvidenceSource.SESSIONS_ONLY, EvidenceSource.CORROBORATED}
			has_session_evidence = any(s.source in session_sources for s in constituent_skills)
			has_repo_evidence = any(
				s.source in {EvidenceSource.RESUME_AND_REPO, EvidenceSource.REPO_ONLY}
				for s in constituent_skills
			)
			if has_session_evidence:
				virtual_source = EvidenceSource.SESSIONS_ONLY
			elif has_repo_evidence:
				if any(s.source is EvidenceSource.RESUME_AND_REPO for s in constituent_skills):
					virtual_source = EvidenceSource.RESUME_AND_REPO
				else:
					virtual_source = EvidenceSource.REPO_ONLY
			else:
				virtual_source = EvidenceSource.RESUME_ONLY
			return MergedSkillEvidence(
				name=rule_name,
				source=virtual_source,
				session_depth=depth if has_session_evidence else None,
				resume_depth=depth if not has_session_evidence else None,
				effective_depth=depth,
				confidence=min(0.7, 0.4 + matched * 0.1),
				discovery_flag=False,
			)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_quick_match.py::TestVirtualSkillConcentration -v`
Expected: PASS

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass. Some existing virtual skill tests may need updates if they rely on old thresholds.

- [ ] **Step 7: Run benchmark with predicted deltas**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Record results. Verify only virtual-skill-heavy postings shifted.

- [ ] **Step 8: Commit**

```bash
git add src/claude_candidate/scoring/constants.py src/claude_candidate/scoring/matching.py \
  tests/test_quick_match.py
git commit -m "feat: tighten virtual skill inference — raise min_count and require depth (#3)"
```

---

### Task 6: Mission Alignment Reanalysis (#10)

**Files:**
- Modify: `src/claude_candidate/scoring/constants.py`
- Modify: `src/claude_candidate/scoring/dimensions.py:340-396`
- Modify: `src/claude_candidate/scoring/engine.py:182-268`
- Create: `tests/test_mission_reanalysis.py`

**Benchmark prediction:** Domain-aware keyword taxonomy improves mission scores for domain-matched postings and penalizes domain-mismatched ones. Adding mission to partial path changes partial assessment weights. Expect 3-6 postings to shift ±1 grade (domain-matched postings up, mismatched down). The partial-path mission proxy may shift grades for postings that previously had no mission signal.

- [ ] **Step 1: Write tests for mission domain taxonomy**

```python
# tests/test_mission_reanalysis.py — new file

"""Tests for mission alignment reanalysis: domain taxonomy + partial-path proxy."""

import pytest
from claude_candidate.scoring.constants import MISSION_DOMAIN_TAXONOMY
from claude_candidate.schemas.merged_profile import MergedEvidenceProfile, MergedSkillEvidence, EvidenceSource
from claude_candidate.schemas.candidate_profile import DepthLevel


class TestMissionDomainTaxonomy:
	"""Verify the domain keyword taxonomy exists and has expected structure."""

	def test_taxonomy_is_dict(self):
		assert isinstance(MISSION_DOMAIN_TAXONOMY, dict)
		assert len(MISSION_DOMAIN_TAXONOMY) > 0

	def test_taxonomy_maps_domains_to_keywords(self):
		"""Each domain maps to a list of related keywords."""
		for domain, keywords in MISSION_DOMAIN_TAXONOMY.items():
			assert isinstance(domain, str), f"Domain key should be string: {domain}"
			assert isinstance(keywords, list), f"Keywords should be list: {domain}"
			assert len(keywords) > 0, f"Domain {domain} has no keywords"

	def test_known_domains_present(self):
		"""Common domains should be in the taxonomy."""
		expected_domains = {"developer-tools", "ai", "fintech", "healthcare", "education"}
		for domain in expected_domains:
			assert domain in MISSION_DOMAIN_TAXONOMY, f"Missing domain: {domain}"

	def test_keywords_are_lowercase(self):
		"""All keywords should be lowercase for consistent matching."""
		for domain, keywords in MISSION_DOMAIN_TAXONOMY.items():
			for kw in keywords:
				assert kw == kw.lower(), f"Keyword '{kw}' in domain '{domain}' should be lowercase"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mission_reanalysis.py::TestMissionDomainTaxonomy -v`
Expected: FAIL — `MISSION_DOMAIN_TAXONOMY` doesn't exist

- [ ] **Step 3: Add `MISSION_DOMAIN_TAXONOMY` to constants**

```python
# src/claude_candidate/scoring/constants.py — add after MISSION_SCORE_MAX (line 72)

# Domain keyword taxonomy for mission alignment scoring.
# Maps product domains to related keywords that indicate domain relevance.
# Used to strengthen mission alignment when the candidate has domain-adjacent experience.
MISSION_DOMAIN_TAXONOMY: dict[str, list[str]] = {
	"developer-tools": [
		"developer", "devtools", "ide", "sdk", "api", "cli", "infrastructure",
		"platform", "tooling", "devops", "ci/cd", "deployment", "monitoring",
	],
	"ai": [
		"artificial intelligence", "machine learning", "ml", "llm", "nlp",
		"deep learning", "neural", "model", "inference", "training", "prompt",
		"agent", "agentic", "generative", "transformer", "embedding",
	],
	"fintech": [
		"financial", "fintech", "banking", "payments", "trading", "crypto",
		"blockchain", "defi", "insurance", "lending", "compliance",
	],
	"healthcare": [
		"health", "medical", "clinical", "patient", "biotech", "pharma",
		"genomic", "bioinformatics", "ehr", "telehealth", "diagnostic",
	],
	"education": [
		"education", "edtech", "learning", "teaching", "student", "course",
		"curriculum", "tutoring", "assessment", "classroom",
	],
	"e-commerce": [
		"commerce", "retail", "shopping", "marketplace", "merchant",
		"catalog", "inventory", "checkout", "fulfillment",
	],
	"gaming": [
		"game", "gaming", "unity", "unreal", "3d", "interactive",
		"multiplayer", "virtual", "simulation", "real-time",
	],
	"creative-tools": [
		"creative", "design", "media", "video", "audio", "music",
		"animation", "rendering", "content creation", "editor",
	],
	"security": [
		"security", "cybersecurity", "encryption", "authentication",
		"vulnerability", "threat", "compliance", "privacy", "zero trust",
	],
	"data": [
		"data", "analytics", "visualization", "dashboard", "metrics",
		"warehouse", "pipeline", "etl", "business intelligence",
	],
	"infrastructure": [
		"cloud", "infrastructure", "kubernetes", "containers", "serverless",
		"networking", "storage", "compute", "orchestration",
	],
	"collaboration": [
		"collaboration", "productivity", "communication", "team",
		"workflow", "project management", "remote work",
	],
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mission_reanalysis.py::TestMissionDomainTaxonomy -v`
Expected: PASS

- [ ] **Step 5: Write test for improved `_score_mission_text_alignment()`**

```python
# tests/test_mission_reanalysis.py — add to existing file

from claude_candidate.scoring.dimensions import _score_mission_text_alignment
from claude_candidate.schemas.company_profile import CompanyProfile
from datetime import datetime


class TestImprovedMissionTextAlignment:
	"""Verify domain-aware mission text alignment scoring."""

	def _make_profile(self, skill_names):
		"""Helper: create a profile with named skills."""
		skills = [
			MergedSkillEvidence(name=n, source=EvidenceSource.RESUME_AND_REPO,
				effective_depth=DepthLevel.DEEP, confidence=0.9)
			for n in skill_names
		]
		return MergedEvidenceProfile(skills=skills, projects=[], patterns=[])

	def _make_company(self, mission, product_desc=""):
		"""Helper: create a company profile with mission."""
		return CompanyProfile(
			company_name="Test Co",
			mission_statement=mission,
			product_description=product_desc or mission,
			enriched_at=datetime.now(),
		)

	def test_domain_keyword_match_boosts_score(self):
		"""AI keywords in mission match candidate with AI skills."""
		profile = self._make_profile(["python", "llm", "prompt-engineering"])
		company = self._make_company(
			"Building the next generation of AI agents for enterprise automation"
		)
		score, details = _score_mission_text_alignment(profile, company)
		assert score > 0, "Should score positively for domain keyword overlap"

	def test_no_domain_match_returns_zero(self):
		"""No keyword overlap → zero score."""
		profile = self._make_profile(["cobol", "fortran"])
		company = self._make_company(
			"Revolutionary healthcare diagnostics platform"
		)
		score, details = _score_mission_text_alignment(profile, company)
		assert score == 0.0

	def test_domain_taxonomy_broadens_matching(self):
		"""Domain taxonomy keywords like 'agent' match even without exact skill name."""
		profile = self._make_profile(["python", "typescript", "react"])
		company = self._make_company(
			"We build developer tools and CLI platforms for infrastructure teams"
		)
		# "developer" and "infrastructure" are in developer-tools domain taxonomy
		# Even though candidate doesn't have "developer-tools" as a skill name,
		# the taxonomy-expanded keywords should find overlap
		score, details = _score_mission_text_alignment(profile, company)
		# Score comes from direct skill name matching + domain taxonomy expansion
		assert isinstance(score, float)
```

- [ ] **Step 6: Run test to verify behavior (may partially pass with existing code)**

Run: `.venv/bin/python -m pytest tests/test_mission_reanalysis.py::TestImprovedMissionTextAlignment -v`

- [ ] **Step 7: Improve `_score_mission_text_alignment()` with domain taxonomy**

Update `src/claude_candidate/scoring/dimensions.py` to expand candidate keywords with domain taxonomy:

```python
# src/claude_candidate/scoring/dimensions.py — update _score_mission_text_alignment (lines 340-375)

# Add import:
from claude_candidate.scoring.constants import (
	# ... existing imports ...
	MISSION_DOMAIN_TAXONOMY,
)

def _score_mission_text_alignment(
	profile: MergedEvidenceProfile,
	company_profile: CompanyProfile,
) -> tuple[float, list[str]]:
	"""Score mission text alignment using domain-aware keyword taxonomy.

	Expands matching beyond raw skill names by including domain taxonomy keywords
	when the candidate has skills in a recognized domain. This catches cases where
	a company's mission mentions domain concepts (e.g., 'developer tools') that
	don't exactly match skill names (e.g., 'ci-cd', 'git').
	"""
	text_sources = []
	if company_profile.mission_statement:
		text_sources.append(company_profile.mission_statement)
	text_sources.append(company_profile.product_description)
	if not text_sources:
		return 0.0, []

	combined_text = " ".join(text_sources).lower()

	# Build candidate keywords from skills + project techs
	candidate_keywords: set[str] = {s.name.lower() for s in profile.skills}
	for proj in profile.projects:
		for tech in proj.technologies:
			candidate_keywords.add(tech.lower())

	# Expand with domain taxonomy: if candidate has skills in a domain,
	# include that domain's keywords for matching against mission text.
	expanded_keywords: set[str] = set(candidate_keywords)
	for domain, domain_keywords in MISSION_DOMAIN_TAXONOMY.items():
		# Check if candidate has skills that overlap with this domain's keywords
		domain_kw_set = set(domain_keywords)
		skill_overlap = candidate_keywords & domain_kw_set
		if skill_overlap or domain.lower() in candidate_keywords:
			expanded_keywords.update(domain_keywords)

	# Match expanded keywords against mission text (3+ chars, word boundary)
	matched = {
		kw
		for kw in expanded_keywords
		if len(kw) >= 3 and re.search(rf"\b{re.escape(kw)}\b", combined_text)
	}
	if not matched:
		return 0.0, []

	# Score based on ratio of matched keywords to total candidate keywords
	# (use original candidate_keywords as denominator, not expanded)
	ratio = len(matched) / max(len(candidate_keywords), 1)
	# Cap ratio at 1.0 since expanded keywords can exceed original count
	ratio = min(ratio, 1.0)
	detail = f"Mission text overlap: {', '.join(sorted(matched)[:MAX_TECH_OVERLAP_DISPLAY])}"
	return ratio * MISSION_TEXT_OVERLAP_WEIGHT, [detail]
```

- [ ] **Step 8: Run mission tests**

Run: `.venv/bin/python -m pytest tests/test_mission_reanalysis.py -v`
Expected: PASS

- [ ] **Step 9: Write tests for mission in partial assessment path**

```python
# tests/test_mission_reanalysis.py — add to existing file

from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority


class TestMissionInPartialPath:
	"""Eng review 4A→C: mission scoring in partial assessments via skill_mapping proxy."""

	def _make_profile(self, skill_names):
		skills = [
			MergedSkillEvidence(name=n, source=EvidenceSource.RESUME_AND_REPO,
				effective_depth=DepthLevel.DEEP, confidence=0.9)
			for n in skill_names
		]
		return MergedEvidenceProfile(
			skills=skills, projects=[], patterns=[],
			total_years_experience=10.0,
		)

	def test_partial_assessment_includes_mission_dimension(self):
		"""Partial assessment should now include a mission dimension."""
		from claude_candidate.scoring.engine import QuickMatchEngine

		profile = self._make_profile(["python", "react", "typescript", "node.js"])
		engine = QuickMatchEngine(profile)
		reqs = [
			QuickRequirement(description="Python", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE),
			QuickRequirement(description="React", skill_mapping=["react"], priority=RequirementPriority.STRONG_PREFERENCE),
		]
		result = engine.assess(reqs, company="TestCo", title="Engineer")
		# Partial assessment should now include mission (proxy-based)
		# It may still be None if no tech_stack overlap — but the code path should execute
		assert result.assessment_phase == "partial"

	def test_partial_mission_uses_skill_mapping_proxy(self):
		"""Partial path derives tech_stack from requirement skill_mappings."""
		from claude_candidate.scoring.engine import QuickMatchEngine

		profile = self._make_profile(["python", "react", "typescript", "docker"])
		engine = QuickMatchEngine(profile)
		reqs = [
			QuickRequirement(description="Python", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE),
			QuickRequirement(description="React", skill_mapping=["react", "typescript"], priority=RequirementPriority.MUST_HAVE),
			QuickRequirement(description="Docker", skill_mapping=["docker"], priority=RequirementPriority.NICE_TO_HAVE),
		]
		result = engine.assess(reqs, company="TestCo", title="Engineer")
		# Tech stack proxy = unique skills from all requirement skill_mappings
		# = ["python", "react", "typescript", "docker"]
		# Candidate has all four → high tech overlap → mission score > neutral
		if result.mission_alignment:
			assert result.mission_alignment.score >= 0.3, "Mission proxy should produce non-trivial score"

	def test_partial_weights_redistribute_with_mission(self):
		"""Partial weights should include mission at 10% (taken from skill).
		Total weights must sum to 1.0: skill 0.60 + exp 0.20 + edu 0.10 + mission 0.10."""
		from claude_candidate.scoring.engine import QuickMatchEngine

		profile = self._make_profile(["python", "react"])
		engine = QuickMatchEngine(profile)
		reqs = [
			QuickRequirement(description="Python", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE),
		]
		result = engine.assess(reqs, company="TestCo", title="Engineer")
		if result.mission_alignment:
			assert result.mission_alignment.weight == pytest.approx(0.10)
			assert result.skill_match.weight == pytest.approx(0.60)
		# Verify assessment_phase is still "partial" (not "full")
		assert result.assessment_phase == "partial"
```

- [ ] **Step 10: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mission_reanalysis.py::TestMissionInPartialPath -v`
Expected: FAIL — partial assessment currently has no mission dimension

- [ ] **Step 11: Add mission scoring to partial assessment path**

In `src/claude_candidate/scoring/engine.py`, update `_run_assessment()` (lines 182-268) to include mission:

```python
# In _run_assessment, after education_dim scoring (line 210) and before weight assignment (line 215):

		# Partial-path mission: derive tech_stack from requirement skill_mappings
		# (eng review decision 4A→C: skill_mapping proxy, no extraction model change)
		proxy_tech_stack = list({
			skill
			for req in scorable_reqs
			for skill in req.skill_mapping
		})
		mission_dim = self._score_mission_alignment(
			company=inp.company,
			tech_stack=proxy_tech_stack if not inp.tech_stack else inp.tech_stack,
			company_profile=inp.company_profile,
		)

		# Partial-assessment weights: skill-heavy, with mission proxy at reduced weight.
		# Weights must sum to 1.0 (_compute_overall_score does straight weighted sum).
		skill_dim.weight = 0.60
		experience_dim.weight = 0.20
		education_dim.weight = 0.10
		if mission_dim:
			mission_dim.weight = 0.10
		# If no mission data, redistribute 0.10 back to skill
		if not mission_dim:
			skill_dim.weight = 0.65
			experience_dim.weight = 0.25
			# education stays 0.10 → total = 1.0

# Update the overall score computation to include mission:
		overall_score = _compute_overall_score(
			skill_dim,
			experience_dim=experience_dim,
			education_dim=education_dim,
			mission_dim=mission_dim,
		)

# Update the _build_assessment call to pass mission_dim:
		return self._build_assessment(
			inp,
			skill_dim,
			mission_dim,  # Was None before — now proxy-based
			None,  # culture_dim still None for partial
			skill_details,
			overall_score,
			elapsed,
			experience_dim=experience_dim,
			education_dim=education_dim,
			partial_percentage=partial_percentage,
			eligibility_gates=eligibility_gates,
			eligibility_passed=eligibility_passed,
			scorable_reqs=scorable_reqs,
			pre_cap_grade=pre_cap_grade,
			domain_gap_term=domain_gap_term,
		)
```

**IMPORTANT:** Also update the `is_partial` check in `_assemble_fit_assessment()` (engine.py line 357).
The current check `is_partial = mission_dim is None and culture_dim is None` would be False
when proxy mission is set, incorrectly labeling partial assessments as "full".

```python
# engine.py line 357 — replace:
#   is_partial = mission_dim is None and culture_dim is None
# with:
		is_partial = culture_dim is None  # Partial = no company research (no culture)
```

Note: `_compute_overall_score()` in dimensions.py already accepts `mission_dim` as a parameter —
no signature change needed. It does a straight weighted sum (no normalization), so all weights
must sum to 1.0.

- [ ] **Step 12: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_mission_reanalysis.py::TestMissionInPartialPath -v`
Expected: PASS

- [ ] **Step 13: Run full test suite**

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass. Existing partial assessment tests may need weight assertion updates.

- [ ] **Step 14: Run benchmark with predicted deltas**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Record results. Domain-matched postings should score slightly higher, mismatched slightly lower.

- [ ] **Step 15: Commit**

```bash
git add src/claude_candidate/scoring/constants.py src/claude_candidate/scoring/dimensions.py \
  src/claude_candidate/scoring/engine.py tests/test_mission_reanalysis.py
git commit -m "feat: mission alignment reanalysis — domain taxonomy + partial-path proxy (#10)"
```

---

### Task 7: Benchmark Recalibration + Version Bump

**Files:**
- Modify: `tests/golden_set/expected_grades.json`
- Modify: `pyproject.toml`
- Modify: `extension/manifest.json`
- Create: `tests/test_pipeline_integration.py` (add full-pipeline tests)

**Prerequisite:** All Phase 1 features (Tasks 1-6) are merged.

- [ ] **Step 1: Run the full benchmark**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Record the full output: exact matches, within-1 matches, and per-posting grades.

- [ ] **Step 2: Analyze grade shifts**

Compare against previous baseline (37/47 exact). For each posting that shifted:
1. Identify which feature caused the shift (distillation, confidence, virtual skill, mission)
2. Verify the new grade is more accurate (review the posting requirements)
3. If the new grade is correct, update `expected_grades.json`
4. If the new grade is wrong, investigate and fix before recalibrating

- [ ] **Step 3: Update `expected_grades.json`**

For each posting where the new grade is confirmed correct, update the expected grade and rationale:

```json
{
  "posting_name": {
    "expected": "NEW_GRADE",
    "rationale": "Updated for v0.8: [reason for change, e.g., 'distillation properly splits compound req']"
  }
}
```

- [ ] **Step 4: Re-run benchmark to verify all expected grades match**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Expected: Exact match count should equal the new baseline.

- [ ] **Step 5: Add full-pipeline integration test**

```python
# tests/test_pipeline_integration.py — add to existing file

import json
from pathlib import Path


class TestFullPipelineIntegration:
	"""Eng review 12: integration test for full pipeline (raw text → parser → scoring)."""

	POSTING_DIR = Path(__file__).parent / "golden_set" / "postings"

	def _load_posting(self, name: str) -> dict:
		path = self.POSTING_DIR / f"{name}.json"
		return json.loads(path.read_text())

	@pytest.mark.parametrize("posting_name", [
		"anthropic-software-engineer",
		"stripe-fullstack-engineer",
		"datadog-senior-swe",
		"figma-frontend-engineer",
		"openai-research-engineer",
	])
	def test_full_pipeline_produces_valid_assessment(self, posting_name, minimal_engine):
		"""Raw requirements → QuickRequirement[] → FitAssessment with valid structure."""
		try:
			posting = self._load_posting(posting_name)
		except FileNotFoundError:
			pytest.skip(f"Posting {posting_name} not in golden set")

		from claude_candidate.schemas.job_requirements import QuickRequirement

		reqs = []
		for r in posting.get("requirements", []):
			try:
				reqs.append(QuickRequirement(**r))
			except Exception:
				continue
		if not reqs:
			pytest.skip(f"No valid requirements in {posting_name}")

		from claude_candidate.requirement_parser import compute_distillation_weights
		compute_distillation_weights(reqs)

		result = minimal_engine.assess(
			reqs,
			company=posting.get("company", "Unknown"),
			title=posting.get("title", "Unknown"),
		)
		assert result.overall_score >= 0.0
		assert result.overall_score <= 1.0
		assert result.overall_grade in ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]
		assert len(result.skill_matches) > 0
```

- [ ] **Step 6: Run integration tests**

Run: `.venv/bin/python -m pytest tests/test_pipeline_integration.py -v`
Expected: PASS for available postings.

- [ ] **Step 7: Bump version to v0.8.0**

```python
# pyproject.toml — update version
version = "0.8.0"
```

```json
// extension/manifest.json — update version
"version": "0.8.0"
```

- [ ] **Step 8: Run full test suite (final verification)**

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass.

- [ ] **Step 9: Commit**

```bash
git add tests/golden_set/expected_grades.json tests/test_pipeline_integration.py \
  pyproject.toml extension/manifest.json
git commit -m "chore: bump version to 0.8.0, recalibrate benchmark for Phase 1"
```

---

## Dependency Graph

```
Task 1 (Parsing Unification)
  └──→ Task 2 (Distillation) ──┐
                                 ├──→ Task 7 (Benchmark + Version)
Task 3 (Per-URL Storage) ───────┤
                                 │
Task 4 (Confidence Wiring) ─────┤
                                 │
Task 5 (Virtual Skill Conc.) ───┤
                                 │
Task 6 (Mission Reanalysis) ────┘
```

Tasks 3, 4, 5, 6 can all run in parallel with each other and with Task 1.
Task 2 depends on Task 1 (distillation goes into the unified prompt).
Task 7 depends on all other tasks.

## Exit Criteria (from CEO plan)

- [ ] Benchmark run after recalibration — all expected grades match
- [ ] All new features have passing test suites
- [ ] Distillation preview renders in extension (compound groups)
- [ ] Per-URL storage works — no cross-tab contamination
- [ ] Unified parsing path active — server delegates to requirement_parser.py
- [ ] Extension tests pass (vitest): `cd extension && npx vitest run`
- [ ] Full Python test suite: `.venv/bin/python -m pytest -x -q`
