# Confidence Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix CONFLICTING evidence depth semantics so resume anchors skill depth, then surface per-skill confidence and evidence category in the extension popup matching the preview in `extension/preview/confidence-metrics.html`.

**Architecture:** Two independent parts in sequence — backend correctness fix first (Python, no API changes), then frontend confidence layer (JS/CSS/HTML, reads existing API fields). All confidence data (`evidence_source`, `confidence`, `match_status`, `matched_skill`) is already serialized in `skill_matches[]`; no server deploy needed for the frontend work.

**Tech Stack:** Python 3.13, pydantic v2, pytest — for backend. Vanilla JS, CSS, HTML — for extension popup.

---

## File Map

| File | What changes |
|---|---|
| `src/claude_candidate/schemas/merged_profile.py:83–84` | CONFLICTING branch of `compute_effective_depth` — directional depth logic |
| `src/claude_candidate/schemas/merged_profile.py:122–123` | CONFLICTING branch of `compute_confidence` — raise from 0.40 → 0.72 |
| `src/claude_candidate/quick_match.py:1071–1114` | Remove `CONFIDENCE_FLOOR`, `CONFLICTING_EXPERT_CONF_FLOOR`, and both usages; update `SOURCE_LABEL` |
| `tests/test_quick_match.py` | Replace `TestConflictingExpertConfidence` class + `test_score_requirement_confidence_floor`; add CONFLICTING direction tests |
| `extension/popup.html` | Replace `results-hero` inner content; insert evidence-summary section; add 4th stat cell |
| `extension/popup.js` | Add `categorizeSkill()`; replace hero rendering block; add `renderSignalBars()`, `renderEvidenceSummary()`; update skill-match loop; set Direct Evid. stat |
| `extension/popup.css` | Add signal bars, evidence chips, conf bars, source chips, low-conf highlight; update stats-row to 4 columns |

> ⚠️ **Visual reference:** Before touching any extension files, open `extension/preview/confidence-metrics.html` in a browser (`open extension/preview/confidence-metrics.html`). The right-hand "Proposed" popup is the pixel target. The spec at `docs/superpowers/specs/2026-03-24-confidence-metrics-design.md` has the full color/size reference table — if anything conflicts, the HTML wins.

---

## Task 1: Fix CONFLICTING effective depth — directional logic

**Files:**
- Modify: `src/claude_candidate/schemas/merged_profile.py:58–84`
- Test: `tests/test_quick_match.py`

- [ ] **Step 1: Write failing tests for CONFLICTING depth directions**

Add to `tests/test_quick_match.py` — these must fail before the fix:

```python
class TestConflictingDepthDirection:
	"""CONFLICTING depth: resume anchors, sessions boost by at most one rung."""

	def _make_conflicting(self, resume_depth, session_depth):
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		# effective_depth is set by the merger; we test compute_effective_depth directly
		return MergedSkillEvidence.compute_effective_depth(
			EvidenceSource.CONFLICTING,
			resume_depth=resume_depth,
			session_depth=session_depth,
		)

	def test_sessions_higher_caps_at_one_above_resume(self):
		"""Sessions=EXPERT, resume=MENTIONED → effective=USED (one above MENTIONED)."""
		from claude_candidate.schemas.candidate_profile import DepthLevel
		result = self._make_conflicting(DepthLevel.MENTIONED, DepthLevel.EXPERT)
		assert result == DepthLevel.USED

	def test_sessions_higher_from_applied_caps_at_deep(self):
		"""Sessions=EXPERT, resume=APPLIED → effective=DEEP (one above APPLIED)."""
		from claude_candidate.schemas.candidate_profile import DepthLevel
		result = self._make_conflicting(DepthLevel.APPLIED, DepthLevel.EXPERT)
		assert result == DepthLevel.DEEP

	def test_resume_higher_trusts_resume(self):
		"""Resume=DEEP, sessions=MENTIONED → effective=DEEP (resume wins)."""
		from claude_candidate.schemas.candidate_profile import DepthLevel
		result = self._make_conflicting(DepthLevel.DEEP, DepthLevel.MENTIONED)
		assert result == DepthLevel.DEEP

	def test_one_side_missing_uses_resume_preferred(self):
		"""Only resume present → use resume depth."""
		from claude_candidate.schemas.candidate_profile import DepthLevel
		result = MergedSkillEvidence.compute_effective_depth(
			EvidenceSource.CONFLICTING,
			resume_depth=DepthLevel.APPLIED,
			session_depth=None,
		)
		from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
		assert result == DepthLevel.APPLIED
```

