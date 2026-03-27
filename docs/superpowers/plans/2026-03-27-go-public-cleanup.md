# Go-Public Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clean up the repo for public visibility — remove PII, gitignore sensitive test data, de-platform the extension from LinkedIn-specific references, and update stale docs.

**Architecture:** Three streams of work: (1) gitignore golden set + anonymize PII in fixtures, (2) de-platform extension to be job-board-agnostic, (3) update README/ARCHITECTURE/CLAUDE.md to reflect v0.8.2 and generic framing. All changes are to the current tree — no git history rewriting.

**Tech Stack:** Git, Chrome Extension (MV3), Python, FastAPI

---

### Task 1: Gitignore Golden Set Postings and Calibration Data

**Files:**
- Modify: `.gitignore`
- Remove from git (keep on disk): `tests/golden_set/postings/`, `tests/golden_set/calibration.json`

The golden set postings contain full verbatim job descriptions from real companies. The calibration.json contains real name and education details. Both stay local for benchmarking but should not be in the public repo. The benchmark script, expected_grades.json, and benchmark_history.jsonl stay public — they show the engineering without exposing the data.

- [ ] **Step 1: Add golden set exclusions to .gitignore**

Add to the end of `.gitignore`:

```
# Golden set — postings + calibration stay local, benchmark infra stays public
tests/golden_set/postings/
tests/golden_set/calibration.json
```

- [ ] **Step 2: Remove tracked files from git index (keep on disk)**

```bash
git rm --cached -r tests/golden_set/postings/
git rm --cached tests/golden_set/calibration.json
```

Expected: `rm 'tests/golden_set/postings/adobe-senior-...'` etc. (47 files + 1 calibration file removed from index). Files remain on disk.

- [ ] **Step 3: Verify files still exist locally**

```bash
ls tests/golden_set/postings/ | wc -l
cat tests/golden_set/calibration.json | head -3
```

