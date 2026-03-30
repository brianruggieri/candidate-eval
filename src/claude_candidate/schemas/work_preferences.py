"""
WorkPreferences: Candidate work environment preferences.

Used for preference-based culture fit scoring. Replaces the old
pattern-matching culture scorer with explicit candidate preferences
around remote work, company size, and cultural values.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


RemotePreference = Literal["remote_first", "hybrid", "in_office", "flexible"]
CompanySizePreference = Literal["startup", "mid", "enterprise"]


class WorkPreferences(BaseModel):
	"""Candidate work environment preferences for culture scoring."""

	remote_preference: RemotePreference = "flexible"
	company_size: list[CompanySizePreference] = Field(default_factory=list)
	culture_values: list[str] = Field(default_factory=list)
	culture_avoid: list[str] = Field(default_factory=list)

	@property
	def has_preferences(self) -> bool:
		"""Return True if any non-default preference is set."""
		return (
			self.remote_preference != "flexible"
			or len(self.company_size) > 0
			or len(self.culture_values) > 0
			or len(self.culture_avoid) > 0
		)

	@classmethod
	def load(cls, path: Path) -> WorkPreferences | None:
		"""Load preferences from JSON file, returning None if missing."""
		if not path.exists():
			return None
		data = json.loads(path.read_text())
		return cls.model_validate(data)

	def save(self, path: Path) -> None:
		"""Write preferences to JSON file."""
		path.parent.mkdir(parents=True, exist_ok=True)
		path.write_text(self.model_dump_json(indent=2) + "\n")