- [ ] **Step 2: Run tests, confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::TestConflictingDepthDirection -v
```
Expected: 4 FAILED (current code returns `session_depth` for CONFLICTING, so direction tests fail)

- [ ] **Step 3: Implement the fix in `compute_effective_depth`**

In `src/claude_candidate/schemas/merged_profile.py`, replace lines 83–84:

```python
	else:  # CONFLICTING
		return session_depth or resume_depth or DepthLevel.MENTIONED
```

With:

```python
	else:  # CONFLICTING — both sources present, depths diverge by 2+ levels.
		# Resume anchors: earned expertise > short-duration agentic sessions.
		# Sessions can boost resume by one rung but cannot leapfrog it.
		if resume_depth is not None and session_depth is not None:
			r_rank = DEPTH_RANK.get(resume_depth, 0)
			s_rank = DEPTH_RANK.get(session_depth, 0)
			if s_rank > r_rank:
				# Sessions claim higher — one conservative rung above resume, capped at DEEP
				depth_by_rank = {v: k for k, v in DEPTH_RANK.items()}
				boosted_rank = min(r_rank + 1, DEPTH_RANK[DepthLevel.DEEP])
				return depth_by_rank.get(boosted_rank, resume_depth)
			else:
				# Resume claims higher — trust resume as earned-expertise anchor
				return resume_depth
		# Only one side present — resume preferred
		return resume_depth or session_depth or DepthLevel.MENTIONED
```

Also update the docstring at line 71 from:
```python
		- conflicting: session depth (observed behavior > self-report)
```
To:
```python
		- conflicting: resume anchors depth; sessions boost by at most one level
```

- [ ] **Step 4: Run tests, confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::TestConflictingDepthDirection -v
```
Expected: 4 PASSED

- [ ] **Step 5: Run full fast suite — no regressions**

```bash
.venv/bin/python -m pytest
```
Expected: all pass (same count as before)

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/schemas/merged_profile.py tests/test_quick_match.py
git commit -m "Fix: CONFLICTING depth anchors to resume, sessions boost by one rung max"
```

---

## Task 2: Fix CONFLICTING confidence — raise 0.40 → 0.72

**Files:**
- Modify: `src/claude_candidate/schemas/merged_profile.py:92–123`
- Test: `tests/test_quick_match.py`

- [ ] **Step 1: Write failing test**

Add to `tests/test_quick_match.py`:

```python
def test_conflicting_confidence_is_072():
	"""CONFLICTING evidence source should return 0.72 confidence, not 0.40.

	Both sources have the skill. Uncertainty is about depth level only,
	which is handled in compute_effective_depth, not here.
	"""
	from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
	conf = MergedSkillEvidence.compute_confidence(
		EvidenceSource.CONFLICTING,
		session_frequency=5,
		resume_context="Listed on resume",
	)
	assert conf == 0.72, f"Expected 0.72, got {conf}"
```

- [ ] **Step 2: Run test, confirm it fails**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::test_conflicting_confidence_is_072 -v
```
Expected: FAILED — current code returns 0.40

- [ ] **Step 3: Implement the fix**

In `src/claude_candidate/schemas/merged_profile.py`, replace lines 100–123 (update docstring + CONFLICTING branch):

Change the docstring band for conflicting:
```python
		- conflicting → 0.72 (both sources present; depth uncertainty handled separately)
```

