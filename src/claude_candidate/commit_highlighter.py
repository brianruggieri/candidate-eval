"""
Claude-powered commit highlight extraction.

Takes pre-filtered commits from commit_filter.py and extracts pithy evidence
quotes with skill tags — either via Claude CLI or via a heuristic fallback.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from claude_candidate.commit_filter import RawCommit
from claude_candidate.schemas.repo_profile import CommitHighlight

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def extract_commit_highlights(
	commits: list[RawCommit],
	*,
	repo_name: str,
	repo_url: str | None = None,
	max_highlights: int = 8,
) -> list[CommitHighlight]:
	"""Extract highlight quotes from commits, using Claude with heuristic fallback.

	Args:
		commits: Pre-filtered commits from filter_commits().
		repo_name: Name of the repository.
		repo_url: GitHub URL of the repo (for building commit links).
		max_highlights: Maximum number of highlights to return.

	Returns:
		List of CommitHighlight objects.
	"""
	if not commits:
		return []

	try:
		from claude_candidate.claude_cli import ClaudeCLIError, call_claude

		prompt = _build_highlight_prompt(commits, repo_name=repo_name, repo_url=repo_url)
		response = call_claude(prompt, timeout=120)
		highlights = _parse_highlight_response(response, commits=commits, repo_url=repo_url)
		if highlights:
			return highlights[:max_highlights]
		logger.warning("Claude returned no parseable highlights, falling back to heuristic")
	except ClaudeCLIError as exc:
		logger.warning("Claude highlight extraction failed (%s), using heuristic fallback", exc)
	except Exception as exc:
		logger.warning(
			"Unexpected error during Claude highlight extraction (%s), using heuristic fallback",
			exc,
		)

	return _heuristic_highlights(commits, repo_url=repo_url, max_highlights=max_highlights)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _build_highlight_prompt(
	commits: list[RawCommit],
	*,
	repo_name: str,
	repo_url: str | None = None,
) -> str:
	"""Build the Claude prompt for commit highlight extraction.

	Includes repo context, commit list with diffs, and structured output format.
	"""
	commit_lines = []
	for i, c in enumerate(commits):
		line = (
			f"[{i}] {c.hash[:8]} {c.timestamp.strftime('%Y-%m-%d')} "
			f"+{c.additions}/-{c.deletions} ({c.files_changed} files) — {c.message}"
		)
		commit_lines.append(line)

	commits_text = "\n".join(commit_lines)
	url_note = f"\nRepo URL: {repo_url}" if repo_url else ""

	return (
		"You are extracting evidence highlights from git commits for a developer portfolio.\n\n"
		f"Repository: {repo_name}{url_note}\n"
		f"Total commits shown: {len(commits)}\n\n"
		"Below are commits with their hash, date, diff stats, and subject line.\n\n"
		f"{commits_text}\n\n"
		f"Select the {min(8, len(commits))} most impressive commits and write a pithy "
		"1-sentence highlight for each. The highlight should:\n"
		"- Describe WHAT was accomplished, not just restate the commit message\n"
		"- Be specific and evidence-based\n"
		"- Include relevant skill names demonstrated\n\n"
		"Respond with ONLY a JSON array:\n"
		"[\n"
		'  {"index": 0, "quote": "...", "skills": ["python", "architecture"]},\n'
		"  ...\n"
		"]"
	)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _strip_json_fences(text: str) -> str:
	"""Strip markdown JSON fences if present."""
	text = text.strip()
	if text.startswith("```json"):
		text = text[len("```json"):]
	elif text.startswith("```"):
		text = text[len("```"):]
	if text.endswith("```"):
		text = text[:-len("```")]
	return text.strip()


def _build_github_url(repo_url: str | None, commit_hash: str) -> str | None:
	"""Build a GitHub commit URL from a repo URL and hash."""
	if not repo_url:
		return None
	return f"{repo_url.rstrip('/')}/commit/{commit_hash}"


def _parse_highlight_response(
	response: str,
	*,
	commits: list[RawCommit],
	repo_url: str | None = None,
) -> list[CommitHighlight]:
	"""Parse Claude's JSON response into CommitHighlight objects.

	Resolves timestamps and GitHub URLs from the original commit data.
	"""
	cleaned = _strip_json_fences(response)
	try:
		data = json.loads(cleaned)
	except json.JSONDecodeError:
		logger.warning("Failed to parse highlight response as JSON")
		return []

	if not isinstance(data, list):
		return []

	highlights: list[CommitHighlight] = []
	for entry in data:
		if not isinstance(entry, dict):
			continue

		idx = entry.get("index")
		quote = entry.get("quote", "")
		skills = entry.get("skills", [])

		if not quote:
			continue

		# Resolve commit data from index
		if isinstance(idx, int) and 0 <= idx < len(commits):
			commit = commits[idx]
			highlights.append(
				CommitHighlight(
					quote=quote,
					commit_hash=commit.hash,
					timestamp=commit.timestamp,
					github_url=_build_github_url(repo_url, commit.hash),
					skills=skills if isinstance(skills, list) else [],
					source="commit",
				)
			)
		else:
			# Entry without valid index — still include with fallback timestamp
			highlights.append(
				CommitHighlight(
					quote=quote,
					timestamp=datetime.now(timezone.utc),
					skills=skills if isinstance(skills, list) else [],
					source="commit",
				)
			)

	return highlights


# ---------------------------------------------------------------------------
# Heuristic fallback
# ---------------------------------------------------------------------------


def _heuristic_highlights(
	commits: list[RawCommit],
	*,
	repo_url: str | None = None,
	max_highlights: int = 5,
) -> list[CommitHighlight]:
	"""Generate highlights from commit messages without Claude.

	Uses the commit subject line as the quote. No skill tags — those
	require Claude's understanding.
	"""
	highlights: list[CommitHighlight] = []
	for c in commits[:max_highlights]:
		highlights.append(
			CommitHighlight(
				quote=c.message,
				commit_hash=c.hash,
				timestamp=c.timestamp,
				github_url=_build_github_url(repo_url, c.hash),
				skills=[],
				source="commit",
			)
		)
	return highlights
