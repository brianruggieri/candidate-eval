# Skill Matching Accuracy Improvement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 8 structural bugs in the skill matching engine, build a 25-posting benchmark, and prepare a ralph-loop for iterative accuracy improvement.

**Architecture:** Phase 1 delivers 8 pre-fixes (canonicalization, related skill fallback, confidence floor, soft skills, compound scoring, profile refresh, extraction normalization, experience matching), a golden set export, a benchmark script, and a ralph-loop PROMPT.md. All changes on a feature branch, committed as a clean baseline before ralph starts.

**Tech Stack:** Python 3.11+, pydantic v2, pytest, SQLite, rapidfuzz

**Spec:** `docs/superpowers/specs/2026-03-20-skill-matching-accuracy-design.md`

**Important:** Always use `.venv/bin/python` for all Python commands. Run tests with `.venv/bin/python -m pytest`.

---

## File Structure

**Modified files:**
- `src/claude_candidate/quick_match.py` — Canonicalization, related skill fallback, confidence floor, soft skill discount, compound scoring, experience years matching
- `src/claude_candidate/skill_taxonomy.py` — No changes needed (existing `are_related()`, `get_category()`, `match()` are sufficient)
- `src/claude_candidate/data/taxonomy.json` — Add soft_skill category entries
- `src/claude_candidate/merger.py` — Accept curated resume data
- `src/claude_candidate/server.py` — Post-extraction normalization
- `src/claude_candidate/requirement_parser.py` — Post-extraction normalization
- `src/claude_candidate/schemas/merged_profile.py` — Add duration field
- `src/claude_candidate/schemas/fit_assessment.py` — Add "related" to valid match statuses
- `tests/test_quick_match.py` — Tests for all matching changes
- `tests/test_skill_taxonomy.py` — Tests for soft skill category
- `tests/test_merger.py` — Tests for curated resume merging

**New files:**
- `tests/golden_set/postings/` — 25 posting JSON files
- `tests/golden_set/expected_grades.json` — Expected grades (user fills in)
- `tests/golden_set/benchmark_accuracy.py` — Benchmark script
- `tests/golden_set/benchmark_history.jsonl` — Iteration log
- `scripts/export_golden_set.py` — DB export script
- `.claude/ralph-accuracy-prompt.md` — Ralph-loop PROMPT.md

---

## Task 1: Canonicalization Consistency (Fix 2)

**Files:**
- Modify: `src/claude_candidate/quick_match.py:280-354` (matching helpers)
- Modify: `tests/test_quick_match.py`

- [ ] **Step 1: Write failing test for canonicalization in matching**

Add to `tests/test_quick_match.py`:

```python
def test_find_skill_match_canonicalizes_hyphens():
    """Skill 'ci-cd' should match profile entry 'ci cd' via canonicalization."""
    from claude_candidate.quick_match import _find_skill_match
    from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
    from claude_candidate.schemas.candidate_profile import DepthLevel
    from claude_candidate.schemas.merged_profile import MergedEvidenceProfile

    profile = MergedEvidenceProfile(
        skills=[MergedSkillEvidence(
            name="ci-cd",  # canonical form from taxonomy
            source=EvidenceSource.SESSIONS_ONLY,
            session_depth=DepthLevel.DEEP,
            session_frequency=15,
            effective_depth=DepthLevel.DEEP,
            confidence=0.75,
            discovery_flag=True,
        )],
        patterns=[], projects=[], roles=[],
        corroborated_skill_count=0, resume_only_skill_count=0,
        sessions_only_skill_count=1, discovery_skills=[],
        profile_hash="test", resume_hash="test",
        candidate_profile_hash="test", merged_at="2026-01-01T00:00:00",
    )

    # These should all resolve to the same canonical skill
    assert _find_skill_match("ci-cd", profile) is not None
    assert _find_skill_match("ci/cd", profile) is not None
    assert _find_skill_match("continuous-integration", profile) is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_quick_match.py::test_find_skill_match_canonicalizes_hyphens -v`