Change the CONFLICTING return at line 122–123:
```python
	else:  # CONFLICTING
		return 0.4
```
To:
```python
	else:  # CONFLICTING — both sources have the skill; depth reconciled in compute_effective_depth
		return 0.72
```

- [ ] **Step 4: Run test, confirm it passes**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::test_conflicting_confidence_is_072 -v
```
Expected: PASSED

- [ ] **Step 5: Run full fast suite**

```bash
.venv/bin/python -m pytest
```
Expected: all pass except `TestConflictingExpertConfidence` and `test_score_requirement_confidence_floor` — these test the old patch behavior and will be replaced in Task 3.

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/schemas/merged_profile.py tests/test_quick_match.py
git commit -m "Fix: CONFLICTING confidence 0.40 → 0.72 (both sources present, depth uncertainty separated)"
```

---

## Task 3: Remove CONFIDENCE_FLOOR rescue patches

**Files:**
- Modify: `src/claude_candidate/quick_match.py:1071–1115` and `~1743`
- Test: `tests/test_quick_match.py` (delete two old tests, add one new)

- [ ] **Step 1: Delete the two tests that pin the old patched behavior**

In `tests/test_quick_match.py`, delete the entire `TestConflictingExpertConfidence` class (lines ~1810–1844) and the `test_score_requirement_confidence_floor` function (lines ~846–866). These tests assert the old floor behavior which we're removing.

- [ ] **Step 2: Add the replacement test**

```python
def test_score_requirement_uses_raw_confidence_no_floor():
	"""Confidence adjustment uses raw skill confidence with no floor clamping.

	With CONFLICTING fixed to 0.72, the floor constants are unnecessary.
	Both resume_only (0.85) and conflicting (0.72) should score via the
	clean formula: adjustment = 0.90 + 0.10 * confidence.
	"""
	from claude_candidate.quick_match import _score_requirement, STATUS_SCORE
	from claude_candidate.schemas.merged_profile import MergedSkillEvidence, EvidenceSource
	from claude_candidate.schemas.candidate_profile import DepthLevel

	resume_skill = MergedSkillEvidence(
		name="python",
		source=EvidenceSource.RESUME_ONLY,
		resume_depth=DepthLevel.DEEP,
		effective_depth=DepthLevel.DEEP,
		confidence=0.85,
	)
	conflicting_skill = MergedSkillEvidence(
		name="docker",
		source=EvidenceSource.CONFLICTING,
		resume_depth=DepthLevel.APPLIED,
		session_depth=DepthLevel.DEEP,
		effective_depth=DepthLevel.DEEP,
		confidence=0.72,
	)

	resume_score = _score_requirement(resume_skill, "strong_match")
	conflicting_score = _score_requirement(conflicting_skill, "strong_match")

	expected_resume = STATUS_SCORE["strong_match"] * (0.90 + 0.10 * 0.85)
	expected_conflicting = STATUS_SCORE["strong_match"] * (0.90 + 0.10 * 0.72)

	assert abs(resume_score - expected_resume) < 0.001, f"resume_only: expected {expected_resume:.4f}, got {resume_score:.4f}"
	assert abs(conflicting_score - expected_conflicting) < 0.001, f"conflicting: expected {expected_conflicting:.4f}, got {conflicting_score:.4f}"
```

