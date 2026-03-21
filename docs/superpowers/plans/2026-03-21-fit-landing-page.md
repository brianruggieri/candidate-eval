# Fit Landing Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a per-company "cover letter replacement" landing page that renders evidence-backed fit assessments at `roojerry.com/fit/<slug>`, powered by a CLI export command in claude-candidate.

**Architecture:** Two independent repos. claude-candidate gets an `export-fit` CLI command that reads FitAssessment + MergedEvidenceProfile + CandidateProfile, generates a tight slug, selects top content, and writes a Hugo-compatible markdown file with YAML front matter. roojerry gets a standalone Hugo template (not extending baseof.html) that renders the markdown into a styled single-page assessment, plus a list page for public entries.

**Tech Stack:** Python 3.13 / Click / PyYAML / Pydantic (claude-candidate), Hugo / CSS custom properties / Saira Extra Condensed + Open Sans (roojerry)

**Spec:** `docs/superpowers/specs/2026-03-21-fit-landing-page-design.md`

---

## Part A: claude-candidate (CLI Export)

**Repo:** `/Users/brianruggieri/git/candidate-eval`
**Run tests with:** `.venv/bin/python -m pytest`

### Prerequisites

- [ ] **Add PyYAML dependency**

PyYAML is not currently in `pyproject.toml`. Add it before starting:

```bash
# Add to pyproject.toml dependencies array:
#   "pyyaml>=6.0",
# Then install:
.venv/bin/pip install -e ".[dev]"
```

### File Structure

| File | Purpose |
|------|---------|
| Modify: `pyproject.toml` | Add `pyyaml>=6.0` to dependencies |
| Create: `src/claude_candidate/fit_exporter.py` | Slug generation, content selection, YAML front matter writing |
| Modify: `src/claude_candidate/cli.py` | Add `export-fit` command |
| Create: `tests/test_fit_exporter.py` | Tests for slug generation, content selection, YAML output |

---

### Task A1: Slug Generation

**Files:**
- Create: `src/claude_candidate/fit_exporter.py`
- Create: `tests/test_fit_exporter.py`

- [ ] **Step 1: Write failing tests for slug generation**

```python
# tests/test_fit_exporter.py
from claude_candidate.fit_exporter import generate_slug


def test_basic_slug():
	assert generate_slug("Software Engineer", "Anthropic") == "software-engineer-anthropic"


def test_strips_senior_prefix():
	assert generate_slug("Senior Software Engineer", "Stripe") == "software-engineer-stripe"


def test_strips_sr_prefix():
	assert generate_slug("Sr. Backend Engineer", "Netflix") == "backend-engineer-netflix"


def test_keeps_highest_seniority():
	assert generate_slug("Sr. Staff Software Engineer", "Google") == "staff-engineer-google"


def test_strips_roman_numerals():
	assert generate_slug("Software Engineer III", "Meta") == "software-engineer-meta"


def test_truncates_long_title():
	assert generate_slug("Senior Staff Software Development Engineer in Test", "Amazon") == "staff-engineer-amazon"


def test_first_word_of_company():
	assert generate_slug("Staff Engineer", "Acme Corp Inc") == "staff-engineer-acme"


def test_lead_title():
	assert generate_slug("Engineering Manager", "Substack") == "eng-manager-substack"


def test_principal_title():
	assert generate_slug("Principal Engineer", "Adobe") == "principal-engineer-adobe"


def test_director_title():
	assert generate_slug("Director of Engineering", "NPR") == "director-engineering-npr"


def test_hyphenates_and_lowercases():
	assert generate_slug("Full Stack Developer", "Change.org") == "fullstack-developer-change"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_fit_exporter.py -v`
Expected: FAIL — `ImportError: cannot import name 'generate_slug'`

- [ ] **Step 3: Implement slug generation**

```python
# src/claude_candidate/fit_exporter.py
"""Export FitAssessment data as Hugo-compatible markdown for the fit landing page."""

from __future__ import annotations

import re

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

	# Truncate to 2 core words (the role essence)
	if len(remaining) > 2:
		remaining = remaining[:2]

	# Build title part
	title_parts: list[str] = []
	if highest_seniority:
		# Normalize jr/junior → skip (too low), keep staff/principal/distinguished
		if highest_rank >= _SENIORITY_MAP.get("staff", 0):
			title_parts.append(highest_seniority)
	title_parts.extend(remaining)

	# Company: first word, strip special chars
	company_word = company.strip().split()[0].lower()
	company_word = re.sub(r"[^a-z0-9]", "", company_word)

	# Join and clean
	slug = "-".join(title_parts + [company_word])
	slug = re.sub(r"[^a-z0-9-]", "", slug)
	slug = re.sub(r"-+", "-", slug).strip("-")

	return slug
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_fit_exporter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/fit_exporter.py tests/test_fit_exporter.py
git commit -m "Add slug generation for fit landing page export"
```

---

### Task A2: Content Selection

**Files:**
- Modify: `src/claude_candidate/fit_exporter.py`
- Modify: `tests/test_fit_exporter.py`

- [ ] **Step 1: Write failing tests for content selection**

```python
# Append to tests/test_fit_exporter.py
from claude_candidate.fit_exporter import select_skill_matches, select_evidence_highlights, select_patterns, select_projects, select_gaps


def _make_skill_match(requirement, priority, match_status, evidence_source="corroborated", confidence=0.8):
	"""Helper to create a SkillMatchDetail-like dict."""
	return {
		"requirement": requirement,
		"priority": priority,
		"match_status": match_status,
		"candidate_evidence": f"Experience with {requirement}",
		"evidence_source": evidence_source,
		"confidence": confidence,
	}


def test_select_skill_matches_limits_to_10():
	matches = [_make_skill_match(f"skill_{i}", "must_have", "strong_match") for i in range(15)]
	result = select_skill_matches(matches)
	assert len(result) <= 10


def test_select_skill_matches_sorts_by_priority():
	matches = [
		_make_skill_match("nice", "nice_to_have", "strong_match"),
		_make_skill_match("must", "must_have", "strong_match"),
		_make_skill_match("pref", "strong_preference", "strong_match"),
	]
	result = select_skill_matches(matches)
	assert result[0]["requirement"] == "must"
	assert result[1]["requirement"] == "pref"


def test_select_gaps_filters_correctly():
	matches = [
		_make_skill_match("Python", "must_have", "strong_match"),
		_make_skill_match("K8s", "must_have", "no_evidence"),
		_make_skill_match("Docker", "strong_preference", "adjacent"),
		_make_skill_match("Go", "nice_to_have", "no_evidence"),
	]
	result = select_gaps(matches)
	requirements = [g["requirement"] for g in result]
	assert "K8s" in requirements
	assert "Docker" in requirements
	assert "Python" not in requirements  # strong_match, not a gap
	assert "Go" not in requirements  # nice_to_have, not important enough


def test_select_gaps_limits_to_3():
	matches = [_make_skill_match(f"gap_{i}", "must_have", "no_evidence") for i in range(5)]
	result = select_gaps(matches)
	assert len(result) <= 3


def test_select_patterns_sorts_by_strength():
	patterns = [
		{"pattern_type": "testing_instinct", "strength": "established", "frequency": "common"},
		{"pattern_type": "architecture_first", "strength": "exceptional", "frequency": "dominant"},
		{"pattern_type": "iterative_refinement", "strength": "strong", "frequency": "common"},
	]
	result = select_patterns(patterns)
	assert result[0]["name"] == "Architecture First"
	assert result[1]["name"] == "Iterative Refinement"


def test_select_patterns_limits_to_5():
	patterns = [{"pattern_type": f"pattern_{i}", "strength": "strong", "frequency": "common"} for i in range(8)]
	result = select_patterns(patterns)
	assert len(result) <= 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_fit_exporter.py -v -k "select"`
