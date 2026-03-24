"""
Evidence compaction: reduces profile size by selecting top evidence per skill.

After extraction produces a full CandidateProfile with potentially thousands of
evidence entries per skill, this module selects the 3-5 best snippets and
collapses the rest into an aggregate summary. Reduces profile from ~49 MB to ~500 KB.

Two selection strategies:
- Claude-powered: sends evidence to Claude for intelligent selection
- Local heuristic: composite score from evidence type, recency, confidence, diversity
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime

from claude_candidate.schemas.candidate_profile import (
	CandidateProfile,
	ProblemSolvingPattern,
	ProjectSummary,
	SessionReference,
	SkillEntry,
)

logger = logging.getLogger(__name__)

COMPACTION_VERSION = "1.0"

# Skills/patterns with this many or fewer evidence entries skip compaction
COMPACTION_THRESHOLD = 10

# How many top evidence entries to keep
MAX_SHOWCASE = 5

# Batch size for medium skills in a single Claude call
MEDIUM_BATCH_SIZE = 8

# Boundary between "large" and "medium" skills
LARGE_SKILL_THRESHOLD = 50

# Evidence type ranking for local heuristic (higher = more valuable)
EVIDENCE_TYPE_RANK: dict[str, int] = {
	"architecture_decision": 5,
	"debugging": 4,
	"refactor": 3,
	"testing": 3,
	"teaching": 4,
	"evaluation": 3,
	"review": 3,
	"planning": 2,
	"integration": 2,
	"direct_usage": 1,
}


def compact_evidence(
	profile: CandidateProfile,
	*,
	use_claude: bool = True,
) -> CandidateProfile:
	"""Compact evidence in a CandidateProfile, reducing size dramatically.

	Args:
		profile: The full uncompacted profile.
		use_claude: If True, attempt Claude-powered selection first,
			falling back to local heuristic on failure.

	Returns:
		The same profile object, mutated in place, with compacted evidence.
	"""
	claude_available = False
	if use_claude:
		claude_available = _check_claude_once()

	# Compact skills
	skills_to_compact = [s for s in profile.skills if len(s.evidence) > COMPACTION_THRESHOLD]
	if skills_to_compact:
		logger.info(
			"Compacting evidence for %d skills (of %d total)",
			len(skills_to_compact),
			len(profile.skills),
		)
		_compact_skills(skills_to_compact, claude_available=claude_available)

	# Compact problem-solving patterns
	patterns_to_compact = [
		p for p in profile.problem_solving_patterns if len(p.evidence) > COMPACTION_THRESHOLD
	]
	if patterns_to_compact:
		logger.info("Compacting evidence for %d patterns", len(patterns_to_compact))
		_compact_patterns(patterns_to_compact, claude_available=claude_available)

	# Compact project evidence
	projects_to_compact = [p for p in profile.projects if len(p.evidence) > COMPACTION_THRESHOLD]
	if projects_to_compact:
		logger.info("Compacting evidence for %d projects", len(projects_to_compact))
		_compact_projects(projects_to_compact, claude_available=claude_available)

	profile.compaction_version = COMPACTION_VERSION
	return profile


def _check_claude_once() -> bool:
	"""Check Claude availability once at the start of compaction."""
	try:
		from claude_candidate.claude_cli import check_claude_available

		available = check_claude_available()
		if not available:
			logger.warning(
				"Claude CLI unavailable — using local heuristic for evidence compaction."
			)
		return available
	except Exception:
		logger.warning("Claude CLI unavailable — using local heuristic for evidence compaction.")
		return False


# ---------------------------------------------------------------------------
# Skill compaction
# ---------------------------------------------------------------------------


def _compact_skills(
	skills: list[SkillEntry],
	*,
	claude_available: bool,
) -> None:
	"""Compact evidence for a list of skills."""
	if claude_available:
		large = [s for s in skills if len(s.evidence) >= LARGE_SKILL_THRESHOLD]
		medium = [s for s in skills if len(s.evidence) < LARGE_SKILL_THRESHOLD]

		# Large skills: one Claude call each
		for skill in large:
			try:
				indices = _claude_select_skill(skill)
				_apply_compaction_to_skill(skill, indices)
			except Exception:
				logger.warning(
					"Claude selection failed for skill %s, using local heuristic",
					skill.name,
				)
				indices = _local_select_evidence(skill.evidence)
				_apply_compaction_to_skill(skill, indices)

		# Medium skills: batch
		if medium:
			_compact_medium_skills_batched(medium)
	else:
		for skill in skills:
			indices = _local_select_evidence(skill.evidence)
			_apply_compaction_to_skill(skill, indices)


def _compact_medium_skills_batched(skills: list[SkillEntry]) -> None:
	"""Batch medium skills into Claude calls."""
	for i in range(0, len(skills), MEDIUM_BATCH_SIZE):
		batch = skills[i : i + MEDIUM_BATCH_SIZE]
		try:
			results = _claude_select_skill_batch(batch)
			for skill in batch:
				indices = results.get(skill.name, None)
				if indices is not None:
					_apply_compaction_to_skill(skill, indices)
				else:
					# Fallback for missing skill in batch response
					indices = _local_select_evidence(skill.evidence)
					_apply_compaction_to_skill(skill, indices)
		except Exception:
			logger.warning(
				"Claude batch selection failed, using local heuristic for %d skills",
				len(batch),
			)
			for skill in batch:
				indices = _local_select_evidence(skill.evidence)
				_apply_compaction_to_skill(skill, indices)


def _apply_compaction_to_skill(skill: SkillEntry, selected_indices: list[int]) -> None:
	"""Replace skill evidence with selected entries + aggregate summary."""
	original_count = len(skill.evidence)
	skill.total_evidence_count = original_count
	skill.compacted = True

	# Validate indices
	valid_indices = [i for i in selected_indices if 0 <= i < original_count]
	if not valid_indices:
		# Keep at least the highest-confidence entry
		best_idx = max(range(original_count), key=lambda i: skill.evidence[i].confidence)
		valid_indices = [best_idx]

	# Deduplicate while preserving order, then cap at MAX_SHOWCASE
	seen: set[int] = set()
	deduped: list[int] = []
	for i in valid_indices:
		if i not in seen:
			seen.add(i)
			deduped.append(i)
	capped_indices = deduped[:MAX_SHOWCASE]

	selected = [skill.evidence[i] for i in capped_indices]

	# Build aggregate from non-selected entries
	excluded_indices = set(range(original_count)) - set(capped_indices)
	excluded = [skill.evidence[i] for i in sorted(excluded_indices)]

	aggregate = _build_aggregate_reference(excluded, all_evidence=skill.evidence)
	skill.evidence = selected + [aggregate]


def _apply_compaction_to_pattern(
	pattern: ProblemSolvingPattern, selected_indices: list[int]
) -> None:
	"""Replace pattern evidence with selected entries + aggregate summary."""
	original_count = len(pattern.evidence)
	pattern.total_evidence_count = original_count
	pattern.compacted = True

	valid_indices = [i for i in selected_indices if 0 <= i < original_count]
	if not valid_indices:
		best_idx = max(range(original_count), key=lambda i: pattern.evidence[i].confidence)
		valid_indices = [best_idx]

	# Deduplicate while preserving order, then cap at MAX_SHOWCASE
	seen_p: set[int] = set()
	deduped_p: list[int] = []
	for i in valid_indices:
		if i not in seen_p:
			seen_p.add(i)
			deduped_p.append(i)
	capped_indices_p = deduped_p[:MAX_SHOWCASE]

	selected = [pattern.evidence[i] for i in capped_indices_p]
	excluded_indices = set(range(original_count)) - set(capped_indices_p)
	excluded = [pattern.evidence[i] for i in sorted(excluded_indices)]

	aggregate = _build_aggregate_reference(excluded, all_evidence=pattern.evidence)
	pattern.evidence = selected + [aggregate]


def _apply_compaction_to_project(project: ProjectSummary, selected_indices: list[int]) -> None:
	"""Replace project evidence with selected entries + aggregate summary."""
	original_count = len(project.evidence)
	project.total_evidence_count = original_count
	project.compacted = True

	valid_indices = [i for i in selected_indices if 0 <= i < original_count]
	if not valid_indices:
		best_idx = max(range(original_count), key=lambda i: project.evidence[i].confidence)
		valid_indices = [best_idx]

	# Deduplicate while preserving order, then cap at MAX_SHOWCASE
	seen_j: set[int] = set()
	deduped_j: list[int] = []
	for i in valid_indices:
		if i not in seen_j:
			seen_j.add(i)
			deduped_j.append(i)
	capped_indices_j = deduped_j[:MAX_SHOWCASE]

	selected = [project.evidence[i] for i in capped_indices_j]
	excluded_indices = set(range(original_count)) - set(capped_indices_j)
	excluded = [project.evidence[i] for i in sorted(excluded_indices)]

	aggregate = _build_aggregate_reference(excluded, all_evidence=project.evidence)
	project.evidence = selected + [aggregate]


# ---------------------------------------------------------------------------
# Pattern compaction
# ---------------------------------------------------------------------------


def _compact_patterns(
	patterns: list[ProblemSolvingPattern],
	*,
	claude_available: bool,
) -> None:
	"""Compact evidence for patterns."""
	if claude_available:
		try:
			results = _claude_select_pattern_batch(patterns)
			for pattern in patterns:
				key = pattern.pattern_type.value
				indices = results.get(key, None)
				if indices is not None:
					_apply_compaction_to_pattern(pattern, indices)
				else:
					indices = _local_select_evidence(pattern.evidence)
					_apply_compaction_to_pattern(pattern, indices)
		except Exception:
			logger.warning("Claude pattern selection failed, using local heuristic")
			for pattern in patterns:
				indices = _local_select_evidence(pattern.evidence)
				_apply_compaction_to_pattern(pattern, indices)
	else:
		for pattern in patterns:
			indices = _local_select_evidence(pattern.evidence)
			_apply_compaction_to_pattern(pattern, indices)


# ---------------------------------------------------------------------------
# Project compaction
# ---------------------------------------------------------------------------


def _compact_projects(
	projects: list[ProjectSummary],
	*,
	claude_available: bool,
) -> None:
	"""Compact evidence for projects."""
	if claude_available:
		try:
			results = _claude_select_project_batch(projects)
			for project in projects:
				indices = results.get(project.project_name, None)
				if indices is not None:
					_apply_compaction_to_project(project, indices)
				else:
					indices = _local_select_evidence(project.evidence)
					_apply_compaction_to_project(project, indices)
		except Exception:
			logger.warning("Claude project selection failed, using local heuristic")
			for project in projects:
				indices = _local_select_evidence(project.evidence)
				_apply_compaction_to_project(project, indices)
	else:
		for project in projects:
			indices = _local_select_evidence(project.evidence)
			_apply_compaction_to_project(project, indices)


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------


def _build_aggregate_reference(
	excluded: list[SessionReference],
	*,
	all_evidence: list[SessionReference],
) -> SessionReference:
	"""Build a synthetic aggregate SessionReference from collapsed evidence.

	Args:
		excluded: The evidence entries that were NOT selected (being collapsed).
		all_evidence: All evidence entries (selected + excluded) for date range/stats.
	"""
	if not excluded:
		# Edge case: everything was selected. Create a minimal aggregate.
		most_recent = max(all_evidence, key=lambda e: e.session_date)
		return SessionReference(
			session_id="__aggregate__",
			session_date=most_recent.session_date,
			project_context="aggregate",
			evidence_snippet="All evidence entries were selected as showcase.",
			evidence_type="direct_usage",
			confidence=0.7,
		)

	# Compute stats from ALL evidence for the summary
	all_dates = [e.session_date for e in all_evidence]
	min_date = min(all_dates)
	max_date = max(all_dates)
	total_sessions = len(all_evidence)

	projects = set(e.project_context for e in all_evidence if e.project_context != "aggregate")
	type_counts = Counter(e.evidence_type for e in all_evidence)
	type_breakdown = ", ".join(
		f"{et} ({count})" for et, count in sorted(type_counts.items(), key=lambda x: -x[1])
	)

	date_fmt = "%Y-%m"
	snippet = (
		f"{total_sessions} sessions across {len(projects)} projects "
		f"({min_date.strftime(date_fmt)} to {max_date.strftime(date_fmt)}). "
		f"Evidence types: {type_breakdown}."
	)
	# Truncate to 500 chars if needed
	if len(snippet) > 500:
		snippet = snippet[:497] + "..."

	most_recent = max(excluded, key=lambda e: e.session_date)
	return SessionReference(
		session_id="__aggregate__",
		session_date=most_recent.session_date,
		project_context="aggregate",
		evidence_snippet=snippet,
		evidence_type="direct_usage",
		confidence=0.7,
	)


# ---------------------------------------------------------------------------
# Local heuristic selection (fallback)
# ---------------------------------------------------------------------------


def _local_select_evidence(
	evidence: list[SessionReference],
	*,
	max_select: int = MAX_SHOWCASE,
) -> list[int]:
	"""Select best evidence indices using a local composite score.

	Score = evidence_type_rank * 0.4 + recency_rank * 0.3 + confidence * 0.3

	After scoring, enforce project diversity: ensure at least 2 different
	project_context values if available.
	"""
	if len(evidence) <= max_select:
		return list(range(len(evidence)))

	# Compute recency ranks (0-1 normalized)
	dates = [e.session_date for e in evidence]
	min_date = min(dates)
	max_date = max(dates)
	date_range = (max_date - min_date).total_seconds()

	scored: list[tuple[int, float]] = []
	for i, e in enumerate(evidence):
		type_rank = EVIDENCE_TYPE_RANK.get(e.evidence_type, 1)
		# Normalize type rank to 0-1 (max is 5)
		type_score = type_rank / 5.0

		if date_range > 0:
			recency_score = (e.session_date - min_date).total_seconds() / date_range
		else:
			recency_score = 1.0

		composite = type_score * 0.4 + recency_score * 0.3 + e.confidence * 0.3
		scored.append((i, composite))

	# Sort by score descending
	scored.sort(key=lambda x: -x[1])
	selected_indices = [idx for idx, _ in scored[:max_select]]

	# Enforce project diversity: at least 2 different projects if available
	selected_projects = {evidence[i].project_context for i in selected_indices}
	if len(selected_projects) < 2:
		# Find the highest-scored entry from a different project
		all_projects = {e.project_context for e in evidence}
		if len(all_projects) >= 2:
			for idx, _ in scored[max_select:]:
				if evidence[idx].project_context not in selected_projects:
					# Swap with the lowest-scored selected entry
					selected_indices[-1] = idx
					break

	return selected_indices


# ---------------------------------------------------------------------------
# Claude-powered selection
# ---------------------------------------------------------------------------


def _claude_select_skill(skill: SkillEntry) -> list[int]:
	"""Use Claude to select best evidence for a single skill."""
	from claude_candidate.claude_cli import call_claude

	prompt = _build_skill_prompt(skill.name, skill.category, skill.depth.value, skill.evidence)
	response = call_claude(prompt, timeout=120)
	return _parse_single_response(response, max_index=len(skill.evidence) - 1)


def _claude_select_skill_batch(skills: list[SkillEntry]) -> dict[str, list[int]]:
	"""Use Claude to select best evidence for a batch of skills."""
	from claude_candidate.claude_cli import call_claude

	prompt = _build_batch_skill_prompt(skills)
	response = call_claude(prompt, timeout=120)
	return _parse_batch_response(response, skills)


def _claude_select_pattern_batch(
	patterns: list[ProblemSolvingPattern],
) -> dict[str, list[int]]:
	"""Use Claude to select best evidence for patterns."""
	from claude_candidate.claude_cli import call_claude

	prompt = _build_pattern_batch_prompt(patterns)
	response = call_claude(prompt, timeout=120)
	return _parse_pattern_batch_response(response, patterns)


def _claude_select_project_batch(
	projects: list[ProjectSummary],
) -> dict[str, list[int]]:
	"""Use Claude to select best evidence for projects."""
	from claude_candidate.claude_cli import call_claude

	prompt = _build_project_batch_prompt(projects)
	response = call_claude(prompt, timeout=120)
	return _parse_project_batch_response(response, projects)


# ---------------------------------------------------------------------------
# Prompt building
# ---------------------------------------------------------------------------


def _format_evidence_list(evidence: list[SessionReference]) -> str:
	"""Format evidence entries for inclusion in a prompt."""
	lines = []
	for i, e in enumerate(evidence):
		lines.append(
			f"[{i}] date={e.session_date.strftime('%Y-%m-%d')} "
			f"project={e.project_context} type={e.evidence_type} "
			f"confidence={e.confidence:.2f} — {e.evidence_snippet}"
		)
	return "\n".join(lines)


def _build_skill_prompt(
	name: str, category: str, depth: str, evidence: list[SessionReference]
) -> str:
	"""Build prompt for single-skill evidence selection."""
	evidence_text = _format_evidence_list(evidence)
	return (
		"You are selecting the best evidence snippets for a candidate's skill profile.\n\n"
		f"Skill: {name}\n"
		f"Category: {category}\n"
		f"Depth: {depth}\n"
		f"Total evidence entries: {len(evidence)}\n\n"
		"Below are all evidence snippets for this skill. Each has an index, session date, "
		"project context, evidence type, and the snippet text.\n\n"
		f"{evidence_text}\n\n"
		f"Select the 3-5 BEST evidence entries by index. Criteria:\n"
		"1. Demonstrates depth — debugging, architecture decisions, teaching > simple usage\n"
		"2. Diversity of evidence types — pick from different types, not all direct_usage\n"
		"3. Diversity of projects — show breadth across different projects\n"
		"4. Recency — prefer recent evidence when quality is similar\n"
		'5. Specificity — concrete descriptions > generic "used X" statements\n\n'
		"Respond with ONLY a JSON object:\n"
		'{"selected_indices": [0, 42, 187], "reasoning": "Brief explanation"}'
	)


def _build_batch_skill_prompt(skills: list[SkillEntry]) -> str:
	"""Build prompt for batched skill evidence selection."""
	sections = []
	for skill in skills:
		evidence_text = _format_evidence_list(skill.evidence)
		sections.append(
			f"=== Skill: {skill.name} (category={skill.category}, "
			f"depth={skill.depth.value}, entries={len(skill.evidence)}) ===\n"
			f"{evidence_text}"
		)

	skills_text = "\n\n".join(sections)
	return (
		"You are selecting the best evidence snippets for multiple skills.\n\n"
		"For each skill below, select the 3-5 best evidence entries by index.\n"
		"Criteria:\n"
		"1. Demonstrates depth — debugging, architecture decisions, teaching > simple usage\n"
		"2. Diversity of evidence types — pick from different types\n"
		"3. Diversity of projects — show breadth\n"
		"4. Recency — prefer recent evidence when quality is similar\n"
		"5. Specificity — concrete descriptions > generic statements\n\n"
		f"{skills_text}\n\n"
		"Respond with ONLY a JSON object:\n"
		'{"skills": {"skill_name": {"selected_indices": [...], "reasoning": "..."}, ...}}'
	)


def _build_pattern_batch_prompt(patterns: list[ProblemSolvingPattern]) -> str:
	"""Build prompt for pattern evidence selection."""
	sections = []
	for pattern in patterns:
		evidence_text = _format_evidence_list(pattern.evidence)
		sections.append(
			f"=== Pattern: {pattern.pattern_type.value} "
			f"(frequency={pattern.frequency}, strength={pattern.strength}, "
			f"entries={len(pattern.evidence)}) ===\n"
			f"{evidence_text}"
		)

	patterns_text = "\n\n".join(sections)
	return (
		"You are selecting the best evidence snippets for problem-solving patterns.\n\n"
		"For each pattern below, select the 3-5 best evidence entries by index.\n"
		"Criteria:\n"
		"1. Demonstrates the pattern clearly — the snippet should show the pattern in action\n"
		"2. Diversity of contexts — show the pattern across different projects\n"
		"3. Strength of instance — prefer clear demonstrations over ambiguous cases\n\n"
		f"{patterns_text}\n\n"
		"Respond with ONLY a JSON object:\n"
		'{"patterns": {"pattern_type": {"selected_indices": [...], "reasoning": "..."}, ...}}'
	)


def _build_project_batch_prompt(projects: list[ProjectSummary]) -> str:
	"""Build prompt for project evidence selection."""
	sections = []
	for project in projects:
		evidence_text = _format_evidence_list(project.evidence)
		sections.append(
			f"=== Project: {project.project_name} "
			f"(complexity={project.complexity.value}, "
			f"entries={len(project.evidence)}) ===\n"
			f"{evidence_text}"
		)

	projects_text = "\n\n".join(sections)
	return (
		"You are selecting the best evidence snippets for project summaries.\n\n"
		"For each project below, select the 3-5 best evidence entries by index.\n"
		"Criteria:\n"
		"1. Shows the most significant contributions to the project\n"
		"2. Diversity of evidence types — architecture, debugging, testing\n"
		"3. Specificity — concrete descriptions of work done\n\n"
		f"{projects_text}\n\n"
		"Respond with ONLY a JSON object:\n"
		'{"projects": {"project_name": {"selected_indices": [...], "reasoning": "..."}, ...}}'
	)


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------


def _strip_json_fences(text: str) -> str:
	"""Strip markdown JSON fences if present."""
	text = text.strip()
	if text.startswith("```json"):
		text = text[len("```json") :]
	elif text.startswith("```"):
		text = text[len("```") :]
	if text.endswith("```"):
		text = text[: -len("```")]
	return text.strip()


def _parse_single_response(response: str, *, max_index: int) -> list[int]:
	"""Parse Claude's response for a single skill selection."""
	cleaned = _strip_json_fences(response)
	data = json.loads(cleaned)
	indices = data.get("selected_indices", [])
	valid = []
	for idx in indices:
		if isinstance(idx, int) and 0 <= idx <= max_index:
			valid.append(idx)
		else:
			logger.warning("Skipping out-of-range index: %s (max=%d)", idx, max_index)
	return valid