- [ ] **Step 3: Run new test, confirm it fails**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::test_score_requirement_uses_raw_confidence_no_floor -v
```
Expected: FAILED — current code floors confidence at 0.65

- [ ] **Step 4: Remove CONFIDENCE_FLOOR from quick_match.py — two sites**

**Site 1:** Delete lines 1071–1076 (the two constants and their comment block):
```python
# Confidence floor — prevent low-confidence skills from cratering scores.
# CONFLICTING defaults to 0.40; sessions-only with low frequency get 0.45–0.65.
# Floor at 0.65 prevents catastrophic penalties for these cases.
# Resume-only (0.85 flat) and corroborated (0.70–1.0) always exceed the floor.
CONFIDENCE_FLOOR = 0.65
CONFLICTING_EXPERT_CONF_FLOOR = 0.80  # expert session evidence overrides resume "mentioned"
```

**Site 2:** Replace lines 1100–1114 in `_score_requirement`:
```python
	req_score = STATUS_SCORE.get(best_status, STATUS_SCORE_NONE)
	if best_match:
		effective_confidence = max(best_match.confidence, CONFIDENCE_FLOOR)
		# Expert/deep session skills marked CONFLICTING (resume "mentioned" vs sessions
		# EXPERT): use a higher floor — session depth evidence dominates.
		if best_match.source == EvidenceSource.CONFLICTING and best_match.effective_depth in (
			DepthLevel.EXPERT,
			DepthLevel.DEEP,
		):
			effective_confidence = max(effective_confidence, CONFLICTING_EXPERT_CONF_FLOOR)
		# Scale confidence to a ~0.965–1.0 range (with floor at 0.65):
		# corroborated/high-freq skills get near-full score (0.985–1.0),
		# resume-only skills get modest penalty (~3.5% at floor).
		adjustment = 0.90 + 0.10 * effective_confidence
		req_score *= adjustment
	return req_score
```
With:
```python
	req_score = STATUS_SCORE.get(best_status, STATUS_SCORE_NONE)
	if best_match:
		# Scale confidence to ~0.972–1.0 range:
		# corroborated/high-freq → 0.985–1.0, conflicting (0.72) → 0.972, resume-only (0.85) → 0.985
		adjustment = 0.90 + 0.10 * best_match.confidence
		req_score *= adjustment
	return req_score
```

**Site 3:** In the compound-scoring loop (~line 1743), replace:
```python
					conf = max(found.confidence, CONFIDENCE_FLOOR)
```
With:
```python
					conf = found.confidence
```

**Site 4:** Update `SOURCE_LABEL` for CONFLICTING (~line 315):
```python
	EvidenceSource.CONFLICTING: "Evidence conflicts between resume and sessions",
```
With:
```python
	EvidenceSource.CONFLICTING: "Resume depth anchored; sessions provided additional signal",
```

- [ ] **Step 5: Run new test, confirm it passes**

```bash
.venv/bin/python -m pytest tests/test_quick_match.py::test_score_requirement_uses_raw_confidence_no_floor -v
```
Expected: PASSED

- [ ] **Step 6: Run full fast suite**

```bash
.venv/bin/python -m pytest
```
Expected: all pass

- [ ] **Step 7: Run benchmark — record before/after delta**

```bash
.venv/bin/python tests/golden_set/benchmark_accuracy.py
```
Note the accuracy score. It should be equal or better than before. If accuracy drops, investigate which posting regressed and why before proceeding.

- [ ] **Step 8: Commit**

```bash
git add src/claude_candidate/quick_match.py tests/test_quick_match.py
git commit -m "Remove: CONFIDENCE_FLOOR/CONFLICTING_EXPERT_CONF_FLOOR — fixed at source in merged_profile.py"
```

---

## Task 4: Extension HTML — structural slots for confidence layer

**Files:**
- Modify: `extension/popup.html`

> Before editing: open `extension/preview/confidence-metrics.html` in a browser to see the target layout.

- [ ] **Step 1: Replace `results-hero` inner content**

In `extension/popup.html`, find:
```html
		<div class="results-hero" id="results-hero">--</div>
```
Replace with:
```html
		<div class="results-hero" id="results-hero">
			<span id="hero-text">--</span>
			<div class="signal-bars hidden" id="signal-bars">
				<div class="signal-bar" id="sb1"></div>
				<div class="signal-bar" id="sb2"></div>
				<div class="signal-bar" id="sb3"></div>
				<div class="signal-bar" id="sb4"></div>
			</div>
		</div>
```

- [ ] **Step 2: Insert evidence-summary section**

Find in `popup.html`:
```html
		<p class="overall-summary" id="results-summary"></p>
		<p class="deep-analysis-banner hidden" id="banner-deep-analysis">
