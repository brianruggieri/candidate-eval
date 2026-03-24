"""
SkillTaxonomy: Canonical skill name resolution with alias lookup and fuzzy matching.

Three-tier matching strategy:
1. Exact alias lookup (case-insensitive)
2. Fuzzy match via rapidfuzz token_set_ratio >= 90
3. None (unknown skill)

Used by the merger to normalize skill names from resume and session sources
before comparison and scoring.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

# Fuzzy match threshold (token_set_ratio score 0-100)
FUZZY_THRESHOLD = 90

# Path to the bundled taxonomy data file
_DEFAULT_TAXONOMY_PATH = Path(__file__).parent / "data" / "taxonomy.json"


class SkillTaxonomy:
	"""Canonical skill name resolver backed by a taxonomy of aliases and relationships."""

	def __init__(self, skills: dict[str, dict[str, Any]]) -> None:
		"""
		Build reverse alias map and prepare canonical names for fuzzy matching.

		Args:
		    skills: Dict mapping canonical name -> {aliases, category, related, parent}
		"""
		self._skills = skills
		# reverse alias map: lowercased alias -> canonical name
		self._alias_map: dict[str, str] = {}
		for canonical, data in skills.items():
			# canonical name is also an alias of itself
			self._alias_map[canonical.lower()] = canonical
			for alias in data.get("aliases", []):
				self._alias_map[alias.lower()] = canonical

		# Sorted list of all strings to check during fuzzy matching:
		# canonical names + all aliases
		self._all_terms: list[tuple[str, str]] = []  # (term, canonical)
		for canonical, data in skills.items():
			self._all_terms.append((canonical.lower(), canonical))
			for alias in data.get("aliases", []):
				self._all_terms.append((alias.lower(), canonical))

	@classmethod
	def load_default(cls) -> SkillTaxonomy:
		"""Load the bundled taxonomy from data/taxonomy.json."""
		return cls.load(_DEFAULT_TAXONOMY_PATH)

	@classmethod
	def load(cls, path: Path) -> SkillTaxonomy:
		"""Load a taxonomy from an arbitrary JSON file path."""
		with open(path) as f:
			skills: dict[str, dict[str, Any]] = json.load(f)
		return cls(skills)

	def canonicalize(self, name: str) -> str:
		"""
		Tier-1 exact alias lookup.

		Returns the canonical skill name if the input matches any known alias,
		otherwise returns the lowercased input unchanged.
		"""
		lowered = name.lower().strip()
		return self._alias_map.get(lowered, lowered)

	def match(self, name: str) -> str | None:
		"""
		Three-tier skill resolution.

		1. Exact alias lookup
		2. Fuzzy match (rapidfuzz token_set_ratio >= 90) across all terms
		3. None if no match found

		Returns the canonical skill name or None.
		"""
		lowered = name.lower().strip()

		# Tier 1: exact alias match
		if lowered in self._alias_map:
			return self._alias_map[lowered]

		# Tier 2: fuzzy match across all canonical names and aliases
		best_canonical: str | None = None
		best_score: float = 0
		for term, canonical in self._all_terms:
			score = fuzz.token_set_ratio(lowered, term)
			if score > best_score:
				best_score = score
				best_canonical = canonical

		if best_score >= FUZZY_THRESHOLD:
			return best_canonical

		# Tier 3: no match
		return None

	def get_related(self, name: str) -> list[str]:
		"""
		Return related canonical skill names for a canonical skill.

		If name is an alias, resolves it first. Returns empty list if skill
		is unknown.
		"""
		canonical = self.canonicalize(name)
		data = self._skills.get(canonical, {})
		return list(data.get("related", []))

	def get_category(self, name: str) -> str | None:
		"""
		Return the category for a canonical skill.

		If name is an alias, resolves it first. Returns None if unknown.
		"""
		canonical = self.canonicalize(name)
		data = self._skills.get(canonical)
		if data is None:
			return None
		return data.get("category")

	def get_content_patterns(self) -> dict[str, list[str]]:
		"""Return a mapping of canonical skill name to content patterns.

		Only entries with a non-empty content_patterns list are included.
		Used by extract_technologies() to drive keyword detection from the taxonomy
		rather than a hardcoded dict.
		"""
		result: dict[str, list[str]] = {}
		for canonical, data in self._skills.items():
			patterns = data.get("content_patterns", [])
			if patterns:
				result[canonical] = list(patterns)
		return result

	def are_related(self, name_a: str, name_b: str) -> bool:
		"""
		Check if two skills are related.

		Two skills are related if:
		- Either appears in the other's related list
		- One is the parent of the other

		Resolves aliases before comparison. Returns False for unknown skills.
		"""
		canon_a = self.canonicalize(name_a)
		canon_b = self.canonicalize(name_b)

		data_a = self._skills.get(canon_a, {})
		data_b = self._skills.get(canon_b, {})

		# Check related lists (symmetric)
		if canon_b in data_a.get("related", []):
			return True
		if canon_a in data_b.get("related", []):
			return True

		# Check parent/child relationships
		if data_a.get("parent") == canon_b:
			return True
		if data_b.get("parent") == canon_a:
			return True

		return False
