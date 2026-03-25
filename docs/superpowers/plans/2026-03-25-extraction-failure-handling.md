# Extraction Failure Handling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent garbage assessments when Claude extraction fails by gating on requirements and removing the keyword fallback.

**Architecture:** Extension-side gate blocks assessment when requirements are missing. Server returns 422 as safety net. LinkedIn URL normalization fixes cache misses. Extraction logging captures failures for debugging.

**Tech Stack:** Python (FastAPI, pydantic), JavaScript (Chrome MV3 extension), pytest + httpx for async server tests.

**Spec:** `docs/superpowers/specs/2026-03-25-extraction-failure-handling-design.md`

---

### Task 1: Server — remove keyword fallback, return 422

**Files:**
- Modify: `src/claude_candidate/server.py:297-327`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing test — 422 on null requirements**

In `tests/test_server.py`, add:

```python
class TestAssessRequiresRequirements:
	"""Server must reject assessments when no requirements are provided."""

	@pytest.mark.asyncio
	async def test_assess_partial_rejects_null_requirements(self, app_with_profile):
		async with LifespanManager(app_with_profile):
			transport = ASGITransport(app=app_with_profile)
			async with AsyncClient(transport=transport, base_url="http://test") as client:
				resp = await client.post(
					"/api/assess/partial",
					json={
						"posting_text": "We need a Python developer with Django experience.",
						"company": "TestCo",
						"title": "Software Engineer",
						"requirements": None,
					},
				)
				assert resp.status_code == 422
				assert "requirements" in resp.json()["detail"].lower()

	@pytest.mark.asyncio
	async def test_assess_partial_rejects_empty_requirements(self, app_with_profile):
		async with LifespanManager(app_with_profile):
			transport = ASGITransport(app=app_with_profile)
			async with AsyncClient(transport=transport, base_url="http://test") as client:
				resp = await client.post(
					"/api/assess/partial",
					json={
						"posting_text": "We need a Python developer.",
						"company": "TestCo",
						"title": "Software Engineer",
						"requirements": [],
					},
				)
				assert resp.status_code == 422

	@pytest.mark.asyncio
	async def test_assess_partial_accepts_valid_requirements(self, app_with_profile):
		async with LifespanManager(app_with_profile):
			transport = ASGITransport(app=app_with_profile)
			async with AsyncClient(transport=transport, base_url="http://test") as client:
				resp = await client.post(
					"/api/assess/partial",
					json={
						"posting_text": "Python developer role",
						"company": "TestCo",
						"title": "Software Engineer",
						"requirements": [
							{
								"description": "Python experience",
								"skill_mapping": ["python"],
								"priority": "must_have",
								"source_text": "Must have Python",
							}
						],
					},
				)
				assert resp.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestAssessRequiresRequirements -v`
Expected: First two FAIL (currently returns 200 with keyword fallback), third PASS.

- [ ] **Step 3: Replace keyword fallback with 422 in `_run_quick_assess`**

In `src/claude_candidate/server.py`, replace lines 297–327 of `_run_quick_assess`:

```python
async def _run_quick_assess(req: AssessRequest) -> dict[str, Any]:
	"""
	Run QuickMatchEngine (local-only, no Claude calls) and persist the result.

	Returns the assessment dict. Raises HTTPException on missing profile
	or missing requirements.
	"""
	from claude_candidate.schemas.job_requirements import QuickRequirement
	from claude_candidate.quick_match import QuickMatchEngine

	store = get_store()

	merged = _build_merged_profile()
	if merged is None:
		raise HTTPException(
			status_code=422,
			detail="No candidate profile loaded. Place candidate_profile.json in the data directory.",
		)

	# Build requirements — filter out invalid entries from Claude
	requirements = []
	if req.requirements:
		for r in req.requirements:
			try:
				requirements.append(QuickRequirement(**r))
			except Exception:
				continue  # Skip malformed requirements

	if not requirements:
		raise HTTPException(
			status_code=422,
			detail="No valid requirements provided — extraction required before assessment.",
		)

	# Run assessment
	engine = QuickMatchEngine(merged)
```

