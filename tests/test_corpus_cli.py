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


# ---------------------------------------------------------------------------
# Export command
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# List command
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Remove command
# ---------------------------------------------------------------------------

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
