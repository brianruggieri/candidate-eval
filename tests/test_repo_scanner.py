import pytest
from pathlib import Path

from claude_candidate.repo_scanner import scan_local_repo


class TestBuildRepoProfile:
	def test_aggregate_skill_evidence(self) -> None:
		"""Multiple repos aggregate into per-skill evidence."""
		from claude_candidate.repo_scanner import build_repo_profile

		repo_path = Path(__file__).parent.parent  # project root
		profile = build_repo_profile(
			local_repos=[repo_path],
			github_repos=[],
		)

		assert profile.repo_timeline_days > 0
		assert "python" in profile.skill_evidence
		python_ev = profile.skill_evidence["python"]
		assert python_ev.repos >= 1
		assert python_ev.total_bytes > 0
		assert profile.repos_with_tests >= 1

	def test_timeline_scales_with_repos(self) -> None:
		"""Timeline span covers earliest to latest across all repos."""
		from claude_candidate.repo_scanner import build_repo_profile

		repo_path = Path(__file__).parent.parent
		profile = build_repo_profile(
			local_repos=[repo_path],
			github_repos=[],
		)

		assert profile.repo_timeline_start <= profile.repo_timeline_end
		assert (
			profile.repo_timeline_days
			== (profile.repo_timeline_end - profile.repo_timeline_start).days
		)


class TestScanLocalRepo:
	def test_scan_candidate_eval(self) -> None:
		"""Scan this repo itself as a known baseline."""
		repo_path = Path(__file__).parent.parent  # project root
		evidence = scan_local_repo(repo_path)

		assert evidence.name == "candidate-eval"
		assert "Python" in evidence.languages
		assert evidence.languages["Python"] > 100_000  # substantial Python codebase
		assert evidence.has_tests is True
		assert evidence.test_framework == "pytest"
		assert evidence.test_file_count > 30
		assert evidence.has_ci is False  # no .github/workflows in this repo
		assert evidence.has_claude_md is True
		assert evidence.claude_dir_exists is True
		assert evidence.ai_maturity_level in ("advanced", "expert")

	def test_scan_detects_dependencies(self) -> None:
		"""Dependencies from pyproject.toml are resolved."""
		repo_path = Path(__file__).parent.parent
		evidence = scan_local_repo(repo_path)

		assert "pydantic" in evidence.dependencies or "fastapi" in evidence.dependencies
		assert "pytest" in evidence.dev_dependencies or "hypothesis" in evidence.dev_dependencies

	def test_scan_detects_llm_imports(self) -> None:
		"""LLM-related imports are detected in source files."""
		repo_path = Path(__file__).parent.parent
		evidence = scan_local_repo(repo_path)

		# candidate-eval uses anthropic SDK indirectly via claude CLI
		# but has direct imports for embeddings
		assert isinstance(evidence.llm_imports, list)

	def test_scan_commit_span(self) -> None:
		"""Commit span is computed from git log."""
		repo_path = Path(__file__).parent.parent
		evidence = scan_local_repo(repo_path)

		assert evidence.commit_span_days > 0
		assert evidence.created_at < evidence.last_pushed


class TestScanGitHubRepo:
	@pytest.mark.slow
	def test_scan_public_repo(self) -> None:
		"""Scan a known public repo via GitHub API."""
		from claude_candidate.repo_scanner import scan_github_repo

		evidence = scan_github_repo("brianruggieri/claude-code-pulse")

		assert evidence.name == "claude-code-pulse"
		assert evidence.url == "https://github.com/brianruggieri/claude-code-pulse"
		assert "Shell" in evidence.languages
		assert evidence.has_tests is True
		assert evidence.has_ci is True
		assert evidence.releases >= 5
		assert evidence.commit_span_days > 0