Key change: the `from claude_candidate.cli import _extract_basic_requirements` import and both fallback calls are deleted. Empty requirements → 422.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestAssessRequiresRequirements -v`
Expected: All 3 PASS.

- [ ] **Step 5: Run full fast test suite**

Run: `.venv/bin/python -m pytest`
Expected: All pass. If any existing test relied on the keyword fallback, it will need updating.

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/server.py tests/test_server.py
git commit -m "fix: reject assessments with no requirements instead of keyword fallback"
```

---

### Task 2: Server — normalize LinkedIn URLs for cache keys

**Files:**
- Modify: `src/claude_candidate/server.py:776-832`
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing test — same posting, different tracking params**

In `tests/test_server.py`, add:

```python
class TestLinkedInUrlNormalization:
	"""LinkedIn tracking params should not defeat the posting cache."""

	@pytest.mark.asyncio
	async def test_linkedin_url_normalized_for_cache(self, app_with_profile):
		"""Same job ID with different tracking params should hit cache."""
		from unittest.mock import patch, AsyncMock

		url_base = "https://www.linkedin.com/jobs/view/4385180576/"
		url_with_params = url_base + "?trk=eml-email_job_alert&eBP=abc123&trackingId=xyz"

		async with LifespanManager(app_with_profile):
			transport = ASGITransport(app=app_with_profile)
			async with AsyncClient(transport=transport, base_url="http://test") as client:
				posting_text = "Senior Engineer role requiring Python and Django."

				with patch(
					"claude_candidate.server._claude_cli.call_claude",
					return_value='{"company":"TestCo","title":"Engineer","description":"test","requirements":[]}',
				), patch(
					"claude_candidate.server._claude_cli.check_claude_available",
					return_value=True,
				):
					# First request with clean URL
					r1 = await client.post(
						"/api/extract-posting",
						json={"url": url_base, "title": "Test", "text": posting_text},
					)
					assert r1.status_code == 200

					# Second request with tracking params — should hit cache, not call Claude again
					with patch(
						"claude_candidate.server._claude_cli.call_claude",
						side_effect=AssertionError("Should not be called — cache should hit"),
					):
						r2 = await client.post(
							"/api/extract-posting",
							json={"url": url_with_params, "title": "Test", "text": posting_text},
						)
						assert r2.status_code == 200
						assert r2.json()["company"] == "TestCo"

	@pytest.mark.asyncio
	async def test_non_linkedin_url_keeps_params(self, app_with_profile):
		"""Non-LinkedIn URLs should keep query params in the cache key."""
		async with LifespanManager(app_with_profile):
			transport = ASGITransport(app=app_with_profile)
			async with AsyncClient(transport=transport, base_url="http://test") as client:
				with patch(
					"claude_candidate.server._claude_cli.call_claude",
					return_value='{"company":"TestCo","title":"Engineer","description":"test","requirements":[]}',
				), patch(
					"claude_candidate.server._claude_cli.check_claude_available",
					return_value=True,
				):
					r1 = await client.post(
						"/api/extract-posting",
						json={
							"url": "https://greenhouse.io/jobs/123?param=a",
							"title": "Test",
							"text": "Some job",
						},
					)
					assert r1.status_code == 200
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestLinkedInUrlNormalization -v`
Expected: `test_linkedin_url_normalized_for_cache` FAIL (second request calls Claude instead of hitting cache).

- [ ] **Step 3: Add URL normalization helper and apply it**

In `src/claude_candidate/server.py`, add a helper function before the `extract_posting` endpoint and apply it:

```python
def _normalize_cache_url(url: str) -> str:
	"""Strip tracking params from LinkedIn URLs for cache key stability.

	LinkedIn appends session-specific params (trk=, eBP=, trackingId=)
	that change per visit. The job ID in the path is the canonical identifier.
	"""
	from urllib.parse import urlparse, urlunparse

	parsed = urlparse(url)
	if "linkedin.com" in parsed.netloc and "/jobs/view/" in parsed.path:
		return urlunparse(parsed._replace(query="", fragment=""))
	return url
```

