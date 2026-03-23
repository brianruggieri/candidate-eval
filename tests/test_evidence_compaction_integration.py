"""Integration tests for evidence compaction with real profile data."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_candidate.schemas.candidate_profile import CandidateProfile

REAL_PROFILE_PATH = Path.home() / ".claude-candidate" / "candidate_profile.json"


@pytest.mark.skipif(
	not REAL_PROFILE_PATH.exists(),
	reason="Real candidate_profile.json not available",
)
class TestCompactRealProfile:
	"""Integration tests using the actual candidate profile."""

	def test_compacted_profile_valid_schema(self):
		"""Compacted profile passes CandidateProfile.model_validate()."""
		from claude_candidate.evidence_compactor import compact_evidence

		profile = CandidateProfile.from_json(REAL_PROFILE_PATH.read_text())
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		# Round-trip through JSON to ensure schema compliance
		json_str = profile.to_json()
		restored = CandidateProfile.from_json(json_str)
		assert restored.compaction_version is not None

	def test_compacted_profile_preserves_frequencies(self):
		"""All skill frequencies remain unchanged after compaction."""
		from claude_candidate.evidence_compactor import compact_evidence

		profile = CandidateProfile.from_json(REAL_PROFILE_PATH.read_text())
		original_freqs = {s.name: s.frequency for s in profile.skills}

		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		for skill in profile.skills:
			assert skill.frequency == original_freqs[skill.name], (
				f"Frequency changed for {skill.name}: "
				f"{original_freqs[skill.name]} -> {skill.frequency}"
			)

	def test_compact_reduces_size(self):
		"""Compacted profile JSON is significantly smaller than original."""
		from claude_candidate.evidence_compactor import compact_evidence

		raw_text = REAL_PROFILE_PATH.read_text()
		original_size = len(raw_text)

		profile = CandidateProfile.from_json(raw_text)
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		compacted_text = profile.to_json()
		compacted_size = len(compacted_text)

		# Should be at least 50% smaller (typically 95%+ smaller)
		assert compacted_size < original_size * 0.5, (
			f"Compacted size {compacted_size:,} is not significantly smaller "
			f"than original {original_size:,}"
		)