Expected: FAIL — `ImportError: cannot import name 'select_skill_matches'`

- [ ] **Step 3: Implement content selection functions**

Add to `src/claude_candidate/fit_exporter.py`:

```python
from __future__ import annotations

from typing import Any

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
		# Find best matching action item by keyword overlap
		requirement = gap["requirement"]
		best_action = _match_action_item(requirement, action_items)
		result.append({
			"requirement": requirement.title(),
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
		# Format date range
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_fit_exporter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/fit_exporter.py tests/test_fit_exporter.py
git commit -m "Add content selection functions for fit page export"
```

---

### Task A3: YAML Front Matter Writer

**Files:**
- Modify: `src/claude_candidate/fit_exporter.py`
- Modify: `tests/test_fit_exporter.py`

- [ ] **Step 1: Write failing tests for YAML output**

```python
# Append to tests/test_fit_exporter.py
import yaml
from pathlib import Path
from claude_candidate.fit_exporter import write_fit_page


def test_write_fit_page_creates_file(tmp_path):
	data = {
		"title": "Staff Engineer",
		"company": "Anthropic",
		"slug": "staff-engineer-anthropic",
		"description": "Evidence-backed fit assessment for Staff Engineer at Anthropic",
		"overall_grade": "A+",
		"overall_score": 0.97,
		"should_apply": "strong_yes",
		"overall_summary": "Exceptional fit.",
		"skill_matches": [],
		"evidence_highlights": [],
		"patterns": [],
		"projects": [],
		"gaps": [],
	}
	result = write_fit_page(data, output_dir=tmp_path)
	assert result.exists()
	assert result.name == "staff-engineer-anthropic.md"


def test_write_fit_page_valid_yaml(tmp_path):
	data = {
		"title": "Staff Engineer",
		"company": "Anthropic",
		"slug": "staff-engineer-anthropic",
		"description": "Test",
		"overall_grade": "A+",
		"overall_score": 0.97,
		"should_apply": "strong_yes",
		"overall_summary": "Great fit.",
		"skill_matches": [
			{"skill": "Python", "status": "strong_match", "priority": "must_have",
			 "depth": "Expert", "sessions": 551, "source": "corroborated", "discovery": False},
		],
		"evidence_highlights": [],
		"patterns": [{"name": "Architecture First", "strength": "Exceptional", "frequency": "Dominant"}],
		"projects": [],
		"gaps": [],
	}
	result = write_fit_page(data, output_dir=tmp_path)
	content = result.read_text()

	# Verify YAML front matter is valid
	assert content.startswith("---\n")
	parts = content.split("---\n", 2)
	assert len(parts) >= 3  # before ---, yaml content, after ---
	parsed = yaml.safe_load(parts[1])
	assert parsed["title"] == "Staff Engineer"
	assert parsed["company"] == "Anthropic"
	assert parsed["overall_grade"] == "A+"
	assert len(parsed["skill_matches"]) == 1
	assert parsed["skill_matches"][0]["skill"] == "Python"


def test_write_fit_page_defaults(tmp_path):
	data = {
		"title": "Engineer",
		"company": "Test",
		"slug": "engineer-test",
		"description": "Test",
		"overall_grade": "B+",
		"overall_score": 0.80,
		"should_apply": "yes",
		"overall_summary": "Solid fit.",
		"skill_matches": [],
		"evidence_highlights": [],
		"patterns": [],
		"projects": [],
		"gaps": [],
	}
	result = write_fit_page(data, output_dir=tmp_path)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert parsed["public"] is False
	assert "cal_link" in parsed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_fit_exporter.py -v -k "write_fit"`
Expected: FAIL — `ImportError: cannot import name 'write_fit_page'`

- [ ] **Step 3: Implement YAML writer**

Add to `src/claude_candidate/fit_exporter.py`:

```python
from pathlib import Path

import yaml


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
		"description": data.get("description", f"Evidence-backed fit assessment for {data['title']} at {data['company']}"),
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

	# Write YAML front matter with --- delimiters
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_fit_exporter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/fit_exporter.py tests/test_fit_exporter.py
git commit -m "Add YAML front matter writer for fit page export"
```

---

### Task A4: CLI Command Integration

**Files:**
- Modify: `src/claude_candidate/cli.py`
- Modify: `src/claude_candidate/fit_exporter.py`
- Modify: `tests/test_fit_exporter.py`

- [ ] **Step 1: Write the export orchestrator function**

Add to `src/claude_candidate/fit_exporter.py`:

```python
import json


def export_fit_assessment(
	assessment_data: dict[str, Any],
	merged_profile_path: Path,
	candidate_profile_path: Path,
	output_dir: Path,
	*,
	cal_link: str = _DEFAULT_CAL_LINK,
) -> Path:
	"""Full export pipeline: load data, select content, write Hugo markdown.

	Args:
		assessment_data: Assessment dict from storage. The 'data' field contains the
			full FitAssessment payload — already parsed as a dict by storage._decode_assessment().
		merged_profile_path: Path to merged_profile.json.
		candidate_profile_path: Path to candidate_profile.json.
		output_dir: Directory to write the markdown file.
		cal_link: Cal.com booking link.

	Returns:
		Path to the written file.
	"""
	# Extract the nested assessment payload.
	# storage.get_assessment() returns a row dict where 'data' is already JSON-parsed
	# by _decode_assessment(). The 'data' dict contains the full FitAssessment fields
	# (job_title, company_name, skill_matches, etc.).
	# Note: top-level fields like 'should_apply' are coerced to bool by storage —
	# always read from the nested 'data' dict to get the original string values.
	raw_data = assessment_data.get("data", {})
	if isinstance(raw_data, str):
		full_data = json.loads(raw_data)
	else:
		full_data = raw_data

	# Load profiles
	merged_profile = json.loads(merged_profile_path.read_text())
	candidate_profile = json.loads(candidate_profile_path.read_text())

	# Extract fields
	title = full_data.get("job_title", "Engineer")
	company = full_data.get("company_name", "Unknown")
	slug = generate_slug(title, company)

	skill_matches_raw = full_data.get("skill_matches", [])
	action_items = full_data.get("action_items", [])

	# Build merged skill lookup for depth/sessions/discovery
	merged_skills = {s["name"].lower(): s for s in merged_profile.get("skills", [])}

	# Select and enrich skill matches
	selected_matches = select_skill_matches(skill_matches_raw)
	enriched_matches = []
	for match in selected_matches:
		req = match["requirement"]
		merged = merged_skills.get(req.lower(), {})
		enriched_matches.append({
			"skill": req,
			"status": match.get("match_status", "no_evidence"),
			"priority": match.get("priority", "implied"),
			"depth": (merged.get("effective_depth") or "Unknown").replace("_", " ").title(),
			"sessions": merged.get("session_evidence_count", 0),
			"source": str(match.get("evidence_source", "resume_only")),
			"discovery": bool(merged.get("discovery_flag", False)),
		})

	# Select other content
	evidence = select_evidence_highlights(
		skill_matches_raw,
		candidate_profile.get("skills", []),
	)
	patterns = select_patterns(merged_profile.get("patterns", []))

	# Collect tech stack from job for project relevance
	job_techs = []
	for m in skill_matches_raw:
		job_techs.append(m.get("requirement", ""))

	projects = select_projects(merged_profile.get("projects", []), job_techs)
	gaps = select_gaps(skill_matches_raw, action_items)

	# Assemble front matter data
	page_data = {
		"title": title,
		"company": company,
		"slug": slug,
		"description": f"Evidence-backed fit assessment for {title} at {company}",
		"posting_url": full_data.get("posting_url"),
		"overall_grade": full_data.get("overall_grade", "?"),
		"overall_score": full_data.get("overall_score", 0.0),
		"should_apply": full_data.get("should_apply", "maybe"),
		"overall_summary": full_data.get("overall_summary", ""),
		"skill_matches": enriched_matches,
		"evidence_highlights": evidence,
		"patterns": patterns,
		"projects": projects,
		"gaps": gaps,
	}

	return write_fit_page(page_data, output_dir=output_dir, cal_link=cal_link)
```

