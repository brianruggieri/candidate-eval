# Gap 1 Addendum: Domain Penalty + match_type Field

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two scoring corrections identified during confidence-metrics work: (1) add a `match_type` field to `SkillMatchDetail` so the extension popup can correctly classify fuzzy vs exact skill resolution; (2) add a domain-penalty cap (B+) when a non-technical industry domain appears in 3+ requirements but is absent from the candidate's profile.

**Architecture:** Both changes are isolated to the scoring pipeline. `match_type` flows from `_find_skill_match` → `_find_best_skill` → `_build_skill_detail` → `SkillMatchDetail` → API response → popup.js. Domain penalty runs in `_run_assessment` before `_build_assessment`, reusing the existing `pre_cap_grade` pattern. No new files needed.

**Tech Stack:** Python 3.13, pydantic v2, pytest. Extension popup.js (vanilla JS).

**Context for agentic workers:**
- This plan is an **addendum** to `docs/superpowers/plans/2026-03-24-corpus-management.md`, which is being implemented on branch `feat/corpus-management`. These tasks should go on that same branch (or a branch off it).
- Branch to work on: `feat/corpus-management` (or a follow-on branch if corpus management is already merged)
- Always use `.venv/bin/python` — never bare `python`
- Tabs for indentation, 100-char line length (enforced by ruff)
- No Co-Authored-By commit trailers

---

## File Map

| File | Action | What changes |
|---|---|---|
| `src/claude_candidate/schemas/fit_assessment.py` | Modify | Add `match_type` field to `SkillMatchDetail`; add `domain_gap_term` field to `FitAssessment` |
| `src/claude_candidate/quick_match.py` | Modify | `_find_skill_match` returns `(skill, type)` tuple; `_find_best_skill` returns `(match, status, type)`; `_build_skill_detail` passes type; add `DOMAIN_KEYWORDS`, `_detect_domain_gap()`; apply cap in `_run_assessment` |
| `extension/popup.js` | Modify | `categorizeSkill()` uses `m.match_type` instead of broken req/matched_skill comparison |
| `tests/test_quick_match.py` | Modify | Add `TestMatchType` class; add domain penalty tests |
| `tests/golden_set/expected_grades.json` | Modify | Recalibrate postings affected by domain penalty (Suno, possibly Milwaukee Brewers) after running benchmark |

---

## Task 1: `match_type` field — schema + backend

**Files:**
- Modify: `src/claude_candidate/schemas/fit_assessment.py`
- Modify: `src/claude_candidate/quick_match.py`
- Test: `tests/test_quick_match.py`

### Background (read before coding)

`_find_skill_match(skill_name, profile)` currently returns `MergedSkillEvidence | None`. It tries four resolution strategies in order:
1. Taxonomy canonicalization → exact name lookup (`_find_exact_match`) → **exact**
2. Original normalized name → exact lookup → **exact**
3. Substring/variant (`_find_fuzzy_match`) → **fuzzy**
4. Pattern match (`_find_pattern_match`) → **fuzzy**
5. Virtual inference (`_infer_virtual_skill`) → **fuzzy**

`_find_best_skill` calls `_find_skill_match` per skill in `req.skill_mapping`, picks the best status, and returns `(best_match, best_status)`. `_build_skill_detail` turns this into a `SkillMatchDetail`.

The extension popup's `categorizeSkill()` currently tries to compare `m.requirement` (full JD sentence) against `m.matched_skill` (canonical skill name) — always unequal, so everything shows "fuzzy". Fix: use `m.match_type` from the API.

- [ ] **Step 1.1: Write failing tests**

Add to `tests/test_quick_match.py`, near other `_find_best_skill` / `_build_skill_detail` tests:

```python
class TestMatchType:
	"""match_type correctly classifies exact vs fuzzy skill resolution."""

	def _make_profile(self, skills=None):
		from datetime import datetime
		from claude_candidate.schemas.merged_profile import MergedEvidenceProfile
		return MergedEvidenceProfile(
			skills=skills or [],
			patterns=[],
			projects=[],
			roles=[],
			corroborated_skill_count=0,
			resume_only_skill_count=0,
			sessions_only_skill_count=len(skills or []),
			discovery_skills=[],
			profile_hash="test",
			resume_hash="test",
			candidate_profile_hash="test",
			merged_at=datetime.now(),
		)

	def _profile_with(self, skill_name: str, source="corroborated") -> MergedEvidenceProfile:
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel
		return self._make_profile(skills=[MergedSkillEvidence(
			name=skill_name,
			source=EvidenceSource[source.upper()],
			effective_depth=DepthLevel.APPLIED,
			confidence=0.85,
		)])

	def _req(self, skill: str):
		from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
		return QuickRequirement(
			description=f"Experience with {skill}",
			skill_mapping=[skill],
			priority=RequirementPriority.STRONG_PREFERENCE,
		)

	def test_exact_name_match_returns_exact(self):
		"""Direct name match → match_type='exact'."""
		from claude_candidate.quick_match import _find_best_skill
		from claude_candidate.schemas.candidate_profile import DepthLevel
		profile = self._profile_with("python")
		req = self._req("python")
		match, status, mtype = _find_best_skill(req, profile, DepthLevel.USED)
		assert match is not None
		assert mtype == "exact"

	def test_taxonomy_alias_returns_exact(self):
		"""Taxonomy alias resolution (ci/cd → ci-cd) → match_type='exact'."""
		from claude_candidate.quick_match import _find_best_skill
		from claude_candidate.schemas.candidate_profile import DepthLevel
		profile = self._profile_with("ci-cd")
		req = self._req("ci/cd")  # alias in taxonomy
		match, status, mtype = _find_best_skill(req, profile, DepthLevel.USED)
		assert match is not None
		assert mtype == "exact"

	def test_no_evidence_returns_none_type(self):
		"""Unmatched requirement → match_type='none'."""
		from claude_candidate.quick_match import _find_best_skill
		from claude_candidate.schemas.candidate_profile import DepthLevel
		profile = self._profile_with("python")
		req = self._req("cobol")
		match, status, mtype = _find_best_skill(req, profile, DepthLevel.USED)
		assert match is None
		assert mtype == "none"
		assert status == "no_evidence"

	def test_skill_match_detail_has_match_type_field(self):
		"""SkillMatchDetail serialises match_type in the API-facing dict."""
		from claude_candidate.quick_match import _find_best_skill, _build_skill_detail
		from claude_candidate.schemas.candidate_profile import DepthLevel
		profile = self._profile_with("python")
		req = self._req("python")
		match, status, mtype = _find_best_skill(req, profile, DepthLevel.USED)
		detail = _build_skill_detail(req, match, status, mtype)
		assert detail.match_type == "exact"
		d = detail.model_dump()
		assert "match_type" in d
```

- [ ] **Step 1.2: Run tests, confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::TestMatchType -v
```
Expected: 4 FAILED (`_find_best_skill` returns a 2-tuple, not 3; `_build_skill_detail` missing `mtype` arg; `SkillMatchDetail` missing field)

- [ ] **Step 1.3: Add `match_type` to `SkillMatchDetail`**

In `src/claude_candidate/schemas/fit_assessment.py`, add one field to `SkillMatchDetail`:

```python
class SkillMatchDetail(BaseModel):
	"""Detailed skill-by-skill match result."""

	requirement: str
	priority: str
	match_status: str
	candidate_evidence: str
	evidence_source: EvidenceSource
	confidence: float = Field(ge=0.0, le=1.0)
	matched_skill: str | None = None
	match_type: str = "exact"  # "exact" | "fuzzy" | "none" — how skill was resolved
