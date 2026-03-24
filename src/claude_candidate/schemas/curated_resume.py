"""
CuratedResume: Human-curated resume profile with rated skill depths.

Produced by `resume onboard`. Supersedes raw ResumeProfile for merge —
curated_skills have manually verified depths and durations instead of
parser-inferred "mentioned" everywhere.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from claude_candidate.schemas.candidate_profile import DepthLevel
from claude_candidate.schemas.resume_profile import ResumeRole


class CuratedSkill(BaseModel):
	"""A skill with human-curated depth and duration."""

	name: str
	depth: DepthLevel
	duration: str | None = None  # e.g. "8 years", "2 months"
	source_context: str = "Listed in skills section"
	curated: bool = True

	@field_validator("name")
	@classmethod
	def normalize_name(cls, v: str) -> str:
		return v.lower().strip()


class CuratedResume(BaseModel):
	"""
	Human-curated resume profile.

	Produced by `resume onboard` from a parsed ResumeProfile with
	manually rated skill depths. The `curated_skills` list supersedes
	the raw `skills` array — the raw list is retained for provenance
	but is never used in scoring.
	"""

	profile_version: str = "0.1.0"
	parsed_at: datetime
	source_file_hash: str
	source_format: Literal["pdf", "docx", "txt"]

	# Identity
	name: str | None = None
	current_title: str | None = None
	location: str | None = None

	# Experience
	roles: list[ResumeRole] = Field(default_factory=list)
	total_years_experience: float | None = None

	# Education & Certs
	education: list[str] = Field(default_factory=list)
	certifications: list[str] = Field(default_factory=list)

	# Summary
	professional_summary: str | None = None

	# The curated data (this is what the merge pipeline uses)
	curated_skills: list[CuratedSkill] = Field(min_length=1)
	curated: bool = True

	# Raw parser output retained for provenance — not used in scoring
	skills: list[dict] = Field(default_factory=list)  # kept loose, not validated

	@model_validator(mode="after")
	def check_curated_skills_not_empty(self) -> CuratedResume:
		"""Fail loudly if curated_skills is missing or empty."""
		if not self.curated_skills:
			raise ValueError(
				"curated_skills must not be empty — "
				"run `resume onboard` to create a curated profile"
			)
		return self

	def get_curated_skill(self, name: str) -> CuratedSkill | None:
		"""Look up a curated skill by canonical name."""
		normalized = name.lower().strip()
		for skill in self.curated_skills:
			if skill.name == normalized:
				return skill
		return None

	def to_json(self) -> str:
		return self.model_dump_json(indent=2)

	@classmethod
	def from_json(cls, data: str) -> CuratedResume:
		return cls.model_validate_json(data)

	@classmethod
	def from_file(cls, path) -> CuratedResume:
		"""Load and validate from a JSON file path."""
		import json
		from pathlib import Path

		p = Path(path)
		return cls.model_validate(json.loads(p.read_text()))
