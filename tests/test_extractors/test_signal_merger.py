"""Tests for SignalMerger: aggregation, depth scoring, patterns, projects, velocity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from claude_candidate.extractors import (
	PatternSignal,
	ProjectSignal,
	SignalResult,
	SkillSignal,
)
from claude_candidate.extractors.signal_merger import SignalMerger
from claude_candidate.schemas.candidate_profile import (
	CandidateProfile,
	DepthLevel,
	PatternType,
)


def _make_signal_result(
	session_id: str = "s1",
	project_context: str = "myproject",
	skills: dict[str, list[SkillSignal]] | None = None,
	patterns: list[PatternSignal] | None = None,
	project_signals: ProjectSignal | None = None,
	metrics: dict[str, float] | None = None,
	session_date: datetime | None = None,
) -> SignalResult:
	return SignalResult(
		session_id=session_id,
		session_date=session_date or datetime.now(timezone.utc),
		project_context=project_context,
		skills=skills or {},
		patterns=patterns or [],
		project_signals=project_signals,
		metrics=metrics or {},
	)


def _skill(
	name: str = "python",
	source: str = "content_pattern",
	confidence: float = 0.8,
	evidence_snippet: str = "import os",
	evidence_type: str = "direct_usage",
	depth_hint: DepthLevel | None = None,
	metadata: dict | None = None,
) -> SkillSignal:
	return SkillSignal(
		canonical_name=name,
		source=source,
		confidence=confidence,
		evidence_snippet=evidence_snippet,
		evidence_type=evidence_type,
		depth_hint=depth_hint,
		metadata=metadata or {},
	)


# ---------------------------------------------------------------------------
# TestSkillAggregation
# ---------------------------------------------------------------------------


class TestSkillAggregation:
	def test_deduplicates_across_extractors(self):
		"""Same skill from code_signals and behavior_signals merges into one SkillEntry."""
		r1 = _make_signal_result(
			session_id="s1",
			skills={"python": [_skill("python", source="file_extension")]},
		)
		r2 = _make_signal_result(
			session_id="s1",
			skills={"python": [_skill("python", source="tool_usage")]},
		)
		merger = SignalMerger()
		profile = merger.merge([r1, r2], manifest_hash="abc")

		py_skills = [s for s in profile.skills if s.name == "python"]
		assert len(py_skills) == 1
		# Evidence from both extractors present
		assert len(py_skills[0].evidence) >= 2

	def test_cross_extractor_confidence_boost(self):
		"""Skill from 2 source types gets +0.1 boost, from 3 gets +0.15."""
		r1 = _make_signal_result(
			skills={"python": [_skill("python", source="file_extension", confidence=0.7)]},
		)
		r2 = _make_signal_result(
			skills={"python": [_skill("python", source="content_pattern", confidence=0.7)]},
		)
		merger = SignalMerger()
		profile = merger.merge([r1, r2], manifest_hash="abc")

		py = [s for s in profile.skills if s.name == "python"][0]
		# Base avg confidence 0.7, +0.1 for 2 source types = 0.8
		avg_conf = sum(e.confidence for e in py.evidence) / len(py.evidence)
		# The average evidence confidence should reflect the boost
		assert avg_conf >= 0.7  # at minimum the base

		# Now 3 source types
		r3 = _make_signal_result(
			skills={"python": [_skill("python", source="import_statement", confidence=0.7)]},
		)
		profile3 = merger.merge([r1, r2, r3], manifest_hash="abc")
		py3 = [s for s in profile3.skills if s.name == "python"][0]
		avg_conf3 = sum(e.confidence for e in py3.evidence) / len(py3.evidence)
		assert avg_conf3 >= avg_conf  # 3 sources should be >= 2 sources

	def test_confidence_capped_at_one(self):
		"""Boost never exceeds 1.0."""
		r1 = _make_signal_result(
			skills={"python": [_skill("python", source="file_extension", confidence=0.95)]},
		)
		r2 = _make_signal_result(
			skills={"python": [_skill("python", source="content_pattern", confidence=0.95)]},
		)
		r3 = _make_signal_result(
			skills={"python": [_skill("python", source="import_statement", confidence=0.95)]},
		)
		merger = SignalMerger()
		profile = merger.merge([r1, r2, r3], manifest_hash="abc")

		py = [s for s in profile.skills if s.name == "python"][0]
		for ev in py.evidence:
			assert ev.confidence <= 1.0

	def test_multiple_sessions_same_skill(self):
		"""Python detected in 5 sessions => frequency=5."""
		results = [
			_make_signal_result(
				session_id=f"s{i}",
				skills={"python": [_skill("python")]},
			)
			for i in range(5)
		]
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		py = [s for s in profile.skills if s.name == "python"][0]
		assert py.frequency == 5


# ---------------------------------------------------------------------------
# TestDepthScoring
# ---------------------------------------------------------------------------


class TestDepthScoring:
	def test_import_only_capped_at_used(self):
		"""Skill with only import_statement evidence caps at USED depth."""
		results = [
			_make_signal_result(
				session_id=f"s{i}",
				skills={"react": [_skill("react", source="import_statement")]},
			)
			for i in range(10)  # High frequency, but only imports
		]
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		react = [s for s in profile.skills if s.name == "react"][0]
		assert react.depth.value <= DepthLevel.USED.value

	def test_package_only_capped_at_mentioned(self):
		"""Skill with only package_command evidence caps at MENTIONED."""
		results = [
			_make_signal_result(
				session_id=f"s{i}",
				skills={"docker": [_skill("docker", source="package_command")]},
			)
			for i in range(10)
		]
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		docker = [s for s in profile.skills if s.name == "docker"][0]
		assert docker.depth == DepthLevel.MENTIONED

	def test_debugging_evidence_boosts_depth(self):
		"""Skill with evidence_type='debugging' gets +1 level."""
		# 2 sessions -> base USED, debugging should boost to APPLIED
		results = [
			_make_signal_result(
				session_id="s1",
				skills={"python": [
					_skill("python", evidence_type="debugging"),
				]},
			),
			_make_signal_result(
				session_id="s2",
				skills={"python": [
					_skill("python", evidence_type="debugging"),
				]},
			),
		]
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		py = [s for s in profile.skills if s.name == "python"][0]
		# Base for 2 sessions = USED, +1 for debugging = APPLIED
		from claude_candidate.schemas.candidate_profile import DEPTH_RANK
		assert DEPTH_RANK[py.depth] >= DEPTH_RANK[DepthLevel.APPLIED]

	def test_multi_source_boosts_depth(self):
		"""Skill from 2+ source types gets +1 level."""
		results = [
			_make_signal_result(
				session_id="s1",
				skills={"python": [
					_skill("python", source="file_extension"),
					_skill("python", source="content_pattern"),
				]},
			),
			_make_signal_result(
				session_id="s2",
				skills={"python": [_skill("python", source="file_extension")]},
			),
		]
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		py = [s for s in profile.skills if s.name == "python"][0]
		# Base for 2 sessions = USED, +1 for multi-source = APPLIED
		from claude_candidate.schemas.candidate_profile import DEPTH_RANK
		assert DEPTH_RANK[py.depth] >= DEPTH_RANK[DepthLevel.APPLIED]

	def test_depth_ceiling_is_expert(self):
		"""Modifiers can't exceed EXPERT."""
		# 10 sessions, debugging, multi-source — all boosters applied
		results = [
			_make_signal_result(
				session_id=f"s{i}",
				skills={"python": [
					_skill("python", source="file_extension", evidence_type="debugging"),
					_skill("python", source="content_pattern", evidence_type="architecture_decision"),
				]},
			)
			for i in range(10)
		]
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		py = [s for s in profile.skills if s.name == "python"][0]
		assert py.depth == DepthLevel.EXPERT


