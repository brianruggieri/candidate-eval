# Pipeline Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix three observed defects from the live walkthrough: misleading assessment timer, false domain-experience claims in deliverables, and cover letter generation timeouts.

**Architecture:** Fix 1 moves `start_time` capture to `cli.py` so the timer covers the full pipeline including Claude requirement parsing. Fix 2 adds a domain-mismatch filter + prompt instruction in `generator.py` to suppress false domain claims. Fix 3 replaces the single `CLAUDE_TIMEOUT_SECONDS` constant with a per-deliverable-type dict in `generator.py`.

**Tech Stack:** Python 3.13, pytest, pydantic v2, click, unittest.mock

**Spec:** `docs/superpowers/specs/2026-03-23-pipeline-polish-design.md`

---

## File Map

| File | Change |
|------|--------|
| `src/claude_candidate/cli.py` | Capture `start_time` before requirement parsing; pass `elapsed` to `engine.assess()` |
| `src/claude_candidate/quick_match.py` | Add optional `elapsed` kwarg to `assess()` and `_run_assessment()`; skip internal timing when provided |
| `src/claude_candidate/generator.py` | Add domain-mismatch constants + helper; update prompt builders; replace timeout constant with typed dict; add `deliverable_type` param to `_call_claude` |
| `tests/test_generator.py` | Add tests: domain mismatch detection, prompt sanitisation, per-type timeout lookup, fallback timeout |
| `tests/test_quick_match.py` | Add test: elapsed kwarg threads through and suppresses internal timing |

---

## Task 1: Fix Assessment Timer

**Files:**
- Modify: `src/claude_candidate/cli.py:84-110`
- Modify: `src/claude_candidate/quick_match.py:1368-1453`
- Test: `tests/test_quick_match.py`

### Step 1.1 — Write the failing test

- [ ] Add to `tests/test_quick_match.py`:

```python
from unittest.mock import patch
import time

def test_assess_accepts_elapsed_kwarg(minimal_engine):
    """When elapsed is passed to assess(), it is used instead of internal timing."""
    reqs = [QuickRequirement(requirement="Python", priority="must_have", requirement_type="skill")]
    with patch("claude_candidate.quick_match.time") as mock_time:
        # Internal time.time() should never be called when elapsed is provided
        mock_time.time.side_effect = AssertionError("internal timer was called")
        assessment = minimal_engine.assess(
            requirements=reqs,
            company="Test Co",
            title="Engineer",
            elapsed=5.0,
        )
    assert assessment.time_to_assess_seconds == pytest.approx(5.0, abs=0.01)
```

- [ ] Run test to verify it fails:

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::test_assess_accepts_elapsed_kwarg -v
```

Expected: FAIL — `assess()` does not accept `elapsed` kwarg.

### Step 1.2 — Update `quick_match.py`

- [ ] In `assess()` (line 1368), add the `elapsed` kwarg and pass it through:

```python
def assess(
    self,
    requirements: list[QuickRequirement],
    company: str,
    title: str,
    posting_url: str | None = None,
    source: str = "paste",
    seniority: str = "unknown",
    culture_signals: list[str] | None = None,
    tech_stack: list[str] | None = None,
    company_profile: CompanyProfile | None = None,
    elapsed: float | None = None,
) -> FitAssessment:
    """Run the three-dimensional fit assessment."""
    inp = AssessmentInput(
        requirements=requirements,
        company=company,
        title=title,
        posting_url=posting_url,
        source=source,
        seniority=seniority,
        culture_signals=culture_signals,
        tech_stack=tech_stack,
        company_profile=company_profile,
    )
    return self._run_assessment(inp, elapsed=elapsed)
```

- [ ] In `_run_assessment()` (line 1396), add `elapsed` kwarg and skip internal timing when provided:

```python
def _run_assessment(self, inp: AssessmentInput, elapsed: float | None = None) -> FitAssessment:
    """Orchestrate scoring dimensions and assemble the result."""
    if elapsed is None:
        start_time = time.time()

    # ... existing scoring logic (lines 1404-1441 unchanged) ...

    if elapsed is None:
        elapsed = time.time() - start_time
    return self._build_assessment(
        inp, skill_dim, None, None,
        skill_details, overall_score, elapsed,
        experience_dim=experience_dim,
        education_dim=education_dim,
        partial_percentage=partial_percentage,
        eligibility_gates=eligibility_gates,
        eligibility_passed=eligibility_passed,
        scorable_reqs=scorable_reqs,
    )
