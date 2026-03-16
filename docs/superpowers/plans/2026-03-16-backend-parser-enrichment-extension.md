# claude-candidate v0.2: Backend, Parser, Enrichment & Extension

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the four highest-priority features from HANDOFF.md — local FastAPI backend server, resume parser, company enrichment engine, and Chrome browser extension — transforming the working PoC into a daily-driver tool.

**Architecture:** The backend server exposes the existing QuickMatchEngine via HTTP endpoints with SQLite persistence. The resume parser extracts text from PDF/DOCX files and structures it into ResumeProfile. The enrichment engine fetches public company data and structures it into CompanyProfile. The browser extension extracts job posting text from job board pages and sends it to the local backend for assessment.

**Tech Stack:** Python 3.11+ / FastAPI / SQLite (aiosqlite) / pdfplumber / python-docx / httpx / Chrome Manifest V3 / TypeScript

---

## Dependency Graph

```
Task 1 (Storage)  ──→  Task 2 (Server)  ──→  Task 5 (Extension)
                                              Task 6 (Extension popup)
Task 3 (Resume Parser) ─── independent ───→  Task 2 uses it
Task 4 (Enrichment)    ─── independent ───→  Task 2 uses it
```

**Parallelizable:** Tasks 1, 3, 4 can run simultaneously. Task 2 follows Task 1. Tasks 5-6 follow Task 2.

---

## File Structure

### New Files
```
src/claude_candidate/
├── storage.py          # SQLite persistence (assessments, watchlist, profiles)
├── server.py           # FastAPI application with all endpoints
├── resume_parser.py    # PDF/DOCX text extraction → ResumeProfile
├── enrichment.py       # Company data fetching → CompanyProfile

tests/
├── test_storage.py     # Storage layer tests
├── test_server.py      # API endpoint tests (httpx AsyncClient)
├── test_resume_parser.py  # Parser extraction tests
├── test_enrichment.py  # Enrichment tests (mocked HTTP)

extension/
├── manifest.json       # Chrome Manifest V3
├── popup.html          # Extension popup UI
├── popup.css           # Popup styles
├── popup.js            # Popup logic
├── content.js          # Content script (job text extraction)
├── background.js       # Service worker
├── extractors/
│   ├── linkedin.js     # LinkedIn DOM extractor
│   ├── greenhouse.js   # Greenhouse extractor
│   ├── lever.js        # Lever extractor
│   ├── indeed.js       # Indeed extractor
│   └── generic.js      # Generic fallback extractor
└── icons/
    ├── icon16.png
    ├── icon48.png
    └── icon128.png
```

### Modified Files
```
src/claude_candidate/__init__.py    # bump version to 0.2.0
src/claude_candidate/cli.py         # add server start/stop commands, resume ingest
pyproject.toml                      # add aiosqlite dependency
```

---

## Chunk 1: Storage & Server

### Task 1: SQLite Storage Layer

**Files:**
- Create: `src/claude_candidate/storage.py`
- Create: `tests/test_storage.py`
- Modify: `pyproject.toml` (add aiosqlite)

- [ ] **Step 1: Add aiosqlite dependency**

In `pyproject.toml`, add `aiosqlite>=0.20` to the dependencies list.

Run: `source .venv/bin/activate && pip install -e ".[dev]"`

- [ ] **Step 2: Write failing tests for storage initialization**

```python
# tests/test_storage.py
"""Tests for SQLite storage layer."""
import asyncio
import json
import pytest
from pathlib import Path
from datetime import datetime, timezone

from claude_candidate.storage import AssessmentStore


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def store(db_path):
    s = AssessmentStore(db_path)
    asyncio.get_event_loop().run_until_complete(s.initialize())
    yield s
    asyncio.get_event_loop().run_until_complete(s.close())


class TestStoreInitialization:
    def test_creates_database_file(self, store, db_path):
        assert db_path.exists()

    def test_creates_tables(self, store):
        tables = asyncio.get_event_loop().run_until_complete(store.list_tables())
        assert "assessments" in tables
        assert "watchlist" in tables
        assert "profiles" in tables

    def test_idempotent_init(self, store):
        # Second init should not error
        asyncio.get_event_loop().run_until_complete(store.initialize())
```

Run: `source .venv/bin/activate && python -m pytest tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_candidate.storage'`

- [ ] **Step 3: Implement storage initialization**

```python
# src/claude_candidate/storage.py
"""SQLite persistence for assessments, watchlist, and profile metadata."""
from __future__ import annotations

import json
import aiosqlite
from pathlib import Path
from datetime import datetime, timezone
from typing import Any


class AssessmentStore:
    """Async SQLite storage for claude-candidate data."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        """Create database and tables if they don't exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = await aiosqlite.connect(str(self.db_path))
        self._db.row_factory = aiosqlite.Row
        await self._create_tables()

    async def _create_tables(self) -> None:
        assert self._db is not None
        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS assessments (
                assessment_id TEXT PRIMARY KEY,
                assessed_at TEXT NOT NULL,
                job_title TEXT NOT NULL,
                company_name TEXT NOT NULL,
                posting_url TEXT,
                overall_score REAL NOT NULL,
                overall_grade TEXT NOT NULL,
                should_apply TEXT NOT NULL,
                data JSON NOT NULL,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS watchlist (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company_name TEXT NOT NULL,
                job_title TEXT NOT NULL,
                posting_url TEXT,
                assessment_id TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'watching',
                added_at TEXT NOT NULL DEFAULT (datetime('now')),
                FOREIGN KEY (assessment_id) REFERENCES assessments(assessment_id)
            );

            CREATE TABLE IF NOT EXISTS profiles (
                profile_type TEXT PRIMARY KEY,
                profile_hash TEXT NOT NULL,
                data JSON NOT NULL,
                updated_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_assessments_company
                ON assessments(company_name);
            CREATE INDEX IF NOT EXISTS idx_assessments_score
                ON assessments(overall_score DESC);
            CREATE INDEX IF NOT EXISTS idx_watchlist_status
                ON watchlist(status);
        """)
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def list_tables(self) -> list[str]:
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
        rows = await cursor.fetchall()
        return [row[0] for row in rows]
```

Run: `source .venv/bin/activate && python -m pytest tests/test_storage.py -v`
Expected: PASS (3 tests)

- [ ] **Step 4: Write failing tests for assessment CRUD**

Add to `tests/test_storage.py`:

```python
class TestAssessmentCRUD:
    def _make_assessment_data(self, assessment_id="test-001", company="Acme", title="Engineer"):
        return {
            "assessment_id": assessment_id,
            "assessed_at": datetime.now(timezone.utc).isoformat(),
            "job_title": title,
            "company_name": company,
            "posting_url": "https://example.com/jobs/1",
            "overall_score": 0.78,
            "overall_grade": "B",
            "should_apply": "yes",
            "overall_summary": "Good fit",
            "skill_match": {"dimension": "skill_match", "score": 0.8, "grade": "B+", "weight": 0.333, "summary": "Strong", "details": []},
            "mission_alignment": {"dimension": "mission_alignment", "score": 0.7, "grade": "B-", "weight": 0.333, "summary": "Good", "details": []},
            "culture_fit": {"dimension": "culture_fit", "score": 0.5, "grade": "C", "weight": 0.333, "summary": "Neutral", "details": []},
        }

    def test_save_and_get_assessment(self, store):
        loop = asyncio.get_event_loop()
        data = self._make_assessment_data()
        loop.run_until_complete(store.save_assessment(data))
        result = loop.run_until_complete(store.get_assessment("test-001"))
        assert result is not None
        assert result["assessment_id"] == "test-001"
        assert result["company_name"] == "Acme"

    def test_get_nonexistent_assessment(self, store):
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(store.get_assessment("nonexistent"))
        assert result is None

    def test_list_assessments(self, store):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(store.save_assessment(self._make_assessment_data("a1", "Acme", "Eng")))
        loop.run_until_complete(store.save_assessment(self._make_assessment_data("a2", "Beta", "Lead")))
        results = loop.run_until_complete(store.list_assessments())
        assert len(results) == 2

    def test_list_assessments_with_limit(self, store):
        loop = asyncio.get_event_loop()
        for i in range(5):
            loop.run_until_complete(store.save_assessment(
                self._make_assessment_data(f"a{i}", f"Company{i}", "Eng")
            ))
        results = loop.run_until_complete(store.list_assessments(limit=3))
        assert len(results) == 3

    def test_delete_assessment(self, store):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(store.save_assessment(self._make_assessment_data()))
        deleted = loop.run_until_complete(store.delete_assessment("test-001"))
        assert deleted is True
        result = loop.run_until_complete(store.get_assessment("test-001"))
        assert result is None
```

Run: `source .venv/bin/activate && python -m pytest tests/test_storage.py::TestAssessmentCRUD -v`
Expected: FAIL — `AttributeError: 'AssessmentStore' object has no attribute 'save_assessment'`

- [ ] **Step 5: Implement assessment CRUD methods**

Add to `AssessmentStore` class in `src/claude_candidate/storage.py`:

```python
    async def save_assessment(self, assessment_data: dict[str, Any]) -> str:
        """Save a FitAssessment as JSON. Returns assessment_id."""
        assert self._db is not None
        aid = assessment_data["assessment_id"]
        await self._db.execute(
            """INSERT OR REPLACE INTO assessments
               (assessment_id, assessed_at, job_title, company_name,
                posting_url, overall_score, overall_grade, should_apply, data)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                aid,
                assessment_data.get("assessed_at", datetime.now(timezone.utc).isoformat()),
                assessment_data["job_title"],
                assessment_data["company_name"],
                assessment_data.get("posting_url"),
                assessment_data["overall_score"],
                assessment_data["overall_grade"],
                assessment_data["should_apply"],
                json.dumps(assessment_data),
            ),
        )
        await self._db.commit()
        return aid

    async def get_assessment(self, assessment_id: str) -> dict[str, Any] | None:
        """Get a single assessment by ID."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT data FROM assessments WHERE assessment_id = ?",
            (assessment_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    async def list_assessments(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """List assessments ordered by most recent first."""
        assert self._db is not None
        cursor = await self._db.execute(
            """SELECT assessment_id, assessed_at, job_title, company_name,
                      overall_score, overall_grade, should_apply
               FROM assessments ORDER BY assessed_at DESC LIMIT ? OFFSET ?""",
            (limit, offset),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def delete_assessment(self, assessment_id: str) -> bool:
        """Delete an assessment. Returns True if deleted."""
        assert self._db is not None
        cursor = await self._db.execute(
            "DELETE FROM assessments WHERE assessment_id = ?",
            (assessment_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0
```

