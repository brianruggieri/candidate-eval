"""Tests for the Claude-powered requirement parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
GOLDEN_FIXTURE = FIXTURES_DIR / "claude_responses" / "parse_swe_posting.json"


class TestParseRequirementsFromResponse:
    """Unit tests for parse_requirements_from_response."""

    def test_parses_valid_json_array(self):
        from claude_candidate.requirement_parser import parse_requirements_from_response

        response = json.dumps([
            {
                "description": "Python experience",
                "skill_mapping": ["python"],
                "priority": "must_have",
                "source_text": "Strong Python proficiency required",
            }
        ])
        results = parse_requirements_from_response(response)
        assert len(results) == 1
        assert results[0].description == "Python experience"
        assert results[0].skill_mapping == ["python"]
        assert results[0].priority.value == "must_have"

    def test_handles_json_in_markdown_block(self):
        from claude_candidate.requirement_parser import parse_requirements_from_response

        response = (
            "```json\n"
            + json.dumps([
                {
                    "description": "Docker knowledge",
                    "skill_mapping": ["docker"],
                    "priority": "nice_to_have",
                    "source_text": "Docker is a plus",
                }
            ])
            + "\n```"
        )
        results = parse_requirements_from_response(response)
        assert len(results) == 1
        assert results[0].skill_mapping == ["docker"]

    def test_returns_empty_on_invalid_json(self):
        from claude_candidate.requirement_parser import parse_requirements_from_response

        results = parse_requirements_from_response("this is not json at all")
        assert results == []

    def test_skips_invalid_items_in_array(self):
        from claude_candidate.requirement_parser import parse_requirements_from_response

        # Second item is missing required skill_mapping
        response = json.dumps([
            {
                "description": "Python experience",
                "skill_mapping": ["python"],
                "priority": "must_have",
                "source_text": "",
            },
            {
                "description": "Missing skill mapping",
                "priority": "must_have",
            },
        ])
        results = parse_requirements_from_response(response)
        assert len(results) == 1
        assert results[0].description == "Python experience"


class TestParseFromGoldenFixture:
    """Tests using the golden fixture — skipped when fixture doesn't exist."""

    @pytest.mark.skipif(
        not GOLDEN_FIXTURE.exists(),
        reason="Golden fixture not yet recorded — run scripts/record_claude_fixtures.py",
    )
    def test_golden_swe_posting(self):
        from claude_candidate.requirement_parser import parse_requirements_from_response

        raw = GOLDEN_FIXTURE.read_text()
        results = parse_requirements_from_response(raw)
        assert len(results) > 0
        for req in results:
            assert req.description
            assert req.skill_mapping
            assert req.priority is not None


class TestParseRequirementsFallback:
    """Tests for the keyword-based fallback parser."""

    def test_detects_python(self):
        from claude_candidate.requirement_parser import parse_requirements_fallback

        results = parse_requirements_fallback("We need strong Python skills.")
        skills = [s for r in results for s in r.skill_mapping]
        assert "python" in skills

    def test_detects_multiple_techs(self):
        from claude_candidate.requirement_parser import parse_requirements_fallback

        text = "We use Python, Docker, and PostgreSQL."
        results = parse_requirements_fallback(text)
        all_skills = {s for r in results for s in r.skill_mapping}
        assert "python" in all_skills
        assert "docker" in all_skills
        assert "postgresql" in all_skills

    def test_infers_must_have_priority(self):
        from claude_candidate.requirement_parser import parse_requirements_fallback
        from claude_candidate.schemas.job_requirements import RequirementPriority

        text = "Python is required. Must have 5+ years."
        results = parse_requirements_fallback(text)
        python_reqs = [r for r in results if "python" in r.skill_mapping]
        assert python_reqs
        assert python_reqs[0].priority == RequirementPriority.MUST_HAVE

    def test_infers_nice_to_have_priority(self):
        from claude_candidate.requirement_parser import parse_requirements_fallback
        from claude_candidate.schemas.job_requirements import RequirementPriority

        text = "GraphQL knowledge is a bonus plus."
        results = parse_requirements_fallback(text)
        gql_reqs = [r for r in results if "graphql" in r.skill_mapping]
        assert gql_reqs
        assert gql_reqs[0].priority in (
            RequirementPriority.NICE_TO_HAVE,
            RequirementPriority.STRONG_PREFERENCE,
        )

    def test_returns_generic_fallback_on_no_match(self):
        from claude_candidate.requirement_parser import parse_requirements_fallback
        from claude_candidate.schemas.job_requirements import RequirementPriority

        results = parse_requirements_fallback("This posting mentions nothing technical.")
        assert len(results) >= 1
        assert results[0].priority == RequirementPriority.MUST_HAVE


class TestParseRequirementsWithClaude:
    """Tests for the top-level Claude CLI integration."""

    def test_with_subprocess_fixture(self, fp):
        """Happy path: subprocess returns valid JSON."""
        from claude_candidate.requirement_parser import parse_requirements_with_claude

        fake_response = json.dumps([
            {
                "description": "Python proficiency",
                "skill_mapping": ["python"],
                "priority": "must_have",
                "source_text": "Python required",
            }
        ])
        fp.register_subprocess(
            ["claude", "--print", "-p", fp.any()],
            stdout=fake_response,
            returncode=0,
        )

        results = parse_requirements_with_claude("Need Python developers.")
        assert len(results) == 1
        assert results[0].skill_mapping == ["python"]

    def test_falls_back_on_cli_error(self, fp):
        """When claude CLI fails, keyword fallback is used."""
        from claude_candidate.requirement_parser import parse_requirements_with_claude

        fp.register_subprocess(
            ["claude", "--print", "-p", fp.any()],
            returncode=1,
            stdout="",
            stderr="error: command not found",
        )

        results = parse_requirements_with_claude("We need strong Python and Docker skills.")
        assert len(results) >= 1
        all_skills = {s for r in results for s in r.skill_mapping}
        assert "python" in all_skills or "docker" in all_skills
