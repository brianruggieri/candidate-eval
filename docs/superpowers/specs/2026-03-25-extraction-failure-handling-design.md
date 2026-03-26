# Extraction Failure Handling

## Problem

When `/api/extract-posting` fails (CLI error, timeout, malformed response), the extension silently falls through to a heuristic fallback that provides no structured requirements. The server then runs `_extract_basic_requirements()` — a v0.1 keyword scanner that matches generic tech terms from noisy LinkedIn page text (including the candidate's own sidebar skills). This produces confident but completely wrong assessments (e.g., 100% A+ for a C++/Unreal Engine gameplay role).

**Root cause chain:** extraction failure → heuristic fallback (no requirements) → keyword scanner on noisy page text → garbage assessment with no signal of failure.

## Design

### Approach: Extension-side gate (Option A)

Block the assessment and surface a clear error when extraction fails. No assessment shown until extraction succeeds.

### Change 1: Extension — gate on requirements

In `popup.js`, after resolving the posting (line ~465), check that `posting.requirements` is a non-empty array before proceeding to assessment. If missing:

- Show the `error` state with message: "Couldn't extract job requirements. Try refreshing the page and reopening the extension."
- Include the existing retry button (reuses `btn-retry` → `initialize`)
- Do NOT fall through to heuristic fallback for assessment purposes

The heuristic fallback path (lines 457–462) should be removed from the assessment flow. If Claude extraction fails, that's the end — show the error.

### Change 2: Server — delete keyword fallback

In `server.py` `_run_quick_assess()` (line ~316–327):

- When `req.requirements` is null/empty after parsing, return HTTP 422 with `detail: "No requirements provided — extraction required"`
- Delete the import of `_extract_basic_requirements` from `cli.py`
- This is a safety net — the extension gate (Change 1) prevents this path from being hit in normal usage

In `cli.py`:
- Keep `_extract_basic_requirements()` for the CLI `assess` command (it uses Claude-based parsing via a different path), but do NOT export it to the server

### Change 3: Server — add extraction failure logging

In `server.py` `/api/extract-posting` endpoint:

- Log when extraction starts (URL, text length)
- Log Claude CLI errors with the error message
- Log when extraction returns empty/null requirements
- Use Python `logging` module at WARNING level for failures, INFO for success

### Change 4: Server — bump extraction timeout

In `server.py` line 793, increase extraction timeout from 90s to 120s. LinkedIn pages can be 15k chars and some postings are slow to extract. A 503 timeout on a valid posting is a worse UX than waiting an extra 30s.

### Change 5: Normalize LinkedIn URLs for cache keys

In `server.py` `/api/extract-posting`, before computing `url_hash`:

- For LinkedIn URLs (`linkedin.com/jobs/view/`), strip all query parameters. The job ID in the path (`/jobs/view/4385180576/`) is the canonical identifier. Tracking params (`trk=`, `eBP=`, `trackingId=`) change per visit and defeat the cache.
- For non-LinkedIn URLs, keep the full URL as-is.
- Apply normalization to both the hash computation AND the stored `url` field so cache lookups match.

### Out of scope

- Retry logic in the extension (user can click retry manually)
- Stream-json workaround for CLI bug (pinned to 2.1.81, CLI bug is tracked at anthropics/claude-code#38774)
- Extraction prompt improvements

## Files Changed

| File | Change |
|------|--------|
| `extension/popup.js` | Gate on `posting.requirements` before calling assess |
| `src/claude_candidate/server.py` | Delete `_extract_basic_requirements` import; return 422 on empty requirements; add logging; bump timeout; normalize LinkedIn URLs for cache |

## Testing

- Fast tests: Add a test in `test_server.py` that POSTs to `/api/assess/partial` with `requirements: null` and expects 422
- Manual: Open extension on a LinkedIn posting, verify extraction succeeds and assessment renders. Then simulate failure (stop server, verify error state shows)