Expected: At least one assertion fails (ci/cd or continuous-integration won't match)

- [ ] **Step 3: Fix `_find_skill_match` to canonicalize via taxonomy**

In `src/claude_candidate/quick_match.py`, update `_find_skill_match()`:

```python
def _find_skill_match(
    skill_name: str,
    profile: MergedEvidenceProfile,
) -> MergedSkillEvidence | None:
    """Find a skill in the merged profile via exact, fuzzy, or pattern match."""
    taxonomy = _get_taxonomy()
    # Canonicalize through taxonomy first (handles aliases like ci/cd -> ci-cd)
    canonical = taxonomy.match(skill_name)
    if canonical:
        found = _find_exact_match(canonical.lower(), profile)
        if found:
            return found

    # Fallback to original normalized form
    normalized = skill_name.lower().strip()
    return (
        _find_exact_match(normalized, profile)
        or _find_fuzzy_match(normalized, profile)
        or _find_pattern_match(normalized, profile)
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_quick_match.py::test_find_skill_match_canonicalizes_hyphens -v`

- [ ] **Step 5: Run full test suite**

Run: `.venv/bin/python -m pytest`

Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/quick_match.py tests/test_quick_match.py
git commit -m "Fix canonicalization: route skill lookups through taxonomy.match()"
```

---

## Task 2: Related Skill Fallback (Fix 3)

**Files:**
- Modify: `src/claude_candidate/quick_match.py:73-205` (constants + lookup tables)
- Modify: `src/claude_candidate/quick_match.py:392-419` (`_find_best_skill`, `_score_requirement`)
- Modify: `tests/test_quick_match.py`

- [ ] **Step 1: Add "related" status constants**

In `src/claude_candidate/quick_match.py`, add after the existing STATUS constants:

```python
# Related skill score (distinct from adjacent which is depth-based)
STATUS_SCORE_RELATED = 0.25

# Shift rank scale to accommodate "related" between no_evidence and adjacent
STATUS_RANK_NONE = 0
STATUS_RANK_RELATED = 1
STATUS_RANK_ADJACENT = 2
STATUS_RANK_PARTIAL = 3
STATUS_RANK_STRONG = 4
STATUS_RANK_EXCEEDS = 5
```

Update the lookup dicts to include "related":

```python
STATUS_SCORE: dict[str, float] = {
    "exceeds": STATUS_SCORE_EXCEEDS,
    "strong_match": STATUS_SCORE_STRONG,
    "partial_match": STATUS_SCORE_PARTIAL,
    "adjacent": STATUS_SCORE_ADJACENT,
    "related": STATUS_SCORE_RELATED,
    "no_evidence": STATUS_SCORE_NONE,
}

# NOTE: Also update the original constant declarations at the top of the file
# to use the shifted values (none=0, related=1, adjacent=2, partial=3, strong=4, exceeds=5)
STATUS_RANK: dict[str, int] = {
    "exceeds": STATUS_RANK_EXCEEDS,       # 5
    "strong_match": STATUS_RANK_STRONG,    # 4
    "partial_match": STATUS_RANK_PARTIAL,  # 3
    "adjacent": STATUS_RANK_ADJACENT,      # 2
    "related": STATUS_RANK_RELATED,        # 1
    "no_evidence": STATUS_RANK_NONE,       # 0
}

STATUS_MARKER: dict[str, str] = {
    "exceeds": "++",
    "strong_match": "+",
    "partial_match": "~",
    "adjacent": "?",
    "related": "~?",
    "no_evidence": "-",
}
```

- [ ] **Step 2: Write failing test for related skill fallback**

```python
def test_find_best_skill_related_fallback():
    """When no direct match exists, related skills should give 'related' status."""
    from claude_candidate.quick_match import _find_best_skill
    from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
    from claude_candidate.schemas.merged_profile import MergedSkillEvidence, MergedEvidenceProfile, EvidenceSource
    from claude_candidate.schemas.candidate_profile import DepthLevel

    # Profile has "anthropic" but requirement asks for "openai" (related in taxonomy)
    profile = MergedEvidenceProfile(
        skills=[MergedSkillEvidence(
            name="anthropic",
            source=EvidenceSource.SESSIONS_ONLY,
            session_depth=DepthLevel.EXPERT,
            session_frequency=95,
            effective_depth=DepthLevel.EXPERT,
            confidence=0.85,
            discovery_flag=True,
        )],
        patterns=[], projects=[], roles=[],
        corroborated_skill_count=0, resume_only_skill_count=0,
        sessions_only_skill_count=1, discovery_skills=[],
        profile_hash="test", resume_hash="test",
        candidate_profile_hash="test", merged_at="2026-01-01T00:00:00",
    )

    req = QuickRequirement(
        description="Experience with OpenAI API",
        skill_mapping=["openai"],
        priority=RequirementPriority.MUST_HAVE,
    )

    match, status = _find_best_skill(req, profile, DepthLevel.APPLIED)
    assert match is not None, "Should find anthropic as a related match"
    assert status == "related"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_quick_match.py::test_find_best_skill_related_fallback -v`

- [ ] **Step 4: Implement related skill fallback in `_find_best_skill`**

Update `_find_best_skill()` in `quick_match.py`:

```python
def _find_best_skill(
    req: QuickRequirement,
    profile: MergedEvidenceProfile,
    depth_floor: DepthLevel,
) -> tuple[MergedSkillEvidence | None, str]:
    """Find the best matching skill for a requirement across all mappings."""
    taxonomy = _get_taxonomy()
    best_match: MergedSkillEvidence | None = None
    best_status = "no_evidence"

    for skill_name in req.skill_mapping:
        # Try direct match (exact, fuzzy, pattern)
        found = _find_skill_match(skill_name, profile)
        if found:
            status = _assess_depth_match(found, depth_floor)
            if STATUS_RANK.get(status, 0) > STATUS_RANK.get(best_status, 0):
                best_match = found
                best_status = status
            continue

        # Try related skill fallback
        canonical = taxonomy.match(skill_name)
        if not canonical:
            continue
        for profile_skill in profile.skills:
            profile_canonical = taxonomy.canonicalize(profile_skill.name)
            if taxonomy.are_related(canonical, profile_canonical):
                if STATUS_RANK.get("related", 0) > STATUS_RANK.get(best_status, 0):
                    best_match = profile_skill
                    best_status = "related"
                break  # Take first related match

    return best_match, best_status
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_quick_match.py::test_find_best_skill_related_fallback -v`

- [ ] **Step 6: Run full test suite**

Run: `.venv/bin/python -m pytest`

- [ ] **Step 7: Commit**

```bash
git add src/claude_candidate/quick_match.py tests/test_quick_match.py
git commit -m "Add related skill fallback: partial credit for related taxonomy entries"
```

---

## Task 3: Confidence Floor (Fix 7)

**Files:**
- Modify: `src/claude_candidate/quick_match.py:411-419` (`_score_requirement`)
- Modify: `tests/test_quick_match.py`

- [ ] **Step 1: Write failing test**

```python
def test_score_requirement_confidence_floor():
    """Low-confidence skills should be floored at 0.5 to prevent cratering."""
    from claude_candidate.quick_match import _score_requirement, STATUS_SCORE
    from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
    from claude_candidate.schemas.candidate_profile import DepthLevel

    low_conf_skill = MergedSkillEvidence(
        name="python",
        source=EvidenceSource.RESUME_ONLY,
        resume_depth=DepthLevel.DEEP,
        resume_context="Listed",
        effective_depth=DepthLevel.DEEP,
        confidence=0.3,  # Very low confidence
    )

    score = _score_requirement(low_conf_skill, "strong_match")
    # Without floor: 0.85 * 0.3 = 0.255
    # With floor: 0.85 * 0.5 = 0.425
    assert score >= STATUS_SCORE["strong_match"] * 0.5
    assert score == STATUS_SCORE["strong_match"] * 0.5  # Exactly at floor
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_quick_match.py::test_score_requirement_confidence_floor -v`

- [ ] **Step 3: Implement confidence floor**

Update `_score_requirement()`:

```python
# Confidence floor — prevent low-confidence skills from cratering scores
CONFIDENCE_FLOOR = 0.5


def _score_requirement(
    best_match: MergedSkillEvidence | None,
    best_status: str,
) -> float:
    """Compute the score for one requirement given its best match."""
    req_score = STATUS_SCORE.get(best_status, STATUS_SCORE_NONE)
    if best_match:
        effective_confidence = max(best_match.confidence, CONFIDENCE_FLOOR)
        req_score *= effective_confidence
    return req_score
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest`

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/quick_match.py tests/test_quick_match.py
git commit -m "Add confidence floor at 0.5 to prevent low-frequency skills from cratering"
```

---

## Task 4: Soft Skill Category (Fix 4)

**Files:**
- Modify: `src/claude_candidate/data/taxonomy.json`
- Modify: `src/claude_candidate/quick_match.py`
- Modify: `tests/test_quick_match.py`
- Modify: `tests/test_skill_taxonomy.py`

- [ ] **Step 1: Add soft_skill entries to taxonomy.json**

Add these entries to `src/claude_candidate/data/taxonomy.json`:

```json
"communication": {
    "aliases": ["written communication", "verbal communication", "communication skills", "excellent communication"],
    "category": "soft_skill",
    "related": ["collaboration", "leadership"],
    "parent": null
},
"collaboration": {
    "aliases": ["teamwork", "team player", "collaborative", "cross-functional"],
    "category": "soft_skill",
    "related": ["communication", "leadership"],
    "parent": null
},
"leadership": {
    "aliases": ["technical leadership", "team lead", "mentorship", "people management"],
    "category": "soft_skill",
    "related": ["communication", "collaboration"],
    "parent": null
},
"problem-solving": {
    "aliases": ["analytical thinking", "critical thinking", "troubleshooting"],
    "category": "soft_skill",
    "related": [],
    "parent": null
},
"adaptability": {
    "aliases": ["flexibility", "fast learner", "quick learner", "self-starter"],
    "category": "soft_skill",
    "related": [],
    "parent": null
}
```

- [ ] **Step 2: Write failing test for soft skill discount**

```python
def test_soft_skill_requirement_discounted():
    """Requirements mapping to soft_skill category should get reduced weight."""
    from claude_candidate.quick_match import QuickMatchEngine, SOFT_SKILL_DISCOUNT
    # The discount factor should exist and be < 1.0
    assert 0.0 < SOFT_SKILL_DISCOUNT < 1.0
```

- [ ] **Step 3: Add soft skill discount constant and logic**

In `quick_match.py`, add constant:

```python
# Soft skill discount factor — reduces weight of soft skill requirements
SOFT_SKILL_DISCOUNT = 0.3
```

In the skill scoring loop inside `_score_skill_match()` (wherever requirements are iterated and weighted), add a check:

```python
taxonomy = _get_taxonomy()
# Check if this requirement maps to a soft skill
is_soft_skill = False
for skill_name in req.skill_mapping:
    canonical = taxonomy.match(skill_name)
    if canonical and taxonomy.get_category(canonical) == "soft_skill":
        is_soft_skill = True
        break

weight = PRIORITY_WEIGHT.get(req.priority, 1.0)
if is_soft_skill:
    weight *= SOFT_SKILL_DISCOUNT
```

Find the exact location in `_score_skill_match()` where `PRIORITY_WEIGHT` is used and integrate.

- [ ] **Step 4: Write test for taxonomy soft skill category**

In `tests/test_skill_taxonomy.py`:

```python
def test_soft_skill_category():
    """Soft skill entries should have category 'soft_skill'."""
    from claude_candidate.skill_taxonomy import SkillTaxonomy
    taxonomy = SkillTaxonomy.load_default()
    assert taxonomy.get_category("communication") == "soft_skill"
    assert taxonomy.get_category("collaboration") == "soft_skill"
    assert taxonomy.get_category("leadership") == "soft_skill"
    # Aliases should resolve
    assert taxonomy.match("excellent communication") == "communication"
    assert taxonomy.match("team player") == "collaboration"
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest`

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/data/taxonomy.json src/claude_candidate/quick_match.py tests/test_quick_match.py tests/test_skill_taxonomy.py
git commit -m "Add soft skill taxonomy category with 0.3x weight discount"
```

---

## Task 5: Compound Requirement Scoring (Fix 5)

**Files:**
- Modify: `src/claude_candidate/quick_match.py` (`_score_skill_match` or wherever per-requirement scoring happens)
- Modify: `tests/test_quick_match.py`

- [ ] **Step 1: Write failing test**

```python
def test_compound_requirement_breadth_scoring():
    """A requirement with 3 skill mappings where 2 match should score better than best-only."""
    from claude_candidate.quick_match import _find_best_skill, _score_requirement
    from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
    # Build a profile with python (expert) and machine-learning (applied) but no data-science
    # Requirement: ["python", "data-science", "machine-learning"]
    # Verify the compound code path exists and returns a valid score.
    # With 3 skill mappings where python matches strongly, the max(best, avg)
    # should at minimum return the best single match score.
    from claude_candidate.quick_match import _find_best_skill, _find_skill_match, _assess_depth_match, _score_requirement, CONFIDENCE_FLOOR, STATUS_SCORE
    # Build profile and requirement — implementation will vary based on
    # how compound scoring is integrated. The key assertion:
    # a multi-skill requirement with partial matches should score >= single best.
    # Implementer: create a profile with 2/3 matching skills, verify score reflects breadth.
```

Note: The `max(best, average)` approach means compound scoring only helps when multiple partial matches average higher than the single best. Write a test that exercises this path.

- [ ] **Step 2: Find the exact location in `_score_skill_match` where per-requirement scoring happens**

Read `src/claude_candidate/quick_match.py` — find the method `_score_skill_match()` and identify where `_find_best_skill()` and `_score_requirement()` are called for each requirement. The change: for each requirement, also compute average of all constituent match scores and take `max(best_score, avg_score)`.

- [ ] **Step 3: Implement compound scoring**

The change is in the per-requirement scoring loop. After `_find_best_skill()` returns the best match/status:

```python
# Compound scoring: also check average of all constituent skills
if len(req.skill_mapping) > 1:
    all_scores = []
    for skill_name in req.skill_mapping:
        found = _find_skill_match(skill_name, profile)
        if found:
            status = _assess_depth_match(found, depth_floor)
            all_scores.append(STATUS_SCORE.get(status, 0.0) * max(found.confidence, CONFIDENCE_FLOOR))
        else:
            all_scores.append(0.0)
    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
    req_score = max(req_score, avg_score)
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest`

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/quick_match.py tests/test_quick_match.py
git commit -m "Add compound requirement scoring: max(best, average) for multi-skill reqs"
```

---

## Task 6: Profile Refresh — Merger Curated Resume Support (Fix 0)

**Files:**
- Modify: `src/claude_candidate/merger.py`
- Modify: `src/claude_candidate/schemas/merged_profile.py` (add duration field)
- Modify: `tests/test_merger.py`

- [ ] **Step 1: Add `resume_duration` field to MergedSkillEvidence**

In `src/claude_candidate/schemas/merged_profile.py`, add to `MergedSkillEvidence`:

```python
resume_duration: str | None = None  # e.g. "8 years", "2 months" from curated resume
```

- [ ] **Step 2: Write failing test for curated resume merging**

In `tests/test_merger.py`:

```python
def test_merge_with_curated_resume(candidate_profile):
    """Merger should use curated_skills depths when available.

    Uses the candidate_profile fixture from conftest.py which provides
    a fully populated CandidateProfile with all required pydantic fields.
    """
    from claude_candidate.merger import merge_with_curated
    cp = candidate_profile

    # Curated resume data (as would be loaded from curated_resume.json)
    curated_skills = [
        {"name": "typescript", "depth": "expert", "duration": "8 years",
         "source_context": "Listed in skills section", "curated": True},
        {"name": "python", "depth": "deep", "duration": "2 years",
         "source_context": "Listed in skills section", "curated": True},
    ]

    merged = merge_with_curated(cp, curated_skills, total_years=12.4, education=["B.S. Computer Science"])
    ts_skill = merged.get_skill("typescript")
    assert ts_skill is not None
    assert ts_skill.source.value == "corroborated"
    assert ts_skill.resume_duration == "8 years"

    py_skill = merged.get_skill("python")
    assert py_skill is not None
    assert py_skill.source.value == "resume_only"
    assert py_skill.resume_duration == "2 years"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_merger.py::test_merge_with_curated_resume -v`

- [ ] **Step 4: Implement `merge_with_curated()` in merger.py**

Add a new function to `src/claude_candidate/merger.py`:

```python
def merge_with_curated(
    candidate_profile: CandidateProfile,
    curated_skills: list[dict],
    total_years: float | None = None,
    education: list[str] | None = None,
) -> MergedEvidenceProfile:
    """Merge CandidateProfile with curated resume skill data.

    curated_skills is a list of dicts with keys: name, depth, duration, source_context.
    This replaces merge_profiles() when curated data is available.
    """
    taxonomy = _get_taxonomy()

    # Build session skill lookup
    from claude_candidate.schemas.candidate_profile import SkillEntry
    session_skills: dict[str, SkillEntry] = {}
    for s in candidate_profile.skills:
        canonical = taxonomy.canonicalize(s.name)
        session_skills[canonical] = s

    # Build curated resume lookup
    curated_lookup: dict[str, dict] = {}
    for cs in curated_skills:
        canonical = taxonomy.canonicalize(cs["name"])
        # Keep entry with higher depth if duplicates
        existing = curated_lookup.get(canonical)
        cs_depth = DepthLevel(cs.get("depth", "mentioned")) if cs.get("depth", "mentioned") in [d.value for d in DepthLevel] else DepthLevel.MENTIONED
        if existing is None:
            curated_lookup[canonical] = cs
        else:
            ex_depth = DepthLevel(existing.get("depth", "mentioned")) if existing.get("depth", "mentioned") in [d.value for d in DepthLevel] else DepthLevel.MENTIONED
            if DEPTH_RANK.get(cs_depth, 0) > DEPTH_RANK.get(ex_depth, 0):
                curated_lookup[canonical] = cs

    all_names = set(session_skills.keys()) | set(curated_lookup.keys())
    merged_skills = []
    counts = {"corroborated": 0, "resume_only": 0, "sessions_only": 0}
    discovery_skills = []

    for name in sorted(all_names):
        s_skill = session_skills.get(name)
        c_skill = curated_lookup.get(name)

        in_sessions = s_skill is not None
        in_resume = c_skill is not None

        # Map curated depth string to DepthLevel
        r_depth = None
        if c_skill:
            depth_str = c_skill.get("depth", "mentioned")
            r_depth = DepthLevel(depth_str) if depth_str in [d.value for d in DepthLevel] else DepthLevel.MENTIONED

        s_depth = s_skill.depth if s_skill else None

        source = classify_evidence_source(in_resume, in_sessions, r_depth, s_depth)
        effective_depth = MergedSkillEvidence.compute_effective_depth(source, r_depth, s_depth)
        confidence = MergedSkillEvidence.compute_confidence(
            source,
            s_skill.frequency if s_skill else None,
            c_skill.get("source_context") if c_skill else None,
        )

        is_discovery = (
            source == EvidenceSource.SESSIONS_ONLY
            and DEPTH_RANK.get(s_depth, 0) >= DEPTH_RANK[DepthLevel.APPLIED]
        )

        if source == EvidenceSource.CORROBORATED:
            counts["corroborated"] += 1
        elif source == EvidenceSource.RESUME_ONLY:
            counts["resume_only"] += 1
        elif source == EvidenceSource.SESSIONS_ONLY:
            counts["sessions_only"] += 1

        if is_discovery:
            discovery_skills.append(name)

        merged_skills.append(MergedSkillEvidence(
            name=name,
            source=source,
            resume_depth=r_depth,
            resume_context=c_skill.get("source_context") if c_skill else None,
            resume_years=None,  # curated uses duration string instead
            resume_duration=c_skill.get("duration") if c_skill else None,
            session_depth=s_depth,
            session_frequency=s_skill.frequency if s_skill else None,
            session_evidence_count=len(s_skill.evidence) if s_skill else None,
            session_recency=s_skill.recency if s_skill else None,
            effective_depth=effective_depth,
            confidence=confidence,
            discovery_flag=is_discovery,
        ))

    # Sort by source priority then depth
    source_order = {
        EvidenceSource.CORROBORATED: 0,
        EvidenceSource.SESSIONS_ONLY: 1,
        EvidenceSource.RESUME_ONLY: 2,
        EvidenceSource.CONFLICTING: 3,
    }
    merged_skills.sort(key=lambda s: (
        source_order.get(s.source, 9),
        -DEPTH_RANK.get(s.effective_depth, 0),
    ))

    from claude_candidate.manifest import hash_json_stable
    profile_hash = hash_json_stable({"candidate": candidate_profile.manifest_hash, "curated": "curated"})

    merged = MergedEvidenceProfile(
        skills=merged_skills,
        patterns=candidate_profile.problem_solving_patterns,
        projects=candidate_profile.projects,
        roles=[],
        corroborated_skill_count=counts["corroborated"],
        resume_only_skill_count=counts["resume_only"],
        sessions_only_skill_count=counts["sessions_only"],
        discovery_skills=discovery_skills,
        profile_hash=profile_hash,
        resume_hash="curated",
        candidate_profile_hash=candidate_profile.manifest_hash,
        merged_at=datetime.now(),
    )
    merged.total_years_experience = total_years
    merged.education = education or []
    return merged
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest`

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/merger.py src/claude_candidate/schemas/merged_profile.py tests/test_merger.py
git commit -m "Add merge_with_curated() for curated resume data with duration tracking"
```

---

## Task 7: Extraction Normalization (Fix 1)

**Files:**
- Modify: `src/claude_candidate/server.py`
- Modify: `src/claude_candidate/requirement_parser.py`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write a normalization helper function**

Add to `src/claude_candidate/requirement_parser.py`:

```python
def normalize_skill_mappings(requirements: list[dict], taxonomy=None) -> list[dict]:
    """Normalize skill_mapping entries through the taxonomy.

    Matched entries are replaced with canonical names.
    Unmatched entries are preserved as-is.
    Returns modified requirements list (mutates in place).
    """
    if taxonomy is None:
        from claude_candidate.skill_taxonomy import SkillTaxonomy
        taxonomy = SkillTaxonomy.load_default()

    for req in requirements:
        normalized = []
        for skill_name in req.get("skill_mapping", []):
            canonical = taxonomy.match(skill_name)
            normalized.append(canonical if canonical else skill_name)
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for name in normalized:
            if name not in seen:
                seen.add(name)
                deduped.append(name)
        req["skill_mapping"] = deduped
    return requirements
```

- [ ] **Step 2: Wire normalization into server extraction endpoint**

In `server.py`, after Claude returns the extracted requirements JSON, add:

```python
from claude_candidate.requirement_parser import normalize_skill_mappings
# ... after parsing Claude's response ...
if "requirements" in parsed:
    normalize_skill_mappings(parsed["requirements"])
```

- [ ] **Step 3: Write test**

```python
def test_normalize_skill_mappings():
    from claude_candidate.requirement_parser import normalize_skill_mappings
    reqs = [
        {"skill_mapping": ["python3", "django", "system design"]},
        {"skill_mapping": ["k8s", "docker-compose"]},
    ]
    normalize_skill_mappings(reqs)
    # python3 -> python (via alias), django stays (not in taxonomy), system design stays
    assert "python" in reqs[0]["skill_mapping"]
    # k8s -> kubernetes, docker-compose -> docker
    assert "kubernetes" in reqs[1]["skill_mapping"]
    assert "docker" in reqs[1]["skill_mapping"]
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest`

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/requirement_parser.py src/claude_candidate/server.py tests/
git commit -m "Add post-extraction skill mapping normalization through taxonomy"
```

---

## Task 8: Experience & Skill Years Matching (Fix 6)

**Files:**
- Modify: `src/claude_candidate/quick_match.py`
- Modify: `tests/test_quick_match.py`

- [ ] **Step 1: Write failing test**

```python
def test_years_experience_boosts_match():
    """When requirement has years_experience and skill has duration, score should improve."""
    from claude_candidate.quick_match import _parse_duration_years
    # Test the duration parser first
    assert _parse_duration_years("8 years") == 8.0
    assert _parse_duration_years("2 months") == 2.0 / 12.0
    assert _parse_duration_years(None) is None
    assert _parse_duration_years("") is None
    # Full integration test: implementer should create a profile with
    # resume_duration="8 years" on a skill, a requirement with years_experience=5,
    # and verify the status gets boosted vs without years matching.
```

- [ ] **Step 2: Implement years matching in `_find_best_skill` or a new helper**

Add a helper that checks `resume_duration` on matched skills:

```python
def _parse_duration_years(duration: str | None) -> float | None:
    """Parse duration string like '8 years', '2 months' into years."""
    if not duration:
        return None
    import re
    match = re.match(r'(\d+)\s*(year|month|yr|mo)', duration.lower())
    if not match:
        return None
    value = int(match.group(1))
    unit = match.group(2)
    if unit.startswith("mo"):
        return value / 12.0
    return float(value)
```

Then in the scoring path, after finding a match and computing status:

```python
# Years experience boost: if requirement specifies years and skill has duration data
if req.years_experience and best_match and best_match.resume_duration:
    candidate_years = _parse_duration_years(best_match.resume_duration)
    if candidate_years:
        if candidate_years >= req.years_experience:
            # Boost status by one tier if not already exceeds
            if best_status == "partial_match":
                best_status = "strong_match"
            elif best_status == "adjacent":
                best_status = "partial_match"
```

Also handle the case where there's no skill match but total_years_experience covers it:

```python
if req.years_experience and best_status == "no_evidence":
    if profile.total_years_experience and profile.total_years_experience >= req.years_experience:
        # They have the general experience even without the specific skill
        best_status = "related"
        # Synthesize minimal evidence
        best_match = MergedSkillEvidence(
            name="general_experience",
            source=EvidenceSource.RESUME_ONLY,
            effective_depth=DepthLevel.APPLIED,
            confidence=0.5,
        )
```

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest`

- [ ] **Step 4: Commit**

```bash
git add src/claude_candidate/quick_match.py tests/test_quick_match.py
git commit -m "Add experience years matching: duration boost and total years fallback"
```

---

## Task 9: Golden Set Export Script

**Files:**
- Create: `scripts/export_golden_set.py`
- Create: `tests/golden_set/postings/` (25 JSON files)
- Create: `tests/golden_set/expected_grades.json`

- [ ] **Step 1: Create export script**

```python
#!/usr/bin/env python3
"""Export cached postings from assessments.db into golden set fixtures."""

import json
import re
import sqlite3
from pathlib import Path

from claude_candidate.skill_taxonomy import SkillTaxonomy
from claude_candidate.requirement_parser import normalize_skill_mappings


def slugify(company: str, title: str) -> str:
    """Generate a filename slug from company and title."""
    combined = f"{company}-{title}".lower()
    combined = re.sub(r'[^a-z0-9]+', '-', combined)
    return combined.strip('-')[:60]


def export():
    db_path = Path.home() / ".claude-candidate" / "assessments.db"
    output_dir = Path("tests/golden_set/postings")
    output_dir.mkdir(parents=True, exist_ok=True)

    taxonomy = SkillTaxonomy.load_default()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cur = conn.execute("SELECT url, data FROM posting_cache ORDER BY extracted_at")
    rows = cur.fetchall()

    expected_grades = {}
    stats = {"total": 0, "normalized": 0, "unmatched": 0}

    for row in rows:
        data = json.loads(row["data"])
        company = data.get("company", "Unknown")
        title = data.get("title", "Unknown")
        slug = slugify(company, title)

        # Skip postings with 0 requirements
        reqs = data.get("requirements", [])
        if not reqs:
            print(f"  SKIP (no requirements): {company} — {title}")
            continue

        # Normalize requirements
        for req in reqs:
            original = list(req.get("skill_mapping", []))
            normalize_skill_mappings([req], taxonomy)
            for orig, norm in zip(original, req.get("skill_mapping", [])):
                if orig != norm:
                    stats["normalized"] += 1
                else:
                    canonical = taxonomy.match(orig)
                    if not canonical:
                        stats["unmatched"] += 1

        # Write posting file
        posting_path = output_dir / f"{slug}.json"
        posting_path.write_text(json.dumps(data, indent=2))
        stats["total"] += 1

        # Stub expected grade
        expected_grades[slug] = {
            "expected": "?",
            "rationale": f"{company} — {title}",
        }

        print(f"  Exported: {slug}.json ({len(reqs)} reqs)")

    # Write expected grades stub
    grades_path = Path("tests/golden_set/expected_grades.json")
    grades_path.write_text(json.dumps(expected_grades, indent=2))

    conn.close()
    print(f"\n=== Export Complete ===")
    print(f"Postings: {stats['total']}")
    print(f"Skill mappings normalized: {stats['normalized']}")
    print(f"Skill mappings unmatched: {stats['unmatched']}")
    print(f"\nExpected grades stub: {grades_path}")
    print(f">>> Fill in expected grades before launching ralph-loop <<<")


if __name__ == "__main__":
    export()
```

- [ ] **Step 2: Run the export**

Run: `.venv/bin/python scripts/export_golden_set.py`

Verify: 24-25 JSON files created in `tests/golden_set/postings/`, normalization stats printed.

- [ ] **Step 3: Commit**

```bash
git add scripts/export_golden_set.py tests/golden_set/
git commit -m "Add golden set: export 25 real LinkedIn postings with normalized requirements"
```

---

## Task 10: Benchmark Script

**Files:**
- Create: `tests/golden_set/benchmark_accuracy.py`

- [ ] **Step 1: Create benchmark script**

The benchmark script needs to:
1. Load all posting files from `tests/golden_set/postings/`
2. Load `expected_grades.json`
3. Load the merged profile (from `~/.claude-candidate/` or `tests/fixtures/`)
4. Run `QuickMatchEngine.assess()` for each posting
5. Compare actual vs expected grades
6. Output structured diagnostic report
7. Append to `benchmark_history.jsonl`

Key code structure:

```python
#!/usr/bin/env python3
"""Benchmark skill matching accuracy against golden set."""

import json
import sys
from datetime import datetime
from pathlib import Path

from claude_candidate.quick_match import QuickMatchEngine
from claude_candidate.schemas.job_requirements import QuickRequirement
from claude_candidate.schemas.merged_profile import MergedEvidenceProfile


GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]

