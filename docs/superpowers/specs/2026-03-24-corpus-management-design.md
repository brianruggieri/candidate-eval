# Corpus Management Design

**Date:** 2026-03-24
**Branch:** feat/corpus-management
**Status:** Approved

## Problem

The benchmark golden set has 24 human-verified postings. That's enough for basic accuracy checks but too narrow to catch edge cases in skill resolution, seniority detection, and requirement parsing. More corpus coverage is needed, but manually labeling every new posting is impractical.

The Chrome extension already extracts and assesses every job posting browsed — that data sits in `assessments.db` unused for testing. The gap is a pipeline to promote those cached postings into a regression corpus and run regression detection on every code change.

## Solution

A two-tier corpus:

- **`tests/golden_set/`** — existing, human-verified grades. Used for accuracy measurement. Unchanged.
- **`tests/regression_corpus/`** — new, auto-graded from `assessments.db`. Used for regression detection only.

A `corpus` CLI command group manages export, promotion, removal, and listing. The existing benchmark script gains `--tier` and `--data-dir` flags.

## Directory Structure

```
tests/
  golden_set/               # existing — human-verified
    postings/
    expected_grades.json
    benchmark_accuracy.py
    benchmark_history.jsonl

  regression_corpus/        # new — auto-graded
    postings/               # same JSON format as golden_set/postings/
    expected_grades.json    # nested format (see Data Formats)
    benchmark_history.jsonl # separate history — never mixed with golden set
```

## CLI Commands

All under the `corpus` group: `claude-candidate corpus <subcommand>`.

### `corpus export`

```
claude-candidate corpus export [--limit N] [--db PATH] [--since DAYS]
```

Reads the posting cache from `assessments.db`. For each cached posting that has an associated assessment:

1. Generates a slug filename (see Slug Generation below)
2. Writes posting JSON to `tests/regression_corpus/postings/`
3. Appends to `tests/regression_corpus/expected_grades.json` with grade, source, assessment_id, url_hash, exported_at

**Slug generation:** Lowercase company and title, replace spaces and non-alphanumeric characters with hyphens, collapse consecutive hyphens, truncate company to 20 chars and title to 40 chars. The date is the export date (today). Example: `"Stripe"` + `"Senior Software Engineer"` exported on 2026-03-24 → `stripe-senior-software-engineer-2026-03-24`.

**Slug collision tiebreaker:** If that slug already exists in `regression_corpus/expected_grades.json` for a different URL hash, append a 6-char prefix of the URL hash: `stripe-senior-software-engineer-2026-03-24-a1b2c3`. If that also collides (extremely unlikely), append a counter: `-2`, `-3`, etc.

**Deduplication:** Before writing, build a set of `url_hash` values already present in `regression_corpus/expected_grades.json`. If the current posting's URL hash is in that set, skip silently and print a skip message. This check requires only reading `expected_grades.json`, not scanning posting files.

**`--since DAYS` filter:** Includes postings where `cached_at > (now - N * 86400 seconds)` — exclusive lower bound. Postings with `NULL` `cached_at` are excluded. Without `--since`, all postings with a valid assessment are exported.

**`--limit N`:** Caps total postings exported. Applied after `--since` filter, newest first by `cached_at`.

**Initial state:** Creates `tests/regression_corpus/postings/` and initialises `tests/regression_corpus/expected_grades.json` as `{}` if they do not exist.

### `corpus promote <posting_id>`

```
claude-candidate corpus promote <posting_id>
```

`posting_id` is the filename stem (e.g. `stripe-senior-software-engineer-2026-03-24`). It is both the filename stem in `regression_corpus/postings/` and the key in `regression_corpus/expected_grades.json`. `corpus list` shows available IDs. Does not query `assessments.db` at promotion time.

Interactive workflow:

1. Reads `regression_corpus/postings/<posting_id>.json`. Errors if file is missing.
2. Reads the `grade` field from `regression_corpus/expected_grades.json[posting_id]`. Errors if the grades entry is missing (message: "grades entry not found — run `corpus remove <posting_id>` to clean up orphaned file").
3. Shows summary: company, title, grade from step 2, first 300 chars of description.
4. Prompts for a human grade: `A+/A/A-/B+/B/B-/C+/C/C-/D+/D/F`. Re-prompts on invalid input. If stdin is exhausted without a valid grade (non-TTY / piped input), raises `click.Abort()` and exits non-zero.
5. Errors if `posting_id` already exists as a key in `golden_set/expected_grades.json` — prevents silent overwrite.
6. Copies posting JSON to `golden_set/postings/<posting_id>.json`.
7. Appends `{"<posting_id>": "<grade>"}` to `golden_set/expected_grades.json` — **flat format, no nested fields** (golden set format is unchanged).
8. Removes the `posting_id` key from `regression_corpus/expected_grades.json`.
9. Deletes `regression_corpus/postings/<posting_id>.json`.

