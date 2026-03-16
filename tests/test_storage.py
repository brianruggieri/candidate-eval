"""Tests for SQLite storage layer (AssessmentStore)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from claude_candidate.storage import AssessmentStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run an async coroutine from a synchronous test function."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test_assessments.db"


@pytest.fixture
def store(db_path: Path) -> AssessmentStore:
    store = AssessmentStore(db_path)
    run(store.initialize())
    yield store
    run(store.close())


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

class TestInitialization:
    def test_creates_db_file(self, db_path: Path):
        store = AssessmentStore(db_path)
        run(store.initialize())
        run(store.close())
        assert db_path.exists()

    def test_creates_expected_tables(self, store: AssessmentStore):
        tables = run(store.list_tables())
        assert "assessments" in tables
        assert "watchlist" in tables
        assert "profiles" in tables

    def test_idempotent_init(self, db_path: Path):
        """Second initialize() call must not raise."""
        store = AssessmentStore(db_path)
        run(store.initialize())
        run(store.initialize())  # should not raise
        run(store.close())


# ---------------------------------------------------------------------------
# Assessment CRUD
# ---------------------------------------------------------------------------

SAMPLE_ASSESSMENT: dict = {
    "assessment_id": "assess-001",
    "assessed_at": "2026-01-15T10:00:00",
    "job_title": "Senior Engineer",
    "company_name": "Acme Corp",
    "posting_url": "https://example.com/job/1",
    "overall_score": 82,
    "overall_grade": "B+",
    "should_apply": True,
    "data": {"dimensions": [], "summary": "Great fit"},
}


class TestAssessmentCRUD:
    def test_save_and_get_assessment(self, store: AssessmentStore):
        aid = run(store.save_assessment(SAMPLE_ASSESSMENT))
        assert aid == "assess-001"
        result = run(store.get_assessment(aid))
        assert result is not None
        assert result["job_title"] == "Senior Engineer"
        assert result["company_name"] == "Acme Corp"
        assert result["overall_score"] == 82

    def test_get_nonexistent_returns_none(self, store: AssessmentStore):
        result = run(store.get_assessment("does-not-exist"))
        assert result is None

    def test_list_assessments(self, store: AssessmentStore):
        # Save multiple assessments
        for i in range(3):
            data = {**SAMPLE_ASSESSMENT, "assessment_id": f"assess-{i:03d}", "overall_score": 70 + i}
            run(store.save_assessment(data))

        results = run(store.list_assessments())
        assert len(results) == 3

    def test_list_with_limit(self, store: AssessmentStore):
        for i in range(5):
            data = {**SAMPLE_ASSESSMENT, "assessment_id": f"assess-{i:03d}"}
            run(store.save_assessment(data))

        results = run(store.list_assessments(limit=2))
        assert len(results) == 2

    def test_list_with_offset(self, store: AssessmentStore):
        for i in range(5):
            data = {**SAMPLE_ASSESSMENT, "assessment_id": f"assess-{i:03d}"}
            run(store.save_assessment(data))

        run(store.list_assessments())
        paged = run(store.list_assessments(limit=50, offset=2))
        assert len(paged) == 3

    def test_delete_assessment(self, store: AssessmentStore):
        run(store.save_assessment(SAMPLE_ASSESSMENT))
        deleted = run(store.delete_assessment("assess-001"))
        assert deleted is True
        assert run(store.get_assessment("assess-001")) is None

    def test_delete_nonexistent_returns_false(self, store: AssessmentStore):
        deleted = run(store.delete_assessment("no-such-id"))
        assert deleted is False

    def test_save_assessment_data_field_roundtrip(self, store: AssessmentStore):
        """The nested 'data' dict should survive a save/get round-trip."""
        run(store.save_assessment(SAMPLE_ASSESSMENT))
        result = run(store.get_assessment("assess-001"))
        assert result["data"]["summary"] == "Great fit"

    def test_save_assessment_returns_id(self, store: AssessmentStore):
        assessment_with_explicit_id = {**SAMPLE_ASSESSMENT, "assessment_id": "explicit-id-42"}
        returned_id = run(store.save_assessment(assessment_with_explicit_id))
        assert returned_id == "explicit-id-42"


# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------

class TestWatchlistCRUD:
    def test_add_to_watchlist(self, store: AssessmentStore):
        wid = run(store.add_to_watchlist(
            company_name="Startup Inc",
            job_title="Backend Engineer",
            posting_url="https://startup.io/jobs/be",
        ))
        assert isinstance(wid, int)
        assert wid > 0

    def test_list_watchlist_returns_entries(self, store: AssessmentStore):
        run(store.add_to_watchlist("Company A", "SWE", notes="Looks good"))
        run(store.add_to_watchlist("Company B", "Staff Eng"))
        results = run(store.list_watchlist())
        assert len(results) == 2

    def test_list_watchlist_filter_by_status(self, store: AssessmentStore):
        wid = run(store.add_to_watchlist("Company A", "SWE"))
        run(store.add_to_watchlist("Company B", "Staff Eng"))
        # Update one to 'applied'
        run(store.update_watchlist(wid, status="applied"))

        watching = run(store.list_watchlist(status="watching"))
        applied = run(store.list_watchlist(status="applied"))
        assert len(watching) == 1
        assert len(applied) == 1

    def test_update_watchlist_status(self, store: AssessmentStore):
        wid = run(store.add_to_watchlist("Acme", "DevOps Eng"))
        updated = run(store.update_watchlist(wid, status="applied"))
        assert updated is True

        results = run(store.list_watchlist())
        entry = next(r for r in results if r["id"] == wid)
        assert entry["status"] == "applied"

    def test_update_watchlist_notes(self, store: AssessmentStore):
        wid = run(store.add_to_watchlist("Acme", "DevOps Eng"))
        run(store.update_watchlist(wid, notes="Great culture"))

        results = run(store.list_watchlist())
        entry = next(r for r in results if r["id"] == wid)
        assert entry["notes"] == "Great culture"

    def test_update_nonexistent_watchlist_returns_false(self, store: AssessmentStore):
        result = run(store.update_watchlist(99999, status="applied"))
        assert result is False

    def test_remove_from_watchlist(self, store: AssessmentStore):
        wid = run(store.add_to_watchlist("Gone Corp", "Temp Role"))
        removed = run(store.remove_from_watchlist(wid))
        assert removed is True

        results = run(store.list_watchlist())
        assert all(r["id"] != wid for r in results)

    def test_remove_nonexistent_returns_false(self, store: AssessmentStore):
        result = run(store.remove_from_watchlist(99999))
        assert result is False

    def test_watchlist_default_status_is_watching(self, store: AssessmentStore):
        run(store.add_to_watchlist("NewCo", "Engineer"))
        results = run(store.list_watchlist())
        assert results[0]["status"] == "watching"

    def test_add_to_watchlist_with_assessment_id(self, store: AssessmentStore):
        run(store.save_assessment(SAMPLE_ASSESSMENT))
        wid = run(store.add_to_watchlist(
            company_name="Acme Corp",
            job_title="Senior Engineer",
            assessment_id="assess-001",
        ))
        results = run(store.list_watchlist())
        entry = next(r for r in results if r["id"] == wid)
        assert entry["assessment_id"] == "assess-001"


# ---------------------------------------------------------------------------
# Profile storage
# ---------------------------------------------------------------------------

class TestProfileStorage:
    def test_save_and_get_profile(self, store: AssessmentStore):
        data = {"name": "Alice", "skills": ["python", "rust"]}
        run(store.save_profile("candidate", "hash123", data))
        result = run(store.get_profile("candidate"))
        assert result is not None
        assert result["name"] == "Alice"
        assert "python" in result["skills"]

    def test_get_nonexistent_profile_returns_none(self, store: AssessmentStore):
        result = run(store.get_profile("resume"))
        assert result is None

    def test_profile_upsert(self, store: AssessmentStore):
        """Saving a profile twice should update, not duplicate."""
        run(store.save_profile("candidate", "hash_v1", {"version": 1}))
        run(store.save_profile("candidate", "hash_v2", {"version": 2}))
        result = run(store.get_profile("candidate"))
        assert result["version"] == 2

    def test_multiple_profile_types(self, store: AssessmentStore):
        run(store.save_profile("candidate", "h1", {"type": "candidate"}))
        run(store.save_profile("resume", "h2", {"type": "resume"}))

        candidate = run(store.get_profile("candidate"))
        resume = run(store.get_profile("resume"))
        assert candidate["type"] == "candidate"
        assert resume["type"] == "resume"
