"""Tests for CLI commands — click runner integration tests."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

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


class TestDashboardCLI:
	def test_dashboard_server_already_running(self) -> None:
		"""When the server is already running, just opens the URL."""
		runner = CliRunner()
		with (
			patch("urllib.request.urlopen") as mock_urlopen,
			patch("webbrowser.open") as mock_browser,
		):
			mock_urlopen.return_value.__enter__ = MagicMock()
			mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
			result = runner.invoke(main, ["dashboard"])
		assert result.exit_code == 0
		assert "Opening dashboard" in result.output
		mock_browser.assert_called_once_with("http://127.0.0.1:7429/dashboard")

	def test_dashboard_spawns_server_when_not_running(self) -> None:
		"""When server isn't running, spawns it then opens URL."""
		call_count = 0

		def urlopen_side_effect(*args, **kwargs):
			nonlocal call_count
			call_count += 1
			if call_count == 1:
				raise ConnectionError("not running")
			# Subsequent calls succeed (server started)
			ctx = MagicMock()
			ctx.__enter__ = MagicMock()
			ctx.__exit__ = MagicMock(return_value=False)
			return ctx

		runner = CliRunner()
		with (
			patch("urllib.request.urlopen", side_effect=urlopen_side_effect),
			patch("subprocess.Popen") as mock_popen,
			patch("webbrowser.open") as mock_browser,
			patch("time.sleep"),
		):
			result = runner.invoke(main, ["dashboard"])
		assert result.exit_code == 0
		assert "Starting server" in result.output
		mock_popen.assert_called_once()
		mock_browser.assert_called_once()

	def test_dashboard_connect_host_for_wildcard_bind(self) -> None:
		"""When binding to 0.0.0.0, uses 127.0.0.1 for browser URL."""
		runner = CliRunner()
		with (
			patch("urllib.request.urlopen") as mock_urlopen,
			patch("webbrowser.open") as mock_browser,
		):
			mock_urlopen.return_value.__enter__ = MagicMock()
			mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
			result = runner.invoke(main, ["dashboard", "--host", "0.0.0.0"])
		assert result.exit_code == 0
		mock_browser.assert_called_once_with("http://127.0.0.1:7429/dashboard")
