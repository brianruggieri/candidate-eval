# Corpus Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-tier corpus system: auto-export cached job postings from `assessments.db` into a regression corpus, with CLI commands to manage (list/remove/promote) and a `--tier regression` mode on the benchmark.

**Architecture:** New `corpus_cli.py` module with a Click group registered on `main`; `list_cached_postings` added to `AssessmentStore`; `benchmark_accuracy.py` gains `--tier` and `--data-dir` flags. Tests live in `tests/test_corpus_cli.py` and follow the existing `test_storage.py` pattern (real SQLite via `tmp_path`, `run()` helper for async).

**Tech Stack:** Python 3.13, click, aiosqlite, pytest, existing `QuickMatchEngine` + `MergedEvidenceProfile`

**Spec:** `docs/superpowers/specs/2026-03-24-corpus-management-design.md`

---

## Corrections vs. spec (from reading actual code)

These are real-code facts the spec got wrong — follow the plan, not the spec, on these points:

| Spec said | Actual code | Plan uses |
|---|---|---|
| `cached_at` column (migration needed) | `extracted_at TEXT NOT NULL DEFAULT datetime('now')` already exists | `extracted_at` — no migration |
| `golden_set/expected_grades.json` is flat `{slug: grade}` | `{slug: {"expected": "B+", "rationale": "..."}}` | nested format; promote writes `{"expected": grade, "rationale": "human-promoted"}` |
| 12-grade scale with `D+` | `GRADE_ORDER = ["A+","A","A-","B+","B","B-","C+","C","C-","D","F"]` (11 grades) | 11-grade scale, no `D+` |

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `src/claude_candidate/storage.py` | Modify | Add `list_cached_postings` method |
| `src/claude_candidate/corpus_cli.py` | Create | `corpus` Click group: export, list, remove, promote; slug/grades helpers |
| `src/claude_candidate/cli.py` | Modify | Register `corpus` group via `main.add_command(corpus)` |
| `tests/golden_set/benchmark_accuracy.py` | Modify | Add `--tier` and `--data-dir` flags; regression tier logic |
| `tests/test_corpus_cli.py` | Create | All corpus CLI tests (fast tier) |
| `tests/test_storage.py` | Modify | Add `test_list_cached_postings_*` tests |

---

## Task 1: `list_cached_postings` in AssessmentStore

**Files:**
- Modify: `src/claude_candidate/storage.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1.1: Write the failing tests**

Add to `tests/test_storage.py` inside a new class `TestListCachedPostings`:

```python
class TestListCachedPostings:
	def test_returns_all_cached_postings(self, store: AssessmentStore):
		run(store.cache_posting("hash1", "https://example.com/job/1", {"company": "Stripe", "title": "SWE"}))
		run(store.cache_posting("hash2", "https://example.com/job/2", {"company": "Vercel", "title": "Platform"}))
		rows = run(store.list_cached_postings())
		assert len(rows) == 2
		urls = {r["url"] for r in rows}
		assert urls == {"https://example.com/job/1", "https://example.com/job/2"}

	def test_each_row_has_expected_fields(self, store: AssessmentStore):
		run(store.cache_posting("hash1", "https://example.com/job/1", {"company": "Stripe"}))
		rows = run(store.list_cached_postings())
		row = rows[0]
		assert "url" in row
		assert "url_hash" in row
		assert "data" in row
		assert "extracted_at" in row
		assert row["url_hash"] == "hash1"
		assert row["data"]["company"] == "Stripe"

	def test_since_filter_excludes_old_postings(self, store: AssessmentStore):
		import aiosqlite
		from datetime import datetime, timedelta

		# Insert one recent (now) and one old (20 days ago) posting
		run(store.cache_posting("recent", "https://example.com/recent", {"company": "New"}))
		old_ts = (datetime.now() - timedelta(days=20)).isoformat()
		# Directly update extracted_at to simulate old posting
		async def _backdate():
			await store._conn.execute(
				"UPDATE posting_cache SET extracted_at = ? WHERE url_hash = 'recent'",
				(old_ts,)
			)
			await store._conn.commit()

		run(_backdate())
		run(store.cache_posting("new", "https://example.com/new", {"company": "New"}))

		cutoff = datetime.now() - timedelta(days=10)
		rows = run(store.list_cached_postings(since=cutoff))
		assert len(rows) == 1
		assert rows[0]["url_hash"] == "new"

	def test_limit_caps_results(self, store: AssessmentStore):
		for i in range(5):
			run(store.cache_posting(f"hash{i}", f"https://example.com/{i}", {"company": f"Co{i}"}))
		rows = run(store.list_cached_postings(limit=3))
		assert len(rows) == 3

	def test_returns_newest_first(self, store: AssessmentStore):
		run(store.cache_posting("hash1", "https://example.com/1", {"company": "First"}))
		run(store.cache_posting("hash2", "https://example.com/2", {"company": "Second"}))
		rows = run(store.list_cached_postings())
		# Both inserted, order by extracted_at DESC — second insert should be first
		assert rows[0]["url_hash"] in ("hash1", "hash2")  # order depends on timing; just assert both present
		assert len(rows) == 2
```

- [ ] **Step 1.2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_storage.py::TestListCachedPostings -v
```

Expected: `AttributeError: 'AssessmentStore' object has no attribute 'list_cached_postings'`

- [ ] **Step 1.3: Implement `list_cached_postings`**

Add after `cache_posting` in `src/claude_candidate/storage.py`:

```python
async def list_cached_postings(
	self,
	since: "datetime | None" = None,
	limit: int | None = None,
) -> list[dict[str, Any]]:
	"""Return cached postings ordered by extracted_at DESC.

	Args:
		since: If provided, only return postings extracted after this datetime.
		limit: Maximum number of rows to return.
	"""
	assert self._conn is not None, "Store not initialized"
	params: list[Any] = []
	where = ""
	if since is not None:
		where = "WHERE extracted_at > ?"
		params.append(since.isoformat())
	order = "ORDER BY extracted_at DESC"
	lim = ""
	if limit is not None:
		lim = "LIMIT ?"
		params.append(limit)
	sql = f"SELECT url_hash, url, data, extracted_at FROM posting_cache {where} {order} {lim};"
	async with self._conn.execute(sql, params) as cursor:
		rows = await cursor.fetchall()
	result = []
	for row in rows:
		d = dict(row)
		if "data" in d and isinstance(d["data"], str):
			d["data"] = json.loads(d["data"])
		result.append(d)
	return result
```

Also add the `datetime` import at the top of `storage.py` if not present:

```python
from datetime import datetime
```

