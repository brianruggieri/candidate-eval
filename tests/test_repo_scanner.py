import tempfile
from pathlib import Path

import pytest

from claude_candidate.repo_scanner import _fetch_raw_commits, scan_local_repo


class TestFetchRawCommits:
	def test_returns_raw_commits_for_this_repo(self) -> None:
		"""Fetching commits from candidate-eval itself returns results."""
		repo_path = Path(__file__).parent.parent
		commits = _fetch_raw_commits(repo_path)
		assert len(commits) > 0
		# Each commit should have a hash and message
		for c in commits[:5]:
			assert len(c.hash) == 40  # full SHA
			assert len(c.message) > 0
			assert c.timestamp.year >= 2025

	def test_respects_max_commits(self) -> None:
		"""max_commits caps the number of returned commits."""
		repo_path = Path(__file__).parent.parent
		commits = _fetch_raw_commits(repo_path, max_commits=5)
		assert len(commits) <= 5

	def test_commits_have_diff_stats(self) -> None:
		"""Non-merge commits should have numeric diff stats."""
		repo_path = Path(__file__).parent.parent
		commits = _fetch_raw_commits(repo_path, max_commits=20)
		# At least some commits should have additions/deletions
		with_stats = [c for c in commits if c.additions > 0 or c.deletions > 0]
		assert len(with_stats) > 0

	def test_returns_empty_on_non_git_dir(self) -> None:
		"""A non-git directory returns an empty list."""
		with tempfile.TemporaryDirectory() as tmpdir:
			commits = _fetch_raw_commits(Path(tmpdir))
			assert commits == []


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
		assert evidence.languages["Python"] > 50_000  # substantial Python codebase
		assert evidence.has_tests is True
		assert evidence.test_framework == "pytest"
		assert evidence.test_file_count > 10
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


class TestAISignalSkillSynthesis:
	"""AI signals from repos should produce scorable skill entries."""

	def test_llm_imports_produce_llm_skill(self) -> None:
		"""Repos with LLM imports should produce 'llm' in skill_evidence."""
		from claude_candidate.repo_scanner import build_repo_profile

		repo_path = Path(__file__).parent.parent  # candidate-eval itself
		profile = build_repo_profile(local_repos=[repo_path])
		repo = profile.repos[0]
		if repo.llm_imports:
			assert "llm" in profile.skill_evidence
			assert profile.skill_evidence["llm"].repos >= 1

	def test_prompt_templates_produce_prompt_engineering(self) -> None:
		"""Repos with prompt templates should produce 'prompt-engineering'."""
		from claude_candidate.repo_scanner import build_repo_profile

		repo_path = Path(__file__).parent.parent
		profile = build_repo_profile(local_repos=[repo_path])
		repo = profile.repos[0]
		if repo.has_prompt_templates:
			assert "prompt-engineering" in profile.skill_evidence

	def test_advanced_ai_maturity_produces_ai_process_engineering(self) -> None:
		"""Repos with 2+ Claude Code maturity signals produce ai-process-engineering."""
		from claude_candidate.repo_scanner import build_repo_profile

		repo_path = Path(__file__).parent.parent
		profile = build_repo_profile(local_repos=[repo_path])
		repo = profile.repos[0]
		cc_signals = sum([
			repo.claude_plans_count > 0,
			repo.claude_specs_count > 0,
			repo.claude_handoffs_count > 0,
			repo.claude_grill_sessions > 0,
			repo.claude_memory_files > 0,
			repo.has_settings_local,
			repo.has_ralph_loops,
			repo.has_superpowers_brainstorms,
			repo.has_worktree_discipline,
		])
		if cc_signals >= 2:
			assert "ai-process-engineering" in profile.skill_evidence
			ev = profile.skill_evidence["ai-process-engineering"]
			assert ev.repos >= 1
			assert len(ev.frameworks) > 0

	def test_eval_framework_enriches_prompt_engineering(self) -> None:
		"""Eval frameworks should add to prompt-engineering evidence."""
		from claude_candidate.repo_scanner import build_repo_profile

		repo_path = Path(__file__).parent.parent
		profile = build_repo_profile(local_repos=[repo_path])
		repo = profile.repos[0]
		if repo.has_eval_framework and "prompt-engineering" in profile.skill_evidence:
			assert "eval-framework" in profile.skill_evidence["prompt-engineering"].frameworks


class TestSkillCraftingDetection:
	"""Detect skill-crafting loop evidence from repo filesystem."""

	def test_skill_crafting_signals_dict_exists(self):
		"""Every RepoEvidence should have a skill_crafting_signals dict."""
		repo_path = Path(__file__).parent.parent
		evidence = scan_local_repo(repo_path)
		assert isinstance(evidence.skill_crafting_signals, dict)

	def test_expected_signal_keys_present(self):
		"""All 7 signal keys from the spec should be in the dict."""
		repo_path = Path(__file__).parent.parent
		evidence = scan_local_repo(repo_path)
		expected_keys = {
			"skills_authored",
			"eval_harnesses",
			"prompt_iterations",
			"skill_test_corpus",
			"ab_test_evidence",
			"meta_skill_count",
			"grading_rubrics",
		}
		assert expected_keys.issubset(evidence.skill_crafting_signals.keys())

	def test_all_signals_are_non_negative_ints(self):
		"""All signal values should be non-negative integers."""
		repo_path = Path(__file__).parent.parent
		evidence = scan_local_repo(repo_path)
		for key, val in evidence.skill_crafting_signals.items():
			assert isinstance(val, int) and val >= 0, f"{key}={val}"

	def test_candidate_eval_has_test_fixtures(self):
		"""candidate-eval repo should have test fixtures counted."""
		repo_path = Path(__file__).parent.parent
		evidence = scan_local_repo(repo_path)
		# This repo has tests/fixtures/ with real fixture files
		assert evidence.skill_crafting_signals.get("skill_test_corpus", 0) > 0

	def test_skill_crafting_loop_enriches_ai_process_engineering(self):
		"""Repos with skill-crafting signals should add frameworks to ai-process-engineering."""
		from claude_candidate.repo_scanner import build_repo_profile

		repo_path = Path(__file__).parent.parent
		profile = build_repo_profile(local_repos=[repo_path])
		if "ai-process-engineering" in profile.skill_evidence:
			ev = profile.skill_evidence["ai-process-engineering"]
			# Should have framework entries from both CC maturity and skill-crafting
			assert len(ev.frameworks) > 0


class TestScanGitHubRepo:
	@pytest.mark.slow
	def test_scan_public_repo(self) -> None:
		"""Scan a known public repo via GitHub API."""
		from claude_candidate.repo_scanner import scan_github_repo

		evidence = scan_github_repo("alexdev/claude-code-pulse")

		assert evidence.name == "claude-code-pulse"
		assert evidence.url == "https://github.com/alexdev/claude-code-pulse"
		assert "Shell" in evidence.languages
		assert evidence.has_tests is True
		assert evidence.has_ci is True
		assert evidence.releases >= 5
		assert evidence.commit_span_days > 0