- [ ] **Step 2: Add export-fit CLI command**

Add to `src/claude_candidate/cli.py` (after existing commands, following the pattern of `generate` or `proof`):

```python
@main.command("export-fit")
@click.argument("assessment_id")
@click.option(
	"--output-dir", "-o",
	type=click.Path(exists=True, file_okay=False),
	required=True,
	help="Directory to write the Hugo markdown file (e.g., ../roojerry/content/fit/)",
)
@click.option(
	"--db",
	type=click.Path(),
	default=None,
	help="Path to assessments.db (default: ~/.claude-candidate/assessments.db)",
)
@click.option(
	"--cal-link",
	default="https://cal.com/brianruggieri/30min",
	help="Cal.com booking link for the CTA button.",
)
def export_fit(assessment_id: str, output_dir: str, db: str | None, cal_link: str) -> None:
	"""Export a FitAssessment as a Hugo markdown file for the fit landing page."""
	import asyncio
	from pathlib import Path
	from claude_candidate.fit_exporter import export_fit_assessment
	from claude_candidate.storage import AssessmentStore

	data_dir = Path.home() / ".claude-candidate"
	db_path = Path(db) if db else data_dir / "assessments.db"
	merged_path = data_dir / "merged_profile.json"
	candidate_path = data_dir / "candidate_profile.json"

	# Validate paths
	if not db_path.exists():
		click.echo(f"Error: Database not found at {db_path}", err=True)
		raise SystemExit(1)
	if not merged_path.exists():
		click.echo(f"Error: Merged profile not found at {merged_path}", err=True)
		raise SystemExit(1)
	if not candidate_path.exists():
		click.echo(f"Error: Candidate profile not found at {candidate_path}", err=True)
		raise SystemExit(1)

	# Load assessment from DB
	async def _load():
		store = AssessmentStore(db_path)
		await store.initialize()
		try:
			return await store.get_assessment(assessment_id)
		finally:
			await store.close()

	assessment = asyncio.run(_load())
	if not assessment:
		click.echo(f"Error: Assessment '{assessment_id}' not found.", err=True)
		raise SystemExit(1)

	# Export
	result_path = export_fit_assessment(
		assessment,
		merged_profile_path=merged_path,
		candidate_profile_path=candidate_path,
		output_dir=Path(output_dir),
		cal_link=cal_link,
	)

	slug = result_path.stem
	click.echo(f"Exported: {result_path}")
	click.echo(f"URL:      roojerry.com/fit/{slug}")
```

- [ ] **Step 3: Write integration test**

```python
# Append to tests/test_fit_exporter.py
import json


def test_export_fit_assessment_end_to_end(tmp_path):
	"""Integration test: full export pipeline with mock data files."""
	from claude_candidate.fit_exporter import export_fit_assessment

	# Create mock merged profile
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "corroborated",
				"effective_depth": "EXPERT",
				"session_evidence_count": 551,
				"discovery_flag": False,
				"confidence": 0.95,
			},
			{
				"name": "react",
				"source": "sessions_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 229,
				"discovery_flag": True,
				"confidence": 0.8,
			},
		],
		"patterns": [
			{"pattern_type": "architecture_first", "strength": "exceptional", "frequency": "dominant"},
			{"pattern_type": "testing_instinct", "strength": "strong", "frequency": "common"},
		],
		"projects": [
			{
				"project_name": "claude-candidate",
				"description": "Evidence-backed job fit engine",
				"complexity": "ambitious",
				"technologies": ["Python", "FastAPI"],
				"session_count": 42,
				"date_range_start": "2026-01-01",
				"date_range_end": "2026-03-20",
				"key_decisions": ["Designed fuzzy skill taxonomy"],
			},
		],
	}
	merged_path = tmp_path / "merged_profile.json"
	merged_path.write_text(json.dumps(merged))

	# Create mock candidate profile
	candidate = {
		"skills": [
			{
				"name": "python",
				"evidence": [
					{
						"session_id": "test-session",
						"session_date": "2026-03-01T00:00:00",
						"project_context": "claude-candidate",
						"evidence_snippet": "Built async pipeline with aiosqlite",
						"evidence_type": "direct_usage",
						"confidence": 0.95,
					},
				],
			},
		],
	}
	candidate_path = tmp_path / "candidate_profile.json"
	candidate_path.write_text(json.dumps(candidate))

	# Create mock assessment data matching what storage.get_assessment() returns.
	# IMPORTANT: storage._decode_assessment() already JSON-parses the 'data' field,
	# so 'data' is a dict here, NOT a JSON string. Top-level 'should_apply' is
	# coerced to bool by storage, but the nested data dict has the original string.
	assessment = {
		"assessment_id": "test-123",
		"should_apply": True,  # coerced by storage layer
		"data": {
			"job_title": "Staff Engineer",
			"company_name": "Anthropic",
			"posting_url": "https://example.com/jobs/123",
			"overall_grade": "A+",
			"overall_score": 0.97,
			"should_apply": "strong_yes",  # original string in nested data
			"overall_summary": "Exceptional fit.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Expert Python developer",
					"evidence_source": "corroborated",
					"confidence": 0.95,
				},
				{
					"requirement": "kubernetes",
					"priority": "must_have",
					"match_status": "no_evidence",
					"candidate_evidence": "Adjacent experience with Docker",
					"evidence_source": "resume_only",
					"confidence": 0.1,
				},
			],
			"action_items": ["Learn Kubernetes for container orchestration"],
		},
	}

	output_dir = tmp_path / "content" / "fit"
	output_dir.mkdir(parents=True)

	result = export_fit_assessment(
		assessment,
		merged_profile_path=merged_path,
		candidate_profile_path=candidate_path,
		output_dir=output_dir,
	)

	assert result.exists()
	assert result.name == "staff-engineer-anthropic.md"

	content = result.read_text()
	parsed = yaml.safe_load(content.split("---\n", 2)[1])
	assert parsed["overall_grade"] == "A+"
	assert parsed["company"] == "Anthropic"
	assert len(parsed["skill_matches"]) >= 1
	assert parsed["skill_matches"][0]["skill"] == "python"
	assert len(parsed["gaps"]) >= 1
	assert parsed["gaps"][0]["requirement"] == "Kubernetes"
```

- [ ] **Step 4: Run all tests**

Run: `.venv/bin/python -m pytest tests/test_fit_exporter.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/fit_exporter.py src/claude_candidate/cli.py tests/test_fit_exporter.py
git commit -m "Add export-fit CLI command with full pipeline integration"
```

---

## Part B: roojerry (Hugo Template + Rendering)

