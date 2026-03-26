"""
MergedEvidenceProfile: Combined view of resume and session evidence.

The primary input to the Quick Match engine. Provides a single,
deduplicated skill list with provenance tracking and merged depth assessments.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from claude_candidate.schemas.candidate_profile import (
	DepthLevel,
	DEPTH_RANK,
	ProblemSolvingPattern,
	ProjectSummary,
)
from claude_candidate.schemas.resume_profile import ResumeRole

RANK_TO_DEPTH: dict[int, "DepthLevel"] = {v: k for k, v in DEPTH_RANK.items()}


class EvidenceSource(str, Enum):
	"""Where the evidence for a skill comes from."""

	RESUME_ONLY = "resume_only"  # Claimed on resume, not in sessions
	SESSIONS_ONLY = "sessions_only"  # deprecated: v0.8 removal
	CORROBORATED = "corroborated"  # deprecated: v0.8 removal
	CONFLICTING = "conflicting"  # deprecated: v0.8 removal
	RESUME_AND_REPO = "resume_and_repo"  # NEW: Both resume and repo evidence
	REPO_ONLY = "repo_only"  # NEW: In repos, not on resume


class MergedSkillEvidence(BaseModel):
	"""A skill with evidence from both resume and session logs."""

	name: str
	source: EvidenceSource

	# Resume evidence
	resume_depth: DepthLevel | None = None
	resume_context: str | None = None
	resume_years: float | None = None
	resume_duration: str | None = None  # e.g. "8 years", "2 months" from curated resume

	# Session evidence (deprecated: parked for v0.8)
	session_depth: DepthLevel | None = None  # deprecated: v0.8 removal
	session_frequency: int | None = None  # deprecated: v0.8 removal
	session_evidence_count: int | None = None  # deprecated: v0.8 removal
	session_recency: datetime | None = None  # deprecated: v0.8 removal
	session_first_seen: datetime | None = None  # deprecated: v0.8 removal

	# Repo evidence (NEW)
	repo_count: int | None = None  # repos where this skill appears
	repo_bytes: int | None = None  # total bytes across repos
	repo_first_seen: datetime | None = None  # earliest repo commit with this skill
	repo_last_seen: datetime | None = None  # latest repo commit with this skill
	repo_frameworks: list[str] | None = None  # frameworks detected via dependencies
	repo_confirmed: bool = False  # skill found in repo evidence

	# Merged assessment
	effective_depth: DepthLevel
	confidence: float | None = Field(default=None, ge=0.0, le=1.0)  # deprecated: moves to match time in v0.7
	discovery_flag: bool = False  # deprecated: v0.8 removal
	category: str | None = None  # taxonomy category: "language", "framework", etc.

	@staticmethod
	def compute_effective_depth(
		source: EvidenceSource,
		resume_depth: DepthLevel | None,
		session_depth: DepthLevel | None,
	) -> DepthLevel:
		"""
		Compute the effective depth based on evidence source.

		Rules:
		- corroborated: max(resume, session) — both agree, use strongest
		- resume_only: resume depth, flagged as unverified
		- sessions_only: session depth — demonstrated > claimed
		- conflicting: resume anchors depth; sessions boost by at most one level
		"""
		if source == EvidenceSource.CORROBORATED:
			r_rank = DEPTH_RANK.get(resume_depth, 0) if resume_depth else 0
			s_rank = DEPTH_RANK.get(session_depth, 0) if session_depth else 0
			if s_rank >= r_rank:
				return session_depth or DepthLevel.MENTIONED
			return resume_depth or DepthLevel.MENTIONED
		elif source == EvidenceSource.RESUME_ONLY:
			return resume_depth or DepthLevel.MENTIONED
		elif source == EvidenceSource.SESSIONS_ONLY:
			return session_depth or DepthLevel.MENTIONED
		else:  # CONFLICTING — both sources present, depths diverge by 2+ levels.
			# Resume anchors: earned expertise > short-duration agentic sessions.
			# Sessions can boost resume by one rung but cannot leapfrog it.
			if resume_depth is not None and session_depth is not None:
				r_rank = DEPTH_RANK.get(resume_depth, 0)
				s_rank = DEPTH_RANK.get(session_depth, 0)
				if s_rank > r_rank:
					# Sessions claim higher — one conservative rung above resume, capped at DEEP
					boosted_rank = min(r_rank + 1, DEPTH_RANK[DepthLevel.DEEP])
					return RANK_TO_DEPTH[boosted_rank]
				else:
					# Resume claims higher — trust resume as earned-expertise anchor
					return resume_depth
			# Only one side present — resume preferred
			return resume_depth or session_depth or DepthLevel.MENTIONED

	@staticmethod
	def compute_confidence(
		source: EvidenceSource,
		session_frequency: int | None,
		resume_context: str | None,
	) -> float:
		"""
		Compute confidence score based on evidence quality.

		Deprecated: confidence moves to match time in v0.7. Use compute_confidence() module
		function instead. This static method is kept for backward compatibility with merger.py
		until Task 7 rewrites it.
		"""
		return compute_confidence(source, session_frequency, resume_context)


class MergedEvidenceProfile(BaseModel):
	"""
	Combined view of resume + session evidence.

	This is the primary input to the QuickMatchEngine.
	"""

	skills: list[MergedSkillEvidence]
	patterns: list[ProblemSolvingPattern]  # From sessions only
	projects: list[ProjectSummary]  # From sessions only
	roles: list[ResumeRole]  # From resume only

	# Resume-level fields (propagated for scoring dimensions)
	total_years_experience: float | None = None
	education: list[str] = Field(default_factory=list)

	# Aggregate stats
	corroborated_skill_count: int = Field(ge=0)
	resume_only_skill_count: int = Field(ge=0)
	sessions_only_skill_count: int = Field(ge=0)
	repo_confirmed_skill_count: int = Field(ge=0, default=0)
	discovery_skills: list[str]  # Skills resume should probably mention

	# Provenance
	profile_hash: str
	resume_hash: str
	candidate_profile_hash: str
	merged_at: datetime

	def get_skill(self, name: str) -> MergedSkillEvidence | None:
		"""Look up a merged skill by canonical name."""
		normalized = name.lower().strip()
		for skill in self.skills:
			if skill.name == normalized:
				return skill
		return None

	def skills_above_depth(self, min_depth: DepthLevel) -> list[MergedSkillEvidence]:
		"""Return skills at or above a minimum depth level."""
		min_rank = DEPTH_RANK[min_depth]
		return [s for s in self.skills if DEPTH_RANK.get(s.effective_depth, 0) >= min_rank]

	def to_json(self) -> str:
		return self.model_dump_json(indent=2)

	@classmethod
	def from_json(cls, data: str) -> MergedEvidenceProfile:
		return cls.model_validate_json(data)


def compute_confidence(
	source: EvidenceSource,
	session_frequency: int | None,
	resume_context: str | None,
) -> float:
	"""
	Standalone confidence computation based on evidence quality.

	Deprecated: confidence moves to match time in v0.7. Kept for merger.py backward
	compatibility until Task 7 rewrites it.

	Actual return values:
	- corroborated: 0.70 + min(freq/50, 0.30) → 0.70–1.0
	- sessions_only + freq ≥ 20 → 0.85
	- sessions_only + freq 5–19 → 0.65
	- sessions_only + freq < 5 → 0.45
	- resume_only → 0.85 (resume is legitimate work evidence; no penalty for missing sessions)
	- conflicting → 0.72 (both sources present; depth uncertainty handled separately)
	"""
	freq = session_frequency or 0

	if source == EvidenceSource.CORROBORATED:
		base = 0.7
		freq_bonus = min(freq / 50, 0.3)  # Up to 0.3 bonus for frequency
		return min(base + freq_bonus, 1.0)
	elif source == EvidenceSource.SESSIONS_ONLY:
		if freq >= 20:
			return 0.85
		elif freq >= 5:
			return 0.65
		else:
			return 0.45
	elif source == EvidenceSource.RESUME_ONLY:
		# Resume claims are legitimate evidence of real work experience.
		# Depth accuracy is handled by the depth matching system, not
		# confidence. No penalty for skills not demonstrated in sessions.
		return 0.85
	else:  # CONFLICTING / RESUME_AND_REPO / REPO_ONLY
		return 0.72
