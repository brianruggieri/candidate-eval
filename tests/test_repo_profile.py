"""Tests for RepoEvidence, SkillRepoEvidence, and RepoProfile schemas."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from claude_candidate.schemas.repo_profile import (
	CommitHighlight,
	RepoEvidence,
	RepoProfile,
	SkillRepoEvidence,
)


def _make_repo_evidence(**overrides) -> RepoEvidence:
	"""Factory for a fully-populated RepoEvidence."""
	defaults = dict(
		name="candidate-eval",
		url="https://github.com/user/candidate-eval",
		description="Privacy-first candidate assessment pipeline",
		created_at=datetime(2025, 1, 15, tzinfo=timezone.utc),
		last_pushed=datetime(2026, 3, 25, tzinfo=timezone.utc),
		commit_span_days=435,
		languages={"Python": 120_000, "TypeScript": 45_000, "Shell": 2_000},
		dependencies=["python", "pydantic", "fastapi", "click"],
		dev_dependencies=["pytest", "ruff", "hypothesis"],
		has_tests=True,
		test_framework="pytest",
		test_file_count=42,
		has_ci=True,
		ci_complexity="advanced",
		releases=6,
		has_changelog=True,
		has_claude_md=True,
		has_agents_md=False,
		has_copilot_instructions=False,
		llm_imports=["anthropic", "openai"],
		has_eval_framework=True,
		has_prompt_templates=True,
		claude_dir_exists=True,
		claude_plans_count=3,
		claude_specs_count=2,
		claude_handoffs_count=1,
		claude_grill_sessions=4,
		claude_memory_files=5,
		has_settings_local=True,
		has_ralph_loops=True,
		has_superpowers_brainstorms=True,
		has_worktree_discipline=True,
		ai_maturity_level="expert",
		file_count=200,
		directory_depth=5,
		source_modules=30,
	)
	defaults.update(overrides)
	return RepoEvidence(**defaults)


class TestCommitHighlight:
	def test_commit_highlight_round_trips(self):
		"""CommitHighlight can be serialized and restored."""
		h = CommitHighlight(
			quote="Refactored scoring engine to use gradient years",
			commit_hash="abc1234",
			timestamp=datetime(2026, 3, 15, tzinfo=timezone.utc),
			github_url="https://github.com/user/repo/commit/abc1234",
			skills=["python", "architecture"],
			source="commit",
		)
		data = h.model_dump(mode="json")
		restored = CommitHighlight.model_validate(data)
		assert restored == h
		assert restored.quote == "Refactored scoring engine to use gradient years"
		assert restored.commit_hash == "abc1234"
		assert restored.skills == ["python", "architecture"]

	def test_pr_highlight_source(self):
		"""CommitHighlight supports source='pr' with pr_number."""
		h = CommitHighlight(
			quote="Added culture scoring pipeline with company research",
			pr_number=42,
			timestamp=datetime(2026, 3, 20, tzinfo=timezone.utc),
			github_url="https://github.com/user/repo/pull/42",
			skills=["fastapi"],
			source="pr",
		)
		assert h.source == "pr"
		assert h.pr_number == 42
		assert h.commit_hash is None

	def test_repo_evidence_accepts_commit_highlights(self):
		"""RepoEvidence defaults commit_highlights to empty list."""
		repo = _make_repo_evidence()
		assert repo.commit_highlights == []

		# Can also supply highlights
		h = CommitHighlight(
			quote="Added test suite",
			timestamp=datetime(2026, 3, 10, tzinfo=timezone.utc),
		)
		repo2 = _make_repo_evidence(commit_highlights=[h])
		assert len(repo2.commit_highlights) == 1
		assert repo2.commit_highlights[0].quote == "Added test suite"


class TestRepoEvidence:
	def test_fully_populated(self):
		"""A fully populated RepoEvidence round-trips correctly."""
		repo = _make_repo_evidence()
		assert repo.name == "candidate-eval"
		assert repo.url == "https://github.com/user/candidate-eval"
		assert repo.commit_span_days == 435
		assert repo.languages == {"Python": 120_000, "TypeScript": 45_000, "Shell": 2_000}
		assert repo.has_tests is True
		assert repo.test_framework == "pytest"
		assert repo.ci_complexity == "advanced"
		assert repo.ai_maturity_level == "expert"
		assert repo.claude_plans_count == 3
		assert repo.has_ralph_loops is True
		assert repo.file_count == 200

	def test_minimal_repo(self):
		"""Repo with only required fields and sensible defaults."""
		repo = RepoEvidence(
			name="tiny-lib",
			created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
			last_pushed=datetime(2026, 1, 2, tzinfo=timezone.utc),
			commit_span_days=1,
			languages={"Rust": 5_000},
			dependencies=[],
			dev_dependencies=[],
			has_tests=False,
			test_file_count=0,
			has_ci=False,
			ci_complexity="basic",
			releases=0,
			has_changelog=False,
			has_claude_md=False,
			has_agents_md=False,
			has_copilot_instructions=False,
			llm_imports=[],
			has_eval_framework=False,
			has_prompt_templates=False,
			claude_dir_exists=False,
			claude_plans_count=0,
			claude_specs_count=0,
			claude_handoffs_count=0,
			claude_grill_sessions=0,
			claude_memory_files=0,
			has_settings_local=False,
			has_ralph_loops=False,
			has_superpowers_brainstorms=False,
			has_worktree_discipline=False,
			ai_maturity_level="basic",
			file_count=3,
			directory_depth=1,
			source_modules=1,
		)
		assert repo.url is None
		assert repo.description is None
		assert repo.test_framework is None

	def test_ai_maturity_rejects_invalid(self):
		"""ai_maturity_level must be one of the Literal values."""
		with pytest.raises(ValidationError, match="ai_maturity_level"):
			_make_repo_evidence(ai_maturity_level="godlike")

	def test_ci_complexity_rejects_invalid(self):
		"""ci_complexity must be basic, standard, or advanced."""
		with pytest.raises(ValidationError, match="ci_complexity"):
			_make_repo_evidence(ci_complexity="mega")

	def test_negative_commit_span_rejected(self):
		"""commit_span_days must be >= 0."""
		with pytest.raises(ValidationError, match="commit_span_days"):
			_make_repo_evidence(commit_span_days=-1)

	def test_negative_file_count_rejected(self):
		"""file_count must be >= 0."""
		with pytest.raises(ValidationError, match="file_count"):
			_make_repo_evidence(file_count=-5)

	def test_serialization_roundtrip(self):
		"""Model can serialize to dict and back."""
		repo = _make_repo_evidence()
		data = repo.model_dump(mode="json")
		restored = RepoEvidence.model_validate(data)
		assert restored == repo


class TestSkillRepoEvidence:
	def test_all_fields(self):
		"""SkillRepoEvidence works with all fields populated."""
		evidence = SkillRepoEvidence(
			repos=3,
			total_bytes=250_000,
			first_seen=datetime(2024, 6, 1, tzinfo=timezone.utc),
			last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
			frameworks=["fastapi", "flask"],
			test_coverage=True,
		)
		assert evidence.repos == 3
		assert evidence.total_bytes == 250_000
		assert evidence.frameworks == ["fastapi", "flask"]
		assert evidence.test_coverage is True

	def test_defaults(self):
		"""Defaults are applied for frameworks and test_coverage."""
		evidence = SkillRepoEvidence(
			repos=1,
			total_bytes=1_000,
			first_seen=datetime(2025, 1, 1, tzinfo=timezone.utc),
			last_seen=datetime(2025, 6, 1, tzinfo=timezone.utc),
		)
		assert evidence.frameworks == []
		assert evidence.test_coverage is False

	def test_negative_repos_rejected(self):
		"""repos must be >= 0."""
		with pytest.raises(ValidationError, match="repos"):
			SkillRepoEvidence(
				repos=-1,
				total_bytes=0,
				first_seen=datetime(2025, 1, 1, tzinfo=timezone.utc),
				last_seen=datetime(2025, 6, 1, tzinfo=timezone.utc),
			)


class TestRepoProfile:
	def test_with_aggregation_fields(self):
		"""RepoProfile works with repos and aggregation fields."""
		repo = _make_repo_evidence()
		profile = RepoProfile(
			repos=[repo],
			scan_date=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_start=datetime(2025, 1, 15, tzinfo=timezone.utc),
			repo_timeline_end=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_days=435,
			skill_evidence={
				"python": SkillRepoEvidence(
					repos=1,
					total_bytes=120_000,
					first_seen=datetime(2025, 1, 15, tzinfo=timezone.utc),
					last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
					frameworks=["fastapi"],
					test_coverage=True,
				),
			},
			repos_with_tests=1,
			repos_with_ci=1,
			repos_with_releases=1,
			repos_with_ai_signals=1,
		)
		assert len(profile.repos) == 1
		assert profile.repo_timeline_days == 435
		assert "python" in profile.skill_evidence
		assert profile.repos_with_tests == 1

	def test_empty_profile(self):
		"""RepoProfile with no repos uses defaults."""
		profile = RepoProfile(
			repos=[],
			scan_date=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_start=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_end=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_days=0,
			repos_with_tests=0,
			repos_with_ci=0,
			repos_with_releases=0,
			repos_with_ai_signals=0,
		)
		assert profile.skill_evidence == {}
		assert len(profile.repos) == 0

	def test_serialization_roundtrip(self):
		"""Full profile serializes to JSON and back."""
		repo = _make_repo_evidence()
		profile = RepoProfile(
			repos=[repo],
			scan_date=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_start=datetime(2025, 1, 15, tzinfo=timezone.utc),
			repo_timeline_end=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_days=435,
			skill_evidence={
				"python": SkillRepoEvidence(
					repos=1,
					total_bytes=120_000,
					first_seen=datetime(2025, 1, 15, tzinfo=timezone.utc),
					last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
				),
			},
			repos_with_tests=1,
			repos_with_ci=1,
			repos_with_releases=1,
			repos_with_ai_signals=1,
		)
		data = profile.model_dump(mode="json")
		restored = RepoProfile.model_validate(data)
		assert restored == profile
