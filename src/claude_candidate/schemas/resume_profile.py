"""
ResumeProfile: Structured representation of the user's resume.

Parsed from PDF or DOCX upload. All data comes directly from
the resume — no inference beyond normalizing skill names and
estimating depth from context.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from claude_candidate.schemas.candidate_profile import DepthLevel


class ResumeSkill(BaseModel):
	"""A skill extracted from the resume."""

	name: str
	source_context: str
	implied_depth: DepthLevel
	years_experience: float | None = None
	recency: Literal["current_role", "previous_role", "historical", "unknown"]

	@field_validator("name")
	@classmethod
	def normalize_name(cls, v: str) -> str:
		return v.lower().strip()


class ResumeRole(BaseModel):
	"""A role/position extracted from the resume."""

	title: str
	company: str
	start_date: str  # "YYYY-MM" or "YYYY"
	end_date: str | None = None  # None if current role
	duration_months: int | None = None
	description: str
	technologies: list[str]
	achievements: list[str]
	domain: str | None = None


class ResumeProfile(BaseModel):
	"""
	Structured representation of the user's resume.

	Every field is extracted directly from the resume document.
	"""

	profile_version: str = "0.1.0"
	parsed_at: datetime
	source_file_hash: str
	source_format: Literal["pdf", "docx", "txt"]

	# Identity (minimal, user-controlled)
	name: str | None = None
	current_title: str | None = None
	location: str | None = None

	# Experience
	roles: list[ResumeRole]
	total_years_experience: float | None = None

	# Skills
	skills: list[ResumeSkill]

	# Education & Certs
	education: list[str] = Field(default_factory=list)
	certifications: list[str] = Field(default_factory=list)

	# Summary
	professional_summary: str | None = None

	def get_skill(self, name: str) -> ResumeSkill | None:
		"""Look up a skill by canonical name."""
		normalized = name.lower().strip()
		for skill in self.skills:
			if skill.name == normalized:
				return skill
		return None

	def all_skill_names(self) -> set[str]:
		"""Return all skill names as a set."""
		return {s.name for s in self.skills}

	def to_json(self) -> str:
		return self.model_dump_json(indent=2)

	@classmethod
	def from_json(cls, data: str) -> ResumeProfile:
		return cls.model_validate_json(data)
