# Pipeline Polish Design

**Date:** 2026-03-23
**Status:** Approved

## Summary

Three targeted fixes surfaced during a live walkthrough session. No new features, no scope expansion — each fix addresses a specific observed defect.

## Goals

- Timer accurately reflects full assessment wall-clock time
- Deliverable generator does not produce false domain-experience claims
- Cover letter generation completes reliably within a typed, documented timeout

## Non-Goals

- Depth calibration (separate brainstorm)
- Migrating `generate-deliverable` to Anthropic SDK
- Changing scoring logic or benchmark grades
- Adding retry logic to the Claude CLI wrapper

---

## Fix 1: Assessment Timer

**Problem:** `time_to_assess_seconds` is set inside `quick_match.py::_run_assessment()` (via `start_time = time.time()` at line ~1402, `elapsed = time.time() - start_time` at line ~1443), which runs *after* `parse_requirements_with_claude` has already returned in `cli.py`. The label "Assessed in X.Xs" is misleading — it measures only the scoring step, not the full pipeline including requirement parsing.

**Fix:** Move `start_time = time.time()` into `cli.py`, captured just before requirement parsing begins (before the `parse_requirements_with_claude` call or sidecar load). Pass the resulting `elapsed: float` into `engine.assess()` as an optional kwarg. Thread it through `assess()` → `_run_assessment()` → `_build_assessment()`, suppressing the internal `start_time` capture when `elapsed` is provided. The label stays "Assessed in X.Xs."

**Touch points in `quick_match.py`:**
1. `assess(...)` — add `elapsed: float | None = None` kwarg, pass to `_run_assessment`
2. `_run_assessment(...)` — add `elapsed: float | None = None` kwarg; if provided, skip internal `start_time` and compute nothing — pass `elapsed` directly to `_build_assessment`
3. `_build_assessment(...)` — already accepts `elapsed: float`; no signature change needed

**Files:**
- Modify: `src/claude_candidate/cli.py` — capture `start_time = time.time()` before parsing, compute `elapsed = time.time() - start_time` after `engine.assess()` returns, pass as `elapsed=elapsed`
- Modify: `src/claude_candidate/quick_match.py` — thread optional `elapsed` through `assess()` and `_run_assessment()` as described above

**Behaviour change:**
- Fresh posting (Claude parses): "Assessed in ~8s" instead of "Assessed in 0.1s"
- Cached sidecar: "Assessed in ~0.1s" — accurate, fast path is fast
- Direct API callers (`engine.assess()` from benchmark script and server): unaffected — `elapsed` is an optional kwarg defaulting to `None`, falling back to internal timing

---

## Fix 2: False Domain-Experience Claims in Deliverables

**Problem:** The deliverable generator builds resume bullets using the *requirement text* as the framing, not the actual evidence. When a general-purpose skill (e.g. `security`) matches a domain-specific requirement (e.g. "Background in highly regulated industries — healthcare or financial services"), the generated bullet claims domain experience the evidence does not support.

**Fix:** Two-layer approach:

### Layer 1 — Prompt instruction

Add an explicit instruction to `_build_bullet_prompt` and `_build_cover_letter_prompt`:

> "Do not claim specific domain experience (healthcare, financial services, regulated industries, or other named verticals) unless the candidate_evidence text explicitly references that domain. If the matched skill is a general-purpose skill (security, testing, etc.), describe what the evidence demonstrates — not what the requirement mentions."

### Layer 2 — Generator filter

Before building the prompt, scan each `SkillMatchDetail` for domain-specificity mismatch:
- **Domain-specific requirement**: requirement text contains any of: `healthcare`, `financial`, `fintech`, `regulated`, `HIPAA`, `compliance`, `legal`, `insurance`, `pharma`
- **General-purpose matched skill**: `matched_skill` is one of a defined set of general skills that commonly false-match domain requirements: `security`, `testing`, `authentication`, `compliance`, `documentation`
- **Action**: for flagged matches, substitute the requirement text in the prompt with only the evidence text (e.g. "security practices: 138 sessions, expert depth"), stripping the domain framing

**Files:**
- Modify: `src/claude_candidate/generator.py`
  - Add `DOMAIN_KEYWORDS: frozenset[str]` constant
  - Add `GENERAL_SKILLS_PRONE_TO_DOMAIN_MISMATCH: frozenset[str]` constant
  - Add `_is_domain_mismatch(match: SkillMatchDetail) -> bool` helper
  - Update `_build_bullet_prompt` — add instruction, apply filter
  - Update `_build_cover_letter_prompt` — same

**Tests:**
- `tests/test_generator.py` — add cases for domain mismatch detection and prompt sanitisation

---

## Fix 3: Per-Deliverable-Type Timeouts

**Problem:** `CLAUDE_TIMEOUT_SECONDS = 120` is a single global constant applied to all deliverable types. Cover letter generation (~400 words of prose) consistently times out at 120s. Resume bullets (short list) succeed. The single constant is undocumented and not tunable by type.

**Fix:** Replace with a typed dict:

```python
CLAUDE_TIMEOUTS: dict[str, int] = {
    "resume-bullets": 120,   # short list, fast
    "cover-letter": 300,     # prose narrative, ~400 words
    "interview-prep": 300,   # longer narrative
}
DEFAULT_CLAUDE_TIMEOUT = 180  # fallback for unknown types
```

`_call_claude` accepts a `deliverable_type: str` parameter and looks up the timeout. Callers pass their type string explicitly. `call_claude` in `claude_cli.py` already accepts a `timeout` kwarg — no changes needed there.

**Files:**
- Modify: `src/claude_candidate/generator.py`
  - Replace `CLAUDE_TIMEOUT_SECONDS` with `CLAUDE_TIMEOUTS` dict + `DEFAULT_CLAUDE_TIMEOUT`
  - Update `_call_claude(prompt, deliverable_type)` signature
  - Update `_call_claude` signature to `_call_claude(prompt: str, deliverable_type: str = "") -> str`; make `deliverable_type` optional with empty-string default
  - Update the three user-facing callers to pass their type string: `generate_resume_bullets` → `"resume-bullets"`, `generate_cover_letter` → `"cover-letter"`, `generate_interview_prep` → `"interview-prep"`
  - `generate_site_narrative` calls `_call_claude(prompt)` without a type — it relies on the default `""` which resolves to `DEFAULT_CLAUDE_TIMEOUT`. No change needed to the call site.

**Tests:**
- `tests/test_generator.py` — verify correct timeout is looked up per type; verify fallback for unknown type

---

## Test Strategy

All three fixes have clear unit-testable behaviour:
1. **Timer**: mock `time.time()` in `cli.py` tests; assert elapsed is passed through
2. **Domain filter**: unit test `_is_domain_mismatch` with known-bad and known-good matches; test prompt output doesn't contain flagged domain text
3. **Timeouts**: parametrised test over all deliverable types (`resume-bullets`, `cover-letter`, `interview-prep`) asserting correct timeout value; test unknown type (including `generate_site_narrative`'s path) falls back to `DEFAULT_CLAUDE_TIMEOUT`

No golden set benchmark changes expected — scoring engine is untouched.
