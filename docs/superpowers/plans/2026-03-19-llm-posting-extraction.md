# LLM-Based Job Posting Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace CSS selector-based job posting extraction with LLM extraction via Claude CLI, cached server-side by URL.

**Architecture:** Content script grabs `document.body.innerText` and sends raw text to the local FastAPI server. Server calls Claude CLI to extract structured job data (company, title, description, location, seniority, remote, salary). Results are cached in SQLite by URL hash with 7-day TTL. Extension falls back to a simple heuristic (first h1 + largest text block) when the server is unavailable.

**Tech Stack:** Python 3.11+ (FastAPI, aiosqlite), TypeScript-free Chrome Extension (Manifest V3), Claude CLI via existing `call_claude()` helper

**Spec:** `docs/superpowers/specs/2026-03-19-llm-posting-extraction-design.md`

---

## File Structure

**Modified files:**
- `src/claude_candidate/storage.py` — add `posting_cache` table + `cache_posting()`, `get_cached_posting()` methods
- `src/claude_candidate/server.py` — add `ExtractPostingRequest`/`PostingExtraction` models, `POST /api/extract-posting` endpoint, `_infer_source()` helper
- `tests/test_server.py` — extraction endpoint tests (cache hit/miss, TTL, errors, source inference, truncation)
- `extension/content.js` — replace entire file: `grabPageText()` + `heuristicFallback()` + message listener
- `extension/background.js` — add `handleExtractPosting()` handler + switch case
- `extension/popup.js` — rewrite `initialize()` for two-step extraction: inject script → get raw text → server extraction → fallback
- `extension/manifest.json` — remove `content_scripts` block, add `scripting` permission

---

### Task 1: Add Posting Cache to Storage Layer

**Files:**
- Modify: `src/claude_candidate/storage.py`

The cache table stores Claude's structured extraction results keyed by URL hash. This is a pure backend change — no extension involvement.

- [ ] Add `_CREATE_POSTING_CACHE` SQL constant after the existing `_CREATE_PROFILES` constant:

```python
_CREATE_POSTING_CACHE = """
CREATE TABLE IF NOT EXISTS posting_cache (
    url_hash     TEXT PRIMARY KEY,
    url          TEXT NOT NULL,
    data         TEXT NOT NULL,
    extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""
```

- [ ] Add `posting_cache` table creation in `AssessmentStore.initialize()` after the profiles table creation (line 75):

```python
await self._conn.execute(_CREATE_POSTING_CACHE)
```

- [ ] Add `get_cached_posting()` method to `AssessmentStore` — returns the cached posting dict if fresh (< 7 days), else returns None and opportunistically deletes the expired row:

```python
async def get_cached_posting(self, url_hash: str) -> dict[str, Any] | None:
    """Return cached posting extraction if fresh (< 7 days), else None."""
    assert self._conn is not None, "Store not initialized"
    async with self._conn.execute(
        "SELECT data, extracted_at FROM posting_cache WHERE url_hash = ?;",
        (url_hash,),
    ) as cursor:
        row = await cursor.fetchone()
    if row is None:
        return None
    # TTL check: 7 days in seconds = 604800
    async with self._conn.execute(
        "SELECT (julianday('now') - julianday(?)) * 86400 > 604800;",
        (row[1],),
    ) as cursor:
        expired_row = await cursor.fetchone()
    if expired_row and expired_row[0]:
        # Opportunistic cleanup
        await self._conn.execute(
            "DELETE FROM posting_cache WHERE url_hash = ?;", (url_hash,)
        )
        await self._conn.commit()
        return None
    return json.loads(row[0])
```

- [ ] Add `cache_posting()` method:

```python
async def cache_posting(
    self, url_hash: str, url: str, data: dict[str, Any]
) -> None:
    """Cache a posting extraction result."""
    assert self._conn is not None, "Store not initialized"
    await self._conn.execute(
        """
        INSERT OR REPLACE INTO posting_cache (url_hash, url, data)
        VALUES (?, ?, ?);
        """,
        (url_hash, url, json.dumps(data)),
    )
    await self._conn.commit()
```

- [ ] Run tests to verify no regressions: `/opt/homebrew/bin/python3.11 -m pytest -q`
- [ ] Commit: `git add src/claude_candidate/storage.py && git commit -m "Add posting_cache table and methods to storage layer"`

