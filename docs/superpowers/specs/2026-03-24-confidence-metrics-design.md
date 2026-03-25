# Confidence Metrics — Extension UI Design Spec

> **For agentic workers:** After reading this spec, invoke `superpowers:writing-plans` to produce the implementation plan.

**Goal:** Surface per-skill evidence quality and signal confidence in the extension popup, so the user can see at a glance which parts of their score are backed by direct session evidence vs. inferred or fuzzy matches. Simultaneously fix a design flaw in the CONFLICTING evidence source that causes depth to be set incorrectly and confidence to be artificially low.

**Reference visual:** `extension/preview/confidence-metrics.html` — the right-hand "Proposed" popup is the **exact pixel target**. All color values, sizes, and layout decisions in this spec are derived verbatim from that file.

> ⚠️ **Before implementing Part 2:** Open `extension/preview/confidence-metrics.html` in a browser (double-click, or `open extension/preview/confidence-metrics.html` from the repo root). The right-hand popup is the implementation target. Match it exactly — every color, spacing, font, bar size, and chip shape. Do not approximate. If the spec and the HTML ever conflict, **the HTML wins.**

The preview file is self-contained and canonical. The style reference section below reproduces the exact CSS tokens from it; the preview is the authority if anything here diverges.

---

## Style Reference (from `extension/preview/confidence-metrics.html`)

These values are extracted verbatim from the preview. Copy them exactly.

### Colors

| Token | Hex | Used for |
|---|---|---|
| Lit signal bar | `#06b6d4` | Signal bars — active bars |
| Unlit signal bar | `#d1d5db` | Signal bars — inactive bars |
| direct bg | `#ecfdf5` | Evidence chip, source chip |
| direct text | `#065f46` | Evidence chip, source chip |
| direct border | `#a7f3d0` | Evidence chip border |
| direct dot | `#10b981` | Evidence dot |
| inferred bg | `#fffbeb` | Evidence chip, source chip, low-conf gradient |
| inferred text | `#78350f` | Evidence chip, source chip |
| inferred border | `#fde68a` | Evidence chip border, low-conf left border |
| inferred dot | `#f59e0b` | Evidence dot |
| fuzzy bg | `#faf5ff` | Evidence chip, source chip |
| fuzzy text | `#4c1d95` | Evidence chip, source chip |
| fuzzy border | `#ddd6fe` | Evidence chip border |
| fuzzy dot | `#8b5cf6` | Evidence dot |
| missing bg | `#fff1f2` | Evidence chip |
| missing text | `#881337` | Evidence chip |
| missing border | `#fecdd3` | Evidence chip border |
| missing dot | `#f43f5e` | Evidence dot |
| conf-bar high | `#10b981` | Confidence fill ≥ 0.75 |
| conf-bar medium | `#f59e0b` | Confidence fill 0.50–0.74 |
| conf-bar low | `#f43f5e` | Confidence fill < 0.50 |
| signal stat bg | `#f0fdfa` | Direct Evid. stat cell background |
| signal stat text | `#0d9488` | Direct Evid. stat value |
| missing dash | `#d1d5db` | Conf val and source dash for no-evidence skills |

### Sizing

| Element | Spec |
|---|---|
| Signal bars container | `background: #fff; border-radius: 4px; padding: 2px 3px; box-shadow: 0 1px 4px rgba(0,0,0,0.15)` |
| Signal bar widths | `3px` each, gap `2px` |
| Signal bar heights | `4px / 6px / 8px / 10px` (bars 1–4) |
| Confidence bar | `width: 44px; height: 4px; border-radius: 2px` |
| Confidence value | `font-size: 9px; width: 26px; text-align: right` |
| Source chip | `font-size: 9px; padding: 1px 5px; border-radius: 3px` |
| Evidence chip | `font-size: 10px; padding: 2px 7px; border-radius: 4px` |
| Evidence dot | `width: 5px; height: 5px; border-radius: 50%` |
| Low-conf border | `border-left: 2px solid #f59e0b` |
| Low-conf gradient | `background: linear-gradient(to right, #fffbeb 0%, transparent 100%)` |

### Fonts

