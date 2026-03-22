"""
Shared interfaces for the three-extractor architecture.
All extractors produce SignalResult objects. The SignalMerger consumes them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from claude_candidate.message_format import NormalizedMessage
from claude_candidate.schemas.candidate_profile import DepthLevel, PatternType


class NormalizedSession(BaseModel):
	"""Session-level container wrapping NormalizedMessage list with metadata."""
	model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

	session_id: str
	timestamp: datetime
	cwd: str
	project_context: str
	git_branch: str | None = None
	messages: list[NormalizedMessage]


class SkillSignal(BaseModel):
	"""A single skill detection from one extractor."""
	model_config = ConfigDict(frozen=True)

	canonical_name: str
	source: Literal[
		"file_extension", "content_pattern", "import_statement",
		"package_command", "tool_usage", "agent_dispatch",
		"skill_invocation", "user_message", "git_workflow",
		"quality_signal",
	]
	confidence: float = Field(ge=0.0, le=1.0, default=0.7)
	depth_hint: DepthLevel | None = None
	evidence_snippet: str = Field(max_length=500)
	evidence_type: Literal[
		"direct_usage", "architecture_decision", "debugging",
		"teaching", "evaluation", "integration", "refactor",
		"testing", "review", "planning",
	] = "direct_usage"
	metadata: dict[str, Any] = Field(default_factory=dict)


class PatternSignal(BaseModel):
	"""A behavioral or communication pattern detection.
	Does NOT carry frequency/strength — computed by SignalMerger."""
	model_config = ConfigDict(frozen=True)

	pattern_type: PatternType
	session_ids: list[str]
	confidence: float = Field(ge=0.0, le=1.0, default=0.7)
	description: str
	evidence_snippet: str = Field(max_length=500)
	metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectSignal(BaseModel):
	"""Project-level enrichment from a single session."""
	model_config = ConfigDict(frozen=True)

	key_decisions: list[str] = Field(default_factory=list)
	challenges: list[str] = Field(default_factory=list)
	description_fragments: list[str] = Field(default_factory=list)


class SignalResult(BaseModel):
	"""One extraction layer's output for a single session."""
	model_config = ConfigDict(frozen=True)

	session_id: str
	session_date: datetime
	project_context: str
	git_branch: str | None = None
	skills: dict[str, list[SkillSignal]] = Field(default_factory=dict)
	patterns: list[PatternSignal] = Field(default_factory=list)
	project_signals: ProjectSignal | None = None
	metrics: dict[str, float] = Field(default_factory=dict)


class ExtractorProtocol(Protocol):
	"""Contract for all three extractors."""
	def extract_session(self, session: NormalizedSession) -> SignalResult: ...
	def name(self) -> str: ...