```

Note: `_build_assessment` already accepts `elapsed: float` — no change to its signature.

- [ ] Run test again:

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::test_assess_accepts_elapsed_kwarg -v
```

Expected: PASS

### Step 1.3 — Update `cli.py`

- [ ] In the `assess` command (around line 84), capture `start_time` before the sidecar check and compute `elapsed` immediately before `engine.assess()`:

```python
    click.echo(f"Loading job posting from {job}...")
    job_text = Path(job).read_text()

    start_time = time.time()   # <-- ADD THIS (covers both parse paths)

    # Parse requirements from the job text
    req_path = Path(job).with_suffix(".requirements.json")
    if req_path.exists():
        click.echo(f"Loading requirements from {req_path}...")
        req_data = json.loads(req_path.read_text())
        requirements = [QuickRequirement(**r) for r in req_data]
    else:
        click.echo("Parsing requirements with Claude...")
        from claude_candidate.requirement_parser import parse_requirements_with_claude
        requirements = parse_requirements_with_claude(job_text)
        click.echo(f"  Extracted {len(requirements)} requirements")

    elapsed = time.time() - start_time   # <-- ADD THIS

    # Run assessment
    click.echo(f"\nAssessing fit for {title} at {company}...")
    engine = QuickMatchEngine(merged)
    assessment = engine.assess(
        requirements=requirements,
        company=company,
        title=title,
        posting_url=None,
        source="cli",
        seniority=seniority,
        elapsed=elapsed,           # <-- ADD THIS
    )
```

- [ ] Verify `time` is already imported in `cli.py`:

```bash
.venv/bin/python -m pytest tests/ -k "assess" --tb=short -q
```

Expected: all assess-related tests pass (no regressions).

### Step 1.4 — Run full test suite

- [ ] Run:

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all existing tests pass.

### Step 1.5 — Commit

```bash
git add src/claude_candidate/cli.py src/claude_candidate/quick_match.py tests/test_quick_match.py
git commit -m "Fix: assessment timer now covers full pipeline including requirement parsing"
```

---

## Task 2: False Domain-Experience Claims in Deliverables

**Files:**
- Modify: `src/claude_candidate/generator.py`
- Test: `tests/test_generator.py`

### Step 2.1 — Write failing tests

- [ ] Add to `tests/test_generator.py`:

```python
from claude_candidate.generator import _is_domain_mismatch
from claude_candidate.schemas.fit_assessment import SkillMatchDetail
from claude_candidate.schemas.merged_profile import EvidenceSource


def _make_match(requirement: str, matched_skill: str | None) -> SkillMatchDetail:
    return SkillMatchDetail(
        requirement=requirement,
        priority="must_have",
        match_status="strong_match",
        candidate_evidence="security practices: 138 sessions, expert depth",
        evidence_source=EvidenceSource.SESSIONS_ONLY,
        confidence=0.85,
        matched_skill=matched_skill,
    )


class TestDomainMismatch:
    def test_domain_mismatch_detected(self):
        """security matched to healthcare requirement is a mismatch."""
        match = _make_match(
            "Background in highly regulated industries — healthcare or financial services",
            "security",
        )
        assert _is_domain_mismatch(match) is True

    def test_no_mismatch_on_domain_skill(self):
        """A non-general skill matching a domain req is not flagged."""
        match = _make_match(
            "Experience in healthcare software",
            "healthcare-compliance",
        )
        assert _is_domain_mismatch(match) is False

    def test_no_mismatch_on_generic_req(self):
        """security matched to a plain security requirement is fine."""
        match = _make_match(
            "Strong security practices and auth experience",
            "security",
        )
        assert _is_domain_mismatch(match) is False

    def test_no_mismatch_when_matched_skill_is_none(self):
        """No matched_skill → no false positive."""
        match = _make_match(
            "Background in regulated industries",
            None,
        )
        assert _is_domain_mismatch(match) is False


class TestBulletPromptDomainFilter:
    def test_domain_framing_stripped_from_mismatch(self):
        """When domain mismatch: prompt uses evidence text, not requirement text."""
        mismatch_match = _make_match(
            "Background in highly regulated industries — healthcare or financial services",
            "security",
        )
        clean_match = _make_match(
            "Strong Python proficiency",
            "python",
        )
        assessment = _make_assessment(skill_matches=[mismatch_match, clean_match])

        with patch("claude_candidate.generator.call_claude", return_value="- Bullet") as mock_call:
            generate_resume_bullets(assessment=assessment)
            prompt = mock_call.call_args[0][0]

        # The domain framing should NOT appear in the prompt
        assert "healthcare" not in prompt.lower()
        assert "financial services" not in prompt.lower()
        # Evidence text SHOULD appear
        assert "138 sessions" in prompt

    def test_clean_match_not_stripped(self):
        """Non-mismatch requirements are passed through unchanged."""
        clean_match = _make_match("Strong Python proficiency", "python")
        assessment = _make_assessment(skill_matches=[clean_match])

        with patch("claude_candidate.generator.call_claude", return_value="- Bullet") as mock_call:
            generate_resume_bullets(assessment=assessment)
            prompt = mock_call.call_args[0][0]

        assert "Strong Python proficiency" in prompt
```