Expected: 47 postings still on disk, calibration.json still readable.

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "chore: gitignore golden set postings and calibration data for public repo"
```

---

### Task 2: Remove Committed Binary Artifacts

**Files:**
- Remove from git: any `fit-page-*.png` files, any `.DS_Store` files

These are already in `.gitignore` but were committed before the rules existed.

- [ ] **Step 1: Check for tracked artifacts**

```bash
git ls-files '*.png' '.DS_Store' '*/.DS_Store' 'fit-page-*.png'
```

- [ ] **Step 2: Remove from git index**

```bash
git rm --cached -r --ignore-unmatch '*.DS_Store' 'fit-page-*.png'
```

If nothing is tracked, skip to the next task.

- [ ] **Step 3: Commit**

```bash
git commit -m "chore: remove tracked .DS_Store and PNG artifacts"
```

---

### Task 3: Anonymize PII in Test Fixtures

**Files:**
- Modify: `tests/fixtures/sample_resume_profile.json` (line 6: real name)
- Modify: `tests/fixtures/sample_candidate_profile.json` (lines with `brianruggieri` GitHub URLs)
- Modify: `tests/test_site_renderer.py` (lines 361, 485, 535: GitHub URL assertions)
- Modify: `tests/test_session_scanner.py` (lines 132, 135, 139: path extraction tests)
- Modify: `tests/test_repo_scanner.py` (lines 201, 204: real GitHub repo reference)

Replace real name and GitHub username in test fixtures with generic equivalents. Keep the test logic identical.

- [ ] **Step 1: Anonymize sample_resume_profile.json**

In `tests/fixtures/sample_resume_profile.json`, change:

```json
"name": "Brian Ruggieri",
```

to:

```json
"name": "Alex Developer",
```

- [ ] **Step 2: Anonymize sample_candidate_profile.json**

In `tests/fixtures/sample_candidate_profile.json`, replace all occurrences of `brianruggieri` with `alexdev` in the `public_repo_url` fields:

```
"public_repo_url": "https://github.com/brianruggieri/obsidian-daily-digest"
→ "public_repo_url": "https://github.com/alexdev/obsidian-daily-digest"
```

Same for `teamchat`, `claude-code-pulse`, `blog-a-claude`.

- [ ] **Step 3: Update test_site_renderer.py assertions**

In `tests/test_site_renderer.py`, replace all occurrences of:

```python
"https://github.com/brianruggieri/claude-candidate"
```

with:

```python
"https://github.com/alexdev/claude-candidate"
```

(Lines 361, 485, 535)

- [ ] **Step 4: Update test_session_scanner.py path tests**

In `tests/test_session_scanner.py`, replace:

```python
assert _extract_display_name("-Users-brianruggieri-git-candidate-eval") == "candidate-eval"
```

with:

```python
assert _extract_display_name("-Users-alexdev-git-candidate-eval") == "candidate-eval"
```

And similarly for lines 135 and 139 — replace `brianruggieri` with `alexdev`.

- [ ] **Step 5: Update test_repo_scanner.py**

In `tests/test_repo_scanner.py`, these tests at lines 201-204 call `scan_github_repo("brianruggieri/claude-code-pulse")` which makes a real network call. Replace with:

```python
evidence = scan_github_repo("alexdev/claude-code-pulse")
```

and:

```python
assert evidence.url == "https://github.com/alexdev/claude-code-pulse"
```

**Important:** This test may be marked `@pytest.mark.slow` since it calls the GitHub API. Check if it uses a mock or makes real network calls. If it calls real GitHub, it will fail with "alexdev" since that repo doesn't exist. In that case, this test should be skipped or mocked. Read the test first to determine the right approach.

- [ ] **Step 6: Run fast tests to verify nothing broke**

```bash
.venv/bin/python -m pytest -x -q 2>&1 | tail -20
```

Expected: All fast tests pass.

- [ ] **Step 7: Commit**

```bash
git add tests/fixtures/sample_resume_profile.json tests/fixtures/sample_candidate_profile.json tests/test_site_renderer.py tests/test_session_scanner.py tests/test_repo_scanner.py
git commit -m "chore: anonymize PII in test fixtures for public repo"
```

---

### Task 4: De-Platform Extension — Manifest and Host Permissions

**Files:**
- Modify: `extension/manifest.json`

The extension currently has `host_permissions` limited to `localhost` and `linkedin.com`. Since we use `chrome.scripting.executeScript` with the `activeTab` permission (which grants access to the current tab when the user clicks the extension), we don't need broad host permissions for content script injection. We only need `localhost` for the API server. The `activeTab` permission already covers injecting the content script into whatever tab the user is viewing.

- [ ] **Step 1: Remove LinkedIn-specific host permission**

In `extension/manifest.json`, change line 7 from:

```json
"host_permissions": ["http://localhost:7429/*", "https://www.linkedin.com/*"],
```

to:

```json
"host_permissions": ["http://localhost:7429/*"],
```

The `activeTab` permission (already in `permissions` array) handles content script injection on the current tab regardless of domain.

- [ ] **Step 2: Verify manifest is valid JSON**

```bash
python3 -c "import json; json.load(open('extension/manifest.json'))"
```

Expected: No error.

- [ ] **Step 3: Commit**

```bash
git add extension/manifest.json
git commit -m "feat: remove platform-specific host permissions from extension manifest"
```

---

### Task 5: De-Platform Extension — Batch Assess URL Filter

**Files:**
- Modify: `extension/background.js` (lines 172-186)

The batch assess function currently only finds LinkedIn job tabs. It should find tabs on any supported job board, or better yet, any tab the user has open (since the LLM extraction handles any page).

- [ ] **Step 1: Broaden the batch assess tab filter**

In `extension/background.js`, replace the handleBatchAssess function's tab filtering logic (lines 176-186):

```javascript
/**
 * Batch assess: find all open job posting tabs, extract + assess each one.
 * Sends progress updates via chrome.storage.local.
 */