Then in `extract_posting`, replace:
```python
url_hash = hashlib.sha256(req.url.encode()).hexdigest()[:16]
```
with:
```python
cache_url = _normalize_cache_url(req.url)
url_hash = hashlib.sha256(cache_url.encode()).hexdigest()[:16]
```

And update the cache store call:
```python
await store.cache_posting(url_hash, cache_url, result_dict)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestLinkedInUrlNormalization -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/server.py tests/test_server.py
git commit -m "fix: normalize LinkedIn URLs for posting cache keys"
```

---

### Task 3: Server — extraction logging + timeout bump

**Files:**
- Modify: `src/claude_candidate/server.py:776-833`

- [ ] **Step 1: Add logging to extraction endpoint**

At the top of `server.py`, add (near existing imports):

```python
import logging

logger = logging.getLogger("claude_candidate.server")
```

Then update the `extract_posting` endpoint to log key events:

```python
@app.post("/api/extract-posting")
async def extract_posting(req: ExtractPostingRequest):
	store = get_store()
	cache_url = _normalize_cache_url(req.url)
	url_hash = hashlib.sha256(cache_url.encode()).hexdigest()[:16]

	cached = await store.get_cached_posting(url_hash)
	if cached is not None:
		logger.info("extract-posting cache hit: %s", cache_url[:80])
		return cached

	if not _claude_cli.check_claude_available():
		logger.warning("extract-posting: Claude CLI not available")
		raise HTTPException(status_code=503, detail="Claude CLI not available for extraction")

	import asyncio

	logger.info("extract-posting: extracting %s (%d chars)", cache_url[:80], len(req.text))
	prompt = _build_extraction_prompt(req.title, req.text)
	try:
		raw = await asyncio.get_event_loop().run_in_executor(
			None, lambda: _claude_cli.call_claude(prompt, timeout=120)
		)
	except _claude_cli.ClaudeCLIError as exc:
		logger.warning("extract-posting: Claude CLI error for %s: %s", cache_url[:80], exc)
		raise HTTPException(status_code=503, detail=f"Claude CLI error: {exc}") from exc

	try:
		cleaned = raw.strip()
		if cleaned.startswith("```"):
			cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
		if cleaned.endswith("```"):
			cleaned = cleaned.rsplit("```", 1)[0]
		cleaned = cleaned.strip()
		parsed = json.loads(cleaned)
	except (json.JSONDecodeError, ValueError) as exc:
		logger.warning("extract-posting: invalid JSON from Claude for %s", cache_url[:80])
		raise HTTPException(
			status_code=502,
			detail="Extraction failed: invalid response from Claude",
		) from exc

	# Normalize skill mappings through taxonomy
	if "requirements" in parsed and isinstance(parsed["requirements"], list):
		from claude_candidate.requirement_parser import normalize_skill_mappings
		normalize_skill_mappings(parsed["requirements"])

	req_count = len(parsed.get("requirements", []) or [])
	if req_count == 0:
		logger.warning("extract-posting: Claude returned 0 requirements for %s", cache_url[:80])
	else:
		logger.info("extract-posting: extracted %d requirements for %s", req_count, cache_url[:80])

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
		requirements=parsed.get("requirements"),
	)
	result_dict = result.model_dump()
	await store.cache_posting(url_hash, cache_url, result_dict)
	return result_dict