- [ ] Run tests to verify they fail:

```bash
.venv/bin/python -m pytest tests/test_generator.py::TestDomainMismatch tests/test_generator.py::TestBulletPromptDomainFilter -v
```

Expected: ImportError (`_is_domain_mismatch` not defined yet) or AttributeError.

### Step 2.2 — Add constants and helper to `generator.py`

- [ ] After the existing constants block (after line 44, before `_call_claude`), add:

```python
# ---------------------------------------------------------------------------
# Domain-mismatch detection
# ---------------------------------------------------------------------------

DOMAIN_KEYWORDS: frozenset[str] = frozenset({
    "healthcare",
    "financial",
    "fintech",
    "regulated",
    "hipaa",
    "compliance",
    "legal",
    "insurance",
    "pharma",
})

GENERAL_SKILLS_PRONE_TO_DOMAIN_MISMATCH: frozenset[str] = frozenset({
    "security",
    "testing",
    "authentication",
    "compliance",
    "documentation",
})


def _is_domain_mismatch(match: SkillMatchDetail) -> bool:
    """Return True when a general skill has matched a domain-specific requirement.

    False positives (claiming domain experience the evidence doesn't support) occur
    when a general-purpose skill like 'security' matches a requirement that names a
    specific regulated domain (healthcare, financial services, etc.).
    """
    if match.matched_skill is None:
        return False
    if match.matched_skill not in GENERAL_SKILLS_PRONE_TO_DOMAIN_MISMATCH:
        return False
    req_lower = match.requirement.lower()
    return any(kw in req_lower for kw in DOMAIN_KEYWORDS)
```

- [ ] Run mismatch detection tests only:

```bash
.venv/bin/python -m pytest tests/test_generator.py::TestDomainMismatch -v
```

Expected: all 4 PASS.

### Step 2.3 — Update `_format_matches_for_prompt` to strip domain framing

- [ ] Replace `_format_matches_for_prompt` (lines 107-114) with a version that accepts an optional filter:

```python
def _format_matches_for_prompt(
    matches: list[SkillMatchDetail],
    *,
    strip_domain_mismatch: bool = False,
) -> str:
    """Format skill matches into a readable string for prompts."""
    lines = []
    for m in matches:
        if strip_domain_mismatch and _is_domain_mismatch(m):
            # Replace requirement text with evidence-only framing to prevent
            # the model from echoing domain claims the evidence doesn't support.
            req_text = m.candidate_evidence
        else:
            req_text = m.requirement
        lines.append(f"- {req_text} ({m.match_status}): {m.candidate_evidence}")
    return "\n".join(lines)
```

### Step 2.4 — Update prompt builders to add instruction and use filter

- [ ] Update `_build_bullet_prompt` to add the domain instruction and pass `strip_domain_mismatch=True`:

```python
def _build_bullet_prompt(
    assessment: FitAssessment,
    profile: MergedEvidenceProfile | None,
) -> str:
    """Build a prompt for Claude to generate resume bullets."""
    matches_text = _format_matches_for_prompt(
        assessment.skill_matches, strip_domain_mismatch=True
    )
    return (
        f"Generate tailored resume bullet points for a {assessment.job_title} "
        f"role at {assessment.company_name}.\n\n"
        f"Skill matches:\n{matches_text}\n\n"
        "Format: action verb + specific achievement + technology context. "
        "Return only the bullet points, one per line, prefixed with a dash.\n\n"
        "Important: Do not claim specific domain experience (healthcare, financial "
        "services, regulated industries, or other named verticals) unless the "
        "candidate_evidence text explicitly references that domain. If the matched "
        "skill is a general-purpose skill, describe what the evidence demonstrates "
        "— not what the requirement mentions."
    )
```