---

### Task 2: Add Extract-Posting Server Endpoint

**Files:**
- Modify: `src/claude_candidate/server.py`
- Modify: `tests/test_server.py`

The endpoint receives raw page text, checks cache, calls Claude CLI if needed, caches the result, and returns structured posting data.

- [ ] Add Pydantic models after `GenerateRequest` in `server.py`:

```python
class ExtractPostingRequest(BaseModel):
    url: str
    title: str
    text: str

class PostingExtraction(BaseModel):
    company: str = ""
    title: str = ""
    description: str = ""
    url: str = ""
    source: str = "web"
    location: str | None = None
    seniority: str | None = None
    remote: bool | None = None
    salary: str | None = None
```

- [ ] Add `_infer_source()` helper inside `create_app()`:

```python
def _infer_source(url: str) -> str:
    """Infer job board source from URL hostname."""
    lower = url.lower()
    if "linkedin.com" in lower:
        return "linkedin"
    if "greenhouse.io" in lower:
        return "greenhouse"
    if "lever.co" in lower:
        return "lever"
    if "indeed.com" in lower:
        return "indeed"
    return "web"
```

- [ ] Add `_build_extraction_prompt()` helper inside `create_app()`:

```python
MAX_EXTRACTION_TEXT = 15_000

def _build_extraction_prompt(title: str, text: str) -> str:
    truncated = text[:MAX_EXTRACTION_TEXT]
    return (
        "Extract the job posting from this web page text. "
        "Return ONLY valid JSON with these fields:\n"
        '- company: string (the hiring company name)\n'
        '- title: string (the job title)\n'
        '- description: string (full job description including requirements and qualifications)\n'
        '- location: string or null\n'
        '- seniority: string or null (one of: junior, mid, senior, staff, principal, director)\n'
        '- remote: boolean or null\n'
        '- salary: string or null\n\n'
        "If this page does not contain a job posting, return all fields as null.\n\n"
        f"Page title: {title}\n"
        f"Page text:\n{truncated}"
    )
```

- [ ] Add imports at the top of `server.py` (after the existing `from claude_candidate.storage import AssessmentStore` line):

```python
from claude_candidate.claude_cli import call_claude, ClaudeCLIError, check_claude_available
```

Note: `hashlib` and `json` are already imported at module level in `server.py`.

- [ ] Add `POST /api/extract-posting` endpoint inside `create_app()`:

```python
@app.post("/api/extract-posting")
async def extract_posting(req: ExtractPostingRequest):
    store = get_store()
    url_hash = hashlib.sha256(req.url.encode()).hexdigest()[:16]

    # Check cache
    cached = await store.get_cached_posting(url_hash)
    if cached is not None:
        return cached

    # Call Claude
    if not check_claude_available():
        raise HTTPException(status_code=503, detail="Claude CLI not available for extraction")

    prompt = _build_extraction_prompt(req.title, req.text)
    try:
        raw = call_claude(prompt, timeout=30)
    except ClaudeCLIError as exc:
        raise HTTPException(status_code=503, detail=f"Claude CLI error: {exc}") from exc

    # Parse JSON from Claude response
    try:
        # Claude may wrap JSON in markdown code fences
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0]
        cleaned = cleaned.strip()
        parsed = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Extraction failed: invalid response from Claude",
        ) from exc

    # Build result
    source = _infer_source(req.url)
    result = PostingExtraction(
        company=parsed.get("company") or "",
        title=parsed.get("title") or "",
        description=parsed.get("description") or "",
        url=req.url,
        source=source,
        location=parsed.get("location"),
        seniority=parsed.get("seniority"),
        remote=parsed.get("remote"),
        salary=parsed.get("salary"),
    )
    result_dict = result.model_dump()

    # Cache
    await store.cache_posting(url_hash, req.url, result_dict)

    return result_dict
```

- [ ] Add `import json` to `tests/test_server.py` imports (needed for `json.dumps` in mock responses)

- [ ] Write tests in `tests/test_server.py` — add `TestExtractPostingEndpoint` class:

```python
class TestExtractPostingEndpoint:
    """Tests for POST /api/extract-posting."""

    async def test_extracts_posting_via_claude(self, client):
        """Cache miss: calls Claude, returns structured result, caches it."""
        claude_response = json.dumps({
            "company": "Acme Corp",
            "title": "Software Engineer",
            "description": "Build things.",
            "location": "Remote",
            "seniority": "senior",
            "remote": True,
            "salary": "$150k",
        })
        with patch("claude_candidate.claude_cli.check_claude_available", return_value=True), \
             patch("claude_candidate.claude_cli.call_claude", return_value=claude_response):
            resp = await client.post("/api/extract-posting", json={
                "url": "https://linkedin.com/jobs/view/123",
                "title": "Software Engineer | LinkedIn",
                "text": "Acme Corp is hiring a Software Engineer...",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["company"] == "Acme Corp"
        assert data["title"] == "Software Engineer"
        assert data["source"] == "linkedin"

    async def test_returns_cached_result(self, client):
        """Cache hit: returns cached result without calling Claude."""
        claude_response = json.dumps({"company": "Cached Co", "title": "Eng", "description": "x"})
        with patch("claude_candidate.claude_cli.check_claude_available", return_value=True), \
             patch("claude_candidate.claude_cli.call_claude", return_value=claude_response) as mock_claude:
            # First call — populates cache
            await client.post("/api/extract-posting", json={
                "url": "https://example.com/job/1",
                "title": "Eng",
                "text": "Some text",
            })
            # Second call — should hit cache
            resp = await client.post("/api/extract-posting", json={
                "url": "https://example.com/job/1",
                "title": "Eng",
                "text": "Some text",
            })
        assert resp.status_code == 200
        assert resp.json()["company"] == "Cached Co"
        assert mock_claude.call_count == 1  # only called once

    async def test_503_when_claude_unavailable(self, client):
        """Returns 503 when Claude CLI is not installed."""
        with patch("claude_candidate.claude_cli.check_claude_available", return_value=False):
            resp = await client.post("/api/extract-posting", json={
                "url": "https://example.com/job/2",
                "title": "Test",
                "text": "text",
            })
        assert resp.status_code == 503

    async def test_502_on_malformed_claude_response(self, client):
        """Returns 502 when Claude returns non-JSON."""
        with patch("claude_candidate.claude_cli.check_claude_available", return_value=True), \
             patch("claude_candidate.claude_cli.call_claude", return_value="This is not JSON"):
            resp = await client.post("/api/extract-posting", json={
                "url": "https://example.com/job/3",
                "title": "Test",
                "text": "text",
            })
        assert resp.status_code == 502

    async def test_infers_source_from_url(self, client):
        """Source field is inferred from URL, not from Claude."""
        claude_response = json.dumps({"company": "X", "title": "Y", "description": "Z"})
        with patch("claude_candidate.claude_cli.check_claude_available", return_value=True), \
             patch("claude_candidate.claude_cli.call_claude", return_value=claude_response):
            resp = await client.post("/api/extract-posting", json={
                "url": "https://boards.greenhouse.io/company/jobs/123",
                "title": "Y",
                "text": "text",
            })
        assert resp.json()["source"] == "greenhouse"

    async def test_truncates_long_text(self, client):
        """Text longer than 15k chars is truncated before sending to Claude."""
        long_text = "x" * 20_000
        claude_response = json.dumps({"company": "X", "title": "Y", "description": "Z"})
        with patch("claude_candidate.claude_cli.check_claude_available", return_value=True), \
             patch("claude_candidate.claude_cli.call_claude", return_value=claude_response) as mock_claude:
            await client.post("/api/extract-posting", json={
                "url": "https://example.com/job/4",
                "title": "Test",
                "text": long_text,
            })
        # Verify the prompt sent to Claude has truncated text
        prompt = mock_claude.call_args[0][0]
        assert len(prompt) < 20_000

    async def test_handles_code_fenced_json(self, client):
        """Claude sometimes wraps JSON in markdown code fences."""
        fenced = '```json\n{"company": "Fenced Co", "title": "Eng", "description": "ok"}\n```'
        with patch("claude_candidate.claude_cli.check_claude_available", return_value=True), \
             patch("claude_candidate.claude_cli.call_claude", return_value=fenced):
            resp = await client.post("/api/extract-posting", json={
                "url": "https://example.com/job/5",
                "title": "Test",
                "text": "text",
            })
        assert resp.status_code == 200
        assert resp.json()["company"] == "Fenced Co"

    async def test_null_fields_for_non_job_page(self, client):
        """Non-job pages return null/empty fields with 200."""
        claude_response = json.dumps({
            "company": None, "title": None, "description": None,
            "location": None, "seniority": None, "remote": None, "salary": None,
        })
        with patch("claude_candidate.claude_cli.check_claude_available", return_value=True), \
             patch("claude_candidate.claude_cli.call_claude", return_value=claude_response):
            resp = await client.post("/api/extract-posting", json={
                "url": "https://twitter.com/home",
                "title": "Twitter",
                "text": "What is happening?!",
            })
        assert resp.status_code == 200
        assert resp.json()["company"] == ""
        assert resp.json()["description"] == ""

    async def test_expired_cache_triggers_reextraction(self, client):
        """Cache entry older than 7 days triggers a fresh Claude call."""
        claude_response = json.dumps({"company": "Old Co", "title": "Eng", "description": "old"})
        with patch("claude_candidate.claude_cli.check_claude_available", return_value=True), \
             patch("claude_candidate.claude_cli.call_claude", return_value=claude_response):
            # First call — populates cache
            await client.post("/api/extract-posting", json={
                "url": "https://example.com/job/expired",
                "title": "Eng",
                "text": "Some text",
            })

        # Manually backdate the cache entry to 8 days ago
        store = client.app.state.store if hasattr(client.app, 'state') else None
        # Use direct DB access to backdate
        import aiosqlite
        # The store's db path is accessible; manipulate extracted_at directly
        # (This is a test-only hack to simulate TTL expiry)

        new_response = json.dumps({"company": "Fresh Co", "title": "Eng", "description": "fresh"})
        with patch("claude_candidate.claude_cli.check_claude_available", return_value=True), \
             patch("claude_candidate.claude_cli.call_claude", return_value=new_response) as mock_claude:
            # The implementer should backdate the cache row's extracted_at to 8 days ago
            # before this second call, then verify mock_claude is called again.
            # Exact DB manipulation depends on how the test fixture exposes the store.
            pass
```