**Repo:** `/Users/brianruggieri/git/roojerry`
**Run with:** `npm run dev` (Hugo dev server)

### File Structure

| File | Purpose |
|------|---------|
| Create: `content/fit/_index.md` | Section landing page config |
| Create: `static/css/fit.css` | Fit-specific styles (standalone, imports design-system.css vars) |
| Create: `layouts/fit/single.html` | Standalone template for individual fit pages |
| Create: `layouts/fit/list.html` | Public assessment index |
| Create: `static/robots.txt` | Disallow /fit/ for crawlers |

---

### Task B1: Content Directory and Robots

**Files:**
- Create: `content/fit/_index.md`
- Create: `static/robots.txt`

- [ ] **Step 1: Create section index**

```markdown
<!-- content/fit/_index.md -->
---
title: "Fit Assessments"
description: "Evidence-backed job fit assessments by Brian Ruggieri"
---
```

- [ ] **Step 2: Create robots.txt**

```
# static/robots.txt
User-agent: *
Disallow: /fit/

Sitemap: https://www.roojerry.com/sitemap.xml
```

- [ ] **Step 3: Commit**

```bash
git add content/fit/_index.md static/robots.txt
git commit -m "Add fit content section and robots.txt"
```

---

### Task B2: Fit CSS

**Files:**
- Create: `static/css/fit.css`

- [ ] **Step 1: Create fit.css with all fit-specific styles**

This file is standalone — it does NOT import design-system.css via `@import` (the standalone HTML template links both files separately). It references the same CSS custom property names defined in `design-system.css`.