```

- [ ] **Step 1.4: Modify `_find_skill_match` to return `(skill, type)` tuple**

In `src/claude_candidate/quick_match.py`, find `_find_skill_match` (~line 891). Replace:

```python
def _find_skill_match(
	skill_name: str,
	profile: MergedEvidenceProfile,
) -> MergedSkillEvidence | None:
	"""Find a skill in the merged profile via exact, fuzzy, pattern, or inference."""
	taxonomy = _get_taxonomy()
	canonical = taxonomy.match(skill_name)
	if canonical:
		found = _find_exact_match(canonical.lower(), profile)
		if found:
			return found

	normalized = skill_name.lower().strip()
	return (
		_find_exact_match(normalized, profile)
		or _find_fuzzy_match(normalized, profile)
		or _find_pattern_match(normalized, profile)
		or _infer_virtual_skill(skill_name, profile)
	)
```

With:

```python
def _find_skill_match(
	skill_name: str,
	profile: MergedEvidenceProfile,
) -> tuple[MergedSkillEvidence | None, str]:
	"""Find a skill in the merged profile via exact, fuzzy, pattern, or inference.

	Returns (skill, match_type) where match_type is:
	  "exact"  — canonical name or taxonomy alias resolved to an exact profile hit
	  "fuzzy"  — substring, pattern, or inferred virtual skill
	  "none"   — no match found
	"""
	taxonomy = _get_taxonomy()
	canonical = taxonomy.match(skill_name)
	if canonical:
		found = _find_exact_match(canonical.lower(), profile)
		if found:
			return found, "exact"

	normalized = skill_name.lower().strip()
	exact = _find_exact_match(normalized, profile)
	if exact:
		return exact, "exact"
	fuzzy = _find_fuzzy_match(normalized, profile)
	if fuzzy:
		return fuzzy, "fuzzy"
	pattern = _find_pattern_match(normalized, profile)
	if pattern:
		return pattern, "fuzzy"
	inferred = _infer_virtual_skill(skill_name, profile)
	if inferred:
		return inferred, "fuzzy"
	return None, "none"
```

- [ ] **Step 1.5: Modify `_find_best_skill` to propagate match_type**

Find `_find_best_skill` (~line 1012). Change the return type annotation and internal logic to track `best_match_type`:

```python
def _find_best_skill(
	req: QuickRequirement,
	profile: MergedEvidenceProfile,
	depth_floor: DepthLevel,
) -> tuple[MergedSkillEvidence | None, str, str]:
	"""Find the best matching skill for a requirement across all mappings.

	Returns (best_match, best_status, match_type).
	match_type is "exact", "fuzzy", or "none".
	"""
	taxonomy = _get_taxonomy()
	best_match: MergedSkillEvidence | None = None
	best_status = "no_evidence"
	best_match_type = "none"

	for skill_name in req.skill_mapping:
		found, mtype = _find_skill_match(skill_name, profile)
		if found:
			status = _assess_depth_match(found, depth_floor, profile)
			if STATUS_RANK.get(status, 0) > STATUS_RANK.get(best_status, 0):
				best_match = found
				best_status = status
				best_match_type = mtype
			continue

		# Related skill fallback
		canonical = taxonomy.match(skill_name)
		if not canonical:
			continue
		for profile_skill in profile.skills:
			profile_canonical = taxonomy.canonicalize(profile_skill.name)
			if taxonomy.are_related(canonical, profile_canonical):
				if STATUS_RANK.get("related", 0) > STATUS_RANK.get(best_status, 0):
					best_match = profile_skill
					best_status = "related"
					best_match_type = "fuzzy"
				break

	# Years experience boost
	if req.years_experience and best_match and best_match.resume_duration:
		candidate_years = _parse_duration_years(best_match.resume_duration)
		if candidate_years:
			if candidate_years >= req.years_experience:
				if best_status == "partial_match":
					best_status = "strong_match"
				elif best_status == "adjacent":
					best_status = "partial_match"

	# Total years fallback
	if req.years_experience and best_status == "no_evidence":
		if (
			profile.total_years_experience
			and profile.total_years_experience >= req.years_experience
		):
			best_status = "related"
			best_match = MergedSkillEvidence(
				name="general_experience",
				source=EvidenceSource.RESUME_ONLY,
				effective_depth=DepthLevel.APPLIED,
				confidence=0.5,
			)
			best_match_type = "fuzzy"

	return best_match, best_status, best_match_type
