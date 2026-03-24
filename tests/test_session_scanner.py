"""Tests for the session scanner module — JSONL file discovery."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from claude_candidate.session_scanner import (
	discover_sessions,
	discover_projects,
	_extract_project_hint,
	_extract_display_name,
	_canonical_project_key,
)


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


class TestExtractDisplayName:
	def test_standard_git_path(self) -> None:
		assert _extract_display_name("-Users-brianruggieri-git-candidate-eval") == "candidate-eval"

	def test_no_git_segment_returns_full_name(self) -> None:
		assert _extract_display_name("-Users-brianruggieri") == "-Users-brianruggieri"

	def test_worktree_suffix_stripped_via_canonical(self) -> None:
		# Worktree dirs should be split on -- before calling this
		canonical = "-Users-brianruggieri-git-candidate-eval--worktrees-feat".split("--")[0]
		assert _extract_display_name(canonical) == "candidate-eval"

	def test_multiple_git_segments_takes_last(self) -> None:
		# If there are multiple -git- segments, take the last
		name = "-Users-git-org-git-myproject"
		assert _extract_display_name(name) == "myproject"


class TestCanonicalProjectKey:
	def test_no_double_dash_returns_self(self) -> None:
		assert _canonical_project_key("-Users-x-git-myproject") == "-Users-x-git-myproject"

	def test_worktree_split_on_double_dash(self) -> None:
		assert _canonical_project_key("-Users-x-git-proj--worktrees-feat") == "-Users-x-git-proj"

	def test_claude_worktrees_split(self) -> None:
		assert (
			_canonical_project_key("-Users-x-git-proj--claude-worktrees-agent-abc")
			== "-Users-x-git-proj"
		)


class TestDiscoverProjects:
	def _make_project(
		self, root: Path, dir_name: str, session_count: int = 1, size: int = 10
	) -> None:
		"""Helper: create a project directory with N .jsonl files."""
		project_dir = root / dir_name
		project_dir.mkdir(parents=True, exist_ok=True)
		for i in range(session_count):
			f = project_dir / f"session-{i:04d}.jsonl"
			f.write_bytes(b"x" * size)

	def test_discovers_projects_with_sessions(self, tmp_path: Path) -> None:
		self._make_project(tmp_path, "-Users-u-git-proj-a", session_count=3)
		self._make_project(tmp_path, "-Users-u-git-proj-b", session_count=1)
		self._make_project(tmp_path, "-Users-u-git-proj-c", session_count=5)

		results = discover_projects(tmp_path)

		assert len(results) == 3
		names = {p.display_name for p in results}
		assert names == {"proj-a", "proj-b", "proj-c"}
		counts = {p.display_name: p.session_count for p in results}
		assert counts["proj-a"] == 3
		assert counts["proj-b"] == 1
		assert counts["proj-c"] == 5

	def test_groups_worktrees_with_parent(self, tmp_path: Path) -> None:
		self._make_project(tmp_path, "-Users-u-git-proj-a", session_count=2)
		self._make_project(tmp_path, "-Users-u-git-proj-a--worktrees-feat", session_count=3)

		results = discover_projects(tmp_path)

		assert len(results) == 1
		assert results[0].display_name == "proj-a"
		assert results[0].session_count == 5  # 2 + 3
		assert len(results[0].dir_names) == 2

	def test_groups_claude_worktrees(self, tmp_path: Path) -> None:
		self._make_project(tmp_path, "-Users-u-git-proj-a", session_count=1)
		self._make_project(
			tmp_path, "-Users-u-git-proj-a--claude-worktrees-agent-xxx", session_count=4
		)

		results = discover_projects(tmp_path)

		assert len(results) == 1
		assert results[0].session_count == 5  # 1 + 4

	def test_empty_project_dir_excluded(self, tmp_path: Path) -> None:
		(tmp_path / "-Users-u-git-empty-proj").mkdir()
		self._make_project(tmp_path, "-Users-u-git-real-proj", session_count=2)

		results = discover_projects(tmp_path)

		assert len(results) == 1
		assert results[0].display_name == "real-proj"

	def test_mtime_range_captured(self, tmp_path: Path) -> None:
		project_dir = tmp_path / "-Users-u-git-myproj"
		project_dir.mkdir()

		old_file = project_dir / "old-session.jsonl"
		new_file = project_dir / "new-session.jsonl"
		old_file.write_bytes(b"x")
		new_file.write_bytes(b"x")

		# Set known mtimes
		old_time = 1_000_000.0
		new_time = 2_000_000.0
		os.utime(old_file, (old_time, old_time))
		os.utime(new_file, (new_time, new_time))

		results = discover_projects(tmp_path)

		assert len(results) == 1
		assert results[0].oldest_mtime == old_time
		assert results[0].newest_mtime == new_time

	def test_nonexistent_dir_returns_empty(self, tmp_path: Path) -> None:
		results = discover_projects(tmp_path / "does-not-exist")
		assert results == []

	def test_projects_sorted_by_display_name(self, tmp_path: Path) -> None:
		for name in ("zebra", "apple", "mango"):
			self._make_project(tmp_path, f"-Users-u-git-{name}", session_count=1)

		results = discover_projects(tmp_path)

		display_names = [p.display_name for p in results]
		assert display_names == sorted(display_names, key=str.lower)

	def test_total_size_bytes_summed(self, tmp_path: Path) -> None:
		project_dir = tmp_path / "-Users-u-git-sized-proj"
		project_dir.mkdir()
		(project_dir / "s1.jsonl").write_bytes(b"x" * 100)
		(project_dir / "s2.jsonl").write_bytes(b"x" * 200)

		results = discover_projects(tmp_path)

		assert results[0].total_size_bytes == 300

	def test_worktree_only_groups_under_canonical_key(self, tmp_path: Path) -> None:
		# Worktree dir exists but no parent dir — should still show up
		self._make_project(tmp_path, "-Users-u-git-orphan--worktrees-branch", session_count=2)

		results = discover_projects(tmp_path)

		assert len(results) == 1
		assert results[0].display_name == "orphan"