def _parse_batch_response(response: str, skills: list[SkillEntry]) -> dict[str, list[int]]:
	"""Parse Claude's response for a batch of skill selections."""
	cleaned = _strip_json_fences(response)
	data = json.loads(cleaned)
	skills_data = data.get("skills", {})

	result: dict[str, list[int]] = {}
	for skill in skills:
		skill_resp = skills_data.get(skill.name, None)
		if skill_resp is None:
			continue
		indices = skill_resp.get("selected_indices", [])
		max_index = len(skill.evidence) - 1
		valid = [idx for idx in indices if isinstance(idx, int) and 0 <= idx <= max_index]
		if valid:
			result[skill.name] = valid

	return result


def _parse_pattern_batch_response(
	response: str, patterns: list[ProblemSolvingPattern]
) -> dict[str, list[int]]:
	"""Parse Claude's response for pattern selections."""
	cleaned = _strip_json_fences(response)
	data = json.loads(cleaned)
	patterns_data = data.get("patterns", {})

	result: dict[str, list[int]] = {}
	for pattern in patterns:
		key = pattern.pattern_type.value
		pat_resp = patterns_data.get(key, None)
		if pat_resp is None:
			continue
		indices = pat_resp.get("selected_indices", [])
		max_index = len(pattern.evidence) - 1
		valid = [idx for idx in indices if isinstance(idx, int) and 0 <= idx <= max_index]
		if valid:
			result[key] = valid

	return result


def _parse_project_batch_response(
	response: str, projects: list[ProjectSummary]
) -> dict[str, list[int]]:
	"""Parse Claude's response for project selections."""
	cleaned = _strip_json_fences(response)
	data = json.loads(cleaned)
	projects_data = data.get("projects", {})

	result: dict[str, list[int]] = {}
	for project in projects:
		proj_resp = projects_data.get(project.project_name, None)
		if proj_resp is None:
			continue
		indices = proj_resp.get("selected_indices", [])
		max_index = len(project.evidence) - 1
		valid = [idx for idx in indices if isinstance(idx, int) and 0 <= idx <= max_index]
		if valid:
			result[project.project_name] = valid

	return result