**Atomicity:** Steps 6–9 are not transactional. If the process fails after step 6 but before step 9, the posting exists in both tiers. Recovery: run `corpus remove <posting_id>` to clean up the regression side.

### `corpus remove <posting_id>`

```
claude-candidate corpus remove <posting_id>
```

Deletes whatever exists for `posting_id` in the regression corpus:

- If `regression_corpus/postings/<posting_id>.json` exists, deletes it.
- If `regression_corpus/expected_grades.json[posting_id]` exists, removes the entry.
- If only one of the two exists (partial state), deletes what is present and prints a warning about the missing counterpart.
- If neither exists, prints "Not found in regression corpus" and exits cleanly (no error).

### `corpus list`

```
claude-candidate corpus list
```

Reads `regression_corpus/expected_grades.json`. For each entry, reads the corresponding posting JSON to get `company` and `title`. Prints:

```
posting_id                                   | company  | title                    | grade | exported_at
stripe-senior-software-engineer-2026-03-24   | Stripe   | Senior Software Engineer | B+    | 2026-03-24 14:32
```

`exported_at` is displayed as `YYYY-MM-DD HH:MM`. If the posting JSON file is missing, prints `[file missing]` for company and title.

## Data Formats

### `regression_corpus/expected_grades.json`

```json
{
  "stripe-senior-software-engineer-2026-03-24": {
    "grade": "B+",
    "source": "auto",
    "assessment_id": "abc123def456",
    "url_hash": "d4e5f6a1b2c3",
    "exported_at": "2026-03-24T14:32:00"
  }
}
```

The `url_hash` field (first 16 chars of SHA-256 of the posting URL) is stored here for O(1) deduplication on subsequent exports.

### Posting JSON

Same schema as `tests/golden_set/postings/*.json`. Fields: `company`, `title`, `description`, `url`, `requirements` (array of `QuickRequirement`-compatible dicts), `location`, `seniority`, `remote`, `salary`.

### `golden_set/expected_grades.json` (flat format — unchanged)

```json
{
  "stripe-senior-software-engineer-2026-03-24": "B+"
}
```

`corpus promote` writes in this exact format. No nested fields are ever written to `golden_set/expected_grades.json`.

## Benchmark Changes

`tests/golden_set/benchmark_accuracy.py` gains two optional flags:

| Flag | Default | Purpose |
|---|---|---|
| `--tier` | `golden` | `golden`, `regression`, or `all` |
| `--data-dir PATH` | `~/.claude-candidate/` | Override merged profile directory (used by tests to inject fixture profiles) |

**`--tier all` writes to both history files independently:** the golden result is appended to `golden_set/benchmark_history.jsonl` and the regression result is appended to `regression_corpus/benchmark_history.jsonl`. Console output shows both sequentially. Combined output schema:

```json
{
  "golden": { "<existing accuracy output schema>" },
  "regression": { "<stability output schema>" }
}
```

When `regression_corpus/expected_grades.json` is absent or empty:
```json
{"tier": "regression", "total": 0, "stable": 0, "regressions": 0, "improvements": 0, "stability_pct": 100.0, "changed": []}
```

### Regression tier output

Reports **stability**, not accuracy:

```json
{
  "tier": "regression",
  "total": 47,
  "stable": 45,
  "regressions": 1,
  "improvements": 1,
  "stability_pct": 95.7,
  "changed": [
    {"posting_id": "openai-research-2026-03-20", "stored_grade": "B", "current_grade": "C+", "direction": "regression"},
    {"posting_id": "anthropic-infra-2026-03-18", "stored_grade": "A", "current_grade": "A+", "direction": "improvement"}
  ]
}
```

No `"accuracy"` key is ever present in regression output.

**Grade shift threshold:** Any grade change is flagged. Canonical ordered scale (12 grades):

```
A+  A  A-  B+  B  B-  C+  C  C-  D+  D  F
 0   1   2   3  4   5   6  7   8   9  10  11
```

