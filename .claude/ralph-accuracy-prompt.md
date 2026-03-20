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