```

Note: timeout changed from `90` to `120` (line with `call_claude`).

- [ ] **Step 2: Run full fast test suite**

Run: `.venv/bin/python -m pytest`
Expected: All pass.

- [ ] **Step 3: Commit**

```bash
git add src/claude_candidate/server.py
git commit -m "feat: add extraction logging and bump timeout to 120s"
```

---

### Task 4: Extension — gate on requirements before assessment

**Files:**
- Modify: `extension/popup.js:442-465`

- [ ] **Step 1: Remove heuristic fallback and add requirements gate**

In `extension/popup.js`, replace lines 442–465:

```javascript
if (!posting) {
	const lt = el('loading-text');
	if (lt) lt.textContent = 'Extracting job posting...';
	const ext = await injectAndSend({ action: 'extractJobPosting' });
	if (ext.success && ext.pageData) {
		const extraction = await sendToBackground({
			action: 'extractPosting',
			payload: ext.pageData,
		});
		if (extraction.success && extraction.description) {
			posting = { ...extraction, extractedAt: Date.now() };
			chrome.storage.local.set({ currentPosting: posting });
		}
	}
}

// Gate: require extracted requirements before proceeding
if (!posting || !posting.description) { showState('no-job'); return; }
if (!posting.requirements || !posting.requirements.length) {
	el('error-message').textContent =
		'Couldn\u2019t extract job requirements. Try refreshing the page and reopening the extension.';
	showState('error');
	return;
}
```

Key changes:
- The heuristic fallback block (lines 457–462: `extractFallback`) is removed entirely
- A new requirements gate checks `posting.requirements` is a non-empty array
- If missing, shows the `error` state with a clear message and the existing retry button

- [ ] **Step 2: Manual test — verify extraction still works**

1. Ensure server is running (`claude-candidate server start`)
2. Open a LinkedIn job posting in Chrome
3. Click the extension popup
4. Verify: extraction spinner shows, then assessment renders with requirements

- [ ] **Step 3: Manual test — verify error state on failure**

1. Stop the server (`claude-candidate server stop`)
2. Open a LinkedIn job posting, click extension popup
3. Verify: error message appears ("Couldn't extract job requirements...")
4. Verify: retry button is visible

- [ ] **Step 4: Commit**

```bash
git add extension/popup.js
git commit -m "fix: block assessment when extraction fails instead of silent fallback"
```

---

### Task 5: Extension — fix stale full-assessment rendering across postings

**Files:**
- Modify: `extension/popup.js:494-504`

- [ ] **Step 1: Fix poll to verify assessment ID matches current posting**

In `extension/popup.js`, the poll at line 494 picks up any `fullAssessmentReady` — including one from a previous posting. When the user navigates to a new job before the full assessment finishes, the old result renders over the new page.

Replace lines 494–504:

```javascript
// Poll for completion (if popup stays open) — update in-place
const currentAssessmentId = assessmentId;
const pollInterval = setInterval(async () => {
	const ready = await new Promise(r => {
		chrome.storage.local.get('fullAssessmentReady', res => r(res.fullAssessmentReady || null));
	});
	if (ready && ready.assessmentId === currentAssessmentId && ready.data) {
		clearInterval(pollInterval);
		if (deepBanner) deepBanner.classList.add('hidden');
		renderResults(ready.data);
	}
}, 2000);
```

Key change: `ready.assessmentId === currentAssessmentId` instead of just `ready.assessmentId` (truthy check). This ensures only the current posting's full assessment is rendered.

- [ ] **Step 2: Also clear stale fullAssessmentReady when starting a new assessment**

At the top of the assess flow (just before `sendToBackground({ action: 'assessPartial' ...})`), clear any stale result:

```javascript
chrome.storage.local.remove('fullAssessmentReady');
```

Add this line before the `const partial = await sendToBackground(...)` call (around line 474).

- [ ] **Step 3: Manual test**

1. Open posting A, wait for partial assessment to render
2. Immediately navigate to posting B in the same tab
3. Reopen popup — should show posting B's assessment, not posting A's full assessment

- [ ] **Step 4: Commit**

```bash
git add extension/popup.js
git commit -m "fix: prevent stale full assessment from rendering on different posting"
```

---

### Task 6: Server — auto-tag education requirements missed by extraction

**Files:**
- Modify: `src/claude_candidate/server.py` (post-processing in extract_posting)
- Test: `tests/test_server.py`

- [ ] **Step 1: Write failing test**

In `tests/test_server.py`, add:

```python
class TestEducationAutoTagging:
	"""Requirements mentioning degrees should get education_level set."""

	def test_auto_tag_phd(self):
		from claude_candidate.server import _auto_tag_education
		reqs = [{"description": "PhD in Computer Science or related field", "skill_mapping": ["computer-science"]}]
		_auto_tag_education(reqs)
		assert reqs[0]["education_level"] == "phd"

	def test_auto_tag_masters(self):
		from claude_candidate.server import _auto_tag_education
		reqs = [{"description": "MSc or PhD in Electrical Engineering, Applied Math, or a related field", "skill_mapping": ["electrical-engineering"]}]
		_auto_tag_education(reqs)
		assert reqs[0]["education_level"] == "phd"  # highest mentioned

	def test_auto_tag_bachelors(self):
		from claude_candidate.server import _auto_tag_education
		reqs = [{"description": "Bachelor's degree in Computer Science", "skill_mapping": ["computer-science"]}]
		_auto_tag_education(reqs)
		assert reqs[0]["education_level"] == "bachelor"

	def test_no_false_positive(self):
		from claude_candidate.server import _auto_tag_education
		reqs = [{"description": "5+ years of Python experience", "skill_mapping": ["python"]}]
		_auto_tag_education(reqs)
		assert reqs[0].get("education_level") is None

	def test_skips_already_tagged(self):
		from claude_candidate.server import _auto_tag_education
		reqs = [{"description": "PhD in CS", "skill_mapping": ["computer-science"], "education_level": "master"}]
		_auto_tag_education(reqs)
		assert reqs[0]["education_level"] == "master"  # not overwritten
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestEducationAutoTagging -v`
Expected: FAIL — `_auto_tag_education` doesn't exist yet.

- [ ] **Step 3: Implement `_auto_tag_education`**

In `src/claude_candidate/server.py`, add:

```python
import re

