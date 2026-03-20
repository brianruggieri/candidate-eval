"""SQLite-backed persistence for assessments, watchlist, and profiles."""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

import aiosqlite

_CREATE_ASSESSMENTS = """
CREATE TABLE IF NOT EXISTS assessments (
    assessment_id TEXT PRIMARY KEY,
    assessed_at   TEXT,
    job_title     TEXT,
    company_name  TEXT,
    posting_url   TEXT,
    overall_score INTEGER,
    overall_grade TEXT,
    should_apply  INTEGER,
    data          TEXT NOT NULL
);
"""

_CREATE_WATCHLIST = """
CREATE TABLE IF NOT EXISTS watchlist (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name  TEXT NOT NULL,
    job_title     TEXT NOT NULL,
    posting_url   TEXT,
    assessment_id TEXT,
    notes         TEXT,
    status        TEXT NOT NULL DEFAULT 'watching',
    added_at      TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (assessment_id) REFERENCES assessments(assessment_id)
);
"""

_CREATE_PROFILES = """
CREATE TABLE IF NOT EXISTS profiles (
    profile_type TEXT PRIMARY KEY,
    profile_hash TEXT NOT NULL,
    data         TEXT NOT NULL,
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_POSTING_CACHE = """
CREATE TABLE IF NOT EXISTS posting_cache (
    url_hash     TEXT PRIMARY KEY,
    url          TEXT NOT NULL,
    data         TEXT NOT NULL,
    extracted_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

_CREATE_COMPANY_RESEARCH = """
CREATE TABLE IF NOT EXISTS company_research (
    company_key    TEXT PRIMARY KEY,
    company_name   TEXT NOT NULL,
    data           TEXT NOT NULL,
    researched_at  TEXT DEFAULT (datetime('now'))
);
"""

_CREATE_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_assessments_company ON assessments(company_name);",
    "CREATE INDEX IF NOT EXISTS idx_assessments_score ON assessments(overall_score DESC);",
    "CREATE INDEX IF NOT EXISTS idx_watchlist_status ON watchlist(status);",
]