```css
/* static/css/fit.css */

/* ── New tokens (not in design-system.css) ── */
:root {
	--color-slate: #64748B;
	--color-slate-rgb: 100 116 139;
}

/* ── Status colors mapped to match_status ── */
.status-strong_match  { --status-color: var(--accent); }
.status-exceeds       { --status-color: var(--brand); }
.status-partial_match { --status-color: var(--status-amber); }
.status-adjacent      { --status-color: var(--cyan); }
.status-gap,
.status-no_evidence   { --status-color: var(--color-slate); }

/* ── Layout ── */
.fit-page {
	max-width: 1200px;
	margin: 0 auto;
	padding: 0 1.5rem;
}

.fit-section {
	margin-bottom: 5rem;
}

/* ── Sticky Nav ── */
.fit-nav {
	position: fixed;
	top: 0;
	left: 0;
	right: 0;
	z-index: 50;
	height: 4rem;
	background: rgba(45, 74, 82, 0.85);
	backdrop-filter: blur(12px);
	-webkit-backdrop-filter: blur(12px);
	border-bottom: 1px solid rgba(139, 186, 193, 0.3);
}

.fit-nav__inner {
	max-width: 1200px;
	margin: 0 auto;
	padding: 0 1.5rem;
	height: 100%;
	display: flex;
	align-items: center;
	justify-content: space-between;
}

.fit-nav__brand {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 1.2rem;
	color: white;
	text-decoration: none;
	text-transform: uppercase;
	letter-spacing: 0.02em;
}

.fit-nav__links {
	display: flex;
	gap: 2rem;
	list-style: none;
	margin: 0;
	padding: 0;
}

.fit-nav__links a {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 600;
	font-size: 0.85rem;
	color: rgba(255, 255, 255, 0.7);
	text-decoration: none;
	text-transform: uppercase;
	letter-spacing: 0.08em;
	transition: color 0.15s ease;
}

.fit-nav__links a:hover,
.fit-nav__links a:focus {
	color: white;
	outline: none;
}

.fit-nav__links a:focus-visible {
	outline: 2px solid var(--accent);
	outline-offset: 2px;
}

.fit-nav__cta {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 0.75rem;
	text-transform: uppercase;
	letter-spacing: 0.1em;
	color: white;
	background: var(--brand);
	border: none;
	padding: 0.5rem 1.25rem;
	border-radius: var(--radius-lg);
	cursor: pointer;
	text-decoration: none;
	transition: background 0.15s ease, transform 0.15s ease;
}

.fit-nav__cta:hover {
	background: var(--accent);
}

.fit-nav__cta:active {
	transform: scale(0.98);
}

/* ── Hero ── */
.fit-hero {
	display: grid;
	grid-template-columns: 1fr auto;
	gap: 3rem;
	align-items: center;
	padding-top: 8rem;
}

.fit-hero__context {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 600;
	font-size: 0.65rem;
	text-transform: uppercase;
	letter-spacing: 0.15em;
	color: var(--muted);
	display: flex;
	align-items: center;
	gap: 0.5rem;
	margin-bottom: 1.5rem;
}

.fit-hero__context-dot {
	width: 6px;
	height: 6px;
	border-radius: 50%;
	background: var(--accent);
	animation: status-pulse 2.4s ease-in-out infinite;
}

.fit-hero__heading {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: clamp(2.5rem, 5vw, 4rem);
	line-height: 1.1;
	color: var(--brand-dark);
	text-transform: uppercase;
	margin: 0 0 1.5rem;
}

.fit-hero__summary {
	font-family: 'Open Sans', sans-serif;
	font-size: 1.1rem;
	line-height: 1.7;
	color: var(--muted);
	max-width: 38rem;
	margin-bottom: 2rem;
}

.fit-hero__stats {
	display: flex;
	gap: 2rem;
	align-items: center;
}

.fit-hero__stat-label {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 600;
	font-size: 0.6rem;
	text-transform: uppercase;
	letter-spacing: 0.12em;
	color: var(--muted);
	margin-bottom: 0.25rem;
}

.fit-hero__stat-value {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 1.1rem;
	color: var(--brand);
}

.fit-hero__divider {
	width: 1px;
	height: 2.5rem;
	background: rgba(var(--shadow-tint-rgb) / 0.14);
}

/* ── Grade Badge ── */
.fit-grade {
	width: 16rem;
	height: 16rem;
	border-radius: 50%;
	display: flex;
	flex-direction: column;
	align-items: center;
	justify-content: center;
	position: relative;
	flex-shrink: 0;
}

.fit-grade__ring {
	position: absolute;
	inset: 0;
	border-radius: 50%;
	border: 12px solid var(--bg-mid);
}

.fit-grade__ring--fill {
	position: absolute;
	inset: 0;
	border-radius: 50%;
	border: 12px solid var(--grade-color, var(--accent));
	clip-path: polygon(50% 50%, 50% 0%, 100% 0%, 100% 100%, 0% 100%, 0% 0%, 50% 0%);
}

.fit-grade--a { --grade-color: var(--accent); }
.fit-grade--b { --grade-color: var(--status-amber); }
.fit-grade--c,
.fit-grade--d,
.fit-grade--f { --grade-color: var(--color-slate); }

.fit-grade__letter {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 5rem;
	line-height: 1;
	color: var(--brand);
	position: relative;
	z-index: 1;
}

.fit-grade__label {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 600;
	font-size: 0.65rem;
	text-transform: uppercase;
	letter-spacing: 0.12em;
	color: var(--muted);
	position: relative;
	z-index: 1;
}

/* ── Section Headings ── */
.fit-section__title {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 2rem;
	color: var(--brand-dark);
	text-transform: uppercase;
	margin: 0 0 0.5rem;
}

.fit-section__subtitle {
	font-family: 'Open Sans', sans-serif;
	font-size: 0.85rem;
	color: var(--muted);
	margin: 0 0 2rem;
}

/* ── Skill Cards ── */
.fit-skills-grid {
	display: grid;
	grid-template-columns: repeat(3, 1fr);
	gap: 1.25rem;
}

.fit-skill-card {
	background: rgb(255 255 255 / 0.45);
	border: 1px solid rgba(var(--shadow-tint-rgb) / 0.14);
	border-left: 3px solid var(--status-color, var(--muted));
	border-radius: var(--radius-lg);
	padding: 1.75rem 2rem;
	box-shadow: var(--shadow-card);
	transition: transform 0.25s ease, box-shadow 0.25s ease;
}

.fit-skill-card:hover {
	transform: translateY(-4px);
	box-shadow: var(--shadow-card-hover);
}

.fit-skill-card__header {
	display: flex;
	justify-content: space-between;
	align-items: flex-start;
	margin-bottom: 1.25rem;
}

.fit-skill-card__name {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 1.15rem;
	color: var(--brand-dark);
	text-transform: uppercase;
}

.fit-skill-card__status {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 600;
	font-size: 0.6rem;
	text-transform: uppercase;
	letter-spacing: 0.05em;
	color: white;
	background: var(--status-color, var(--muted));
	padding: 0.2rem 0.6rem;
	border-radius: 90px;
	white-space: nowrap;
}

.fit-skill-card__row {
	display: flex;
	justify-content: space-between;
	align-items: center;
	font-size: 0.78rem;
	padding: 0.35rem 0;
}

.fit-skill-card__row-label {
	color: var(--muted);
	font-family: 'Open Sans', sans-serif;
}

.fit-skill-card__row-value {
	font-family: 'Open Sans', sans-serif;
	font-weight: 600;
	color: var(--brand-dark);
}

.fit-skill-card__discovery {
	margin-top: 0.75rem;
	font-family: 'Open Sans', sans-serif;
	font-size: 0.7rem;
	color: var(--brand);
	font-style: italic;
}

/* ── Evidence Cards ── */
.fit-evidence-card {
	background: rgb(255 255 255 / 0.45);
	border: 1px solid rgba(var(--shadow-tint-rgb) / 0.14);
	border-radius: var(--radius-lg);
	padding: 2.5rem;
	box-shadow: var(--shadow-card);
	margin-bottom: 1.5rem;
	display: flex;
	gap: 2.5rem;
}

.fit-evidence-card__meta {
	flex-shrink: 0;
	width: 12rem;
}

.fit-evidence-card__heading {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 0.7rem;
	text-transform: uppercase;
	letter-spacing: 0.1em;
	color: var(--muted);
	margin-bottom: 0.5rem;
}

.fit-evidence-card__date {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 600;
	font-size: 0.65rem;
	color: var(--muted);
}

.fit-evidence-card__quote {
	font-family: 'Open Sans', sans-serif;
	font-size: 1.25rem;
	font-style: italic;
	line-height: 1.5;
	color: var(--brand-dark);
	margin: 0 0 1rem;
}

.fit-evidence-card__project {
	font-family: 'Open Sans', sans-serif;
	font-size: 0.82rem;
	color: var(--muted);
}

/* ── Tags (teardrop style matching existing) ── */
.fit-tag {
	display: inline-block;
	background: var(--cyan);
	color: white;
	height: 26px;
	line-height: 26px;
	padding: 0 20px 0 23px;
	border-radius: 3px 0 90px 3px;
	font-family: 'Open Sans', sans-serif;
	font-size: 0.7rem;
	font-weight: 600;
	position: relative;
	margin: 0 0.5rem 0.5rem 0;
}

.fit-tag::before {
	content: "";
	position: absolute;
	left: 10px;
	top: 50%;
	transform: translateY(-50%);
	width: 6px;
	height: 6px;
	border-radius: 50%;
	background: white;
}

/* ── Patterns Row ── */
.fit-patterns-grid {
	display: grid;
	grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
	gap: 1rem;
}

.fit-pattern-card {
	background: rgb(255 255 255 / 0.45);
	border: 1px solid rgba(var(--shadow-tint-rgb) / 0.14);
	border-radius: var(--radius-lg);
	padding: 1.5rem;
	text-align: center;
	box-shadow: var(--shadow-card);
	transition: transform 0.25s ease, box-shadow 0.25s ease;
}

.fit-pattern-card:hover {
	transform: translateY(-4px);
	box-shadow: var(--shadow-card-hover);
}

.fit-pattern-card__name {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 0.65rem;
	text-transform: uppercase;
	letter-spacing: 0.1em;
	color: var(--muted);
	margin-bottom: 0.75rem;
}

.fit-pattern-card__strength {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 1.5rem;
	color: var(--brand-dark);
}

.fit-pattern-card__frequency {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 600;
	font-size: 0.6rem;
	text-transform: uppercase;
	color: var(--brand);
}

/* ── Projects Timeline ── */
.fit-timeline {
	border-left: 2px solid rgba(var(--shadow-tint-rgb) / 0.14);
	padding-left: 2rem;
	margin-left: 0.5rem;
}

.fit-project {
	position: relative;
	margin-bottom: 3rem;
}

.fit-project__dot {
	position: absolute;
	left: calc(-2rem - 9px);
	top: 0;
	width: 16px;
	height: 16px;
	border-radius: 50%;
	background: var(--brand);
	border: 4px solid var(--bg-off);
}

.fit-project__date {
	font-family: 'Open Sans', sans-serif;
	font-size: 0.78rem;
	font-variant-numeric: tabular-nums;
	color: var(--muted);
	margin-bottom: 0.5rem;
}

.fit-project__name {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 1.5rem;
	color: var(--brand-dark);
	text-transform: uppercase;
	margin-bottom: 0.75rem;
}

.fit-project__techs {
	display: flex;
	flex-wrap: wrap;
	gap: 0.35rem;
	margin-bottom: 1rem;
}

.fit-project__tech {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 600;
	font-size: 0.63rem;
	text-transform: uppercase;
	background: var(--bg-mid);
	color: var(--brand-dark);
	padding: 0.15rem 0.5rem;
	border-radius: var(--radius-sm);
}

.fit-project__body {
	background: rgb(255 255 255 / 0.45);
	border: 1px solid rgba(var(--shadow-tint-rgb) / 0.14);
	border-radius: var(--radius-lg);
	padding: 2rem;
	box-shadow: var(--shadow-card);
}

.fit-project__desc {
	font-family: 'Open Sans', sans-serif;
	font-size: 0.92rem;
	line-height: 1.7;
	color: var(--muted);
	margin-bottom: 1.25rem;
}

.fit-project__callout {
	background: rgba(var(--accent-rgb) / 0.05);
	border-left: 4px solid var(--accent);
	padding: 1.25rem 1.5rem;
	border-radius: 0 var(--radius-md) var(--radius-md) 0;
}

.fit-project__callout-label {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 0.6rem;
	text-transform: uppercase;
	letter-spacing: 0.1em;
	color: var(--accent);
	margin-bottom: 0.35rem;
}

.fit-project__callout-text {
	font-family: 'Open Sans', sans-serif;
	font-size: 0.85rem;
	font-style: italic;
	line-height: 1.6;
	color: var(--brand-dark);
}

/* ── Gap Section ── */
.fit-gaps {
	background: var(--bg-mid);
	border-radius: var(--radius-lg);
	padding: 4rem 5rem;
	position: relative;
	overflow: hidden;
}

.fit-gaps__icon {
	position: absolute;
	top: 2rem;
	right: 3rem;
	font-size: 8rem;
	opacity: 0.06;
	color: var(--brand-dark);
}

.fit-gap-card {
	background: rgb(255 255 255 / 0.65);
	border: 1px solid rgba(var(--shadow-tint-rgb) / 0.10);
	border-radius: var(--radius-lg);
	padding: 2rem;
	box-shadow: var(--shadow-card);
	margin-bottom: 1.25rem;
}

.fit-gap-card__header {
	display: flex;
	justify-content: space-between;
	align-items: center;
	flex-wrap: wrap;
	gap: 1rem;
	margin-bottom: 1.5rem;
}

.fit-gap-card__requirement {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 1.25rem;
	color: var(--brand-dark);
	text-transform: uppercase;
}

.fit-gap-card__status-tag {
	font-family: 'Open Sans', sans-serif;
	font-size: 0.75rem;
	font-style: italic;
	color: var(--color-slate);
	background: rgba(var(--color-slate-rgb) / 0.08);
	padding: 0.3rem 0.75rem;
	border-radius: var(--radius-md);
	border: 1px solid rgba(var(--color-slate-rgb) / 0.15);
}

.fit-gap-card__action {
	display: flex;
	align-items: center;
	gap: 0.75rem;
	padding-top: 1.5rem;
	border-top: 1px solid rgba(var(--shadow-tint-rgb) / 0.08);
}

.fit-gap-card__action-label {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 0.6rem;
	text-transform: uppercase;
	letter-spacing: 0.08em;
	color: var(--muted);
}

.fit-gap-card__action-text {
	font-family: 'Open Sans', sans-serif;
	font-size: 0.85rem;
	font-weight: 600;
	color: var(--brand-dark);
}

/* ── Footer ── */
.fit-footer {
	background: var(--bg-off);
	border-top: 1px solid rgba(var(--shadow-tint-rgb) / 0.10);
	padding: 4rem 1.5rem;
	text-align: center;
}

.fit-footer__cta {
	display: inline-block;
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 700;
	font-size: 0.85rem;
	text-transform: uppercase;
	letter-spacing: 0.08em;
	color: white;
	background: var(--brand);
	padding: 1rem 2.5rem;
	border-radius: var(--radius-lg);
	text-decoration: none;
	box-shadow: 0 4px 12px rgba(var(--brand-rgb) / 0.3);
	transition: background 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
}

.fit-footer__cta:hover {
	background: var(--accent);
	box-shadow: 0 6px 20px rgba(var(--accent-rgb) / 0.3);
}

.fit-footer__cta:active {
	transform: scale(0.98);
}

.fit-footer__links {
	display: flex;
	justify-content: center;
	gap: 2rem;
	margin-top: 2rem;
	list-style: none;
	padding: 0;
}

.fit-footer__links a {
	font-family: 'Saira Extra Condensed', sans-serif;
	font-weight: 600;
	font-size: 0.7rem;
	text-transform: uppercase;
	letter-spacing: 0.12em;
	color: var(--muted);
	text-decoration: none;
	transition: color 0.15s ease;
}

.fit-footer__links a:hover {
	color: var(--brand);
}

.fit-footer__credit {
	font-family: 'Open Sans', sans-serif;
	font-size: 0.65rem;
	color: var(--muted);
	margin-top: 1.5rem;
}

/* ── Responsive ── */
@media (max-width: 991px) {
	.fit-nav__links { display: none; }
	.fit-hero { grid-template-columns: 1fr; text-align: center; }
	.fit-hero__summary { margin-left: auto; margin-right: auto; }
	.fit-hero__stats { justify-content: center; }
	.fit-grade { margin: 0 auto 2rem; width: 12rem; height: 12rem; }
	.fit-grade__letter { font-size: 3.5rem; }
	.fit-skills-grid { grid-template-columns: repeat(2, 1fr); }
	.fit-gaps { padding: 3rem 2rem; }
}

@media (max-width: 767px) {
	.fit-skills-grid { grid-template-columns: 1fr; }
	.fit-evidence-card { flex-direction: column; gap: 1rem; }
	.fit-evidence-card__meta { width: auto; }
	.fit-patterns-grid { grid-template-columns: repeat(2, 1fr); }
}

/* ── Accessibility ── */
@media (prefers-reduced-motion: reduce) {
	.fit-skill-card,
	.fit-pattern-card,
	.fit-nav__cta,
	.fit-footer__cta {
		transition: none;
	}
	.fit-skill-card:hover,
	.fit-pattern-card:hover {
		transform: none;
	}
	.fit-hero__context-dot {
		animation: none;
	}
}

/* Reuse keyframes from projects.css if available, else define here */
@keyframes status-pulse {
	0%, 100% { box-shadow: 0 0 0 0 rgba(var(--accent-rgb) / 0.4); }
	50% { box-shadow: 0 0 0 6px rgba(var(--accent-rgb) / 0); }
}
```