- [ ] Update `_build_cover_letter_prompt` similarly:

```python
def _build_cover_letter_prompt(
    assessment: FitAssessment,
    profile: MergedEvidenceProfile | None,
) -> str:
    """Build a prompt for Claude to generate a cover letter."""
    matches_text = _format_matches_for_prompt(
        assessment.skill_matches, strip_domain_mismatch=True
    )
    return (
        f"Write a professional cover letter for a {assessment.job_title} "
        f"position at {assessment.company_name}.\n\n"
        f"Candidate fit: {assessment.overall_summary}\n"
        f"Skill matches:\n{matches_text}\n\n"
        "Tone: professional but authentic. Length: 300-500 words. "
        "Reference specific skills and evidence. Do not use placeholders.\n\n"
        "Important: Do not claim specific domain experience (healthcare, financial "
        "services, regulated industries, or other named verticals) unless the "
        "candidate_evidence text explicitly references that domain. If the matched "
        "skill is a general-purpose skill, describe what the evidence demonstrates "
        "— not what the requirement mentions."
    )
```

- [ ] Run all generator tests:

```bash
.venv/bin/python -m pytest tests/test_generator.py -v
```

Expected: all PASS including new `TestDomainMismatch` and `TestBulletPromptDomainFilter`.

### Step 2.5 — Update `__all__` export in `generator.py`

- [ ] Add `_is_domain_mismatch` to `__all__` if tests import it, OR keep private and import via direct module reference in tests. Tests above use `from claude_candidate.generator import _is_domain_mismatch` — that works without `__all__` since it's a direct import. No change needed.

### Step 2.6 — Run full test suite

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all existing tests pass, new tests added.

### Step 2.7 — Commit

```bash
git add src/claude_candidate/generator.py tests/test_generator.py
git commit -m "Fix: strip domain framing from deliverable prompts when skill is a false match"
```

---

## Task 3: Per-Deliverable-Type Timeouts

**Files:**
- Modify: `src/claude_candidate/generator.py`
- Test: `tests/test_generator.py`

### Step 3.1 — Write failing tests

- [ ] Add to `tests/test_generator.py`:

```python
from claude_candidate.generator import (
    CLAUDE_TIMEOUTS,
    DEFAULT_CLAUDE_TIMEOUT,
)
from claude_candidate.claude_cli import call_claude as real_call_claude


class TestPerTypeTimeouts:
    def test_resume_bullets_timeout(self):
        """resume-bullets uses the configured short timeout."""
        assert CLAUDE_TIMEOUTS["resume-bullets"] == 120

    def test_cover_letter_timeout(self):
        """cover-letter uses the configured long timeout."""
        assert CLAUDE_TIMEOUTS["cover-letter"] == 300

    def test_interview_prep_timeout(self):
        """interview-prep uses the configured long timeout."""
        assert CLAUDE_TIMEOUTS["interview-prep"] == 300

    def test_default_timeout_for_unknown_type(self):
        """Unknown deliverable type falls back to DEFAULT_CLAUDE_TIMEOUT."""
        assert DEFAULT_CLAUDE_TIMEOUT == 180

    def test_generate_resume_bullets_passes_correct_timeout(self, minimal_assessment):
        """generate_resume_bullets calls call_claude with resume-bullets timeout."""
        with patch("claude_candidate.generator.call_claude", return_value="- Bullet") as mock_call:
            generate_resume_bullets(assessment=minimal_assessment)
            _, kwargs = mock_call.call_args
            assert kwargs.get("timeout") == CLAUDE_TIMEOUTS["resume-bullets"]

    def test_generate_cover_letter_passes_correct_timeout(self, minimal_assessment):
        """generate_cover_letter calls call_claude with cover-letter timeout."""
        with patch("claude_candidate.generator.call_claude", return_value="Dear Hiring Manager") as mock_call:
            generate_cover_letter(assessment=minimal_assessment)
            _, kwargs = mock_call.call_args
            assert kwargs.get("timeout") == CLAUDE_TIMEOUTS["cover-letter"]

    def test_generate_interview_prep_passes_correct_timeout(self, minimal_assessment):
        """generate_interview_prep calls call_claude with interview-prep timeout."""
        with patch("claude_candidate.generator.call_claude", return_value="## Technical Topics") as mock_call:
            generate_interview_prep(assessment=minimal_assessment)
            _, kwargs = mock_call.call_args
            assert kwargs.get("timeout") == CLAUDE_TIMEOUTS["interview-prep"]

    def test_site_narrative_empty_type_resolves_to_default_timeout(self):
        """Empty deliverable_type (generate_site_narrative's path) uses DEFAULT_CLAUDE_TIMEOUT.

        generate_site_narrative calls _call_claude(prompt) with no type string, which
        defaults to "" — verify that resolves to DEFAULT_CLAUDE_TIMEOUT via CLAUDE_TIMEOUTS.get.
        """
        assert CLAUDE_TIMEOUTS.get("", DEFAULT_CLAUDE_TIMEOUT) == DEFAULT_CLAUDE_TIMEOUT
```

