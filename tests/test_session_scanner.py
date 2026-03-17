"""Tests for the session scanner module — JSONL file discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_candidate.session_scanner import discover_sessions, _extract_project_hint


class TestDiscoverSessions:
    def test_finds_jsonl_files(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "projects" / "abc123"
        project_dir.mkdir(parents=True)
        session_file = project_dir / "session-001.jsonl"
        session_file.write_text('{"type":"user","message":"hello"}\n')

        results = discover_sessions(tmp_path)

        assert len(results) == 1
        assert results[0].path == session_file

    def test_skips_non_jsonl(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "projects" / "abc123"
        project_dir.mkdir(parents=True)
        (project_dir / "session.jsonl").write_text('{"msg":"hi"}\n')
        (project_dir / "notes.txt").write_text("some text\n")
        (project_dir / "data.json").write_text('{"key":"value"}\n')

        results = discover_sessions(tmp_path)

        assert len(results) == 1
        assert results[0].path.suffix == ".jsonl"

    def test_empty_directory(self, tmp_path: Path) -> None:
        results = discover_sessions(tmp_path)

        assert results == []

    def test_nonexistent_directory(self, tmp_path: Path) -> None:
        nonexistent = tmp_path / "does_not_exist"

        results = discover_sessions(nonexistent)

        assert results == []

    def test_extracts_project_hint(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "projects" / "my-project"
        project_dir.mkdir(parents=True)
        (project_dir / "session.jsonl").write_text('{"msg":"hello"}\n')

        results = discover_sessions(tmp_path)

        assert len(results) == 1
        assert results[0].project_hint == "my-project"

    def test_extracts_session_id_from_filename(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        (project_dir / "abc-123-def.jsonl").write_text('{"msg":"hello"}\n')

        results = discover_sessions(tmp_path)

        assert len(results) == 1
        assert results[0].session_id == "abc-123-def"

    def test_multiple_projects(self, tmp_path: Path) -> None:
        for project_name in ("proj-a", "proj-b", "proj-c"):
            project_dir = tmp_path / "projects" / project_name
            project_dir.mkdir(parents=True)
            (project_dir / f"session-{project_name}.jsonl").write_text('{"msg":"hello"}\n')

        results = discover_sessions(tmp_path)

        assert len(results) == 3
        project_hints = {r.project_hint for r in results}
        assert project_hints == {"proj-a", "proj-b", "proj-c"}

    def test_results_sorted_by_path(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        for name in ("z-session.jsonl", "a-session.jsonl", "m-session.jsonl"):
            (project_dir / name).write_text('{"msg":"hello"}\n')

        results = discover_sessions(tmp_path)

        paths = [r.path for r in results]
        assert paths == sorted(paths)

    def test_file_size_bytes_populated(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        content = '{"msg":"hello world"}\n'
        (project_dir / "session.jsonl").write_text(content)

        results = discover_sessions(tmp_path)

        assert results[0].file_size_bytes == len(content.encode())

    def test_session_info_is_frozen(self, tmp_path: Path) -> None:
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        (project_dir / "session.jsonl").write_text('{"msg":"hello"}\n')

        results = discover_sessions(tmp_path)
        info = results[0]

        with pytest.raises(Exception):
            info.session_id = "mutated"  # type: ignore[misc]


class TestExtractProjectHint:
    def test_returns_parent_name(self) -> None:
        path = Path("/home/user/.claude/projects/my-cool-project/session.jsonl")
        assert _extract_project_hint(path) == "my-cool-project"

    def test_returns_immediate_parent(self) -> None:
        path = Path("/a/b/c/d/session.jsonl")
        assert _extract_project_hint(path) == "d"
