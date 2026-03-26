"""Tests for CLI commands — click runner integration tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from claude_candidate.cli import main


class TestReposCLI:
	def test_repos_list_shows_configured(self, tmp_path: Path) -> None:
		"""repos list shows configured repos."""
		config = tmp_path / "repos.json"
		config.write_text('{"github_repos": ["user/repo1"], "local_repos": [], "exclude": []}')
		runner = CliRunner()
		result = runner.invoke(main, ["repos", "list", "--config", str(config)])
		assert result.exit_code == 0
		assert "user/repo1" in result.output

	def test_repos_scan_produces_profile(self, tmp_path: Path) -> None:
		"""repos scan creates repo_profile.json."""
		project_root = Path(__file__).parent.parent
		config = tmp_path / "repos.json"
		config.write_text(json.dumps({
			"github_repos": [],
			"local_repos": [str(project_root)],
			"exclude": [],
		}))
		data_dir = tmp_path / "data"
		data_dir.mkdir()
		runner = CliRunner()
		result = runner.invoke(main, [
			"repos", "scan",
			"--config", str(config),
			"--data-dir", str(data_dir),
		])
		assert result.exit_code == 0
		assert (data_dir / "repo_profile.json").exists()
