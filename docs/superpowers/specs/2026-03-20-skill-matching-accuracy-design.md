# Skill Matching Accuracy Improvement — Design Spec

**Date:** 2026-03-20
**Status:** Draft
**Goal:** Fix skill matching accuracy so assessments produce realistic grades, then iteratively improve via ralph-loop until all 25 real job postings score within 1 letter grade AND 10 percentage points of expected.

---

## Problem Statement

The matching engine grades almost everything D/F. The Anthropic Claude Code role — a near-perfect fit — scores C (60.6%). NPR Senior AI Engineer scores D (50.8%). 62 assessments across 25 unique LinkedIn postings show systemic underscoring.

**Root causes (12 issues identified by audit):**

| # | Issue | Category | Impact |
|---|---|---|---|
| 1 | Extraction prompt doesn't reference taxonomy — Claude generates arbitrary skill names | Extraction | Root cause of all mismatches |
| 2 | No related skill fallback — `are_related()` never called during matching | Matching | -15 to -25% |
| 3 | Merger reads shallow resume_profile, not curated_resume with depths/durations | Profile | All resume skills undervalued |
| 4 | No merged_profile.json exists — server can't load it | Profile | Matching uses incomplete data |
| 5 | Canonicalization mismatch — merger normalizes with spaces, matcher with hyphens | Matching | -10 to -20% |
| 6 | Confidence multiplier double-penalizes low-frequency skills | Scoring | -5 to -15% |
| 7 | Soft skills not categorized or filtered | Taxonomy | Inflates gap count |
| 8 | Compound requirements not split | Extraction | All-or-nothing scoring |
| 9 | Experience years not matched to skill durations | Matching | "5+ years Python" = no_evidence |
| 10 | Curated skill durations (e.g. TypeScript 8yr) never used in matching | Profile | Real data ignored |
| 11 | Experience/education default to 0.9 when no requirement — currently masks skill gaps but will need recalibration after skill scoring is fixed | Scoring | Deferred to Phase 2 (calibration) |
| 12 | Grade curve may need recalibration after fixes shift score distribution | Calibration | Deferred to Phase 2 (calibration) |

**Issue-to-Fix mapping:** Fix 0 → Issues 3,4,10. Fix 1 → Issue 1. Fix 2 → Issue 5 (canonicalization). Fix 3 → Issue 2 (related skill fallback). Fix 4 → Issue 7. Fix 5 → Issue 8. Fix 6 → Issue 9. Fix 7 → Issue 6. Issues 11,12 → deferred to ralph-loop Stage 3 (calibration).

---

## Architecture: Two-Phase Approach

### Phase 1: Pre-Fixes (deterministic bug fixes, committed as clean baseline)

Seven structural fixes implemented manually, producing a single clean commit. All tests passing. Benchmark run to record pre-ralph baseline scores.

### Phase 2: Ralph Loop (iterative accuracy improvement)

Ralph-loop iterates on the benchmark, fixing one issue per iteration with staged priority: taxonomy expansion -> requirement handling -> scoring calibration.

---

## Phase 1: Pre-Fixes

### Fix 0: Profile Refresh

**Problem:** Candidate profile shows 0 sessions for all skills. Resume profile has all skills as "mentioned" with no years. No merged profile exists. The curated resume (`~/.claude-candidate/curated_resume.json`) has rich data (40 skills with depth + duration) but the merger reads the shallow `resume_profile.json` instead.

**Fix:**
1. Update `merger.py` to accept and prefer curated resume data when available
   - Load `curated_resume.json`, extract `curated_skills` array
   - Map curated depth/duration into `ResumeSkill` objects with proper `implied_depth` and `years_experience`
   - Fall back to `resume_profile.json` if no curated data exists
2. Re-run `sessions scan` to rebuild `candidate_profile.json` with real session counts
3. Run `profile merge` to generate `merged_profile.json`
4. Verify merged profile has corroborated skills with real session counts and curated depths

**Prerequisites:** Step 2 (`sessions scan`) requires access to `~/.claude/projects/` and takes ~2-5 minutes for 247 sessions. This is a local-only operation Brian runs manually. The resulting `candidate_profile.json` is committed alongside other profile artifacts as part of the golden set fixture data.