```
Insert between them:
```html
		<div class="evidence-summary hidden" id="section-evidence-summary">
			<span class="evidence-label">Evidence</span>
			<span class="evidence-chip direct hidden" id="chip-direct">
				<span class="evidence-dot direct-dot"></span>
				<span id="chip-direct-count"></span>
			</span>
			<span class="evidence-chip inferred hidden" id="chip-inferred">
				<span class="evidence-dot inferred-dot"></span>
				<span id="chip-inferred-count"></span>
			</span>
			<span class="evidence-chip fuzzy hidden" id="chip-fuzzy">
				<span class="evidence-dot fuzzy-dot"></span>
				<span id="chip-fuzzy-count"></span>
			</span>
			<span class="evidence-chip missing hidden" id="chip-missing">
				<span class="evidence-dot missing-dot"></span>
				<span id="chip-missing-count"></span>
			</span>
		</div>
```

- [ ] **Step 3: Add 4th stat cell**

Find the stats-row in `popup.html`:
```html
		<div class="stats-row">
			...
			<div class="stat" id="row-gap">
				<span class="stat-value" id="detail-biggest-gap"></span>
				<span class="stat-label">Biggest gap</span>
			</div>
		</div>
```
Add after `#row-gap`, before the closing `</div>`:
```html
			<div class="stat" id="row-direct-evid">
				<span class="stat-value signal" id="detail-direct-evid">--</span>
				<span class="stat-label">Direct Evid.</span>
			</div>
```

- [ ] **Step 4: Verify HTML renders in browser**