Flagged when `abs(current_index - stored_index) >= 1`. `D-` is not a valid grade.

Regression runs append to `tests/regression_corpus/benchmark_history.jsonl` only. `--tier all` appends one entry to each respective `.jsonl` file.

## Storage Layer

**`list_cached_postings` (new method on `AssessmentStore`):**

```sql
SELECT url, url_hash, data, cached_at FROM posting_cache
[WHERE cached_at > :since]
ORDER BY cached_at DESC
[LIMIT :limit]
```

**`corpus export` join logic (Python-side, not SQL):**

1. Call `list_cached_postings(since=..., limit=...)` to get posting rows
2. For each posting row, call `list_assessments()` filtered by `posting_url` — or do a single `list_assessments()` call upfront and build a `{url: assessment}` dict
3. If multiple assessments exist for a URL, use the one with the latest `assessed_at`
4. Skip postings with no matching assessment

**Schema migration:** `cached_at` is added to `posting_cache` via `AssessmentStore.initialize()`, the existing migration hook. Migration uses `ALTER TABLE posting_cache ADD COLUMN cached_at TEXT` wrapped in a `try/except` for `OperationalError: duplicate column` (SQLite's idiomatic idempotent migration pattern). Pre-migration rows have `cached_at = NULL` and are excluded from `--since` filtering.

## Tests

New file: `tests/test_corpus_cli.py`. All tests are fast tier (no Claude CLI calls).

| Test | What it covers |
|---|---|
| `test_export_writes_posting_json` | Seeds DB with fixture posting + assessment; asserts JSON written to regression_corpus/postings/ with correct fields |
| `test_export_writes_expected_grades` | Verifies grade, source, assessment_id, url_hash, exported_at in expected_grades.json |
| `test_export_deduplicates_by_url_hash` | Export same URL twice → one file; second run is a no-op (url_hash already in expected_grades.json) |
| `test_export_since_filter` | Two postings: one cached 1 day ago, one 10 days ago; `--since 3` exports only the recent one |
| `test_export_since_skips_null_cached_at` | Pre-migration row with NULL cached_at is excluded when --since is used |
| `test_remove_deletes_posting_and_grade_entry` | Export then remove → both file and grades entry gone |
| `test_remove_partial_state` | Grades entry exists but file is missing → remove deletes grades entry, prints warning, exits cleanly |
| `test_remove_missing_is_noop` | `corpus remove` on nonexistent posting_id exits cleanly with "Not found" message |
| `test_promote_moves_to_golden_set` | Export, promote with "B+" → removed from regression_corpus/; posting JSON in golden_set/postings/; golden_set/expected_grades.json has flat `{"<id>": "B+"}` |
| `test_promote_errors_if_already_in_golden` | Promote a posting_id already in golden_set/expected_grades.json → error before any writes |
| `test_promote_rejects_invalid_grade` | Pipe invalid input then valid grade via CliRunner; assert re-prompt, then success |
| `test_promote_aborts_on_eof` | CliRunner with only invalid input exhausted → Click.Abort, non-zero exit |
| `test_promote_errors_on_missing_grade_entry` | Posting file exists but grades entry is missing → error with cleanup hint |
| `test_list_shows_corpus_contents` | Export two postings; list output has both rows with company+title from posting JSON |
| `test_list_missing_file_shows_placeholder` | Grades entry exists but JSON file is missing → list shows `[file missing]` |
| `test_regression_tier_flags_grade_shifts` | Writes regression_corpus/ fixture: posting JSON requiring Python (must_have), expected_grades with `grade: "B+"`; passes `--data-dir` pointing to a tmp fixture dir containing a merged profile with no Python skill (forces low score → C+ or below); asserts `changed` list has one regression entry. Real QuickMatchEngine, no mocks. |
| `test_regression_tier_no_accuracy_metric` | Regression output JSON has no `"accuracy"` key |
| `test_regression_history_separate_from_golden` | `--tier regression` appends to regression_corpus/benchmark_history.jsonl only; golden_set/benchmark_history.jsonl unchanged |
| `test_regression_tier_all_empty_corpus` | `--tier all` with empty regression_corpus → regression section has total=0, stability_pct=100.0 |

## Out of Scope

- URL fetching / web scraping — corpus is populated only from the extension's existing cache
- Auto-labeling with Claude — grades come from `QuickMatchEngine`, not LLM judgment
- CI integration — regression benchmark is a manual developer tool, not a pytest check
- UI for corpus management — CLI only