Run: `source .venv/bin/activate && python -m pytest tests/test_storage.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Write failing tests for watchlist CRUD**

Add to `tests/test_storage.py`:

```python
class TestWatchlistCRUD:
    def test_add_to_watchlist(self, store):
        loop = asyncio.get_event_loop()
        wid = loop.run_until_complete(store.add_to_watchlist(
            company_name="Acme Corp",
            job_title="Senior Engineer",
            posting_url="https://acme.com/jobs/1",
            notes="Looks promising"
        ))
        assert isinstance(wid, int)

    def test_list_watchlist(self, store):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(store.add_to_watchlist("Acme", "Eng"))
        loop.run_until_complete(store.add_to_watchlist("Beta", "Lead"))
        items = loop.run_until_complete(store.list_watchlist())
        assert len(items) == 2

    def test_update_watchlist_status(self, store):
        loop = asyncio.get_event_loop()
        wid = loop.run_until_complete(store.add_to_watchlist("Acme", "Eng"))
        updated = loop.run_until_complete(store.update_watchlist(wid, status="applied"))
        assert updated is True
        items = loop.run_until_complete(store.list_watchlist())
        assert items[0]["status"] == "applied"

    def test_remove_from_watchlist(self, store):
        loop = asyncio.get_event_loop()
        wid = loop.run_until_complete(store.add_to_watchlist("Acme", "Eng"))
        deleted = loop.run_until_complete(store.remove_from_watchlist(wid))
        assert deleted is True
        items = loop.run_until_complete(store.list_watchlist())
        assert len(items) == 0
