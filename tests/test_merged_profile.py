"""
Tests for MergedSkillEvidence and EvidenceSource schema changes (v0.7).
"""

from datetime import datetime, timezone

import pytest

from claude_candidate.schemas.merged_profile import EvidenceSource, MergedSkillEvidence
from claude_candidate.schemas.candidate_profile import DepthLevel


class TestEvidenceSourceV2:
	def test_resume_and_repo_source(self) -> None:
		skill = MergedSkillEvidence(
			name="typescript",
			source=EvidenceSource.RESUME_AND_REPO,
			resume_depth=DepthLevel.EXPERT,
			resume_duration="8 years",
			repo_count=5,
			repo_bytes=2_800_000,
			repo_confirmed=True,
			effective_depth=DepthLevel.EXPERT,
		)
		assert skill.source == EvidenceSource.RESUME_AND_REPO
		assert skill.repo_confirmed is True

	def test_repo_only_source(self) -> None:
		skill = MergedSkillEvidence(
			name="fastapi",
			source=EvidenceSource.REPO_ONLY,
			repo_count=2,
			repo_bytes=50_000,
			repo_confirmed=True,
			effective_depth=DepthLevel.APPLIED,
		)
		assert skill.source == EvidenceSource.REPO_ONLY
		assert skill.resume_depth is None

	def test_backward_compat_old_sources(self) -> None:
		"""Old source values still work for backward compatibility."""
		skill = MergedSkillEvidence(
			name="python",
			source=EvidenceSource.CORROBORATED,
			resume_depth=DepthLevel.DEEP,
			session_depth=DepthLevel.DEEP,
			effective_depth=DepthLevel.DEEP,
		)
		assert skill.source == EvidenceSource.CORROBORATED

	def test_repo_fields_default_to_none(self) -> None:
		"""Repo fields default to None when not provided."""
		skill = MergedSkillEvidence(
			name="python",
			source=EvidenceSource.RESUME_ONLY,
			resume_depth=DepthLevel.EXPERT,
			effective_depth=DepthLevel.EXPERT,
		)
		assert skill.repo_count is None
		assert skill.repo_bytes is None
		assert skill.repo_first_seen is None
		assert skill.repo_last_seen is None
		assert skill.repo_frameworks is None
		assert skill.repo_confirmed is False

	def test_confidence_is_optional(self) -> None:
		"""confidence field is optional (defaults to None) in v0.7."""
		skill = MergedSkillEvidence(
			name="rust",
			source=EvidenceSource.RESUME_AND_REPO,
			resume_depth=DepthLevel.DEEP,
			repo_count=3,
			repo_confirmed=True,
			effective_depth=DepthLevel.DEEP,
		)
		assert skill.confidence is None

	def test_confidence_still_accepted_for_backward_compat(self) -> None:
		"""Existing code that sets confidence= still works."""
		skill = MergedSkillEvidence(
			name="python",
			source=EvidenceSource.CORROBORATED,
			resume_depth=DepthLevel.EXPERT,
			session_depth=DepthLevel.EXPERT,
			effective_depth=DepthLevel.EXPERT,
			confidence=0.95,
		)
		assert skill.confidence == 0.95

	def test_repo_frameworks_list(self) -> None:
		"""repo_frameworks stores a list of detected framework names."""
		skill = MergedSkillEvidence(
			name="python",
			source=EvidenceSource.RESUME_AND_REPO,
			resume_depth=DepthLevel.EXPERT,
			repo_count=10,
			repo_confirmed=True,
			repo_frameworks=["fastapi", "pytest", "pydantic"],
			effective_depth=DepthLevel.EXPERT,
		)
		assert skill.repo_frameworks == ["fastapi", "pytest", "pydantic"]

	def test_all_evidence_source_values_valid(self) -> None:
		"""All six EvidenceSource values are accessible."""
		sources = {s.value for s in EvidenceSource}
		assert "resume_only" in sources
		assert "sessions_only" in sources
		assert "corroborated" in sources
		assert "conflicting" in sources
		assert "resume_and_repo" in sources
		assert "repo_only" in sources
