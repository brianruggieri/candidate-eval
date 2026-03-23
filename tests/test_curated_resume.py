"""Tests for the CuratedResume pydantic model."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from claude_candidate.schemas.candidate_profile import DepthLevel
from claude_candidate.schemas.curated_resume import CuratedResume, CuratedSkill


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture() -> dict:
	return json.loads((FIXTURES_DIR / "curated_resume_sample.json").read_text())


class TestCuratedSkill:
	def test_valid_skill(self):
		skill = CuratedSkill(name="Python", depth="deep", duration="4 years")
		assert skill.name == "python"  # normalized
		assert skill.depth == DepthLevel.DEEP
		assert skill.duration == "4 years"
		assert skill.curated is True

	def test_depth_validation_rejects_typo(self):
		with pytest.raises(ValidationError, match="depth"):
			CuratedSkill(name="python", depth="deeo")

	def test_name_normalization(self):
		skill = CuratedSkill(name="  TypeScript  ", depth="expert")
		assert skill.name == "typescript"

	def test_optional_duration(self):
		skill = CuratedSkill(name="docker", depth="used")
		assert skill.duration is None

	def test_default_source_context(self):
		skill = CuratedSkill(name="git", depth="expert")
		assert skill.source_context == "Listed in skills section"


class TestCuratedResume:
	def test_valid_fixture_loads(self):
		data = _load_fixture()
		curated = CuratedResume.model_validate(data)
		assert len(curated.curated_skills) == 3
		assert curated.name == "Test Candidate"
		assert curated.source_format == "pdf"

	def test_existing_curated_resume_loads(self):
		"""The real curated_resume.json at ~/.claude-candidate/ validates."""
		real_path = Path.home() / ".claude-candidate" / "curated_resume.json"
		if not real_path.exists():
			pytest.skip("No real curated_resume.json found")
		curated = CuratedResume.from_file(real_path)
		assert len(curated.curated_skills) > 0
		assert curated.curated is True

	def test_missing_curated_skills_key_fails(self):
		data = _load_fixture()
		del data["curated_skills"]
		with pytest.raises(ValidationError, match="curated_skills"):
			CuratedResume.model_validate(data)

	def test_misspelled_curated_skills_key_fails(self):
		"""The exact bug this schema prevents: 'curated_skill' instead of 'curated_skills'."""
		data = _load_fixture()
		data["curated_skill"] = data.pop("curated_skills")
		with pytest.raises(ValidationError, match="curated_skills"):
			CuratedResume.model_validate(data)

	def test_empty_curated_skills_fails(self):
		data = _load_fixture()
		data["curated_skills"] = []
		with pytest.raises(ValidationError):
			CuratedResume.model_validate(data)

	def test_roundtrip(self):
		data = _load_fixture()
		curated = CuratedResume.model_validate(data)
		roundtripped = CuratedResume.from_json(curated.to_json())
		assert roundtripped.name == curated.name
		assert len(roundtripped.curated_skills) == len(curated.curated_skills)
		assert roundtripped.source_file_hash == curated.source_file_hash

	def test_get_curated_skill(self):
		data = _load_fixture()
		curated = CuratedResume.model_validate(data)
		# Case-insensitive lookup
		skill = curated.get_curated_skill("Python")
		assert skill is not None
		assert skill.depth == DepthLevel.DEEP
		# Non-existent
		assert curated.get_curated_skill("nonexistent") is None

	def test_optional_fields_default(self):
		"""Missing roles, education, certifications all default to []."""
		data = _load_fixture()
		del data["roles"]
		del data["education"]
		del data["certifications"]
		curated = CuratedResume.model_validate(data)
		assert curated.roles == []
		assert curated.education == []
		assert curated.certifications == []

	def test_skills_field_retained_but_loose(self):
		"""Raw skills list accepted as list[dict] without validation."""
		data = _load_fixture()
		# Add some arbitrary dict to skills — should not fail
		data["skills"].append({"arbitrary_key": "arbitrary_value"})
		curated = CuratedResume.model_validate(data)
		assert len(curated.skills) == 2

	def test_skills_field_absent_defaults_empty(self):
		"""If raw skills key is missing, defaults to empty list."""
		data = _load_fixture()
		del data["skills"]
		curated = CuratedResume.model_validate(data)
		assert curated.skills == []

	def test_invalid_depth_in_curated_skill_fails(self):
		data = _load_fixture()
		data["curated_skills"][0]["depth"] = "exprrt"
		with pytest.raises(ValidationError):
			CuratedResume.model_validate(data)

	def test_from_file(self, tmp_path):
		data = _load_fixture()
		path = tmp_path / "test_curated.json"
		path.write_text(json.dumps(data))
		curated = CuratedResume.from_file(path)
		assert curated.name == "Test Candidate"