```

- [ ] **Step 1.6: Update `_build_skill_detail` to accept and use match_type**

Find `_build_skill_detail` (~line 1103). Update signature and body:

```python
def _build_skill_detail(
	req: QuickRequirement,
	best_match: MergedSkillEvidence | None,
	best_status: str,
	match_type: str = "exact",
) -> SkillMatchDetail:
	"""Build a SkillMatchDetail for one requirement."""
	return SkillMatchDetail(
		requirement=req.description,
		priority=req.priority.value,
		match_status=best_status,
		candidate_evidence=(_evidence_summary(best_match) if best_match else "No evidence found"),
		evidence_source=(best_match.source if best_match else EvidenceSource.RESUME_ONLY),
		confidence=best_match.confidence if best_match else 0.0,
		matched_skill=best_match.name if best_match else None,
		match_type=match_type,
	)
```

- [ ] **Step 1.7: Update every call site of `_find_best_skill` and `_build_skill_detail`**

Search all call sites — both source and tests:
```bash
grep -rn "_find_best_skill\|_build_skill_detail" src/claude_candidate/ tests/
```

For each `_find_best_skill(...)` call, unpack the third return value (change 2-tuple to 3-tuple unpack). Existing test-file calls like `match, status = _find_best_skill(...)` will raise `ValueError: too many values to unpack` if not updated — update them all. For each `_build_skill_detail(...)` call, pass the `match_type` arg. The main source call site is in `_score_skill_match` or wherever `_find_best_skill` is used in the scoring loop — find it and update accordingly.

- [ ] **Step 1.8: Run tests, confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::TestMatchType -v
```
Expected: 4 PASSED

- [ ] **Step 1.9: Run full fast suite**

```bash
.venv/bin/python -m pytest
```
Expected: all pass

- [ ] **Step 1.10: Update `categorizeSkill` in popup.js**

In `extension/popup.js`, replace `categorizeSkill`:

```js
function categorizeSkill(m) {
	if (m.match_status === 'no_evidence') return 'missing';
	if (m.evidence_source === 'corroborated') return 'direct';
	// match_type from API: "fuzzy" = substring/pattern/inferred resolution
	if (m.match_type === 'fuzzy') return 'fuzzy';
	return 'inferred';
}
```

Verify syntax:
```bash
node --check extension/popup.js && echo OK
```

- [ ] **Step 1.11: Commit**

```bash
git add src/claude_candidate/schemas/fit_assessment.py \
        src/claude_candidate/quick_match.py \
        extension/popup.js \
        tests/test_quick_match.py
git commit -m "feat: add match_type field to SkillMatchDetail (exact/fuzzy/none); fix popup categorizeSkill"
```

---

## Task 2: Domain-penalty heuristic

**Files:**
- Modify: `src/claude_candidate/quick_match.py`
- Modify: `src/claude_candidate/schemas/fit_assessment.py`
- Modify: `tests/test_quick_match.py`
- Modify: `tests/golden_set/expected_grades.json` (recalibrate after benchmark run)

### Background

Suno (music company) and Milwaukee Brewers (baseball) both scored A because their JDs list standard tech skills — the music/baseball domain gap is not captured. Fix: if a non-technical industry keyword appears in 3+ requirements AND is absent from the candidate's skill/project/role profile, cap the final grade at B+.

The cap mirrors the existing eligibility cap pattern: store the pre-cap grade in `pre_cap_grade`, set `domain_gap_term` on the assessment for transparency.

`FitAssessment.pre_cap_grade` already exists (set by eligibility gate logic). We reuse it for domain penalty. If eligibility already zeroed the score, domain cap is moot. If both fire, eligibility wins (score=0 outranks B+ cap).

