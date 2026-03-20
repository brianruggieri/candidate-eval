# LLM-Based Job Posting Extraction

**Date:** 2026-03-19
**Status:** Approved
**Problem:** CSS selector-based job posting extraction breaks whenever LinkedIn or other boards change their DOM. Maintenance is constant and selectors are already stale.

**Solution:** Replace all board-specific selector logic with a single LLM extraction pipeline. The content script grabs visible page text and sends it to the local server, which uses Claude CLI to parse it into structured job data. Results are cached by URL.

---

## Architecture

```
Browser page → content.js (grabs innerText)
            → popup.js (orchestrator)
            → background.js → POST /api/extract-posting
            → Claude CLI → cache + return
```

No CSS selectors. No board detection. Works on any page.

## Data Flow Contracts

Exact JSON shapes at each handoff:

### 1. Content script → popup (raw page data)

```json
{
  "success": true,
  "pageData": {
    "url": "https://linkedin.com/jobs/view/...",
    "title": "Principal Agentic Engineer - Remote - USA | LinkedIn",
    "text": "<document.body.innerText, max 15000 chars>",
    "extractedAt": 1742400000000
  }
}
```

Note: this replaces the current contract where content script returns a fully parsed `{ posting: { title, company, description, ... } }`. The content script no longer parses — it returns raw text.

### 2. Popup → background (`extractPosting` message)

```json
{
  "action": "extractPosting",
  "payload": {
    "url": "https://linkedin.com/jobs/view/...",
    "title": "Principal Agentic Engineer - Remote - USA | LinkedIn",
    "text": "<page text>"
  }
}
```

### 3. Background → server (`POST /api/extract-posting`)

```json
{
  "url": "https://linkedin.com/jobs/view/...",
  "title": "Principal Agentic Engineer - Remote - USA | LinkedIn",
  "text": "<page text>"
}
```

### 4. Server → background → popup (structured posting)

```json
{
  "company": "FullStack",
  "title": "Principal Agentic Engineer",
  "description": "FullStack is one of the fastest-growing...",
  "url": "https://linkedin.com/jobs/view/...",
  "source": "linkedin",
  "location": "Charleston, WV",
  "seniority": "principal",
  "remote": true,
  "salary": null
}
```

### 5. Popup → background (`assessPartial` message)

Popup maps the extraction result to the existing assessment request shape:

```javascript
{
  action: 'assessPartial',
  payload: {
    description: extraction.description,  // maps description → description
    company: extraction.company,
    title: extraction.title,
    url: extraction.url
  }
}
```

Background maps to server's `AssessRequest` as today: `description` → `posting_text`.

### 6. Heuristic fallback shape (server unavailable)

When the server is down, the content script provides a best-effort extraction with the same field names but only `title` and `description` populated:

```json
{
  "company": "",
  "title": "<first h1 text or document.title>",
  "description": "<largest text block on page>",
  "url": "https://...",
  "source": "heuristic",
  "location": null,
  "seniority": null,
  "remote": null,
  "salary": null
}
```

This is compatible with the assessment pipeline — `company` defaults to empty string (popup can show "Unknown Company"), `description` is populated.

### 7. Extension storage (`chrome.storage.local`)

