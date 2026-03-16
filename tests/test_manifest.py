"""Tests for the manifest module — hashing, scanning, manifest creation/verification."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime
from pathlib import Path

import pytest

from claude_candidate.manifest import (
    hash_file,
    hash_json_stable,
    hash_string,
    create_manifest,
    scan_session_file,
    scan_sessions,
    verify_manifest,
    make_path_relative,
    compute_corpus_statistics,
)


class TestHashing:
    def test_hash_string_known_vector(self):
        # SHA-256 of "hello world" is well-known
        h = hash_string("hello world")
        assert h == "b94d27b9934d3e08a52e52d7da7dabfac484efe37a5380ee9088f7ace2efcde9"

    def test_hash_string_deterministic(self):
        h1 = hash_string("test content")
        h2 = hash_string("test content")
        assert h1 == h2

    def test_hash_string_different_content(self):
        h1 = hash_string("content a")
        h2 = hash_string("content b")
        assert h1 != h2

    def test_hash_file(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        h = hash_file(f)
        assert len(h) == 64  # SHA-256 hex digest length
        # Should match hash_string of the file's binary content
        assert h == hash_string("hello world")

    def test_hash_json_stable_key_order_invariance(self):
        d1 = {"b": 2, "a": 1, "c": 3}
        d2 = {"a": 1, "c": 3, "b": 2}
        assert hash_json_stable(d1) == hash_json_stable(d2)

    def test_hash_json_stable_nested(self):
        d1 = {"outer": {"b": 2, "a": 1}}
        d2 = {"outer": {"a": 1, "b": 2}}
        assert hash_json_stable(d1) == hash_json_stable(d2)

    def test_hash_json_stable_with_datetime(self):
        """Datetimes should serialize consistently via default=str."""
        dt = datetime(2026, 1, 1, 12, 0, 0)
        d1 = {"time": dt, "value": 1}
        d2 = {"value": 1, "time": dt}
        assert hash_json_stable(d1) == hash_json_stable(d2)

    def test_hash_json_stable_with_none(self):
        d1 = {"a": None, "b": 1}
        d2 = {"b": 1, "a": None}
        assert hash_json_stable(d1) == hash_json_stable(d2)

    def test_hash_json_stable_different_values(self):
        d1 = {"a": 1}
        d2 = {"a": 2}
        assert hash_json_stable(d1) != hash_json_stable(d2)


class TestSessionScanning:
    def test_scan_single_session(self, tmp_path):
        session = tmp_path / "session.jsonl"
        session.write_text('{"type":"user","message":"hello"}\n{"type":"assistant","message":"hi"}\n')

        record = scan_session_file(session)
        assert record.line_count == 2
        assert record.file_size_bytes > 0
        assert record.hash_raw
        assert record.hash_sanitized is None  # Not yet sanitized

    def test_scan_detects_technologies(self, tmp_path):
        session = tmp_path / "session.jsonl"
        session.write_text('{"message":"import python pandas"}\n{"message":"react useState"}\n')

        record = scan_session_file(session)
        assert "python" in record.technologies_detected
        assert "react" in record.technologies_detected

    def test_scan_sessions_multiple(self, tmp_path):
        for i in range(3):
            f = tmp_path / f"session_{i}.jsonl"
            f.write_text(f'{{"message":"session {i}"}}\n')

        records = scan_sessions([tmp_path / f"session_{i}.jsonl" for i in range(3)])
        assert len(records) == 3

    def test_scan_sessions_skips_missing(self, tmp_path):
        existing = tmp_path / "exists.jsonl"
        existing.write_text('{"msg":"hi"}\n')

        records = scan_sessions([existing, tmp_path / "missing.jsonl"])
        assert len(records) == 1  # Only the existing one

    def test_scan_flags_large_file(self, tmp_path):
        session = tmp_path / "big.jsonl"
        session.write_text('{"msg":"x"}' * 20000 + "\n")

        record = scan_session_file(session)
        assert "large_file" in record.flags


class TestMakePathRelative:
    def test_strips_home_prefix(self):
        home = Path.home()
        full_path = home / "projects" / "test.jsonl"
        relative = make_path_relative(full_path)
        assert not relative.startswith("/")

    def test_preserves_claude_prefix(self):
        path = Path("/Users/someone/.claude/projects/abc/sessions/s.jsonl")
        relative = make_path_relative(path)
        assert relative.startswith(".claude/")


class TestCorpusStatistics:
    def test_empty_corpus(self):
        stats = compute_corpus_statistics([])
        assert stats.total_sessions == 0
        assert stats.total_tokens_estimate == 0

    def test_computes_aggregates(self, tmp_path):
        sessions = []
        for i in range(5):
            f = tmp_path / f"s{i}.jsonl"
            f.write_text(f'{{"msg":"session {i} with some words"}}\n')
            sessions.append(f)

        records = scan_sessions(sessions)
        stats = compute_corpus_statistics(records)
        assert stats.total_sessions == 5
        assert stats.total_lines == 5


class TestManifestCreation:
    def test_create_and_verify(self, tmp_path):
        session = tmp_path / "session.jsonl"
        session.write_text('{"msg":"test"}\n')

        records = scan_sessions([session])
        manifest = create_manifest(records, run_id="test-run")

        assert manifest.manifest_hash is not None
        assert manifest.run_id == "test-run"
        assert len(manifest.sessions) == 1

        result = verify_manifest(manifest)
        assert result["valid"], f"Errors: {result['errors']}"

    def test_tamper_detection(self, tmp_path):
        session = tmp_path / "session.jsonl"
        session.write_text('{"msg":"test"}\n')

        records = scan_sessions([session])
        manifest = create_manifest(records)

        # Tamper with the manifest
        manifest.sessions[0].line_count = 999

        result = verify_manifest(manifest)
        assert not result["valid"]
        assert any("hash mismatch" in e.lower() for e in result["errors"])

    def test_detects_duplicate_session_ids(self, tmp_path):
        session = tmp_path / "session.jsonl"
        session.write_text('{"msg":"test"}\n')

        records = scan_sessions([session])
        # Duplicate the record
        records.append(records[0].model_copy())

        manifest = create_manifest(records)
        result = verify_manifest(manifest)
        assert not result["valid"]
        assert any("duplicate" in e.lower() for e in result["errors"])