Grade cap logic: `GRADE_ORDER = ["A+","A","A-","B+","B","B-","C+","C","C-","D","F"]` (index 0 = best). Cap at B+ (index 3): if `GRADE_ORDER.index(overall_grade) < 3`, clamp to B+.

- [ ] **Step 2.1: Write failing tests**

Add to `tests/test_quick_match.py`:

```python
class TestDomainPenalty:
	"""Domain-penalty caps grade at B+ when industry domain appears 3+ times but is absent."""

	def _make_profile(self, skills=None):
		from datetime import datetime
		from claude_candidate.schemas.merged_profile import MergedEvidenceProfile
		return MergedEvidenceProfile(
			skills=skills or [],
			patterns=[],
			projects=[],
			roles=[],
			corroborated_skill_count=0,
			resume_only_skill_count=0,
			sessions_only_skill_count=len(skills or []),
			discovery_skills=[],
			profile_hash="test",
			resume_hash="test",
			candidate_profile_hash="test",
			merged_at=datetime.now(),
		)

	def _reqs_with_domain(self, domain_word: str, count: int):
		"""Create `count` requirements that mention the domain word."""
		from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
		return [
			QuickRequirement(
				description=f"Experience in {domain_word} industry applications",
				skill_mapping=["python"],
				priority=RequirementPriority.STRONG_PREFERENCE,
			)
			for _ in range(count)
		]

	def test_domain_fires_when_keyword_in_three_reqs(self):
		"""'music' in 3 requirements + no music in profile → domain_gap_term='music'."""
		from claude_candidate.quick_match import _detect_domain_gap
		reqs = self._reqs_with_domain("music", 3)
		profile = self._make_profile()
		gap = _detect_domain_gap(reqs, profile)
		assert gap == "music"

	def test_domain_does_not_fire_when_keyword_in_two_reqs(self):
		"""'music' in only 2 requirements → no gap (threshold is 3)."""
		from claude_candidate.quick_match import _detect_domain_gap
		reqs = self._reqs_with_domain("music", 2)
		profile = self._make_profile()
		gap = _detect_domain_gap(reqs, profile)
		assert gap is None

	def test_domain_does_not_fire_when_keyword_in_profile(self):
		"""'music' in 3 requirements but candidate has music as a skill name → no gap."""
		from claude_candidate.quick_match import _detect_domain_gap
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		from claude_candidate.schemas.candidate_profile import DepthLevel
		reqs = self._reqs_with_domain("music", 3)
		profile = self._make_profile(skills=[MergedSkillEvidence(
			name="music",
			source=EvidenceSource.RESUME_ONLY,
			effective_depth=DepthLevel.MENTIONED,
			confidence=0.8,
		)])
		gap = _detect_domain_gap(reqs, profile)
		assert gap is None

	def test_tech_term_not_in_domain_keywords_does_not_fire(self):
		"""'python' in 5 requirements → not a domain keyword, no gap."""
		from claude_candidate.quick_match import _detect_domain_gap
		reqs = self._reqs_with_domain("python", 5)
		profile = self._make_profile()
		gap = _detect_domain_gap(reqs, profile)
		assert gap is None

	def test_domain_cap_applied_to_high_scoring_assessment(self):
		"""Assessment that would score A gets capped to B+ when domain gap detected."""
		# Sanity-check that the constants are present.
		# Full end-to-end cap is validated by benchmark recalibration (Step 2.8).
		from claude_candidate.quick_match import _detect_domain_gap, DOMAIN_KEYWORDS
		assert "music" in DOMAIN_KEYWORDS
		assert "baseball" in DOMAIN_KEYWORDS
```