Note: the expired cache test requires direct DB manipulation to backdate `extracted_at`. The implementer should adapt the exact DB access pattern to match the test fixture's store exposure.

- [ ] Run tests: `/opt/homebrew/bin/python3.11 -m pytest tests/test_server.py -q`
- [ ] Run full suite: `/opt/homebrew/bin/python3.11 -m pytest -q`
- [ ] Commit: `git add src/claude_candidate/server.py tests/test_server.py && git commit -m "Add POST /api/extract-posting endpoint with Claude CLI extraction and cache"`

---

### Task 3: Rewrite Content Script

**Files:**
- Rewrite: `extension/content.js`

Delete all 383 lines. Replace with ~50 lines: `grabPageText()`, `heuristicFallback()`, and a message listener.

Note: the spec mentions `rawPageText` auto-caching on page load. This is intentionally omitted because the content script is now injected on-demand via `chrome.scripting.executeScript`, not at `document_idle`. There is no auto-extract-on-load behavior.

- [ ] Replace entire content of `extension/content.js`:

```javascript
/**
 * content.js — Raw page text grabber for LLM-based extraction.
 * No CSS selectors. No board detection. Grabs visible text and returns it.
 * Injected on-demand via chrome.scripting.executeScript from the popup.
 */
(function () {
	'use strict';

	const MAX_TEXT_LENGTH = 15000;

	/** Grab raw visible text from the page. */
	function grabPageText() {
		const text = (document.body.innerText || '').substring(0, MAX_TEXT_LENGTH);
		return {
			url: window.location.href,
			title: document.title,
			text: text,
			extractedAt: Date.now(),
		};
	}

	/** Best-effort heuristic fallback when server is unavailable. */
	function heuristicFallback() {
		const h1 = document.querySelector('h1');
		const title = h1 ? (h1.innerText || '').trim() : document.title;

		// Find the largest text block on the page
		let best = '';
		const candidates = document.querySelectorAll('section, article, main, [role="main"], div');
		for (const el of candidates) {
			const t = (el.innerText || '').trim();
			if (t.length > best.length && t.length > 100 && t.length < MAX_TEXT_LENGTH) {
				best = t;
			}
		}

		return {
			company: '',
			title: title,
			description: best,
			url: window.location.href,
			source: 'heuristic',
			location: null,
			seniority: null,
			remote: null,
			salary: null,
		};
	}

	chrome.runtime.onMessage.addListener(function (request, _sender, sendResponse) {
		try {
			if (request.action === 'extractJobPosting') {
				const pageData = grabPageText();
				sendResponse({ success: true, pageData });
			} else if (request.action === 'extractFallback') {
				const posting = heuristicFallback();
				sendResponse({ success: true, posting });
			} else {
				sendResponse({ success: false, error: 'Unknown action' });
			}
		} catch (err) {
			sendResponse({ success: false, error: err.message || 'Content script error' });
		}
		return false; // synchronous response
	});
})();
```

