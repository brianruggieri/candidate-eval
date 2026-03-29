"""Tests for WorkPreferences schema, culture scoring, and CLI integration."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_candidate.schemas.work_preferences import WorkPreferences


class TestWorkPreferencesSchema:
	"""Tests for the WorkPreferences pydantic model."""

	def test_defaults(self):
		prefs = WorkPreferences()
		assert prefs.remote_preference == "flexible"
		assert prefs.company_size == []
		assert prefs.culture_values == []
		assert prefs.culture_avoid == []

	def test_has_preferences_false_on_defaults(self):
		prefs = WorkPreferences()
		assert prefs.has_preferences is False

	def test_has_preferences_true_remote(self):
		prefs = WorkPreferences(remote_preference="remote_first")
		assert prefs.has_preferences is True

	def test_has_preferences_true_size(self):
		prefs = WorkPreferences(company_size=["startup"])
		assert prefs.has_preferences is True

	def test_has_preferences_true_values(self):
		prefs = WorkPreferences(culture_values=["collaboration"])
		assert prefs.has_preferences is True

	def test_has_preferences_true_avoid(self):
		prefs = WorkPreferences(culture_avoid=["micromanagement"])
		assert prefs.has_preferences is True

	def test_roundtrip_json(self, tmp_path):
		prefs = WorkPreferences(
			remote_preference="hybrid",
			company_size=["startup", "mid"],
			culture_values=["autonomy", "transparency"],
			culture_avoid=["crunch culture"],
		)
		path = tmp_path / "prefs.json"
		prefs.save(path)
		loaded = WorkPreferences.load(path)
		assert loaded is not None
		assert loaded.remote_preference == "hybrid"
		assert loaded.company_size == ["startup", "mid"]
		assert loaded.culture_values == ["autonomy", "transparency"]
		assert loaded.culture_avoid == ["crunch culture"]

	def test_load_missing_file(self, tmp_path):
		path = tmp_path / "nonexistent.json"
		assert WorkPreferences.load(path) is None

	def test_save_creates_parent_dirs(self, tmp_path):
		prefs = WorkPreferences(remote_preference="in_office")
		path = tmp_path / "sub" / "dir" / "prefs.json"
		prefs.save(path)
		assert path.exists()
		loaded = WorkPreferences.load(path)
		assert loaded is not None
		assert loaded.remote_preference == "in_office"

	def test_model_validate_from_dict(self):
		data = {
			"remote_preference": "remote_first",
			"company_size": ["enterprise"],
			"culture_values": ["innovation"],
			"culture_avoid": [],
		}
		prefs = WorkPreferences.model_validate(data)
		assert prefs.remote_preference == "remote_first"
		assert prefs.company_size == ["enterprise"]


class TestCultureConstants:
	"""Verify culture preference constants are correctly defined."""

	def test_remote_weight_values(self):
		from claude_candidate.scoring.constants import (
			CULTURE_REMOTE_WEIGHT,
			CULTURE_SIZE_WEIGHT,
			CULTURE_VALUES_WEIGHT,
		)

		assert CULTURE_REMOTE_WEIGHT == 0.3
		assert CULTURE_SIZE_WEIGHT == 0.2
		assert CULTURE_VALUES_WEIGHT == 0.5
		assert abs(CULTURE_REMOTE_WEIGHT + CULTURE_SIZE_WEIGHT + CULTURE_VALUES_WEIGHT - 1.0) < 1e-9

	def test_remote_match_matrix_covers_all_combinations(self):
		from claude_candidate.scoring.constants import REMOTE_MATCH_MATRIX

		candidates = ["remote_first", "hybrid", "in_office", "flexible"]
		companies = ["remote_first", "hybrid", "in_office"]
		for cand in candidates:
			for comp in companies:
				assert (cand, comp) in REMOTE_MATCH_MATRIX, f"Missing ({cand}, {comp})"

	def test_remote_matrix_perfect_matches_score_one(self):
		from claude_candidate.scoring.constants import REMOTE_MATCH_MATRIX

		assert REMOTE_MATCH_MATRIX[("remote_first", "remote_first")] == 1.0
		assert REMOTE_MATCH_MATRIX[("hybrid", "hybrid")] == 1.0
		assert REMOTE_MATCH_MATRIX[("in_office", "in_office")] == 1.0

	def test_flexible_always_scores_one(self):
		from claude_candidate.scoring.constants import REMOTE_MATCH_MATRIX

		for policy in ("remote_first", "hybrid", "in_office"):
			assert REMOTE_MATCH_MATRIX[("flexible", policy)] == 1.0

	def test_unknown_score(self):
		from claude_candidate.scoring.constants import CULTURE_UNKNOWN_SCORE

		assert CULTURE_UNKNOWN_SCORE == 0.7

	def test_size_match_scores(self):
		from claude_candidate.scoring.constants import CULTURE_SIZE_MATCH, CULTURE_SIZE_NO_MATCH

		assert CULTURE_SIZE_MATCH == 1.0
		assert CULTURE_SIZE_NO_MATCH == 0.3

	def test_avoid_caps(self):
		from claude_candidate.scoring.constants import (
			CULTURE_AVOID_CAP_ONE,
			CULTURE_AVOID_CAP_TWO_PLUS,
		)

		assert CULTURE_AVOID_CAP_ONE == 0.799
		assert CULTURE_AVOID_CAP_TWO_PLUS == 0.699

	def test_constants_importable_from_scoring_package(self):
		from claude_candidate.scoring import (
			CULTURE_REMOTE_WEIGHT,
			CULTURE_SIZE_WEIGHT,
			CULTURE_VALUES_WEIGHT,
			REMOTE_MATCH_MATRIX,
			CULTURE_UNKNOWN_SCORE,
			CULTURE_SIZE_MATCH,
			CULTURE_SIZE_NO_MATCH,
			CULTURE_AVOID_CAP_ONE,
			CULTURE_AVOID_CAP_TWO_PLUS,
		)

		# Just verify they're importable (values tested above)
		assert CULTURE_REMOTE_WEIGHT is not None