Load the extension in Chrome (chrome://extensions → load unpacked → select `extension/`). Open any page, click the extension. It should render without JS errors. The grade circle should show "--" (hero-text working), stats row should show 4 cells.

- [ ] **Step 5: Commit**

```bash
git add extension/popup.html
git commit -m "feat: add confidence layer HTML slots (hero-text, signal-bars, evidence-summary, 4th stat)"
```

---

## Task 5: Extension CSS — confidence layer styles

**Files:**
- Modify: `extension/popup.css`

> Keep the preview HTML open while working. Every hex and pixel value below is from the preview's `<style>` block.

- [ ] **Step 1: Update stats-row to 4 columns + signal cell**

In `extension/popup.css`, find and replace:
```css
.stats-row {
	display: grid; grid-template-columns: 1fr 1fr 1fr;
	gap: 1px; background: #e5e7eb;
	border-bottom: 1px solid #e5e7eb;
}
```
With:
```css
.stats-row {
	display: grid; grid-template-columns: repeat(4, 1fr);
	gap: 1px; background: #e5e7eb;
	border-bottom: 1px solid #e5e7eb;
}
```

Add after `.stat-label { ... }`:
```css
#row-direct-evid { background: #f0fdfa; }
.stat-value.signal { color: #0d9488; }
```

- [ ] **Step 2: Add signal bars styles**

Append to `popup.css`:
```css
/* ── Signal bars — absolute overlay on grade badge ───────────────── */
#results-hero { position: relative; }
.signal-bars {
	position: absolute; bottom: -2px; right: -2px;
	display: flex; align-items: flex-end; gap: 2px;
	background: #fff; border-radius: 4px;
	padding: 2px 3px;
	box-shadow: 0 1px 4px rgba(0,0,0,0.15);
}
.signal-bar { width: 3px; border-radius: 1px; background: #d1d5db; }
.signal-bar.lit { background: #06b6d4; }
.signal-bar:nth-child(1) { height: 4px; }
.signal-bar:nth-child(2) { height: 6px; }
.signal-bar:nth-child(3) { height: 8px; }
.signal-bar:nth-child(4) { height: 10px; }
```

- [ ] **Step 3: Add evidence summary styles**

Append to `popup.css`:
```css
/* ── Evidence summary chips ───────────────────────────────────────── */
.evidence-summary {
	display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
	padding: 6px 16px 10px;
	border-bottom: 1px solid #f3f4f6;
}
.evidence-label {
	font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
	font-size: 10px; font-weight: 500; letter-spacing: 0.04em;
	text-transform: uppercase; color: #9ca3af;
}
.evidence-chip {
	font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
	font-size: 10px; font-weight: 600;
	padding: 2px 7px; border-radius: 4px;
	display: inline-flex; align-items: center; gap: 3px;
	border: 1px solid transparent;
}
.evidence-chip.direct  { background: #ecfdf5; color: #065f46; border-color: #a7f3d0; }
.evidence-chip.inferred { background: #fffbeb; color: #78350f; border-color: #fde68a; }
.evidence-chip.fuzzy   { background: #faf5ff; color: #4c1d95; border-color: #ddd6fe; }
.evidence-chip.missing { background: #fff1f2; color: #881337; border-color: #fecdd3; }
.evidence-dot { width: 5px; height: 5px; border-radius: 50%; flex-shrink: 0; }
.direct-dot   { background: #10b981; }
.inferred-dot { background: #f59e0b; }
.fuzzy-dot    { background: #8b5cf6; }
.missing-dot  { background: #f43f5e; }
```

- [ ] **Step 4: Add per-skill confidence + source chip + low-conf styles**

Append to `popup.css`:
```css
/* ── Per-skill confidence bars ────────────────────────────────────── */
.conf-bar-wrap {
	display: flex; align-items: center; gap: 5px; flex-shrink: 0;
}
.conf-bar {
	width: 44px; height: 4px; background: #e5e7eb;
	border-radius: 2px; overflow: hidden;
}
.conf-bar-fill { height: 100%; border-radius: 2px; }
.conf-bar-fill.high   { background: #10b981; }
.conf-bar-fill.medium { background: #f59e0b; }
.conf-bar-fill.low    { background: #f43f5e; }
.conf-val {
	font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
	font-size: 9px; font-weight: 600; color: #9ca3af;
	width: 26px; text-align: right; flex-shrink: 0;
}

/* ── Source provenance chips ──────────────────────────────────────── */
.source-chip {
	font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
	font-size: 9px; font-weight: 500;
	padding: 1px 5px; border-radius: 3px; white-space: nowrap; flex-shrink: 0;
}
.source-chip.direct   { background: #ecfdf5; color: #065f46; }
.source-chip.inferred { background: #fffbeb; color: #78350f; }
.source-chip.fuzzy    { background: #faf5ff; color: #4c1d95; }
/* missing: inline dash via JS, no chip class needed */

/* ── Low-confidence skill highlight ──────────────────────────────── */
.match-item.low-conf {
	background: linear-gradient(to right, #fffbeb 0%, transparent 100%);
	border-radius: 4px;
	padding-left: 4px; margin-left: -4px;
	border-left: 2px solid #f59e0b;
}
```

- [ ] **Step 5: Reload extension and verify stats row**

Reload the extension in Chrome. The stats row should now show 4 columns. The 4th cell ("Direct Evid.") shows "--" until assessment runs. Visually it should match the 4-column stats layout in the preview's right popup.

- [ ] **Step 6: Commit**

```bash
git add extension/popup.css
git commit -m "feat: add confidence layer CSS (signal bars, evidence chips, conf bars, source chips, low-conf)"
```

---

## Task 6: Extension JS — hero rendering fix + confidence functions

**Files:**
- Modify: `extension/popup.js`

- [ ] **Step 1: Add `categorizeSkill` helper**

At the top of `popup.js`, after the `barColor` function (around line 55), add:

```js
function categorizeSkill(m) {
	if (m.match_status === 'no_evidence') return 'missing';
	const req = (m.requirement || '').toLowerCase().replace(/[^a-z0-9]/g, '');
	const matched = (m.matched_skill || '').toLowerCase().replace(/[^a-z0-9]/g, '');
	if (matched && matched !== req) return 'fuzzy';
	if (m.evidence_source === 'corroborated') return 'direct';
	// resume_only, sessions_only, conflicting → inferred.
	// sessions_only is intentionally "inferred": agentic sessions without
	// resume corroboration are not guaranteed personal mastery.
	return 'inferred';
}
```

- [ ] **Step 2: Add `renderSignalBars` and `renderEvidenceSummary` helpers**

After `categorizeSkill`, add:

```js
function renderSignalBars(matches) {
	const withEvidence = matches.filter(m => m.match_status !== 'no_evidence');
	if (!withEvidence.length) return;
	const directCount = withEvidence.filter(m => categorizeSkill(m) === 'direct').length;
	const ratio = directCount / withEvidence.length;
	const litCount = ratio >= 0.75 ? 4 : ratio >= 0.5 ? 3 : ratio >= 0.25 ? 2 : 1;
	for (let i = 1; i <= 4; i++) {
		el(`sb${i}`).classList.toggle('lit', i <= litCount);
	}
	el('signal-bars').classList.remove('hidden');
}

function renderEvidenceSummary(matches) {
	const counts = { direct: 0, inferred: 0, fuzzy: 0, missing: 0 };
	matches.forEach(m => counts[categorizeSkill(m)]++);
	['direct', 'inferred', 'fuzzy', 'missing'].forEach(cat => {
		const chip = el(`chip-${cat}`);
		if (counts[cat] > 0) {
			el(`chip-${cat}-count`).textContent = `${counts[cat]} ${cat}`;
			chip.classList.remove('hidden');
		} else {
			chip.classList.add('hidden');
		}
	});
	if (matches.length > 0) el('section-evidence-summary').classList.remove('hidden');
}
```

- [ ] **Step 3: Fix hero rendering to use `#hero-text`**

Find the existing hero block in `renderResults` (lines 76–92):
```js
	// Hero display: percentage for partial, letter grade for full
	const heroEl = el('results-hero');
	if (phase === 'full') {
		const grade = data.overall_grade || scoreToGrade(data.overall_score || 0);
		heroEl.textContent = grade;
		heroEl.dataset.grade = grade;
		heroEl.classList.add('hero-grade');
		heroEl.classList.remove('hero-pct');
	} else {
		const partial = data.partial_percentage != null
			? Math.round(data.partial_percentage)
			: Math.round((data.overall_score || 0) * 100);
		heroEl.textContent = partial + '%';
		heroEl.dataset.grade = '';
		heroEl.classList.add('hero-pct');
		heroEl.classList.remove('hero-grade');
	}
```
Replace entirely with:
```js
	// Hero display: target #hero-text child so signal-bars sibling is preserved
	const heroEl = el('results-hero');
	const heroText = el('hero-text');
	if (phase === 'full') {
		const grade = data.overall_grade || scoreToGrade(data.overall_score || 0);
		heroText.textContent = grade;
		heroEl.dataset.grade = grade;
		heroEl.classList.add('hero-grade');
		heroEl.classList.remove('hero-pct');
	} else {
		const partial = data.partial_percentage != null
			? Math.round(data.partial_percentage)
			: Math.round((data.overall_score || 0) * 100);
		heroText.textContent = partial + '%';
		heroEl.dataset.grade = '';
		heroEl.classList.add('hero-pct');
		heroEl.classList.remove('hero-grade');
	}
```

- [ ] **Step 4: Set Direct Evid. stat**

Find in `renderResults` the stats block (around line 179):
```js
	// Stats
	el('detail-must-haves').textContent = data.must_have_coverage || '--';
	el('detail-strongest-match').textContent = data.strongest_match || '--';
	el('detail-biggest-gap').textContent = data.biggest_gap || 'None';
```
Add below it:
```js
	// Direct evidence % stat — computed from skill_matches (available at this point or below)
	// Set after skill_matches are processed; placeholder here will be overwritten.
	el('detail-direct-evid').textContent = '--';
```

- [ ] **Step 5: Update skill-match loop + call confidence renders**

Find the skill-matches section in `renderResults` (around line 206):
```js
	const matches = data.skill_matches || [];
	const matchList = el('skill-match-list');
	matchList.innerHTML = '';
	if (matches.length > 0) {
		el('tag-skills').textContent = matches.length;
		matches.forEach(m => {
			const status = m.match_status || '';
			const iconClass = status.includes('strong') || status === 'exceeds' ? 'hit'
				: status === 'no_evidence' ? 'miss' : 'partial';
			const iconChar = iconClass === 'hit' ? '+' : iconClass === 'miss' ? 'x' : '~';
			const div = document.createElement('div');
			div.className = 'match-item';
			div.innerHTML = `
				<span class="match-icon ${iconClass}">${iconChar}</span>
				<span class="match-name">${m.requirement || ''}</span>
				<span class="match-source">${m.evidence_source || ''}</span>
			`;
			matchList.appendChild(div);
		});
		el('section-skills').classList.remove('hidden');
	}
```
Replace with:
```js
	const matches = data.skill_matches || [];
	const matchList = el('skill-match-list');
	matchList.innerHTML = '';
	if (matches.length > 0) {
		el('tag-skills').textContent = matches.length;
		matches.forEach(m => {
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
			const div = document.createElement('div');
			div.className = 'match-item' + (!isMissing && conf <= 0.70 ? ' low-conf' : '');
			div.innerHTML = `
				<span class="match-icon ${iconClass}">${iconChar}</span>
				<span class="match-name">${m.requirement || ''}</span>
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
		el('section-skills').classList.remove('hidden');

		// Compute and render confidence layer from full matches array
		const withEvidence = matches.filter(m => m.match_status !== 'no_evidence');
		const directCount = withEvidence.filter(m => categorizeSkill(m) === 'direct').length;
		const directPct = withEvidence.length
			? Math.round(directCount / withEvidence.length * 100) + '%'
			: '--';
		el('detail-direct-evid').textContent = directPct;

		renderEvidenceSummary(matches);
		renderSignalBars(matches);
	}
