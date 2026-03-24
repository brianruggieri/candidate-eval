"""
SessionManifest: Cryptographic chain of custody for pipeline runs.

Proves which sessions were processed, what was redacted, and links
to public repo corroboration — without exposing raw session content.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class SessionFileRecord(BaseModel):
	"""Record for a single session file in the manifest."""

	session_id: str
	original_path: str  # Relative path (no absolute paths — privacy)
	file_size_bytes: int = Field(ge=0)
	line_count: int = Field(ge=0)
	token_count_estimate: int = Field(ge=0)
	created_at: datetime
	modified_at: datetime

	# Hashes
	hash_raw: str
	hash_sanitized: str | None = None
	hash_algorithm: str = "sha256"

	# Content metadata (non-revealing)
	project_hint: str | None = None
	technologies_detected: list[str] = Field(default_factory=list)
	flags: list[str] = Field(default_factory=list)


class RedactionSummary(BaseModel):
	"""Aggregate redaction statistics for the proof package."""

	total_redactions: int = Field(ge=0)
	redactions_by_type: dict[str, int]
	sessions_with_redactions: int = Field(ge=0)
	sessions_without_redactions: int = Field(ge=0)
	heaviest_redaction_session: str | None = None
	redaction_density: float = Field(ge=0.0)
	sample_redaction_types: list[str] = Field(max_length=5)


class PublicRepoCorrelation(BaseModel):
	"""Evidence linking session activity to public git history."""

	repo_url: str
	repo_name: str
	session_ids: list[str]
	commit_hashes: list[str]
	correlation_type: Literal["filename_match", "temporal", "content_reference", "combined"]
	correlation_strength: Literal["strong", "moderate", "weak"]
	notes: str


class PipelineArtifactRecord(BaseModel):
	"""Hash record for a pipeline-generated artifact."""

	artifact_name: str
	artifact_path: str
	hash: str
	generated_at: datetime
	generated_by: str
	schema_version: str


class CorpusStatistics(BaseModel):
	"""Non-revealing aggregate statistics about the session corpus."""

	total_sessions: int = Field(ge=0)
	total_lines: int = Field(ge=0)
	total_tokens_estimate: int = Field(ge=0)
	date_range_start: datetime
	date_range_end: datetime
	date_span_days: int = Field(ge=0)
	sessions_per_month: dict[str, int]  # "YYYY-MM" → count
	unique_projects: int = Field(ge=0)
	technologies_overview: dict[str, int]  # tech name → session count
	average_session_length_tokens: int = Field(ge=0)
	median_session_length_tokens: int = Field(ge=0)
	longest_session_tokens: int = Field(ge=0)


class SessionManifest(BaseModel):
	"""
	Complete trust document for a pipeline run.

	Cryptographic chain of custody from raw sessions to deliverables.
	"""

	manifest_version: str = "0.1.0"
	manifest_id: str
	generated_at: datetime
	pipeline_version: str
	run_id: str

	sessions: list[SessionFileRecord]
	corpus_statistics: CorpusStatistics
	redaction_summary: RedactionSummary
	public_repo_correlations: list[PublicRepoCorrelation]
	pipeline_artifacts: list[PipelineArtifactRecord]

	# Self-integrity hash (set as final step)
	manifest_hash: str | None = None

	def to_json(self) -> str:
		return self.model_dump_json(indent=2)

	@classmethod
	def from_json(cls, data: str) -> SessionManifest:
		return cls.model_validate_json(data)
