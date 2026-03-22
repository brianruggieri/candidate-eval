"""Validate taxonomy content_patterns don't over-match."""
import json
from pathlib import Path
import pytest

TAXONOMY_PATH = Path("src/claude_candidate/data/taxonomy.json")


class TestTaxonomyPatterns:
	@pytest.fixture
	def taxonomy(self):
		return json.loads(TAXONOMY_PATH.read_text())

	def test_all_entries_have_content_patterns(self, taxonomy):
		"""Every taxonomy entry must have non-empty content_patterns."""
		missing = [name for name, info in taxonomy.items() if not info.get("content_patterns")]
		assert missing == [], f"Entries missing content_patterns: {missing}"

	def test_no_single_character_patterns(self, taxonomy):
		for name, info in taxonomy.items():
			for pattern in info.get("content_patterns", []):
				assert len(pattern) > 1, f"{name} has single-char pattern: {pattern}"

	def test_no_overly_common_patterns(self, taxonomy):
		too_common = {"the", "a", "an", "is", "it", "in", "on", "to", "for", "of", "and", "or"}
		for name, info in taxonomy.items():
			for pattern in info.get("content_patterns", []):
				assert pattern.lower() not in too_common, f"{name} has overly common pattern: {pattern}"

	def test_practices_have_multiple_patterns(self, taxonomy):
		for name, info in taxonomy.items():
			if info.get("category") == "practice":
				patterns = info.get("content_patterns", [])
				assert len(patterns) >= 2, f"Practice '{name}' needs 2+ patterns, has {len(patterns)}"

	def test_patterns_are_not_all_caps(self, taxonomy):
		for name, info in taxonomy.items():
			for pattern in info.get("content_patterns", []):
				assert not pattern.isupper() or len(pattern) <= 4, f"{name} has ALL CAPS pattern: {pattern}"