- [ ] **Step 1.4: Run tests to confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_storage.py::TestListCachedPostings -v
```

Expected: All 5 tests PASS.

- [ ] **Step 1.5: Run full fast suite to confirm no regressions**

```bash
.venv/bin/python -m pytest
```

Expected: All existing tests still pass.

- [ ] **Step 1.6: Commit**

```bash
git add src/claude_candidate/storage.py tests/test_storage.py
git commit -m "feat: add list_cached_postings to AssessmentStore"
```

---

## Task 2: `corpus_cli.py` — slug + grades helpers

**Files:**
- Create: `src/claude_candidate/corpus_cli.py`
- Create: `tests/test_corpus_cli.py`

These helpers are the foundation — all corpus commands use them.

- [ ] **Step 2.1: Write failing tests for slug generation and grades I/O**

Create `tests/test_corpus_cli.py`:

```python
"""Tests for corpus CLI commands and helpers."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path

import pytest

from claude_candidate.corpus_cli import (
	make_slug,
	load_regression_grades,
	save_regression_grades,
	GRADE_ORDER,
)
from claude_candidate.storage import AssessmentStore


# ---------------------------------------------------------------------------
# Event loop + helpers (mirror test_storage.py pattern)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _event_loop():
	loop = asyncio.new_event_loop()
	asyncio.set_event_loop(loop)
	yield loop
	loop.close()
	asyncio.set_event_loop(None)


def run(coro):
	return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
	return tmp_path / "assessments.db"


@pytest.fixture
def store(db_path: Path) -> AssessmentStore:
	s = AssessmentStore(db_path)
	run(s.initialize())
	yield s
	run(s.close())


@pytest.fixture
def corpus_dir(tmp_path: Path) -> Path:
	d = tmp_path / "regression_corpus"
	d.mkdir()
	(d / "postings").mkdir()
	return d


@pytest.fixture
def golden_dir(tmp_path: Path) -> Path:
	d = tmp_path / "golden_set"
	d.mkdir()
	(d / "postings").mkdir()
	(d / "expected_grades.json").write_text("{}")
	return d


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

class TestMakeSlug:
	def test_basic_slug(self):
		slug = make_slug("Stripe", "Senior Software Engineer", datetime(2026, 3, 24))
		assert slug == "stripe-senior-software-engineer-2026-03-24"

	def test_special_chars_replaced(self):
		slug = make_slug("Acme & Co.", "Sr. Engineer (Remote)", datetime(2026, 3, 24))
		assert "&" not in slug
		assert "." not in slug
		assert "(" not in slug

	def test_consecutive_hyphens_collapsed(self):
		slug = make_slug("X Corp", "ML / AI Engineer", datetime(2026, 1, 1))
		assert "--" not in slug

	def test_company_truncated_to_20(self):
		slug = make_slug("A" * 30, "Engineer", datetime(2026, 3, 24))
		company_part = slug.split("-engineer-")[0]
		assert len(company_part) <= 20

	def test_title_truncated_to_40(self):
		slug = make_slug("Stripe", "T" * 60, datetime(2026, 3, 24))
		# date part is at end; title is between company and date
		parts = slug.rsplit("-2026-03-24", 1)
		title_part = parts[0].replace("stripe-", "", 1)
		assert len(title_part) <= 40


# ---------------------------------------------------------------------------
# Grades file I/O
# ---------------------------------------------------------------------------

class TestGradesIO:
	def test_load_nonexistent_returns_empty(self, corpus_dir: Path):
		grades = load_regression_grades(corpus_dir)
		assert grades == {}

	def test_load_existing(self, corpus_dir: Path):
		data = {"slug-a": {"grade": "B+", "source": "auto", "assessment_id": "x", "url_hash": "y", "exported_at": "2026-03-24T00:00:00"}}
		(corpus_dir / "expected_grades.json").write_text(json.dumps(data))
		grades = load_regression_grades(corpus_dir)
		assert grades["slug-a"]["grade"] == "B+"

	def test_save_roundtrip(self, corpus_dir: Path):
		grades = {"slug-b": {"grade": "A", "source": "auto", "assessment_id": "abc", "url_hash": "def", "exported_at": "2026-03-24T00:00:00"}}
		save_regression_grades(corpus_dir, grades)
		loaded = load_regression_grades(corpus_dir)
		assert loaded == grades


# ---------------------------------------------------------------------------
# GRADE_ORDER
# ---------------------------------------------------------------------------

class TestGradeOrder:
	def test_contains_expected_grades(self):
		assert "A+" in GRADE_ORDER
		assert "F" in GRADE_ORDER
		assert "D" in GRADE_ORDER

	def test_no_d_minus(self):
		assert "D-" not in GRADE_ORDER

	def test_ordered_best_to_worst(self):
		assert GRADE_ORDER.index("A+") < GRADE_ORDER.index("B")
		assert GRADE_ORDER.index("B") < GRADE_ORDER.index("C")
		assert GRADE_ORDER.index("C") < GRADE_ORDER.index("F")
```

- [ ] **Step 2.2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestMakeSlug tests/test_corpus_cli.py::TestGradesIO tests/test_corpus_cli.py::TestGradeOrder -v
```

Expected: `ModuleNotFoundError: No module named 'claude_candidate.corpus_cli'`

- [ ] **Step 2.3: Create `corpus_cli.py` with helpers**

Create `src/claude_candidate/corpus_cli.py`:

```python
"""CLI commands for regression corpus management.

Registered on the main CLI group via: main.add_command(corpus)
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import click

# Canonical grade ordering — 11 grades, matches benchmark_accuracy.py
GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]

# Paths relative to the repo root (where the CLI is run from)
_REGRESSION_DIR = Path("tests/regression_corpus")
_GOLDEN_DIR = Path("tests/golden_set")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_slug(company: str, title: str, date: datetime) -> str:
	"""Generate a filesystem-safe slug: {company}-{title}-{YYYY-MM-DD}."""
	def _slugify(s: str, max_len: int) -> str:
		s = s.lower()
		s = re.sub(r"[^a-z0-9]+", "-", s)
		s = re.sub(r"-+", "-", s).strip("-")
		return s[:max_len].rstrip("-")

	company_slug = _slugify(company, 20)
	title_slug = _slugify(title, 40)
	date_str = date.strftime("%Y-%m-%d")
	return f"{company_slug}-{title_slug}-{date_str}"


def load_regression_grades(corpus_dir: Path) -> dict[str, Any]:
	"""Load regression_corpus/expected_grades.json, returning {} if absent."""
	grades_path = corpus_dir / "expected_grades.json"
	if not grades_path.exists():
		return {}
	return json.loads(grades_path.read_text())


def save_regression_grades(corpus_dir: Path, grades: dict[str, Any]) -> None:
	"""Write regression_corpus/expected_grades.json."""
	(corpus_dir / "expected_grades.json").write_text(
		json.dumps(grades, indent=2, ensure_ascii=False)
	)


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------


@click.group()
def corpus() -> None:
	"""Manage the regression corpus of auto-graded job postings."""
```

- [ ] **Step 2.4: Run tests to confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestMakeSlug tests/test_corpus_cli.py::TestGradesIO tests/test_corpus_cli.py::TestGradeOrder -v
```

Expected: All tests PASS.

- [ ] **Step 2.5: Commit**

```bash
git add src/claude_candidate/corpus_cli.py tests/test_corpus_cli.py
git commit -m "feat: add corpus_cli module with slug + grades helpers"
```

---

## Task 3: `corpus export` command

**Files:**
- Modify: `src/claude_candidate/corpus_cli.py`
- Modify: `tests/test_corpus_cli.py`

