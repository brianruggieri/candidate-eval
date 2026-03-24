"""Tests for evidence compaction — reducing profile size by selecting top evidence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from claude_candidate.evidence_compactor import (
	COMPACTION_THRESHOLD,
	COMPACTION_VERSION,
	MAX_SHOWCASE,
	_build_aggregate_reference,
	_local_select_evidence,
	_parse_single_response,
	_strip_json_fences,
	compact_evidence,
)
from claude_candidate.schemas.candidate_profile import (
	CandidateProfile,
	DepthLevel,
	PatternType,
	ProblemSolvingPattern,
	ProjectComplexity,
	ProjectSummary,
	SessionReference,
	SkillEntry,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_evidence(
	n: int,
	*,
	project_prefix: str = "project",
	num_projects: int = 3,
	base_date: datetime | None = None,
	evidence_type: str = "direct_usage",
) -> list[SessionReference]:
	"""Generate n synthetic evidence entries spread across projects."""
	if base_date is None:
		base_date = datetime(2025, 9, 1)
	refs = []
	for i in range(n):
		proj = f"{project_prefix}-{i % num_projects}"
		refs.append(
			SessionReference(
				session_id=f"session-{i:04d}",
				session_date=base_date + timedelta(days=i),
				project_context=proj,
				evidence_snippet=f"Used skill in {proj} context #{i}",
				evidence_type=evidence_type,
				confidence=0.7 + 0.3 * (i / max(n - 1, 1)),
			)
		)
	return refs


def _make_diverse_evidence(n: int) -> list[SessionReference]:
	"""Generate evidence with diverse types and projects."""
	types = [
		"architecture_decision",
		"debugging",
		"refactor",
		"testing",
		"teaching",
		"integration",
		"direct_usage",
		"review",
		"planning",
		"evaluation",
	]
	base_date = datetime(2025, 6, 1)
	refs = []
	for i in range(n):
		refs.append(
			SessionReference(
				session_id=f"session-{i:04d}",
				session_date=base_date + timedelta(days=i * 2),
				project_context=f"project-{i % 5}",
				evidence_snippet=f"Evidence of type {types[i % len(types)]} in project-{i % 5}",
				evidence_type=types[i % len(types)],
				confidence=0.5 + 0.5 * (i / max(n - 1, 1)),
			)
		)
	return refs


def _make_skill(name: str = "python", evidence_count: int = 20) -> SkillEntry:
	"""Create a SkillEntry with the given number of evidence entries."""
	evidence = _make_evidence(evidence_count)
	return SkillEntry(
		name=name,
		category="language",
		depth=DepthLevel.DEEP,
		frequency=evidence_count,
		recency=evidence[-1].session_date,
		first_seen=evidence[0].session_date,
		evidence=evidence,
	)


def _make_pattern(evidence_count: int = 20) -> ProblemSolvingPattern:
	"""Create a ProblemSolvingPattern with the given number of evidence entries."""
	evidence = _make_evidence(evidence_count)
	return ProblemSolvingPattern(
		pattern_type=PatternType.SYSTEMATIC_DEBUGGING,
		frequency="common",
		strength="strong",
		description="Systematic approach to debugging",
		evidence=evidence,
	)


def _make_project(evidence_count: int = 20) -> ProjectSummary:
	"""Create a ProjectSummary with the given number of evidence entries."""
	evidence = _make_evidence(evidence_count)
	return ProjectSummary(
		project_name="test-project",
		description="A test project",
		complexity=ProjectComplexity.MODERATE,
		technologies=["python", "fastapi"],
		session_count=evidence_count,
		date_range_start=evidence[0].session_date,
		date_range_end=evidence[-1].session_date,
		evidence=evidence,
	)


def _make_profile(
	*,
	skill_evidence_counts: list[int] | None = None,
	pattern_evidence_counts: list[int] | None = None,
	project_evidence_counts: list[int] | None = None,
) -> CandidateProfile:
	"""Create a CandidateProfile with configurable evidence counts."""
	if skill_evidence_counts is None:
		skill_evidence_counts = [20, 3]
	if pattern_evidence_counts is None:
		pattern_evidence_counts = [15]
	if project_evidence_counts is None:
		project_evidence_counts = [5]

	skills = []
	for i, count in enumerate(skill_evidence_counts):
		skills.append(_make_skill(name=f"skill-{i}", evidence_count=count))

	patterns = []
	pattern_types = list(PatternType)
	for i, count in enumerate(pattern_evidence_counts):
		evidence = _make_evidence(count)
		patterns.append(
			ProblemSolvingPattern(
				pattern_type=pattern_types[i % len(pattern_types)],
				frequency="common",
				strength="strong",
				description=f"Pattern {i}",
				evidence=evidence,
			)
		)

	projects = []
	for i, count in enumerate(project_evidence_counts):
		evidence = _make_evidence(count)
		projects.append(
			ProjectSummary(
				project_name=f"project-{i}",
				description=f"Project {i}",
				complexity=ProjectComplexity.MODERATE,
				technologies=["python"],
				session_count=count,
				date_range_start=evidence[0].session_date,
				date_range_end=evidence[-1].session_date,
				evidence=evidence,
			)
		)

	return CandidateProfile(
		generated_at=datetime.now(),
		session_count=sum(skill_evidence_counts),
		date_range_start=datetime(2025, 9, 1),
		date_range_end=datetime(2026, 3, 15),
		manifest_hash="test_hash_" + "a" * 54,
		skills=skills,
		primary_languages=["python"],
		primary_domains=["backend"],
		problem_solving_patterns=patterns,
		working_style_summary="Test working style",
		projects=projects,
		communication_style="clear",
		documentation_tendency="moderate",
		extraction_notes="Test extraction",
		confidence_assessment="high",
	)


# ---------------------------------------------------------------------------
# Tests: compaction threshold
# ---------------------------------------------------------------------------


class TestCompactionThreshold:
	"""Skills with <= COMPACTION_THRESHOLD evidence entries are not modified."""

	def test_compact_skill_below_threshold(self):
		profile = _make_profile(
			skill_evidence_counts=[3, 5, COMPACTION_THRESHOLD],
			pattern_evidence_counts=[2],
			project_evidence_counts=[3],
		)
		original_evidence_lens = [len(s.evidence) for s in profile.skills]

		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		# Skills at or below threshold should be untouched
		for i, skill in enumerate(profile.skills):
			assert len(skill.evidence) == original_evidence_lens[i]
			assert skill.compacted is False
			assert skill.total_evidence_count is None

	def test_compact_skill_above_threshold(self):
		profile = _make_profile(skill_evidence_counts=[25])
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		skill = profile.skills[0]
		assert skill.compacted is True
		assert skill.total_evidence_count == 25
		# Should have MAX_SHOWCASE selected + 1 aggregate
		assert len(skill.evidence) <= MAX_SHOWCASE + 1


# ---------------------------------------------------------------------------
# Tests: evidence selection
# ---------------------------------------------------------------------------


class TestLocalHeuristicSelection:
	"""The local heuristic produces valid selections."""

	def test_selects_within_max(self):
		evidence = _make_evidence(30)
		indices = _local_select_evidence(evidence)
		assert len(indices) <= MAX_SHOWCASE
		assert all(0 <= i < 30 for i in indices)

	def test_small_list_returns_all(self):
		evidence = _make_evidence(3)
		indices = _local_select_evidence(evidence, max_select=5)
		assert sorted(indices) == [0, 1, 2]

	def test_prefers_high_value_types(self):
		"""Architecture decisions should rank higher than direct_usage."""
		evidence = []
		base_date = datetime(2026, 1, 1)
		# All same date and confidence, differ only by type
		for i, etype in enumerate(["direct_usage", "architecture_decision", "debugging"]):
			evidence.append(
				SessionReference(
					session_id=f"s-{i}",
					session_date=base_date,
					project_context=f"proj-{i}",
					evidence_snippet=f"Evidence {i}",
					evidence_type=etype,
					confidence=0.8,
				)
			)
		indices = _local_select_evidence(evidence, max_select=2)
		# architecture_decision (idx 1) and debugging (idx 2) should be preferred
		assert 1 in indices
		assert 2 in indices

	def test_fallback_diversity_enforcement(self):
		"""When top selections are all from one project, swap in a different project."""
		evidence = []
		base_date = datetime(2026, 1, 1)
		# 8 entries from project-A (high confidence), 2 from project-B (lower)
		for i in range(8):
			evidence.append(
				SessionReference(
					session_id=f"s-{i}",
					session_date=base_date + timedelta(days=i),
					project_context="project-A",
					evidence_snippet=f"High quality evidence {i}",
					evidence_type="architecture_decision",
					confidence=0.95,
				)
			)
		for i in range(2):
			evidence.append(
				SessionReference(
					session_id=f"s-b-{i}",
					session_date=base_date,
					project_context="project-B",
					evidence_snippet=f"Lower quality evidence {i}",
					evidence_type="direct_usage",
					confidence=0.5,
				)
			)

		indices = _local_select_evidence(evidence, max_select=5)
		selected_projects = {evidence[i].project_context for i in indices}
		assert len(selected_projects) >= 2, "Should include at least 2 projects"


# ---------------------------------------------------------------------------
# Tests: compaction application
# ---------------------------------------------------------------------------


class TestCompactionApplication:
	"""Compacted skills have correct structure."""

	def test_compact_preserves_total_count(self):
		profile = _make_profile(skill_evidence_counts=[50])
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		skill = profile.skills[0]
		assert skill.total_evidence_count == 50

	def test_compact_sets_flag(self):
		profile = _make_profile(skill_evidence_counts=[50])
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		skill = profile.skills[0]
		assert skill.compacted is True

	def test_compact_profile_version(self):
		profile = _make_profile(skill_evidence_counts=[50])
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		assert profile.compaction_version == COMPACTION_VERSION

	def test_compact_has_aggregate_entry(self):
		profile = _make_profile(skill_evidence_counts=[50])
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		skill = profile.skills[0]
		aggregate = [e for e in skill.evidence if e.session_id == "__aggregate__"]
		assert len(aggregate) == 1
		assert aggregate[0].project_context == "aggregate"

	def test_compact_evidence_min_length_satisfied(self):
		"""Compacted skills must still have at least 1 evidence entry (schema constraint)."""
		profile = _make_profile(skill_evidence_counts=[20])
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		skill = profile.skills[0]
		assert len(skill.evidence) >= 1

	def test_compact_mixed_skills(self):
		"""Profile with both small and large skills — only large get compacted."""
		profile = _make_profile(skill_evidence_counts=[3, 50, 5, 100])
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		assert profile.skills[0].compacted is False
		assert profile.skills[1].compacted is True
		assert profile.skills[2].compacted is False
		assert profile.skills[3].compacted is True


# ---------------------------------------------------------------------------
# Tests: pattern evidence compaction
# ---------------------------------------------------------------------------


class TestPatternCompaction:
	"""Pattern evidence is compacted with the same mechanism."""

	def test_compact_pattern_evidence(self):
		profile = _make_profile(
			skill_evidence_counts=[3],
			pattern_evidence_counts=[30],
		)
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		pattern = profile.problem_solving_patterns[0]
		assert pattern.compacted is True
		assert pattern.total_evidence_count == 30
		assert len(pattern.evidence) <= MAX_SHOWCASE + 1

	def test_small_pattern_not_compacted(self):
		profile = _make_profile(
			skill_evidence_counts=[3],
			pattern_evidence_counts=[5],
		)
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		pattern = profile.problem_solving_patterns[0]
		assert pattern.compacted is False


# ---------------------------------------------------------------------------
# Tests: project evidence compaction
# ---------------------------------------------------------------------------


class TestProjectCompaction:
	"""Project evidence is compacted with the same mechanism."""

	def test_compact_project_evidence(self):
		profile = _make_profile(
			skill_evidence_counts=[3],
			pattern_evidence_counts=[3],
			project_evidence_counts=[25],
		)
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		project = profile.projects[0]
		assert project.compacted is True
		assert project.total_evidence_count == 25
		assert len(project.evidence) <= MAX_SHOWCASE + 1


# ---------------------------------------------------------------------------
# Tests: aggregate summary format
# ---------------------------------------------------------------------------


class TestAggregateSummary:
	"""Aggregate reference contains correct stats."""

	def test_aggregate_summary_format(self):
		evidence = _make_diverse_evidence(20)
		aggregate = _build_aggregate_reference(evidence[5:], all_evidence=evidence)

		assert aggregate.session_id == "__aggregate__"
		assert aggregate.project_context == "aggregate"
		assert "20 sessions" in aggregate.evidence_snippet
		assert "5 projects" in aggregate.evidence_snippet
		assert "2025-06" in aggregate.evidence_snippet

	def test_aggregate_empty_excluded(self):
		"""When all entries are selected, aggregate still valid."""
		evidence = _make_evidence(3)
		aggregate = _build_aggregate_reference([], all_evidence=evidence)
		assert aggregate.session_id == "__aggregate__"
		assert "All evidence entries were selected" in aggregate.evidence_snippet


# ---------------------------------------------------------------------------
# Tests: Claude response parsing
# ---------------------------------------------------------------------------


class TestResponseParsing:
	"""Claude response parsing handles various formats."""

	def test_parse_valid_response(self):
		response = '{"selected_indices": [0, 5, 10], "reasoning": "good ones"}'
		indices = _parse_single_response(response, max_index=20)
		assert indices == [0, 5, 10]

	def test_parse_response_with_fences(self):
		response = '```json\n{"selected_indices": [1, 3, 7], "reasoning": "best"}\n```'
		indices = _parse_single_response(response, max_index=10)
		assert indices == [1, 3, 7]

	def test_parse_response_invalid_indices(self):
		response = '{"selected_indices": [0, 999, -1, 5], "reasoning": "mixed"}'
		indices = _parse_single_response(response, max_index=10)
		assert indices == [0, 5]

	def test_strip_json_fences_plain(self):
		assert _strip_json_fences('{"a": 1}') == '{"a": 1}'

	def test_strip_json_fences_with_json_tag(self):
		assert _strip_json_fences('```json\n{"a": 1}\n```') == '{"a": 1}'

	def test_strip_json_fences_bare_backticks(self):
		assert _strip_json_fences('```\n{"a": 1}\n```') == '{"a": 1}'


# ---------------------------------------------------------------------------
# Tests: fallback behavior
# ---------------------------------------------------------------------------


class TestFallback:
	"""When Claude is unavailable, local heuristic produces valid results."""

	def test_fallback_local_heuristic(self):
		"""Compaction succeeds with local heuristic when Claude is unavailable."""
		profile = _make_profile(skill_evidence_counts=[50])
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		skill = profile.skills[0]
		assert skill.compacted is True
		assert skill.total_evidence_count == 50
		assert len(skill.evidence) <= MAX_SHOWCASE + 1

	def test_fallback_diversity(self):
		"""Local heuristic picks from at least 2 projects when available."""
		evidence = _make_evidence(30, num_projects=5)
		indices = _local_select_evidence(evidence, max_select=5)
		selected_projects = {evidence[i].project_context for i in indices}
		assert len(selected_projects) >= 2

	@pytest.mark.slow
	def test_claude_failure_triggers_fallback(self):
		"""When Claude call raises, fallback to local heuristic."""
		profile = _make_profile(skill_evidence_counts=[60])

		def mock_check():
			return True

		with (
			patch("claude_candidate.evidence_compactor._check_claude_once", side_effect=mock_check),
			patch(
				"claude_candidate.evidence_compactor._claude_select_skill",
				side_effect=Exception("API error"),
			),
		):
			compact_evidence(profile)

		# Should still succeed via fallback
		skill = profile.skills[0]
		assert skill.compacted is True


# ---------------------------------------------------------------------------
# Tests: no-compact flag
# ---------------------------------------------------------------------------


class TestNoCompactFlag:
	"""The --no-compact flag skips compaction entirely."""

	def test_no_compact_flag_skips(self):
		profile = _make_profile(skill_evidence_counts=[50])
		original_len = len(profile.skills[0].evidence)

		# Don't call compact_evidence — simulating --no-compact
		assert profile.skills[0].compacted is False
		assert profile.skills[0].total_evidence_count is None
		assert len(profile.skills[0].evidence) == original_len
		assert profile.compaction_version is None


# ---------------------------------------------------------------------------
# Tests: schema backward compatibility
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
	"""New fields have defaults that maintain backward compatibility."""

	def test_skill_entry_defaults(self):
		skill = SkillEntry(
			name="python",
			category="language",
			depth=DepthLevel.DEEP,
			frequency=10,
			recency=datetime(2026, 3, 1),
			first_seen=datetime(2025, 9, 1),
			evidence=[
				SessionReference(
					session_id="s1",
					session_date=datetime(2026, 3, 1),
					project_context="proj",
					evidence_snippet="Used python",
					evidence_type="direct_usage",
					confidence=0.9,
				)
			],
		)
		assert skill.total_evidence_count is None
		assert skill.compacted is False

	def test_pattern_defaults(self):
		pattern = ProblemSolvingPattern(
			pattern_type=PatternType.SYSTEMATIC_DEBUGGING,
			frequency="common",
			strength="strong",
			description="Test",
			evidence=[
				SessionReference(
					session_id="s1",
					session_date=datetime(2026, 3, 1),
					project_context="proj",
					evidence_snippet="Debugged systematically",
					evidence_type="debugging",
					confidence=0.9,
				)
			],
		)
		assert pattern.total_evidence_count is None
		assert pattern.compacted is False

	def test_project_defaults(self):
		project = ProjectSummary(
			project_name="test",
			description="test project",
			complexity=ProjectComplexity.MODERATE,
			technologies=["python"],
			session_count=5,
			date_range_start=datetime(2025, 9, 1),
			date_range_end=datetime(2026, 3, 1),
			evidence=[
				SessionReference(
					session_id="s1",
					session_date=datetime(2026, 3, 1),
					project_context="proj",
					evidence_snippet="Worked on test",
					evidence_type="direct_usage",
					confidence=0.9,
				)
			],
		)
		assert project.total_evidence_count is None
		assert project.compacted is False

	def test_profile_compaction_version_default(self):
		profile = _make_profile(skill_evidence_counts=[3])
		assert profile.compaction_version is None


# ---------------------------------------------------------------------------
# Tests: compacted profile validates
# ---------------------------------------------------------------------------


class TestCompactedProfileValid:
	"""A compacted profile still passes schema validation."""

	def test_compacted_profile_roundtrips(self):
		profile = _make_profile(skill_evidence_counts=[50, 3, 30])
		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		# Serialize and deserialize
		json_str = profile.to_json()
		restored = CandidateProfile.from_json(json_str)

		assert restored.compaction_version == COMPACTION_VERSION
		assert restored.skills[0].compacted is True
		assert restored.skills[0].total_evidence_count == 50
		assert restored.skills[1].compacted is False  # below threshold
		assert restored.skills[2].compacted is True

	def test_compacted_profile_preserves_frequencies(self):
		"""Skill frequencies are unchanged after compaction."""
		profile = _make_profile(skill_evidence_counts=[50, 30])
		original_freqs = [s.frequency for s in profile.skills]

		with patch("claude_candidate.evidence_compactor._check_claude_once", return_value=False):
			compact_evidence(profile)

		for i, skill in enumerate(profile.skills):
			assert skill.frequency == original_freqs[i]
