"""Tests for the shared prepare_assess_inputs() helper."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.work_preferences import WorkPreferences
from claude_candidate.scoring import prepare_assess_inputs


class TestPrepareAssessInputs:
	def test_loads_work_preferences_from_file(self, tmp_path, monkeypatch):
		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
		)
		cc_dir = tmp_path / ".claude-candidate"
		cc_dir.mkdir()
		prefs.save(cc_dir / "work_preferences.json")
		monkeypatch.setenv("HOME", str(tmp_path))

		result = prepare_assess_inputs("TestCo")
		assert result["work_preferences"] is not None
		assert result["work_preferences"].remote_preference == "remote_first"

	def test_returns_none_preferences_when_file_missing(self, tmp_path, monkeypatch):
		monkeypatch.setenv("HOME", str(tmp_path))
		result = prepare_assess_inputs("TestCo")
		assert result["work_preferences"] is None

	def test_builds_company_profile_from_culture_signals(self, tmp_path, monkeypatch):
		monkeypatch.setenv("HOME", str(tmp_path))
		result = prepare_assess_inputs(
			"TestCo",
			culture_signals=["collaborative", "fast-paced"],
			tech_stack=["python", "react"],
		)
		cp = result["company_profile"]
		assert cp is not None
		assert cp.company_name == "TestCo"
		assert "collaborative" in cp.culture_keywords
		assert "python" in cp.tech_stack_public

	def test_no_company_profile_when_no_signals(self, tmp_path, monkeypatch):
		monkeypatch.setenv("HOME", str(tmp_path))
		result = prepare_assess_inputs("TestCo")
		assert result["company_profile"] is None

	def test_passes_through_existing_company_profile(self, tmp_path, monkeypatch):
		monkeypatch.setenv("HOME", str(tmp_path))
		existing = CompanyProfile(
			company_name="TestCo",
			mission_statement="We build things",
			product_description="TestCo company",
			product_domain=[],
			culture_keywords=["innovation"],
			enriched_at=datetime.now(),
		)
		result = prepare_assess_inputs("TestCo", company_profile=existing)
		assert result["company_profile"] is existing
		assert result["company_profile"].mission_statement == "We build things"

	def test_existing_company_profile_takes_precedence_over_signals(self, tmp_path, monkeypatch):
		monkeypatch.setenv("HOME", str(tmp_path))
		existing = CompanyProfile(
			company_name="TestCo",
			product_description="TestCo company",
			product_domain=[],
			culture_keywords=["existing"],
			enriched_at=datetime.now(),
		)
		result = prepare_assess_inputs(
			"TestCo",
			culture_signals=["ignored"],
			company_profile=existing,
		)
		assert result["company_profile"].culture_keywords == ["existing"]