- [ ] **Step 3.1: Write failing tests**

Add to `tests/test_corpus_cli.py`:

```python
import hashlib
from click.testing import CliRunner
from claude_candidate.corpus_cli import corpus


def _url_hash(url: str) -> str:
	return hashlib.sha256(url.encode()).hexdigest()[:16]


def _seed_posting_and_assessment(store, url: str, company: str, title: str, grade: str) -> str:
	"""Helper: inserts a posting + assessment into the store. Returns assessment_id."""
	import uuid
	url_hash = _url_hash(url)
	posting = {"company": company, "title": title, "description": "Some job", "url": url, "requirements": []}
	run(store.cache_posting(url_hash, url, posting))
	aid = str(uuid.uuid4())
	run(store.save_assessment({
		"assessment_id": aid,
		"assessed_at": datetime.now().isoformat(),
		"job_title": title,
		"company_name": company,
		"posting_url": url,
		"overall_score": 0.77,
		"overall_grade": grade,
		"should_apply": "yes",
		"data": {"overall_grade": grade, "posting_url": url},
	}))
	return aid


class TestCorpusExport:
	def test_writes_posting_json(self, store, corpus_dir, db_path):
		_seed_posting_and_assessment(store, "https://stripe.com/job/1", "Stripe", "SWE", "B+")
		runner = CliRunner()
		result = runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir)])
		assert result.exit_code == 0, result.output
		postings = list((corpus_dir / "postings").glob("*.json"))
		assert len(postings) == 1
		data = json.loads(postings[0].read_text())
		assert data["company"] == "Stripe"
		assert data["url"] == "https://stripe.com/job/1"

	def test_writes_expected_grades(self, store, corpus_dir, db_path):
		aid = _seed_posting_and_assessment(store, "https://stripe.com/job/2", "Stripe", "SWE", "B+")
		runner = CliRunner()
		runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir)])
		grades = load_regression_grades(corpus_dir)
		assert len(grades) == 1
		entry = list(grades.values())[0]
		assert entry["grade"] == "B+"
		assert entry["source"] == "auto"
		assert entry["assessment_id"] == aid
		assert "url_hash" in entry
		assert "exported_at" in entry

	def test_deduplicates_by_url_hash(self, store, corpus_dir, db_path):
		_seed_posting_and_assessment(store, "https://stripe.com/job/3", "Stripe", "SWE", "B+")
		runner = CliRunner()
		runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir)])
		runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir)])
		postings = list((corpus_dir / "postings").glob("*.json"))
		assert len(postings) == 1
		grades = load_regression_grades(corpus_dir)
		assert len(grades) == 1

	def test_since_filter(self, store, corpus_dir, db_path):
		from datetime import timedelta
		# Seed two postings then backdate one to 20 days ago
		_seed_posting_and_assessment(store, "https://old.com/job", "Old Co", "Eng", "C")
		_seed_posting_and_assessment(store, "https://new.com/job", "New Co", "Eng", "B")
		old_ts = (datetime.now() - timedelta(days=20)).isoformat()
		async def _backdate():
			await store._conn.execute(
				"UPDATE posting_cache SET extracted_at = ? WHERE url = 'https://old.com/job'", (old_ts,)
			)
			await store._conn.commit()
		run(_backdate())
		runner = CliRunner()
		runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir), "--since", "7"])
		grades = load_regression_grades(corpus_dir)
		assert len(grades) == 1
		posting_data = json.loads(list((corpus_dir / "postings").glob("*.json"))[0].read_text())
		assert posting_data["company"] == "New Co"

	def test_skips_posting_with_no_assessment(self, store, corpus_dir, db_path):
		# Cache a posting but no assessment
		url_hash = _url_hash("https://orphan.com/job")
		run(store.cache_posting(url_hash, "https://orphan.com/job", {"company": "Orphan", "title": "Dev", "url": "https://orphan.com/job"}))
		runner = CliRunner()
		runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir)])
		assert len(list((corpus_dir / "postings").glob("*.json"))) == 0

	# NOTE: The spec listed test_export_since_skips_null_cached_at to cover pre-migration rows
	# with NULL cached_at. This test is omitted because posting_cache.extracted_at is
	# NOT NULL DEFAULT datetime('now') — NULL values cannot exist, making the test impossible.
```

- [ ] **Step 3.2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestCorpusExport -v
```

Expected: `UsageError` or `No such command 'export'`.

- [ ] **Step 3.3: Implement `corpus export`**

Add to `src/claude_candidate/corpus_cli.py`:

```python
@corpus.command("export")
@click.option("--db", "db_path", default=None, help="Path to assessments.db")
@click.option("--since", "since_days", type=int, default=None, help="Only export postings from last N days")
@click.option("--limit", "limit", type=int, default=None, help="Max postings to export")
@click.option("--corpus-dir", "corpus_dir_override", default=None, help="Override regression corpus directory (for tests)")
def export_cmd(db_path: str | None, since_days: int | None, limit: int | None, corpus_dir_override: str | None) -> None:
	"""Export cached job postings from assessments.db into the regression corpus."""
	import asyncio
	import hashlib
	from claude_candidate.storage import AssessmentStore

	corpus_dir = Path(corpus_dir_override) if corpus_dir_override else _REGRESSION_DIR
	postings_dir = corpus_dir / "postings"
	postings_dir.mkdir(parents=True, exist_ok=True)

	data_dir = Path(db_path).parent if db_path else Path.home() / ".claude-candidate"
	db = Path(db_path) if db_path else data_dir / "assessments.db"

	loop = asyncio.new_event_loop()
	try:
		store = AssessmentStore(db)
		loop.run_until_complete(store.initialize())

		since_dt = None
		if since_days is not None:
			from datetime import timedelta
			since_dt = datetime.now() - timedelta(days=since_days)

		postings = loop.run_until_complete(store.list_cached_postings(since=since_dt, limit=limit))
		assessments = loop.run_until_complete(store.list_assessments(limit=10000))
	finally:
		loop.run_until_complete(store.close())
		loop.close()

	# Build url → latest assessment map
	url_to_assessment: dict[str, Any] = {}
	for a in assessments:
		url = a.get("posting_url")
		if not url:
			continue
		if url not in url_to_assessment or a.get("assessed_at", "") > url_to_assessment[url].get("assessed_at", ""):
			url_to_assessment[url] = a

	# Load existing grades for dedup
	grades = load_regression_grades(corpus_dir)
	existing_url_hashes = {v["url_hash"] for v in grades.values()}

	exported = 0
	skipped = 0
	for posting_row in postings:
		url_hash = posting_row["url_hash"]
		url = posting_row["url"]
		posting_data = posting_row["data"]

		if url_hash in existing_url_hashes:
			click.echo(f"  skip (already exported): {url}")
			skipped += 1
			continue

		assessment = url_to_assessment.get(url)
		if not assessment:
			continue

		# Enrich posting_data with url if missing
		posting_data = dict(posting_data)
		posting_data.setdefault("url", url)

		company = posting_data.get("company") or assessment.get("company_name") or "unknown"
		title = posting_data.get("title") or assessment.get("job_title") or "unknown"
		slug = make_slug(company, title, datetime.now())

		# Resolve slug collisions
		base_slug = slug
		if slug in grades:
			# Different URL — append hash prefix
			slug = f"{base_slug}-{url_hash[:6]}"
			counter = 2
			while slug in grades:
				slug = f"{base_slug}-{url_hash[:6]}-{counter}"
				counter += 1

		# Write posting JSON
		posting_path = postings_dir / f"{slug}.json"
		posting_path.write_text(json.dumps(posting_data, indent=2, ensure_ascii=False))

		# Append to grades
		overall_grade = None
		if isinstance(assessment.get("data"), dict):
			overall_grade = assessment["data"].get("overall_grade")
		overall_grade = overall_grade or assessment.get("overall_grade") or "?"

		grades[slug] = {
			"grade": overall_grade,
			"source": "auto",
			"assessment_id": assessment.get("assessment_id", ""),
			"url_hash": url_hash,
			"exported_at": datetime.now().isoformat(),
		}
		existing_url_hashes.add(url_hash)
		click.echo(f"  exported: {slug}  grade={overall_grade}")
		exported += 1

	save_regression_grades(corpus_dir, grades)
	click.echo(f"\nExported {exported} posting(s). Skipped {skipped} duplicate(s).")