- [ ] **Step 2.2: Run tests, confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::TestDomainPenalty -v
```
Expected: FAILED — `_detect_domain_gap` doesn't exist, `DOMAIN_KEYWORDS` doesn't exist

- [ ] **Step 2.3: Add `DOMAIN_KEYWORDS` and `_detect_domain_gap` to quick_match.py**

Add near the top of `quick_match.py` (after module-level constants like `STATUS_SCORE`):

```python
# Industry/domain keywords — non-technical terms that appear repeatedly in domain-specific JDs.
# If any of these appears in 3+ requirements but is absent from the candidate's profile,
# the grade is capped at B+ (domain fit cannot be proven without evidence).
DOMAIN_KEYWORDS: frozenset[str] = frozenset({
	# Music / audio
	"music", "audio", "sound", "recording", "podcast",
	# Sports
	"sports", "baseball", "football", "basketball", "soccer", "athletics",
	# Healthcare / biotech
	"healthcare", "medical", "clinical", "patient", "biotech", "pharma",
	# Finance
	"fintech", "banking", "financial", "trading", "insurance",
	# Legal
	"legal", "compliance", "regulatory",
	# Automotive
	"automotive", "vehicle",
	# Education
	"edtech", "educational", "curriculum",
	# Gaming
	"gaming", "esports",
	# Real estate
	"real estate", "construction",
	# Energy
	"energy", "utilities",
	# Retail / logistics
	"retail", "ecommerce", "logistics",
})


def _detect_domain_gap(
	requirements: list["QuickRequirement"],
	profile: "MergedEvidenceProfile",
) -> str | None:
	"""Return the first domain keyword in 3+ requirements that is absent from the profile.

	Checks candidate skills, project names (word-split), and role domains.
	Returns the keyword string if a gap is detected, None otherwise.
	"""
	candidate_terms: set[str] = set()
	for skill in profile.skills:
		candidate_terms.add(skill.name.lower())
	for project in (profile.projects or []):
		for word in project.project_name.lower().split():
			candidate_terms.add(word)
	for role in (profile.roles or []):
		if role.domain:
			candidate_terms.add(role.domain.lower())

	for kw in sorted(DOMAIN_KEYWORDS):  # sorted for deterministic output
		count = sum(1 for r in requirements if kw in r.description.lower())
		if count >= 3 and kw not in candidate_terms:
			return kw
	return None
```

- [ ] **Step 2.4: Add `domain_gap_term` to `FitAssessment`**

In `src/claude_candidate/schemas/fit_assessment.py`, add to `FitAssessment` (near `pre_cap_grade` and eligibility fields):

```python
	domain_gap_term: str | None = None  # Industry domain in 3+ reqs but absent from profile
```

- [ ] **Step 2.5: Apply cap in `_run_assessment`**

In `_run_assessment`, after `overall_score` is computed and before `partial_percentage` is set, add:

```python
	# Domain penalty: cap at B+ if industry domain appears 3+ times in requirements
	# but is absent from the candidate's profile.
	domain_gap_term = _detect_domain_gap(scorable_reqs, self._profile)
	GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]
	if domain_gap_term and not unmet_gates:  # eligibility cap already zeros score; skip
		candidate_grade = score_to_grade(overall_score)
		if GRADE_ORDER.index(candidate_grade) < GRADE_ORDER.index("B+"):  # grade better than B+
			if pre_cap_grade is None:  # don't overwrite eligibility pre_cap_grade
				pre_cap_grade = candidate_grade
			# Drop score to the top of the B+ band (0.80)
			overall_score = min(overall_score, 0.799)
```

Note: `self._profile` is the merged profile stored on the engine instance. Verify the attribute name by reading `QuickMatchEngine.__init__` — it may be `self.profile` or `self._merged_profile`. Use the correct name.

Also pass `domain_gap_term` through the full call chain:

1. Find the `_build_assessment(...)` call at the bottom of `_run_assessment` and add `domain_gap_term=domain_gap_term` as a kwarg.

2. Update `_build_assessment` signature to accept `domain_gap_term: str | None = None`:
   ```python
   def _build_assessment(
       self,
       ...,
       pre_cap_grade: str | None = None,
       domain_gap_term: str | None = None,
   ) -> FitAssessment:
   ```
   And pass it to the `_assemble_fit_assessment(...)` call inside `_build_assessment`:
   ```python
   return self._assemble_fit_assessment(
       ...,
       pre_cap_grade=pre_cap_grade,
       domain_gap_term=domain_gap_term,
   )
   ```

3. Update `_assemble_fit_assessment` signature to accept `domain_gap_term: str | None = None` and pass it to the `FitAssessment(...)` constructor:
   ```python
   def _assemble_fit_assessment(
       self,
       ...,
       pre_cap_grade: str | None = None,
       domain_gap_term: str | None = None,
   ) -> FitAssessment:
       ...
       return FitAssessment(
           ...,
           domain_gap_term=domain_gap_term,
       )
   ```

- [ ] **Step 2.6: Run tests, confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::TestDomainPenalty -v
```
Expected: all pass