_EDUCATION_PATTERNS: list[tuple[str, re.Pattern]] = [
	("phd", re.compile(r"\b(?:ph\.?d|doctorate|doctoral)\b", re.IGNORECASE)),
	("master", re.compile(r"\b(?:m\.?s\.?c?|master'?s?|m\.?eng)\b", re.IGNORECASE)),
	("bachelor", re.compile(r"\b(?:b\.?s\.?c?|bachelor'?s?|b\.?eng|b\.?a\.?)\b", re.IGNORECASE)),
]

def _auto_tag_education(requirements: list[dict]) -> None:
	"""Set education_level on requirements that mention degrees but weren't tagged by extraction."""
	for req in requirements:
		if req.get("education_level"):
			continue  # already tagged
		desc = req.get("description", "")
		# Find highest degree mentioned
		for level, pattern in _EDUCATION_PATTERNS:
			if pattern.search(desc):
				req["education_level"] = level
				break
```

Then call it in the `extract_posting` endpoint, after `normalize_skill_mappings`:

```python
if "requirements" in parsed and isinstance(parsed["requirements"], list):
	from claude_candidate.requirement_parser import normalize_skill_mappings
	normalize_skill_mappings(parsed["requirements"])
	_auto_tag_education(parsed["requirements"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_server.py::TestEducationAutoTagging -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/server.py tests/test_server.py
git commit -m "fix: auto-tag education requirements when extraction misses education_level"
```

---

### Task 7: Final verification

- [ ] **Step 1: Run full fast test suite**

Run: `.venv/bin/python -m pytest`
Expected: All pass.

- [ ] **Step 2: End-to-end manual test**

1. Restart the server
2. Clear posting cache for a test URL via DB
3. Open a LinkedIn job posting — verify extraction + assessment works
4. Reopen on same posting — verify cache hits (instant load, no "Extracting..." spinner)
5. Open the same posting from a different LinkedIn email link (different tracking params) — verify cache still hits

- [ ] **Step 3: Final commit if any cleanup needed, then push**

```bash
git push origin <branch>
```