def grade_distance(actual: str, expected: str) -> int:
    """Ordinal distance between two grades. Positive = actual is lower."""
    try:
        return GRADE_ORDER.index(actual) - GRADE_ORDER.index(expected)
    except ValueError:
        return 99


def load_profile() -> MergedEvidenceProfile:
    """Load merged profile from standard location."""
    profile_path = Path.home() / ".claude-candidate" / "merged_profile.json"
    if not profile_path.exists():
        # Fallback to generating on the fly
        from claude_candidate.schemas.candidate_profile import CandidateProfile
        cp_path = Path.home() / ".claude-candidate" / "candidate_profile.json"
        curated_path = Path.home() / ".claude-candidate" / "curated_resume.json"
        cp = CandidateProfile.from_json(cp_path.read_text())
        curated = json.loads(curated_path.read_text())
        from claude_candidate.merger import merge_with_curated
        return merge_with_curated(
            cp,
            curated.get("curated_skills", []),
            total_years=curated.get("total_years_experience"),
            education=curated.get("education", []),
        )
    return MergedEvidenceProfile.from_json(profile_path.read_text())


def run_benchmark():
    golden_dir = Path("tests/golden_set")
    postings_dir = golden_dir / "postings"
    expected_path = golden_dir / "expected_grades.json"
    history_path = golden_dir / "benchmark_history.jsonl"

    expected = json.loads(expected_path.read_text())
    profile = load_profile()
    engine = QuickMatchEngine(profile)

    results = {}
    taxonomy_gaps = 0
    soft_skill_gaps = 0
    total_must_haves = 0
    met_must_haves = 0

    for posting_file in sorted(postings_dir.glob("*.json")):
        slug = posting_file.stem
        if slug not in expected:
            continue

        data = json.loads(posting_file.read_text())
        reqs = [QuickRequirement(**r) for r in data.get("requirements", [])]

        assessment = engine.assess(
            requirements=reqs,
            company=data.get("company", "Unknown"),
            title=data.get("title", "Unknown"),
            posting_url=data.get("url"),
            source="golden_set",
            seniority=data.get("seniority", "unknown"),
        )

        exp_grade = expected[slug]["expected"]
        actual_grade = assessment.overall_grade
        delta = grade_distance(actual_grade, exp_grade)
        score_pct = round(assessment.overall_score * 100, 1)

        # Count must-have coverage
        for detail in assessment.skill_matches:
            if detail.priority == "must_have":
                total_must_haves += 1
                if detail.match_status in ("strong_match", "exceeds"):
                    met_must_haves += 1
                elif detail.match_status == "no_evidence":
                    # Check if it's a taxonomy gap
                    taxonomy_gaps += 1

        results[slug] = {
            "actual": actual_grade,
            "expected": exp_grade,
            "delta": delta,
            "score": score_pct,
            "skill_score": round(assessment.skill_match.score * 100, 1),
        }

    # Compute summary stats
    exact = sum(1 for r in results.values() if r["delta"] == 0)
    within_1 = sum(1 for r in results.values() if abs(r["delta"]) <= 1 and abs(r["score"] - _grade_to_midpoint(r["expected"])) <= 10)
    off_by_2 = len(results) - within_1
    avg_delta = sum(r["delta"] for r in results.values()) / max(len(results), 1)

    # Stage diagnosis
    must_have_pct = round(met_must_haves / max(total_must_haves, 1) * 100)

    # Print report
    print(f"=== ACCURACY BENCHMARK ({len(results)} postings) ===")
    print(f"Exact match: {exact}/{len(results)} | Within 1 grade: {within_1}/{len(results)} | Off by 2+: {off_by_2}/{len(results)}")
    print(f"Avg grade delta: {avg_delta:+.1f}")
    print(f"Must-have coverage: {must_have_pct}% ({met_must_haves}/{total_must_haves})")
    print()

    # Stage diagnosis
    if taxonomy_gaps > len(results) * 0.1:
        print(f"  >>> FOCUS: Stage 1 (Taxonomy) — {taxonomy_gaps} must-have no_evidence gaps")
    elif must_have_pct < 70:
        print(f"  >>> FOCUS: Stage 2 (Requirement handling) — must-have coverage {must_have_pct}%")
    else:
        print(f"  >>> FOCUS: Stage 3 (Calibration) — fine-tune weights and thresholds")
    print()

    # Worst mismatches
    worst = sorted(results.items(), key=lambda x: abs(x[1]["delta"]), reverse=True)[:5]
    print("WORST MISMATCHES:")
    for slug, r in worst:
        if abs(r["delta"]) > 1:
            print(f"  {slug:.<45} actual={r['actual']:>3} expected={r['expected']:>3} delta={r['delta']:+d} score={r['score']}%")

    # Correct
    correct = [(s, r) for s, r in results.items() if abs(r["delta"]) <= 1]
    if correct:
        print(f"\nWITHIN TOLERANCE ({len(correct)}):")
        for slug, r in correct[:5]:
            print(f"  {slug:.<45} actual={r['actual']:>3} expected={r['expected']:>3}")

    # Append to history
    entry = {
        "timestamp": datetime.now().isoformat(),
        "exact_match": exact,
        "within_1": within_1,
        "off_by_2_plus": off_by_2,
        "avg_delta": round(avg_delta, 2),
        "must_have_pct": must_have_pct,
        "postings": results,
    }
    with open(history_path, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # Exit code for CI
    if within_1 == len(results):
        print("\n*** ALL POSTINGS WITHIN TOLERANCE ***")
        sys.exit(0)
    else:
        sys.exit(1)


def _grade_to_midpoint(grade: str) -> float:
    """Approximate midpoint score for a grade."""
    midpoints = {"A+": 97, "A": 92, "A-": 87, "B+": 82, "B": 77, "B-": 72,
                 "C+": 67, "C": 62, "C-": 57, "D": 50, "F": 25}
    return midpoints.get(grade, 50)


if __name__ == "__main__":
    run_benchmark()
```

- [ ] **Step 2: Test the benchmark runs (will fail until expected grades are filled in)**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`

It should produce output even with "?" expected grades.

- [ ] **Step 3: Commit**

```bash
git add tests/golden_set/benchmark_accuracy.py
git commit -m "Add benchmark script for golden set accuracy measurement"
```

---

## Task 11: Ralph-Loop PROMPT.md

**Files:**
- Create: `.claude/ralph-accuracy-prompt.md`

- [ ] **Step 1: Write the PROMPT.md**

Copy the PROMPT.md content from the spec (Section "Phase 3: Ralph Loop") into `.claude/ralph-accuracy-prompt.md`.

- [ ] **Step 2: Commit**

```bash
git add .claude/ralph-accuracy-prompt.md
git commit -m "Add ralph-loop PROMPT.md for accuracy improvement iterations"
```

---

## Task 12: Profile Regeneration (Manual — Brian required)

This task requires Brian to run `sessions scan` locally.

- [ ] **Step 1: Brian runs sessions scan**

```bash
.venv/bin/claude-candidate sessions scan --session-dir ~/.claude/projects/ --output ~/.claude-candidate/candidate_profile.json
```

- [ ] **Step 2: Generate merged profile with curated data**

```bash
.venv/bin/python -c "
import json
from pathlib import Path
from claude_candidate.schemas.candidate_profile import CandidateProfile
from claude_candidate.merger import merge_with_curated

cp = CandidateProfile.from_json(Path.home().joinpath('.claude-candidate/candidate_profile.json').read_text())
curated = json.loads(Path.home().joinpath('.claude-candidate/curated_resume.json').read_text())
merged = merge_with_curated(
    cp,
    curated.get('curated_skills', []),
    total_years=curated.get('total_years_experience'),
    education=curated.get('education', []),
)
Path.home().joinpath('.claude-candidate/merged_profile.json').write_text(merged.to_json())
print(f'Merged profile: {len(merged.skills)} skills')
print(f'Corroborated: {merged.corroborated_skill_count}')
print(f'Sessions only: {merged.sessions_only_skill_count}')
print(f'Resume only: {merged.resume_only_skill_count}')
"
```

- [ ] **Step 3: Verify profile quality**

Check that key skills show real data:
- TypeScript: expert, 8yr, 45+ sessions
- Python: deep, 2yr, 89+ sessions
- React: applied/deep, sessions evidence

---

## Task 13: Final Clean Commit + Baseline Benchmark

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest`

Expected: ALL tests pass

- [ ] **Step 2: Run benchmark to record baseline**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`

This records the pre-ralph baseline in `benchmark_history.jsonl`.

- [ ] **Step 3: Create clean baseline commit**

```bash
git add -A
git commit -m "Pre-ralph baseline: 8 structural fixes + golden set + benchmark

Fixes applied:
- Canonicalization consistency (taxonomy.match() in all lookups)
- Related skill fallback (are_related() -> 'related' status at 0.25)
- Confidence floor (0.5 minimum multiplier)
- Soft skill category (5 entries, 0.3x weight discount)
- Compound requirement scoring (max(best, average))
- Curated resume merger (depth + duration from curated_skills)
- Extraction normalization (post-extraction taxonomy pass)
- Experience years matching (duration boost + total years fallback)

Golden set: 25 real LinkedIn postings with normalized requirements
Benchmark: accuracy measurement with stage diagnosis"
```

---

## Verification Gate

After all tasks:
1. Full test suite passes
2. Golden set exported with 25 postings
3. Benchmark script runs and produces structured output
4. Merged profile exists with real session + curated data
5. Ralph-loop PROMPT.md is ready
6. Brian has filled in expected grades in `expected_grades.json`
7. Clean baseline commit on feature branch

**Then:** Brian reviews, fills in expected grades, and launches:
```bash
/ralph-loop "improve skill matching accuracy" --max-iterations 20 --completion-promise "ACCURACY ACHIEVED"
```