class AssessmentStore:
    """Async SQLite storage for assessments, watchlist, and profiles."""

    def __init__(self, db_path: Path | str) -> None:
        self._db_path = Path(db_path)
        self._conn: aiosqlite.Connection | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Open (or reuse) the database connection and create tables."""
        if self._conn is None:
            self._conn = await aiosqlite.connect(self._db_path)
            self._conn.row_factory = aiosqlite.Row

        await self._conn.execute(_CREATE_ASSESSMENTS)
        await self._conn.execute(_CREATE_WATCHLIST)
        await self._conn.execute(_CREATE_PROFILES)
        await self._conn.execute(_CREATE_POSTING_CACHE)
        await self._conn.execute(_CREATE_COMPANY_RESEARCH)
        for idx_sql in _CREATE_INDEXES:
            await self._conn.execute(idx_sql)
        await self._conn.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    async def list_tables(self) -> list[str]:
        """Return the names of all user-created tables in the database."""
        assert self._conn is not None, "Store not initialized"
        async with self._conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
        ) as cursor:
            rows = await cursor.fetchall()
        return [row[0] for row in rows]

    # ------------------------------------------------------------------
    # Assessment CRUD
    # ------------------------------------------------------------------

    async def save_assessment(self, assessment_data: dict[str, Any]) -> str:
        """Insert or replace an assessment record. Returns the assessment_id."""
        assert self._conn is not None, "Store not initialized"
        data = dict(assessment_data)
        assessment_id = data.get("assessment_id") or str(uuid.uuid4())

        # Serialize any nested dicts/lists stored in the 'data' key
        nested = data.get("data", {})
        data_json = json.dumps(nested) if not isinstance(nested, str) else nested

        await self._conn.execute(
            """
            INSERT OR REPLACE INTO assessments
                (assessment_id, assessed_at, job_title, company_name, posting_url,
                 overall_score, overall_grade, should_apply, data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                assessment_id,
                data.get("assessed_at"),
                data.get("job_title"),
                data.get("company_name"),
                data.get("posting_url"),
                data.get("overall_score"),
                data.get("overall_grade"),
                1 if data.get("should_apply") else 0,
                data_json,
            ),
        )
        await self._conn.commit()
        return assessment_id

    async def get_assessment(self, assessment_id: str) -> dict[str, Any] | None:
        """Fetch a single assessment by ID, or None if not found."""
        assert self._conn is not None, "Store not initialized"
        async with self._conn.execute(
            "SELECT * FROM assessments WHERE assessment_id = ?;",
            (assessment_id,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return self._decode_assessment(row)

    async def list_assessments(
        self, limit: int = 50, offset: int = 0
    ) -> list[dict[str, Any]]:
        """Return assessments ordered by assessed_at DESC with pagination."""
        assert self._conn is not None, "Store not initialized"
        async with self._conn.execute(
            "SELECT * FROM assessments ORDER BY assessed_at DESC LIMIT ? OFFSET ?;",
            (limit, offset),
        ) as cursor:
            rows = await cursor.fetchall()
        return [self._decode_assessment(r) for r in rows]

    async def delete_assessment(self, assessment_id: str) -> bool:
        """Delete an assessment by ID. Returns True if a row was deleted."""
        assert self._conn is not None, "Store not initialized"
        async with self._conn.execute(
            "DELETE FROM assessments WHERE assessment_id = ?;",
            (assessment_id,),
        ) as cursor:
            deleted = cursor.rowcount
        await self._conn.commit()
        return deleted > 0

    @staticmethod
    def _decode_assessment(row: aiosqlite.Row) -> dict[str, Any]:
        d = dict(row)
        if "data" in d and isinstance(d["data"], str):
            d["data"] = json.loads(d["data"])
        if "should_apply" in d:
            d["should_apply"] = bool(d["should_apply"])
        return d

    # ------------------------------------------------------------------
    # Watchlist CRUD
    # ------------------------------------------------------------------

    async def add_to_watchlist(
        self,
        company_name: str,
        job_title: str,
        posting_url: str | None = None,
        assessment_id: str | None = None,
        notes: str | None = None,
    ) -> int:
        """Insert a watchlist entry and return its auto-generated id."""
        assert self._conn is not None, "Store not initialized"
        async with self._conn.execute(
            """
            INSERT INTO watchlist (company_name, job_title, posting_url, assessment_id, notes)
            VALUES (?, ?, ?, ?, ?);
            """,
            (company_name, job_title, posting_url, assessment_id, notes),
        ) as cursor:
            row_id = cursor.lastrowid
        await self._conn.commit()
        return row_id  # type: ignore[return-value]

    async def list_watchlist(
        self, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """List watchlist entries, optionally filtered by status."""
        assert self._conn is not None, "Store not initialized"
        if status is not None:
            async with self._conn.execute(
                "SELECT * FROM watchlist WHERE status = ? ORDER BY added_at DESC LIMIT ?;",
                (status, limit),
            ) as cursor:
                rows = await cursor.fetchall()
        else:
            async with self._conn.execute(
                "SELECT * FROM watchlist ORDER BY added_at DESC LIMIT ?;",
                (limit,),
            ) as cursor:
                rows = await cursor.fetchall()
        return [dict(r) for r in rows]

    async def update_watchlist(
        self,
        watchlist_id: int,
        status: str | None = None,
        notes: str | None = None,
        assessment_id: str | None = None,
    ) -> bool:
        """Update a watchlist entry's mutable fields. Returns True if updated."""
        assert self._conn is not None, "Store not initialized"
        # Build SET clause only for provided fields
        fields: list[str] = []
        values: list[Any] = []
        if status is not None:
            fields.append("status = ?")
            values.append(status)
        if notes is not None:
            fields.append("notes = ?")
            values.append(notes)
        if assessment_id is not None:
            fields.append("assessment_id = ?")
            values.append(assessment_id)

        if not fields:
            # Nothing to update — check existence
            async with self._conn.execute(
                "SELECT id FROM watchlist WHERE id = ?;", (watchlist_id,)
            ) as cursor:
                row = await cursor.fetchone()
            return row is not None

        values.append(watchlist_id)
        sql = f"UPDATE watchlist SET {', '.join(fields)} WHERE id = ?;"
        async with self._conn.execute(sql, values) as cursor:
            updated = cursor.rowcount
        await self._conn.commit()
        return updated > 0

    async def remove_from_watchlist(self, watchlist_id: int) -> bool:
        """Delete a watchlist entry by id. Returns True if a row was deleted."""
        assert self._conn is not None, "Store not initialized"
        async with self._conn.execute(
            "DELETE FROM watchlist WHERE id = ?;", (watchlist_id,)
        ) as cursor:
            deleted = cursor.rowcount
        await self._conn.commit()
        return deleted > 0

    # ------------------------------------------------------------------
    # Profile storage
    # ------------------------------------------------------------------

    async def save_profile(
        self, profile_type: str, profile_hash: str, data: dict[str, Any]
    ) -> None:
        """Insert or replace a profile (upsert on profile_type PK)."""
        assert self._conn is not None, "Store not initialized"
        data_json = json.dumps(data)
        await self._conn.execute(
            """
            INSERT INTO profiles (profile_type, profile_hash, data, updated_at)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(profile_type) DO UPDATE SET
                profile_hash = excluded.profile_hash,
                data         = excluded.data,
                updated_at   = excluded.updated_at;
            """,
            (profile_type, profile_hash, data_json),
        )
        await self._conn.commit()

    async def get_profile(self, profile_type: str) -> dict[str, Any] | None:
        """Fetch profile data by type, or None if not found."""
        assert self._conn is not None, "Store not initialized"
        async with self._conn.execute(
            "SELECT data FROM profiles WHERE profile_type = ?;",
            (profile_type,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return json.loads(row[0])

    # ------------------------------------------------------------------
    # Posting cache
    # ------------------------------------------------------------------

    async def get_cached_posting(self, url_hash: str) -> dict[str, Any] | None:
        """Return cached posting dict if < 7 days old, else None (deletes expired row)."""
        assert self._conn is not None, "Store not initialized"
        async with self._conn.execute(
            "SELECT data, extracted_at FROM posting_cache WHERE url_hash = ?;",
            (url_hash,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        async with self._conn.execute(
            "SELECT (julianday('now') - julianday(?)) * 86400 > 604800;",
            (row[1],),
        ) as cursor:
            expired_row = await cursor.fetchone()
        if expired_row and expired_row[0]:
            await self._conn.execute(
                "DELETE FROM posting_cache WHERE url_hash = ?;", (url_hash,)
            )
            await self._conn.commit()
            return None
        return json.loads(row[0])

    async def cache_posting(
        self, url_hash: str, url: str, data: dict[str, Any]
    ) -> None:
        """Insert or replace a posting cache entry."""
        assert self._conn is not None, "Store not initialized"
        await self._conn.execute(
            "INSERT OR REPLACE INTO posting_cache (url_hash, url, data) VALUES (?, ?, ?);",
            (url_hash, url, json.dumps(data)),
        )
        await self._conn.commit()

    # ------------------------------------------------------------------
    # Company research cache
    # ------------------------------------------------------------------

    async def cache_company_research(self, company_name: str, data: dict) -> None:
        """Insert or replace a company research cache entry."""
        assert self._conn is not None, "Store not initialized"
        key = company_name.strip().lower()
        await self._conn.execute(
            "INSERT OR REPLACE INTO company_research (company_key, company_name, data) VALUES (?, ?, ?);",
            (key, company_name.strip(), json.dumps(data)),
        )
        await self._conn.commit()

    async def get_cached_company_research(self, company_name: str) -> dict | None:
        """Return cached company research if < 30 days old, else None (deletes expired row)."""
        assert self._conn is not None, "Store not initialized"
        key = company_name.strip().lower()
        async with self._conn.execute(
            "SELECT data, researched_at FROM company_research WHERE company_key = ?;",
            (key,),
        ) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        # 30 days = 30 * 86400 = 2592000 seconds
        async with self._conn.execute(
            "SELECT (julianday('now') - julianday(?)) * 86400 > 2592000;",
            (row[1],),
        ) as cursor:
            expired_row = await cursor.fetchone()
        if expired_row and expired_row[0]:
            await self._conn.execute(
                "DELETE FROM company_research WHERE company_key = ?;", (key,)
            )
            await self._conn.commit()
            return None
        return json.loads(row[0])
