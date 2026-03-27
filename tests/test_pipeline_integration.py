"""Integration tests for the unified parsing pipeline."""

import pytest
from claude_candidate.requirement_parser import (
	build_extraction_prompt,
	CACHE_PROMPT_VERSION,
)


class TestCachePromptVersion:
	"""Verify the cache version key exists and is a non-empty string."""

	def test_cache_version_is_string(self):
		assert isinstance(CACHE_PROMPT_VERSION, str)
		assert len(CACHE_PROMPT_VERSION) > 0

	def test_prompt_includes_all_requirement_fields(self):
		"""Both CLI and server prompts must extract the same requirement fields."""
		prompt = build_extraction_prompt("Test", "Some job posting text")
		# Fields that must appear in the extraction prompt
		for field in [
			"description",
			"skill_mapping",
			"priority",
			"years_experience",
			"education_level",
			"is_eligibility",
			"source_text",
		]:
			assert field in prompt, f"Missing field '{field}' in extraction prompt"