async function handleBatchAssess() {
	// Find tabs that look like job postings on any board
	const allTabs = await chrome.tabs.query({});
	console.log(`[batch] Found ${allTabs.length} total tabs`);
	const JOB_URL_PATTERNS = [
		/linkedin\.com\/jobs\/view\//,
		/boards\.greenhouse\.io\/.+\/jobs\//,
		/jobs\.lever\.co\//,
		/indeed\.com\/viewjob/,
		/careers\.|\/careers\//,
		/jobs\.|\/jobs\//,
		/ashbyhq\.com\/.+\/jobs\//,
		/apply\.workable\.com\//,
	];
	const jobTabs = allTabs.filter(t =>
		t.url && JOB_URL_PATTERNS.some(p => p.test(t.url))
	);
	console.log(`[batch] Found ${jobTabs.length} job posting tabs`);

	if (jobTabs.length === 0) {
		return { success: false, error: 'No job posting tabs found. Open some job postings first.' };
	}
```

This replaces the LinkedIn-only regex with patterns that match any common job board. The `/careers/` and `/jobs/` patterns also catch company career pages.

- [ ] **Step 2: Commit**

```bash
git add extension/background.js
git commit -m "feat: batch assess supports any job board, not just LinkedIn"
```

---

### Task 6: De-Platform Extension — UI Text

**Files:**
- Modify: `extension/popup.html` (line 46)
- Modify: `extension/dashboard.html` (line 152)
- Modify: `extension/content.js` (line 12: comment only)

- [ ] **Step 1: Update popup.html help text**

In `extension/popup.html`, change line 46 from:

```html
<p class="muted">Navigate to a job listing on LinkedIn, Greenhouse, Lever, or Indeed.</p>
```

to:

```html
<p class="muted">Navigate to any online job listing to get started.</p>
```

- [ ] **Step 2: Update dashboard.html empty state text**

In `extension/dashboard.html`, change line 152 from:

```html
<p>Open LinkedIn job posting tabs and click "Assess All Open Job Tabs" in the extension popup.</p>
```

to:

```html
<p>Open job posting tabs and click "Assess All Open Job Tabs" in the extension popup.</p>
```

- [ ] **Step 3: Update content.js comment**

In `extension/content.js`, change line 12 from:

```javascript
// LinkedIn "...more" buttons that expand truncated job descriptions
```

to:

```javascript
// "Show more" buttons that expand truncated job descriptions
```

- [ ] **Step 4: Commit**

```bash
git add extension/popup.html extension/dashboard.html extension/content.js
git commit -m "chore: remove platform-specific references from extension UI"
```

---

### Task 7: De-Platform Extension — Test Fixtures

**Files:**
- Modify: `extension/tests/chrome-mock.js` (line 40)
- Modify: `extension/tests/storage.test.js` (lines 16, 52)

The test data uses LinkedIn URLs as examples. Replace with generic URLs.

- [ ] **Step 1: Update chrome-mock.js**

In `extension/tests/chrome-mock.js`, change line 40 from:

```javascript
const tabs = [{ url: 'https://www.linkedin.com/jobs/view/12345' }];
```

to:

```javascript
const tabs = [{ url: 'https://jobs.example.com/posting/12345' }];
```

- [ ] **Step 2: Update storage.test.js**

In `extension/tests/storage.test.js`, change line 16 from:

```javascript
const url = 'https://linkedin.com/jobs/view/123?utm_source=google&trk=abc';
```

to:

```javascript
const url = 'https://example.com/jobs/view/123?utm_source=google&trk=abc';
```

And change line 17 from:

```javascript
expect(normalizeUrl(url)).toBe('https://linkedin.com/jobs/view/123');
```

to:

```javascript
expect(normalizeUrl(url)).toBe('https://example.com/jobs/view/123');
```

And change line 52 from:

```javascript
const url = 'https://linkedin.com/jobs/view/123?utm_source=google';
```

to:

```javascript
const url = 'https://example.com/jobs/view/123?utm_source=google';
```

- [ ] **Step 3: Run extension tests**

```bash
cd extension && source ~/.nvm/nvm.sh && nvm use && npx vitest run 2>&1 | tail -20
```

Expected: All tests pass.

- [ ] **Step 4: Commit**

```bash
git add extension/tests/chrome-mock.js extension/tests/storage.test.js
git commit -m "chore: use generic URLs in extension test fixtures"
```

---

### Task 8: De-Platform Server — Source Inference and Test Data

**Files:**
- Modify: `src/claude_candidate/server.py` (lines 901-911: `_infer_source`)
- Modify: `tests/test_server.py` (lines 1134-1152, 1369-1397)
- Modify: `tests/test_generator.py` (line 86)
- Modify: `tests/test_site_renderer.py` (line 58)
- Modify: `tests/test_proof_generator.py` (line 40)

The `_infer_source` function is fine — it detects URL sources generically. Keep it. But rename the test and update test data to not lead with LinkedIn.

- [ ] **Step 1: Rename LinkedIn-specific test in test_server.py**

In `tests/test_server.py`, change the test name and docstring at line 1369 from:

```python
async def test_linkedin_tracking_params_normalized(self, client: AsyncClient):
	"""Same LinkedIn job with different tracking params should hit cache."""
	url_base = "https://www.linkedin.com/jobs/view/4385180576/"
	url_with_params = url_base + "?trk=eml-email_job_alert&eBP=abc123&trackingId=xyz"
```

to:

```python
async def test_tracking_params_normalized(self, client: AsyncClient):
	"""Same job posting with different tracking params should hit cache."""
	url_base = "https://www.linkedin.com/jobs/view/4385180576/"
	url_with_params = url_base + "?trk=eml-email_job_alert&eBP=abc123&trackingId=xyz"
```

Keep the actual URL (it's testing URL normalization — the URL content doesn't matter for platform association, and the `_infer_source` function needs to work with real patterns).

- [ ] **Step 2: Update source= in test fixtures**

In `tests/test_generator.py` line 86, `tests/test_site_renderer.py` line 58, and `tests/test_proof_generator.py` line 40, change:

```python
source="linkedin",
```

to:

```python
source="web",
```

These are test fixtures where the source value doesn't matter to the test logic — it's just a field being passed through. Using "web" is more generic.

- [ ] **Step 3: Run fast tests**

```bash
.venv/bin/python -m pytest -x -q 2>&1 | tail -20
```

Expected: All fast tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/claude_candidate/server.py tests/test_server.py tests/test_generator.py tests/test_site_renderer.py tests/test_proof_generator.py
git commit -m "chore: de-platform test names and fixture source fields"
```

---

### Task 9: Update README.md

**Files:**
- Modify: `README.md`

The README says v0.5, references LinkedIn, and has stale metrics.

- [ ] **Step 1: Update the "What It Does" bullet**

Change line 15 from:

```markdown
- **Runs as a browser extension** — Chrome extension assesses LinkedIn postings in real-time via a local FastAPI server.
```

to:

```markdown
- **Runs as a browser extension** — Chrome extension assesses job postings in real-time from any job board via a local FastAPI server.
```

- [ ] **Step 2: Update the "By the Numbers" table**

Change lines 46-51 from:

```markdown
| Metric | Value |
|--------|-------|
| Test coverage | Fully tested |
| Canonical skills in taxonomy | 104 |
| Sessions scanned (author) | 2,300+ |
```

to:

```markdown
| Metric | Value |
|--------|-------|
| Tests | 1,343 (fast: ~7s, full: ~5min) |
| Benchmark accuracy | 47/47 postings within 1 grade |
| Canonical skills in taxonomy | 104 |
| Sessions scanned (author) | 2,300+ |
```

- [ ] **Step 3: Update the daily-driver workflow line**

Change line 81 from:

```markdown
For the daily-driver workflow: run `claude-candidate server start` and use the Chrome extension to assess LinkedIn postings in-browser.
```

to:

```markdown
For the daily-driver workflow: run `claude-candidate server start` and use the Chrome extension to assess job postings in-browser.
```

- [ ] **Step 4: Update project status**

Change lines 87-88 from:

```markdown
**v0.5** — Active development. Core pipeline stable. v0.5 adds eligibility filters, adoption velocity scoring, and session compaction.
```

to:

```markdown
**v0.8.2** — Core pipeline stable. Dual evidence model (resume + repos), 104-skill taxonomy with fuzzy matching, eligibility gates, confidence scoring, and Chrome extension for real-time assessment.
```

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "docs: update README to v0.8.2, remove platform-specific references"
```

---

### Task 10: Update CLAUDE.md and ARCHITECTURE.md

**Files:**
- Modify: `CLAUDE.md` (lines 61, 111)
- Modify: `ARCHITECTURE.md` (check for stale version references)

- [ ] **Step 1: Update CLAUDE.md golden set reference**

In `CLAUDE.md`, change line 61 from:

```markdown
| `tests/golden_set/postings/*.json` | 24 real LinkedIn postings for accuracy benchmarking |
```

to:

```markdown
| `tests/golden_set/postings/*.json` | 47 real job postings for accuracy benchmarking (gitignored) |
```

- [ ] **Step 2: Update CLAUDE.md extension description**

In `CLAUDE.md`, change line 111 from:

```markdown
The `extension/` directory contains a Chrome MV3 extension that integrates with the FastAPI server for real-time job posting assessment on LinkedIn.
```

to:

```markdown
The `extension/` directory contains a Chrome MV3 extension that integrates with the FastAPI server for real-time job posting assessment on any job board.
```

- [ ] **Step 3: Scan ARCHITECTURE.md for stale version references**

Read the full ARCHITECTURE.md and check if the version header (line 1: "v0.8.2") is already correct. If it references v0.5.0 anywhere else, update to v0.8.2. Check for any LinkedIn-specific references.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md ARCHITECTURE.md
git commit -m "docs: update CLAUDE.md and ARCHITECTURE.md for public repo"
```

---

### Task 11: Commit Uncommitted Files

**Files:**
- Stage: `tests/golden_set/benchmark_history.jsonl` (modified, unstaged)
- Decide: `docs/superpowers/plans/2026-03-27-v08-phase3-polish.md` (untracked)

- [ ] **Step 1: Commit benchmark_history.jsonl**

```bash
git add tests/golden_set/benchmark_history.jsonl
git commit -m "chore: update benchmark history with latest accuracy run"
```

- [ ] **Step 2: Decide on the untracked plan file**

The file `docs/superpowers/plans/2026-03-27-v08-phase3-polish.md` is a superpowers plan from the v0.8 Phase 3 work. Other plan files are committed in `docs/superpowers/plans/`. Commit it for consistency:

```bash
git add docs/superpowers/plans/2026-03-27-v08-phase3-polish.md
git commit -m "docs: add v0.8 phase 3 polish plan"
```

---

### Task 12: Clean Up Worktree

**Files:** None (git operations only)

- [ ] **Step 1: Check worktree status**

```bash
git worktree list
```

- [ ] **Step 2: Remove stale worktree if present**

If `.worktrees/feat-v08-phase3-polish/` exists:

```bash
git worktree remove .worktrees/feat-v08-phase3-polish
git worktree prune
```

If the branch `feat/v08-phase3-polish` has been merged to main:

```bash
git branch -d feat/v08-phase3-polish
```

- [ ] **Step 3: Verify clean state**

```bash
git worktree list
git branch --merged main
```

Expected: Only the main worktree and the current feature branch.

---

### Task 13: Final Verification

- [ ] **Step 1: Run full fast test suite**

```bash
.venv/bin/python -m pytest -x -q 2>&1 | tail -20
```

Expected: All tests pass.

- [ ] **Step 2: Run extension tests**

```bash
cd extension && source ~/.nvm/nvm.sh && nvm use && npx vitest run 2>&1 | tail -20
```

Expected: All tests pass.

- [ ] **Step 3: Verify no PII in tracked files**

```bash
git grep -i "Brian Ruggieri" -- ':!docs/superpowers/' ':!.claude/'
```

Expected: No matches (docs/superpowers plans are internal dev history, acceptable).

- [ ] **Step 4: Verify golden set postings are not tracked**

```bash
git ls-files tests/golden_set/postings/
```

Expected: Empty output.

- [ ] **Step 5: Verify no platform-specific references in extension**

```bash
grep -ri "linkedin" extension/ --include='*.js' --include='*.html' --include='*.json' | grep -v node_modules
```

Expected: Only the URL patterns inside `JOB_URL_PATTERNS` array in background.js (these are generic URL matchers, not branding). No UI text or error messages should mention LinkedIn.

---

## Summary of Changes

| Area | What changes | What stays |
|------|-------------|------------|
| Golden set | Postings + calibration gitignored | benchmark_accuracy.py, expected_grades.json, benchmark_history.jsonl |
| Extension manifest | LinkedIn host_permission removed | activeTab handles all domains |
| Extension batch assess | Matches any job board URL pattern | Same extraction + assessment flow |
| Extension UI | Generic "any job listing" text | All functionality unchanged |
| Test fixtures | Generic URLs, anonymized names | Same test logic and assertions |
| Server | No changes to _infer_source | Source detection still works |
| README | v0.8.2, real test count, generic framing | Architecture, pipeline docs |
| Tracked artifacts | .DS_Store, PNGs removed | Everything else |