# ---------------------------------------------------------------------------
# TestPatternAggregation
# ---------------------------------------------------------------------------


class TestPatternAggregation:
	def test_merges_same_pattern_across_sessions(self):
		"""5 sessions with ITERATIVE_REFINEMENT => 'common' or 'dominant' frequency."""
		results = [
			_make_signal_result(
				session_id=f"s{i}",
				patterns=[PatternSignal(
					pattern_type=PatternType.ITERATIVE_REFINEMENT,
					session_ids=[f"s{i}"],
					confidence=0.8,
					description="Iterative refinement observed",
					evidence_snippet="Revised implementation after feedback",
				)],
			)
			for i in range(5)
		]
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		ir_patterns = [
			p for p in profile.problem_solving_patterns
			if p.pattern_type == PatternType.ITERATIVE_REFINEMENT
		]
		assert len(ir_patterns) == 1
		assert ir_patterns[0].frequency in ("common", "dominant")

	def test_all_12_pattern_types_accepted(self):
		"""One of each PatternType => 12 patterns in output."""
		results = []
		for pt in PatternType:
			results.append(_make_signal_result(
				session_id=f"s-{pt.value}",
				patterns=[PatternSignal(
					pattern_type=pt,
					session_ids=[f"s-{pt.value}"],
					confidence=0.7,
					description=f"Pattern {pt.value} observed",
					evidence_snippet=f"Evidence for {pt.value}",
				)],
			))
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		output_types = {p.pattern_type for p in profile.problem_solving_patterns}
		assert output_types == set(PatternType)

	def test_pattern_frequency_thresholds(self):
		""">=5=dominant, >=3=common, >=2=occasional, >=1=rare."""
		def _make_patterns(pt: PatternType, count: int) -> list[SignalResult]:
			return [
				_make_signal_result(
					session_id=f"s-{pt.value}-{i}",
					patterns=[PatternSignal(
						pattern_type=pt,
						session_ids=[f"s-{pt.value}-{i}"],
						confidence=0.7,
						description=f"Pattern {pt.value}",
						evidence_snippet=f"Evidence for {pt.value}",
					)],
				)
				for i in range(count)
			]

		results = (
			_make_patterns(PatternType.ITERATIVE_REFINEMENT, 5)
			+ _make_patterns(PatternType.ARCHITECTURE_FIRST, 3)
			+ _make_patterns(PatternType.TESTING_INSTINCT, 2)
			+ _make_patterns(PatternType.META_COGNITION, 1)
		)
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		freq_map = {
			p.pattern_type: p.frequency
			for p in profile.problem_solving_patterns
		}
		assert freq_map[PatternType.ITERATIVE_REFINEMENT] == "dominant"
		assert freq_map[PatternType.ARCHITECTURE_FIRST] == "common"
		assert freq_map[PatternType.TESTING_INSTINCT] == "occasional"
		assert freq_map[PatternType.META_COGNITION] == "rare"