The preview uses Google Fonts (`JetBrains Mono`). The extension popup cannot load external fonts. Use the following fallback stack everywhere the preview uses a monospace font:

```css
font-family: 'SF Mono', 'Fira Code', 'Consolas', monospace;
```

This applies to: `.evidence-label`, `.evidence-chip`, `.conf-val`, `.source-chip`.

---

## Scope

Six UI additions to the extension popup + one backend correctness fix (prerequisite).

**Not in scope:** Counterfactual grade ("B w/o inferred"), server-side `display_category` field, any changes to the CLI, export formats, or assessments.db schema.

---

## Part 1 — Backend: Fix CONFLICTING Depth Semantics

### Problem

`EvidenceSource.CONFLICTING` fires when a skill exists in both resume and sessions but depths diverge by ≥ 2 levels. The current behavior:

1. `compute_effective_depth` always uses `session_depth` for CONFLICTING — sessions override resume depth
2. `compute_confidence` returns `0.40` for CONFLICTING — the lowest of all four sources, lower than `resume_only` (0.85)
3. `quick_match.py` patches this with `CONFIDENCE_FLOOR = 0.65` and `CONFLICTING_EXPERT_CONF_FLOOR = 0.80`

The root cause: sessions are short-duration, high-velocity, and agentic. A few months of Claude-assisted coding ≠ years of personally-written, production-debugged experience. The resume is the anchor for earned expertise; sessions confirm activity and can provide a modest upward boost, but should not override.

### Fix 1 — `merged_profile.py`: `compute_effective_depth`

Split the CONFLICTING branch by direction:

```python
else:  # CONFLICTING — both sources present, depths diverge by 2+ levels
    if resume_depth is not None and session_depth is not None:
        r_rank = DEPTH_RANK.get(resume_depth, 0)
        s_rank = DEPTH_RANK.get(session_depth, 0)
        if s_rank > r_rank:
            # Sessions claim higher than resume — conservative boost: one level above resume,
            # capped at DEEP. Agentic sessions overstate personal mastery.
            depth_by_rank = {v: k for k, v in DEPTH_RANK.items()}
            boosted_rank = min(r_rank + 1, DEPTH_RANK[DepthLevel.DEEP])
            return depth_by_rank.get(boosted_rank, resume_depth)
        else:
            # Resume claims higher — trust resume as earned-expertise anchor.
            return resume_depth
    # Only one side present — use whichever exists, resume preferred
    return resume_depth or session_depth or DepthLevel.MENTIONED
```

Semantic: "resume is the ceiling; sessions can bump it by one rung but not leapfrog it."

### Fix 2 — `merged_profile.py`: `compute_confidence`

```python
else:  # CONFLICTING
    return 0.72
```

Rationale: both sources have the skill (more evidence than resume_only alone). The 0.40 was a proxy for "uncertain" — but uncertainty about depth level is now handled in `compute_effective_depth`, not confidence. `0.72` sits just above the corroborated floor (`0.70`) and below high-frequency corroborated (`0.85+`).

### Fix 3 — `quick_match.py`: Remove rescue constants

Delete `CONFIDENCE_FLOOR = 0.65` and `CONFLICTING_EXPERT_CONF_FLOOR = 0.80`. They are referenced in two places — both must be cleaned up:

1. **`_score_requirement`** — remove the entire conditional block that clamps `effective_confidence` to these floors. Replace with the clean formula applied uniformly: `adjustment = 0.90 + 0.10 * best_match.confidence`.

2. **Compound-scoring loop** (line ~1743) — the line `conf = max(found.confidence, CONFIDENCE_FLOOR)` becomes simply `conf = found.confidence`. The floor was patching CONFLICTING's bad 0.40 value; with CONFLICTING at 0.72 this floor only distorts legitimate scores upward.

Update `SOURCE_LABEL` comment for CONFLICTING:
```python
EvidenceSource.CONFLICTING: "Resume depth anchored; sessions provided additional signal",
```

### Tests — `tests/test_quick_match.py`

Add to the existing parametrized skill-match tests:

