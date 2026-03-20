"""Tests for the company research module."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from claude_candidate.company_research import research_company, _strip_code_fences


# ---------------------------------------------------------------------------
# _strip_code_fences
# ---------------------------------------------------------------------------

class TestStripCodeFences:
    def test_plain_json_unchanged(self):
        raw = '{"mission": "Build things"}'
        assert _strip_code_fences(raw) == raw

    def test_strips_json_code_fence(self):
        raw = '```json\n{"mission": "Build things"}\n```'
        assert _strip_code_fences(raw) == '{"mission": "Build things"}'

    def test_strips_bare_code_fence(self):
        raw = '```\n{"mission": "Build things"}\n```'
        assert _strip_code_fences(raw) == '{"mission": "Build things"}'

    def test_strips_with_surrounding_whitespace(self):
        raw = '  \n```json\n{"key": "value"}\n```\n  '
        assert _strip_code_fences(raw) == '{"key": "value"}'


# ---------------------------------------------------------------------------
# research_company
# ---------------------------------------------------------------------------

SAMPLE_RESEARCH_RESPONSE = {
    "mission": "Accelerate the transition to sustainable energy",
    "values": ["innovation", "sustainability", "speed"],
    "culture_signals": ["move fast", "first principles thinking"],
    "tech_philosophy": "Vertical integration, build everything in-house",
    "ai_native": False,
    "product_domains": ["electric vehicles", "energy storage", "solar"],
    "team_size_signal": "enterprise (500+)",
}


class TestResearchCompany:
    @patch("claude_candidate.company_research._claude_cli.call_claude")
    def test_parses_plain_json(self, mock_call):
        mock_call.return_value = json.dumps(SAMPLE_RESEARCH_RESPONSE)
        result = research_company("Tesla")
        assert result["mission"] == "Accelerate the transition to sustainable energy"
        assert result["ai_native"] is False
        assert "innovation" in result["values"]
        assert len(result["product_domains"]) == 3
        mock_call.assert_called_once()

    @patch("claude_candidate.company_research._claude_cli.call_claude")
    def test_parses_json_with_code_fences(self, mock_call):
        fenced = "```json\n" + json.dumps(SAMPLE_RESEARCH_RESPONSE) + "\n```"
        mock_call.return_value = fenced
        result = research_company("Tesla")
        assert result["mission"] == "Accelerate the transition to sustainable energy"
        assert result["team_size_signal"] == "enterprise (500+)"

    @patch("claude_candidate.company_research._claude_cli.call_claude")
    def test_raises_on_invalid_json(self, mock_call):
        mock_call.return_value = "This is not JSON at all"
        with pytest.raises(ValueError, match="Failed to parse"):
            research_company("BadCo")

    @patch("claude_candidate.company_research._claude_cli.call_claude")
    def test_passes_timeout(self, mock_call):
        mock_call.return_value = json.dumps(SAMPLE_RESEARCH_RESPONSE)
        research_company("TestCo", timeout=120)
        _, kwargs = mock_call.call_args
        assert kwargs["timeout"] == 120

    @patch("claude_candidate.company_research._claude_cli.call_claude")
    def test_prompt_contains_company_name(self, mock_call):
        mock_call.return_value = json.dumps(SAMPLE_RESEARCH_RESPONSE)
        research_company("Anthropic")
        args, _ = mock_call.call_args
        assert "Anthropic" in args[0]