Key `currentPosting` changes shape. Now stores the structured server response (same as contract #4), not the old content-script-parsed result. The 5-minute TTL check in popup stays the same — it checks `extractedAt` which is added by popup when storing.

```json
{
  "currentPosting": {
    "company": "FullStack",
    "title": "Principal Agentic Engineer",
    "description": "...",
    "url": "...",
    "source": "linkedin",
    "extractedAt": 1742400000000
  }
}
```

## Content Script

Replace all board-specific extractors with one function:

```
grabPageText() → { url, title, text, extractedAt }
```

- `text` = `document.body.innerText` (visible text, no hidden elements), truncated to 15,000 chars from the start
- `title` = `document.title`
- `url` = `window.location.href`

The content script handles two messages:

1. **`extractJobPosting`:** grab raw text, return it. Does NOT call server — popup orchestrates that.
2. **`extractFallback`:** run heuristic extraction (first `<h1>` + largest text block), return a posting-shaped object for offline use.

Auto-extract-on-load caches raw text to `chrome.storage.local` under key `rawPageText` (separate from `currentPosting` which holds the parsed result).

### Deleted

- `extractLinkedIn()`, `extractGreenhouse()`, `extractLever()`, `extractIndeed()`, `extractGeneric()`
- `detectBoard()`, `expandLinkedInMore()`
- `queryText()`, `queryContent()`, `getTextAfterHeading()`
- All CSS selector constants

### Changed

- `manifest.json`: use `activeTab` permission + `chrome.scripting.executeScript` from popup for on-demand injection instead of `<all_urls>` content script matches. This avoids the alarming "can read all your data" permission prompt. Content script match patterns are removed entirely.

## Server Endpoint

### Pydantic Models

```python
class ExtractPostingRequest(BaseModel):
    url: str
    title: str
    text: str

class PostingExtraction(BaseModel):
    company: str
    title: str
    description: str
    url: str
    source: str  # inferred from URL, not from Claude
    location: str | None = None
    seniority: str | None = None
    remote: bool | None = None
    salary: str | None = None
```

### `POST /api/extract-posting`

**Logic:**

1. Truncate `text` to 15,000 chars (server-side, single place to enforce)
2. Hash URL → check `posting_cache` table in SQLite
3. Cache hit where `extracted_at` is < 7 days old (UTC comparison) → return cached result
4. Cache miss or expired → call `call_claude(prompt)` via existing `claude_cli.py` helper (reuses timeout, error handling)
5. Parse Claude JSON response into `PostingExtraction`
6. Infer `source` from URL: `linkedin.com` → `"linkedin"`, `greenhouse.io` → `"greenhouse"`, etc., default `"web"`
7. Cache the result, return it

**Extraction prompt:**

```
Extract the job posting from this web page text. Return ONLY valid JSON with these fields:
- company: string (the hiring company name)
- title: string (the job title)
- description: string (full job description including requirements and qualifications)
- location: string or null
- seniority: string or null (one of: junior, mid, senior, staff, principal, director)
- remote: boolean or null
- salary: string or null

If this page does not contain a job posting, return all fields as null.

Page title: {title}
Page text:
{text}
```

**Cache table:**

```sql
CREATE TABLE IF NOT EXISTS posting_cache (
    url_hash TEXT PRIMARY KEY,
    url TEXT NOT NULL,
    data TEXT NOT NULL,
    extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
);
```

TTL: 7 days. Checked on read by comparing `extracted_at` (UTC) to `datetime('now')` (UTC). Expired entries are deleted on read (opportunistic cleanup). No background eviction.

**Error responses:**
- Claude CLI unavailable → `503 {"detail": "Claude CLI not available for extraction"}`
- Claude returns non-JSON → `502 {"detail": "Extraction failed: invalid response from Claude"}`
- Empty/null extraction (not a job page) → `200` with all fields null

## Extension Flow (step by step)

1. Popup opens → check backend health (existing `checkBackend`)
2. Check `chrome.storage.local` for `currentPosting` with valid 5-minute TTL → if hit, skip to step 7
3. Inject content script into active tab via `chrome.scripting.executeScript`
4. Send `extractJobPosting` to content script → receives `{ success, pageData: { url, title, text } }`
5. Popup sends `extractPosting` to background → background calls `POST /api/extract-posting` → receives structured posting
6. If server call succeeds: store result in `chrome.storage.local` as `currentPosting` with `extractedAt` timestamp
7. If server call fails: popup sends `extractFallback` to content script → receives heuristic posting. Show subtle "offline" indicator.
8. Check `posting.description` — if empty/null, show "no-job" state
9. Proceed to `assessPartial` with the structured posting (existing flow)

### background.js

New handler: `handleExtractPosting(payload)` → calls `POST /api/extract-posting`, returns structured posting.

Existing handlers (`handleAssessPartial`, `handleAssessFull`, etc.) unchanged.

### popup.js

Key change: `initialize()` now has a two-step extraction (get raw text → send to server) instead of the old one-step (content script returns parsed posting).

The `posting.description` check at the gate stays — it now checks the server's structured response instead of the content script's parsed result.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Server down | Heuristic fallback from content script, "offline" indicator in popup |
| Claude CLI unavailable | Server returns 503, extension uses heuristic fallback |
| Non-job page | Claude returns null fields, popup shows "no-job" |
| Very long page | Server truncates to 15,000 chars before sending to Claude |
| Repeat visit (< 5 min) | Extension cache hit, instant |
| Repeat visit (< 7 days) | Server cache hit, fast (no Claude call) |
| Malformed Claude response | Server returns 502, extension uses heuristic fallback |
| Prompt injection in page text | Low risk for personal tool; noted as known limitation |

## Testing

**Automated (server, `test_server.py`):**
- Cache miss → `call_claude` called with correct prompt → result cached
- Cache hit (fresh) → no `call_claude` call, returns cached result
- Cache hit (expired, > 7 days) → re-extracts via Claude
- Empty text → returns null fields
- Text > 15k chars → truncated before Claude call
- Claude returns valid JSON → parsed correctly
- Claude returns malformed response → 502 error
- Claude CLI unavailable → 503 error
- `source` inferred correctly from URL (linkedin.com → "linkedin", etc.)

**Manual (extension):**
- LinkedIn job page → structured extraction
- Greenhouse job page → structured extraction
- Non-job page → graceful "no-job" state
- Server down → heuristic fallback with "offline" indicator
- Repeat visit → instant from cache

## Files Changed

**New:**
- None (changes go in existing files)

**Modified:**
- `extension/content.js` — replace all extractors with `grabPageText()` + heuristic fallback
- `extension/background.js` — add `handleExtractPosting` handler
- `extension/popup.js` — two-step extraction flow, `activeTab` script injection
- `extension/manifest.json` — remove content script match patterns, add `scripting` permission, keep `activeTab`
- `src/claude_candidate/server.py` — add `ExtractPostingRequest`/`PostingExtraction` models, `POST /api/extract-posting` endpoint
- `src/claude_candidate/storage.py` — add `posting_cache` table creation + `cache_posting`/`get_cached_posting`/`delete_expired_postings` methods
- `tests/test_server.py` — extraction endpoint tests