Note: `minimal_assessment` and `minimal_profile` fixtures need to exist in the test file or conftest. The test file already has `_make_assessment()` — add a pytest fixture that wraps it:

```python
@pytest.fixture
def minimal_assessment():
    return _make_assessment()
```

- [ ] Run tests to verify they fail:

```bash
.venv/bin/python -m pytest tests/test_generator.py::TestPerTypeTimeouts -v
```

Expected: ImportError (`CLAUDE_TIMEOUTS`, `DEFAULT_CLAUDE_TIMEOUT` not exported) or AssertionError.

### Step 3.2 — Replace `CLAUDE_TIMEOUT_SECONDS` in `generator.py`

- [ ] Replace line 25 (`CLAUDE_TIMEOUT_SECONDS = 120`) with:

```python
CLAUDE_TIMEOUTS: dict[str, int] = {
    "resume-bullets": 120,   # short list, fast
    "cover-letter": 300,     # prose narrative, ~400 words
    "interview-prep": 300,   # longer narrative
}
DEFAULT_CLAUDE_TIMEOUT = 180  # fallback for unknown / untyped callers
```

- [ ] Update `_call_claude` signature and body (line 51):

```python
def _call_claude(prompt: str, deliverable_type: str = "") -> str:
    """Call Claude CLI with per-type timeout. Raises ClaudeCLIError on any failure."""
    timeout = CLAUDE_TIMEOUTS.get(deliverable_type, DEFAULT_CLAUDE_TIMEOUT)
    return call_claude(prompt, timeout=timeout)
```

- [ ] Update callers to pass `deliverable_type`:

In `generate_resume_bullets` (line 133):
```python
result = _call_claude(prompt, "resume-bullets")
```

In `generate_cover_letter` (line 158):
```python
return scrub_deliverable(_call_claude(prompt, "cover-letter"))
```

In `generate_interview_prep` (line 172):
```python
return scrub_deliverable(_call_claude(prompt, "interview-prep"))
```

`generate_site_narrative` (line 302) already calls `_call_claude(prompt)` with no type — the empty string default resolves to `DEFAULT_CLAUDE_TIMEOUT`. **No change needed.**

### Step 3.3 — Run timeout tests

```bash
.venv/bin/python -m pytest tests/test_generator.py::TestPerTypeTimeouts -v
```

Expected: all PASS.

### Step 3.4 — Run full test suite

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all tests pass.

### Step 3.5 — Commit

```bash
git add src/claude_candidate/generator.py tests/test_generator.py
git commit -m "Fix: per-deliverable-type timeouts (cover-letter: 300s, default: 180s)"
```

---

## Final Verification

- [ ] Run full test suite one last time:

```bash
.venv/bin/python -m pytest --tb=short -q
```

Expected: all tests pass, no regressions.

- [ ] Smoke-check timer on a sidecar posting (fast path should read ~0.1s):

```bash
.venv/bin/python -m claude_candidate.cli assess \
  --profile ~/.claude-candidate/candidate_profile.json \
  --resume ~/.claude-candidate/curated_resume.json \
  --job /tmp/anthropic-posting.txt \
  --company "Anthropic" \
  --title "Software Engineer, Claude Code" \
  --seniority mid
```

Expected: `⏱ Assessed in ~0.1s` (sidecar loaded, no Claude re-parse).