```

Run: `source .venv/bin/activate && python -m pytest tests/test_storage.py::TestWatchlistCRUD -v`
Expected: FAIL

- [ ] **Step 7: Implement watchlist CRUD methods**

Add to `AssessmentStore` class:

```python
    async def add_to_watchlist(
        self,
        company_name: str,
        job_title: str,
        posting_url: str | None = None,
        assessment_id: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Add a job to the watchlist. Returns the watchlist item ID."""
        assert self._db is not None
        cursor = await self._db.execute(
            """INSERT INTO watchlist
               (company_name, job_title, posting_url, assessment_id, notes)
               VALUES (?, ?, ?, ?, ?)""",
            (company_name, job_title, posting_url, assessment_id, notes),
        )
        await self._db.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def list_watchlist(
        self, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List watchlist items, optionally filtered by status."""
        assert self._db is not None
        if status:
            cursor = await self._db.execute(
                "SELECT * FROM watchlist WHERE status = ? ORDER BY added_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cursor = await self._db.execute(
                "SELECT * FROM watchlist ORDER BY added_at DESC LIMIT ?",
                (limit,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]

    async def update_watchlist(
        self,
        watchlist_id: int,
        status: str | None = None,
        notes: str | None = None,
        assessment_id: str | None = None,
    ) -> bool:
        """Update a watchlist item. Returns True if updated."""
        assert self._db is not None
        updates = []
        params: list[Any] = []
        if status is not None:
            updates.append("status = ?")
            params.append(status)
        if notes is not None:
            updates.append("notes = ?")
            params.append(notes)
        if assessment_id is not None:
            updates.append("assessment_id = ?")
            params.append(assessment_id)
        if not updates:
            return False
        params.append(watchlist_id)
        cursor = await self._db.execute(
            f"UPDATE watchlist SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        await self._db.commit()
        return cursor.rowcount > 0

    async def remove_from_watchlist(self, watchlist_id: int) -> bool:
        """Remove a watchlist item. Returns True if removed."""
        assert self._db is not None
        cursor = await self._db.execute(
            "DELETE FROM watchlist WHERE id = ?",
            (watchlist_id,),
        )
        await self._db.commit()
        return cursor.rowcount > 0
```

Run: `source .venv/bin/activate && python -m pytest tests/test_storage.py -v`
Expected: PASS (12 tests)

- [ ] **Step 8: Write failing tests for profile storage**

Add to `tests/test_storage.py`:

```python
class TestProfileStorage:
    def test_save_and_get_profile(self, store):
        loop = asyncio.get_event_loop()
        profile_data = {"name": "test", "skills": ["python"]}
        loop.run_until_complete(store.save_profile("candidate", "abc123", profile_data))
        result = loop.run_until_complete(store.get_profile("candidate"))
        assert result is not None
        assert result["profile_hash"] == "abc123"
        assert result["data"]["name"] == "test"

    def test_get_nonexistent_profile(self, store):
        loop = asyncio.get_event_loop()
        result = loop.run_until_complete(store.get_profile("nonexistent"))
        assert result is None

    def test_update_profile(self, store):
        loop = asyncio.get_event_loop()
        loop.run_until_complete(store.save_profile("candidate", "abc123", {"v": 1}))
        loop.run_until_complete(store.save_profile("candidate", "def456", {"v": 2}))
        result = loop.run_until_complete(store.get_profile("candidate"))
        assert result["profile_hash"] == "def456"
        assert result["data"]["v"] == 2
```

- [ ] **Step 9: Implement profile storage methods**

Add to `AssessmentStore` class:

```python
    async def save_profile(
        self, profile_type: str, profile_hash: str, data: dict[str, Any]
    ) -> None:
        """Save or update a profile (candidate, resume, merged)."""
        assert self._db is not None
        await self._db.execute(
            """INSERT OR REPLACE INTO profiles (profile_type, profile_hash, data, updated_at)
               VALUES (?, ?, ?, datetime('now'))""",
            (profile_type, profile_hash, json.dumps(data)),
        )
        await self._db.commit()

    async def get_profile(self, profile_type: str) -> dict[str, Any] | None:
        """Get a profile by type."""
        assert self._db is not None
        cursor = await self._db.execute(
            "SELECT profile_hash, data FROM profiles WHERE profile_type = ?",
            (profile_type,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return {"profile_hash": row[0], "data": json.loads(row[1])}
```

Run: `source .venv/bin/activate && python -m pytest tests/test_storage.py -v`
Expected: PASS (15 tests)

- [ ] **Step 10: Commit storage layer**

```bash
git add src/claude_candidate/storage.py tests/test_storage.py pyproject.toml
git commit -m "Add SQLite storage layer with assessment, watchlist, and profile CRUD"
```

---

### Task 2: FastAPI Backend Server

**Files:**
- Create: `src/claude_candidate/server.py`
- Create: `tests/test_server.py`
- Modify: `src/claude_candidate/cli.py` (add server commands)

- [ ] **Step 1: Write failing tests for server health and profile status**

```python
# tests/test_server.py
"""Tests for FastAPI backend server."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock

from httpx import AsyncClient, ASGITransport
from claude_candidate.server import create_app


@pytest.fixture
def app(tmp_path):
    return create_app(data_dir=tmp_path)


@pytest.fixture
async def client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
class TestHealthEndpoint:
    async def test_health_check(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    async def test_health_includes_profile_status(self, client):
        resp = await client.get("/api/health")
        data = resp.json()
        assert "profile_loaded" in data


@pytest.mark.asyncio
class TestProfileStatus:
    async def test_no_profile_loaded(self, client):
        resp = await client.get("/api/profile/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["has_candidate_profile"] is False
        assert data["has_resume_profile"] is False
        assert data["has_merged_profile"] is False
```

Run: `source .venv/bin/activate && python -m pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_candidate.server'`

- [ ] **Step 2: Implement server skeleton with health and profile status**

```python
# src/claude_candidate/server.py
"""FastAPI backend server for claude-candidate."""
from __future__ import annotations

import json
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from claude_candidate import __version__
from claude_candidate.storage import AssessmentStore


class ProfileStatus(BaseModel):
    has_candidate_profile: bool = False
    has_resume_profile: bool = False
    has_merged_profile: bool = False
    candidate_profile_hash: str | None = None
    resume_profile_hash: str | None = None
    merged_profile_hash: str | None = None


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str = __version__
    profile_loaded: bool = False


def create_app(data_dir: Path | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if data_dir is None:
        data_dir = Path.home() / ".claude-candidate"

    store: AssessmentStore | None = None
    profile_cache: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal store
        data_dir.mkdir(parents=True, exist_ok=True)
        store = AssessmentStore(data_dir / "assessments.db")
        await store.initialize()

        # Auto-discover profiles
        for ptype, fname in [
            ("candidate", "candidate_profile.json"),
            ("resume", "resume_profile.json"),
            ("merged", "merged_profile.json"),
        ]:
            fpath = data_dir / fname
            if fpath.exists():
                profile_cache[ptype] = json.loads(fpath.read_text())

        yield
        if store:
            await store.close()

    app = FastAPI(
        title="claude-candidate",
        version=__version__,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "chrome-extension://*",
            "http://localhost:*",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health", response_model=HealthResponse)
    async def health():
        return HealthResponse(
            profile_loaded="merged" in profile_cache or "candidate" in profile_cache,
        )

    @app.get("/api/profile/status", response_model=ProfileStatus)
    async def profile_status():
        return ProfileStatus(
            has_candidate_profile="candidate" in profile_cache,
            has_resume_profile="resume" in profile_cache,
            has_merged_profile="merged" in profile_cache,
            candidate_profile_hash=profile_cache.get("candidate", {}).get("manifest_hash"),
            resume_profile_hash=profile_cache.get("resume", {}).get("source_file_hash"),
            merged_profile_hash=profile_cache.get("merged", {}).get("profile_hash"),
        )

    # Store the store and cache on the app for endpoint access
    app.state.store = None  # Set during lifespan
    app.state.profile_cache = profile_cache
    app.state.data_dir = data_dir

    # Re-wire store reference after lifespan sets it
    @app.middleware("http")
    async def inject_store(request, call_next):
        request.state.store = store
        return await call_next(request)

    return app
```

Run: `source .venv/bin/activate && python -m pytest tests/test_server.py -v`
Expected: PASS (3 tests)

- [ ] **Step 3: Write failing tests for the assess endpoint**

Add to `tests/test_server.py`:

```python
@pytest.fixture
def app_with_profile(tmp_path, sample_candidate_profile_json, sample_resume_profile_json):
    """App with pre-loaded profiles."""
    (tmp_path / "candidate_profile.json").write_text(sample_candidate_profile_json)
    (tmp_path / "resume_profile.json").write_text(sample_resume_profile_json)
    return create_app(data_dir=tmp_path)


@pytest.fixture
async def loaded_client(app_with_profile):
    transport = ASGITransport(app=app_with_profile)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
class TestAssessEndpoint:
    async def test_assess_with_posting_text(self, loaded_client, sample_job_posting_text, sample_requirements_json):
        resp = await loaded_client.post("/api/assess", json={
            "posting_text": sample_job_posting_text,
            "company": "TechCorp",
            "title": "Senior AI Engineer",
            "requirements": json.loads(sample_requirements_json),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "assessment_id" in data
        assert "overall_score" in data
        assert 0.0 <= data["overall_score"] <= 1.0
        assert data["company_name"] == "TechCorp"

    async def test_assess_without_profile(self, client):
        resp = await client.post("/api/assess", json={
            "posting_text": "We need a Python developer",
            "company": "Acme",
            "title": "Developer",
        })
        assert resp.status_code == 422  # No profile loaded

    async def test_assess_persists_result(self, loaded_client, sample_job_posting_text, sample_requirements_json):
        resp = await loaded_client.post("/api/assess", json={
            "posting_text": sample_job_posting_text,
            "company": "TechCorp",
            "title": "Senior AI Engineer",
            "requirements": json.loads(sample_requirements_json),
        })
        aid = resp.json()["assessment_id"]
        # Retrieve it
        resp2 = await loaded_client.get(f"/api/assessments/{aid}")
        assert resp2.status_code == 200
        assert resp2.json()["assessment_id"] == aid
```

Run: `source .venv/bin/activate && python -m pytest tests/test_server.py::TestAssessEndpoint -v`
Expected: FAIL

- [ ] **Step 4: Implement assess endpoint**

Add to `server.py` (inside `create_app`, after the profile_status endpoint):

```python
    from claude_candidate.schemas import (
        CandidateProfile, ResumeProfile, QuickRequirement,
        RequirementPriority, CompanyProfile,
    )
    from claude_candidate.merger import merge_profiles, merge_candidate_only
    from claude_candidate.quick_match import QuickMatchEngine

    class AssessRequest(BaseModel):
        posting_text: str
        company: str
        title: str
        posting_url: str | None = None
        requirements: list[dict[str, Any]] | None = None
        seniority: str = "unknown"
        culture_signals: list[str] | None = None
        tech_stack: list[str] | None = None

    @app.post("/api/assess")
    async def assess(req: AssessRequest):
        if "candidate" not in profile_cache and "merged" not in profile_cache:
            raise HTTPException(
                status_code=422,
                detail="No candidate profile loaded. Run 'claude-candidate profile' first.",
            )

        # Build merged profile if not cached
        if "merged" not in profile_cache:
            cp = CandidateProfile.from_json(json.dumps(profile_cache["candidate"]))
            if "resume" in profile_cache:
                rp = ResumeProfile.from_json(json.dumps(profile_cache["resume"]))
                merged = merge_profiles(cp, rp)
            else:
                merged = merge_candidate_only(cp)
            profile_cache["merged_obj"] = merged
        elif "merged_obj" not in profile_cache:
            from claude_candidate.schemas.merged_profile import MergedEvidenceProfile
            profile_cache["merged_obj"] = MergedEvidenceProfile.from_json(
                json.dumps(profile_cache["merged"])
            )

        merged_profile = profile_cache["merged_obj"]

        # Build requirements
        if req.requirements:
            reqs = [
                QuickRequirement(
                    description=r.get("description", ""),
                    skill_mapping=r.get("skill_mapping", [r.get("description", "unknown")]),
                    priority=RequirementPriority(r.get("priority", "nice_to_have")),
                    source_text=r.get("source_text", ""),
                )
                for r in req.requirements
            ]
        else:
            # Basic extraction from posting text
            from claude_candidate.cli import _extract_basic_requirements
            reqs = _extract_basic_requirements(req.posting_text)

        engine = QuickMatchEngine(merged_profile)
        assessment = engine.assess(
            requirements=reqs,
            company=req.company,
            title=req.title,
            posting_url=req.posting_url,
            seniority=req.seniority,
            culture_signals=req.culture_signals,
            tech_stack=req.tech_stack,
        )

        # Persist
        assessment_data = json.loads(assessment.to_json())
        assert store is not None
        await store.save_assessment(assessment_data)

        return assessment_data

    @app.get("/api/assessments/{assessment_id}")
    async def get_assessment(assessment_id: str):
        assert store is not None
        result = await store.get_assessment(assessment_id)
        if result is None:
            raise HTTPException(status_code=404, detail="Assessment not found")
        return result

    @app.get("/api/assessments")
    async def list_assessments(limit: int = 50, offset: int = 0):
        assert store is not None
        return await store.list_assessments(limit=limit, offset=offset)

    @app.delete("/api/assessments/{assessment_id}")
    async def delete_assessment(assessment_id: str):
        assert store is not None
        deleted = await store.delete_assessment(assessment_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Assessment not found")
        return {"deleted": True}
```

Run: `source .venv/bin/activate && python -m pytest tests/test_server.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Write failing tests for watchlist endpoints**

Add to `tests/test_server.py`:

```python
@pytest.mark.asyncio
class TestWatchlistEndpoints:
    async def test_add_to_watchlist(self, client):
        resp = await client.post("/api/watchlist", json={
            "company_name": "Acme",
            "job_title": "Engineer",
            "posting_url": "https://acme.com/jobs/1",
        })
        assert resp.status_code == 200
        assert "id" in resp.json()

    async def test_list_watchlist(self, client):
        await client.post("/api/watchlist", json={"company_name": "A", "job_title": "E1"})
        await client.post("/api/watchlist", json={"company_name": "B", "job_title": "E2"})
        resp = await client.get("/api/watchlist")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_update_watchlist(self, client):
        resp = await client.post("/api/watchlist", json={"company_name": "A", "job_title": "E"})
        wid = resp.json()["id"]
        resp2 = await client.patch(f"/api/watchlist/{wid}", json={"status": "applied"})
        assert resp2.status_code == 200

    async def test_delete_from_watchlist(self, client):
        resp = await client.post("/api/watchlist", json={"company_name": "A", "job_title": "E"})
        wid = resp.json()["id"]
        resp2 = await client.delete(f"/api/watchlist/{wid}")
        assert resp2.status_code == 200
```

- [ ] **Step 6: Implement watchlist endpoints**

Add to `server.py` (inside `create_app`):

```python
    class WatchlistAddRequest(BaseModel):
        company_name: str
        job_title: str
        posting_url: str | None = None
        assessment_id: str | None = None
        notes: str | None = None

    class WatchlistUpdateRequest(BaseModel):
        status: str | None = None
        notes: str | None = None
        assessment_id: str | None = None

    @app.post("/api/watchlist")
    async def add_to_watchlist(req: WatchlistAddRequest):
        assert store is not None
        wid = await store.add_to_watchlist(
            company_name=req.company_name,
            job_title=req.job_title,
            posting_url=req.posting_url,
            assessment_id=req.assessment_id,
            notes=req.notes,
        )
        return {"id": wid}

    @app.get("/api/watchlist")
    async def list_watchlist(status: str | None = None, limit: int = 50):
        assert store is not None
        return await store.list_watchlist(status=status, limit=limit)

    @app.patch("/api/watchlist/{watchlist_id}")
    async def update_watchlist(watchlist_id: int, req: WatchlistUpdateRequest):
        assert store is not None
        updated = await store.update_watchlist(
            watchlist_id, status=req.status, notes=req.notes,
            assessment_id=req.assessment_id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Watchlist item not found")
        return {"updated": True}

    @app.delete("/api/watchlist/{watchlist_id}")
    async def delete_from_watchlist(watchlist_id: int):
        assert store is not None
        deleted = await store.remove_from_watchlist(watchlist_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Watchlist item not found")
        return {"deleted": True}
```

Run: `source .venv/bin/activate && python -m pytest tests/test_server.py -v`
Expected: PASS (10 tests)

- [ ] **Step 7: Add server CLI commands**

Add to `src/claude_candidate/cli.py` — a `server` group with `start` and `stop` commands:

```python
@main.group()
def server():
    """Manage the local backend server."""
    pass

@server.command("start")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", default=7429, help="Port to bind to")
@click.option("--data-dir", type=click.Path(), default=None, help="Data directory")
def server_start(host, port, data_dir):
    """Start the local backend server."""
    import uvicorn
    from claude_candidate.server import create_app

    data_path = Path(data_dir) if data_dir else Path.home() / ".claude-candidate"
    app = create_app(data_dir=data_path)
    click.echo(f"Starting claude-candidate server on {host}:{port}")
    click.echo(f"Data directory: {data_path}")
    uvicorn.run(app, host=host, port=port)
```

- [ ] **Step 8: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All tests pass (91 existing + new server/storage tests)

- [ ] **Step 9: Commit server**

```bash
git add src/claude_candidate/server.py tests/test_server.py src/claude_candidate/cli.py
git commit -m "Add FastAPI backend server with assess, watchlist, and profile endpoints"
```

---

## Chunk 2: Resume Parser & Company Enrichment

### Task 3: Resume Parser

**Files:**
- Create: `src/claude_candidate/resume_parser.py`
- Create: `tests/test_resume_parser.py`
- Create: `tests/fixtures/sample_resume.txt` (plain text fixture for testing)

- [ ] **Step 1: Create plain text resume fixture**

Create `tests/fixtures/sample_resume.txt` with a realistic plain-text resume matching the sample_resume_profile.json fixture data. This provides a testable input without needing actual PDF/DOCX files.

```text
BRIAN RUGGIERI
Senior Software Engineer
San Francisco, CA

SUMMARY
Full-stack engineer with 8+ years of experience in Python, TypeScript, and cloud infrastructure.
Passionate about developer tooling, AI/ML systems, and open-source software.

EXPERIENCE

Senior Software Engineer | TechCorp Inc.
January 2022 - Present
- Architected and deployed microservices handling 50M+ requests/day using Python and FastAPI
- Led migration from monolithic architecture to event-driven system, reducing latency by 40%
- Built internal developer tools used by 200+ engineers
- Technologies: Python, FastAPI, PostgreSQL, Redis, Docker, Kubernetes, AWS

Software Engineer | StartupCo
March 2019 - December 2021
- Developed full-stack web applications using React and Node.js
- Implemented CI/CD pipelines reducing deployment time from hours to minutes
- Built data pipeline processing 10TB+ daily using Apache Spark
- Technologies: TypeScript, React, Node.js, PostgreSQL, Apache Spark, GCP

SKILLS
Python, TypeScript, JavaScript, React, FastAPI, PostgreSQL, Redis, Docker, Kubernetes,
AWS, GCP, Apache Spark, Git, CI/CD, Microservices, REST APIs

EDUCATION
B.S. Computer Science, University of California, Berkeley, 2018

CERTIFICATIONS
AWS Solutions Architect Associate, 2023
```

- [ ] **Step 2: Write failing tests for text extraction**

```python
# tests/test_resume_parser.py
"""Tests for resume parser."""
import pytest
from pathlib import Path

from claude_candidate.resume_parser import (
    extract_text_from_file,
    parse_resume_text,
    ingest_resume,
)
from claude_candidate.schemas import ResumeProfile


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestTextExtraction:
    def test_extract_from_txt(self):
        text = extract_text_from_file(FIXTURES_DIR / "sample_resume.txt")
        assert "BRIAN RUGGIERI" in text
        assert "Python" in text
        assert len(text) > 100

    def test_extract_unsupported_format(self):
        with pytest.raises(ValueError, match="Unsupported"):
            extract_text_from_file(Path("fake.xyz"))

    def test_extract_missing_file(self):
        with pytest.raises(FileNotFoundError):
            extract_text_from_file(Path("/nonexistent/resume.txt"))


class TestResumeTextParsing:
    def test_parse_produces_resume_profile(self):
        text = extract_text_from_file(FIXTURES_DIR / "sample_resume.txt")
        profile = parse_resume_text(text, source_format="txt")
        assert isinstance(profile, ResumeProfile)
        assert profile.source_format == "txt"
        assert len(profile.skills) > 0

    def test_parse_extracts_skills(self):
        text = extract_text_from_file(FIXTURES_DIR / "sample_resume.txt")
        profile = parse_resume_text(text, source_format="txt")
        skill_names = {s.name for s in profile.skills}
        assert "python" in skill_names
        assert "typescript" in skill_names

    def test_parse_extracts_roles(self):
        text = extract_text_from_file(FIXTURES_DIR / "sample_resume.txt")
        profile = parse_resume_text(text, source_format="txt")
        assert len(profile.roles) >= 1
        companies = {r.company for r in profile.roles}
        assert "TechCorp Inc." in companies or any("TechCorp" in c for c in companies)

    def test_parse_extracts_name(self):
        text = extract_text_from_file(FIXTURES_DIR / "sample_resume.txt")
        profile = parse_resume_text(text, source_format="txt")
        assert profile.name is not None
        assert "BRIAN" in profile.name.upper() or "RUGGIERI" in profile.name.upper()


class TestIngestResume:
    def test_ingest_txt_file(self):
        profile = ingest_resume(FIXTURES_DIR / "sample_resume.txt")
        assert isinstance(profile, ResumeProfile)
        assert profile.source_format == "txt"
        assert len(profile.source_file_hash) == 64  # SHA-256

    def test_ingest_round_trip(self):
        profile = ingest_resume(FIXTURES_DIR / "sample_resume.txt")
        json_str = profile.to_json()
        restored = ResumeProfile.from_json(json_str)
        assert restored.name == profile.name
        assert len(restored.skills) == len(profile.skills)
```

Run: `source .venv/bin/activate && python -m pytest tests/test_resume_parser.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement resume parser with regex-based extraction**

The v0.1 parser uses regex/heuristic extraction (no Claude API calls). This keeps it fast, testable, and self-contained. Claude-powered parsing can be added in v0.2.

```python
# src/claude_candidate/resume_parser.py
"""Resume parser: extracts text from PDF/DOCX/TXT and structures into ResumeProfile."""
from __future__ import annotations

import re
from pathlib import Path
from datetime import datetime, timezone

from claude_candidate.manifest import hash_file, hash_string
from claude_candidate.schemas import ResumeProfile, ResumeSkill, ResumeRole
from claude_candidate.schemas.candidate_profile import DepthLevel


# Known skill patterns for normalization
SKILL_ALIASES: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "react.js": "react",
    "reactjs": "react",
    "node.js": "node",
    "nodejs": "node",
    "k8s": "kubernetes",
    "postgres": "postgresql",
    "mongo": "mongodb",
    "tf": "terraform",
    "py": "python",
}

# Common skill names to look for
KNOWN_SKILLS = {
    "python", "typescript", "javascript", "react", "node", "fastapi", "django",
    "flask", "postgresql", "mysql", "mongodb", "redis", "docker", "kubernetes",
    "aws", "gcp", "azure", "terraform", "git", "ci/cd", "graphql", "rest",
    "microservices", "apache-spark", "kafka", "elasticsearch", "nginx",
    "html", "css", "vue", "angular", "svelte", "rust", "go", "java",
    "c++", "c#", "swift", "kotlin", "ruby", "php", "scala", "haskell",
    "machine-learning", "deep-learning", "nlp", "computer-vision",
    "data-engineering", "data-science", "devops", "sre",
}


def extract_text_from_file(path: Path) -> str:
    """Extract text from a resume file (PDF, DOCX, or TXT)."""
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()

    if suffix == ".txt":
        return path.read_text(encoding="utf-8")
    elif suffix == ".pdf":
        return _extract_pdf(path)
    elif suffix == ".docx":
        return _extract_docx(path)
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Use .pdf, .docx, or .txt")


def _extract_pdf(path: Path) -> str:
    """Extract text from PDF using pdfplumber."""
    import pdfplumber

    parts: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                parts.append(text)
            for table in page.extract_tables():
                for row in table:
                    if row:
                        parts.append(" | ".join(cell or "" for cell in row))

    result = "\n\n".join(parts)
    if not result.strip():
        raise ValueError(
            "No text could be extracted from this PDF. "
            "It may be image-only (scanned). Please upload a text-based PDF or DOCX."
        )
    return result


def _extract_docx(path: Path) -> str:
    """Extract text from DOCX using python-docx."""
    from docx import Document

    doc = Document(str(path))
    parts: list[str] = []

    for para in doc.paragraphs:
        if para.text.strip():
            parts.append(para.text)

    for table in doc.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))

    return "\n\n".join(parts)


def parse_resume_text(text: str, source_format: str = "txt") -> ResumeProfile:
    """Parse extracted resume text into a structured ResumeProfile using heuristics."""
    lines = text.strip().split("\n")
    name = _extract_name(lines)
    roles = _extract_roles(text)
    skills = _extract_skills(text, roles)
    education = _extract_education(text)
    certifications = _extract_certifications(text)
    summary = _extract_summary(text)
    title = _extract_current_title(text, roles)

    return ResumeProfile(
        parsed_at=datetime.now(timezone.utc),
        source_file_hash=hash_string(text),
        source_format=source_format,
        name=name,
        current_title=title,
        location=_extract_location(lines),
        roles=roles,
        total_years_experience=_estimate_years(roles),
        skills=skills,
        education=education,
        certifications=certifications,
        professional_summary=summary,
    )


def ingest_resume(path: Path) -> ResumeProfile:
    """Full pipeline: extract text from file, parse into ResumeProfile."""
    text = extract_text_from_file(path)
    suffix = path.suffix.lower().lstrip(".")
    profile = parse_resume_text(text, source_format=suffix)
    # Override hash with file hash (not text hash)
    profile.source_file_hash = hash_file(path)
    return profile


def _extract_name(lines: list[str]) -> str | None:
    """Heuristic: first non-empty line that looks like a name."""
    for line in lines[:5]:
        line = line.strip()
        if not line:
            continue
        # Names are typically short, no special chars beyond spaces/hyphens
        if len(line) < 50 and re.match(r"^[A-Za-z\s\-'.]+$", line):
            # Skip common headers
            if line.upper() not in {"SUMMARY", "EXPERIENCE", "SKILLS", "EDUCATION", "RESUME"}:
                return line
    return None


def _extract_current_title(text: str, roles: list[ResumeRole]) -> str | None:
    """Get current title from roles or text."""
    # Check for title-like line near top
    for line in text.split("\n")[:10]:
        line = line.strip()
        if any(kw in line.lower() for kw in ["engineer", "developer", "architect", "manager", "lead", "director", "scientist"]):
            if len(line) < 60 and not any(c.isdigit() for c in line):
                return line
    if roles:
        return roles[0].title
    return None


def _extract_location(lines: list[str]) -> str | None:
    """Look for city/state pattern in first few lines."""
    loc_pattern = re.compile(
        r"([A-Z][a-zA-Z\s]+,\s*[A-Z]{2})\b"
    )
    for line in lines[:10]:
        match = loc_pattern.search(line)
        if match:
            return match.group(1).strip()
    return None


def _extract_summary(text: str) -> str | None:
    """Extract professional summary section."""
    patterns = [
        r"(?i)(?:SUMMARY|PROFILE|ABOUT|OBJECTIVE)\s*\n([\s\S]*?)(?=\n\s*(?:EXPERIENCE|SKILLS|EDUCATION|WORK|\n[A-Z]{3,}))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            summary = match.group(1).strip()
            if len(summary) > 20:
                return summary
    return None


def _extract_roles(text: str) -> list[ResumeRole]:
    """Extract work experience roles."""
    roles: list[ResumeRole] = []

    # Pattern: Title | Company  OR  Title at Company
    # Followed by date range
    role_pattern = re.compile(
        r"([A-Za-z\s]+(?:Engineer|Developer|Architect|Manager|Lead|Director|Scientist|Analyst|Designer|Consultant)[A-Za-z\s]*)"
        r"\s*[\|@at]+\s*"
        r"([A-Za-z\s&.,]+?)\s*\n"
        r"\s*([A-Za-z]+\s+\d{4})\s*[-–—]\s*((?:[A-Za-z]+\s+\d{4})|Present)",
        re.IGNORECASE,
    )

    for match in role_pattern.finditer(text):
        title = match.group(1).strip()
        company = match.group(2).strip()
        start = match.group(3).strip()
        end = match.group(4).strip()

        # Find bullets following the role
        role_end = match.end()
        next_section = text.find("\n\n", role_end + 50)
        if next_section == -1:
            next_section = len(text)
        role_text = text[role_end:next_section]

        achievements = []
        technologies: list[str] = []
        for line in role_text.split("\n"):
            line = line.strip()
            if line.startswith(("-", "•", "–", "*")):
                bullet = line.lstrip("-•–* ").strip()
                if bullet:
                    achievements.append(bullet)
            if line.lower().startswith("technologies:") or line.lower().startswith("tech:"):
                tech_str = line.split(":", 1)[1].strip()
                technologies = [t.strip() for t in tech_str.split(",") if t.strip()]

        roles.append(ResumeRole(
            title=title,
            company=company,
            start_date=start,
            end_date=None if end.lower() == "present" else end,
            duration_months=None,
            description=" ".join(achievements[:2]) if achievements else "",
            technologies=technologies,
            achievements=achievements,
            domain=None,
        ))

    return roles


def _extract_skills(text: str, roles: list[ResumeRole]) -> list[ResumeSkill]:
    """Extract skills from skills section and role contexts."""
    skills_found: dict[str, ResumeSkill] = {}

    # Find skills section
    skills_section = ""
    skills_match = re.search(
        r"(?i)\bSKILLS?\b[:\s]*\n([\s\S]*?)(?=\n\s*(?:EXPERIENCE|EDUCATION|CERTIFICATION|PROJECT|\n[A-Z]{3,})|$)",
        text,
    )
    if skills_match:
        skills_section = skills_match.group(1)

    # Extract from skills section
    text_lower = text.lower()
    for skill in KNOWN_SKILLS:
        normalized = skill.lower().replace("-", "[ -]?")
        if re.search(r"\b" + normalized + r"\b", text_lower):
            # Determine depth from context
            in_skills_section = skill.lower() in skills_section.lower() if skills_section else False
            in_role = any(
                skill.lower() in " ".join(r.technologies).lower() or
                skill.lower() in " ".join(r.achievements).lower()
                for r in roles
            )

            if in_role and in_skills_section:
                depth = DepthLevel.APPLIED
            elif in_role:
                depth = DepthLevel.USED
            else:
                depth = DepthLevel.MENTIONED

            canonical = SKILL_ALIASES.get(skill.lower(), skill.lower())

            if canonical not in skills_found:
                skills_found[canonical] = ResumeSkill(
                    name=canonical,
                    source_context="skills section" if in_skills_section else "role description",
                    implied_depth=depth,
                    years_experience=None,
                    recency="current_role" if roles and any(
                        skill.lower() in " ".join(r.technologies).lower()
                        for r in roles[:1]
                    ) else "unknown",
                )

    # Also check for raw comma-separated items in skills section
    if skills_section:
        for item in re.split(r"[,\n|•]", skills_section):
            item = item.strip().lower()
            if not item or len(item) > 30:
                continue
            canonical = SKILL_ALIASES.get(item, item.replace(" ", "-"))
            if canonical and canonical not in skills_found and len(canonical) > 1:
                skills_found[canonical] = ResumeSkill(
                    name=canonical,
                    source_context="skills section",
                    implied_depth=DepthLevel.MENTIONED,
                    years_experience=None,
                    recency="unknown",
                )

    return list(skills_found.values())


def _extract_education(text: str) -> list[str]:
    """Extract education entries."""
    education: list[str] = []
    edu_match = re.search(
        r"(?i)\bEDUCATION\b[:\s]*\n([\s\S]*?)(?=\n\s*(?:CERTIFICATION|SKILLS|EXPERIENCE|PROJECT|\n[A-Z]{3,})|$)",
        text,
    )
    if edu_match:
        for line in edu_match.group(1).split("\n"):
            line = line.strip()
            if line and len(line) > 10:
                education.append(line)
    return education


def _extract_certifications(text: str) -> list[str]:
    """Extract certification entries."""
    certs: list[str] = []
    cert_match = re.search(
        r"(?i)\bCERTIFICATION[S]?\b[:\s]*\n([\s\S]*?)(?=\n\s*(?:EDUCATION|SKILLS|EXPERIENCE|PROJECT|\n[A-Z]{3,})|$)",
        text,
    )
    if cert_match:
        for line in cert_match.group(1).split("\n"):
            line = line.strip()
            if line and len(line) > 5:
                certs.append(line)
    return certs


def _estimate_years(roles: list[ResumeRole]) -> float | None:
    """Estimate total years of experience from role dates."""
    if not roles:
        return None
    # Simple: difference between earliest start and latest end/now
    try:
        dates = []
        for role in roles:
            start_match = re.search(r"(\d{4})", role.start_date)
            if start_match:
                dates.append(int(start_match.group(1)))
        if dates:
            earliest = min(dates)
            return float(datetime.now().year - earliest)
    except (ValueError, AttributeError):
        pass
    return None
```

Run: `source .venv/bin/activate && python -m pytest tests/test_resume_parser.py -v`
Expected: PASS (8 tests)

- [ ] **Step 4: Add resume ingest CLI command**

Add to `src/claude_candidate/cli.py`, in a new `resume` command group:

```python
@main.group()
def resume():
    """Resume management commands."""
    pass

@resume.command("ingest")
@click.argument("resume_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None, help="Output path for ResumeProfile JSON")
def resume_ingest(resume_path, output):
    """Parse a resume file into a structured ResumeProfile."""
    from claude_candidate.resume_parser import ingest_resume

    path = Path(resume_path)
    click.echo(f"Ingesting resume: {path.name}")

    profile = ingest_resume(path)
    click.echo(f"  Name: {profile.name or 'Not detected'}")
    click.echo(f"  Title: {profile.current_title or 'Not detected'}")
    click.echo(f"  Skills found: {len(profile.skills)}")
    click.echo(f"  Roles found: {len(profile.roles)}")
    click.echo(f"  Education: {len(profile.education)} entries")
    click.echo(f"  File hash: {profile.source_file_hash[:16]}...")

    out_path = Path(output) if output else Path.home() / ".claude-candidate" / "resume_profile.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(profile.to_json())
    click.echo(f"  Saved to: {out_path}")
```

- [ ] **Step 5: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 6: Commit resume parser**

```bash
git add src/claude_candidate/resume_parser.py tests/test_resume_parser.py tests/fixtures/sample_resume.txt src/claude_candidate/cli.py
git commit -m "Add resume parser with PDF/DOCX/TXT extraction and CLI ingest command"
```

---

### Task 4: Company Enrichment Engine

**Files:**
- Create: `src/claude_candidate/enrichment.py`
- Create: `tests/test_enrichment.py`

- [ ] **Step 1: Write failing tests for enrichment**

```python
# tests/test_enrichment.py
"""Tests for company enrichment engine."""
import json
import pytest
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

from claude_candidate.enrichment import (
    CompanyEnrichmentEngine,
    fetch_page_text,
    extract_company_info,
)
from claude_candidate.schemas import CompanyProfile


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "company_cache"


@pytest.fixture
def engine(cache_dir):
    return CompanyEnrichmentEngine(cache_dir=cache_dir)


class TestExtractCompanyInfo:
    def test_extracts_from_about_page(self):
        html = """
        <html><body>
        <h1>About Acme Corp</h1>
        <p>We build developer tools that make engineering teams more productive.</p>
        <p>Our mission is to eliminate boilerplate and let developers focus on what matters.</p>
        <p>Tech stack: Python, TypeScript, React, PostgreSQL</p>
        <p>We are a remote-first company of 50 engineers.</p>
        </body></html>
        """
        info = extract_company_info("Acme Corp", html, "https://acme.com")
        assert info["company_name"] == "Acme Corp"
        assert len(info["product_description"]) > 0

    def test_extracts_tech_stack(self):
        html = "<p>We use Python, Go, and Kubernetes in production.</p>"
        info = extract_company_info("TestCo", html, "https://test.com")
        assert any("python" in t.lower() for t in info.get("tech_stack_public", []))


class TestCompanyEnrichmentEngine:
    def test_cache_miss_and_store(self, engine, cache_dir):
        # Manually write a cache file
        cache_dir.mkdir(parents=True, exist_ok=True)
        profile = CompanyProfile(
            company_name="Cached Corp",
            product_description="A test company",
            product_domain=["testing"],
            enriched_at=datetime.now(timezone.utc),
            sources=["manual"],
        )
        cache_file = cache_dir / "cached-corp.json"
        cache_file.write_text(profile.to_json())

        result = engine.get_cached("Cached Corp")
        assert result is not None
        assert result.company_name == "Cached Corp"

    def test_cache_miss_returns_none(self, engine):
        result = engine.get_cached("Unknown Corp")
        assert result is None

    def test_cache_expiry(self, engine, cache_dir):
        cache_dir.mkdir(parents=True, exist_ok=True)
        profile = CompanyProfile(
            company_name="Old Corp",
            product_description="Stale data",
            product_domain=["test"],
            enriched_at=datetime.now(timezone.utc) - timedelta(days=8),  # >7 day cache
            sources=["manual"],
        )
        cache_file = cache_dir / "old-corp.json"
        cache_file.write_text(profile.to_json())

        result = engine.get_cached("Old Corp", max_age_days=7)
        assert result is None  # Expired

    def test_build_profile_from_info(self, engine):
        info = {
            "company_name": "TestCo",
            "product_description": "Developer tools",
            "product_domain": ["devtools"],
            "tech_stack_public": ["python", "typescript"],
            "culture_keywords": ["remote-first", "open-source"],
            "remote_policy": "remote_first",
            "company_size": "50-200",
        }
        profile = engine.build_profile(info)
        assert isinstance(profile, CompanyProfile)
        assert profile.company_name == "TestCo"
        assert "python" in profile.tech_stack_public
```

Run: `source .venv/bin/activate && python -m pytest tests/test_enrichment.py -v`
Expected: FAIL

- [ ] **Step 2: Implement enrichment engine**

```python
# src/claude_candidate/enrichment.py
"""Company enrichment engine: fetches public company data and structures into CompanyProfile."""
from __future__ import annotations

import json
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import Any

from claude_candidate.schemas import CompanyProfile


# Known tech keywords to detect in page text
TECH_KEYWORDS = {
    "python", "typescript", "javascript", "react", "vue", "angular", "svelte",
    "node", "go", "golang", "rust", "java", "kotlin", "swift", "ruby",
    "php", "scala", "elixir", "haskell", "c++", "c#",
    "postgresql", "mysql", "mongodb", "redis", "elasticsearch", "dynamodb",
    "docker", "kubernetes", "terraform", "aws", "gcp", "azure",
    "kafka", "rabbitmq", "graphql", "grpc", "fastapi", "django", "flask",
    "next.js", "nuxt", "rails", "spring", "express",
}

CULTURE_KEYWORDS = {
    "remote-first", "remote friendly", "hybrid", "in-office",
    "open source", "open-source", "oss",
    "agile", "scrum", "kanban",
    "pair programming", "code review", "test-driven",
    "diversity", "inclusion", "equity",
    "work-life balance", "flexible hours", "unlimited pto",
    "startup", "fast-paced", "move fast",
    "collaborative", "autonomous", "self-directed",
    "documentation", "knowledge sharing",
}

REMOTE_POLICY_KEYWORDS = {
    "remote_first": ["remote-first", "remote first", "fully remote", "100% remote"],
    "hybrid": ["hybrid", "flexible location", "office optional"],
    "in_office": ["in-office", "on-site", "in office", "office-based"],
}


def fetch_page_text(url: str) -> str:
    """Synchronously fetch a URL and return extracted text."""
    import httpx
    from html.parser import HTMLParser

    resp = httpx.get(
        url,
        follow_redirects=True,
        timeout=15.0,
        headers={"User-Agent": "claude-candidate/0.2 (job-search-tool)"},
    )
    resp.raise_for_status()
    return _strip_html(resp.text)


def _strip_html(html: str) -> str:
    """Strip HTML tags and return plain text."""
    # Remove script and style tags
    text = re.sub(r"<(script|style)[^>]*>[\s\S]*?</\1>", "", html, flags=re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Normalize whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_company_info(company_name: str, page_text: str, url: str) -> dict[str, Any]:
    """Extract structured company information from page text using heuristics."""
    text_lower = page_text.lower()

    # Detect tech stack
    tech_found = []
    for tech in TECH_KEYWORDS:
        if re.search(r"\b" + re.escape(tech) + r"\b", text_lower):
            tech_found.append(tech)

    # Detect culture keywords
    culture_found = []
    for kw in CULTURE_KEYWORDS:
        if kw.lower() in text_lower:
            culture_found.append(kw)

    # Detect remote policy
    remote_policy = "unknown"
    for policy, keywords in REMOTE_POLICY_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            remote_policy = policy
            break

    # Extract product description (first substantial paragraph)
    sentences = re.split(r"[.!?]\s+", page_text)
    description_parts = []
    for s in sentences:
        s = s.strip()
        if len(s) > 30 and company_name.lower().split()[0] in s.lower():
            description_parts.append(s)
        if len(description_parts) >= 3:
            break
    product_description = ". ".join(description_parts) + "." if description_parts else f"Information about {company_name}"

    # Detect domains
    domain_keywords = {
        "devtools": ["developer tool", "dev tool", "developer experience", "dx"],
        "ai-ml": ["artificial intelligence", "machine learning", "ai", "ml", "llm", "large language model"],
        "fintech": ["fintech", "financial", "banking", "payments"],
        "healthcare": ["health", "medical", "clinical", "patient"],
        "e-commerce": ["e-commerce", "ecommerce", "marketplace", "shopping"],
        "security": ["security", "cybersecurity", "infosec"],
        "data": ["data platform", "data infrastructure", "analytics", "data engineering"],
        "cloud": ["cloud", "infrastructure", "iaas", "paas"],
        "saas": ["saas", "software as a service", "platform"],
    }

    domains_found = []
    for domain, keywords in domain_keywords.items():
        if any(kw in text_lower for kw in keywords):
            domains_found.append(domain)

    return {
        "company_name": company_name,
        "company_url": url,
        "product_description": product_description,
        "product_domain": domains_found or ["unknown"],
        "tech_stack_public": tech_found,
        "culture_keywords": culture_found,
        "remote_policy": remote_policy,
        "company_size": None,
        "sources": [url],
    }


class CompanyEnrichmentEngine:
    """Manages company data enrichment with caching."""

    def __init__(self, cache_dir: Path | None = None) -> None:
        self.cache_dir = cache_dir or (Path.home() / ".claude-candidate" / "company_cache")

    def _cache_key(self, company_name: str) -> str:
        """Normalize company name to cache filename."""
        return re.sub(r"[^a-z0-9]+", "-", company_name.lower()).strip("-")

    def _cache_path(self, company_name: str) -> Path:
        return self.cache_dir / f"{self._cache_key(company_name)}.json"

    def get_cached(
        self, company_name: str, max_age_days: int = 7
    ) -> CompanyProfile | None:
        """Get cached company profile if fresh enough."""
        path = self._cache_path(company_name)
        if not path.exists():
            return None

        try:
            profile = CompanyProfile.from_json(path.read_text())
            age = datetime.now(timezone.utc) - profile.enriched_at
            if age > timedelta(days=max_age_days):
                return None
            return profile
        except Exception:
            return None

    def save_cache(self, profile: CompanyProfile) -> None:
        """Save a company profile to cache."""
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_path(profile.company_name)
        path.write_text(profile.to_json())

    def build_profile(self, info: dict[str, Any]) -> CompanyProfile:
        """Build a CompanyProfile from extracted info dict."""
        enrichment_quality = "sparse"
        score = 0
        if info.get("tech_stack_public"):
            score += 1
        if info.get("culture_keywords"):
            score += 1
        if info.get("product_description") and len(info["product_description"]) > 50:
            score += 1
        if score >= 3:
            enrichment_quality = "rich"
        elif score >= 1:
            enrichment_quality = "moderate"

        return CompanyProfile(
            company_name=info["company_name"],
            company_url=info.get("company_url"),
            mission_statement=None,
            product_description=info.get("product_description", ""),
            product_domain=info.get("product_domain", []),
            tech_stack_public=info.get("tech_stack_public", []),
            culture_keywords=info.get("culture_keywords", []),
            remote_policy=info.get("remote_policy", "unknown"),
            company_size=info.get("company_size"),
            enriched_at=datetime.now(timezone.utc),
            sources=info.get("sources", []),
            enrichment_quality=enrichment_quality,
        )

    def enrich(self, company_name: str, company_url: str | None = None) -> CompanyProfile:
        """Enrich company data. Uses cache if available, fetches if not."""
        cached = self.get_cached(company_name)
        if cached:
            return cached

        if not company_url:
            # Return sparse profile without URL
            profile = CompanyProfile(
                company_name=company_name,
                product_description=f"No public information available for {company_name}",
                product_domain=["unknown"],
                enriched_at=datetime.now(timezone.utc),
                sources=[],
                enrichment_quality="sparse",
            )
            self.save_cache(profile)
            return profile

        try:
            page_text = fetch_page_text(company_url)
            info = extract_company_info(company_name, page_text, company_url)
            profile = self.build_profile(info)
            self.save_cache(profile)
            return profile
        except Exception:
            # Graceful degradation
            profile = CompanyProfile(
                company_name=company_name,
                company_url=company_url,
                product_description=f"Could not fetch data for {company_name}",
                product_domain=["unknown"],
                enriched_at=datetime.now(timezone.utc),
                sources=[],
                enrichment_quality="sparse",
            )
            self.save_cache(profile)
            return profile
```

Run: `source .venv/bin/activate && python -m pytest tests/test_enrichment.py -v`
Expected: PASS (5 tests)

- [ ] **Step 3: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: All pass

- [ ] **Step 4: Commit enrichment engine**

```bash
git add src/claude_candidate/enrichment.py tests/test_enrichment.py
git commit -m "Add company enrichment engine with caching and heuristic extraction"
```

---

## Chunk 3: Browser Extension

### Task 5: Chrome Extension Core

**Files:**
- Create: `extension/manifest.json`
- Create: `extension/background.js`
- Create: `extension/content.js`
- Create: `extension/extractors/linkedin.js`
- Create: `extension/extractors/greenhouse.js`
- Create: `extension/extractors/lever.js`
- Create: `extension/extractors/indeed.js`
- Create: `extension/extractors/generic.js`

- [ ] **Step 1: Create Chrome Manifest V3**

```json
// extension/manifest.json
{
  "manifest_version": 3,
  "name": "claude-candidate",
  "version": "0.2.0",
  "description": "Honest, evidence-backed job fit assessments from your Claude Code session logs",
  "permissions": [
    "activeTab",
    "storage"
  ],
  "host_permissions": [
    "http://localhost:7429/*"
  ],
  "background": {
    "service_worker": "background.js"
  },
  "content_scripts": [
    {
      "matches": [
        "*://*.linkedin.com/jobs/*",
        "*://*.greenhouse.io/*/jobs/*",
        "*://jobs.lever.co/*",
        "*://*.indeed.com/viewjob*",
        "*://*.indeed.com/jobs*"
      ],
      "js": ["content.js"],
      "run_at": "document_idle"
    }
  ],
  "action": {
    "default_popup": "popup.html",
    "default_icon": {
      "16": "icons/icon16.png",
      "48": "icons/icon48.png",
      "128": "icons/icon128.png"
    }
  },
  "icons": {
    "16": "icons/icon16.png",
    "48": "icons/icon48.png",
    "128": "icons/icon128.png"
  }
}
```

- [ ] **Step 2: Create job text extractors**

```javascript
// extension/extractors/linkedin.js
function extractLinkedIn() {
  const selectors = [
    '.jobs-description__content',
    '.jobs-box__html-content',
    '.description__text',
    '[class*="job-description"]',
    '#job-details',
  ];

  let text = '';
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el && el.innerText.trim().length > 50) {
      text = el.innerText.trim();
      break;
    }
  }

  const titleEl = document.querySelector('.jobs-unified-top-card__job-title, .top-card-layout__title, h1');
  const companyEl = document.querySelector('.jobs-unified-top-card__company-name, .topcard__org-name-link, [class*="company-name"]');

  return {
    title: titleEl ? titleEl.innerText.trim() : '',
    company: companyEl ? companyEl.innerText.trim() : '',
    description: text,
    url: window.location.href,
    source: 'linkedin',
  };
}
```

```javascript
// extension/extractors/greenhouse.js
function extractGreenhouse() {
  const contentEl = document.querySelector('#content, .content, [class*="job-post"]');
  const titleEl = document.querySelector('.app-title, h1');
  const companyEl = document.querySelector('.company-name, [class*="company"]');

  return {
    title: titleEl ? titleEl.innerText.trim() : '',
    company: companyEl ? companyEl.innerText.trim() : document.title.split(' - ').pop() || '',
    description: contentEl ? contentEl.innerText.trim() : '',
    url: window.location.href,
    source: 'greenhouse',
  };
}
```

```javascript
// extension/extractors/lever.js
function extractLever() {
  const contentEl = document.querySelector('.content, .section-wrapper, [class*="posting"]');
  const titleEl = document.querySelector('.posting-headline h2, h1');
  const companyEl = document.querySelector('.main-header-logo img, .posting-categories .location');

  return {
    title: titleEl ? titleEl.innerText.trim() : '',
    company: document.title.split(' - ').pop() || '',
    description: contentEl ? contentEl.innerText.trim() : '',
    url: window.location.href,
    source: 'lever',
  };
}
```

```javascript
// extension/extractors/indeed.js
function extractIndeed() {
  const selectors = [
    '#jobDescriptionText',
    '.jobsearch-jobDescriptionText',
    '[class*="job-description"]',
  ];

  let text = '';
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) {
      text = el.innerText.trim();
      break;
    }
  }

  const titleEl = document.querySelector('.jobsearch-JobInfoHeader-title, h1');
  const companyEl = document.querySelector('[data-company-name], .jobsearch-InlineCompanyRating-companyHeader');

  return {
    title: titleEl ? titleEl.innerText.trim() : '',
    company: companyEl ? companyEl.innerText.trim() : '',
    description: text,
    url: window.location.href,
    source: 'indeed',
  };
}
```

```javascript
// extension/extractors/generic.js
function extractGeneric() {
  // Heuristic: find the largest text block on the page
  const candidates = document.querySelectorAll('main, article, [role="main"], .content, #content, .job-description');
  let best = '';
  for (const el of candidates) {
    const text = el.innerText.trim();
    if (text.length > best.length) {
      best = text;
    }
  }

  // Fallback to body
  if (best.length < 100) {
    best = document.body.innerText.trim();
  }

  // Try to find title
  const h1 = document.querySelector('h1');

  return {
    title: h1 ? h1.innerText.trim() : document.title,
    company: '',
    description: best,
    url: window.location.href,
    source: 'generic',
  };
}
```

- [ ] **Step 3: Create content script**

```javascript
// extension/content.js
// Content script that extracts job posting text from supported job boards
(function() {
  'use strict';

  const hostname = window.location.hostname;

  function getExtractor() {
    if (hostname.includes('linkedin.com')) return extractLinkedIn;
    if (hostname.includes('greenhouse.io')) return extractGreenhouse;
    if (hostname.includes('lever.co')) return extractLever;
    if (hostname.includes('indeed.com')) return extractIndeed;
    return extractGeneric;
  }

  // Extractors are inlined here since content scripts can't import modules
  // LinkedIn
  function extractLinkedIn() {
    const selectors = ['.jobs-description__content', '.jobs-box__html-content', '.description__text', '[class*="job-description"]', '#job-details'];
    let text = '';
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.innerText.trim().length > 50) { text = el.innerText.trim(); break; }
    }
    const titleEl = document.querySelector('.jobs-unified-top-card__job-title, .top-card-layout__title, h1');
    const companyEl = document.querySelector('.jobs-unified-top-card__company-name, .topcard__org-name-link, [class*="company-name"]');
    return { title: titleEl ? titleEl.innerText.trim() : '', company: companyEl ? companyEl.innerText.trim() : '', description: text, url: window.location.href, source: 'linkedin' };
  }

  // Greenhouse
  function extractGreenhouse() {
    const contentEl = document.querySelector('#content, .content, [class*="job-post"]');
    const titleEl = document.querySelector('.app-title, h1');
    const companyEl = document.querySelector('.company-name, [class*="company"]');
    return { title: titleEl ? titleEl.innerText.trim() : '', company: companyEl ? companyEl.innerText.trim() : document.title.split(' - ').pop() || '', description: contentEl ? contentEl.innerText.trim() : '', url: window.location.href, source: 'greenhouse' };
  }

  // Lever
  function extractLever() {
    const contentEl = document.querySelector('.content, .section-wrapper, [class*="posting"]');
    const titleEl = document.querySelector('.posting-headline h2, h1');
    return { title: titleEl ? titleEl.innerText.trim() : '', company: document.title.split(' - ').pop() || '', description: contentEl ? contentEl.innerText.trim() : '', url: window.location.href, source: 'lever' };
  }

  // Indeed
  function extractIndeed() {
    const selectors = ['#jobDescriptionText', '.jobsearch-jobDescriptionText', '[class*="job-description"]'];
    let text = '';
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el) { text = el.innerText.trim(); break; }
    }
    const titleEl = document.querySelector('.jobsearch-JobInfoHeader-title, h1');
    const companyEl = document.querySelector('[data-company-name], .jobsearch-InlineCompanyRating-companyHeader');
    return { title: titleEl ? titleEl.innerText.trim() : '', company: companyEl ? companyEl.innerText.trim() : '', description: text, url: window.location.href, source: 'indeed' };
  }

  // Generic fallback
  function extractGeneric() {
    const candidates = document.querySelectorAll('main, article, [role="main"], .content, #content, .job-description');
    let best = '';
    for (const el of candidates) {
      const text = el.innerText.trim();
      if (text.length > best.length) best = text;
    }
    if (best.length < 100) best = document.body.innerText.trim();
    const h1 = document.querySelector('h1');
    return { title: h1 ? h1.innerText.trim() : document.title, company: '', description: best, url: window.location.href, source: 'generic' };
  }

  // Listen for messages from popup/background
  chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
    if (request.action === 'extractJobPosting') {
      const extractor = getExtractor();
      const result = extractor();
      sendResponse(result);
    }
    return true; // Keep channel open for async
  });

  // Auto-extract on load and store for popup
  const extractor = getExtractor();
  const posting = extractor();
  if (posting.description && posting.description.length > 50) {
    chrome.storage.local.set({
      currentPosting: posting,
      lastExtracted: Date.now(),
    });
  }
})();
```

- [ ] **Step 4: Create background service worker**

```javascript
// extension/background.js
// Service worker for claude-candidate extension
const BACKEND_URL = 'http://localhost:7429';

chrome.runtime.onMessage.addListener((request, sender, sendResponse) => {
  if (request.action === 'checkBackend') {
    fetch(`${BACKEND_URL}/api/health`)
      .then(r => r.json())
      .then(data => sendResponse({ connected: true, ...data }))
      .catch(() => sendResponse({ connected: false }));
    return true;
  }

  if (request.action === 'assess') {
    fetch(`${BACKEND_URL}/api/assess`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request.payload),
    })
      .then(r => r.json())
      .then(data => sendResponse({ success: true, data }))
      .catch(err => sendResponse({ success: false, error: err.message }));
    return true;
  }

  if (request.action === 'getAssessment') {
    fetch(`${BACKEND_URL}/api/assessments/${request.assessmentId}`)
      .then(r => r.json())
      .then(data => sendResponse({ success: true, data }))
      .catch(err => sendResponse({ success: false, error: err.message }));
    return true;
  }

  if (request.action === 'addToWatchlist') {
    fetch(`${BACKEND_URL}/api/watchlist`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(request.payload),
    })
      .then(r => r.json())
      .then(data => sendResponse({ success: true, data }))
      .catch(err => sendResponse({ success: false, error: err.message }));
    return true;
  }
});
```

- [ ] **Step 5: Create placeholder icons**

Use simple SVG-to-PNG or create minimal placeholder PNGs for the extension icons. These can be replaced with designed icons later.

Create simple 1-color PNG icons at 16x16, 48x48, 128x128 using Python:

```python
# Run this as a one-time script to generate placeholder icons
from PIL import Image, ImageDraw
for size in [16, 48, 128]:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = size // 8
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=size // 6,
        fill=(59, 130, 246),  # Blue
    )
    # Draw "C" letter
    draw.text((size // 3, size // 6), "C", fill="white")
    img.save(f"extension/icons/icon{size}.png")
```

- [ ] **Step 6: Commit extension core**

```bash
git add extension/
git commit -m "Add Chrome Manifest V3 extension with job board extractors"
```

---

### Task 6: Extension Popup UI

**Files:**
- Create: `extension/popup.html`
- Create: `extension/popup.css`
- Create: `extension/popup.js`

- [ ] **Step 1: Create popup HTML**

```html
<!-- extension/popup.html -->
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>claude-candidate</title>
  <link rel="stylesheet" href="popup.css">
</head>
<body>
  <div id="app">
    <!-- State: Loading -->
    <div id="state-loading" class="state">
      <div class="spinner"></div>
      <p>Connecting...</p>
    </div>

    <!-- State: No Backend -->
    <div id="state-no-backend" class="state hidden">
      <div class="icon-large">⚠</div>
      <h2>Backend Not Running</h2>
      <p>Start the claude-candidate server:</p>
      <code>claude-candidate server start</code>
    </div>

    <!-- State: No Profile -->
    <div id="state-no-profile" class="state hidden">
      <div class="icon-large">👤</div>
      <h2>No Profile Loaded</h2>
      <p>Create your candidate profile first:</p>
      <code>claude-candidate resume ingest resume.pdf</code>
    </div>

    <!-- State: Not on Job Page -->
    <div id="state-no-job" class="state hidden">
      <div class="icon-large">🔍</div>
      <h2>No Job Posting Found</h2>
      <p>Navigate to a job posting on LinkedIn, Greenhouse, Lever, Indeed, or any career page.</p>
      <button id="btn-manual-extract" class="btn-secondary">Try Manual Extract</button>
    </div>

    <!-- State: Assessing -->
    <div id="state-assessing" class="state hidden">
      <div class="spinner"></div>
      <p id="assess-status">Analyzing posting...</p>
      <div id="partial-results" class="hidden">
        <div class="partial-title" id="partial-title"></div>
      </div>
    </div>

    <!-- State: Results -->
    <div id="state-results" class="state hidden">
      <div class="result-header">
        <div class="company-title">
          <h2 id="result-company"></h2>
          <p id="result-title"></p>
        </div>
        <div class="overall-grade" id="result-grade"></div>
      </div>

      <div class="score-bar">
        <label>Skills</label>
        <div class="bar"><div class="bar-fill" id="bar-skills"></div></div>
        <span class="bar-grade" id="grade-skills"></span>
      </div>
      <div class="score-bar">
        <label>Mission</label>
        <div class="bar"><div class="bar-fill" id="bar-mission"></div></div>
        <span class="bar-grade" id="grade-mission"></span>
      </div>
      <div class="score-bar">
        <label>Culture</label>
        <div class="bar"><div class="bar-fill" id="bar-culture"></div></div>
        <span class="bar-grade" id="grade-culture"></span>
      </div>

      <div class="detail-row">
        <span class="detail-label">Must-haves:</span>
        <span id="result-must-haves"></span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Strongest:</span>
        <span id="result-strongest"></span>
      </div>
      <div class="detail-row">
        <span class="detail-label">Biggest gap:</span>
        <span id="result-gap"></span>
      </div>

      <div id="discoveries" class="hidden">
        <h3>Resume Gaps Discovered</h3>
        <ul id="discovery-list"></ul>
      </div>

      <div class="verdict" id="result-verdict"></div>

      <div class="actions">
        <button id="btn-watchlist" class="btn-primary">Save to Watchlist</button>
        <button id="btn-details" class="btn-secondary">Full Details</button>
      </div>
    </div>

    <!-- State: Error -->
    <div id="state-error" class="state hidden">
      <div class="icon-large">✕</div>
      <h2>Assessment Failed</h2>
      <p id="error-message"></p>
      <button id="btn-retry" class="btn-secondary">Retry</button>
    </div>
  </div>

  <script src="popup.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create popup CSS**

```css
/* extension/popup.css */
* { margin: 0; padding: 0; box-sizing: border-box; }

body {
  width: 400px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 13px;
  color: #1a1a2e;
  background: #f8f9fc;
}

#app { padding: 16px; }

.hidden { display: none !important; }

.state { text-align: center; }

/* Loading / Spinner */
.spinner {
  width: 32px; height: 32px;
  border: 3px solid #e2e8f0;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  margin: 24px auto 12px;
}
@keyframes spin { to { transform: rotate(360deg); } }

.icon-large { font-size: 36px; margin: 16px 0 8px; }

h2 { font-size: 16px; margin-bottom: 6px; font-weight: 600; }
h3 { font-size: 13px; margin: 12px 0 6px; font-weight: 600; color: #475569; }

code {
  display: block;
  background: #1e293b;
  color: #e2e8f0;
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 12px;
  margin-top: 8px;
  text-align: left;
  user-select: all;
}

/* Result card */
.result-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
  text-align: left;
}
.company-title h2 { font-size: 15px; color: #0f172a; }
.company-title p { font-size: 12px; color: #64748b; margin-top: 2px; }

.overall-grade {
  font-size: 28px;
  font-weight: 700;
  color: #3b82f6;
  line-height: 1;
}

/* Score bars */
.score-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  text-align: left;
}
.score-bar label {
  width: 52px;
  font-size: 11px;
  font-weight: 500;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.bar {
  flex: 1;
  height: 8px;
  background: #e2e8f0;
  border-radius: 4px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  border-radius: 4px;
  transition: width 0.6s ease;
  background: linear-gradient(90deg, #ef4444, #f59e0b, #22c55e);
}
.bar-grade {
  width: 24px;
  font-size: 11px;
  font-weight: 600;
  text-align: right;
}

/* Details */
.detail-row {
  display: flex;
  gap: 8px;
  font-size: 12px;
  margin-bottom: 4px;
  text-align: left;
}
.detail-label {
  font-weight: 600;
  color: #475569;
  white-space: nowrap;
}

/* Discoveries */
#discoveries {
  margin-top: 12px;
  padding: 8px;
  background: #f0fdf4;
  border-radius: 6px;
  border: 1px solid #bbf7d0;
  text-align: left;
}
#discovery-list {
  list-style: none;
  font-size: 12px;
}
#discovery-list li::before {
  content: '+ ';
  color: #16a34a;
  font-weight: 700;
}

/* Verdict */
.verdict {
  margin-top: 12px;
  padding: 8px 12px;
  border-radius: 6px;
  font-weight: 600;
  text-align: center;
}
.verdict.strong_yes, .verdict.yes { background: #f0fdf4; color: #16a34a; }
.verdict.maybe { background: #fefce8; color: #ca8a04; }
.verdict.probably_not, .verdict.no { background: #fef2f2; color: #dc2626; }

/* Buttons */
.actions {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.btn-primary, .btn-secondary {
  flex: 1;
  padding: 8px 12px;
  border: none;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
  cursor: pointer;
  transition: opacity 0.2s;
}
.btn-primary { background: #3b82f6; color: white; }
.btn-primary:hover { opacity: 0.9; }
.btn-secondary { background: #e2e8f0; color: #475569; }
.btn-secondary:hover { background: #cbd5e1; }
```

- [ ] **Step 3: Create popup JavaScript**

```javascript
// extension/popup.js
// Extension popup logic — manages 6 states
(function() {
  'use strict';

  const STATES = ['loading', 'no-backend', 'no-profile', 'no-job', 'assessing', 'results', 'error'];
  let currentAssessment = null;

  function showState(stateName) {
    STATES.forEach(s => {
      const el = document.getElementById(`state-${s}`);
      if (el) el.classList.toggle('hidden', s !== stateName);
    });
  }

  function setBarWidth(id, score) {
    const el = document.getElementById(id);
    if (el) el.style.width = `${Math.round(score * 100)}%`;
  }

  function renderResults(data) {
    currentAssessment = data;

    document.getElementById('result-company').textContent = data.company_name;
    document.getElementById('result-title').textContent = data.job_title;
    document.getElementById('result-grade').textContent = data.overall_grade;

    // Score bars
    setBarWidth('bar-skills', data.skill_match.score);
    setBarWidth('bar-mission', data.mission_alignment.score);
    setBarWidth('bar-culture', data.culture_fit.score);

    document.getElementById('grade-skills').textContent = data.skill_match.grade;
    document.getElementById('grade-mission').textContent = data.mission_alignment.grade;
    document.getElementById('grade-culture').textContent = data.culture_fit.grade;

    // Details
    document.getElementById('result-must-haves').textContent = data.must_have_coverage;
    document.getElementById('result-strongest').textContent = data.strongest_match;
    document.getElementById('result-gap').textContent = data.biggest_gap;

    // Discoveries
    const discoveriesEl = document.getElementById('discoveries');
    const discoveryList = document.getElementById('discovery-list');
    if (data.resume_gaps_discovered && data.resume_gaps_discovered.length > 0) {
      discoveryList.innerHTML = '';
      data.resume_gaps_discovered.forEach(skill => {
        const li = document.createElement('li');
        li.textContent = skill;
        discoveryList.appendChild(li);
      });
      discoveriesEl.classList.remove('hidden');
    } else {
      discoveriesEl.classList.add('hidden');
    }

    // Verdict
    const verdictEl = document.getElementById('result-verdict');
    const verdictLabels = {
      strong_yes: 'Strong Yes — Apply!',
      yes: 'Yes — Good Fit',
      maybe: 'Maybe — Review Gaps',
      probably_not: 'Probably Not — Significant Gaps',
      no: 'No — Poor Fit',
    };
    verdictEl.textContent = verdictLabels[data.should_apply] || data.should_apply;
    verdictEl.className = `verdict ${data.should_apply}`;

    showState('results');
  }

  async function initialize() {
    showState('loading');

    // Step 1: Check backend
    chrome.runtime.sendMessage({ action: 'checkBackend' }, (response) => {
      if (!response || !response.connected) {
        showState('no-backend');
        return;
      }

      // Step 2: Check profile
      if (!response.profile_loaded) {
        showState('no-profile');
        return;
      }

      // Step 3: Check for job posting
      chrome.storage.local.get(['currentPosting', 'lastExtracted'], (stored) => {
        const posting = stored.currentPosting;
        const age = Date.now() - (stored.lastExtracted || 0);

        if (!posting || !posting.description || posting.description.length < 50 || age > 300000) {
          // Try extracting from current tab
          chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
            if (!tabs[0]) { showState('no-job'); return; }
            chrome.tabs.sendMessage(tabs[0].id, { action: 'extractJobPosting' }, (result) => {
              if (chrome.runtime.lastError || !result || !result.description || result.description.length < 50) {
                showState('no-job');
              } else {
                runAssessment(result);
              }
            });
          });
        } else {
          runAssessment(posting);
        }
      });
    });
  }

  function runAssessment(posting) {
    showState('assessing');
    document.getElementById('assess-status').textContent = `Analyzing: ${posting.title || 'job posting'}...`;

    const partialTitle = document.getElementById('partial-title');
    if (posting.title) {
      partialTitle.textContent = `${posting.company} — ${posting.title}`;
      document.getElementById('partial-results').classList.remove('hidden');
    }

    chrome.runtime.sendMessage({
      action: 'assess',
      payload: {
        posting_text: posting.description,
        company: posting.company || 'Unknown Company',
        title: posting.title || 'Unknown Position',
        posting_url: posting.url,
      }
    }, (response) => {
      if (response && response.success) {
        renderResults(response.data);
      } else {
        document.getElementById('error-message').textContent =
          response ? response.error : 'Could not connect to backend';
        showState('error');
      }
    });
  }

  // Event listeners
  document.getElementById('btn-watchlist')?.addEventListener('click', () => {
    if (!currentAssessment) return;
    chrome.runtime.sendMessage({
      action: 'addToWatchlist',
      payload: {
        company_name: currentAssessment.company_name,
        job_title: currentAssessment.job_title,
        posting_url: currentAssessment.posting_url,
        assessment_id: currentAssessment.assessment_id,
      }
    }, (response) => {
      const btn = document.getElementById('btn-watchlist');
      if (response && response.success) {
        btn.textContent = 'Saved!';
        btn.disabled = true;
      }
    });
  });

  document.getElementById('btn-manual-extract')?.addEventListener('click', () => {
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (!tabs[0]) return;
      chrome.tabs.sendMessage(tabs[0].id, { action: 'extractJobPosting' }, (result) => {
        if (result && result.description && result.description.length > 50) {
          runAssessment(result);
        }
      });
    });
  });

  document.getElementById('btn-retry')?.addEventListener('click', initialize);

  // Start
  initialize();
})();
```

- [ ] **Step 4: Generate placeholder icons**

Run a Python script to generate simple placeholder PNG icons:

```bash
source .venv/bin/activate && python -c "
from PIL import Image, ImageDraw, ImageFont
for size in [16, 48, 128]:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    m = max(1, size // 8)
    draw.rounded_rectangle([m, m, size-m, size-m], radius=max(1, size//6), fill=(59, 130, 246))
    fs = max(8, size // 2)
    draw.text((size//4, size//8), 'C', fill='white')
    img.save(f'extension/icons/icon{size}.png')
print('Icons generated')
"
```

- [ ] **Step 5: Commit extension popup**

```bash
git add extension/
git commit -m "Add extension popup UI with 6-state flow and fit assessment card"
```

---

## Chunk 4: Integration & Version Bump

### Task 7: Wire Everything Together

**Files:**
- Modify: `src/claude_candidate/__init__.py` (version bump)
- Modify: `src/claude_candidate/cli.py` (resume commands)
- Modify: `pyproject.toml` (version bump)

- [ ] **Step 1: Update version to 0.2.0**

In `src/claude_candidate/__init__.py`: change `__version__ = "0.1.0"` to `__version__ = "0.2.0"`
In `pyproject.toml`: change `version = "0.1.0"` to `version = "0.2.0"`

- [ ] **Step 2: Run full test suite**

Run: `source .venv/bin/activate && python -m pytest tests/ -v`
Expected: ALL pass (91 original + new storage/server/parser/enrichment tests)

- [ ] **Step 3: Run linter and type checker**

Run: `source .venv/bin/activate && ruff check src/ tests/`
Run: `source .venv/bin/activate && mypy src/claude_candidate/ --strict` (fix any issues)

- [ ] **Step 4: Commit version bump and integration**

```bash
git add src/claude_candidate/__init__.py pyproject.toml src/claude_candidate/cli.py
git commit -m "Bump version to 0.2.0 with backend, parser, enrichment, and extension"
```

- [ ] **Step 5: Run end-to-end verification**

```bash
source .venv/bin/activate
# Verify CLI works
claude-candidate --version
# Verify server starts (kill after 2s)
timeout 3 claude-candidate server start --port 7430 || true
# Verify resume ingest
claude-candidate resume ingest tests/fixtures/sample_resume.txt -o /tmp/test_resume_profile.json
cat /tmp/test_resume_profile.json | python -m json.tool | head -20
```

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "v0.2.0: complete backend server, resume parser, enrichment engine, browser extension"
```
