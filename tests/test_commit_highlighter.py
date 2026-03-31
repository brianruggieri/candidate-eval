"""Tests for Claude commit highlight extraction."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_candidate.commit_filter import RawCommit
from claude_candidate.commit_filter import filter_commits
from claude_candidate.commit_highlighter import (
	_build_highlight_prompt,
	_heuristic_highlights,
	_parse_highlight_response,
	extract_commit_highlights,
)

_TS1 = datetime(2026, 3, 10, tzinfo=timezone.utc)
_TS2 = datetime(2026, 3, 15, tzinfo=timezone.utc)
_TS3 = datetime(2026, 3, 20, tzinfo=timezone.utc)

_REPO_URL = "https://github.com/user/candidate-eval"


def _sample_commits() -> list[RawCommit]:
	"""Build a small set of sample commits for testing."""
	return [
		RawCommit(
			hash="a" * 40,
			message="feat: add gradient year scoring to replace binary thresholds",
			timestamp=_TS1,
			additions=200,
			deletions=50,
			files_changed=8,
		),
		RawCommit(
			hash="b" * 40,
			message="refactor: simplify merger logic for evidence provenance",
			timestamp=_TS2,
			additions=150,
			deletions=80,
			files_changed=5,
		),
		RawCommit(
			hash="c" * 40,
			message="fix: null check in taxonomy lookup for unknown skills",
			timestamp=_TS3,
			additions=30,
			deletions=5,
			files_changed=2,
		),
	]


# ---------------------------------------------------------------------------
# _build_highlight_prompt
# ---------------------------------------------------------------------------


class TestBuildHighlightPrompt:
	def test_includes_repo_name(self):
		prompt = _build_highlight_prompt(
			_sample_commits(), repo_name="candidate-eval", repo_url=_REPO_URL
		)
		assert "candidate-eval" in prompt

	def test_includes_repo_url(self):
		prompt = _build_highlight_prompt(
			_sample_commits(), repo_name="candidate-eval", repo_url=_REPO_URL
		)
		assert _REPO_URL in prompt

	def test_includes_commit_hashes(self):
		commits = _sample_commits()
		prompt = _build_highlight_prompt(commits, repo_name="test-repo")
		for c in commits:
			assert c.hash[:8] in prompt

	def test_includes_json_format_instruction(self):
		prompt = _build_highlight_prompt(_sample_commits(), repo_name="test-repo")
		assert '"index"' in prompt
		assert '"quote"' in prompt
		assert '"skills"' in prompt


# ---------------------------------------------------------------------------
# _parse_highlight_response
# ---------------------------------------------------------------------------


class TestParseHighlightResponse:
	def test_parses_valid_json_array(self):
		commits = _sample_commits()
		response = json.dumps([
			{"index": 0, "quote": "Replaced binary scoring with gradient years", "skills": ["python"]},
			{"index": 1, "quote": "Simplified evidence provenance tracking", "skills": ["architecture"]},
		])
		highlights = _parse_highlight_response(response, commits=commits, repo_url=_REPO_URL)
		assert len(highlights) == 2
		assert highlights[0].quote == "Replaced binary scoring with gradient years"
		assert highlights[0].commit_hash == "a" * 40
		assert highlights[0].skills == ["python"]

	def test_resolves_github_url(self):
		commits = _sample_commits()
		response = json.dumps([
			{"index": 0, "quote": "Some highlight", "skills": []},
		])
		highlights = _parse_highlight_response(response, commits=commits, repo_url=_REPO_URL)
		assert highlights[0].github_url == f"{_REPO_URL}/commit/{'a' * 40}"

	def test_handles_fenced_json(self):
		commits = _sample_commits()
		response = '```json\n[{"index": 0, "quote": "Test highlight", "skills": []}]\n```'
		highlights = _parse_highlight_response(response, commits=commits)
		assert len(highlights) == 1

	def test_handles_invalid_json(self):
		highlights = _parse_highlight_response("not json at all", commits=_sample_commits())
		assert highlights == []

	def test_skips_out_of_range_index(self):
		"""Out-of-range index still produces a highlight with fallback timestamp."""
		commits = _sample_commits()
		response = json.dumps([
			{"index": 999, "quote": "Out of range highlight", "skills": []},
		])
		highlights = _parse_highlight_response(response, commits=commits)
		assert len(highlights) == 1
		assert highlights[0].commit_hash is None

	def test_no_github_url_without_repo_url(self):
		commits = _sample_commits()
		response = json.dumps([
			{"index": 0, "quote": "Test", "skills": []},
		])
		highlights = _parse_highlight_response(response, commits=commits, repo_url=None)
		assert highlights[0].github_url is None


# ---------------------------------------------------------------------------
# _heuristic_highlights
# ---------------------------------------------------------------------------


class TestHeuristicHighlights:
	def test_uses_message_as_quote(self):
		commits = _sample_commits()
		highlights = _heuristic_highlights(commits, repo_url=_REPO_URL)
		assert highlights[0].quote == commits[0].message

	def test_caps_at_max_highlights(self):
		commits = _sample_commits()
		highlights = _heuristic_highlights(commits, repo_url=_REPO_URL, max_highlights=2)
		assert len(highlights) == 2

	def test_no_skill_tags(self):
		"""Heuristic highlights have empty skill lists."""
		commits = _sample_commits()
		highlights = _heuristic_highlights(commits, repo_url=_REPO_URL)
		for h in highlights:
			assert h.skills == []

	def test_builds_github_urls(self):
		commits = _sample_commits()
		highlights = _heuristic_highlights(commits, repo_url=_REPO_URL)
		assert highlights[0].github_url == f"{_REPO_URL}/commit/{'a' * 40}"


# ---------------------------------------------------------------------------
# extract_commit_highlights (integration with mocked Claude)
# ---------------------------------------------------------------------------


class TestExtractCommitHighlights:
	def test_returns_empty_for_no_commits(self):
		result = extract_commit_highlights([], repo_name="test")
		assert result == []

	def test_falls_back_to_heuristic_on_claude_error(self):
		"""When Claude fails, heuristic fallback produces highlights."""
		with patch(
			"claude_candidate.claude_cli.call_claude",
			side_effect=Exception("Claude unavailable"),
		):
			commits = _sample_commits()
			result = extract_commit_highlights(
				commits, repo_name="test-repo", repo_url=_REPO_URL
			)
			assert len(result) > 0
			# Heuristic uses message as quote
			assert result[0].quote == commits[0].message

	def test_uses_claude_response_when_available(self):
		"""When Claude succeeds, its response is used."""
		claude_response = json.dumps([
			{"index": 0, "quote": "Claude-generated highlight", "skills": ["python"]},
		])
		with patch(
			"claude_candidate.claude_cli.call_claude",
			return_value=claude_response,
		):
			commits = _sample_commits()
			result = extract_commit_highlights(
				commits, repo_name="test-repo", repo_url=_REPO_URL
			)
			assert len(result) == 1
			assert result[0].quote == "Claude-generated highlight"
			assert result[0].skills == ["python"]


# ---------------------------------------------------------------------------
# Slow integration tests (real Claude CLI)
# ---------------------------------------------------------------------------


class TestCommitHighlighterIntegration:
	@pytest.mark.slow
	def test_highlights_from_this_repo(self):
		"""Full pipeline on candidate-eval repo with real Claude CLI."""
		from claude_candidate.repo_scanner import _fetch_raw_commits, _get_remote_url

		repo_path = Path(__file__).parent.parent
		raw = _fetch_raw_commits(repo_path, max_commits=50)
		filtered = filter_commits(raw, max_candidates=20)
		repo_url = _get_remote_url(repo_path)

		highlights = extract_commit_highlights(
			filtered,
			repo_name="candidate-eval",
			repo_url=repo_url,
			max_highlights=5,
		)

		assert len(highlights) > 0
		assert len(highlights) <= 5
		for h in highlights:
			assert h.quote  # non-empty
			assert h.timestamp.year >= 2025

	@pytest.mark.slow
	def test_highlights_carry_github_links(self):
		"""Highlights from a repo with a remote should have GitHub URLs."""
		from claude_candidate.repo_scanner import _fetch_raw_commits, _get_remote_url

		repo_path = Path(__file__).parent.parent
		repo_url = _get_remote_url(repo_path)
		if repo_url is None:
			pytest.skip("No remote URL for this repo")

		raw = _fetch_raw_commits(repo_path, max_commits=20)
		filtered = filter_commits(raw, max_candidates=10)

		highlights = extract_commit_highlights(
			filtered,
			repo_name="candidate-eval",
			repo_url=repo_url,
			max_highlights=3,
		)

		assert len(highlights) > 0
		for h in highlights:
			assert h.github_url is not None
			assert h.github_url.startswith("https://")
			assert "/commit/" in h.github_url
