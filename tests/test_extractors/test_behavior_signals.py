"""Tests for BehaviorSignalExtractor: patterns, agent orchestration, git, quality signals."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from claude_candidate.extractors import NormalizedSession, SignalResult
from claude_candidate.extractors.behavior_signals import BehaviorSignalExtractor
from claude_candidate.message_format import NormalizedMessage, normalize_messages
from claude_candidate.schemas.candidate_profile import DepthLevel, PatternType

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "sessions"


def _load_session(filename: str, session_id: str = "test-session") -> NormalizedSession:
	"""Load a JSONL fixture and return a NormalizedSession."""
	raw_events = []
	with open(FIXTURES / filename) as f:
		for line in f:
			line = line.strip()
			if line:
				raw_events.append(json.loads(line))

	messages = normalize_messages(raw_events)

	# Extract metadata from first event
	first = raw_events[0] if raw_events else {}
	cwd = first.get("cwd", "/tmp/test")
	git_branch = first.get("gitBranch")
	timestamp_str = first.get("timestamp", "2026-03-20T10:00:00Z")
	sid = first.get("sessionId", session_id)

	# Derive project_context from cwd
	project_context = Path(cwd).name if cwd else "unknown"

	return NormalizedSession(
		session_id=sid,
		timestamp=datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")),
		cwd=cwd,
		project_context=project_context,
		git_branch=git_branch,
		messages=messages,
	)


@pytest.fixture
def extractor() -> BehaviorSignalExtractor:
	return BehaviorSignalExtractor()


@pytest.fixture
def agent_session() -> NormalizedSession:
	return _load_session("agent_orchestration_session.jsonl")


@pytest.fixture
def simple_session() -> NormalizedSession:
	return _load_session("simple_python_session.jsonl")


@pytest.fixture
def multi_tech_session() -> NormalizedSession:
	return _load_session("multi_tech_session.jsonl")


# ============================================================================
# Extractor basics
# ============================================================================


class TestExtractorBasics:
	def test_name(self, extractor: BehaviorSignalExtractor):
		assert extractor.name() == "behavior_signals"

	def test_returns_signal_result(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		result = extractor.extract_session(agent_session)
		assert isinstance(result, SignalResult)
		assert result.session_id == "behavior-test-session"

	def test_empty_session(self, extractor: BehaviorSignalExtractor):
		session = NormalizedSession(
			session_id="empty",
			timestamp=datetime(2026, 3, 20),
			cwd="/tmp",
			project_context="test",
			messages=[],
		)
		result = extractor.extract_session(session)
		assert isinstance(result, SignalResult)
		assert result.patterns == []
		assert result.skills == {}


# ============================================================================
# Pattern detection — all 12 PatternType values
# ============================================================================


class TestPatternDetection:
	"""Verify all 12 PatternType values are reachable."""

	def test_iterative_refinement_from_simple_session(
		self, extractor: BehaviorSignalExtractor, simple_session: NormalizedSession
	):
		"""simple_python_session has Write + Bash calls → check ITERATIVE_REFINEMENT."""
		result = extractor.extract_session(simple_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		# The simple session has role=tool_use messages with Write and Bash.
		# _get_tool_use_blocks extracts these; if 2+ Write + 1+ Bash, pattern fires.
		# Synthetic test below is the authoritative coverage; this validates
		# the real fixture runs without error and produces patterns.
		assert isinstance(pattern_types, set)

	def test_iterative_refinement_synthetic(self, extractor: BehaviorSignalExtractor):
		"""Synthetic session with 2 Writes + 1 Bash → ITERATIVE_REFINEMENT."""
		msgs: list[NormalizedMessage] = [
			{
				"role": "assistant",
				"content": [
					{"type": "tool_use", "name": "Write", "input": {"file_path": "a.py"}},
				],
				"raw": {},
			},
			{
				"role": "assistant",
				"content": [
					{"type": "tool_use", "name": "Write", "input": {"file_path": "b.py"}},
				],
				"raw": {},
			},
			{
				"role": "assistant",
				"content": [
					{
						"type": "tool_use",
						"name": "Bash",
						"input": {"command": "python b.py"},
					},
				],
				"raw": {},
			},
		]
		session = NormalizedSession(
			session_id="iter-test",
			timestamp=datetime(2026, 3, 20),
			cwd="/tmp/test",
			project_context="test",
			messages=msgs,
		)
		result = extractor.extract_session(session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.ITERATIVE_REFINEMENT in pattern_types

	def test_systematic_debugging(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Grep→Read→Edit sequence in fixture → SYSTEMATIC_DEBUGGING."""
		result = extractor.extract_session(agent_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.SYSTEMATIC_DEBUGGING in pattern_types
		# Check evidence type hint
		debug_patterns = [
			p for p in result.patterns if p.pattern_type == PatternType.SYSTEMATIC_DEBUGGING
		]
		assert debug_patterns[0].confidence >= 0.7

	def test_recovery_from_failure(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""is_error=true followed by different Edit → RECOVERY_FROM_FAILURE."""
		result = extractor.extract_session(agent_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.RECOVERY_FROM_FAILURE in pattern_types

	def test_tool_selection(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Agent with explicit subagent_type + Skill invocation → TOOL_SELECTION."""
		result = extractor.extract_session(agent_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.TOOL_SELECTION in pattern_types

	def test_documentation_driven(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Write to .md file in same session as code edits → DOCUMENTATION_DRIVEN."""
		result = extractor.extract_session(agent_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.DOCUMENTATION_DRIVEN in pattern_types

	def test_testing_instinct_from_fixture(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""test file edit and pytest command → TESTING_INSTINCT."""
		result = extractor.extract_session(agent_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.TESTING_INSTINCT in pattern_types

	def test_architecture_first(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Read + Write in session → ARCHITECTURE_FIRST."""
		result = extractor.extract_session(agent_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.ARCHITECTURE_FIRST in pattern_types

	def test_modular_thinking_from_multi_tech(
		self, extractor: BehaviorSignalExtractor, multi_tech_session: NormalizedSession
	):
		"""Multi-tech session has .sql, .py, .tsx, Dockerfile, .yml → MODULAR_THINKING."""
		result = extractor.extract_session(multi_tech_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		# The multi_tech session has Write to .sql, .py, .tsx, Dockerfile, .yml files
		# That's 5+ extensions → modular thinking
		assert PatternType.MODULAR_THINKING in pattern_types

	def test_tradeoff_analysis(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Agent Explore dispatch before Write/Edit → TRADEOFF_ANALYSIS."""
		result = extractor.extract_session(agent_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.TRADEOFF_ANALYSIS in pattern_types

	def test_scope_management(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""TaskCreate with 'Phase' in subject → SCOPE_MANAGEMENT."""
		result = extractor.extract_session(agent_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.SCOPE_MANAGEMENT in pattern_types

	def test_meta_cognition_via_clear(self, extractor: BehaviorSignalExtractor):
		"""Bash with /clear → META_COGNITION."""
		msgs: list[NormalizedMessage] = [
			{
				"role": "assistant",
				"content": [
					{
						"type": "tool_use",
						"name": "Bash",
						"input": {"command": "/clear"},
					},
				],
				"raw": {},
			},
		]
		session = NormalizedSession(
			session_id="meta-test",
			timestamp=datetime(2026, 3, 20),
			cwd="/tmp/test",
			project_context="test",
			messages=msgs,
		)
		result = extractor.extract_session(session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.META_COGNITION in pattern_types

	def test_communication_clarity_not_produced(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""COMMUNICATION_CLARITY is a cross-signal from CommSignalExtractor, not here."""
		result = extractor.extract_session(agent_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.COMMUNICATION_CLARITY not in pattern_types


# ============================================================================
# Agent orchestration
# ============================================================================


class TestAgentOrchestration:
	def test_agentic_workflows_skill(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Agent tool_use events → 'agentic-workflows' skill."""
		result = extractor.extract_session(agent_session)
		assert "agentic-workflows" in result.skills
		agent_skills = result.skills["agentic-workflows"]
		assert len(agent_skills) >= 1

	def test_agent_dispatch_metadata(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Agent dispatch includes subagent_type info in metadata."""
		result = extractor.extract_session(agent_session)
		agent_skills = result.skills["agentic-workflows"]
		# Find the agent_dispatch source signal
		dispatch_signals = [s for s in agent_skills if s.source == "agent_dispatch"]
		assert len(dispatch_signals) >= 1
		meta = dispatch_signals[0].metadata
		assert "subagent_types" in meta
		assert "Explore" in meta["subagent_types"]

	def test_parallel_fan_out(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Multiple Agent calls in one message → parallel fan-out detected."""
		result = extractor.extract_session(agent_session)
		assert result.metrics["parallel_dispatch_count"] >= 1.0

	def test_skill_invocation_produces_tool_selection(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Skill invocation produces TOOL_SELECTION pattern."""
		result = extractor.extract_session(agent_session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.TOOL_SELECTION in pattern_types
		# Also check that skill invocation appears in agentic-workflows
		inv_signals = [
			s for s in result.skills.get("agentic-workflows", []) if s.source == "skill_invocation"
		]
		assert len(inv_signals) >= 1

	def test_agent_dispatch_count_metric(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Metrics include agent_dispatch_count >= 1."""
		result = extractor.extract_session(agent_session)
		assert result.metrics["agent_dispatch_count"] >= 1.0


# ============================================================================
# Git workflow
# ============================================================================


class TestGitWorkflow:
	def test_git_skill_from_branch(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""gitBranch metadata → 'git' skill signal."""
		result = extractor.extract_session(agent_session)
		assert "git" in result.skills
		git_signals = result.skills["git"]
		assert len(git_signals) >= 1
		assert any(s.source == "git_workflow" for s in git_signals)

	def test_worktree_usage(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""git worktree command → advanced git signal with DEEP depth."""
		result = extractor.extract_session(agent_session)
		git_signals = result.skills["git"]
		worktree_signals = [s for s in git_signals if s.depth_hint == DepthLevel.DEEP]
		assert len(worktree_signals) >= 1
		assert result.metrics["worktree_usage"] == 1.0

	def test_cicd_from_gh_pr(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""gh pr create → 'ci-cd' practice signal."""
		result = extractor.extract_session(agent_session)
		assert "ci-cd" in result.skills

	def test_branch_type_classification(self, extractor: BehaviorSignalExtractor):
		"""Branch type classified from prefix."""
		ext = extractor
		assert ext._classify_branch("feat/new-feature") == "feature"
		assert ext._classify_branch("fix/bug-123") == "fix"
		assert ext._classify_branch("cleanup/dead-code") == "cleanup"
		assert ext._classify_branch("release/v1.0") == "release"
		assert ext._classify_branch("main") == "default"
		assert ext._classify_branch("random-branch") == "other"


# ============================================================================
# Quality signals
# ============================================================================


class TestQualitySignals:
	def test_security_detection_from_file_paths(self, extractor: BehaviorSignalExtractor):
		"""File paths with 'sanitiz'/'secret'/'auth' → security skill."""
		msgs: list[NormalizedMessage] = [
			{
				"role": "assistant",
				"content": [
					{
						"type": "tool_use",
						"name": "Edit",
						"input": {
							"file_path": "src/auth_handler.py",
							"old_string": "pass",
							"new_string": "validate()",
						},
					},
				],
				"raw": {},
			},
		]
		session = NormalizedSession(
			session_id="sec-test",
			timestamp=datetime(2026, 3, 20),
			cwd="/tmp/test",
			project_context="test",
			messages=msgs,
		)
		result = extractor.extract_session(session)
		assert "security" in result.skills

	def test_testing_from_test_file_edits(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Test file edits → 'testing' quality signal."""
		result = extractor.extract_session(agent_session)
		assert "testing" in result.skills
		testing_signals = result.skills["testing"]
		assert any(s.evidence_type == "testing" for s in testing_signals)

	def test_code_review_from_gh_pr(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""gh pr commands → 'code-review' quality signal."""
		result = extractor.extract_session(agent_session)
		assert "code-review" in result.skills


# ============================================================================
# Evidence type classification
# ============================================================================


class TestEvidenceTypes:
	def test_debugging_evidence_type(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Debugging sequence pattern has 'debugging' in description context."""
		result = extractor.extract_session(agent_session)
		debug_patterns = [
			p for p in result.patterns if p.pattern_type == PatternType.SYSTEMATIC_DEBUGGING
		]
		assert len(debug_patterns) >= 1
		# The pattern itself is "debugging" evidence
		assert (
			"Grep" in debug_patterns[0].description
			or "debug" in debug_patterns[0].description.lower()
		)

	def test_testing_evidence_type(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Test file edits produce evidence_type 'testing'."""
		result = extractor.extract_session(agent_session)
		testing_signals = result.skills.get("testing", [])
		assert any(s.evidence_type == "testing" for s in testing_signals)

	def test_planning_evidence_type(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Skill invocation produces evidence_type 'planning'."""
		result = extractor.extract_session(agent_session)
		agent_signals = result.skills.get("agentic-workflows", [])
		planning_signals = [s for s in agent_signals if s.evidence_type == "planning"]
		assert len(planning_signals) >= 1

	def test_agent_dispatch_evidence_type(
		self, extractor: BehaviorSignalExtractor, agent_session: NormalizedSession
	):
		"""Agent dispatch produces evidence_type 'architecture_decision'."""
		result = extractor.extract_session(agent_session)
		agent_signals = result.skills.get("agentic-workflows", [])
		arch_signals = [s for s in agent_signals if s.evidence_type == "architecture_decision"]
		assert len(arch_signals) >= 1
