"""Tests for shared extractor interfaces: SkillSignal, SignalResult, NormalizedSession, PatternSignal."""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from claude_candidate.extractors import (
	NormalizedSession,
	PatternSignal,
	ProjectSignal,
	SignalResult,
	SkillSignal,
)
from claude_candidate.message_format import NormalizedMessage
from claude_candidate.schemas.candidate_profile import DepthLevel, PatternType


# === SkillSignal ===


class TestSkillSignal:
	def test_valid_creation(self):
		signal = SkillSignal(
			canonical_name="python",
			source="file_extension",
			confidence=0.9,
			depth_hint=DepthLevel.APPLIED,
			evidence_snippet="Wrote a Python decorator for caching",
			evidence_type="direct_usage",
		)
		assert signal.canonical_name == "python"
		assert signal.source == "file_extension"
		assert signal.confidence == 0.9
		assert signal.depth_hint == DepthLevel.APPLIED
		assert signal.evidence_type == "direct_usage"

	def test_confidence_default(self):
		signal = SkillSignal(
			canonical_name="rust",
			source="content_pattern",
			evidence_snippet="Used lifetime annotations",
		)
		assert signal.confidence == 0.7

	def test_confidence_upper_bound(self):
		with pytest.raises(ValidationError):
			SkillSignal(
				canonical_name="go",
				source="import_statement",
				confidence=1.1,
				evidence_snippet="Imported net/http",
			)

	def test_confidence_lower_bound(self):
		with pytest.raises(ValidationError):
			SkillSignal(
				canonical_name="go",
				source="import_statement",
				confidence=-0.1,
				evidence_snippet="Imported net/http",
			)

	def test_confidence_exact_bounds(self):
		low = SkillSignal(
			canonical_name="js",
			source="file_extension",
			confidence=0.0,
			evidence_snippet="Found .js file",
		)
		high = SkillSignal(
			canonical_name="js",
			source="file_extension",
			confidence=1.0,
			evidence_snippet="Found .js file",
		)
		assert low.confidence == 0.0
		assert high.confidence == 1.0

	def test_snippet_max_length_500(self):
		# Exactly 500 characters should work
		signal = SkillSignal(
			canonical_name="python",
			source="content_pattern",
			evidence_snippet="x" * 500,
		)
		assert len(signal.evidence_snippet) == 500

		# 501 characters should fail
		with pytest.raises(ValidationError):
			SkillSignal(
				canonical_name="python",
				source="content_pattern",
				evidence_snippet="x" * 501,
			)

	def test_all_source_types_accepted(self):
		sources = [
			"file_extension", "content_pattern", "import_statement",
			"package_command", "tool_usage", "agent_dispatch",
			"skill_invocation", "user_message", "git_workflow",
			"quality_signal",
		]
		for source in sources:
			signal = SkillSignal(
				canonical_name="test",
				source=source,
				evidence_snippet=f"Evidence for {source}",
			)
			assert signal.source == source

	def test_invalid_source_rejected(self):
		with pytest.raises(ValidationError):
			SkillSignal(
				canonical_name="test",
				source="nonexistent_source",
				evidence_snippet="Some evidence",
			)

	def test_frozen(self):
		signal = SkillSignal(
			canonical_name="python",
			source="file_extension",
			evidence_snippet="Found .py file",
		)
		with pytest.raises(ValidationError):
			signal.canonical_name = "rust"

	def test_metadata_default_empty(self):
		signal = SkillSignal(
			canonical_name="python",
			source="file_extension",
			evidence_snippet="Found .py file",
		)
		assert signal.metadata == {}

	def test_metadata_custom(self):
		signal = SkillSignal(
			canonical_name="python",
			source="file_extension",
			evidence_snippet="Found .py file",
			metadata={"line_number": 42, "file": "main.py"},
		)
		assert signal.metadata["line_number"] == 42


# === PatternSignal ===


class TestPatternSignal:
	def test_all_pattern_types(self):
		"""All 12 PatternType values should be accepted."""
		expected_types = [
			PatternType.SYSTEMATIC_DEBUGGING,
			PatternType.ARCHITECTURE_FIRST,
			PatternType.ITERATIVE_REFINEMENT,
			PatternType.TRADEOFF_ANALYSIS,
			PatternType.SCOPE_MANAGEMENT,
			PatternType.DOCUMENTATION_DRIVEN,
			PatternType.RECOVERY_FROM_FAILURE,
			PatternType.TOOL_SELECTION,
			PatternType.MODULAR_THINKING,
			PatternType.TESTING_INSTINCT,
			PatternType.META_COGNITION,
			PatternType.COMMUNICATION_CLARITY,
		]
		assert len(expected_types) == 12

		for pt in expected_types:
			signal = PatternSignal(
				pattern_type=pt,
				session_ids=["sess-001"],
				confidence=0.8,
				description=f"Observed {pt.value}",
				evidence_snippet=f"Evidence of {pt.value}",
			)
			assert signal.pattern_type == pt

	def test_valid_creation(self):
		signal = PatternSignal(
			pattern_type=PatternType.SYSTEMATIC_DEBUGGING,
			session_ids=["sess-001", "sess-002"],
			confidence=0.85,
			description="Consistently uses divide-and-conquer debugging",
			evidence_snippet="Narrowed down the bug by bisecting commits",
		)
		assert signal.pattern_type == PatternType.SYSTEMATIC_DEBUGGING
		assert len(signal.session_ids) == 2
		assert signal.confidence == 0.85

	def test_confidence_bounds(self):
		with pytest.raises(ValidationError):
			PatternSignal(
				pattern_type=PatternType.ARCHITECTURE_FIRST,
				session_ids=["sess-001"],
				confidence=1.5,
				description="test",
				evidence_snippet="test",
			)

	def test_snippet_max_length_500(self):
		with pytest.raises(ValidationError):
			PatternSignal(
				pattern_type=PatternType.TESTING_INSTINCT,
				session_ids=["sess-001"],
				description="test",
				evidence_snippet="x" * 501,
			)

	def test_frozen(self):
		signal = PatternSignal(
			pattern_type=PatternType.MODULAR_THINKING,
			session_ids=["sess-001"],
			description="Breaks problems into modules",
			evidence_snippet="Extracted common logic into reusable utility",
		)
		with pytest.raises(ValidationError):
			signal.description = "changed"