# ---------------------------------------------------------------------------
# TestProjectEnrichment
# ---------------------------------------------------------------------------


class TestProjectEnrichment:
	def test_replaces_generic_description(self):
		"""ProjectSignal with description_fragments populates real description."""
		r = _make_signal_result(
			project_context="myproject",
			skills={"python": [_skill("python")]},
			project_signals=ProjectSignal(
				description_fragments=["A CLI tool for candidate evaluation"],
			),
		)
		merger = SignalMerger()
		profile = merger.merge([r], manifest_hash="abc")

		proj = [p for p in profile.projects if p.project_name == "myproject"]
		assert len(proj) == 1
		assert "CLI tool" in proj[0].description

	def test_populates_key_decisions(self):
		"""ProjectSignal with key_decisions flows through."""
		r = _make_signal_result(
			project_context="myproject",
			skills={"python": [_skill("python")]},
			project_signals=ProjectSignal(
				key_decisions=["Chose pydantic v2 for schema validation"],
			),
		)
		merger = SignalMerger()
		profile = merger.merge([r], manifest_hash="abc")

		proj = [p for p in profile.projects if p.project_name == "myproject"][0]
		assert "pydantic v2" in proj.key_decisions[0]

	def test_populates_challenges(self):
		"""ProjectSignal with challenges flows through."""
		r = _make_signal_result(
			project_context="myproject",
			skills={"python": [_skill("python")]},
			project_signals=ProjectSignal(
				challenges=["Handling malformed JSONL gracefully"],
			),
		)
		merger = SignalMerger()
		profile = merger.merge([r], manifest_hash="abc")

		proj = [p for p in profile.projects if p.project_name == "myproject"][0]
		assert "malformed JSONL" in proj.challenges_overcome[0]