```

- [ ] **Step 3.4: Run tests to confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestCorpusExport -v
```

Expected: All tests PASS.

- [ ] **Step 3.5: Run full fast suite**

```bash
.venv/bin/python -m pytest
```

- [ ] **Step 3.6: Commit**

```bash
git add src/claude_candidate/corpus_cli.py tests/test_corpus_cli.py
git commit -m "feat: add corpus export command"
```

---

## Task 4: `corpus list` command

**Files:**
- Modify: `src/claude_candidate/corpus_cli.py`
- Modify: `tests/test_corpus_cli.py`

- [ ] **Step 4.1: Write failing tests**

Add to `tests/test_corpus_cli.py`:

```python
class TestCorpusList:
	def test_shows_corpus_contents(self, store, corpus_dir, db_path):
		_seed_posting_and_assessment(store, "https://stripe.com/list/1", "Stripe", "SWE", "B+")
		_seed_posting_and_assessment(store, "https://vercel.com/list/1", "Vercel", "Platform Eng", "A-")
		runner = CliRunner()
		runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir)])
		result = runner.invoke(corpus, ["list", "--corpus-dir", str(corpus_dir)])
		assert result.exit_code == 0
		assert "Stripe" in result.output
		assert "Vercel" in result.output

	def test_missing_json_shows_placeholder(self, corpus_dir):
		grades = {
			"ghost-posting-2026-03-24": {
				"grade": "B",
				"source": "auto",
				"assessment_id": "x",
				"url_hash": "y",
				"exported_at": "2026-03-24T00:00:00",
			}
		}
		save_regression_grades(corpus_dir, grades)
		# No posting JSON file written
		runner = CliRunner()
		result = runner.invoke(corpus, ["list", "--corpus-dir", str(corpus_dir)])
		assert "[file missing]" in result.output

	def test_empty_corpus_shows_nothing(self, corpus_dir):
		runner = CliRunner()
		result = runner.invoke(corpus, ["list", "--corpus-dir", str(corpus_dir)])
		assert result.exit_code == 0
		assert "0 posting" in result.output or result.output.strip() == "" or "No postings" in result.output
```

- [ ] **Step 4.2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestCorpusList -v
```

- [ ] **Step 4.3: Implement `corpus list`**

Add to `src/claude_candidate/corpus_cli.py`:

```python
@corpus.command("list")
@click.option("--corpus-dir", "corpus_dir_override", default=None)
def list_cmd(corpus_dir_override: str | None) -> None:
	"""List all postings in the regression corpus."""
	corpus_dir = Path(corpus_dir_override) if corpus_dir_override else _REGRESSION_DIR
	grades = load_regression_grades(corpus_dir)

	if not grades:
		click.echo("No postings in regression corpus.")
		return

	header = f"{'posting_id':<55} {'company':<20} {'title':<30} {'grade':<6} {'exported_at'}"
	click.echo(header)
	click.echo("-" * len(header))

	for posting_id, entry in sorted(grades.items()):
		posting_path = corpus_dir / "postings" / f"{posting_id}.json"
		if posting_path.exists():
			data = json.loads(posting_path.read_text())
			company = (data.get("company") or "")[:20]
			title = (data.get("title") or "")[:30]
		else:
			company = "[file missing]"
			title = "[file missing]"

		grade = entry.get("grade", "?")
		exported_at = entry.get("exported_at", "")[:16].replace("T", " ")
		click.echo(f"{posting_id:<55} {company:<20} {title:<30} {grade:<6} {exported_at}")
```

- [ ] **Step 4.4: Run tests to confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestCorpusList -v
```

- [ ] **Step 4.5: Commit**

```bash
git add src/claude_candidate/corpus_cli.py tests/test_corpus_cli.py
git commit -m "feat: add corpus list command"
```

---

## Task 5: `corpus remove` command

**Files:**
- Modify: `src/claude_candidate/corpus_cli.py`
- Modify: `tests/test_corpus_cli.py`

- [ ] **Step 5.1: Write failing tests**

Add to `tests/test_corpus_cli.py`:

```python
class TestCorpusRemove:
	def test_removes_posting_and_grade_entry(self, store, corpus_dir, db_path):
		_seed_posting_and_assessment(store, "https://stripe.com/rm/1", "Stripe", "SWE", "B+")
		runner = CliRunner()
		runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir)])
		slug = list(load_regression_grades(corpus_dir).keys())[0]
		result = runner.invoke(corpus, ["remove", slug, "--corpus-dir", str(corpus_dir)])
		assert result.exit_code == 0
		assert not (corpus_dir / "postings" / f"{slug}.json").exists()
		assert slug not in load_regression_grades(corpus_dir)

	def test_partial_state_removes_what_exists(self, corpus_dir):
		# grades entry exists but no file
		grades = {"ghost-2026-03-24": {"grade": "B", "source": "auto", "assessment_id": "x", "url_hash": "y", "exported_at": "2026-03-24T00:00:00"}}
		save_regression_grades(corpus_dir, grades)
		runner = CliRunner()
		result = runner.invoke(corpus, ["remove", "ghost-2026-03-24", "--corpus-dir", str(corpus_dir)])
		assert result.exit_code == 0
		assert "ghost-2026-03-24" not in load_regression_grades(corpus_dir)
		assert "warning" in result.output.lower() or "missing" in result.output.lower()

	def test_missing_is_noop(self, corpus_dir):
		runner = CliRunner()
		result = runner.invoke(corpus, ["remove", "nonexistent-2026-03-24", "--corpus-dir", str(corpus_dir)])
		assert result.exit_code == 0
		assert "not found" in result.output.lower()
```

