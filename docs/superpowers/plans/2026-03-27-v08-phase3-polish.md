# v0.8 Phase 3 — Polish + Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship v0.8.2 — extend the dashboard with shortlist integration, add unified skills display with evidence drill-down, detect stale profiles via hash comparison, remove backward-compat import shim, and update ARCHITECTURE.md to reflect v0.8 final state.

**Architecture:** The extension dashboard gains tab navigation (Assessments | Shortlist) backed by a new enriched shortlist API endpoint that JOINs shortlist rows with fresh assessment data. The popup gains expandable skill detail rows and a stale-profile yellow banner driven by `/api/profile/status` hash comparison. Backend gets shortlist deduplication. All old `from claude_candidate.quick_match import X` paths are migrated to `from claude_candidate.scoring import X`, and the shim file is deleted.

**Tech Stack:** Python 3.13, FastAPI, aiosqlite, Pydantic v2, Chrome Extension MV3 (plain JS), vitest, pytest

**Scope exclusion:** #9 Scale Property is skipped (weak signal from local git data, low ROI). The `scale` field on `MergedSkillEvidence` remains but is not surfaced in UI or scoring.

**Agent assignments:**
- Tasks 1, 5, 6, 7: sonnet (mechanical)
- Tasks 2, 3, 4: opus (judgment — data architecture, UX)

**Parallelization:**
- Task 1 first (version bump — prerequisite for all)
- Task 2 next (backend shortlist — prerequisite for Task 3)
- Tasks 3, 4, 5 in parallel (dashboard, skills display, stale profile)
- Tasks 6, 7 in parallel (import cleanup, ARCHITECTURE.md)

---

### Task 1: Version Bump to 0.8.2

**Files:**
- Modify: `pyproject.toml:7`
- Modify: `extension/manifest.json:4`

- [ ] **Step 1: Bump Python package version**

In `pyproject.toml`, change line 7:

```toml
version = "0.8.2"
```

- [ ] **Step 2: Bump extension version**

In `extension/manifest.json`, change line 4:

```json
  "version": "0.8.2",
```

- [ ] **Step 3: Verify versions match**

Run: `.venv/bin/python -c "from claude_candidate import __version__; print(__version__)"`
Expected: `0.8.2`

Run: `grep '"version"' extension/manifest.json`
Expected: `"version": "0.8.2",`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml extension/manifest.json
git commit -m "$(cat <<'EOF'
chore: bump version to 0.8.2 for Phase 3
EOF
)"
```

---

### Task 2: Backend — Shortlist Deduplication + Enriched Listing

**Files:**
- Modify: `src/claude_candidate/storage.py:218-315`
- Modify: `src/claude_candidate/server.py:817-870`
- Modify: `tests/test_storage.py`

**Context:** The shortlist table has no dedup protection — clicking "Add to Shortlist" twice creates duplicate rows. The dashboard needs fresh assessment grades, but shortlist stores snapshot `overall_grade` at add-time. This task adds: (1) `find_shortlist_by_url()` for dedup checks, (2) `list_shortlist_enriched()` that JOINs with assessments for fresh data, (3) upsert behavior in the server endpoint.

- [ ] **Step 1: Write failing test for find_shortlist_by_url**

Add to `tests/test_storage.py`:

```python
class TestShortlistDedup:
	"""Shortlist deduplication via posting_url lookup."""

	def test_find_by_url_returns_match(self, store):
		"""find_shortlist_by_url returns the existing entry when posting_url matches."""
		run(store.add_to_shortlist(
			company_name="Acme",
			job_title="Engineer",
			posting_url="https://example.com/job/1",
			overall_grade="B+",
		))
		result = run(store.find_shortlist_by_url("https://example.com/job/1"))
		assert result is not None
		assert result["company_name"] == "Acme"
		assert result["posting_url"] == "https://example.com/job/1"

	def test_find_by_url_returns_none_when_missing(self, store):
		"""find_shortlist_by_url returns None when no match."""
		result = run(store.find_shortlist_by_url("https://example.com/job/999"))
		assert result is None

	def test_find_by_url_returns_none_for_null_url(self, store):
		"""Entries with NULL posting_url are not matched."""
		run(store.add_to_shortlist(
			company_name="Acme",
			job_title="Engineer",
			posting_url=None,
		))
		result = run(store.find_shortlist_by_url("https://example.com/job/1"))
		assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_storage.py::TestShortlistDedup -v`
Expected: FAIL with `AttributeError: 'AssessmentStore' object has no attribute 'find_shortlist_by_url'`

- [ ] **Step 3: Implement find_shortlist_by_url**

Add to `src/claude_candidate/storage.py` after the `remove_from_shortlist` method (after line 315):

```python
	async def find_shortlist_by_url(self, posting_url: str) -> dict[str, Any] | None:
		"""Find a shortlist entry by posting_url, or None if not found."""
		assert self._conn is not None, "Store not initialized"
		async with self._conn.execute(
			"SELECT * FROM shortlist WHERE posting_url = ? ORDER BY added_at DESC LIMIT 1;",
			(posting_url,),
		) as cursor:
			row = await cursor.fetchone()
		return dict(row) if row else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_storage.py::TestShortlistDedup -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Write failing test for list_shortlist_enriched**

Add to `tests/test_storage.py`:

