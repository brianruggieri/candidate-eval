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

		response = json.dumps(
			[
				{
					"description": "Python experience",
					"skill_mapping": ["python"],
					"priority": "must_have",
					"source_text": "Strong Python proficiency required",
				}
			]
		)
		results = parse_requirements_from_response(response)
		assert len(results) == 1
		assert results[0].description == "Python experience"
		assert results[0].skill_mapping == ["python"]
		assert results[0].priority.value == "must_have"

	def test_handles_json_in_markdown_block(self):
		from claude_candidate.requirement_parser import parse_requirements_from_response

		response = (
			"```json\n"
			+ json.dumps(
				[
					{
						"description": "Docker knowledge",
						"skill_mapping": ["docker"],
						"priority": "nice_to_have",
						"source_text": "Docker is a plus",
					}
				]
			)
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
		response = json.dumps(
			[
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
			]
		)
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


class TestNormalizeSkillMappings:
	"""Tests for normalize_skill_mappings taxonomy normalization."""

	def test_canonicalizes_known_aliases(self):
		"""normalize_skill_mappings should canonicalize known skills through taxonomy."""
		from claude_candidate.requirement_parser import normalize_skill_mappings

		reqs = [
			{"skill_mapping": ["python3", "django", "system design"]},
			{"skill_mapping": ["k8s", "docker-compose"]},
		]
		normalize_skill_mappings(reqs)
		# python3 -> python (via alias), django stays (not in taxonomy as direct entry)
		assert "python" in reqs[0]["skill_mapping"]
		# k8s -> kubernetes, docker-compose -> docker
		assert "kubernetes" in reqs[1]["skill_mapping"]
		assert "docker" in reqs[1]["skill_mapping"]

	def test_preserves_unmatched_skills(self):
		"""Skills not in the taxonomy should be preserved as-is."""
		from claude_candidate.requirement_parser import normalize_skill_mappings

		reqs = [{"skill_mapping": ["some-obscure-tool", "another-unknown"]}]
		normalize_skill_mappings(reqs)
		assert reqs[0]["skill_mapping"] == ["some-obscure-tool", "another-unknown"]

	def test_deduplicates_after_normalization(self):
		"""If two aliases resolve to the same canonical, deduplicate."""
		from claude_candidate.requirement_parser import normalize_skill_mappings

		reqs = [{"skill_mapping": ["python3", "python", "py"]}]
		normalize_skill_mappings(reqs)
		assert reqs[0]["skill_mapping"].count("python") == 1

	def test_handles_empty_skill_mapping(self):
		"""Requirements with empty or missing skill_mapping should not error."""
		from claude_candidate.requirement_parser import normalize_skill_mappings

		reqs = [{"skill_mapping": []}, {"description": "no mapping key"}]
		normalize_skill_mappings(reqs)
		assert reqs[0]["skill_mapping"] == []
		assert reqs[1]["skill_mapping"] == []


class TestParseRequirementsWithClaude:
	"""Tests for the top-level Claude CLI integration."""

	def test_with_subprocess_fixture(self, fp):
		"""Happy path: subprocess returns valid JSON."""
		from claude_candidate.requirement_parser import parse_requirements_with_claude

		fake_response = json.dumps(
			[
				{
					"description": "Python proficiency",
					"skill_mapping": ["python"],
					"priority": "must_have",
					"source_text": "Python required",
				}
			]
		)
		fp.register_subprocess(
			["claude", "--print", "-p", fp.any()],
			stdout=fake_response,
			returncode=0,
		)

		results = parse_requirements_with_claude("Need Python developers.")
		assert len(results) == 1
		assert results[0].skill_mapping == ["python"]

	def test_raises_on_cli_error(self, fp):
		"""When claude CLI fails, ClaudeCLIError propagates (no silent fallback)."""
		from claude_candidate.claude_cli import ClaudeCLIError
		from claude_candidate.requirement_parser import parse_requirements_with_claude

		fp.register_subprocess(
			["claude", "--print", "-p", fp.any()],
			returncode=1,
			stdout="",
			stderr="error: command not found",
		)

		with pytest.raises(ClaudeCLIError):
			parse_requirements_with_claude("We need strong Python and Docker skills.")

	def test_falls_back_to_keywords_on_bad_json(self, fp):
		"""When Claude returns malformed JSON, keyword parser is used as fallback."""
		from claude_candidate.requirement_parser import parse_requirements_with_claude

		fp.register_subprocess(
			["claude", "--print", "-p", fp.any()],
			returncode=0,
			stdout="this is not valid json at all",
		)

		results = parse_requirements_with_claude("We need strong Python and Docker skills.")
		assert len(results) >= 1
		all_skills = {s for r in results for s in r.skill_mapping}
		assert "python" in all_skills or "docker" in all_skills


class TestBuildExtractionPrompt:
	def test_returns_string_with_required_fields(self):
		from claude_candidate.requirement_parser import build_extraction_prompt

		prompt = build_extraction_prompt(title="Software Engineer", text="We need Python...")
		assert "company" in prompt
		assert "title" in prompt
		assert "requirements" in prompt
		assert "skill_mapping" in prompt
		assert "is_eligibility" in prompt
		assert "Software Engineer" in prompt
		assert "We need Python" in prompt

	def test_truncates_long_text(self):
		from claude_candidate.requirement_parser import build_extraction_prompt

		long_text = "x" * 20000
		prompt = build_extraction_prompt(title="Test", text=long_text)
		# MAX_EXTRACTION_TEXT = 15000
		assert len(long_text) > 15000
		assert "x" * 15000 in prompt
		assert "x" * 15001 not in prompt
