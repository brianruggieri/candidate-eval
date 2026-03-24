"""
SignalMerger: Aggregates SignalResults from all extractors into a CandidateProfile.

Takes SignalResult objects from CodeSignalExtractor, BehaviorSignalExtractor,
and CommSignalExtractor and produces the existing CandidateProfile schema unchanged.
Owns aggregation, deduplication, depth scoring, pattern merging, project enrichment,
and profile assembly.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from claude_candidate.extractors import (
	PatternSignal,
	ProjectSignal,
	SignalResult,
	SkillSignal,
)
from claude_candidate.schemas.candidate_profile import (
	CandidateProfile,
	DEPTH_RANK,
	DepthLevel,
	PatternType,
	ProblemSolvingPattern,
	ProjectComplexity,
	ProjectSummary,
	SessionReference,
	SkillEntry,
)
from claude_candidate.skill_taxonomy import SkillTaxonomy

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Valid SkillEntry categories (must match the Literal in candidate_profile.py)
VALID_CATEGORIES = frozenset(
	{
		"language",
		"framework",
		"tool",
		"platform",
		"concept",
		"practice",
		"domain",
		"soft_skill",
	}
)

# Taxonomy category remapping (taxonomy uses "runtime", schema needs "platform")
CATEGORY_REMAP: dict[str, str] = {
	"runtime": "platform",
}

FALLBACK_CATEGORY = "tool"

# Multi-source (SkillSignal.source-level) confidence boosts
BOOST_2_SOURCES = 0.1
BOOST_3_SOURCES = 0.15

# Depth frequency thresholds — scaled for large corpora (2000+ sessions).
# EXPERT requires both high frequency AND evidence diversity (modifiers).
# Base from frequency alone caps at DEEP to avoid everything becoming EXPERT.
DEPTH_THRESHOLDS: list[tuple[int, DepthLevel]] = [
	(20, DepthLevel.DEEP),
	(8, DepthLevel.APPLIED),
	(3, DepthLevel.USED),
	(2, DepthLevel.USED),
]

# Pattern frequency thresholds
PATTERN_FREQ_DOMINANT = 5
PATTERN_FREQ_COMMON = 3
PATTERN_FREQ_OCCASIONAL = 2

# Project complexity thresholds
PROJECT_AMBITIOUS = 10
PROJECT_COMPLEX = 5
PROJECT_MODERATE = 3
PROJECT_SIMPLE = 2

TOP_N = 5

# Depth levels in order for index-based navigation
DEPTH_LEVELS = [
	DepthLevel.MENTIONED,
	DepthLevel.USED,
	DepthLevel.APPLIED,
	DepthLevel.DEEP,
	DepthLevel.EXPERT,
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _depth_from_rank(rank: int) -> DepthLevel:
	"""Convert numeric rank (0-4) to DepthLevel, clamped."""
	rank = max(0, min(rank, len(DEPTH_LEVELS) - 1))
	return DEPTH_LEVELS[rank]


def _pattern_frequency(session_count: int) -> str:
	"""Classify pattern frequency from session count."""
	if session_count >= PATTERN_FREQ_DOMINANT:
		return "dominant"
	if session_count >= PATTERN_FREQ_COMMON:
		return "common"
	if session_count >= PATTERN_FREQ_OCCASIONAL:
		return "occasional"
	return "rare"


def _pattern_strength(session_count: int, has_advanced: bool = False) -> str:
	"""Classify pattern strength."""
	if session_count >= 5 and has_advanced:
		return "exceptional"
	if session_count >= 3:
		return "strong"
	if session_count >= 2:
		return "established"
	return "emerging"


def _project_complexity(session_count: int) -> ProjectComplexity:
	"""Classify project complexity by session count."""
	if session_count >= PROJECT_AMBITIOUS:
		return ProjectComplexity.AMBITIOUS
	if session_count >= PROJECT_COMPLEX:
		return ProjectComplexity.COMPLEX
	if session_count >= PROJECT_MODERATE:
		return ProjectComplexity.MODERATE
	if session_count >= PROJECT_SIMPLE:
		return ProjectComplexity.SIMPLE
	return ProjectComplexity.TRIVIAL


# ---------------------------------------------------------------------------
# SignalMerger
# ---------------------------------------------------------------------------


class SignalMerger:
	"""Aggregates SignalResults from all extractors into a CandidateProfile."""

	def __init__(self) -> None:
		self._taxonomy = SkillTaxonomy.load_default()

	def merge(
		self,
		results: list[SignalResult],
		manifest_hash: str,
	) -> CandidateProfile:
		"""Merge all extractor results into a single CandidateProfile."""
		if not results:
			return self._build_empty_profile(manifest_hash)

		skills = self._aggregate_skills(results)
		patterns = self._aggregate_patterns(results)
		projects = self._build_projects(results)

		# Date range
		all_dates = [r.session_date for r in results]
		date_start = min(all_dates)
		date_end = max(all_dates)

		# Unique session count
		session_ids = {r.session_id for r in results}
		session_count = len(session_ids)

		return CandidateProfile(
			generated_at=datetime.now(timezone.utc),
			session_count=session_count,
			date_range_start=date_start,
			date_range_end=date_end,
			manifest_hash=manifest_hash,
			skills=skills,
			primary_languages=self._top_by_category(skills, "language"),
			primary_domains=self._top_by_category(skills, "domain"),
			problem_solving_patterns=patterns,
			working_style_summary=self._build_working_style(patterns),
			projects=projects,
			communication_style=self._derive_communication_style(results),
			documentation_tendency=self._assess_documentation(results),
			extraction_notes=f"Merged from {len(results)} result(s) across {session_count} session(s)",
			confidence_assessment=self._assess_confidence(session_count, results),
		)

	# -------------------------------------------------------------------
	# Skill Aggregation
	# -------------------------------------------------------------------

	def _aggregate_skills(self, results: list[SignalResult]) -> list[SkillEntry]:
		"""Group all SkillSignals by canonical_name, aggregate, and score."""
		# Collect all signals per canonical name
		skill_signals: dict[str, list[tuple[SignalResult, SkillSignal]]] = defaultdict(list)
		for r in results:
			for _name, signals in r.skills.items():
				for sig in signals:
					skill_signals[sig.canonical_name].append((r, sig))

		entries = []
		for canonical_name, pairs in sorted(skill_signals.items()):
			entry = self._build_skill_entry(canonical_name, pairs)
			entries.append(entry)
		return entries

	def _build_skill_entry(
		self,
		canonical_name: str,
		pairs: list[tuple[SignalResult, SkillSignal]],
	) -> SkillEntry:
		"""Build a single SkillEntry from all signals for one skill."""
		# Collect distinct source types and session IDs
		source_types: set[str] = set()
		session_ids: set[str] = set()
		evidence_types: set[str] = set()
		all_dates: list[datetime] = []

		for result, sig in pairs:
			source_types.add(sig.source)
			session_ids.add(result.session_id)
			evidence_types.add(sig.evidence_type)
			all_dates.append(result.session_date)

		frequency = len(session_ids)
		num_sources = len(source_types)

		# Multi-source confidence boost
		if num_sources >= 3:
			boost = BOOST_3_SOURCES
		elif num_sources >= 2:
			boost = BOOST_2_SOURCES
		else:
			boost = 0.0

		# Depth scoring
		depth = self._score_depth(
			frequency=frequency,
			source_types=source_types,
			evidence_types=evidence_types,
			num_sources=num_sources,
		)

		# Category mapping
		category = self._resolve_category(canonical_name)

		# Build evidence (SessionReference list)
		evidence = self._build_evidence(pairs, boost)

		return SkillEntry(
			name=canonical_name,
			category=category,
			depth=depth,
			frequency=max(frequency, 1),
			recency=max(all_dates),
			first_seen=min(all_dates),
			evidence=evidence,
		)

	def _score_depth(
		self,
		*,
		frequency: int,
		source_types: set[str],
		evidence_types: set[str],
		num_sources: int,
	) -> DepthLevel:
		"""Compute depth level with base thresholds and modifiers."""
		# Check import-only and package-only caps first
		if source_types == {"import_statement"}:
			return DepthLevel.USED
		if source_types == {"package_command"}:
			return DepthLevel.MENTIONED

		# Base depth from frequency
		base_rank = 0  # MENTIONED
		for min_freq, level in DEPTH_THRESHOLDS:
			if frequency >= min_freq:
				base_rank = DEPTH_RANK[level]
				break

		# Modifiers
		bonus = 0
		if "debugging" in evidence_types:
			bonus += 1
		if "architecture_decision" in evidence_types:
			bonus += 1
		if num_sources >= 2:
			bonus += 1

		final_rank = min(base_rank + bonus, DEPTH_RANK[DepthLevel.EXPERT])
		return _depth_from_rank(final_rank)

	def _resolve_category(self, skill_name: str) -> str:
		"""Resolve a skill's category from taxonomy, with remapping and fallback."""
		raw_category = self._taxonomy.get_category(skill_name)
		if raw_category is None:
			return FALLBACK_CATEGORY
		# Remap taxonomy categories that don't match the schema
		remapped = CATEGORY_REMAP.get(raw_category, raw_category)
		if remapped not in VALID_CATEGORIES:
			return FALLBACK_CATEGORY
		return remapped

	def _build_evidence(
		self,
		pairs: list[tuple[SignalResult, SkillSignal]],
		boost: float,
	) -> list[SessionReference]:
		"""Build SessionReference list from (result, signal) pairs."""
		evidence: list[SessionReference] = []
		for result, sig in pairs:
			confidence = min(sig.confidence + boost, 1.0)
			snippet = sig.evidence_snippet.strip()
			if not snippet:
				snippet = f"Detected {sig.canonical_name} via {sig.source}"
			evidence.append(
				SessionReference(
					session_id=result.session_id,
					session_date=result.session_date,
					project_context=result.project_context,
					evidence_snippet=snippet,
					evidence_type=sig.evidence_type,
					confidence=confidence,
				)
			)
		return evidence

	# -------------------------------------------------------------------
	# Pattern Aggregation
	# -------------------------------------------------------------------

	def _aggregate_patterns(
		self,
		results: list[SignalResult],
	) -> list[ProblemSolvingPattern]:
		"""Group PatternSignals by pattern_type, merge, and score."""
		# Collect all pattern signals grouped by type
		pattern_groups: dict[PatternType, list[tuple[SignalResult, PatternSignal]]] = defaultdict(
			list
		)
		for r in results:
			for ps in r.patterns:
				pattern_groups[ps.pattern_type].append((r, ps))

		patterns = []
		for pt, pairs in sorted(pattern_groups.items(), key=lambda kv: kv[0].value):
			patterns.append(self._build_pattern(pt, pairs))
		return patterns

	def _build_pattern(
		self,
		pt: PatternType,
		pairs: list[tuple[SignalResult, PatternSignal]],
	) -> ProblemSolvingPattern:
		"""Build a single ProblemSolvingPattern from grouped signals."""
		# Collect all unique session IDs across all PatternSignals for this type
		all_session_ids: set[str] = set()
		descriptions: list[str] = []
		has_advanced = False

		for result, ps in pairs:
			all_session_ids.update(ps.session_ids)
			all_session_ids.add(result.session_id)
			descriptions.append(ps.description)
			if ps.metadata:
				has_advanced = True

		session_count = len(all_session_ids)

		# Pick the best description (longest non-generic)
		description = max(descriptions, key=len) if descriptions else f"Pattern {pt.value}"

		# Build evidence — one per unique (result, pattern) pair
		evidence: list[SessionReference] = []
		for result, ps in pairs:
			snippet = ps.evidence_snippet.strip()
			if not snippet:
				snippet = f"Pattern {pt.value} observed"
			evidence.append(
				SessionReference(
					session_id=result.session_id,
					session_date=result.session_date,
					project_context=result.project_context,
					evidence_snippet=snippet,
					evidence_type="direct_usage",
					confidence=ps.confidence,
				)
			)

		return ProblemSolvingPattern(
			pattern_type=pt,
			frequency=_pattern_frequency(session_count),
			strength=_pattern_strength(session_count, has_advanced),
			description=description,
			evidence=evidence,
		)

	# -------------------------------------------------------------------
	# Project Enrichment
	# -------------------------------------------------------------------

	def _build_projects(self, results: list[SignalResult]) -> list[ProjectSummary]:
		"""Group results by project_context and build enriched ProjectSummaries."""
		project_results: dict[str, list[SignalResult]] = defaultdict(list)
		for r in results:
			project_results[r.project_context].append(r)

		projects = []
		for project_name, proj_results in sorted(project_results.items()):
			projects.append(self._build_one_project(project_name, proj_results))
		return projects

	def _build_one_project(
		self,
		project_name: str,
		results: list[SignalResult],
	) -> ProjectSummary:
		"""Build a single ProjectSummary from results for one project."""
		# Merge project signals
		description_fragments: list[str] = []
		key_decisions: list[str] = []
		challenges: list[str] = []
		technologies: set[str] = set()
		all_dates: list[datetime] = []
		session_ids: set[str] = set()

		for r in results:
			session_ids.add(r.session_id)
			all_dates.append(r.session_date)

			# Collect technologies from skill names
			for skill_name in r.skills:
				technologies.add(skill_name)

			# Merge project signal data
			if r.project_signals:
				description_fragments.extend(r.project_signals.description_fragments)
				key_decisions.extend(r.project_signals.key_decisions)
				challenges.extend(r.project_signals.challenges)

		# Build description
		if description_fragments:
			description = " ".join(description_fragments)
		else:
			description = f"Project {project_name} with {len(session_ids)} session(s)"

		session_count = len(session_ids)

		# Build evidence
		evidence: list[SessionReference] = []
		for r in results:
			# Pick first skill signal snippet, or fallback
			snippet = None
			for _name, signals in r.skills.items():
				for sig in signals:
					s = sig.evidence_snippet.strip()
					if s:
						snippet = s
						break
				if snippet:
					break
			if not snippet:
				snippet = f"Session {r.session_id} in {project_name}"
			evidence.append(
				SessionReference(
					session_id=r.session_id,
					session_date=r.session_date,
					project_context=r.project_context,
					evidence_snippet=snippet,
					evidence_type="direct_usage",
					confidence=0.7,
				)
			)

		return ProjectSummary(
			project_name=project_name,
			description=description,
			complexity=_project_complexity(session_count),
			technologies=sorted(technologies),
			session_count=max(session_count, 1),
			date_range_start=min(all_dates),
			date_range_end=max(all_dates),
			key_decisions=key_decisions[:5],
			challenges_overcome=challenges[:5],
			evidence=evidence,
		)

	# -------------------------------------------------------------------
	# Profile Assembly Helpers
	# -------------------------------------------------------------------

	def _derive_communication_style(self, results: list[SignalResult]) -> str:
		"""Derive communication style from CommSignalExtractor metrics."""
		total_steering = 0.0
		total_deferral = 0.0
		total_sessions = 0

		for r in results:
			if r.metrics:
				total_steering += r.metrics.get("steering_count", 0.0)
				total_deferral += r.metrics.get("deferral_count", 0.0)
				total_sessions += 1

		if total_sessions == 0:
			return "Data-driven and evidence-based"

		avg_steering = total_steering / total_sessions
		avg_deferral = total_deferral / total_sessions

		if avg_steering >= 2.0 and avg_deferral <= 0.5:
			return "Precise and scope-conscious"
		if avg_steering >= 1.0:
			return "Directive and focused"
		if avg_deferral >= 1.0:
			return "Collaborative and flexible"
		return "Data-driven and evidence-based"

	def _assess_documentation(self, results: list[SignalResult]) -> str:
		"""Assess documentation tendency from metrics."""
		doc_edits = sum(r.metrics.get("doc_edit_count", 0.0) for r in results)
		session_count = len({r.session_id for r in results})
		if session_count == 0:
			return "minimal"
		avg = doc_edits / session_count
		if avg >= 3:
			return "extensive"
		if avg >= 1.5:
			return "thorough"
		if avg >= 0.5:
			return "moderate"
		return "minimal"

	def _assess_confidence(
		self,
		session_count: int,
		results: list[SignalResult],
	) -> str:
		"""Assess confidence based on session count and cross-extractor corroboration."""
		# Count skills with multi-source corroboration
		skill_sources: dict[str, set[str]] = defaultdict(set)
		for r in results:
			for _name, signals in r.skills.items():
				for sig in signals:
					skill_sources[sig.canonical_name].add(sig.source)
		corroborated = sum(1 for sources in skill_sources.values() if len(sources) >= 2)

		if session_count >= 20 and corroborated >= 5:
			return "very_high"
		if session_count >= 10 or corroborated >= 3:
			return "high"
		if session_count >= 3:
			return "moderate"
		return "low"

	def _build_working_style(self, patterns: list[ProblemSolvingPattern]) -> str:
		"""Summarize working style from observed patterns."""
		if not patterns:
			return "Insufficient data to characterize working style."
		names = [p.pattern_type.value for p in patterns[:5]]
		return f"Working style includes: {', '.join(names)}."

	def _top_by_category(self, skills: list[SkillEntry], category: str) -> list[str]:
		"""Return top N skill names for a given category, sorted by frequency."""
		filtered = [s for s in skills if s.category == category]
		filtered.sort(key=lambda s: s.frequency, reverse=True)
		return [s.name for s in filtered[:TOP_N]]

	def _build_empty_profile(self, manifest_hash: str) -> CandidateProfile:
		"""Build a minimal valid profile when no results are available."""
		now = datetime.now(timezone.utc)
		return CandidateProfile(
			generated_at=now,
			session_count=0,
			date_range_start=now,
			date_range_end=now,
			manifest_hash=manifest_hash,
			skills=[],
			primary_languages=[],
			primary_domains=[],
			problem_solving_patterns=[],
			working_style_summary="No sessions available for analysis.",
			projects=[],
			communication_style="Data-driven and evidence-based",
			documentation_tendency="minimal",
			extraction_notes="No sessions provided",
			confidence_assessment="low",
		)