```python
class TestShortlistEnriched:
	"""Shortlist listing enriched with assessment data."""

	def test_enriched_includes_assessment_grade(self, store):
		"""Enriched listing includes fresh grade from linked assessment."""
		aid = run(store.save_assessment({
			"assessment_id": "a-1",
			"assessed_at": "2026-03-27T10:00:00",
			"job_title": "Engineer",
			"company_name": "Acme",
			"overall_score": 82,
			"overall_grade": "B+",
			"should_apply": True,
			"data": {"overall_score": 0.82},
		}))
		run(store.add_to_shortlist(
			company_name="Acme",
			job_title="Engineer",
			posting_url="https://example.com/job/1",
			assessment_id="a-1",
			overall_grade="B",  # stale snapshot grade
		))
		results = run(store.list_shortlist_enriched())
		assert len(results) == 1
		# Fresh grade from assessment, not stale snapshot
		assert results[0]["assessment_grade"] == "B+"
		assert results[0]["assessment_score"] == 82

	def test_enriched_without_assessment_uses_snapshot(self, store):
		"""Entries without linked assessment fall back to snapshot grade."""
		run(store.add_to_shortlist(
			company_name="Acme",
			job_title="Engineer",
			posting_url="https://example.com/job/1",
			overall_grade="B",
		))
		results = run(store.list_shortlist_enriched())
		assert len(results) == 1
		assert results[0]["assessment_grade"] is None
		assert results[0]["overall_grade"] == "B"

	def test_enriched_filters_by_status(self, store):
		"""Enriched listing respects status filter."""
		run(store.add_to_shortlist(
			company_name="Acme",
			job_title="SWE",
			status="applied",
		))
		run(store.add_to_shortlist(
			company_name="Beta",
			job_title="SRE",
		))
		results = run(store.list_shortlist_enriched(status="applied"))
		assert len(results) == 1
		assert results[0]["company_name"] == "Acme"
```

- [ ] **Step 6: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_storage.py::TestShortlistEnriched -v`
Expected: FAIL with `AttributeError: 'AssessmentStore' object has no attribute 'list_shortlist_enriched'`

- [ ] **Step 7: Implement list_shortlist_enriched**

Add to `src/claude_candidate/storage.py` after `find_shortlist_by_url`:

```python
	async def list_shortlist_enriched(
		self, status: str | None = None, limit: int = 50
	) -> list[dict[str, Any]]:
		"""List shortlist entries with fresh assessment data joined in."""
		assert self._conn is not None, "Store not initialized"
		where = ""
		params: list[Any] = []
		if status is not None:
			where = "WHERE s.status = ?"
			params.append(status)
		params.append(limit)
		sql = f"""
			SELECT s.*,
				a.overall_grade AS assessment_grade,
				a.overall_score AS assessment_score,
				a.assessed_at AS assessment_date
			FROM shortlist s
			LEFT JOIN assessments a ON s.assessment_id = a.assessment_id
			{where}
			ORDER BY s.added_at DESC
			LIMIT ?;
		"""
		async with self._conn.execute(sql, params) as cursor:
			rows = await cursor.fetchall()
		return [dict(r) for r in rows]