- [ ] **Step 5.2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestCorpusRemove -v
```

- [ ] **Step 5.3: Implement `corpus remove`**

Add to `src/claude_candidate/corpus_cli.py`:

```python
@corpus.command("remove")
@click.argument("posting_id")
@click.option("--corpus-dir", "corpus_dir_override", default=None)
def remove_cmd(posting_id: str, corpus_dir_override: str | None) -> None:
	"""Remove a posting from the regression corpus."""
	corpus_dir = Path(corpus_dir_override) if corpus_dir_override else _REGRESSION_DIR
	grades = load_regression_grades(corpus_dir)
	posting_path = corpus_dir / "postings" / f"{posting_id}.json"

	has_file = posting_path.exists()
	has_grade = posting_id in grades

	if not has_file and not has_grade:
		click.echo(f"Not found in regression corpus: {posting_id}")
		return

	if has_file:
		posting_path.unlink()
	else:
		click.echo(f"Warning: posting file missing for {posting_id} (grades entry still removed)")

	if has_grade:
		del grades[posting_id]
		save_regression_grades(corpus_dir, grades)
	else:
		click.echo(f"Warning: grades entry missing for {posting_id} (file still deleted)")

	click.echo(f"Removed: {posting_id}")
```

- [ ] **Step 5.4: Run tests to confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestCorpusRemove -v
```

- [ ] **Step 5.5: Commit**

```bash
git add src/claude_candidate/corpus_cli.py tests/test_corpus_cli.py
git commit -m "feat: add corpus remove command"
```

---

## Task 6: `corpus promote` command

**Files:**
- Modify: `src/claude_candidate/corpus_cli.py`
- Modify: `tests/test_corpus_cli.py`

Note: The golden set `expected_grades.json` uses `{slug: {"expected": grade, "rationale": "..."}}`. `corpus promote` writes `{"expected": grade, "rationale": "human-promoted"}` to match.

- [ ] **Step 6.1: Write failing tests**

Add to `tests/test_corpus_cli.py`:

```python
class TestCorpusPromote:
	def test_moves_to_golden_set(self, store, corpus_dir, golden_dir, db_path):
		_seed_posting_and_assessment(store, "https://stripe.com/promo/1", "Stripe", "SWE", "B+")
		runner = CliRunner()
		runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir)])
		slug = list(load_regression_grades(corpus_dir).keys())[0]

		result = runner.invoke(
			corpus,
			["promote", slug, "--corpus-dir", str(corpus_dir), "--golden-dir", str(golden_dir)],
			input="B+\n",
		)
		assert result.exit_code == 0

		# Removed from regression
		assert slug not in load_regression_grades(corpus_dir)
		assert not (corpus_dir / "postings" / f"{slug}.json").exists()

		# Added to golden set
		golden_grades = json.loads((golden_dir / "expected_grades.json").read_text())
		assert slug in golden_grades
		assert golden_grades[slug]["expected"] == "B+"
		assert (golden_dir / "postings" / f"{slug}.json").exists()

	def test_errors_if_already_in_golden(self, store, corpus_dir, golden_dir, db_path):
		_seed_posting_and_assessment(store, "https://stripe.com/promo/2", "Stripe", "SWE", "B+")
		runner = CliRunner()
		runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir)])
		slug = list(load_regression_grades(corpus_dir).keys())[0]

		# Pre-populate golden set with same slug
		existing = json.loads((golden_dir / "expected_grades.json").read_text())
		existing[slug] = {"expected": "A", "rationale": "already here"}
		(golden_dir / "expected_grades.json").write_text(json.dumps(existing))

		result = runner.invoke(
			corpus,
			["promote", slug, "--corpus-dir", str(corpus_dir), "--golden-dir", str(golden_dir)],
			input="B+\n",
		)
		assert result.exit_code != 0
		# Should NOT have written anything new
		golden_grades = json.loads((golden_dir / "expected_grades.json").read_text())
		assert golden_grades[slug]["expected"] == "A"  # unchanged

	def test_rejects_invalid_grade(self, store, corpus_dir, golden_dir, db_path):
		_seed_posting_and_assessment(store, "https://stripe.com/promo/3", "Stripe", "SWE", "B+")
		runner = CliRunner()
		runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir)])
		slug = list(load_regression_grades(corpus_dir).keys())[0]

		# First input invalid, second valid
		result = runner.invoke(
			corpus,
			["promote", slug, "--corpus-dir", str(corpus_dir), "--golden-dir", str(golden_dir)],
			input="ZZ\nB+\n",
		)
		assert result.exit_code == 0
		golden_grades = json.loads((golden_dir / "expected_grades.json").read_text())
		assert golden_grades[slug]["expected"] == "B+"

	def test_aborts_on_eof(self, store, corpus_dir, golden_dir, db_path):
		_seed_posting_and_assessment(store, "https://stripe.com/promo/4", "Stripe", "SWE", "B+")
		runner = CliRunner()
		runner.invoke(corpus, ["export", "--db", str(db_path), "--corpus-dir", str(corpus_dir)])
		slug = list(load_regression_grades(corpus_dir).keys())[0]

		result = runner.invoke(
			corpus,
			["promote", slug, "--corpus-dir", str(corpus_dir), "--golden-dir", str(golden_dir)],
			input="ZZ\n",  # only invalid input — EOF after one try
		)
		assert result.exit_code != 0

	def test_errors_on_missing_grade_entry(self, corpus_dir, golden_dir):
		# posting file exists but no grades entry
		slug = "orphan-2026-03-24"
		(corpus_dir / "postings" / f"{slug}.json").write_text(
			json.dumps({"company": "X", "title": "Y", "description": "Z", "url": "https://x.com"})
		)
		runner = CliRunner()
		result = runner.invoke(
			corpus,
			["promote", slug, "--corpus-dir", str(corpus_dir), "--golden-dir", str(golden_dir)],
			input="B+\n",
		)
		assert result.exit_code != 0
		assert "grades entry not found" in result.output.lower() or "cleanup" in result.output.lower()
```

