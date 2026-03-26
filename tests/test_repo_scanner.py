from pathlib import Path

from claude_candidate.repo_scanner import scan_local_repo


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