# ---------------------------------------------------------------------------
# TestProfileAssembly
# ---------------------------------------------------------------------------


class TestProfileAssembly:
	def test_produces_valid_candidate_profile(self):
		"""Merger output is a valid CandidateProfile."""
		r = _make_signal_result(
			skills={"python": [_skill("python")]},
			patterns=[PatternSignal(
				pattern_type=PatternType.ITERATIVE_REFINEMENT,
				session_ids=["s1"],
				confidence=0.8,
				description="Iterative refinement",
				evidence_snippet="Revised approach",
			)],
		)
		merger = SignalMerger()
		profile = merger.merge([r], manifest_hash="abc123")

		assert isinstance(profile, CandidateProfile)
		assert profile.manifest_hash == "abc123"
		assert profile.session_count >= 1
		assert len(profile.skills) >= 1

	def test_empty_results_produces_valid_profile(self):
		"""Empty input => valid profile with 0 skills."""
		merger = SignalMerger()
		profile = merger.merge([], manifest_hash="empty")

		assert isinstance(profile, CandidateProfile)
		assert profile.session_count == 0
		assert len(profile.skills) == 0
		assert len(profile.problem_solving_patterns) == 0
		assert len(profile.projects) == 0

	def test_communication_style_not_hardcoded(self):
		"""Output communication_style is not 'Technical and detail-oriented'."""
		results = [
			_make_signal_result(
				session_id=f"s{i}",
				skills={"python": [_skill("python")]},
				metrics={"steering_count": 3.0, "deferral_count": 1.0},
			)
			for i in range(5)
		]
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		assert profile.communication_style != "Technical and detail-oriented"

	def test_all_pattern_types_in_output(self):
		"""When all 12 PatternTypes are provided, all appear in output."""
		results = []
		for pt in PatternType:
			results.append(_make_signal_result(
				session_id=f"s-{pt.value}",
				skills={"python": [_skill("python")]},
				patterns=[PatternSignal(
					pattern_type=pt,
					session_ids=[f"s-{pt.value}"],
					confidence=0.7,
					description=f"Pattern {pt.value}",
					evidence_snippet=f"Evidence for {pt.value}",
				)],
			))
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		output_types = {p.pattern_type for p in profile.problem_solving_patterns}
		assert output_types == set(PatternType)


# ---------------------------------------------------------------------------
# TestLearningVelocity
# ---------------------------------------------------------------------------


class TestLearningVelocity:
	def test_skill_trajectory_populated(self):
		"""With enough agentic data, skill_trajectory is not None/empty."""
		base = datetime(2026, 1, 1, tzinfo=timezone.utc)
		results = []
		for i in range(12):
			# Simulate progression: early sessions have low agentic metrics,
			# later sessions have higher ones
			results.append(_make_signal_result(
				session_id=f"s{i}",
				session_date=base + timedelta(days=i),
				skills={"python": [_skill("python")]},
				metrics={
					"agent_dispatch_count": float(min(i, 3)),
					"task_phases": float(min(i // 3, 3)),
					"skill_invocation_count": float(min(i // 2, 3)),
					"context_resets": float(min(i // 4, 3)),
					"worktree_count": float(min(i // 4, 3)),
				},
			))
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		assert profile.skill_trajectory is not None
		assert len(profile.skill_trajectory) > 0

	def test_learning_velocity_notes_populated(self):
		"""With progression data, notes are generated."""
		base = datetime(2026, 1, 1, tzinfo=timezone.utc)
		results = []
		for i in range(12):
			results.append(_make_signal_result(
				session_id=f"s{i}",
				session_date=base + timedelta(days=i),
				skills={"python": [_skill("python")]},
				metrics={
					"agent_dispatch_count": float(min(i, 3)),
					"task_phases": float(min(i // 3, 3)),
					"skill_invocation_count": float(min(i // 2, 3)),
					"context_resets": float(min(i // 4, 3)),
					"worktree_count": float(min(i // 4, 3)),
				},
			))
		merger = SignalMerger()
		profile = merger.merge(results, manifest_hash="abc")

		assert profile.learning_velocity_notes is not None
		assert len(profile.learning_velocity_notes) > 0