- [ ] Commit: `git add extension/content.js && git commit -m "Replace selector-based extractors with raw text grabber and heuristic fallback"`

---

### Task 4: Add Extract Handler to Background Script

**Files:**
- Modify: `extension/background.js`

Add `handleExtractPosting()` that calls `POST /api/extract-posting` and wire it into the message listener switch.

- [ ] Add handler after `handleOpenReport`:

```javascript
async function handleExtractPosting(payload) {
	try {
		const data = await apiFetch('/api/extract-posting', {
			method: 'POST',
			body: JSON.stringify({
				url: payload.url || '',
				title: payload.title || '',
				text: payload.text || '',
			}),
		});
		return { success: true, ...data };
	} catch (err) {
		return { success: false, error: err.message };
	}
}
```

- [ ] Add case to the message listener switch (after `'openReport'` case):

```javascript
case 'extractPosting':
    promise = handleExtractPosting(request.payload);
    break;
```

- [ ] Commit: `git add extension/background.js && git commit -m "Add extractPosting handler to background service worker"`

---

### Task 5: Rewrite Popup Initialization Flow

**Files:**
- Modify: `extension/popup.js`

Replace the `initialize()` function to use two-step extraction: inject content script → get raw text → server extraction → fallback. Also add a helper for programmatic script injection.

- [ ] Add `injectAndSend()` helper after `sendToActiveTab()`:

```javascript
/**
 * Inject content.js into the active tab and send it a message.
 * Uses chrome.scripting.executeScript (requires "scripting" permission + "activeTab").
 */
async function injectAndSend(msg) {
	const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
	if (!tabs || !tabs.length) return { success: false, error: 'No active tab' };
	const tabId = tabs[0].id;

	// Inject the content script (idempotent — Chrome ignores if already injected)
	try {
		await chrome.scripting.executeScript({
			target: { tabId },
			files: ['content.js'],
		});
	} catch (err) {
		return { success: false, error: 'Cannot inject script: ' + (err.message || '') };
	}

	// Small delay to let the script initialize
	await new Promise(r => setTimeout(r, 100));

	// Send message to content script
	return new Promise(resolve => {
		chrome.tabs.sendMessage(tabId, msg, r => {
			if (chrome.runtime.lastError) {
				resolve({ success: false, error: chrome.runtime.lastError.message });
			} else {
				resolve(r || {});
			}
		});
	});
}
```

- [ ] Rewrite `initialize()`:

```javascript
async function initialize() {
	showState('loading');

	// Step 1: Check backend
	const health = await sendToBackground({ action: 'checkBackend' });
	if (!health.connected) { showState('no-backend'); return; }
	if (health.profile_loaded === false) { showState('no-profile'); return; }

	// Step 2: Check extension cache (5-minute TTL)
	let posting = null;
	const stored = await new Promise(r => {
		chrome.storage.local.get('currentPosting', res => r(res.currentPosting || null));
	});
	const fresh = stored && stored.extractedAt && (Date.now() - stored.extractedAt) < POSTING_TTL_MS;
	if (fresh && stored.description) {
		posting = stored;
	}

	if (!posting) {
		// Step 3: Inject content script and grab raw page text
		const ext = await injectAndSend({ action: 'extractJobPosting' });
		if (ext.success && ext.pageData) {
			// Step 4: Send raw text to server for LLM extraction
			const extraction = await sendToBackground({
				action: 'extractPosting',
				payload: ext.pageData,
			});
			if (extraction.success && extraction.description) {
				posting = { ...extraction, extractedAt: Date.now() };
				chrome.storage.local.set({ currentPosting: posting });
			}
		}

		// Step 5: Heuristic fallback if server extraction failed
		if (!posting) {
			const fallback = await injectAndSend({ action: 'extractFallback' });
			if (fallback.success && fallback.posting && fallback.posting.description) {
				posting = { ...fallback.posting, extractedAt: Date.now() };
				// Don't cache heuristic results — they're low quality
			}
		}
	}

	// Step 6: Gate on description
	if (!posting || !posting.description) { showState('no-job'); return; }
	currentPosting = posting;

	const ac = el('assessing-company');
	if (ac) ac.textContent = posting.company
		? `${posting.title || 'Role'} at ${posting.company}`
		: posting.title || '';
	showState('assessing');

	// Step 7: Assess (existing progressive loading flow)
	const partial = await sendToBackground({ action: 'assessPartial', payload: posting });
	if (!partial.success && partial.error) {
		el('error-message').textContent = partial.error;
		showState('error');
		return;
	}

	renderResults(partial);
	const banner = el('banner-full-loading');
	if (banner) banner.classList.remove('hidden');

	const assessmentId = partial.assessment_id;
	sendToBackground({ action: 'assessFull', assessmentId }).then(full => {
		if (banner) banner.classList.add('hidden');
		const btnFull = el('btn-full-details');
		if (!btnFull) return;
		if (full.success && full.assessment_id) {
			const reportUrl = `http://localhost:7429/api/assessments/${full.assessment_id}`;
			btnFull.onclick = () => sendToBackground({ action: 'openReport', url: reportUrl });
		} else if (full.error) {
			btnFull.title = `Full report unavailable: ${full.error}`;
		}
	});
}
```

- [ ] Remove the old `sendToActiveTab()` function (no longer used — replaced by `injectAndSend()`)
- [ ] Commit: `git add extension/popup.js && git commit -m "Rewrite popup initialization for two-step LLM extraction flow"`

---

### Task 6: Update Extension Manifest

**Files:**
- Modify: `extension/manifest.json`

Remove the `content_scripts` block (content script is now injected on demand). Add `scripting` permission for `chrome.scripting.executeScript`.

- [ ] Replace the entire `manifest.json`:

```json
{
  "manifest_version": 3,
  "name": "claude-candidate",
  "version": "0.4.0",
  "description": "Honest, evidence-backed job fit assessments from your Claude Code session logs",
  "permissions": ["activeTab", "storage", "scripting"],
  "host_permissions": ["http://localhost:7429/*"],
  "background": { "service_worker": "background.js" },
  "action": {
    "default_popup": "popup.html",
    "default_icon": { "16": "icons/icon16.png", "48": "icons/icon48.png", "128": "icons/icon128.png" }
  },
  "icons": { "16": "icons/icon16.png", "48": "icons/icon48.png", "128": "icons/icon128.png" }
}
```

Key changes:
- Removed `content_scripts` block entirely
- Added `"scripting"` to `permissions` array
- Bumped version to `0.4.0`

- [ ] Commit: `git add extension/manifest.json && git commit -m "Remove content_scripts, add scripting permission for on-demand injection"`

---

### Task 7: Integration Verification

Run full test suite and verify the entire flow works end-to-end.

- [ ] Run full test suite: `/opt/homebrew/bin/python3.11 -m pytest -q`
- [ ] Verify all existing tests still pass (should be 687+ passed)
- [ ] Load extension in Chrome (`chrome://extensions` → Load unpacked → select `extension/` directory)
- [ ] Navigate to a LinkedIn job posting → click extension → verify extraction succeeds
- [ ] Navigate to a non-job page → click extension → verify "no-job" state
- [ ] Stop the server → click extension on a job page → verify heuristic fallback
- [ ] Re-visit the same job page → verify cache hit (instant response)
- [ ] Commit any fixes discovered during verification

---

## Verification Gate

After all 7 tasks:
1. Full test suite passes (687+ existing + new extraction tests)
2. `POST /api/extract-posting` returns structured posting from raw page text
3. Cache hit returns instantly without calling Claude
4. Cache expired (> 7 days) triggers re-extraction
5. Claude CLI unavailable returns 503
6. Malformed Claude response returns 502
7. Extension extracts job postings from any page (not just LinkedIn/Greenhouse)
8. Extension falls back to heuristic when server is down
9. No CSS selectors remain in `content.js`
10. Extension manifest uses `activeTab` + `scripting` (no `<all_urls>`)
