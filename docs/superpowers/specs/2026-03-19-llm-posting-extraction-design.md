# LLM-Based Job Posting Extraction

**Date:** 2026-03-19
**Status:** Approved
**Problem:** CSS selector-based job posting extraction breaks whenever LinkedIn or other boards change their DOM. Maintenance is constant and selectors are already stale.

**Solution:** Replace all board-specific selector logic with a single LLM extraction pipeline. The content script grabs visible page text and sends it to the local server, which uses Claude CLI to parse it into structured job data. Results are cached by URL.

---

## Architecture

```
Browser page → content.js (grabs innerText) → background.js → POST /api/extract-posting → Claude CLI → cache + return
```

No CSS selectors. No board detection. Works on any page.

## Content Script

Replace all board-specific extractors with one function:

```
grabPageText() → { url, title, text, extractedAt }
```

- `text` = `document.body.innerText` (visible text, no hidden elements)
- `title` = `document.title`
- `url` = `window.location.href`

The content script does two things:

1. **On message `extractJobPosting`:** grab text, send to background, background calls server, return result.
2. **Heuristic fallback** (server unavailable): first `<h1>` text as title, largest text block as description.

Auto-extract-on-load caches raw text to `chrome.storage.local`, not a parsed result. Parsing always goes through the server.

### Deleted

- `extractLinkedIn()`, `extractGreenhouse()`, `extractLever()`, `extractIndeed()`, `extractGeneric()`
- `detectBoard()`, `expandLinkedInMore()`
- All CSS selector constants

### Changed

- `manifest.json` content script matches expand to `<all_urls>`
- Note: broader permission triggers a user prompt on extension update

## Server Endpoint

### `POST /api/extract-posting`

**Request:**

```json
{
  "url": "https://linkedin.com/jobs/view/...",
  "title": "Principal Agentic Engineer | LinkedIn",
  "text": "<full visible page text, truncated to 15k chars>"
}
```

**Logic:**

1. Hash URL → check `posting_cache` table in SQLite
2. Cache hit (< 7 days old) → return cached result
3. Cache miss → call `claude --print` with extraction prompt
4. Parse Claude JSON response into `PostingExtraction`
5. Cache result, return it

**Extraction prompt:**

```
Extract the job posting from this web page text. Return JSON only with these fields:
- company: string
- title: string
- description: string (full job description, requirements, qualifications)
- location: string or null
- seniority: string or null (junior/mid/senior/staff/principal/director)
- remote: boolean or null
- salary: string or null

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

7-day TTL checked on read. No background eviction.

**Response:** Structured posting JSON with fields: `company`, `title`, `description`, `url`, `source`, `location`, `seniority`, `remote`, `salary`.

If Claude CLI is unavailable, returns 503.

## Extension Flow

1. Popup opens → check backend health
2. Send `extractJobPosting` to content script
3. Content script grabs raw text, returns to popup via background
4. Background calls `POST /api/extract-posting`
5. Server returns structured posting → proceed to assess
6. Server unavailable → heuristic fallback
7. Heuristic fails → "no-job" state

### Cache Layers

- **Server SQLite** — authoritative, URL hash key, 7-day TTL
- **Extension `chrome.storage.local`** — existing `currentPosting` with 5-minute TTL for instant popup reopens

### background.js

New handler: `handleExtractPosting(rawPageData)` → calls `POST /api/extract-posting`. Existing `handleAssessPartial` unchanged.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Server down | Heuristic fallback, subtle warning in popup |
| Claude CLI unavailable | Server returns 503, extension uses heuristic |
| Non-job page | Claude returns empty fields, popup shows "no-job" |
| Very long page | Text truncated to 15,000 chars before sending |
| Repeat visit | Cache hit, instant response |

## Testing

**Automated (server):**
- Cache miss → Claude CLI called → result cached
- Cache hit → no Claude call
- Cache TTL expired → re-extracts
- Empty/garbage text → empty fields
- Text truncation at 15k chars
- Claude prompt includes title and text
- Malformed Claude response handled gracefully

**Manual (extension):**
- LinkedIn job page
- Greenhouse job page
- Non-job page (graceful no-job state)
- Server down (heuristic fallback)

## Files Changed

**New:**
- None (changes go in existing files)

**Modified:**
- `extension/content.js` — replace all extractors with `grabPageText()` + heuristic fallback
- `extension/background.js` — add `handleExtractPosting` handler
- `extension/popup.js` — wire new extraction flow
- `extension/manifest.json` — expand content script matches to `<all_urls>`
- `src/claude_candidate/server.py` — add `POST /api/extract-posting` endpoint + cache
- `src/claude_candidate/storage.py` — add `posting_cache` table + methods
- `tests/test_server.py` — extraction endpoint tests