- [ ] **Step 2: Commit**

```bash
git add static/css/fit.css
git commit -m "Add fit page stylesheet with glassmorphic cards and roojerry tokens"
```

---

### Task B3: Single Page Template

**Files:**
- Create: `layouts/fit/single.html`

- [ ] **Step 1: Create the standalone template**

This is the core template. It is fully standalone — it does NOT use `{{ define "main" }}` or extend `baseof.html`. It provides its own complete HTML document.

```html
<!-- layouts/fit/single.html -->
<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>{{ .Params.company }} — {{ .Title }} | Brian Ruggieri</title>
	<meta name="description" content="{{ .Params.description | default .Params.overall_summary }}">
	{{ if not .Params.public }}
	<meta name="robots" content="noindex, nofollow">
	{{ end }}

	{{/* Fonts — preload for performance */}}
	<link rel="preload" href="/fonts/saira-extra-condensed-700.woff2" as="font" type="font/woff2" crossorigin>
	<link rel="preload" href="/fonts/open-sans.woff2" as="font" type="font/woff2" crossorigin>

	<link rel="stylesheet" href="/css/fonts.css">
	<link rel="stylesheet" href="/css/design-system.css">
	<link rel="stylesheet" href="/css/fit.css">

	<link rel="icon" type="image/svg+xml" href="/favicon.svg">
</head>
<body style="background: var(--bg-off); color: var(--brand-dark); font-family: 'Open Sans', sans-serif; margin: 0; -webkit-font-smoothing: antialiased;">

{{/* ── Nav ── */}}
<nav class="fit-nav">
	<div class="fit-nav__inner">
		<a href="https://www.roojerry.com" class="fit-nav__brand">Brian Ruggieri</a>
		<ul class="fit-nav__links">
			<li><a href="#match">Match</a></li>
			<li><a href="#skills">Skills</a></li>
			<li><a href="#evidence">Evidence</a></li>
			<li><a href="#projects">Projects</a></li>
			<li><a href="#gaps">Gaps</a></li>
		</ul>
		<a href="{{ .Params.cal_link }}" class="fit-nav__cta" target="_blank" rel="noopener">Let's Talk</a>
	</div>
</nav>

{{/* ── Hero ── */}}
<main>
<section class="fit-page fit-section" id="match">
	{{/* Derive grade class */}}
	{{ $grade := .Params.overall_grade }}
	{{ $gradeClass := "c" }}
	{{ if or (eq $grade "A+") (eq $grade "A") (eq $grade "A-") }}{{ $gradeClass = "a" }}{{ end }}
	{{ if or (eq $grade "B+") (eq $grade "B") (eq $grade "B-") }}{{ $gradeClass = "b" }}{{ end }}

	{{/* Derive should_apply display */}}
	{{ $verdict := "Maybe" }}
	{{ if eq .Params.should_apply "strong_yes" }}{{ $verdict = "Strong Yes" }}{{ end }}
	{{ if eq .Params.should_apply "yes" }}{{ $verdict = "Yes" }}{{ end }}
	{{ if eq .Params.should_apply "probably_not" }}{{ $verdict = "Probably Not" }}{{ end }}
	{{ if eq .Params.should_apply "no" }}{{ $verdict = "No" }}{{ end }}

	{{/* Derive must-have coverage */}}
	{{ $mustTotal := 0 }}{{ $mustMet := 0 }}
	{{ range .Params.skill_matches }}
		{{ if eq .priority "must_have" }}
			{{ $mustTotal = add $mustTotal 1 }}
			{{ if ne .status "no_evidence" }}{{ $mustMet = add $mustMet 1 }}{{ end }}
		{{ end }}
	{{ end }}

	<div class="fit-hero">
		<div>
			<div class="fit-hero__context">
				<span class="fit-hero__context-dot"></span>
				Targeting {{ .Params.company }} — {{ .Title }}
			</div>
			<h1 class="fit-hero__heading">
				{{ .Title }}<br>at {{ .Params.company }}
			</h1>
			<p class="fit-hero__summary">{{ .Params.overall_summary }}</p>
			<div class="fit-hero__stats">
				<div>
					<div class="fit-hero__stat-label">Confidence</div>
					<div class="fit-hero__stat-value">{{ $verdict }}</div>
				</div>
				<div class="fit-hero__divider"></div>
				<div>
					<div class="fit-hero__stat-label">Must-Haves</div>
					<div class="fit-hero__stat-value">{{ $mustMet }}/{{ $mustTotal }} met</div>
				</div>
			</div>
		</div>
		<div class="fit-grade fit-grade--{{ $gradeClass }}" aria-label="Overall grade: {{ $grade }}">
			<div class="fit-grade__ring"></div>
			<div class="fit-grade__ring--fill"></div>
			<span class="fit-grade__letter">{{ $grade }}</span>
			<span class="fit-grade__label">Overall Grade</span>
		</div>
	</div>
</section>

{{/* ── Skills ── */}}
{{ with .Params.skill_matches }}
<section class="fit-page fit-section" id="skills">
	<div class="fit-section__title">Skill Match Matrix</div>
	<div class="fit-section__subtitle">Technical proficiency validated through session data and corroboration.</div>
	<div class="fit-skills-grid">
		{{ range . }}
		{{ $statusDisplay := replace .status "_" " " | title }}
		<div class="fit-skill-card status-{{ .status }}">
			<div class="fit-skill-card__header">
				<span class="fit-skill-card__name">{{ .skill }}</span>
				<span class="fit-skill-card__status">{{ $statusDisplay }}</span>
			</div>
			<div class="fit-skill-card__row">
				<span class="fit-skill-card__row-label">Priority</span>
				<span class="fit-skill-card__row-value">{{ replace .priority "_" " " | title }}</span>
			</div>
			<div class="fit-skill-card__row">
				<span class="fit-skill-card__row-label">Depth</span>
				<span class="fit-skill-card__row-value">{{ .depth }}</span>
			</div>
			{{ with .sessions }}
			<div class="fit-skill-card__row">
				<span class="fit-skill-card__row-label">Sessions</span>
				<span class="fit-skill-card__row-value" style="font-variant-numeric: tabular-nums; color: var(--brand);">{{ . }}</span>
			</div>
			{{ end }}
			<div class="fit-skill-card__row">
				<span class="fit-skill-card__row-label">Source</span>
				<span class="fit-skill-card__row-value">{{ replace .source "_" " " | title }}</span>
			</div>
			{{ if .discovery }}
			<div class="fit-skill-card__discovery">✦ Found in sessions, not on resume</div>
			{{ end }}
		</div>
		{{ end }}
	</div>
</section>
{{ end }}

{{/* ── Evidence ── */}}
{{ with .Params.evidence_highlights }}
<section class="fit-page fit-section" id="evidence" style="background: var(--bg-mid); padding: 5rem 0; margin: 0 calc(-50vw + 50%); width: 100vw;">
	<div style="max-width: 1200px; margin: 0 auto; padding: 0 1.5rem;">
		<div style="text-align: center; margin-bottom: 3rem;">
			<div class="fit-section__subtitle" style="color: var(--brand); margin-bottom: 0.5rem;">Evidence & Documentation</div>
			<div class="fit-section__title">Technical Decision Logs</div>
		</div>
		{{ range . }}
		<div class="fit-evidence-card">
			<div class="fit-evidence-card__meta">
				<div class="fit-evidence-card__heading">{{ .heading }}</div>
				<div class="fit-evidence-card__date">{{ .date }}</div>
				{{ with .tags }}
				<div style="margin-top: 0.75rem;">
					{{ range . }}<span class="fit-tag">{{ . }}</span>{{ end }}
				</div>
				{{ end }}
			</div>
			<div>
				<blockquote class="fit-evidence-card__quote">"{{ .quote }}"</blockquote>
				<div class="fit-evidence-card__project">{{ .project }}</div>
			</div>
		</div>
		{{ end }}
	</div>
</section>
{{ end }}

{{/* ── Patterns ── */}}
{{ with .Params.patterns }}
<section class="fit-page fit-section">
	<div class="fit-section__title">Behavioral Fingerprint</div>
	<div class="fit-section__subtitle">Frequency analysis of professional instincts and workflow patterns.</div>
	<div class="fit-patterns-grid">
		{{ range . }}
		<div class="fit-pattern-card">
			<div class="fit-pattern-card__name">{{ .name }}</div>
			<div class="fit-pattern-card__strength">{{ .strength }}</div>
			<div class="fit-pattern-card__frequency">{{ .frequency }}</div>
		</div>
		{{ end }}
	</div>
</section>
{{ end }}

{{/* ── Projects ── */}}
{{ with .Params.projects }}
<section class="fit-page fit-section" id="projects">
	<div class="fit-section__title">Flagship Implementations</div>
	<div style="height: 3px; width: 4rem; background: var(--brand); border-radius: 2px; margin-bottom: 2.5rem;"></div>
	<div class="fit-timeline">
		{{ range . }}
		<div class="fit-project">
			<div class="fit-project__dot"></div>
			<div class="fit-project__date">{{ .date_range }}</div>
			<div class="fit-project__name">{{ .name }}</div>
			<div class="fit-project__techs">
				{{ range .technologies }}
				<span class="fit-project__tech">{{ . }}</span>
				{{ end }}
			</div>
			<div class="fit-project__body">
				<p class="fit-project__desc">{{ .description }}</p>
				{{ with .callout }}
				<div class="fit-project__callout">
					<div class="fit-project__callout-label">Key Decision</div>
					<p class="fit-project__callout-text">"{{ . }}"</p>
				</div>
				{{ end }}
			</div>
		</div>
		{{ end }}
	</div>
</section>
{{ end }}

{{/* ── Gaps ── */}}
{{ with .Params.gaps }}
<section class="fit-page fit-section" id="gaps">
	<div class="fit-gaps">
		<div class="fit-gaps__icon">↑</div>
		<div style="position: relative; z-index: 1; max-width: 42rem;">
			<div class="fit-section__title">Where I'm Growing</div>
			<p class="fit-section__subtitle" style="font-size: 1rem; margin-bottom: 2.5rem;">Transparent view of my current development areas and active plans.</p>
			{{ range . }}
			<div class="fit-gap-card">
				<div class="fit-gap-card__header">
					<div>
						<div class="fit-gap-card__action-label">Gap Analysis</div>
						<div class="fit-gap-card__requirement">{{ .requirement }}</div>
					</div>
					<div class="fit-gap-card__status-tag">{{ .status }}</div>
				</div>
				<div class="fit-gap-card__action">
					<div>
						<div class="fit-gap-card__action-label">Action Plan</div>
						<div class="fit-gap-card__action-text">{{ .action }}</div>
					</div>
				</div>
			</div>
			{{ end }}
		</div>
	</div>
</section>
{{ end }}
</main>

{{/* ── Footer ── */}}
<footer class="fit-footer">
	<h3 style="font-family: 'Saira Extra Condensed', sans-serif; font-weight: 700; font-size: 1.5rem; color: var(--brand-dark); text-transform: uppercase; margin: 0 0 1.5rem;">Let's talk about this role</h3>
	<a href="{{ .Params.cal_link }}" class="fit-footer__cta" target="_blank" rel="noopener">Schedule a Conversation</a>
	<ul class="fit-footer__links">
		<li><a href="https://linkedin.com/in/roojerry" target="_blank" rel="noopener">LinkedIn</a></li>
		<li><a href="https://github.com/brianruggieri" target="_blank" rel="noopener">GitHub</a></li>
		<li><a href="https://www.roojerry.com" target="_blank" rel="noopener">Portfolio</a></li>
	</ul>
	<p class="fit-footer__credit">Generated by claude-candidate — an evidence-backed fit assessment engine.</p>
	<p class="fit-footer__credit">© {{ now.Year }} Brian Ruggieri</p>
</footer>

</body>
</html>
```

