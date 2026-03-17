"""Tests for the signal extractor module."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_candidate.extractor import (
    SessionSignals,
    build_candidate_profile,
    extract_session_signals,
    extract_technologies,
    parse_session_lines,
    _classify_category,
    _detect_from_content,
    _detect_from_file_path,
    _extract_evidence_snippets,
    _extract_tool_calls,
    _infer_depth,
    _is_valid_json_line,
    _truncate_snippet,
)
from claude_candidate.schemas.candidate_profile import (
    CandidateProfile,
    DepthLevel,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sessions"


# ---------------------------------------------------------------------------
# parse_session_lines
# ---------------------------------------------------------------------------


class TestParseSessionLines:
    def test_parses_valid_jsonl(self) -> None:
        lines = [
            '{"type": "user", "message": "hello"}',
            '{"type": "assistant", "message": "hi"}',
        ]
        result = parse_session_lines(lines)
        assert len(result) == 2
        assert result[0]["type"] == "user"
        assert result[1]["type"] == "assistant"

    def test_skips_malformed_lines(self) -> None:
        lines = [
            '{"type": "user"}',
            "{invalid json here",
            '{"type": "assistant"}',
        ]
        result = parse_session_lines(lines)
        assert len(result) == 2

    def test_skips_empty_lines(self) -> None:
        lines = [
            '{"type": "user"}',
            "",
            "   ",
            '{"type": "assistant"}',
        ]
        result = parse_session_lines(lines)
        assert len(result) == 2

    def test_returns_empty_for_no_input(self) -> None:
        assert parse_session_lines([]) == []


# ---------------------------------------------------------------------------
# _is_valid_json_line
# ---------------------------------------------------------------------------


class TestIsValidJsonLine:
    def test_valid_json(self) -> None:
        assert _is_valid_json_line('{"key": "value"}') is True

    def test_invalid_json(self) -> None:
        assert _is_valid_json_line("{bad json") is False

    def test_empty_string(self) -> None:
        assert _is_valid_json_line("") is False

    def test_whitespace_only(self) -> None:
        assert _is_valid_json_line("   ") is False


# ---------------------------------------------------------------------------
# _detect_from_file_path
# ---------------------------------------------------------------------------


class TestDetectFromFilePath:
    def test_python_file(self) -> None:
        assert "python" in _detect_from_file_path("/project/app/main.py")

    def test_tsx_file(self) -> None:
        techs = _detect_from_file_path("/project/src/App.tsx")
        assert "typescript" in techs
        assert "react" in techs

    def test_jsx_file(self) -> None:
        techs = _detect_from_file_path("/project/src/App.jsx")
        assert "javascript" in techs
        assert "react" in techs

    def test_dockerfile(self) -> None:
        assert "docker" in _detect_from_file_path("/project/Dockerfile")

    def test_unknown_extension(self) -> None:
        assert _detect_from_file_path("/project/data.xyz") == []

    def test_sql_file(self) -> None:
        assert "postgresql" in _detect_from_file_path("/project/db/schema.sql")

    def test_rust_file(self) -> None:
        assert "rust" in _detect_from_file_path("/project/src/main.rs")


# ---------------------------------------------------------------------------
# _detect_from_content
# ---------------------------------------------------------------------------


class TestDetectFromContent:
    def test_detects_fastapi(self) -> None:
        content = "from fastapi import FastAPI"
        assert "fastapi" in _detect_from_content(content)

    def test_detects_pydantic(self) -> None:
        content = "from pydantic import BaseModel"
        assert "pydantic" in _detect_from_content(content)

    def test_detects_pytest(self) -> None:
        content = "def test_something():\n    pass"
        assert "pytest" in _detect_from_content(content)

    def test_detects_react_hooks(self) -> None:
        content = "import { useState, useEffect } from 'react'"
        techs = _detect_from_content(content)
        assert "react" in techs

    def test_detects_docker(self) -> None:
        content = "docker-compose up --build"
        assert "docker" in _detect_from_content(content)

    def test_detects_sqlalchemy(self) -> None:
        content = "from sqlalchemy import Column"
        assert "sqlalchemy" in _detect_from_content(content)

    def test_detects_git(self) -> None:
        content = "git commit -m 'initial'"
        assert "git" in _detect_from_content(content)

    def test_no_match_returns_empty(self) -> None:
        assert _detect_from_content("hello world") == []


# ---------------------------------------------------------------------------
# extract_technologies
# ---------------------------------------------------------------------------


class TestExtractTechnologies:
    def test_detects_python_from_tool_use(self) -> None:
        messages = [
            {
                "type": "tool_use",
                "toolUse": {
                    "name": "Write",
                    "input": {"file_path": "/app/main.py", "content": "print('hello')"},
                },
            },
        ]
        techs = extract_technologies(messages)
        assert "python" in techs

    def test_detects_typescript_from_file_extension(self) -> None:
        messages = [
            {
                "type": "tool_use",
                "toolUse": {
                    "name": "Write",
                    "input": {"file_path": "/app/index.ts", "content": "const x = 1"},
                },
            },
        ]
        techs = extract_technologies(messages)
        assert "typescript" in techs

    def test_no_duplicates(self) -> None:
        messages = [
            {
                "type": "tool_use",
                "toolUse": {
                    "name": "Write",
                    "input": {"file_path": "/a.py", "content": "import fastapi"},
                },
            },
            {
                "type": "tool_use",
                "toolUse": {
                    "name": "Write",
                    "input": {"file_path": "/b.py", "content": "from fastapi import FastAPI"},
                },
            },
        ]
        techs = extract_technologies(messages)
        assert techs.count("python") == 1
        assert techs.count("fastapi") == 1

    def test_detects_from_content_patterns(self) -> None:
        messages = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "We'll use pydantic BaseModel for validation."},
                    ],
                },
            },
        ]
        techs = extract_technologies(messages)
        assert "pydantic" in techs

    def test_detects_from_user_messages(self) -> None:
        messages = [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Can you set up docker-compose for this?"},
                    ],
                },
            },
        ]
        techs = extract_technologies(messages)
        assert "docker" in techs

    def test_empty_messages_returns_empty(self) -> None:
        assert extract_technologies([]) == []


# ---------------------------------------------------------------------------
# _extract_tool_calls
# ---------------------------------------------------------------------------


class TestExtractToolCalls:
    def test_extracts_tool_names(self) -> None:
        messages = [
            {"type": "tool_use", "toolUse": {"name": "Write", "input": {}}},
            {"type": "tool_use", "toolUse": {"name": "Read", "input": {}}},
            {"type": "tool_use", "toolUse": {"name": "Bash", "input": {}}},
        ]
        tools = _extract_tool_calls(messages)
        assert "Write" in tools
        assert "Read" in tools
        assert "Bash" in tools

    def test_skips_non_tool_messages(self) -> None:
        messages = [
            {"type": "user", "message": {"role": "user"}},
            {"type": "tool_use", "toolUse": {"name": "Write", "input": {}}},
        ]
        tools = _extract_tool_calls(messages)
        assert tools == ["Write"]

    def test_empty_messages(self) -> None:
        assert _extract_tool_calls([]) == []


# ---------------------------------------------------------------------------
# _extract_evidence_snippets
# ---------------------------------------------------------------------------


class TestExtractEvidenceSnippets:
    def test_extracts_from_assistant_messages(self) -> None:
        messages = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [
                        {"type": "text", "text": "I'll create a FastAPI auth endpoint."},
                    ],
                },
            },
        ]
        snippets = _extract_evidence_snippets(messages)
        assert len(snippets) >= 1
        assert any("FastAPI" in s for s in snippets)

    def test_skips_user_messages(self) -> None:
        messages = [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"type": "text", "text": "help me"}],
                },
            },
        ]
        snippets = _extract_evidence_snippets(messages)
        assert len(snippets) == 0

    def test_truncates_long_snippets(self) -> None:
        long_text = "A" * 600
        messages = [
            {
                "type": "assistant",
                "message": {
                    "role": "assistant",
                    "content": [{"type": "text", "text": long_text}],
                },
            },
        ]
        snippets = _extract_evidence_snippets(messages)
        assert all(len(s) <= 500 for s in snippets)

    def test_empty_messages(self) -> None:
        assert _extract_evidence_snippets([]) == []


# ---------------------------------------------------------------------------
# _truncate_snippet
# ---------------------------------------------------------------------------


class TestTruncateSnippet:
    def test_short_text_unchanged(self) -> None:
        assert _truncate_snippet("hello") == "hello"

    def test_long_text_truncated(self) -> None:
        text = "A" * 600
        result = _truncate_snippet(text)
        assert len(result) <= 500

    def test_truncation_adds_ellipsis(self) -> None:
        text = "B" * 600
        result = _truncate_snippet(text)
        assert result.endswith("...")

    def test_exactly_500_unchanged(self) -> None:
        text = "C" * 500
        assert _truncate_snippet(text) == text


# ---------------------------------------------------------------------------
# _classify_category
# ---------------------------------------------------------------------------


class TestClassifyCategory:
    def test_language(self) -> None:
        assert _classify_category("python") == "language"
        assert _classify_category("typescript") == "language"

    def test_framework(self) -> None:
        assert _classify_category("fastapi") == "framework"
        assert _classify_category("react") == "framework"

    def test_tool(self) -> None:
        assert _classify_category("docker") == "tool"
        assert _classify_category("git") == "tool"

    def test_platform(self) -> None:
        assert _classify_category("postgresql") == "platform"

    def test_unknown_defaults_to_tool(self) -> None:
        assert _classify_category("unknowntech") == "tool"


# ---------------------------------------------------------------------------
# _infer_depth
# ---------------------------------------------------------------------------


class TestInferDepth:
    def test_low_frequency_mentioned(self) -> None:
        assert _infer_depth(1, tool_count=0) == DepthLevel.MENTIONED

    def test_moderate_frequency_used(self) -> None:
        assert _infer_depth(2, tool_count=1) == DepthLevel.USED

    def test_higher_frequency_applied(self) -> None:
        assert _infer_depth(4, tool_count=3) == DepthLevel.APPLIED

    def test_high_frequency_deep(self) -> None:
        assert _infer_depth(6, tool_count=3) == DepthLevel.DEEP

    def test_very_high_frequency_expert(self) -> None:
        assert _infer_depth(8, tool_count=3) == DepthLevel.EXPERT


# ---------------------------------------------------------------------------
# extract_session_signals
# ---------------------------------------------------------------------------


class TestExtractSessionSignals:
    def test_from_fixture_file(self) -> None:
        """Test against the simple_python_session.jsonl fixture."""
        fixture = FIXTURES_DIR / "simple_python_session.jsonl"
        content = fixture.read_text()
        signals = extract_session_signals(content)
        assert len(signals.technologies) > 0
        assert signals.line_count > 0
        assert signals.session_id != ""

    def test_detects_python_technologies(self) -> None:
        fixture = FIXTURES_DIR / "simple_python_session.jsonl"
        content = fixture.read_text()
        signals = extract_session_signals(content)
        assert "python" in signals.technologies
        assert "fastapi" in signals.technologies

    def test_detects_tool_calls(self) -> None:
        fixture = FIXTURES_DIR / "simple_python_session.jsonl"
        content = fixture.read_text()
        signals = extract_session_signals(content)
        assert "Write" in signals.tool_calls

    def test_multi_tech_session(self) -> None:
        fixture = FIXTURES_DIR / "multi_tech_session.jsonl"
        content = fixture.read_text()
        signals = extract_session_signals(content)
        assert "python" in signals.technologies
        assert "typescript" in signals.technologies
        assert "react" in signals.technologies
        assert "docker" in signals.technologies

    def test_empty_content(self) -> None:
        signals = extract_session_signals("")
        assert signals.technologies == []
        assert signals.line_count == 0
        assert signals.session_id == "unknown"

    def test_malformed_session(self) -> None:
        """Test against malformed_session.jsonl fixture -- should handle gracefully."""
        fixture = FIXTURES_DIR / "malformed_session.jsonl"
        content = fixture.read_text()
        signals = extract_session_signals(content)
        # Should not crash, should recover what it can
        assert isinstance(signals, SessionSignals)
        assert signals.line_count > 0

    def test_has_evidence_snippets(self) -> None:
        fixture = FIXTURES_DIR / "simple_python_session.jsonl"
        content = fixture.read_text()
        signals = extract_session_signals(content)
        assert len(signals.evidence_snippets) > 0

    def test_has_timestamp(self) -> None:
        fixture = FIXTURES_DIR / "simple_python_session.jsonl"
        content = fixture.read_text()
        signals = extract_session_signals(content)
        assert signals.timestamp != ""

    def test_has_project_hint(self) -> None:
        fixture = FIXTURES_DIR / "simple_python_session.jsonl"
        content = fixture.read_text()
        signals = extract_session_signals(content)
        assert signals.project_hint != ""


# ---------------------------------------------------------------------------
# build_candidate_profile
# ---------------------------------------------------------------------------


class TestBuildCandidateProfile:
    @pytest.fixture
    def sample_signals(self) -> list[SessionSignals]:
        return [
            SessionSignals(
                session_id="session-001",
                project_hint="my-project",
                technologies=["python", "fastapi", "pydantic"],
                tool_calls=["Write", "Read", "Bash"],
                patterns_observed=["iterative_refinement"],
                evidence_snippets=["Built a FastAPI auth endpoint with pydantic."],
                line_count=50,
                timestamp="2026-03-10T09:00:00.000Z",
            ),
            SessionSignals(
                session_id="session-002",
                project_hint="my-project",
                technologies=["python", "typescript", "react", "docker"],
                tool_calls=["Write", "Write", "Write", "Write", "Write"],
                patterns_observed=["modular_thinking"],
                evidence_snippets=[
                    "Scaffolded a full-stack app with React frontend and FastAPI backend."
                ],
                line_count=100,
                timestamp="2026-03-12T10:00:00.000Z",
            ),
        ]

    def test_builds_from_signals_list(self, sample_signals: list[SessionSignals]) -> None:
        profile = build_candidate_profile(
            signals_list=sample_signals,
            manifest_hash="abc123",
        )
        assert isinstance(profile, CandidateProfile)
        assert profile.session_count == 2
        assert profile.manifest_hash == "abc123"

    def test_merges_technologies_across_sessions(
        self, sample_signals: list[SessionSignals]
    ) -> None:
        profile = build_candidate_profile(
            signals_list=sample_signals,
            manifest_hash="abc123",
        )
        skill_names = [s.name for s in profile.skills]
        assert "python" in skill_names
        assert "fastapi" in skill_names
        assert "typescript" in skill_names

    def test_evidence_snippets_max_length(
        self, sample_signals: list[SessionSignals]
    ) -> None:
        profile = build_candidate_profile(
            signals_list=sample_signals,
            manifest_hash="abc123",
        )
        for skill in profile.skills:
            for ev in skill.evidence:
                assert len(ev.evidence_snippet) <= 500

    def test_all_required_fields_populated(
        self, sample_signals: list[SessionSignals]
    ) -> None:
        profile = build_candidate_profile(
            signals_list=sample_signals,
            manifest_hash="abc123",
        )
        assert profile.profile_version == "0.1.0"
        assert profile.generated_at is not None
        assert profile.session_count >= 0
        assert profile.date_range_start is not None
        assert profile.date_range_end is not None
        assert len(profile.skills) > 0
        assert len(profile.primary_languages) > 0
        assert profile.primary_domains is not None
        assert len(profile.problem_solving_patterns) > 0
        assert profile.working_style_summary != ""
        assert len(profile.projects) > 0
        assert profile.communication_style != ""
        assert profile.documentation_tendency in (
            "minimal",
            "moderate",
            "thorough",
            "extensive",
        )
        assert profile.extraction_notes != ""
        assert profile.confidence_assessment in (
            "low",
            "moderate",
            "high",
            "very_high",
        )

    def test_skill_entry_has_evidence(self, sample_signals: list[SessionSignals]) -> None:
        profile = build_candidate_profile(
            signals_list=sample_signals,
            manifest_hash="abc123",
        )
        for skill in profile.skills:
            assert len(skill.evidence) >= 1
            for ev in skill.evidence:
                assert ev.evidence_snippet.strip() != ""
                assert ev.session_id != ""

    def test_date_range_correct(self, sample_signals: list[SessionSignals]) -> None:
        profile = build_candidate_profile(
            signals_list=sample_signals,
            manifest_hash="abc123",
        )
        assert profile.date_range_start <= profile.date_range_end

    def test_primary_languages_max_five(
        self, sample_signals: list[SessionSignals]
    ) -> None:
        profile = build_candidate_profile(
            signals_list=sample_signals,
            manifest_hash="abc123",
        )
        assert len(profile.primary_languages) <= 5

    def test_projects_populated(self, sample_signals: list[SessionSignals]) -> None:
        profile = build_candidate_profile(
            signals_list=sample_signals,
            manifest_hash="abc123",
        )
        assert len(profile.projects) >= 1
        for proj in profile.projects:
            assert proj.project_name != ""
            assert proj.session_count >= 1
            assert len(proj.evidence) >= 1

    def test_python_frequency_is_two(self, sample_signals: list[SessionSignals]) -> None:
        """Python appears in both sessions, so frequency should be 2."""
        profile = build_candidate_profile(
            signals_list=sample_signals,
            manifest_hash="abc123",
        )
        python_skill = profile.get_skill("python")
        assert python_skill is not None
        assert python_skill.frequency == 2

    def test_empty_signals_list(self) -> None:
        profile = build_candidate_profile(
            signals_list=[],
            manifest_hash="empty-hash",
        )
        assert profile.session_count == 0
        assert len(profile.skills) == 0
        assert len(profile.projects) == 0

    def test_profile_serializes_round_trip(
        self, sample_signals: list[SessionSignals]
    ) -> None:
        profile = build_candidate_profile(
            signals_list=sample_signals,
            manifest_hash="abc123",
        )
        json_str = profile.to_json()
        restored = CandidateProfile.from_json(json_str)
        assert restored.session_count == profile.session_count
        assert len(restored.skills) == len(profile.skills)


# ---------------------------------------------------------------------------
# Integration: fixture file -> profile
# ---------------------------------------------------------------------------


class TestEndToEnd:
    def test_fixture_to_profile(self) -> None:
        """Extract signals from fixture files and build a complete profile."""
        signals_list = []
        for fixture in FIXTURES_DIR.glob("*.jsonl"):
            content = fixture.read_text()
            signals = extract_session_signals(content)
            if signals.technologies:
                signals_list.append(signals)

        assert len(signals_list) >= 1

        profile = build_candidate_profile(
            signals_list=signals_list,
            manifest_hash="integration-test",
        )
        assert isinstance(profile, CandidateProfile)
        assert profile.session_count == len(signals_list)
        assert len(profile.skills) > 0

    def test_profile_evidence_chain_intact(self) -> None:
        """Every skill must trace back to a session with valid evidence."""
        fixture = FIXTURES_DIR / "simple_python_session.jsonl"
        signals = extract_session_signals(fixture.read_text())
        profile = build_candidate_profile(
            signals_list=[signals],
            manifest_hash="chain-test",
        )
        for skill in profile.skills:
            for ev in skill.evidence:
                assert ev.evidence_snippet.strip() != ""
                assert len(ev.evidence_snippet) <= 500
                assert ev.session_id != ""
                assert ev.confidence >= 0.0
                assert ev.confidence <= 1.0
