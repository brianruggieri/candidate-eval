"""
RepoProfile: Evidence extracted from GitHub repository analysis.

Captures structural signals from public repos — language usage, testing practices,
CI configuration, dependency graphs, and AI-tooling maturity indicators.
Consumed by the depth model to corroborate session and resume evidence.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RepoProject(BaseModel):
	"""Canonical project representation derived from repo evidence.

	Replaces ProjectSummary as the project source in MergedEvidenceProfile.projects.
	Constructed from RepoEvidence via the from_repo_evidence() classmethod.
	"""

	name: str
	url: str | None = None
	description: str | None = None
	languages: list[str] = Field(
		default_factory=list,
		description="Language names sorted by bytes descending",
	)
	dependencies: list[str] = Field(default_factory=list)
	commit_span_days: int = Field(ge=0)
	created_at: datetime
	last_pushed: datetime
	has_tests: bool
	test_framework: str | None = None
	has_ci: bool
	releases: int = Field(ge=0)
	ai_maturity_level: Literal["basic", "intermediate", "advanced", "expert"]
	evidence_highlights: list[str] = Field(default_factory=list)

	@classmethod
	def from_repo_evidence(cls, evidence: "RepoEvidence") -> "RepoProject":
		"""Construct a RepoProject from a RepoEvidence instance."""
		# Sort languages by bytes descending, keep names only
		sorted_langs = sorted(
			evidence.languages.items(),
			key=lambda kv: kv[1],
			reverse=True,
		)
		language_names = [name for name, _bytes in sorted_langs]

		return cls(
			name=evidence.name,
			url=evidence.url,
			description=evidence.description,
			languages=language_names,
			dependencies=list(evidence.dependencies),
			commit_span_days=evidence.commit_span_days,
			created_at=evidence.created_at,
			last_pushed=evidence.last_pushed,
			has_tests=evidence.has_tests,
			test_framework=evidence.test_framework,
			has_ci=evidence.has_ci,
			releases=evidence.releases,
			ai_maturity_level=evidence.ai_maturity_level,
			evidence_highlights=[],
		)


class CommitHighlight(BaseModel):
	"""A pithy evidence quote extracted from a commit or PR."""

	quote: str = Field(description="The highlight text extracted by Claude")
	commit_hash: str | None = Field(default=None, description="Full or short git hash")
	pr_number: int | None = Field(default=None, description="GitHub PR number if source=pr")
	timestamp: datetime
	github_url: str | None = Field(default=None, description="Direct link to commit or PR")
	skills: list[str] = Field(default_factory=list, description="Skill names demonstrated")
	source: Literal["commit", "pr"] = "commit"


class RepoEvidence(BaseModel):
	"""Evidence extracted from a single GitHub repository."""

	name: str
	url: str | None = None
	description: str | None = None
	created_at: datetime
	last_pushed: datetime
	commit_span_days: int = Field(ge=0)
	languages: dict[str, int] = Field(
		description="Language → bytes of code",
	)
	dependencies: list[str] = Field(
		description="Resolved skill names from production dependencies",
	)
	dev_dependencies: list[str] = Field(
		description="Resolved skill names from dev dependencies",
	)
	has_tests: bool
	test_framework: str | None = None
	test_file_count: int = Field(ge=0)
	has_ci: bool
	ci_complexity: Literal["basic", "standard", "advanced"]
	releases: int = Field(ge=0)
	has_changelog: bool

	# AI-tooling signals
	has_claude_md: bool
	has_agents_md: bool
	has_copilot_instructions: bool
	llm_imports: list[str] = Field(
		description="LLM SDK imports found in source (e.g. anthropic, openai, langchain)",
	)
	has_eval_framework: bool
	has_prompt_templates: bool

	# Claude Code maturity signals
	claude_dir_exists: bool
	claude_plans_count: int = Field(ge=0)
	claude_specs_count: int = Field(ge=0)
	claude_handoffs_count: int = Field(ge=0)
	claude_grill_sessions: int = Field(ge=0)
	claude_memory_files: int = Field(ge=0)
	has_settings_local: bool
	has_ralph_loops: bool
	has_superpowers_brainstorms: bool
	has_worktree_discipline: bool
	ai_maturity_level: Literal["basic", "intermediate", "advanced", "expert"]

	# Skill-crafting loop signals
	skill_crafting_signals: dict[str, int] = Field(
		default_factory=dict,
		description="Skill-crafting loop evidence counts: skills_authored, eval_harnesses, etc.",
	)

	# Commit highlights
	commit_highlights: list[CommitHighlight] = Field(default_factory=list)

	# Repo scale
	file_count: int = Field(ge=0)
	directory_depth: int = Field(ge=0)
	source_modules: int = Field(ge=0)


class SkillRepoEvidence(BaseModel):
	"""Aggregated evidence for one skill across all scanned repos."""

	repos: int = Field(ge=0)
	total_bytes: int = Field(ge=0)
	first_seen: datetime
	last_seen: datetime
	frameworks: list[str] = Field(default_factory=list)
	test_coverage: bool = False


class RepoProfile(BaseModel):
	"""Aggregate profile across all scanned repositories."""

	repos: list[RepoEvidence]
	scan_date: datetime
	repo_timeline_start: datetime
	repo_timeline_end: datetime
	repo_timeline_days: int = Field(ge=0)
	skill_evidence: dict[str, SkillRepoEvidence] = Field(default_factory=dict)
	repos_with_tests: int = Field(ge=0)
	repos_with_ci: int = Field(ge=0)
	repos_with_releases: int = Field(ge=0)
	repos_with_ai_signals: int = Field(ge=0)