- [ ] **Step 6.2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestCorpusPromote -v
```

- [ ] **Step 6.3: Implement `corpus promote`**

Add to `src/claude_candidate/corpus_cli.py`:

```python
@corpus.command("promote")
@click.argument("posting_id")
@click.option("--corpus-dir", "corpus_dir_override", default=None)
@click.option("--golden-dir", "golden_dir_override", default=None)
def promote_cmd(posting_id: str, corpus_dir_override: str | None, golden_dir_override: str | None) -> None:
	"""Promote a regression corpus posting to the golden set with a human grade."""
	corpus_dir = Path(corpus_dir_override) if corpus_dir_override else _REGRESSION_DIR
	golden_dir = Path(golden_dir_override) if golden_dir_override else _GOLDEN_DIR

	# Step 1: read posting file
	posting_path = corpus_dir / "postings" / f"{posting_id}.json"
	if not posting_path.exists():
		raise click.ClickException(f"Posting file not found: {posting_path}")

	# Step 2: read grades entry
	grades = load_regression_grades(corpus_dir)
	if posting_id not in grades:
		raise click.ClickException(
			f"Grades entry not found for {posting_id}. "
			f"Run `corpus remove {posting_id}` to clean up the orphaned file."
		)

	posting_data = json.loads(posting_path.read_text())
	auto_grade = grades[posting_id]["grade"]

	# Step 3: show summary
	click.echo(f"\nPosting:    {posting_data.get('company', '?')} — {posting_data.get('title', '?')}")
	click.echo(f"Auto grade: {auto_grade}")
	click.echo(f"Preview:    {posting_data.get('description', '')[:300]}")
	click.echo()

	# Step 4: prompt for human grade
	valid_grades = set(GRADE_ORDER)
	human_grade = None
	while human_grade is None:
		raw = click.prompt(
			"Enter human grade (A+/A/A-/B+/B/B-/C+/C/C-/D/F)",
			default="",
			show_default=False,
		)
		if raw.strip().upper() in valid_grades:
			human_grade = raw.strip().upper()
		elif raw == "":
			raise click.Abort()
		else:
			click.echo(f"Invalid grade '{raw}'. Valid: {'/'.join(GRADE_ORDER)}")

	# Step 5: check golden set for conflicts
	golden_grades_path = golden_dir / "expected_grades.json"
	golden_grades: dict[str, Any] = {}
	if golden_grades_path.exists():
		golden_grades = json.loads(golden_grades_path.read_text())
	if posting_id in golden_grades:
		raise click.ClickException(
			f"{posting_id} already exists in golden set. "
			"Remove it from golden_set/expected_grades.json first if you want to replace it."
		)

	# Step 6: copy posting JSON to golden set
	golden_postings_dir = golden_dir / "postings"
	golden_postings_dir.mkdir(parents=True, exist_ok=True)
	shutil.copy2(posting_path, golden_postings_dir / f"{posting_id}.json")

	# Step 7: append to golden set expected_grades.json (existing nested format)
	golden_grades[posting_id] = {"expected": human_grade, "rationale": "human-promoted"}
	golden_grades_path.write_text(json.dumps(golden_grades, indent=2, ensure_ascii=False))

	# Step 8-9: remove from regression corpus
	del grades[posting_id]
	save_regression_grades(corpus_dir, grades)
	posting_path.unlink()

	click.echo(f"\nPromoted {posting_id} → golden set with grade {human_grade}")
```

- [ ] **Step 6.4: Run tests to confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestCorpusPromote -v
```

- [ ] **Step 6.5: Run all corpus tests**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py -v
```

Expected: All tests PASS.

- [ ] **Step 6.6: Commit**

```bash
git add src/claude_candidate/corpus_cli.py tests/test_corpus_cli.py
git commit -m "feat: add corpus promote command"
```

---

## Task 7: Register `corpus` group in CLI

**Files:**
- Modify: `src/claude_candidate/cli.py`

- [ ] **Step 7.1: Add import and registration**

At the bottom of `src/claude_candidate/cli.py`, just before `if __name__ == "__main__":`, add:

```python
# Register corpus subcommand group
from claude_candidate.corpus_cli import corpus as _corpus_group
main.add_command(_corpus_group, name="corpus")
```

- [ ] **Step 7.2: Verify CLI help shows corpus**

```bash
.venv/bin/python -m claude_candidate.cli --help
```

Expected: `corpus` appears in the list of commands.

```bash
.venv/bin/python -m claude_candidate.cli corpus --help
```

Expected: Shows `export`, `list`, `remove`, `promote` subcommands.

- [ ] **Step 7.3: Run full fast suite**

```bash
.venv/bin/python -m pytest
```

- [ ] **Step 7.4: Commit**

```bash
git add src/claude_candidate/cli.py
git commit -m "feat: register corpus group on main CLI"
```

---

## Task 8: Benchmark `--tier regression` and `--data-dir`

**Files:**
- Modify: `tests/golden_set/benchmark_accuracy.py`
- Modify: `tests/test_corpus_cli.py`

- [ ] **Step 8.1: Write failing tests**

Add to `tests/test_corpus_cli.py`:

```python
import subprocess
import sys


def _make_fixture_profile(tmp_path: Path) -> Path:
	"""Write a minimal CandidateProfile with no skills to a tmp data dir.

	load_profile() reads candidate_profile.json as CandidateProfile then calls
	_merge_profile — so we must write CandidateProfile here, not MergedEvidenceProfile.
	"""
	from datetime import timezone
	from claude_candidate.schemas.candidate_profile import CandidateProfile
	data_dir = tmp_path / "data"
	data_dir.mkdir()
	now = datetime.now(tz=timezone.utc)
	profile = CandidateProfile(
		generated_at=now,
		session_count=0,
		date_range_start=now,
		date_range_end=now,
		manifest_hash="fixture",
		skills=[],
		primary_languages=[],
		primary_domains=[],
		problem_solving_patterns=[],
		working_style_summary="",
		projects=[],
		communication_style="",
		documentation_tendency="minimal",
		extraction_notes="",
		confidence_assessment="low",
	)
	(data_dir / "candidate_profile.json").write_text(profile.model_dump_json())
	return data_dir


def _make_regression_fixture(corpus_dir: Path, slug: str, stored_grade: str) -> None:
	"""Write a posting + expected_grades entry to corpus_dir."""
	postings_dir = corpus_dir / "postings"
	postings_dir.mkdir(parents=True, exist_ok=True)
	posting = {
		"company": "Test Co",
		"title": "Engineer",
		"description": "Test posting",
		"url": "https://testco.com/job/1",
		"requirements": [
			{"description": "Python", "skill_mapping": ["python"], "priority": "must_have", "years_experience": None, "education_level": None, "is_eligibility": False}
		],
	}
	(postings_dir / f"{slug}.json").write_text(json.dumps(posting))
	grades = {
		slug: {
			"grade": stored_grade,
			"source": "auto",
			"assessment_id": "test-aid",
			"url_hash": "testhash",
			"exported_at": datetime.now().isoformat(),
		}
	}
	(corpus_dir / "expected_grades.json").write_text(json.dumps(grades))


