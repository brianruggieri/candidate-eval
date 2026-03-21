"""Export FitAssessment data as Hugo-compatible markdown for the fit landing page."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# Seniority prefixes in ascending order. Keep only the highest.
_SENIORITY_PREFIXES = [
	"junior", "jr", "jr.",
	"mid", "mid-level",
	"senior", "sr", "sr.",
	"staff",
	"principal",
	"distinguished",
]

_SENIORITY_MAP = {p: i for i, p in enumerate(_SENIORITY_PREFIXES)}

# Common title normalizations
_TITLE_REPLACEMENTS = {
	"engineering manager": "eng-manager",
	"engineering lead": "eng-lead",
	"full stack": "fullstack",
	"front end": "frontend",
	"front-end": "frontend",
	"back end": "backend",
	"back-end": "backend",
	"director of engineering": "director-engineering",
	"director of": "director",
	"vp of engineering": "vp-engineering",
	"vp of": "vp",
	"head of engineering": "head-engineering",
	"head of": "head",
}

_ROMAN_NUMERALS = {"i", "ii", "iii", "iv", "v", "vi"}

_FILLER_WORDS = {"in", "of", "the", "a", "an", "and", "for", "at", "to", "with"}

_ROLE_NOUNS = {
	"engineer", "developer", "architect", "manager", "lead", "director",
	"designer", "analyst", "scientist", "administrator", "consultant",
}


def generate_slug(title: str, company: str) -> str:
	"""Generate a tight, clean URL slug from job title + company name.

	Rules:
	- Strip seniority prefixes, keep only the highest-level one
	- Strip roman numeral suffixes (I, II, III, IV)
	- Apply common title normalizations (Engineering Manager → eng-manager)
	- Truncate to 2-3 core words
	- Append first word of company name
	- Lowercase, hyphenate
	"""
	title_lower = title.lower().strip()

	# Apply whole-phrase replacements first
	for phrase, replacement in _TITLE_REPLACEMENTS.items():
		if phrase in title_lower:
			title_lower = title_lower.replace(phrase, replacement)

	words = title_lower.split()

	# Strip roman numerals from end
	while words and words[-1] in _ROMAN_NUMERALS:
		words.pop()

	# Extract seniority prefixes
	highest_seniority: str | None = None
	highest_rank = -1
	remaining: list[str] = []

	for word in words:
		clean = word.rstrip(".")
		if clean in _SENIORITY_MAP:
			rank = _SENIORITY_MAP[clean]
			if rank > highest_rank:
				highest_seniority = clean.rstrip(".")
				highest_rank = rank
		else:
			remaining.append(word)

	# Remove filler words
	remaining = [w for w in remaining if w not in _FILLER_WORDS]

	# Build title part
	title_parts: list[str] = []
	keep_seniority = highest_seniority and highest_rank >= _SENIORITY_MAP.get("staff", 0)
	if keep_seniority:
		title_parts.append(highest_seniority)
		# With a seniority prefix, keep only the core role noun
		role_nouns = [w for w in remaining if w in _ROLE_NOUNS]
		if role_nouns:
			remaining = [role_nouns[-1]]
		elif remaining:
			remaining = [remaining[-1]]
	else:
		# Without seniority, truncate to 2 core words
		if len(remaining) > 2:
			remaining = remaining[:2]
	title_parts.extend(remaining)

	# Company: first word, strip special chars (split on non-alphanumeric for "Change.org")
	company_word = re.split(r"[^a-zA-Z0-9]", company.strip().split()[0])[0].lower()

	# Join and clean
	slug = "-".join(title_parts + [company_word])
	slug = re.sub(r"[^a-z0-9-]", "", slug)
	slug = re.sub(r"-+", "-", slug).strip("-")

	return slug


# ── Content Selection ──

_PRIORITY_ORDER = {"must_have": 0, "strong_preference": 1, "nice_to_have": 2, "implied": 3}
_STRENGTH_ORDER = {"exceptional": 0, "strong": 1, "established": 2, "emerging": 3}


def select_skill_matches(
	skill_matches: list[dict[str, Any]],
	*,
	limit: int = 10,
) -> list[dict[str, Any]]:
	"""Select top skill matches sorted by priority then confidence."""
	sorted_matches = sorted(
		skill_matches,
		key=lambda m: (
			_PRIORITY_ORDER.get(m.get("priority", "implied"), 99),
			-m.get("confidence", 0),
		),
	)
	return sorted_matches[:limit]


def select_gaps(
	skill_matches: list[dict[str, Any]],
	action_items: list[str] | None = None,
	*,
	limit: int = 3,
) -> list[dict[str, Any]]:
	"""Select gaps: must_have/strong_preference with no_evidence or adjacent status."""
	gap_statuses = {"no_evidence", "adjacent"}
	gap_priorities = {"must_have", "strong_preference"}
	action_items = action_items or []

	gaps = [
		m for m in skill_matches
		if m.get("match_status") in gap_statuses and m.get("priority") in gap_priorities
	]

	result = []
	for gap in gaps[:limit]:
		requirement = gap["requirement"]
		best_action = _match_action_item(requirement, action_items)
		result.append({
			"requirement": requirement,
			"status": gap.get("candidate_evidence", "No direct experience"),
			"action": best_action,
		})
	return result


def _match_action_item(requirement: str, action_items: list[str]) -> str:
	"""Find the action item most relevant to a requirement by keyword overlap."""
	if not action_items:
		return "Actively developing this skill"
	req_words = set(requirement.lower().split())
	best_match = action_items[0]
	best_score = 0
	for item in action_items:
		item_words = set(item.lower().split())
		overlap = len(req_words & item_words)
		if overlap > best_score:
			best_score = overlap
			best_match = item
	return best_match


def select_patterns(
	patterns: list[dict[str, Any]],
	*,
	limit: int = 5,
) -> list[dict[str, Any]]:
	"""Select top behavioral patterns sorted by strength."""
	sorted_patterns = sorted(
		patterns,
		key=lambda p: _STRENGTH_ORDER.get(p.get("strength", "emerging"), 99),
	)
	result = []
	for p in sorted_patterns[:limit]:
		name = p.get("pattern_type", p.get("name", "unknown"))
		result.append({
			"name": name.replace("_", " ").title(),
			"strength": p.get("strength", "emerging").capitalize(),
			"frequency": p.get("frequency", "unknown").capitalize(),
		})
	return result


def select_projects(
	projects: list[dict[str, Any]],
	job_technologies: list[str] | None = None,
	*,
	limit: int = 4,
) -> list[dict[str, Any]]:
	"""Select top projects, preferring technology overlap with job requirements."""
	job_techs = {t.lower() for t in (job_technologies or [])}

	def relevance(proj: dict) -> int:
		proj_techs = {t.lower() for t in proj.get("technologies", [])}
		return len(proj_techs & job_techs)

	sorted_projects = sorted(projects, key=relevance, reverse=True)

	result = []
	for proj in sorted_projects[:limit]:
		start = proj.get("date_range_start")
		end = proj.get("date_range_end")
		if start and end:
			start_year = str(start)[:4]
			end_year = str(end)[:4]
			date_range = start_year if start_year == end_year else f"{start_year} — {end_year}"
		elif start:
			date_range = str(start)[:4]
		else:
			date_range = ""

		result.append({
			"name": proj.get("project_name", proj.get("name", "Unknown")),
			"description": proj.get("description", ""),
			"complexity": proj.get("complexity", "moderate").capitalize(),
			"technologies": proj.get("technologies", []),
			"sessions": proj.get("session_count", 0),
			"date_range": date_range,
			"callout": (proj.get("key_decisions") or [""])[0],
		})
	return result


def select_evidence_highlights(
	skill_matches: list[dict[str, Any]],
	candidate_skills: list[dict[str, Any]],
	*,
	limit: int = 3,
) -> list[dict[str, Any]]:
	"""Select top evidence highlights from strong matches with session references.

	Args:
		skill_matches: SkillMatchDetail dicts from FitAssessment.
		candidate_skills: SkillEntry dicts from CandidateProfile (with evidence[]).
	"""
	# Build lookup from skill name to evidence list
	skill_evidence: dict[str, list[dict]] = {}
	for skill in candidate_skills:
		name = skill.get("name", "").lower()
		evidence = skill.get("evidence", [])
		if evidence:
			skill_evidence[name] = evidence

	# Prefer corroborated strong matches
	strong = [
		m for m in skill_matches
		if m.get("match_status") == "strong_match"
	]
	strong.sort(
		key=lambda m: (
			0 if m.get("evidence_source") == "corroborated" else 1,
			-m.get("confidence", 0),
		),
	)

	result = []
	for match in strong:
		if len(result) >= limit:
			break
		requirement = match["requirement"].lower()
		evidence_list = skill_evidence.get(requirement, [])
		if not evidence_list:
			continue

		# Pick highest-confidence session reference
		best = max(evidence_list, key=lambda e: e.get("confidence", 0))
		session_date = best.get("session_date", "")
		if session_date:
			from datetime import datetime
			try:
				dt = datetime.fromisoformat(str(session_date).replace("Z", "+00:00"))
				formatted_date = dt.strftime("%b %Y")
			except (ValueError, TypeError):
				formatted_date = str(session_date)[:7]
		else:
			formatted_date = ""

		result.append({
			"heading": match["requirement"].title(),
			"quote": best.get("evidence_snippet", ""),
			"project": best.get("project_context", ""),
			"date": formatted_date,
			"tags": [match["requirement"]],
		})

	return result


# ── YAML Front Matter Writer ──

_DEFAULT_CAL_LINK = "https://cal.com/brianruggieri/30min"


def write_fit_page(
	data: dict[str, Any],
	*,
	output_dir: Path,
	cal_link: str = _DEFAULT_CAL_LINK,
) -> Path:
	"""Write a Hugo-compatible markdown file with YAML front matter.

	Args:
		data: Dict containing all front matter fields.
		output_dir: Directory to write the markdown file to.
		cal_link: Default Cal.com booking link.

	Returns:
		Path to the written file.
	"""
	output_dir = Path(output_dir)
	if not output_dir.is_dir():
		raise FileNotFoundError(f"Output directory does not exist: {output_dir}")

	slug = data["slug"]
	front_matter = {
		"title": data["title"],
		"company": data["company"],
		"slug": slug,
		"description": data.get(
			"description",
			f"Evidence-backed fit assessment for {data['title']} at {data['company']}",
		),
		"date": data.get("date", _today_iso()),
		"public": data.get("public", False),
		"cal_link": data.get("cal_link", cal_link),
		"posting_url": data.get("posting_url"),
		"overall_grade": data["overall_grade"],
		"overall_score": data["overall_score"],
		"should_apply": data["should_apply"],
		"overall_summary": data["overall_summary"],
		"skill_matches": data.get("skill_matches", []),
		"evidence_highlights": data.get("evidence_highlights", []),
		"patterns": data.get("patterns", []),
		"projects": data.get("projects", []),
		"gaps": data.get("gaps", []),
	}

	yaml_str = yaml.dump(
		front_matter,
		default_flow_style=False,
		allow_unicode=True,
		sort_keys=False,
		width=120,
	)
	content = f"---\n{yaml_str}---\n"

	output_path = output_dir / f"{slug}.md"
	output_path.write_text(content, encoding="utf-8")
	return output_path


def _today_iso() -> str:
	from datetime import date
	return date.today().isoformat()