- [ ] **Step 2: Verify with Hugo dev server**

Run: `npm run dev` — navigate to `localhost:1313/fit/` and verify no build errors. (No content yet, so the page will be empty — just checking template syntax.)

- [ ] **Step 3: Commit**

```bash
git add layouts/fit/single.html
git commit -m "Add standalone fit page template with all 8 sections"
```

---

### Task B4: List Page Template

**Files:**
- Create: `layouts/fit/list.html`

- [ ] **Step 1: Create the list template**

```html
<!-- layouts/fit/list.html -->
<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1.0">
	<title>Fit Assessments | Brian Ruggieri</title>
	<meta name="description" content="Evidence-backed job fit assessments by Brian Ruggieri">

	<link rel="preload" href="/fonts/saira-extra-condensed-700.woff2" as="font" type="font/woff2" crossorigin>
	<link rel="preload" href="/fonts/open-sans.woff2" as="font" type="font/woff2" crossorigin>

	<link rel="stylesheet" href="/css/fonts.css">
	<link rel="stylesheet" href="/css/design-system.css">
	<link rel="stylesheet" href="/css/fit.css">

	<link rel="icon" type="image/svg+xml" href="/favicon.svg">
</head>
<body style="background: var(--bg-off); color: var(--brand-dark); font-family: 'Open Sans', sans-serif; margin: 0; -webkit-font-smoothing: antialiased;">

<nav class="fit-nav">
	<div class="fit-nav__inner">
		<a href="https://www.roojerry.com" class="fit-nav__brand">Brian Ruggieri</a>
		<span></span>
		<a href="https://www.roojerry.com" class="fit-nav__cta">Portfolio</a>
	</div>
</nav>

<main class="fit-page" style="padding-top: 8rem; padding-bottom: 4rem;">
	<div class="fit-section__title">Fit Assessments</div>
	<div class="fit-section__subtitle">Evidence-backed job match analysis, powered by session data.</div>

	{{ $public := where .Pages ".Params.public" true }}
	{{ if $public }}
	<div class="fit-skills-grid" style="margin-top: 2rem;">
		{{ range $public }}
		{{ $grade := .Params.overall_grade }}
		{{ $gradeClass := "c" }}
		{{ if or (eq $grade "A+") (eq $grade "A") (eq $grade "A-") }}{{ $gradeClass = "a" }}{{ end }}
		{{ if or (eq $grade "B+") (eq $grade "B") (eq $grade "B-") }}{{ $gradeClass = "b" }}{{ end }}

		<a href="{{ .Permalink }}" class="fit-skill-card status-strong_match" style="text-decoration: none; cursor: pointer;">
			<div class="fit-skill-card__header">
				<span class="fit-skill-card__name">{{ .Params.company }}</span>
				<span class="fit-skill-card__status" style="background: var(--grade-color, var(--accent));">{{ $grade }}</span>
			</div>
			<div class="fit-skill-card__row">
				<span class="fit-skill-card__row-label">Role</span>
				<span class="fit-skill-card__row-value">{{ .Title }}</span>
			</div>
			<div style="font-family: 'Open Sans', sans-serif; font-size: 0.78rem; color: var(--muted); margin-top: 0.75rem; line-height: 1.5;">
				{{ .Params.overall_summary | truncate 120 }}
			</div>
		</a>
		{{ end }}
	</div>
	{{ end }}
</main>

<footer class="fit-footer">
	<p class="fit-footer__credit">Generated by claude-candidate — an evidence-backed fit assessment engine.</p>
	<p class="fit-footer__credit">© {{ now.Year }} Brian Ruggieri</p>
</footer>

</body>
</html>
```