```

Note: The `add_to_shortlist` method needs an optional `status` parameter to support the test. Check if it already accepts `status` — looking at the current signature, it does NOT accept `status`. Add it:

In `src/claude_candidate/storage.py`, update `add_to_shortlist` signature and INSERT (around line 218):

```python
	async def add_to_shortlist(
		self,
		company_name: str,
		job_title: str,
		posting_url: str | None = None,
		assessment_id: str | None = None,
		notes: str | None = None,
		salary: str | None = None,
		location: str | None = None,
		overall_grade: str | None = None,
		status: str = "shortlisted",
	) -> int:
		"""Insert a shortlist entry and return its auto-generated id."""
		assert self._conn is not None, "Store not initialized"
		async with self._conn.execute(
			"""
            INSERT INTO shortlist (company_name, job_title, posting_url, assessment_id, notes, status, salary, location, overall_grade)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
			(
				company_name,
				job_title,
				posting_url,
				assessment_id,
				notes,
				status,
				salary,
				location,
				overall_grade,
			),
		) as cursor:
			row_id = cursor.lastrowid
		await self._conn.commit()
		return row_id  # type: ignore[return-value]
```

- [ ] **Step 8: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_storage.py::TestShortlistEnriched -v`
Expected: PASS (3 tests)

- [ ] **Step 9: Update server endpoint for dedup + add enriched endpoint**

In `src/claude_candidate/server.py`, update the `add_shortlist` endpoint (around line 817):

```python
	@app.post("/api/shortlist", status_code=201)
	async def add_shortlist(req: ShortlistAddRequest):
		store = get_store()
		# Dedup: if posting_url already in shortlist, update instead of inserting
		if req.posting_url:
			existing = await store.find_shortlist_by_url(req.posting_url)
			if existing:
				# Update assessment linkage if provided
				await store.update_shortlist(
					existing["id"],
					assessment_id=req.assessment_id,
				)
				return {
					**existing,
					"assessment_id": req.assessment_id or existing["assessment_id"],
					"already_exists": True,
				}
		sid = await store.add_to_shortlist(
			company_name=req.company_name,
			job_title=req.job_title,
			posting_url=req.posting_url,
			assessment_id=req.assessment_id,
			notes=req.notes,
			salary=req.salary,
			location=req.location,
			overall_grade=req.overall_grade,
		)
		return {
			"id": sid,
			"company_name": req.company_name,
			"job_title": req.job_title,
			"posting_url": req.posting_url,
			"assessment_id": req.assessment_id,
			"notes": req.notes,
			"status": "shortlisted",
			"salary": req.salary,
			"location": req.location,
			"overall_grade": req.overall_grade,
		}
```

Add the enriched endpoint after the existing `/api/shortlist` GET (after line 849):

```python
	@app.get("/api/shortlist/enriched")
	async def list_shortlist_enriched(
		status: str | None = Query(default=None),
		limit: int = Query(default=50, ge=1, le=200),
	):
		store = get_store()
		return await store.list_shortlist_enriched(status=status, limit=limit)
```

- [ ] **Step 10: Run full test suite**

Run: `.venv/bin/python -m pytest tests/test_storage.py -v`
Expected: All tests pass

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass (1317+)

- [ ] **Step 11: Commit**

```bash
git add src/claude_candidate/storage.py src/claude_candidate/server.py tests/test_storage.py
git commit -m "$(cat <<'EOF'
feat: shortlist deduplication and enriched listing endpoint

Add find_shortlist_by_url() for dedup checks, list_shortlist_enriched()
with LEFT JOIN for fresh assessment grades, and upsert behavior in the
POST /api/shortlist endpoint to prevent duplicate entries.
EOF
)"
```

---

### Task 3: Dashboard — Tab Navigation with Shortlist View

**Files:**
- Modify: `extension/dashboard.html`
- Modify: `extension/dashboard.js`

**Context:** The current dashboard is a batch-results-only view sourced from `chrome.storage.local` + `/api/assessments`. This task adds tab navigation with a Shortlist tab sourced from the new `/api/shortlist/enriched` endpoint, with inline status management and drill-down links.

- [ ] **Step 1: Add tab navigation to dashboard.html**

Replace the `<h1>` and `<p class="subtitle">` section (lines 64-66) in `extension/dashboard.html` with:

```html
	<div class="container">
		<h1>claude-candidate Dashboard</h1>

		<nav class="tab-bar">
			<button class="tab active" data-tab="assessments">Assessments</button>
			<button class="tab" data-tab="shortlist">Shortlist</button>
		</nav>

		<div id="tab-assessments" class="tab-panel">
			<p class="subtitle" id="subtitle">Loading...</p>

			<div id="progress-section">
```

Note: The closing `</div>` for `tab-assessments` goes after the empty-state div (before the closing `</div>` for `.container`). Add it after line 109:

```html
		</div><!-- end tab-assessments -->

		<div id="tab-shortlist" class="tab-panel hidden">
			<div class="summary-row" id="shortlist-summary">
				<div class="summary-card">
					<div class="label">Shortlisted</div>
					<div class="value" id="sl-stat-total">0</div>
				</div>
				<div class="summary-card">
					<div class="label">Applied</div>
					<div class="value" id="sl-stat-applied">0</div>
				</div>
				<div class="summary-card">
					<div class="label">Interviewing</div>
					<div class="value" id="sl-stat-interview">0</div>
				</div>
				<div class="summary-card">
					<div class="label">Avg Grade</div>
					<div class="value" id="sl-stat-grade">--</div>
				</div>
			</div>

			<table id="shortlist-table">
				<thead>
					<tr>
						<th>Grade</th>
						<th>Company</th>
						<th>Role</th>
						<th>Status</th>
						<th>Location</th>
						<th>Salary</th>
						<th>Added</th>
						<th></th>
					</tr>
				</thead>
				<tbody id="shortlist-body"></tbody>
			</table>

			<div class="empty-state" id="shortlist-empty">
				<h2>No shortlisted jobs</h2>
				<p>Use the "Add to Shortlist" button in the extension popup to track jobs you're interested in.</p>
			</div>
		</div><!-- end tab-shortlist -->
	</div>
```

- [ ] **Step 2: Add tab bar and shortlist styles**

Add these styles before the closing `</style>` tag in `dashboard.html`:

```css
		.tab-bar { display: flex; gap: 0; margin-bottom: 24px; border-bottom: 2px solid #e2e8f0; }
		.tab {
			padding: 10px 20px; font-size: 13px; font-weight: 600; color: #64748b;
			background: none; border: none; cursor: pointer; border-bottom: 2px solid transparent;
			margin-bottom: -2px; transition: all 0.15s;
		}
		.tab:hover { color: #334155; }
		.tab.active { color: #6366f1; border-bottom-color: #6366f1; }
		.tab-panel.hidden { display: none; }
		.status-select {
			padding: 4px 8px; border-radius: 6px; border: 1px solid #e2e8f0;
			font-size: 12px; cursor: pointer; background: #fff;
		}
		.status-shortlisted { color: #6366f1; }
		.status-applied { color: #0891b2; }
		.status-interviewing { color: #d97706; }
		.status-offer { color: #059669; }
		.status-rejected { color: #dc2626; }
		.btn-delete {
			background: none; border: none; cursor: pointer; color: #94a3b8;
			font-size: 16px; padding: 4px 8px; border-radius: 4px;
		}
		.btn-delete:hover { background: #fef2f2; color: #dc2626; }
		.date-cell { color: #64748b; font-size: 12px; white-space: nowrap; }
```

- [ ] **Step 3: Add shortlist tab logic to dashboard.js**

Append to the end of `extension/dashboard.js` (after line 202):

```javascript

// ---------------------------------------------------------------------------
// Tab navigation
// ---------------------------------------------------------------------------

document.querySelectorAll('.tab').forEach(tab => {
	tab.addEventListener('click', () => {
		document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
		document.querySelectorAll('.tab-panel').forEach(p => p.classList.add('hidden'));
		tab.classList.add('active');
		document.getElementById('tab-' + tab.dataset.tab).classList.remove('hidden');
		if (tab.dataset.tab === 'shortlist') loadShortlist();
	});
});

// ---------------------------------------------------------------------------
// Shortlist tab
// ---------------------------------------------------------------------------

const STATUS_OPTIONS = ['shortlisted', 'applied', 'interviewing', 'offer', 'rejected'];

async function loadShortlist() {
	try {
		const resp = await fetch('http://localhost:7429/api/shortlist/enriched?limit=200');
		if (!resp.ok) return;
		const items = await resp.json();
		renderShortlist(items);
	} catch (e) {
		console.log('Could not load shortlist:', e);
	}
}

function renderShortlist(items) {
	const tbody = document.getElementById('shortlist-body');
	const table = document.getElementById('shortlist-table');
	const empty = document.getElementById('shortlist-empty');
	tbody.innerHTML = '';

	if (!items.length) {
		table.classList.add('hidden');
		empty.classList.remove('hidden');
		return;
	}
	table.classList.remove('hidden');
	empty.classList.add('hidden');

	// Summary stats
	document.getElementById('sl-stat-total').textContent = items.length;
	document.getElementById('sl-stat-applied').textContent =
		items.filter(i => i.status === 'applied').length;
	document.getElementById('sl-stat-interview').textContent =
		items.filter(i => i.status === 'interviewing').length;

	const grades = items.map(i => i.assessment_grade || i.overall_grade).filter(Boolean);
	if (grades.length > 0) {
		// Simple grade average via score mapping
		const gradeScore = { 'A+': 97, 'A': 93, 'A-': 90, 'B+': 87, 'B': 83, 'B-': 80, 'C+': 77, 'C': 73, 'C-': 70, 'D': 65, 'F': 50 };
		const avg = grades.reduce((s, g) => s + (gradeScore[g] || 70), 0) / grades.length;
		const avgGrade = Object.entries(gradeScore).find(([, v]) => avg >= v)?.[0] || 'C';
		document.getElementById('sl-stat-grade').textContent = avgGrade;
	}

	items.forEach(item => {
		const tr = document.createElement('tr');
		const grade = item.assessment_grade || item.overall_grade || '?';
		const addedDate = item.added_at ? new Date(item.added_at + 'Z').toLocaleDateString() : '--';

		tr.innerHTML = `
			<td><span class="grade-badge ${gradeClass(grade)}">${grade}</span></td>
			<td><strong>${escapeHtml(item.company_name || '')}</strong></td>
			<td>${escapeHtml(item.job_title || '')}</td>
			<td>
				<select class="status-select status-${item.status || 'shortlisted'}" data-id="${item.id}">
					${STATUS_OPTIONS.map(s =>
						`<option value="${s}" ${s === item.status ? 'selected' : ''}>${s}</option>`
					).join('')}
				</select>
			</td>
			<td>${escapeHtml(item.location || '--')}</td>
			<td>${escapeHtml(item.salary || '--')}</td>
			<td class="date-cell">${addedDate}</td>
			<td><button class="btn-delete" data-id="${item.id}" title="Remove">✕</button></td>
		`;

		// Click row (except controls) to open posting
		tr.style.cursor = 'pointer';
		tr.addEventListener('click', (e) => {
			if (e.target.closest('select, button')) return;
			if (item.posting_url) window.open(item.posting_url, '_blank');
		});

		tbody.appendChild(tr);
	});

	// Status change handlers
	tbody.querySelectorAll('.status-select').forEach(sel => {
		sel.addEventListener('change', async (e) => {
			const id = e.target.dataset.id;
			const newStatus = e.target.value;
			e.target.className = `status-select status-${newStatus}`;
			await fetch(`http://localhost:7429/api/shortlist/${id}`, {
				method: 'PATCH',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ status: newStatus }),
			});
		});
	});

	// Delete handlers
	tbody.querySelectorAll('.btn-delete').forEach(btn => {
		btn.addEventListener('click', async (e) => {
			e.stopPropagation();
			const id = btn.dataset.id;
			await fetch(`http://localhost:7429/api/shortlist/${id}`, { method: 'DELETE' });
			loadShortlist(); // refresh
		});
	});
}

function escapeHtml(s) {
	return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}
```

- [ ] **Step 4: Verify dashboard loads correctly**

Open `extension/dashboard.html` in a browser (or load the extension and open dashboard). Verify:
- Two tabs appear: "Assessments" and "Shortlist"
- Assessments tab shows existing batch results
- Shortlist tab fetches from `/api/shortlist/enriched`
- Status dropdowns change color per status
- Delete button removes entries

Run: `cd extension && source ~/.nvm/nvm.sh && nvm use default && npx vitest run`
Expected: All existing tests still pass (13 tests)

- [ ] **Step 5: Commit**

```bash
git add extension/dashboard.html extension/dashboard.js
git commit -m "$(cat <<'EOF'
feat: dashboard tabs with shortlist view and status tracking

Add tab navigation to dashboard (Assessments | Shortlist). Shortlist tab
shows enriched data with fresh assessment grades, inline status management
(shortlisted → applied → interviewing → offer → rejected), and delete.
EOF
)"
```

---

### Task 4: Unified Skills Display — Evidence Drill-Down

**Files:**
- Modify: `extension/popup.html:194-198`
- Modify: `extension/popup.js:292-403`
- Modify: `extension/popup.css`

**Context:** The popup already renders skill match rows with icon, requirement name, confidence bar, and source chip. This task makes each row expandable — clicking reveals the evidence chain: canonical skill → match type → evidence source → candidate evidence text → priority level.

The data is already present in `SkillMatchDetail`: `matched_skill`, `match_type`, `evidence_source`, `candidate_evidence`, `priority`, `confidence`.

- [ ] **Step 1: Add expandable detail styles to popup.css**

Append to `extension/popup.css`:

```css
/* Unified skills — expandable evidence detail */
.match-item { cursor: pointer; }
.match-detail {
	display: none;
	padding: 6px 12px 10px 32px;
	font-size: 11px;
	line-height: 1.6;
	color: #475569;
	background: #f8fafc;
	border-top: 1px solid #f1f5f9;
}
.match-item.expanded + .match-detail { display: block; }
.match-detail-row {
	display: flex;
	gap: 6px;
	align-items: baseline;
}
.match-detail-label {
	font-weight: 600;
	color: #64748b;
	min-width: 70px;
	flex-shrink: 0;
	font-size: 10px;
	text-transform: uppercase;
	letter-spacing: 0.03em;
}
.match-detail-value {
	color: #334155;
}
.match-type-badge {
	display: inline-block;
	padding: 1px 6px;
	border-radius: 4px;
	font-size: 10px;
	font-weight: 600;
}
.match-type-exact { background: #ecfdf5; color: #065f46; }
.match-type-fuzzy { background: #eff6ff; color: #1e40af; }
.match-type-none { background: #fef2f2; color: #991b1b; }
.priority-badge {
	display: inline-block;
	padding: 1px 6px;
	border-radius: 4px;
	font-size: 10px;
	font-weight: 500;
}
.priority-must_have { background: #fef2f2; color: #991b1b; }
.priority-strong_preference { background: #fffbeb; color: #92400e; }
.priority-nice_to_have { background: #f0fdf4; color: #166534; }
.priority-implied { background: #f1f5f9; color: #64748b; }
```

- [ ] **Step 2: Update skill match rendering in popup.js to add expandable detail**

In `extension/popup.js`, find the section where `match-item` divs are created (inside the `matches.forEach((m, i) => {` loop, approximately lines 314-344). After each `matchList.appendChild(div);` for a non-compound match-item, insert a detail panel.

Replace the `matches.forEach` block (lines 314-345, from `matches.forEach((m, i) => {` to the line before `// Render compound groups`) with:

```javascript
		matches.forEach((m, i) => {
			// Skip children — they render inside their compound group
			if (renderedAsChild.has(i)) return;

			const status = m.match_status || '';
			const iconClass = status.includes('strong') || status === 'exceeds' ? 'hit'
				: status === 'no_evidence' ? 'miss' : 'partial';
			const iconChar = iconClass === 'hit' ? '+' : iconClass === 'miss' ? 'x' : '~';
			const cat = categorizeSkill(m);
			const isMissing = cat === 'missing';
			const conf = m.confidence || 0;
			const confFill = conf >= 0.75 ? 'high' : conf >= 0.50 ? 'medium' : 'low';
			const confDisplay = isMissing ? '\u2014' : conf.toFixed(2);
			const confValStyle = isMissing ? ' style="color:#d1d5db"' : '';
			const sourceHtml = isMissing
				? `<span style="font-family:'SF Mono','Fira Code',monospace;font-size:9px;color:#d1d5db;flex-shrink:0">\u2014</span>`
				: `<span class="source-chip ${cat}">${cat}</span>`;
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

			// Toggle expand on click
			div.addEventListener('click', () => div.classList.toggle('expanded'));

			matchList.appendChild(div);

			// Evidence detail panel (hidden until expanded)
			const detail = document.createElement('div');
			detail.className = 'match-detail';
			const detailRows = [];
			if (m.matched_skill) {
				detailRows.push(`<div class="match-detail-row">
					<span class="match-detail-label">Skill</span>
					<span class="match-detail-value">${escHtml(m.matched_skill)}</span>
				</div>`);
			}
			if (m.match_type) {
				detailRows.push(`<div class="match-detail-row">
					<span class="match-detail-label">Match</span>
					<span class="match-detail-value"><span class="match-type-badge match-type-${m.match_type}">${m.match_type}</span></span>
				</div>`);
			}
			if (m.evidence_source) {
				const srcLabel = String(m.evidence_source).replace(/_/g, ' ');
				detailRows.push(`<div class="match-detail-row">
					<span class="match-detail-label">Source</span>
					<span class="match-detail-value">${escHtml(srcLabel)}</span>
				</div>`);
			}
			if (m.priority) {
				const prioLabel = String(m.priority).replace(/_/g, ' ');
				detailRows.push(`<div class="match-detail-row">
					<span class="match-detail-label">Priority</span>
					<span class="match-detail-value"><span class="priority-badge priority-${m.priority}">${escHtml(prioLabel)}</span></span>
				</div>`);
			}
			if (m.candidate_evidence && !isMissing) {
				detailRows.push(`<div class="match-detail-row">
					<span class="match-detail-label">Evidence</span>
					<span class="match-detail-value">${escHtml(m.candidate_evidence)}</span>
				</div>`);
			}
			detail.innerHTML = detailRows.join('');
			matchList.appendChild(detail);
		});
```

- [ ] **Step 3: Verify skill display expands on click**

Load the extension, navigate to a job posting, trigger an assessment. In the Skill Matches section:
- Click a skill row → detail panel expands showing canonical skill, match type, source, priority, evidence
- Click again → collapses
- Missing skills show no evidence row
- Compound groups still render correctly

Run: `cd extension && source ~/.nvm/nvm.sh && nvm use default && npx vitest run`
Expected: All existing tests still pass

- [ ] **Step 4: Commit**

```bash
git add extension/popup.css extension/popup.js
git commit -m "$(cat <<'EOF'
feat: unified skills display with expandable evidence drill-down

Click any skill match row to reveal the evidence chain: canonical skill
name, match type (exact/fuzzy), evidence source, priority level, and
candidate evidence text.
EOF
)"
```

---

### Task 5: Stale Profile Detection — Yellow Banner

**Files:**
- Modify: `extension/popup.html:60-62`
- Modify: `extension/popup.js:460-497`
- Create: `extension/tests/stale.test.js`

**Context:** Each `FitAssessment` stores a `profile_hash`. The `/api/profile/status` endpoint returns current hashes for all profile types. When the popup reopens a cached assessment, it compares the current profile hashes against those stored at assessment time. If they differ, a yellow banner warns the user. The banner is session-dismissible.

- [ ] **Step 1: Write failing vitest test for stale detection logic**

Create `extension/tests/stale.test.js`:

```javascript
import { describe, it, expect } from 'vitest';

// Pure logic helper — will be added to utils.js
const { isProfileStale } = await import('../utils.js');

describe('isProfileStale', () => {
	it('returns false when hashes match', () => {
		const stored = { candidate: 'abc', curated_resume: 'def', repo_profile: 'ghi' };
		const current = { candidate: 'abc', curated_resume: 'def', repo_profile: 'ghi' };
		expect(isProfileStale(stored, current)).toBe(false);
	});

	it('returns true when any hash changes', () => {
		const stored = { candidate: 'abc', curated_resume: 'def', repo_profile: 'ghi' };
		const current = { candidate: 'abc', curated_resume: 'CHANGED', repo_profile: 'ghi' };
		expect(isProfileStale(stored, current)).toBe(true);
	});

	it('returns true when a new profile type appears', () => {
		const stored = { candidate: 'abc' };
		const current = { candidate: 'abc', repo_profile: 'new' };
		expect(isProfileStale(stored, current)).toBe(true);
	});

	it('returns false when stored is null (first assessment)', () => {
		expect(isProfileStale(null, { candidate: 'abc' })).toBe(false);
	});

	it('returns false when current is empty', () => {
		const stored = { candidate: 'abc' };
		expect(isProfileStale(stored, {})).toBe(false);
	});
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd extension && source ~/.nvm/nvm.sh && nvm use default && npx vitest run tests/stale.test.js`
Expected: FAIL — `isProfileStale` is not exported from utils.js

- [ ] **Step 3: Implement isProfileStale in utils.js**

Add to `extension/utils.js` before the `globalThis` export block (before line 61):

```javascript
/**
 * Compare stored profile hashes against current hashes.
 * Returns true if the profile has changed since the stored snapshot.
 */
function isProfileStale(storedHashes, currentHashes) {
	if (!storedHashes) return false;
	if (!currentHashes || Object.keys(currentHashes).length === 0) return false;
	// Check all keys present in current — any new or changed hash means stale
	for (const key of Object.keys(currentHashes)) {
		if (storedHashes[key] !== currentHashes[key]) return true;
	}
	return false;
}
```

Update the `globalThis` export block to include `isProfileStale`:

```javascript
if (typeof globalThis !== 'undefined') {
	globalThis.normalizeUrl = normalizeUrl;
	globalThis.getForUrl = getForUrl;
	globalThis.setForUrl = setForUrl;
	globalThis.removeForUrl = removeForUrl;
	globalThis.isProfileStale = isProfileStale;
}
```

Update the `module.exports` block:

```javascript
if (typeof module !== 'undefined' && module.exports) {
	module.exports = { normalizeUrl, getForUrl, setForUrl, removeForUrl, isProfileStale };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd extension && source ~/.nvm/nvm.sh && nvm use default && npx vitest run tests/stale.test.js`
Expected: PASS (5 tests)

- [ ] **Step 5: Add stale banner HTML to popup.html**

In `extension/popup.html`, add the banner inside `state-results` right after line 62 (`<div id="state-results" class="state hidden">`):

```html
		<div class="stale-banner hidden" id="stale-banner">
			<span class="stale-icon">⚠</span>
			<span class="stale-text">Your profile has changed since this assessment.</span>
			<button id="btn-reassess" class="btn-stale-action">Re-assess</button>
			<button id="btn-dismiss-stale" class="btn-stale-dismiss">✕</button>
		</div>
```

- [ ] **Step 6: Add stale banner styles to popup.css**

Append to `extension/popup.css`:

```css
/* Stale profile banner */
.stale-banner {
	display: flex;
	align-items: center;
	gap: 8px;
	padding: 8px 12px;
	background: #fef9c3;
	border: 1px solid #fde68a;
	border-radius: 8px;
	margin: 0 0 12px 0;
	font-size: 12px;
	color: #854d0e;
}
.stale-banner.hidden { display: none; }
.stale-icon { font-size: 14px; flex-shrink: 0; }
.stale-text { flex: 1; }
.btn-stale-action {
	padding: 3px 10px;
	background: #f59e0b;
	color: #fff;
	border: none;
	border-radius: 5px;
	font-size: 11px;
	font-weight: 600;
	cursor: pointer;
	flex-shrink: 0;
}
.btn-stale-action:hover { background: #d97706; }
.btn-stale-dismiss {
	background: none;
	border: none;
	color: #92400e;
	cursor: pointer;
	font-size: 14px;
	padding: 0 4px;
	flex-shrink: 0;
}
```

- [ ] **Step 7: Wire stale detection into popup.js**

In `extension/popup.js`, update the `initialize` function. After the successful assessment result is cached (around line 551, after `setForUrl('assessment', currentTabUrl, { url: posting.url, data: partial });`), store the current profile hashes:

```javascript
	// Store profile hashes for stale detection
	try {
		const profileStatus = await sendToBackground({ action: 'getProfileStatus' });
		if (profileStatus && profileStatus.hashes) {
			setForUrl('profileHashes', currentTabUrl, profileStatus.hashes);
		}
	} catch (e) { /* non-critical */ }
```

In the cache-hit path (around line 476, before `renderResults`), add stale detection:

```javascript
	if (fresh && lastAssessment && lastAssessment.data) {
		currentPosting = stored;

		// Stale profile detection
		const storedHashes = await getForUrl('profileHashes', currentTabUrl);
		try {
			const profileStatus = await sendToBackground({ action: 'getProfileStatus' });
			if (profileStatus && profileStatus.hashes && isProfileStale(storedHashes, profileStatus.hashes)) {
				const banner = el('stale-banner');
				if (banner) banner.classList.remove('hidden');
			}
		} catch (e) { /* non-critical — banner just won't show */ }
```

In the `DOMContentLoaded` handler (around line 575), add banner button listeners:

```javascript
	const btnDismissStale = el('btn-dismiss-stale');
	if (btnDismissStale) btnDismissStale.addEventListener('click', () => {
		el('stale-banner').classList.add('hidden');
	});

	const btnReassess = el('btn-reassess');
	if (btnReassess) btnReassess.addEventListener('click', async () => {
		// Clear cached assessment so initialize() runs fresh
		const [activeTab] = await chrome.tabs.query({ active: true, currentWindow: true });
		const url = activeTab?.url || '';
		await removeForUrl('assessment', url);
		await removeForUrl('fullReady', url);
		await removeForUrl('posting', url);
		el('stale-banner').classList.add('hidden');
		initialize();
	});
```

- [ ] **Step 8: Add getProfileStatus handler to background.js**

In `extension/background.js`, add a case to the message handler switch (around line 329, before the `default` case):

```javascript
		case 'getProfileStatus':
			promise = apiFetch('/api/profile/status').catch(() => ({}));
			break;
```

- [ ] **Step 9: Run all extension tests**

Run: `cd extension && source ~/.nvm/nvm.sh && nvm use default && npx vitest run`
Expected: All tests pass (storage tests + stale tests)

- [ ] **Step 10: Commit**

```bash
git add extension/popup.html extension/popup.js extension/popup.css extension/background.js extension/utils.js extension/tests/stale.test.js
git commit -m "$(cat <<'EOF'
feat: stale profile detection with yellow banner in popup

Compare profile hashes from /api/profile/status against stored hashes.
Show yellow banner when profile changes since last assessment, with
re-assess and dismiss buttons. Session-dismissible.
EOF
)"
```

---

### Task 6: Import Path Migration — Remove quick_match.py Shim

**Files:**
- Modify: `src/claude_candidate/server.py:435,540`
- Modify: `src/claude_candidate/cli.py:93`
- Modify: `tests/conftest.py:88`
- Modify: `tests/test_integration.py:174`
- Modify: `tests/test_quick_match.py` (many imports)
- Modify: `tests/golden_set/benchmark_accuracy.py:18`
- Delete: `src/claude_candidate/quick_match.py`

**Context:** The `quick_match.py` shim was created in Phase 0 to maintain backward compatibility during the scoring/ subpackage migration. All imports using `from claude_candidate.quick_match import X` must be updated to `from claude_candidate.scoring import X`. Then the shim file is deleted.

**Important:** Only modify active source and test files. Plan docs in `docs/superpowers/plans/` are historical and should NOT be updated.

- [ ] **Step 1: Update server.py imports**

In `src/claude_candidate/server.py`, find and replace all occurrences:

Line 435: `from claude_candidate.quick_match import QuickMatchEngine`
→ `from claude_candidate.scoring import QuickMatchEngine`

Line 540: `from claude_candidate.quick_match import QuickMatchEngine`
→ `from claude_candidate.scoring import QuickMatchEngine`

- [ ] **Step 2: Update cli.py import**

In `src/claude_candidate/cli.py`, line 93:
`from claude_candidate.quick_match import QuickMatchEngine`
→ `from claude_candidate.scoring import QuickMatchEngine`

- [ ] **Step 3: Update test files**

In `tests/conftest.py`, line 88:
`from claude_candidate.quick_match import QuickMatchEngine`
→ `from claude_candidate.scoring import QuickMatchEngine`

In `tests/test_integration.py`, line 174:
`from claude_candidate.quick_match import QuickMatchEngine`
→ `from claude_candidate.scoring import QuickMatchEngine`

In `tests/golden_set/benchmark_accuracy.py`, line 18:
`from claude_candidate.quick_match import QuickMatchEngine`
→ `from claude_candidate.scoring import QuickMatchEngine`

In `tests/test_quick_match.py`, replace ALL `from claude_candidate.quick_match import` with `from claude_candidate.scoring import` throughout the file. There are approximately 50+ occurrences. Use a global find/replace:
`from claude_candidate.quick_match import` → `from claude_candidate.scoring import`

- [ ] **Step 4: Run the full test suite BEFORE deleting the shim**

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass (the shim is still present, but no code imports it anymore)

- [ ] **Step 5: Delete the shim file**

```bash
rm src/claude_candidate/quick_match.py
```

- [ ] **Step 6: Run the full test suite AFTER deleting the shim**

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass — no code depends on quick_match.py anymore

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Expected: 47/47 exact match, no regressions

- [ ] **Step 7: Verify no remaining quick_match imports in active code**

Run: `grep -r "from claude_candidate.quick_match" src/ tests/ --include="*.py" | grep -v "docs/"`
Expected: No output (zero remaining imports)

- [ ] **Step 8: Commit**

```bash
git add -u src/claude_candidate/server.py src/claude_candidate/cli.py src/claude_candidate/quick_match.py tests/conftest.py tests/test_integration.py tests/test_quick_match.py tests/golden_set/benchmark_accuracy.py
git commit -m "$(cat <<'EOF'
refactor: remove quick_match.py backward-compat shim

Migrate all imports from claude_candidate.quick_match to
claude_candidate.scoring. Delete the shim file — all scoring
logic lives in the scoring/ subpackage since Phase 0.
EOF
)"
```

---

### Task 7: ARCHITECTURE.md Update

**Files:**
- Modify: `ARCHITECTURE.md`

**Context:** ARCHITECTURE.md is at v0.5.0 and doesn't reflect the v0.8 architecture: scoring/ subpackage, 3 evidence sources (resume + repos + sessions/behavioral), repo scanner, dashboard, shortlist, stale profile detection, culture fit from sessions.

- [ ] **Step 1: Rewrite ARCHITECTURE.md to v0.8.2**

Replace the entire contents of `ARCHITECTURE.md` with the updated version. Key changes:
- Version header: v0.5.0 → v0.8.2
- Pipeline diagram: add repo scanner path, sessions → behavioral signals path
- Module map: add scoring/ subpackage (constants, matching, dimensions, engine), repo_scanner.py, remove quick_match.py (replaced by scoring/)
- Merger description: update evidence sources (resume_only, repo_only, resume_and_repo) — remove sessions_only/corroborated as deprecated
- Scoring description: reference scoring/ subpackage, adaptive weights, 5 dimensions (skills, experience, education, mission, culture fit)
- Extension section: add dashboard with tabs, shortlist integration, stale profile detection, unified skills display
- Data flow: add repo scan step, stale detection flow
- Key design decisions: add repo-as-receipt evidence model, profile_hash staleness, session behavioral signals for culture fit
- What is not implemented: update (remove items now implemented), add remaining gaps
- Local data: add repo_profile.json path
- Tech stack: no changes

The full content should be written by the implementing agent based on the current codebase state. The agent should read all key files fresh and produce an accurate architecture document. Do NOT copy the old v0.5.0 content — write from scratch to match v0.8.2 reality.

Key sections to include:
1. Pipeline Stages (updated diagram with 3 evidence sources)
2. Module Map (core pipeline, scoring subpackage, supporting modules, enrichment subpackage)
3. Schema Map (all pydantic models)
4. Browser Extension Architecture (popup, dashboard with tabs, background, content)
5. Data Flow (session scan, resume onboard, repo scan, assess, stale detection)
6. Scoring Architecture (5 dimensions, adaptive weights, confidence model)
7. Key Design Decisions (privacy, dual→triple evidence, Claude CLI not API, incremental extraction, evidence compaction, adaptive weights, eligibility gates, profile hash staleness)
8. What Is Not Implemented (remaining gaps)
9. Local Data
10. Tech Stack

- [ ] **Step 2: Verify the document is accurate**

Spot-check: grep for key module names, class names, and paths mentioned in the document to confirm they exist in the codebase.

- [ ] **Step 3: Commit**

```bash
git add ARCHITECTURE.md
git commit -m "$(cat <<'EOF'
docs: update ARCHITECTURE.md to v0.8.2 final state

Reflect scoring/ subpackage, 3 evidence sources (resume + repos +
sessions/behavioral), dashboard with shortlist tabs, stale profile
detection, unified skills display, and culture fit from sessions.
EOF
)"
```

---

## Post-Completion Verification

After all 7 tasks are committed:

- [ ] **Run Python test suite**

Run: `.venv/bin/python -m pytest -x -q`
Expected: All tests pass (1317+ tests)

- [ ] **Run extension tests**

Run: `cd extension && source ~/.nvm/nvm.sh && nvm use default && npx vitest run`
Expected: All tests pass (13+ existing + 5 stale tests)

- [ ] **Run benchmark**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Expected: 47/47 exact match, no regressions

- [ ] **Push and create PR**

```bash
git push -u origin feat/v08-phase3-polish
gh pr create --title "feat: v0.8 Phase 3 — polish, dashboard, stale detection" --body "$(cat <<'EOF'
## Summary
- Extended dashboard with tab navigation (Assessments | Shortlist) — enriched shortlist view with status tracking and fresh assessment grades via LEFT JOIN
- Unified skills display with expandable evidence drill-down (canonical skill → match type → source → evidence text)
- Stale profile detection via profile_hash comparison — yellow banner with re-assess action
- Import path migration complete — quick_match.py shim removed, all imports use scoring/ subpackage
- ARCHITECTURE.md updated to v0.8.2 final state

## Test plan
- [ ] 1317+ Python tests pass (`pytest -x -q`)
- [ ] 18+ vitest extension tests pass
- [ ] 47/47 benchmark exact match
- [ ] Dashboard: tabs switch correctly, shortlist loads from enriched endpoint
- [ ] Dashboard: status dropdown updates via PATCH, delete removes entry
- [ ] Popup: skill rows expand to show evidence detail
- [ ] Popup: stale banner appears when profile hashes change
- [ ] Popup: "Add to Shortlist" deduplicates (shows already_exists for same URL)
- [ ] No remaining `from claude_candidate.quick_match` imports in src/ or tests/
EOF
)"
```
