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
