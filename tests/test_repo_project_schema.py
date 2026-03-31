"""Tests for RepoProject schema and from_repo_evidence() factory."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from claude_candidate.schemas.repo_profile import RepoEvidence, RepoProject


def _make_repo_evidence(**overrides) -> RepoEvidence:
	"""Build a minimal RepoEvidence with sensible defaults."""
	defaults = {
		"name": "candidate-eval",
		"url": "https://github.com/user/candidate-eval",
		"description": "Evidence-backed job fit engine",
		"created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
		"last_pushed": datetime(2026, 3, 25, tzinfo=timezone.utc),
		"commit_span_days": 84,
		"languages": {"Python": 500_000, "TypeScript": 200_000, "Shell": 5_000},
		"dependencies": ["fastapi", "pydantic", "click"],
		"dev_dependencies": ["pytest", "ruff"],
		"has_tests": True,
		"test_framework": "pytest",
		"test_file_count": 42,
		"has_ci": True,
		"ci_complexity": "standard",
		"releases": 3,
		"has_changelog": True,
		"has_claude_md": True,
		"has_agents_md": False,
		"has_copilot_instructions": False,
		"llm_imports": ["anthropic"],
		"has_eval_framework": False,
		"has_prompt_templates": True,
		"claude_dir_exists": True,
		"claude_plans_count": 5,
		"claude_specs_count": 0,
		"claude_handoffs_count": 0,
		"claude_grill_sessions": 3,
		"claude_memory_files": 2,
		"has_settings_local": True,
		"has_ralph_loops": True,
		"has_superpowers_brainstorms": False,
		"has_worktree_discipline": True,
		"ai_maturity_level": "advanced",
		"skill_crafting_signals": {},
		"file_count": 200,
		"directory_depth": 5,
		"source_modules": 30,
	}
	defaults.update(overrides)
	return RepoEvidence(**defaults)


class TestRepoProjectFromRepoEvidence:
	def test_from_repo_evidence_populates_name(self):
		evidence = _make_repo_evidence(name="my-project")
		project = RepoProject.from_repo_evidence(evidence)
		assert project.name == "my-project"

	def test_from_repo_evidence_preserves_url(self):
		evidence = _make_repo_evidence(url="https://github.com/user/repo")
		project = RepoProject.from_repo_evidence(evidence)
		assert project.url == "https://github.com/user/repo"

	def test_url_none_for_local_repo(self):
		evidence = _make_repo_evidence(url=None)
		project = RepoProject.from_repo_evidence(evidence)
		assert project.url is None

	def test_languages_as_sorted_list(self):
		"""Languages should be sorted by bytes descending, names only."""
		evidence = _make_repo_evidence(
			languages={"Python": 500_000, "TypeScript": 200_000, "Shell": 5_000}
		)
		project = RepoProject.from_repo_evidence(evidence)
		assert project.languages == ["Python", "TypeScript", "Shell"]

	def test_commit_span_days_preserved(self):
		evidence = _make_repo_evidence(commit_span_days=120)
		project = RepoProject.from_repo_evidence(evidence)
		assert project.commit_span_days == 120

	def test_structural_signals_preserved(self):
		evidence = _make_repo_evidence(
			has_tests=True,
			test_framework="pytest",
			has_ci=True,
			releases=5,
			ai_maturity_level="expert",
		)
		project = RepoProject.from_repo_evidence(evidence)
		assert project.has_tests is True
		assert project.test_framework == "pytest"
		assert project.has_ci is True
		assert project.releases == 5
		assert project.ai_maturity_level == "expert"

	def test_evidence_highlights_empty_by_default(self):
		evidence = _make_repo_evidence()
		project = RepoProject.from_repo_evidence(evidence)
		assert project.evidence_highlights == []

	def test_dependencies_preserved(self):
		evidence = _make_repo_evidence(dependencies=["fastapi", "pydantic", "click"])
		project = RepoProject.from_repo_evidence(evidence)
		assert project.dependencies == ["fastapi", "pydantic", "click"]

	def test_roundtrip_serialization(self):
		evidence = _make_repo_evidence()
		project = RepoProject.from_repo_evidence(evidence)
		json_str = project.model_dump_json()
		restored = RepoProject.model_validate_json(json_str)
		assert restored.name == project.name
		assert restored.url == project.url
		assert restored.languages == project.languages
		assert restored.commit_span_days == project.commit_span_days
		assert restored.ai_maturity_level == project.ai_maturity_level
		assert restored.evidence_highlights == project.evidence_highlights
