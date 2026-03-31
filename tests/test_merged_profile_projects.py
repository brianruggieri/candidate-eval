"""Tests that MergedEvidenceProfile.projects accepts RepoProject instances."""

from __future__ import annotations

from datetime import datetime, timezone

from claude_candidate.schemas.merged_profile import (
	EvidenceSource,
	MergedEvidenceProfile,
	MergedSkillEvidence,
)
from claude_candidate.schemas.repo_profile import RepoProject
from claude_candidate.schemas.candidate_profile import DepthLevel


def _make_repo_project(**overrides) -> RepoProject:
	defaults = {
		"name": "test-project",
		"url": "https://github.com/user/test-project",
		"description": "A test project",
		"languages": ["Python", "TypeScript"],
		"dependencies": ["fastapi", "pydantic"],
		"commit_span_days": 90,
		"created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
		"last_pushed": datetime(2026, 3, 25, tzinfo=timezone.utc),
		"has_tests": True,
		"test_framework": "pytest",
		"has_ci": True,
		"releases": 2,
		"ai_maturity_level": "advanced",
		"evidence_highlights": [],
	}
	defaults.update(overrides)
	return RepoProject(**defaults)


def _make_minimal_merged(projects: list[RepoProject]) -> MergedEvidenceProfile:
	"""Build a minimal MergedEvidenceProfile with given projects."""
	return MergedEvidenceProfile(
		skills=[
			MergedSkillEvidence(
				name="python",
				source=EvidenceSource.RESUME_ONLY,
				effective_depth=DepthLevel.EXPERT,
			)
		],
		patterns=[],
		projects=projects,
		roles=[],
		corroborated_skill_count=0,
		resume_only_skill_count=1,
		sessions_only_skill_count=0,
		discovery_skills=[],
		profile_hash="test-hash",
		resume_hash="resume-hash",
		candidate_profile_hash="none",
		merged_at=datetime.now(timezone.utc),
	)


class TestMergedProfileAcceptsRepoProject:
	def test_accepts_single_repo_project(self):
		proj = _make_repo_project()
		merged = _make_minimal_merged([proj])
		assert len(merged.projects) == 1
		assert merged.projects[0].name == "test-project"

	def test_accepts_multiple_repo_projects(self):
		projects = [
			_make_repo_project(name="proj-a"),
			_make_repo_project(name="proj-b"),
		]
		merged = _make_minimal_merged(projects)
		assert len(merged.projects) == 2
		names = [p.name for p in merged.projects]
		assert "proj-a" in names
		assert "proj-b" in names

	def test_accepts_empty_projects(self):
		merged = _make_minimal_merged([])
		assert merged.projects == []

	def test_repo_project_fields_accessible(self):
		proj = _make_repo_project(
			languages=["Python", "Go"],
			commit_span_days=120,
			ai_maturity_level="expert",
		)
		merged = _make_minimal_merged([proj])
		p = merged.projects[0]
		assert p.languages == ["Python", "Go"]
		assert p.commit_span_days == 120
		assert p.ai_maturity_level == "expert"

	def test_roundtrip_serialization(self):
		proj = _make_repo_project()
		merged = _make_minimal_merged([proj])
		json_str = merged.to_json()
		restored = MergedEvidenceProfile.from_json(json_str)
		assert len(restored.projects) == 1
		assert restored.projects[0].name == "test-project"
		assert restored.projects[0].url == "https://github.com/user/test-project"
