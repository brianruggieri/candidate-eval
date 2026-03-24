"""Tests for the whitelist module."""

from __future__ import annotations

from pathlib import Path

from claude_candidate.whitelist import (
	WhitelistConfig,
	filter_sessions_by_whitelist,
	load_whitelist,
	save_whitelist,
)
from claude_candidate.session_scanner import SessionInfo


# --- WhitelistConfig.is_whitelisted ---


def test_is_whitelisted_returns_true_for_included_project():
	config = WhitelistConfig(projects=["my-project", "other-project"])
	assert config.is_whitelisted("my-project") is True


def test_is_whitelisted_returns_false_for_excluded_project():
	config = WhitelistConfig(projects=["my-project"])
	assert config.is_whitelisted("private-client-work") is False


def test_is_whitelisted_empty_list_returns_false():
	config = WhitelistConfig()
	assert config.is_whitelisted("anything") is False


# --- save_whitelist / load_whitelist round-trip ---


def test_save_and_load_whitelist_round_trips(tmp_path):
	path = tmp_path / "subdir" / "whitelist.json"
	config = WhitelistConfig(projects=["project-a", "project-b"])
	save_whitelist(config, path)

	loaded = load_whitelist(path)
	assert loaded is not None
	assert loaded.projects == ["project-a", "project-b"]


def test_save_whitelist_creates_parent_dirs(tmp_path):
	path = tmp_path / "a" / "b" / "c" / "whitelist.json"
	save_whitelist(WhitelistConfig(projects=["x"]), path)
	assert path.exists()


def test_save_whitelist_writes_valid_json(tmp_path):
	import json

	path = tmp_path / "whitelist.json"
	save_whitelist(WhitelistConfig(projects=["proj"]), path)
	data = json.loads(path.read_text())
	assert data == {"projects": ["proj"]}


# --- load_whitelist missing file ---


def test_load_whitelist_returns_none_for_missing_file(tmp_path):
	path = tmp_path / "nonexistent.json"
	result = load_whitelist(path)
	assert result is None


def test_load_whitelist_returns_none_for_corrupted_file(tmp_path):
	path = tmp_path / "bad.json"
	path.write_text("not valid json {{{")
	result = load_whitelist(path)
	assert result is None


# --- filter_sessions_by_whitelist ---


def _make_session(project_hint: str) -> SessionInfo:
	"""Helper: construct a minimal SessionInfo."""
	return SessionInfo(
		path=Path(f"/fake/{project_hint}/session.jsonl"),
		session_id="abc123",
		project_hint=project_hint,
		file_size_bytes=100,
	)


def test_filter_sessions_keeps_whitelisted():
	sessions = [
		_make_session("public-project"),
		_make_session("private-client"),
		_make_session("public-project"),
	]
	whitelist = WhitelistConfig(projects=["public-project"])
	result = filter_sessions_by_whitelist(sessions, whitelist)
	assert len(result) == 2
	assert all(s.project_hint == "public-project" for s in result)


def test_filter_sessions_excludes_non_whitelisted():
	sessions = [_make_session("secret-work")]
	whitelist = WhitelistConfig(projects=["open-source"])
	result = filter_sessions_by_whitelist(sessions, whitelist)
	assert result == []


def test_filter_sessions_empty_whitelist_returns_empty():
	sessions = [_make_session("any-project")]
	whitelist = WhitelistConfig()
	result = filter_sessions_by_whitelist(sessions, whitelist)
	assert result == []


def test_filter_sessions_empty_input_returns_empty():
	whitelist = WhitelistConfig(projects=["project-a"])
	result = filter_sessions_by_whitelist([], whitelist)
	assert result == []


# --- is_whitelisted: prefix matching for worktrees ---


def test_is_whitelisted_matches_worktree():
	"""Canonical prefix should match a worktree directory (-- separator)."""
	config = WhitelistConfig(projects=["-Users-u-git-proj-a"])
	assert config.is_whitelisted("-Users-u-git-proj-a--worktrees-feat") is True


def test_is_whitelisted_no_false_positive_on_prefix():
	"""'proj' must NOT match 'proj-extended' (no -- separator)."""
	config = WhitelistConfig(projects=["proj"])
	assert config.is_whitelisted("proj-extended") is False


def test_is_whitelisted_exact_match_still_works():
	"""Full directory name (old-style whitelist entry) still matches exactly."""
	config = WhitelistConfig(projects=["-Users-u-git-candidate-eval"])
	assert config.is_whitelisted("-Users-u-git-candidate-eval") is True


def test_is_whitelisted_claude_worktree_match():
	"""Canonical prefix should match a --claude-worktrees-agent-* directory."""
	config = WhitelistConfig(projects=["-Users-u-git-proj-a"])
	assert config.is_whitelisted("-Users-u-git-proj-a--claude-worktrees-agent-abc") is True


def test_is_whitelisted_worktree_not_matched_by_unrelated_prefix():
	"""Worktree for proj-b is not matched by whitelist entry for proj-a."""
	config = WhitelistConfig(projects=["-Users-u-git-proj-a"])
	assert config.is_whitelisted("-Users-u-git-proj-b--worktrees-feat") is False