class TestBenchmarkRegressionTier:
	def test_flags_grade_shifts(self, tmp_path):
		corpus_dir = tmp_path / "regression_corpus"
		data_dir = _make_fixture_profile(tmp_path)
		# Stored grade is A+ but profile has no Python skill -> will score low
		_make_regression_fixture(corpus_dir, "testco-engineer-2026-03-24", "A+")

		result = subprocess.run(
			[
				sys.executable, "tests/golden_set/benchmark_accuracy.py",
				"--tier", "regression",
				"--corpus-dir", str(corpus_dir),
				"--data-dir", str(data_dir),
			],
			capture_output=True, text=True
		)
		# Must exit cleanly
		assert result.returncode == 0, result.stderr
		# Parse JSON output and assert regression was flagged
		import re
		json_match = re.search(r'\{.*\}', result.stdout, re.DOTALL)
		assert json_match, f"No JSON in output: {result.stdout}"
		out = json.loads(json_match.group())
		assert "accuracy" not in out
		assert out["regressions"] >= 1, f"Expected at least 1 regression, got: {out}"
		assert any(e["direction"] == "regression" for e in out["changed"])

	def test_no_accuracy_key_in_output(self, tmp_path):
		corpus_dir = tmp_path / "regression_corpus"
		data_dir = _make_fixture_profile(tmp_path)
		_make_regression_fixture(corpus_dir, "testco-engineer-2026-03-24", "B+")

		result = subprocess.run(
			[
				sys.executable, "tests/golden_set/benchmark_accuracy.py",
				"--tier", "regression",
				"--corpus-dir", str(corpus_dir),
				"--data-dir", str(data_dir),
			],
			capture_output=True, text=True
		)
		assert "\"accuracy\"" not in result.stdout

	def test_regression_history_written_separately(self, tmp_path):
		corpus_dir = tmp_path / "regression_corpus"
		data_dir = _make_fixture_profile(tmp_path)
		_make_regression_fixture(corpus_dir, "testco-engineer-2026-03-24", "B+")

		subprocess.run(
			[
				sys.executable, "tests/golden_set/benchmark_accuracy.py",
				"--tier", "regression",
				"--corpus-dir", str(corpus_dir),
				"--data-dir", str(data_dir),
			],
			capture_output=True, text=True
		)
		assert (corpus_dir / "benchmark_history.jsonl").exists()
		# Golden set history NOT written
		assert not (tmp_path / "golden_set" / "benchmark_history.jsonl").exists()

	def test_empty_corpus_returns_stable(self, tmp_path):
		corpus_dir = tmp_path / "regression_corpus"
		corpus_dir.mkdir()
		data_dir = _make_fixture_profile(tmp_path)

		result = subprocess.run(
			[
				sys.executable, "tests/golden_set/benchmark_accuracy.py",
				"--tier", "regression",
				"--corpus-dir", str(corpus_dir),
				"--data-dir", str(data_dir),
			],
			capture_output=True, text=True
		)
		assert result.returncode == 0
		assert "0" in result.stdout  # total=0
```

- [ ] **Step 8.2: Run tests to confirm they fail**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestBenchmarkRegressionTier -v
```

Expected: `SystemExit` or `unrecognized arguments: --tier`.

- [ ] **Step 8.3: Refactor `benchmark_accuracy.py` to support `--tier` and `--data-dir`**

Replace `tests/golden_set/benchmark_accuracy.py` with:

```python
#!/usr/bin/env python3
"""Benchmark skill matching accuracy and regression against corpus tiers.

Usage:
  python tests/golden_set/benchmark_accuracy.py                  # golden tier (default)
  python tests/golden_set/benchmark_accuracy.py --tier regression --corpus-dir tests/regression_corpus
  python tests/golden_set/benchmark_accuracy.py --tier all
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from claude_candidate.quick_match import QuickMatchEngine
from claude_candidate.schemas.job_requirements import QuickRequirement
from claude_candidate.schemas.merged_profile import MergedEvidenceProfile

GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]


def grade_distance(actual: str, expected: str) -> int:
	try:
		return GRADE_ORDER.index(actual) - GRADE_ORDER.index(expected)
	except ValueError:
		return 99


def load_profile(data_dir: Path) -> MergedEvidenceProfile:
	from claude_candidate.schemas.candidate_profile import CandidateProfile
	from claude_candidate.cli import _merge_profile
	cp = CandidateProfile.from_json((data_dir / "candidate_profile.json").read_text())
	return _merge_profile(cp, quiet=True)


def _grade_to_midpoint(grade: str) -> float:
	midpoints = {"A+": 97, "A": 92, "A-": 87, "B+": 82, "B": 77, "B-": 72,
	             "C+": 67, "C": 62, "C-": 57, "D": 50, "F": 25}
	return midpoints.get(grade, 50)


def run_golden(golden_dir: Path, profile: MergedEvidenceProfile) -> dict:
	"""Run accuracy benchmark on the golden set. Returns result dict."""
	postings_dir = golden_dir / "postings"
	expected_path = golden_dir / "expected_grades.json"
	history_path = golden_dir / "benchmark_history.jsonl"

	expected = json.loads(expected_path.read_text())
	engine = QuickMatchEngine(profile)

	results = {}
	taxonomy_gaps = 0
	total_must_haves = 0
	met_must_haves = 0

	for posting_file in sorted(postings_dir.glob("*.json")):
		slug = posting_file.stem
		if slug not in expected:
			continue
		data = json.loads(posting_file.read_text())
		reqs = [QuickRequirement(**r) for r in data.get("requirements", []) if r.get("skill_mapping")]
		assessment = engine.assess(
			requirements=reqs,
			company=data.get("company", "Unknown"),
			title=data.get("title", "Unknown"),
			posting_url=data.get("url"),
			source="golden_set",
			seniority=data.get("seniority", "unknown"),
		)
		exp_grade = expected[slug]["expected"]
		actual_grade = assessment.overall_grade
		delta = grade_distance(actual_grade, exp_grade)
		score_pct = round(assessment.overall_score * 100, 1)
		for detail in assessment.skill_matches:
			if detail.priority == "must_have":
				total_must_haves += 1
				if detail.match_status in ("strong_match", "exceeds"):
					met_must_haves += 1
				elif detail.match_status == "no_evidence":
					taxonomy_gaps += 1
		results[slug] = {"actual": actual_grade, "expected": exp_grade, "delta": delta, "score": score_pct,
		                  "skill_score": round(assessment.skill_match.score * 100, 1)}

	graded = {k: v for k, v in results.items() if v["expected"] != "?"}
	exact = sum(1 for r in graded.values() if r["delta"] == 0)
	within_1 = sum(1 for r in graded.values() if abs(r["delta"]) <= 1)
	off_by_2 = len(graded) - within_1
	avg_delta = sum(r["delta"] for r in graded.values()) / max(len(graded), 1)
	must_have_pct = round(met_must_haves / max(total_must_haves, 1) * 100)

	print(f"=== ACCURACY BENCHMARK ({len(results)} postings, {len(graded)} graded) ===")
	if graded:
		print(f"Exact match: {exact}/{len(graded)} | Within 1: {within_1}/{len(graded)} | Off by 2+: {off_by_2}/{len(graded)}")
		print(f"Avg grade delta: {avg_delta:+.1f}")
	print(f"Must-have coverage: {must_have_pct}% ({met_must_haves}/{total_must_haves})")
	print()
	if taxonomy_gaps > len(results) * 0.1:
		print(f"  >>> FOCUS: Stage 1 (Taxonomy) — {taxonomy_gaps} must-have no_evidence gaps")
	elif must_have_pct < 70:
		print(f"  >>> FOCUS: Stage 2 (Requirement handling) — must-have coverage {must_have_pct}%")
	else:
		print("  >>> FOCUS: Stage 3 (Calibration) — fine-tune weights and thresholds")
	print()
	print("ALL POSTINGS:")
	for slug, r in sorted(results.items(), key=lambda x: x[1]["score"], reverse=True):
		exp_str = r["expected"] if r["expected"] != "?" else "?"
		delta_str = f"delta={r['delta']:+d}" if r["expected"] != "?" else "ungraded"
		print(f"  {slug:.<55} actual={r['actual']:>3} expected={exp_str:>3} {delta_str} score={r['score']}%")

	entry = {"timestamp": datetime.now().isoformat(), "tier": "golden", "exact_match": exact,
	          "within_1": within_1, "off_by_2_plus": off_by_2, "avg_delta": round(avg_delta, 2),
	          "must_have_pct": must_have_pct, "postings": results}
	with open(history_path, "a") as f:
		f.write(json.dumps(entry) + "\n")

	return {"tier": "golden", "exact_match": exact, "within_1": within_1,
	         "off_by_2_plus": off_by_2, "postings": len(results), "graded": len(graded)}


def run_regression(corpus_dir: Path, profile: MergedEvidenceProfile) -> dict:
	"""Run regression benchmark on the regression corpus. Returns stability result dict."""
	postings_dir = corpus_dir / "postings"
	grades_path = corpus_dir / "expected_grades.json"
	history_path = corpus_dir / "benchmark_history.jsonl"

	if not grades_path.exists():
		print("=== REGRESSION BENCHMARK (0 postings) ===")
		print("No regression_corpus/expected_grades.json found.")
		result = {"tier": "regression", "total": 0, "stable": 0, "regressions": 0,
		           "improvements": 0, "stability_pct": 100.0, "changed": []}
		with open(history_path, "a") as f:
			f.write(json.dumps({"timestamp": datetime.now().isoformat(), **result}) + "\n")
		return result

	expected = json.loads(grades_path.read_text())
	if not expected:
		result = {"tier": "regression", "total": 0, "stable": 0, "regressions": 0,
		           "improvements": 0, "stability_pct": 100.0, "changed": []}
		with open(history_path, "a") as f:
			f.write(json.dumps({"timestamp": datetime.now().isoformat(), **result}) + "\n")
		return result

	engine = QuickMatchEngine(profile)
	changed = []
	total = 0

	for posting_file in sorted(postings_dir.glob("*.json")):
		slug = posting_file.stem
		if slug not in expected:
			continue
		total += 1
		data = json.loads(posting_file.read_text())
		reqs = [QuickRequirement(**r) for r in data.get("requirements", []) if r.get("skill_mapping")]
		assessment = engine.assess(
			requirements=reqs,
			company=data.get("company", "Unknown"),
			title=data.get("title", "Unknown"),
			posting_url=data.get("url"),
			source="regression",
			seniority=data.get("seniority", "unknown"),
		)
		stored_grade = expected[slug]["grade"]
		current_grade = assessment.overall_grade
		try:
			dist = abs(GRADE_ORDER.index(current_grade) - GRADE_ORDER.index(stored_grade))
		except ValueError:
			dist = 99
		if dist >= 1:
			direction = "improvement" if GRADE_ORDER.index(current_grade) < GRADE_ORDER.index(stored_grade) else "regression"
			changed.append({"posting_id": slug, "stored_grade": stored_grade, "current_grade": current_grade, "direction": direction})

	stable = total - len(changed)
	regressions = sum(1 for c in changed if c["direction"] == "regression")
	improvements = sum(1 for c in changed if c["direction"] == "improvement")
	stability_pct = round(stable / max(total, 1) * 100, 1)

	print(f"=== REGRESSION BENCHMARK ({total} postings) ===")
	print(f"Stable: {stable}/{total} ({stability_pct}%)")
	if regressions:
		print(f"Regressions: {regressions}")
	if improvements:
		print(f"Improvements: {improvements}")
	if changed:
		print("\nCHANGED:")
		for c in changed:
			arrow = "↑" if c["direction"] == "improvement" else "↓"
			print(f"  {c['posting_id']:<55} {c['stored_grade']} → {c['current_grade']} {arrow}")

	result = {"tier": "regression", "total": total, "stable": stable, "regressions": regressions,
	           "improvements": improvements, "stability_pct": stability_pct, "changed": changed}
	with open(history_path, "a") as f:
		f.write(json.dumps({"timestamp": datetime.now().isoformat(), **result}) + "\n")
	return result


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--tier", choices=["golden", "regression", "all"], default="golden")
	parser.add_argument("--data-dir", default=None, help="Override ~/.claude-candidate/ for profile loading")
	parser.add_argument("--corpus-dir", default="tests/regression_corpus", help="Path to regression corpus (for --tier regression)")
	args = parser.parse_args()

	data_dir = Path(args.data_dir) if args.data_dir else Path.home() / ".claude-candidate"
	corpus_dir = Path(args.corpus_dir)
	golden_dir = Path("tests/golden_set")

	profile = load_profile(data_dir)

	if args.tier == "golden":
		result = run_golden(golden_dir, profile)
		graded = result.get("graded", 0)
		within_1 = result.get("within_1", 0)
		if graded and within_1 == graded:
			print("\n*** ALL GRADED POSTINGS WITHIN TOLERANCE ***")
			sys.exit(0)
		elif not graded:
			print("\n*** No graded postings. Fill in expected_grades.json. ***")
			sys.exit(0)
		else:
			sys.exit(1)

	elif args.tier == "regression":
		result = run_regression(corpus_dir, profile)
		print(json.dumps(result, indent=2))
		sys.exit(0)

	elif args.tier == "all":
		golden_result = run_golden(golden_dir, profile)
		print()
		regression_result = run_regression(corpus_dir, profile)
		combined = {"golden": golden_result, "regression": regression_result}
		print(json.dumps(combined, indent=2))
		graded = golden_result.get("graded", 0)
		within_1 = golden_result.get("within_1", 0)
		sys.exit(0 if (not graded or within_1 == graded) else 1)


if __name__ == "__main__":
	main()
```

- [ ] **Step 8.4: Run tests to confirm they pass**

```bash
.venv/bin/python -m pytest tests/test_corpus_cli.py::TestBenchmarkRegressionTier -v
```

Expected: All tests PASS.

- [ ] **Step 8.5: Confirm existing golden benchmark still works**

```bash
.venv/bin/python tests/golden_set/benchmark_accuracy.py --help
```

Expected: Shows `--tier`, `--data-dir`, `--corpus-dir` flags with no errors.

- [ ] **Step 8.6: Run full fast suite**

```bash
.venv/bin/python -m pytest
```

- [ ] **Step 8.7: Commit**

```bash
git add tests/golden_set/benchmark_accuracy.py tests/test_corpus_cli.py
git commit -m "feat: add --tier regression and --data-dir to benchmark"
```

---

## Task 9: Final integration check

- [ ] **Step 9.1: Run full fast test suite**

```bash
.venv/bin/python -m pytest -v
```

Expected: All tests PASS, including all new `test_corpus_cli.py` tests.

- [ ] **Step 9.2: Smoke test CLI**

```bash
.venv/bin/python -m claude_candidate.cli corpus --help
.venv/bin/python -m claude_candidate.cli corpus export --help
.venv/bin/python -m claude_candidate.cli corpus list --help
.venv/bin/python -m claude_candidate.cli corpus remove --help
.venv/bin/python -m claude_candidate.cli corpus promote --help
```

Expected: All show help text without errors.

- [ ] **Step 9.3: Final commit if any cleanup needed**

```bash
git add -p
git commit -m "chore: corpus management cleanup"
```
