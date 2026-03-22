"""Tests for CommSignalExtractor: steering, scope management, grill-me, handoffs."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest

from claude_candidate.extractors import NormalizedSession, SignalResult
from claude_candidate.extractors.comm_signals import (
	CommSignalExtractor,
	_get_text,
	_is_human_message,
)
from claude_candidate.message_format import NormalizedMessage, normalize_messages
from claude_candidate.schemas.candidate_profile import PatternType

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures" / "sessions"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_fixture(name: str) -> list[dict]:
	"""Load a JSONL fixture file into a list of raw events."""
	path = FIXTURE_DIR / name
	events = []
	for line in path.read_text().splitlines():
		line = line.strip()
		if line:
			events.append(json.loads(line))
	return events


def _make_session(
	messages: list[NormalizedMessage],
	session_id: str = "test-session",
) -> NormalizedSession:
	"""Build a NormalizedSession from messages for unit tests."""
	return NormalizedSession(
		session_id=session_id,
		timestamp=datetime(2026, 3, 15, 10, 0),
		cwd="/Users/test/git/myproject",
		project_context="myproject",
		git_branch="feat/test",
		messages=messages,
	)


def _steering_session() -> NormalizedSession:
	"""Load the steering fixture and return a NormalizedSession."""
	raw_events = _load_fixture("steering_session.jsonl")
	messages = normalize_messages(raw_events)
	return NormalizedSession(
		session_id="steering-test-session",
		timestamp=datetime(2026, 3, 15, 10, 0),
		cwd="/Users/test/git/myproject",
		project_context="myproject",
		git_branch="feat/new-feature",
		messages=messages,
	)


# ---------------------------------------------------------------------------
# Human message filtering
# ---------------------------------------------------------------------------


class TestHumanMessageFiltering:
	def test_text_message_is_human(self):
		msg: NormalizedMessage = {
			"role": "user",
			"content": [{"type": "text", "text": "Hello"}],
			"raw": {},
		}
		assert _is_human_message(msg) is True

	def test_tool_result_message_is_not_human(self):
		msg: NormalizedMessage = {
			"role": "user",
			"content": [{"type": "tool_result", "content": "file written", "is_error": False}],
			"raw": {},
		}
		assert _is_human_message(msg) is False

	def test_assistant_message_is_not_human(self):
		msg: NormalizedMessage = {
			"role": "assistant",
			"content": [{"type": "text", "text": "Sure!"}],
			"raw": {},
		}
		assert _is_human_message(msg) is False

	def test_tool_use_message_is_not_human(self):
		msg: NormalizedMessage = {
			"role": "tool_use",
			"content": [{"type": "tool_use", "name": "Bash", "input": {}}],
			"raw": {},
		}
		assert _is_human_message(msg) is False

	def test_fixture_filters_tool_results(self):
		"""tool_result messages in the fixture should be excluded from human messages."""
		session = _steering_session()
		human_msgs = [m for m in session.messages if _is_human_message(m)]
		# All human messages should have text content, not tool_result
		for msg in human_msgs:
			for block in msg["content"]:
				assert block.get("type") != "tool_result", (
					f"tool_result leaked into human messages: {block}"
				)

	def test_human_message_count_from_fixture(self):
		"""The fixture has 7 real human text messages and 2 tool_result messages."""
		session = _steering_session()
		human_msgs = [m for m in session.messages if _is_human_message(m)]
		assert len(human_msgs) == 7


# ---------------------------------------------------------------------------
# Steering precision
# ---------------------------------------------------------------------------


class TestSteeringPrecision:
	def test_detects_communication_clarity(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		pattern_types = [p.pattern_type for p in result.patterns]
		assert PatternType.COMMUNICATION_CLARITY in pattern_types

	def test_steering_count_gte_1(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		clarity = _find_pattern(result, PatternType.COMMUNICATION_CLARITY)
		assert clarity is not None
		assert clarity.metadata["steering_count"] >= 1

	def test_short_correction_after_long_assistant(self):
		"""A short user message starting with redirect keyword after long assistant text."""
		long_text = "x " * 600  # >1000 chars
		messages: list[NormalizedMessage] = [
			{"role": "assistant", "content": [{"type": "text", "text": long_text}], "raw": {}},
			{
				"role": "user",
				"content": [{"type": "text", "text": "no, just do the simple version"}],
				"raw": {},
			},
		]
		session = _make_session(messages)
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		clarity = _find_pattern(result, PatternType.COMMUNICATION_CLARITY)
		assert clarity is not None
		assert clarity.metadata["steering_count"] >= 1

	def test_steering_metrics(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)
		assert result.metrics["steering_count"] >= 1


# ---------------------------------------------------------------------------
# Scope management
# ---------------------------------------------------------------------------


class TestScopeManagement:
	def test_detects_scope_management(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		pattern_types = [p.pattern_type for p in result.patterns]
		assert PatternType.SCOPE_MANAGEMENT in pattern_types

	def test_deferral_count_gte_1(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		scope = _find_pattern(result, PatternType.SCOPE_MANAGEMENT)
		assert scope is not None
		assert scope.metadata["deferral_count"] >= 1

	def test_detects_session_boundary(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		scope = _find_pattern(result, PatternType.SCOPE_MANAGEMENT)
		assert scope is not None
		assert scope.metadata["clean_exits"] >= 1

	def test_deferral_metrics(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)
		assert result.metrics["deferral_count"] >= 1


# ---------------------------------------------------------------------------
# Adversarial self-review
# ---------------------------------------------------------------------------


class TestAdversarialSelfReview:
	def test_detects_meta_cognition(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		pattern_types = [p.pattern_type for p in result.patterns]
		assert PatternType.META_COGNITION in pattern_types

	def test_grill_count_gte_1(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		meta = _find_pattern(result, PatternType.META_COGNITION)
		assert meta is not None
		assert meta.metadata["grill_count"] >= 1

	def test_honesty_requests_gte_1(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		meta = _find_pattern(result, PatternType.META_COGNITION)
		assert meta is not None
		assert meta.metadata["honesty_requests"] >= 1

	def test_feedback_invitations_detected(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		meta = _find_pattern(result, PatternType.META_COGNITION)
		assert meta is not None
		assert meta.metadata["feedback_invitations"] >= 1

	def test_grill_metrics(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)
		assert result.metrics["grill_count"] >= 1


# ---------------------------------------------------------------------------
# Handoff discipline
# ---------------------------------------------------------------------------


class TestHandoffDiscipline:
	def test_detects_documentation_driven(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		pattern_types = [p.pattern_type for p in result.patterns]
		assert PatternType.DOCUMENTATION_DRIVEN in pattern_types

	def test_handoff_count_gte_1(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		doc = _find_pattern(result, PatternType.DOCUMENTATION_DRIVEN)
		assert doc is not None
		assert doc.metadata["handoff_count"] >= 1

	def test_plan_references_gte_1(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		doc = _find_pattern(result, PatternType.DOCUMENTATION_DRIVEN)
		assert doc is not None
		assert doc.metadata["plan_references"] >= 1

	def test_detects_write_to_handoff_file(self):
		"""Write tool_use to a handoff file should be detected."""
		messages: list[NormalizedMessage] = [
			{
				"role": "user",
				"content": [{"type": "text", "text": "save the handoff notes"}],
				"raw": {},
			},
			{
				"role": "assistant",
				"content": [{
					"type": "tool_use",
					"name": "Write",
					"input": {"file_path": "/project/handoff-notes.md", "content": "notes"},
				}],
				"raw": {},
			},
		]
		session = _make_session(messages)
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		doc = _find_pattern(result, PatternType.DOCUMENTATION_DRIVEN)
		assert doc is not None
		assert doc.metadata["handoff_count"] >= 1

	def test_handoff_metrics(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)
		assert result.metrics["handoff_count"] >= 1


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


class TestMetrics:
	def test_human_message_count(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)
		assert result.metrics["human_message_count"] == 7

	def test_all_metric_keys_present(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		expected_keys = {
			"human_message_count",
			"steering_count",
			"deferral_count",
			"grill_count",
			"handoff_count",
			"context_reset_count",
		}
		assert expected_keys.issubset(set(result.metrics.keys()))

	def test_empty_session_produces_zero_metrics(self):
		session = _make_session([])
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)

		assert result.metrics["human_message_count"] == 0
		assert result.metrics["steering_count"] == 0
		assert result.metrics["deferral_count"] == 0
		assert result.metrics["grill_count"] == 0
		assert result.metrics["handoff_count"] == 0
		assert result.metrics["context_reset_count"] == 0

	def test_empty_session_no_patterns(self):
		session = _make_session([])
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)
		assert result.patterns == []


# ---------------------------------------------------------------------------
# Extractor interface
# ---------------------------------------------------------------------------


class TestExtractorInterface:
	def test_name(self):
		extractor = CommSignalExtractor()
		assert extractor.name() == "comm_signals"

	def test_returns_signal_result(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)
		assert isinstance(result, SignalResult)

	def test_session_id_propagated(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)
		assert result.session_id == "steering-test-session"

	def test_project_context_propagated(self):
		session = _steering_session()
		extractor = CommSignalExtractor()
		result = extractor.extract_session(session)
		assert result.project_context == "myproject"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_pattern(result: SignalResult, pattern_type: PatternType):
	"""Find a pattern by type in a SignalResult, or return None."""
	for p in result.patterns:
		if p.pattern_type == pattern_type:
			return p
	return None
