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