- [ ] **Step 2.7: Run full fast suite**

```bash
.venv/bin/python -m pytest
```
Expected: all pass

- [ ] **Step 2.8: Run benchmark, observe which postings change**

```bash
.venv/bin/python tests/golden_set/benchmark_accuracy.py 2>&1 | head -30
```

Expect Suno (`suno-staff-software-engineer`) to drop from A → B+ (music domain detected). Milwaukee Brewers (`milwaukee-brewers-senior-software-engineer-baseball-systems`) may also drop if "baseball" appears in 3+ requirements. Note the deltas.

- [ ] **Step 2.9: Recalibrate expected_grades.json for domain-penalised postings**

For each posting that now scores B+ due to domain penalty, update `expected_grades.json`:

```json
"suno-staff-software-engineer": {
  "expected": "B+",
  "rationale": "Suno — Staff Software Engineer. Music/audio domain not in profile. Domain penalty (music in 3+ requirements) caps at B+. General SWE skills match strongly but domain gap is real."
}
```

Do the same for any other posting that shifts. Then re-run benchmark to confirm 24/24:

```bash
.venv/bin/python tests/golden_set/benchmark_accuracy.py 2>&1 | head -6
```
Expected: Exact match: 24/24

- [ ] **Step 2.10: Commit**

```bash
git add src/claude_candidate/quick_match.py \
        src/claude_candidate/schemas/fit_assessment.py \
        tests/test_quick_match.py \
        tests/golden_set/expected_grades.json \
        tests/golden_set/benchmark_history.jsonl
git commit -m "feat: domain-penalty cap (B+) when industry domain in 3+ reqs absent from profile"
```

---

## Task 3: Widen the golden set with harder postings (data task, no code)

> This task uses `corpus promote` from the corpus management CLI (already implemented in the `feat/corpus-management` branch). Do this task AFTER corpus management is merged and deployed.

**Target posting types to add:**

| Type | Why | Expected grade |
|---|---|---|
| Pure ML research (papers/PhD required) | Tests research-vs-practitioner detection | C or D |
| Native mobile (iOS Swift or Android Kotlin) | Zero mobile skills in profile | D or F |
| Enterprise Java/Spring role | Java not in profile, different ecosystem | C |
| PM role with no engineering path | Not an engineer's role | C |

**Process for each:**
1. Navigate to the job posting in Chrome
2. Run assessment via extension
3. Note the actual grade — if it's already low (≤ C), it's a good candidate
4. `corpus promote <url> <grade>` to add to golden set with honest human-assigned grade
5. Verify with `corpus list` that the entry appears
6. Run `benchmark_accuracy.py` to confirm the golden set is stable

> ⚠️ Do NOT promote any posting where the assessed grade looks inflated by the sparse-requirements bug (issue #26). Fix that bug first, then re-assess, then promote.

---

## Post-implementation verification

After all tasks are complete:

```bash
# Full test suite
.venv/bin/python -m pytest

# Benchmark
.venv/bin/python tests/golden_set/benchmark_accuracy.py

# Extension smoke test (manual)
# 1. Load extension unpacked in Chrome
# 2. Navigate to a LinkedIn job posting with known skills
# 3. Verify: corroborated skills show "direct" chip, non-corroborated show "inferred",
#    fuzzy-resolved skills show "fuzzy", Suno-type postings show B+ not A
```
