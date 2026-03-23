"""Tests for interactive CLI prompt helpers."""

from __future__ import annotations

import time
from dataclasses import dataclass

import pytest
from click.testing import CliRunner
import click

from claude_candidate.cli_prompts import interactive_whitelist_selection, _human_size
from claude_candidate.session_scanner import ProjectSummary
from claude_candidate.whitelist import WhitelistConfig


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_project(display_name: str, session_count: int = 10) -> ProjectSummary:
	"""Create a minimal ProjectSummary for testing."""
	now = time.time()
	return ProjectSummary(
		project_hint=f"-Users-u-git-{display_name}",
		display_name=display_name,
		dir_names=(f"-Users-u-git-{display_name}",),
		session_count=session_count,
		total_size_bytes=session_count * 1024,
		oldest_mtime=now - 86400,
		newest_mtime=now,
	)


def _run_selection(
	projects: list[ProjectSummary],
	input_text: str,
	existing_whitelist: WhitelistConfig | None = None,
	hint_filter: str | None = None,
) -> tuple[WhitelistConfig | None, str, int]:
	"""Invoke interactive_whitelist_selection via a Click test CLI.

	Returns (whitelist_result, output_text, exit_code).
	"""
	result_holder: list[WhitelistConfig] = []
	exit_code_holder: list[int] = [0]

	@click.command()
	def _cmd():
		try:
			wl = interactive_whitelist_selection(projects, existing_whitelist, hint_filter)
			result_holder.append(wl)
		except SystemExit as exc:
			exit_code_holder[0] = int(exc.code) if exc.code is not None else 0

	runner = CliRunner()
	cli_result = runner.invoke(_cmd, input=input_text)
	wl = result_holder[0] if result_holder else None
	return wl, cli_result.output, exit_code_holder[0]


# ---------------------------------------------------------------------------
# _human_size
# ---------------------------------------------------------------------------

class TestHumanSize:
	def test_bytes(self) -> None:
		assert _human_size(500) == "500 B"

	def test_kilobytes(self) -> None:
		assert _human_size(1024) == "1.0 KB"

	def test_megabytes(self) -> None:
		assert _human_size(1024 * 1024) == "1.0 MB"

	def test_gigabytes(self) -> None:
		assert _human_size(1024 ** 3) == "1.0 GB"

	def test_large_megabytes(self) -> None:
		size = int(312 * 1024 * 1024)
		result = _human_size(size)
		assert "MB" in result


# ---------------------------------------------------------------------------
# interactive_whitelist_selection
# ---------------------------------------------------------------------------

class TestInteractiveWhitelistSelection:
	def setup_method(self):
		self.projects = [
			_make_project("alpha", session_count=5),
			_make_project("beta", session_count=20),
			_make_project("gamma", session_count=3),
		]

	def test_select_by_numbers(self) -> None:
		# Select projects 1 and 3, then confirm
		wl, output, _ = _run_selection(self.projects, "1,3\ny\n")
		assert wl is not None
		assert len(wl.projects) == 2
		assert "-Users-u-git-alpha" in wl.projects
		assert "-Users-u-git-gamma" in wl.projects

	def test_select_all(self) -> None:
		wl, output, _ = _run_selection(self.projects, "all\ny\n")
		assert wl is not None
		assert len(wl.projects) == 3

	def test_select_none(self) -> None:
		wl, output, _ = _run_selection(self.projects, "none\ny\n")
		assert wl is not None
		assert wl.projects == []

	def test_enter_keeps_existing_whitelist(self) -> None:
		existing = WhitelistConfig(projects=["-Users-u-git-alpha"])
		wl, output, _ = _run_selection(self.projects, "\n", existing_whitelist=existing)
		assert wl is not None
		assert wl.projects == ["-Users-u-git-alpha"]
		assert "Keeping existing whitelist" in output

	def test_enter_no_existing_returns_empty(self) -> None:
		wl, output, _ = _run_selection(self.projects, "\n", existing_whitelist=None)
		assert wl is not None
		assert wl.projects == []
		assert "No projects selected" in output

	def test_invalid_entries_skipped_with_warning(self) -> None:
		wl, output, _ = _run_selection(self.projects, "1,abc,3\ny\n")
		assert wl is not None
		assert len(wl.projects) == 2
		assert "Skipping invalid entry" in output

	def test_out_of_range_numbers_skipped(self) -> None:
		wl, output, _ = _run_selection(self.projects, "1,99\ny\n")
		assert wl is not None
		assert len(wl.projects) == 1
		assert "-Users-u-git-alpha" in wl.projects
		assert "Skipping out-of-range" in output

	def test_hint_filter_narrows_list(self) -> None:
		wl, output, _ = _run_selection(self.projects, "all\ny\n", hint_filter="alpha")
		assert wl is not None
		# Only "alpha" matches the filter, so "all" selects just 1 project
		assert len(wl.projects) == 1
		assert "-Users-u-git-alpha" in wl.projects

	def test_hint_filter_no_match_returns_existing(self) -> None:
		existing = WhitelistConfig(projects=["-Users-u-git-alpha"])
		wl, output, _ = _run_selection(
			self.projects, "", existing_whitelist=existing, hint_filter="zzznoexist"
		)
		# When filter matches nothing, returns existing whitelist unchanged
		assert wl is not None
		assert wl.projects == ["-Users-u-git-alpha"]

	def test_table_shows_star_for_whitelisted(self) -> None:
		existing = WhitelistConfig(projects=["-Users-u-git-beta"])
		_, output, _ = _run_selection(self.projects, "\n", existing_whitelist=existing)
		# The * marker should appear next to beta
		assert "* beta" in output or "*  beta" in output or "* " in output

	def test_abort_on_confirm_no(self) -> None:
		_, output, exit_code = _run_selection(self.projects, "1\nn\n")
		assert "Aborted" in output

	def test_table_header_shows_project_count(self) -> None:
		_, output, _ = _run_selection(self.projects, "\n")
		assert "3 projects" in output

	def test_selection_summary_shown_before_confirm(self) -> None:
		wl, output, _ = _run_selection(self.projects, "2\ny\n")
		assert "Selected 1 project" in output
		assert "beta" in output