**Files modified:**
- `src/claude_candidate/merger.py`
- `src/claude_candidate/cli.py` (merge command to accept curated resume path)

**Verification:** Merged profile shows TypeScript as expert (8yr, 45+ sessions), Python as deep (2yr, 89 sessions), etc.

### Fix 1: Extraction Normalization

**Problem:** The extraction prompt (`server.py:678`) tells Claude to generate "normalized skill names" but doesn't list the taxonomy. Claude invents names like "system design", "microservices", "django" that don't exist in the 30-skill taxonomy. Cached postings have these poisoned skill_mapping values.

**Fix:**
1. Add post-extraction normalization step: after Claude returns requirements, run each `skill_mapping` entry through `SkillTaxonomy.match()` to canonicalize
   - Matched entries get replaced with canonical names
   - Unmatched entries are preserved as-is (ralph-loop will expand taxonomy to cover these)
2. Update extraction prompt to include the full taxonomy list as guidance (not a hard constraint — new skills can still be extracted, they just won't match until taxonomy is expanded)
3. For the golden set: export cached postings and normalize their requirements during export

**Files modified:**
- `src/claude_candidate/server.py` (extraction endpoint + normalization step)
- `src/claude_candidate/requirement_parser.py` (same normalization)

**Not changed:** Cached posting_cache data is NOT re-extracted (would require API calls). Golden set export handles normalization. Existing local `.requirements.json` files (e.g., `tests/fixtures/sample_job_posting.requirements.json`) are not auto-normalized — they should be manually updated or the export script can normalize them.

### Fix 2: Canonicalization Consistency

> **Note:** This fix must be applied BEFORE Fix 3 (Related Skill Fallback), since the relatedness check depends on consistent canonical names.

**Problem:** The merger canonicalizes skills using `taxonomy.canonicalize()` which returns lowercase with spaces. The matcher searches using `skill_name.lower().strip()` which preserves hyphens. Result: merger stores "ci cd", matcher searches for "ci-cd" — no match.

**Fix:**
Ensure all skill name lookups go through `taxonomy.canonicalize()` or `taxonomy.match()` consistently:
1. In `_find_exact_match()`: canonicalize the search term before profile lookup
2. In `_find_fuzzy_match()`: same
3. Profile skill keys should be canonical names (already done by merger)

**Files modified:**
- `src/claude_candidate/quick_match.py` (matching functions)

### Fix 3: Related Skill Fallback

**Problem:** `SkillTaxonomy.are_related()` exists and works but is never called during skill matching. When exact, fuzzy, and pattern matches all fail, the matcher returns `(None, "no_evidence")` even if a closely related skill exists in the profile.

**Fix:**
In `_find_best_skill()` in `quick_match.py`, after exact/fuzzy/pattern matching fails for a skill name:
1. Canonicalize BOTH the requirement skill name and each profile skill name via `taxonomy.canonicalize()`
2. Check `taxonomy.are_related(canonical_req, canonical_profile)` for all profile skills
3. If a related skill is found, return it with status `"related"` (score 0.25)
4. This is distinct from depth-based `"adjacent"` (score 0.3): `adjacent` means the skill matches but depth is low; `related` means a different-but-related skill exists

**New status:** Add `"related"` to `STATUS_SCORE` (value 0.25), `STATUS_RANK` (value between no_evidence and adjacent), and any display markers in `quick_match.py`. This distinguishes "has a related skill" (weaker signal) from "has the exact skill at insufficient depth" (stronger signal, adjacent=0.3).

**Example:** Requirement asks for "claude-api", profile has "anthropic" (related) → `related` (0.25) instead of `no_evidence` (0.0).

**Files modified:**
- `src/claude_candidate/quick_match.py` (`_find_best_skill()`, `STATUS_SCORE`)
- `src/claude_candidate/schemas/fit_assessment.py` (add "related" to valid statuses if enum-constrained)
- `tests/test_quick_match.py` (test related skill fallback)

### Fix 4: Soft Skill Category + Filtering

**Problem:** Requirements like "excellent communication skills", "collaborative approach", "passion for developer tools" are treated as must-have skill gaps with full weight (3.0x). The taxonomy has no concept of soft skills.

**Fix:**
1. Add `"soft_skill"` category to taxonomy with entries: `communication`, `collaboration`, `leadership`, `mentorship`, `problem-solving`, `adaptability`
2. Add aliases for common phrasings: "excellent communication skills" -> communication, "team player" -> collaboration
3. In `quick_match.py`: when scoring a requirement whose skill_mapping resolves to soft_skill category, apply an initial discount factor of 0.3x (ralph-loop can tune this in Stage 3 calibration)
4. Soft skills matched via behavioral patterns: `documentation_driven` -> communication, `collaborative` patterns -> collaboration

**Why 0.3x?** Soft skills are real requirements but should not dominate a technical assessment. A communication gap should not tank the score the same way a missing Python requirement does. The 0.3x is an initial value — ralph-loop can calibrate it during Stage 3.

**Files modified:**
- `src/claude_candidate/data/taxonomy.json` (add soft_skill entries)
- `src/claude_candidate/skill_taxonomy.py` (ensure `get_category()` works for soft_skill category)
- `src/claude_candidate/quick_match.py` (soft skill weight discount)
- `tests/test_quick_match.py`

### Fix 5: Compound Requirement Scoring

**Problem:** Requirements like "5+ years of professional experience in software development, data science, or machine learning engineering" have multiple `skill_mapping` entries but are scored by taking only the single best match. If you match 2/3 constituent skills, the score only reflects the best one — no credit for breadth.

**Current behavior:** `_find_best_skill()` iterates over `req.skill_mapping` and returns the single highest-status match.

**Fix:** Change scoring to use `max(best_single_match, average_of_all_matches)`:
1. Score each constituent skill independently via `_find_skill_match()`
2. Compute both: (a) best single match score, (b) average of all constituent scores
3. Requirement score = `max(best, average)` — this ensures breadth is rewarded without penalizing a single strong match

**Worked example:**
- Requirement: "Python, data science, or ML" → skill_mapping: ["python", "data-science", "machine-learning"]
- Profile has: python (exceeds=1.0), data-science (no_evidence=0.0), machine-learning (partial=0.55)
- Current: best = 1.0 (takes python only)
- New: best = 1.0, average = (1.0 + 0.0 + 0.55) / 3 = 0.52, final = max(1.0, 0.52) = 1.0
- In this case, no change. But for a requirement with 3 partial matches averaging 0.6, the average (0.6) would beat a single best of 0.55.

**Files modified:**
- `src/claude_candidate/quick_match.py` (requirement scoring logic)
- `tests/test_quick_match.py` (compound scoring tests)

### Fix 6: Experience & Skill Years Matching

**Problem:** Requirements like "5+ years of Python experience" map to a skill but the matcher only checks depth, not duration. The curated resume has "python: deep, 2 years" and total_years_experience=12.4, but this data is never consulted.

**Fix:**
1. When a requirement has `years_experience` set AND a skill match is found:
   - Check the matched skill's duration from curated data
   - If duration >= required years: boost status by one tier (e.g., partial -> strong)
   - If duration < required years but > 0: apply proportional credit
2. When a requirement has `years_experience` set but NO skill match:
   - Check `total_years_experience` from the resume profile
   - If total years >= required: score as "partial_match" (they have the experience, maybe not the specific skill)
3. Industry/domain matching: when requirement mentions domain keywords (e.g., "edtech", "media"), check role descriptions for matching domains

**Files modified:**
- `src/claude_candidate/quick_match.py` (years matching logic)
- `src/claude_candidate/schemas/merged_profile.py` (ensure duration data is accessible)

### Fix 7: Confidence Floor

**Problem:** The confidence score is multiplied directly into the status score. A skill demonstrated in 3 sessions gets confidence=0.45. Combined with partial_match (0.55): 0.55 x 0.45 = 0.25 — grades as F for a skill you demonstrably have.

**Fix:**
Floor the confidence multiplier at 0.5:
```python
effective_confidence = max(best_match.confidence, 0.5)
req_score = STATUS_SCORE[best_status] * effective_confidence
```

**Worked examples:**
- Sessions-only, freq < 5 (conf=0.45): partial_match before = 0.55×0.45 = **0.25**, after = 0.55×0.50 = **0.28** (+12%)
- Sessions-only, freq 5-20 (conf=0.65): partial_match before = 0.55×0.65 = **0.36**, after = same (above floor)
- Resume-only, vague (conf=0.3): strong_match before = 0.85×0.3 = **0.26**, after = 0.85×0.5 = **0.43** (+65%)

The floor prevents resume-only or low-frequency skills from cratering. The confidence still modulates trust above the floor.

**Files modified:**
- `src/claude_candidate/quick_match.py` (`_score_requirement()`)

---

## Phase 1 Deliverables

After all 7 pre-fixes:
1. All existing tests pass (700+)
2. New tests added for each fix
3. Merged profile exists with real data (curated depths + session counts)
4. Golden set exported (25 postings with normalized requirements + expected grades placeholder)
5. Benchmark script working
6. Single clean commit on feature branch
7. Benchmark run to record **pre-ralph baseline scores**

---

## Phase 2: Golden Set & Benchmark

### Golden Set Export Script

**File:** `scripts/export_golden_set.py`

Exports all 25 cached postings from the SQLite `posting_cache` table into individual JSON files with normalized requirements.

**Logic:**
1. Connect to `~/.claude-candidate/assessments.db`
2. Query all rows from `posting_cache`
3. For each posting:
   a. Parse the cached JSON data
   b. For each requirement's `skill_mapping` entries, run through `SkillTaxonomy.match()`
   c. Replace matched entries with canonical names
   d. Preserve unmatched entries as-is (flagged with `"_normalized": false` in output)
   e. Generate a slug filename from company + title (e.g., `anthropic-claude-code.json`)
   f. Write to `tests/golden_set/postings/`
4. Log normalization stats: X entries normalized, Y entries unmatched
5. Generate a stub `expected_grades.json` with all posting slugs and empty expected grades for Brian to fill in

**Validation:** The export script prints a report showing which skill_mapping entries were normalized and which remain unmatched. This report helps identify which taxonomy entries ralph will need to add.

### Golden Set Structure

```
tests/golden_set/
  postings/
    anthropic-claude-code.json
    npr-senior-ai-engineer.json
    adobe-senior-applied-ai.json
    disney-sr-staff-rd.json
    disney-interactive-viz.json
    microsoft-senior-applied-ai.json
    microsoft-ai-sr-pm.json
    staffing-science-agentic.json
    cohere-agent-infrastructure.json
    suno-staff-se.json
    arcadia-ai-agents.json
    deeprec-ai-agentic.json
    backflip-ai-systems.json
    substack-fullstack-product.json
    change-org-ai-tools.json
    motion-recruitment-react-unity.json
    adobe-senior-sde.json
    milwaukee-brewers-baseball.json
    kiddom-ml-engineer.json
    nobody-studios-ai.json
    interplay-principal-react.json
    schoolai-fullstack.json
    fullstack-principal-agentic.json
    imbue-product-engineer.json
    product-ai-commerce.json
  expected_grades.json        # User fills in before ralph starts
  benchmark_accuracy.py       # Benchmark script
  benchmark_history.jsonl     # Iteration-over-iteration log (blog fuel)
```

### Posting JSON Format

Each posting file contains the full data from `posting_cache`, with requirements normalized through the taxonomy:

```json
{
  "company": "Anthropic",
  "title": "Software Engineer, Claude Code",
  "description": "...",
  "url": "https://www.linkedin.com/jobs/view/...",
  "location": "New York City Metropolitan Area",
  "seniority": "senior",
  "remote": false,
  "salary": "$320,000 - $560,000 USD",
  "requirements": [
    {
      "description": "Hands-on experience working with large language models",
      "skill_mapping": ["llm", "anthropic"],
      "priority": "must_have",
      "years_experience": null,
      "education_level": null,
      "source_text": "..."
    }
  ]
}
```

### Expected Grades JSON

User (Brian) fills this in before launching ralph:

```json
{
  "anthropic-claude-code": { "expected": "A-", "rationale": "Literally build Claude Code tools" },
  "npr-senior-ai-engineer": { "expected": "B+", "rationale": "MCP + agentic + Python, media domain gap" },
  "microsoft-ai-sr-pm": { "expected": "F", "rationale": "PM role, not engineering" },
  "..."
}
```

### Benchmark Script Output

```
=== ACCURACY BENCHMARK (25 postings) — Iteration #3 ===
Exact match: 8/25 | Within 1 grade: 18/25 | Off by 2+: 7/25
Avg grade delta: -1.2 grades

IMPROVEMENT FROM LAST ITERATION:
  +2 postings now within 1 grade (was 16/25)
  Avg delta improved by 0.3 grades

STAGE DIAGNOSIS:
  Stage 1 (Taxonomy):     3 postings still have non-taxonomy skill gaps
  Stage 2 (Req handling): 2 postings have must-haves needing better matching
  Stage 3 (Calibration):  7 postings are close but need weight tuning
  >>> FOCUS: Stage 3 (Calibration)

WORST MISMATCHES:
  Cohere Agent Infra       actual=C   expected=B-  delta=-1  [2 taxonomy gaps]
  Disney Interactive Viz   actual=D   expected=C+  delta=-2  [1 compound req]

CORRECT (15 postings):
  Anthropic Claude Code    actual=A-  expected=A-  delta=0
  NPR AI Engineer          actual=B   expected=B+  delta=-1 (within tolerance)
  Microsoft AI Sr PM       actual=F   expected=F   delta=0
  ...
```

Machine-readable `benchmark_history.jsonl` appended each iteration:

```json
{"iteration": 3, "timestamp": "2026-03-21T02:15:00Z", "exact_match": 8, "within_1": 18, "off_by_2_plus": 7, "avg_delta": -1.2, "stage_focus": "calibration", "fix_applied": "Adjust partial_match score from 0.55 to 0.65", "postings": {"anthropic-claude-code": {"actual": "A-", "expected": "A-", "delta": 0}, "...": "..."}}
```

---

## Phase 3: Ralph Loop

### PROMPT.md

```markdown
# Skill Matching Accuracy Improvement

You are iteratively improving skill matching accuracy in claude-candidate.

## Environment
Always use `.venv/bin/python` for all Python commands. Do not activate the venv or use bare `pytest`.

## Your Task
1. Run the benchmark: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
2. Read the output — it tells you what stage to focus on and which postings are worst
3. Read `tests/golden_set/benchmark_history.jsonl` to see what previous iterations tried
4. Read `git log --oneline -10` to see what was already fixed
5. Fix ONE root cause (smallest effective change)
6. Run the full test suite: `.venv/bin/python -m pytest`
7. If tests pass, commit with a descriptive message
8. Re-run the benchmark to verify improvement — CHECK FOR REGRESSIONS
9. If your fix caused any posting that was previously within tolerance to move outside tolerance, REVERT and try a different approach
10. If ALL 25 postings are within 1 letter grade AND 10 percentage points of expected, output:
    <promise>ACCURACY ACHIEVED</promise>

## Stage Priority (follow the benchmark's stage diagnosis)
1. **Taxonomy gaps** — Add missing skills, aliases, content_patterns to
   `src/claude_candidate/data/taxonomy.json`. When <3 postings still fail
   due to missing taxonomy entries, the benchmark will tell you to move on.
2. **Requirement handling** — Improve matching logic in
   `src/claude_candidate/quick_match.py`. Better synonym resolution,
   related-skill credit, pattern matching. When must-have coverage >=70%
   across all postings, move on.
3. **Scoring calibration** — Tune weights, depth thresholds, status scores
   in `quick_match.py`. Adjust grade curve if needed. When all postings
   are within 1 grade of expected, exit.

## Files You May Edit
- `src/claude_candidate/data/taxonomy.json` (taxonomy entries)
- `src/claude_candidate/quick_match.py` (matching + scoring logic)
- `src/claude_candidate/skill_taxonomy.py` (matching algorithm)
- `tests/test_quick_match.py` (tests for new behavior)
- `tests/test_skill_taxonomy.py` (tests for taxonomy changes)

## Files You Must NOT Edit
- `tests/golden_set/` (ground truth — never change expected grades or postings)
- `src/claude_candidate/schemas/` (no schema changes)
- `src/claude_candidate/cli.py` (no CLI changes)
- `src/claude_candidate/server.py` (no server changes)
- `src/claude_candidate/extractor.py` (no extraction changes)
- `src/claude_candidate/merger.py` (no merger changes)

## Success Criterion
"Within 1 grade" uses this ordinal sequence (distance 1 = adjacent):
`A+ > A > A- > B+ > B > B- > C+ > C > C- > D > F`
A posting passes if: ordinal distance <= 1 AND score delta <= 10 percentage points.

## Rules
- ONE fix per iteration. Small, targeted, verifiable.
- Never break existing tests. If a test fails, fix the code, not the test.
- REGRESSION GUARD: If your fix moves any previously-passing posting outside tolerance, revert and try a different approach.
- Read git log to see what previous iterations already fixed.
- Add tests for new taxonomy entries and matching behavior.
- The benchmark output includes stage diagnosis — follow it, don't skip ahead.
- Prefer taxonomy expansion over matching logic hacks.
```

### Ralph Invocation

```bash
/ralph-loop "improve skill matching accuracy" --max-iterations 20 --completion-promise "ACCURACY ACHIEVED"
```

### Sandboxing

- Feature branch: `feat/accuracy-improvement`
- File allowlist enforced by PROMPT.md instructions
- Test suite as gate: never commit if tests fail
- Max 20 iterations cap
- Baseline commit is the clean pre-ralph state — easy to diff or revert

---

## Grade Curve Reference

Current thresholds in `fit_assessment.py:score_to_grade()`:

| Grade | Score | Job-Fit Meaning |
|---|---|---|
| A+ | ≥95% | Dream match — apply immediately |
| A | ≥90% | Excellent match, minor gaps |
| A- | ≥85% | Very good, apply with confidence |
| B+ | ≥80% | Good match, address gaps in cover letter |
| B | ≥75% | Solid match, worth applying |
| B- | ≥70% | Decent match, notable gaps exist |
| C+ | ≥65% | Stretch role but possible |
| C | ≥60% | Significant gaps, apply if passionate |
| C- | ≥55% | Probably not worth applying |
| D | ≥45% | Major misalignment |
| F | <45% | Wrong role entirely |

These thresholds are reasonable for job-fit assessment. The 5-point bands in A-C range provide good granularity. The wide D (10pt) and F (45pt) bands are intentional — there's not much meaningful distinction between 10% and 40% match.

**Calibration note:** If the pre-fixes shift the score distribution significantly (e.g., everything moves from D to B range), ralph-loop Stage 3 can adjust thresholds. The curve itself is in `fit_assessment.py` which is on the "do not edit" list for ralph — if recalibration is needed, it would be a manual adjustment after the loop completes.

---

## Blog Post Capture

The benchmark script is designed for blog-post-friendly output:
- `benchmark_history.jsonl` records every iteration with timestamp, fix description, and per-posting scores
- Before/after comparison is trivial: first entry vs last entry
- Each atomic commit has a descriptive message explaining what was fixed and why
- The git log tells the story of iterative improvement

---

## Execution Plan Summary

| Step | Who | What | Gate |
|---|---|---|---|
| 1. Pre-fixes (Fix 0-7) | Claude (this session) | Structural bug fixes | All tests pass |
| 2. Golden set export | Claude (this session) | Export 25 postings, build benchmark script | Benchmark runs successfully |
| 3. Clean commit | Claude (this session) | Single commit on feature branch | Tests pass, benchmark produces output |
| 4. Brian reviews | Brian | Assign expected grades, review PROMPT.md | expected_grades.json filled in |
| 5. Ralph loop | Ralph | Iterative accuracy improvement | All 25 within 1 grade of expected |
| 6. Review & merge | Brian | Review ralph's changes, merge to main | Satisfied with grades |