# === SignalResult ===


class TestSignalResult:
	def test_empty_result_with_defaults(self):
		result = SignalResult(
			session_id="sess-001",
			session_date=datetime(2026, 3, 15, 10, 0),
			project_context="test-project",
		)
		assert result.session_id == "sess-001"
		assert result.skills == {}
		assert result.patterns == []
		assert result.project_signals is None
		assert result.metrics == {}
		assert result.git_branch is None

	def test_result_with_skills_and_patterns(self):
		skill = SkillSignal(
			canonical_name="python",
			source="file_extension",
			confidence=0.9,
			evidence_snippet="Found .py file",
		)
		pattern = PatternSignal(
			pattern_type=PatternType.TESTING_INSTINCT,
			session_ids=["sess-001"],
			description="Writes tests first",
			evidence_snippet="Created test file before implementation",
		)
		result = SignalResult(
			session_id="sess-001",
			session_date=datetime(2026, 3, 15, 10, 0),
			project_context="test-project",
			git_branch="feat/new-feature",
			skills={"python": [skill]},
			patterns=[pattern],
			project_signals=ProjectSignal(
				key_decisions=["Used FastAPI over Flask"],
				challenges=["Complex async flow"],
			),
			metrics={"message_count": 42.0},
		)
		assert "python" in result.skills
		assert len(result.skills["python"]) == 1
		assert result.skills["python"][0].canonical_name == "python"
		assert len(result.patterns) == 1
		assert result.patterns[0].pattern_type == PatternType.TESTING_INSTINCT
		assert result.project_signals is not None
		assert result.project_signals.key_decisions == ["Used FastAPI over Flask"]
		assert result.metrics["message_count"] == 42.0
		assert result.git_branch == "feat/new-feature"

	def test_frozen(self):
		result = SignalResult(
			session_id="sess-001",
			session_date=datetime(2026, 3, 15),
			project_context="test",
		)
		with pytest.raises(ValidationError):
			result.session_id = "sess-002"


# === NormalizedSession ===


class TestNormalizedSession:
	def test_construction_with_all_fields(self):
		msg: NormalizedMessage = {
			"role": "user",
			"content": [{"type": "text", "text": "Hello"}],
			"raw": {"type": "user", "message": {"content": "Hello"}},
		}
		session = NormalizedSession(
			session_id="2026-03-15_10-00-00_abc12345",
			timestamp=datetime(2026, 3, 15, 10, 0),
			cwd="/home/user/project",
			project_context="my-project",
			git_branch="main",
			messages=[msg],
		)
		assert session.session_id == "2026-03-15_10-00-00_abc12345"
		assert session.timestamp == datetime(2026, 3, 15, 10, 0)
		assert session.cwd == "/home/user/project"
		assert session.project_context == "my-project"
		assert session.git_branch == "main"
		assert len(session.messages) == 1
		assert session.messages[0]["role"] == "user"

	def test_git_branch_optional(self):
		session = NormalizedSession(
			session_id="sess-001",
			timestamp=datetime(2026, 3, 15),
			cwd="/tmp",
			project_context="test",
			messages=[],
		)
		assert session.git_branch is None

	def test_frozen(self):
		session = NormalizedSession(
			session_id="sess-001",
			timestamp=datetime(2026, 3, 15),
			cwd="/tmp",
			project_context="test",
			messages=[],
		)
		with pytest.raises(ValidationError):
			session.session_id = "sess-002"

	def test_multiple_messages(self):
		msgs: list[NormalizedMessage] = [
			{
				"role": "user",
				"content": [{"type": "text", "text": "Fix the bug"}],
				"raw": {},
			},
			{
				"role": "assistant",
				"content": [{"type": "text", "text": "I'll look into it"}],
				"raw": {},
			},
			{
				"role": "tool_use",
				"content": [{"type": "tool_use", "name": "Bash", "input": {"cmd": "ls"}}],
				"raw": {},
			},
		]
		session = NormalizedSession(
			session_id="sess-001",
			timestamp=datetime(2026, 3, 15),
			cwd="/home/user/project",
			project_context="debug-session",
			messages=msgs,
		)
		assert len(session.messages) == 3
		assert session.messages[0]["role"] == "user"
		assert session.messages[1]["role"] == "assistant"
		assert session.messages[2]["role"] == "tool_use"


# === ProjectSignal ===


class TestProjectSignal:
	def test_defaults(self):
		ps = ProjectSignal()
		assert ps.key_decisions == []
		assert ps.challenges == []
		assert ps.description_fragments == []

	def test_with_data(self):
		ps = ProjectSignal(
			key_decisions=["Chose SQLite for storage"],
			challenges=["Complex async patterns"],
			description_fragments=["A CLI tool for candidate evaluation"],
		)
		assert len(ps.key_decisions) == 1
		assert len(ps.challenges) == 1
		assert len(ps.description_fragments) == 1