| Case | Input | Expected |
|---|---|---|
| Sessions > resume by 2+ levels | sessions=EXPERT, resume=MENTIONED | effective_depth = BASIC (one above MENTIONED) |
| Sessions > resume, resume at APPLIED | sessions=EXPERT, resume=APPLIED | effective_depth = DEEP (one above APPLIED, capped at DEEP) |
| Resume > sessions by 2+ levels | resume=DEEP, sessions=MENTIONED | effective_depth = DEEP (resume wins) |
| CONFLICTING confidence | CONFLICTING source | confidence = 0.72 |
| No CONFIDENCE_FLOOR distortion | Call `assess_fit` with a profile containing a resume_only skill at conf 0.85 and a corroborated skill at conf 0.72 | Both score via `0.90 + 0.10 * conf` uniformly; neither is floored upward |

---

## Part 2 — Frontend: Confidence Layer

All data needed (`evidence_source`, `confidence`, `match_status`, `matched_skill`) is already in `skill_matches[]` in the API response. No server-side changes.

### 2a. Display Category Mapping (`popup.js`)

New helper function used by all confidence rendering:

```js
function categorizeSkill(m) {
    if (m.match_status === 'no_evidence') return 'missing';
    const req = (m.requirement || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    const matched = (m.matched_skill || '').toLowerCase().replace(/[^a-z0-9]/g, '');
    if (matched && matched !== req) return 'fuzzy';
    if (m.evidence_source === 'corroborated') return 'direct';
    return 'inferred'; // resume_only, sessions_only, conflicting all map here.
    // sessions_only intentionally reads as "inferred" — a skill seen only in
    // agentic sessions without resume corroboration is not guaranteed personal mastery.
}
```

Category → display color mapping:

| Category | Background | Text | Border | Dot |
|---|---|---|---|---|
| direct | `#ecfdf5` | `#065f46` | `#a7f3d0` | `#10b981` |
| inferred | `#fffbeb` | `#78350f` | `#fde68a` | `#f59e0b` |
| fuzzy | `#faf5ff` | `#4c1d95` | `#ddd6fe` | `#8b5cf6` |
| missing | `#fff1f2` | `#881337` | `#fecdd3` | `#f43f5e` |

### 2b. Signal Bars on Grade Badge

**`popup.html`** — Replace `results-hero` inner content with explicit children:

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

**`popup.js`** — Replace the existing hero rendering block (lines 76–92, both the `full` and `else` branches) with:

```js
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

After rendering skill_matches, compute and render bars:

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
```

**`popup.css`** — Add signal bar styles:

```css
/* Signal bars — absolute overlay on grade badge */
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

### 2c. Evidence Summary Chips

**`popup.html`** — Add between `#results-summary` and `#banner-deep-analysis` (not after the banner):

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

**`popup.js`** — Compute counts and show/hide:

```js
function renderEvidenceSummary(matches) {
    const counts = { direct: 0, inferred: 0, fuzzy: 0, missing: 0 };
    matches.forEach(m => counts[categorizeSkill(m)]++);
    ['direct','inferred','fuzzy','missing'].forEach(cat => {
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

**`popup.css`** — Evidence summary styles:

```css
.evidence-summary {
    display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
    padding: 6px 16px 10px;
    border-bottom: 1px solid #f3f4f6;
}
.evidence-label {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 10px; font-weight: 500; letter-spacing: 0.04em;
    text-transform: uppercase; color: #9ca3af;
}
.evidence-chip {
    font-family: 'SF Mono', 'Fira Code', monospace;
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
.direct-dot  { background: #10b981; }
.inferred-dot { background: #f59e0b; }
.fuzzy-dot   { background: #8b5cf6; }
.missing-dot { background: #f43f5e; }
```

### 2d. "Direct Evid." Stat Cell

**`popup.html`** — Add 4th stat:

```html
<div class="stat" id="row-direct-evid">
    <span class="stat-value signal" id="detail-direct-evid">--</span>
    <span class="stat-label">Direct Evid.</span>
</div>
```

**`popup.css`** — Extend grid to 4 columns, add signal cell styles:

```css
.stats-row { grid-template-columns: repeat(4, 1fr); }
#row-direct-evid { background: #f0fdfa; }
.stat-value.signal { color: #0d9488; }
```

**`popup.js`** — Compute and set:

```js
const withEvidence = matches.filter(m => m.match_status !== 'no_evidence');
const directCount = withEvidence.filter(m => categorizeSkill(m) === 'direct').length;
const directPct = withEvidence.length
    ? Math.round(directCount / withEvidence.length * 100) + '%'
    : '--';
el('detail-direct-evid').textContent = directPct;
```

### 2e. Per-Skill Confidence Bars, Source Chips, and Low-Conf Highlight

**`popup.js`** — Inside the `matches.forEach` loop in `renderResults`, update each `.match-item`:

```js
const cat = categorizeSkill(m);
const isMissing = cat === 'missing';
const conf = m.confidence || 0;
const confFill = conf >= 0.75 ? 'high' : conf >= 0.50 ? 'medium' : 'low';
const confDisplay = isMissing ? '—' : conf.toFixed(2);
const confValStyle = isMissing ? ' style="color:#d1d5db"' : '';
// Missing skills: render a plain dash, not a colored source chip
const sourceHtml = isMissing
    ? `<span style="font-family:'SF Mono','Fira Code',monospace;font-size:9px;color:#d1d5db;flex-shrink:0">—</span>`
    : `<span class="source-chip ${cat}">${cat}</span>`;

div.className = 'match-item' + (!isMissing && conf <= 0.70 ? ' low-conf' : '');
div.innerHTML = `
    <span class="match-icon ${iconClass}">${iconChar}</span>
    <span class="match-name">${m.requirement || ''}</span>
    <div class="conf-bar-wrap">
        <div class="conf-bar">
            <div class="conf-bar-fill ${isMissing ? '' : confFill}" style="width:${isMissing ? 0 : Math.round(conf*100)}%"></div>
        </div>
        <span class="conf-val"${confValStyle}>${confDisplay}</span>
    </div>
    ${sourceHtml}
`;
```

**`popup.css`** — Add per-skill styles:

```css
/* Per-skill confidence bar */
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
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 9px; font-weight: 600; color: #9ca3af;
    width: 26px; text-align: right; flex-shrink: 0;
}

/* Source provenance chip */
.source-chip {
    font-family: 'SF Mono', 'Fira Code', monospace;
    font-size: 9px; font-weight: 500;
    padding: 1px 5px; border-radius: 3px; white-space: nowrap; flex-shrink: 0;
}
.source-chip.direct   { background: #ecfdf5; color: #065f46; }
.source-chip.inferred { background: #fffbeb; color: #78350f; }
.source-chip.fuzzy    { background: #faf5ff; color: #4c1d95; }
/* missing skills: no chip rendered — use dash treatment inline via JS (see 2e) */

/* Low-confidence skill highlight */
.match-item.low-conf {
    background: linear-gradient(to right, #fffbeb 0%, transparent 100%);
    border-radius: 4px;
    padding-left: 4px; margin-left: -4px;
    border-left: 2px solid #f59e0b;
}
```

---

## File Change Summary

| File | What changes |
|---|---|
| `src/claude_candidate/schemas/merged_profile.py` | `compute_effective_depth` CONFLICTING branch — directional depth logic; `compute_confidence` CONFLICTING → 0.72 |
| `src/claude_candidate/quick_match.py` | Remove `CONFIDENCE_FLOOR`, `CONFLICTING_EXPERT_CONF_FLOOR`, and the conditional that uses them; update `SOURCE_LABEL` |
| `extension/popup.html` | `results-hero` → hero-text span + signal-bars slot; `#section-evidence-summary` after summary; 4th stat cell |
| `extension/popup.js` | `categorizeSkill()` helper; `renderSignalBars()`; `renderEvidenceSummary()`; Direct Evid. stat; per-skill conf bars + source chips + low-conf class |
| `extension/popup.css` | Signal bars, evidence chips, conf bars, source chips, low-conf highlight, stats-row 4-column, signal cell teal |
| `tests/test_quick_match.py` | CONFLICTING direction tests; no CONFIDENCE_FLOOR distortion regression |

---

## Non-Goals

- No `display_category` field added to backend schema
- No counterfactual grade
- No changes to full-assessment dimensions (mission, culture)
- No changes to CLI output or assessments.db