- [ ] **Step 2: Commit**

```bash
git add layouts/fit/list.html
git commit -m "Add fit assessment list page showing public entries only"
```

---

### Task B5: Test with Sample Content

**Files:**
- Create: `content/fit/staff-engineer-anthropic.md` (sample — delete after testing)

- [ ] **Step 1: Create a sample content file for visual testing**

Create `content/fit/staff-engineer-anthropic.md` with the example front matter from the spec (copy from the Content File Structure section of the spec document).

- [ ] **Step 2: Run Hugo dev server and verify**

Run: `npm run dev` — navigate to `localhost:1313/fit/staff-engineer-anthropic/`

Verify:
- All 8 sections render
- Glassmorphic cards display correctly
- Grade badge shows correct color
- Skill cards have colored left stripes
- Tags use teardrop style
- Responsive layout works at mobile/tablet breakpoints
- `noindex` meta tag present (since `public: false`)
- Footer links work

- [ ] **Step 3: Fix any visual issues found during testing**

Iterate on `fit.css` and `single.html` as needed.

- [ ] **Step 4: Remove sample content and commit**

```bash
rm content/fit/staff-engineer-anthropic.md
git add -A
git commit -m "Test and polish fit page template"
```

---

### Task B6: PurgeCSS Safelist

**Files:**
- Modify: `purgecss.config.js`

- [ ] **Step 1: Add fit CSS classes to PurgeCSS safelist**

The fit template uses dynamically-generated class names like `status-strong_match`, `status-adjacent`, `fit-grade--a`, etc. These must be safelisted since PurgeCSS can't detect them from Hugo template strings.

Add to the `safelist.deep` array (not `standard`) in `purgecss.config.js`, since these are regex patterns for dynamically-generated class names:

```javascript
// In the safelist.deep array, alongside existing patterns:
deep: [
    /^(bd-|bs-)/,
    /tooltip/,
    /popover/,
    /carousel/,
    /aria-expanded/,
    /^status-/,      // Fit page status classes
    /^fit-grade--/,  // Fit page grade badge classes
],
```

- [ ] **Step 2: Run production build to verify**

Run: `npm run build`
Expected: No errors, fit.css classes preserved in output.

- [ ] **Step 3: Commit**

```bash
git add purgecss.config.js
git commit -m "Safelist fit page dynamic classes for PurgeCSS"
```
