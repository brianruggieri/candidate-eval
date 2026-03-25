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
- **`tests/regression_corpus/`** — new, auto-graded from `assessments.db`. Used for regression detection only. Grade source is always `"auto"`.

A `corpus` CLI command group manages export, promotion, removal, and listing. The existing benchmark script gains a `--tier` flag.

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
    expected_grades.json    # grade + source: "auto" + assessment_id + exported_at
    benchmark_history.jsonl # separate history — never mixed with golden set
```

## CLI Commands

All under the `corpus` group: `claude-candidate corpus <subcommand>`.

### `corpus export`

```
claude-candidate corpus export [--limit N] [--db PATH] [--since DAYS]
```

Reads the posting cache from `assessments.db`. For each cached posting that has an associated assessment:

1. Generates a slug filename: `{company}-{title-kebab}-{YYYY-MM-DD}.json`
2. Writes posting JSON to `tests/regression_corpus/postings/`
3. Appends to `tests/regression_corpus/expected_grades.json` with:
   - `grade`: taken from stored `overall_grade`
   - `source`: `"auto"`
   - `assessment_id`: the stored assessment ID
   - `exported_at`: ISO timestamp

Deduplication by URL hash — exporting the same posting twice is a no-op. `--since DAYS` filters to postings cached within the last N days. `--limit N` caps the export batch size.

### `corpus promote <posting_id>`

```
claude-candidate corpus promote <posting_id>
```

Interactive workflow:

1. Shows a summary of the posting (company, title, overall_score, skill match, gaps)
2. Prompts for a human grade: `A+/A/A-/B+/B/B-/C+/C/C-/D+/D/F`
3. Copies the posting JSON from `regression_corpus/postings/` to `golden_set/postings/`
4. Appends to `golden_set/expected_grades.json` with `"source": "human"`
5. Removes the posting from `regression_corpus/postings/` and its entry from `regression_corpus/expected_grades.json`

`posting_id` is the filename stem (e.g. `stripe-swe-2026-03-24`). `corpus list` shows available IDs.

### `corpus remove <posting_id>`

```
claude-candidate corpus remove <posting_id>
```

Deletes the posting JSON from `regression_corpus/postings/` and removes its entry from `regression_corpus/expected_grades.json`. Used to suppress duplicates, non-SE roles, and junk extractions.

### `corpus list`

```
claude-candidate corpus list
```

Prints a table of all entries in `regression_corpus/expected_grades.json`:
`posting_id | company | title | auto_grade | exported_at`

## Data Formats

### `regression_corpus/expected_grades.json`

```json
{
  "stripe-swe-2026-03-24": {
    "grade": "B+",
    "source": "auto",
    "assessment_id": "abc123def456",
    "exported_at": "2026-03-24T14:32:00"
  }
}
```

### Posting JSON

Same schema as `tests/golden_set/postings/*.json`. Fields: `company`, `title`, `description`, `url`, `requirements` (array of `QuickRequirement`-compatible dicts), `location`, `seniority`, `remote`, `salary`.

## Benchmark Changes

`tests/golden_set/benchmark_accuracy.py` gains a `--tier` flag:

| Invocation | Behavior |
|---|---|
| `benchmark_accuracy.py` | Existing behavior — golden set, accuracy metrics |
| `benchmark_accuracy.py --tier regression` | Regression corpus, stability metrics only |
| `benchmark_accuracy.py --tier all` | Both tiers, each with appropriate metrics |

### Regression tier output

Reports **stability**, not accuracy. Output JSON schema:

```json
{
  "tier": "regression",
  "total": 47,
  "stable": 45,
  "regressions": 1,
  "improvements": 1,
  "stability_pct": 95.7,
  "changed": [
    {"posting_id": "openai-research-2026-03-20", "auto_grade": "B", "current_grade": "C+", "direction": "regression"},
    {"posting_id": "anthropic-infra-2026-03-18", "auto_grade": "A", "current_grade": "A+", "direction": "improvement"}
  ]
}
```

The regression output **never** includes an accuracy percentage. The grades are self-assigned — reporting accuracy against them would be misleading.

**Grade shift threshold:** ≥1 full letter step (B+ → B is flagged; floating-point noise that doesn't cross a step boundary is not).

Regression runs append to `tests/regression_corpus/benchmark_history.jsonl` — separate from `golden_set/benchmark_history.jsonl` so the two trend histories remain independent.

## Storage Layer

`corpus export` reads from two tables via `AssessmentStore`:

- **Posting cache** (`get_cached_posting` / `list_cached_postings`): full extracted posting JSON including `description` and `requirements`
- **Assessments** (`list_assessments`): `overall_grade`, `assessment_id`, `assessed_at`

Joined on `posting_url`. Postings without a corresponding assessment are skipped (no grade to export).

If `AssessmentStore` doesn't expose `list_cached_postings`, a new method is added — it's a simple `SELECT * FROM posting_cache` with optional `WHERE cached_at > ?` for the `--since` filter.

## Tests

New file: `tests/test_corpus_cli.py`. All tests are fast tier (no Claude CLI calls).

| Test | What it covers |
|---|---|
| `test_export_writes_posting_json` | Seeds DB with fixture posting + assessment, asserts JSON written |
| `test_export_writes_expected_grades_with_auto_source` | Verifies grade, source, assessment_id, exported_at in grades file |
| `test_export_deduplicates_by_url` | Export same posting twice → one file, no duplicate grade entry |
| `test_export_since_filter` | Two postings at different timestamps, `--since 3` exports only recent |
| `test_remove_deletes_posting_and_grade_entry` | Export then remove → both file and grades entry gone |
| `test_promote_moves_to_golden_set` | Export, promote with "B+" → removed from regression, added to golden with source="human" |
| `test_list_shows_corpus_contents` | Export two postings, list output contains both |
| `test_regression_tier_flags_grade_shifts` | Seeds regression corpus, shifts scoring, benchmark flags regression |
| `test_regression_tier_no_accuracy_metric` | Regression output JSON has no "accuracy" key |
| `test_regression_history_separate_from_golden` | `--tier regression` appends to regression_corpus/benchmark_history.jsonl only |

## Out of Scope

- URL fetching / web scraping — corpus is populated only from the extension's existing cache
- Auto-labeling with Claude — grades come from `QuickMatchEngine`, not LLM judgment
- CI integration — regression benchmark is a manual developer tool, not a pytest check
- UI for corpus management — CLI only
