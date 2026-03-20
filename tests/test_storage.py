"""Tests for SQLite storage layer (AssessmentStore)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from claude_candidate.storage import AssessmentStore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _event_loop():
    """Create a fresh event loop for each test so aiosqlite connections
    are always used on the loop that created them."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


def run(coro):
    """Run an async coroutine on the current thread's event loop."""
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(coro)


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
        assert "shortlist" in tables
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
# Shortlist CRUD
# ---------------------------------------------------------------------------

class TestShortlistCRUD:
    def test_add_to_shortlist(self, store: AssessmentStore):
        sid = run(store.add_to_shortlist(
            company_name="Startup Inc",
            job_title="Backend Engineer",
            posting_url="https://startup.io/jobs/be",
        ))
        assert isinstance(sid, int)
        assert sid > 0

    def test_list_shortlist_returns_entries(self, store: AssessmentStore):
        run(store.add_to_shortlist("Company A", "SWE", notes="Looks good"))
        run(store.add_to_shortlist("Company B", "Staff Eng"))
        results = run(store.list_shortlist())
        assert len(results) == 2

    def test_list_shortlist_filter_by_status(self, store: AssessmentStore):
        sid = run(store.add_to_shortlist("Company A", "SWE"))
        run(store.add_to_shortlist("Company B", "Staff Eng"))
        # Update one to 'applied'
        run(store.update_shortlist(sid, status="applied"))

        shortlisted = run(store.list_shortlist(status="shortlisted"))
        applied = run(store.list_shortlist(status="applied"))
        assert len(shortlisted) == 1
        assert len(applied) == 1

    def test_update_shortlist_status(self, store: AssessmentStore):
        sid = run(store.add_to_shortlist("Acme", "DevOps Eng"))
        updated = run(store.update_shortlist(sid, status="applied"))
        assert updated is True

        results = run(store.list_shortlist())
        entry = next(r for r in results if r["id"] == sid)
        assert entry["status"] == "applied"

    def test_update_shortlist_notes(self, store: AssessmentStore):
        sid = run(store.add_to_shortlist("Acme", "DevOps Eng"))
        run(store.update_shortlist(sid, notes="Great culture"))

        results = run(store.list_shortlist())
        entry = next(r for r in results if r["id"] == sid)
        assert entry["notes"] == "Great culture"

    def test_update_nonexistent_shortlist_returns_false(self, store: AssessmentStore):
        result = run(store.update_shortlist(99999, status="applied"))
        assert result is False

    def test_remove_from_shortlist(self, store: AssessmentStore):
        sid = run(store.add_to_shortlist("Gone Corp", "Temp Role"))
        removed = run(store.remove_from_shortlist(sid))
        assert removed is True

        results = run(store.list_shortlist())
        assert all(r["id"] != sid for r in results)

    def test_remove_nonexistent_returns_false(self, store: AssessmentStore):
        result = run(store.remove_from_shortlist(99999))
        assert result is False

    def test_shortlist_default_status_is_shortlisted(self, store: AssessmentStore):
        run(store.add_to_shortlist("NewCo", "Engineer"))
        results = run(store.list_shortlist())
        assert results[0]["status"] == "shortlisted"

    def test_add_to_shortlist_with_assessment_id(self, store: AssessmentStore):
        run(store.save_assessment(SAMPLE_ASSESSMENT))
        sid = run(store.add_to_shortlist(
            company_name="Acme Corp",
            job_title="Senior Engineer",
            assessment_id="assess-001",
        ))
        results = run(store.list_shortlist())
        entry = next(r for r in results if r["id"] == sid)
        assert entry["assessment_id"] == "assess-001"

    def test_add_to_shortlist_with_new_fields(self, store: AssessmentStore):
        sid = run(store.add_to_shortlist(
            company_name="TechCo",
            job_title="Staff Engineer",
            salary="$200k-$250k",
            location="San Francisco, CA",
            overall_grade="A-",
        ))
        results = run(store.list_shortlist())
        entry = next(r for r in results if r["id"] == sid)
        assert entry["salary"] == "$200k-$250k"
        assert entry["location"] == "San Francisco, CA"
        assert entry["overall_grade"] == "A-"

    def test_new_fields_default_to_none(self, store: AssessmentStore):
        sid = run(store.add_to_shortlist("MinimalCo", "Engineer"))
        results = run(store.list_shortlist())
        entry = next(r for r in results if r["id"] == sid)
        assert entry["salary"] is None
        assert entry["location"] is None
        assert entry["overall_grade"] is None


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


# ---------------------------------------------------------------------------
# Company research cache
# ---------------------------------------------------------------------------

class TestCompanyResearchCache:
    def test_cache_roundtrip(self, store: AssessmentStore):
        data = {"mission": "Build great things", "values": ["speed", "quality"]}
        run(store.cache_company_research("Acme Corp", data))
        result = run(store.get_cached_company_research("Acme Corp"))
        assert result is not None
        assert result["mission"] == "Build great things"
        assert result["values"] == ["speed", "quality"]

    def test_cache_miss_returns_none(self, store: AssessmentStore):
        result = run(store.get_cached_company_research("Nonexistent Inc"))
        assert result is None

    def test_cache_key_is_case_insensitive(self, store: AssessmentStore):
        data = {"mission": "Test"}
        run(store.cache_company_research("Acme Corp", data))
        result = run(store.get_cached_company_research("  acme corp  "))
        assert result is not None
        assert result["mission"] == "Test"

    def test_cache_upsert(self, store: AssessmentStore):
        run(store.cache_company_research("Acme", {"version": 1}))
        run(store.cache_company_research("Acme", {"version": 2}))
        result = run(store.get_cached_company_research("Acme"))
        assert result["version"] == 2