```

- [ ] **Step 6: Reload extension, run against a real job posting**

Load the extension (chrome://extensions → reload). Navigate to a LinkedIn job posting or paste one. Run an assessment. Verify:
- Grade circle shows grade/pct text + signal bars (cyan) bottom-right
- Evidence chips appear below the summary (green direct, amber inferred, etc.)
- 4th stat cell shows "X%" in teal
- Skill match rows show thin confidence bar + numeric value + source chip
- Skills with confidence ≤ 0.70 have amber left border + gradient

Compare side-by-side with `extension/preview/confidence-metrics.html` right popup.

- [ ] **Step 7: Commit**

```bash
git add extension/popup.js
git commit -m "feat: confidence layer JS (categorizeSkill, signal bars, evidence chips, per-skill conf bars)"
```

---

## Task 7: Open PR

- [ ] **Step 1: Run full fast test suite one final time**

```bash
.venv/bin/python -m pytest
```
Expected: all pass

- [ ] **Step 2: Push branch**

```bash
git push -u origin spec/confidence-metrics
```

- [ ] **Step 3: Create PR**

```bash
gh pr create \
  --title "Confidence metrics: fix CONFLICTING depth + surface evidence quality in popup" \
  --body "$(cat <<'EOF'
## Summary
- **Backend:** Fix `CONFLICTING` evidence source — resume now anchors skill depth, sessions boost by one rung max. Raise CONFLICTING confidence from 0.40 → 0.72. Remove `CONFIDENCE_FLOOR` and `CONFLICTING_EXPERT_CONF_FLOOR` rescue patches (root cause fixed).
- **Extension:** Surface per-skill confidence in the popup — signal bars on grade badge, evidence summary chips (direct/inferred/fuzzy/missing), per-skill confidence bars + source chips, amber low-confidence highlight, Direct Evid. % stat cell.

## Visual reference
Open `extension/preview/confidence-metrics.html` — right popup is the pixel target.

## Test plan
- [ ] `.venv/bin/python -m pytest` passes
- [ ] Benchmark accuracy equal or better than before (`tests/golden_set/benchmark_accuracy.py`)
- [ ] Load extension, run assessment on a LinkedIn posting, verify confidence layer renders correctly against preview
EOF
)"
```
