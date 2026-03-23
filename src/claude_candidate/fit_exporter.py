"""Export FitAssessment data as Hugo-compatible markdown for the fit landing page."""

from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from claude_candidate.skill_taxonomy import SkillTaxonomy

_taxonomy: SkillTaxonomy | None = None


def _get_taxonomy() -> SkillTaxonomy:
    global _taxonomy
    if _taxonomy is None:
        _taxonomy = SkillTaxonomy.load_default()
    return _taxonomy


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
    company_parts = company.strip().split()
    if not company_parts:
        company_word = "company"
    else:
        company_word = re.split(r"[^a-zA-Z0-9]", company_parts[0])[0].lower()
    if not company_word:
        company_word = "company"

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
    best_match = None
    best_score = 0
    for item in action_items:
        item_words = set(item.lower().split())
        overlap = len(req_words & item_words)
        if overlap > best_score:
            best_score = overlap
            best_match = item
    return best_match if best_match else "Actively developing this skill"


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


# Generic terms that should never fuzzy-match to a real skill.
_RESOLVE_STOPWORDS = frozenset({
    "experience", "years", "year", "proficiency", "knowledge", "expertise",
    "understanding", "familiarity", "skills", "ability", "strong", "deep",
    "solid", "proven", "track", "record", "working", "hands", "plus",
    "preferred", "required", "minimum", "senior", "junior", "staff",
})


def _resolve_skill_key(
    raw_key: str,
    evidence_dict: dict[str, Any],
    taxonomy: SkillTaxonomy,
) -> str | None:
    """Try to resolve a requirement phrase to a key in evidence_dict.

    Attempts, in order:
    1. Direct lookup (already lowered by caller)
    2. Canonicalize via taxonomy alias table
    3. Extract individual words and try each via direct/canonical lookup
       (no fuzzy on individual words — avoids "experience" → "startup-experience")

    Returns the matching key or None.
    """
    # 1. Direct
    if raw_key in evidence_dict:
        return raw_key

    # 2. Canonicalize (exact alias lookup, fast)
    canonical = taxonomy.canonicalize(raw_key)
    if canonical in evidence_dict:
        return canonical

    # 3. Extract individual words and try direct/canonical only.
    # Skip fuzzy matching on individual words to avoid false positives
    # (e.g., "experience" fuzzy-matching to "startup-experience").
    words = re.findall(r"[a-z][a-z0-9.#+_-]*", raw_key)
    for word in words:
        if word in _RESOLVE_STOPWORDS:
            continue
        if word in evidence_dict:
            return word
        word_canonical = taxonomy.canonicalize(word)
        if word_canonical in evidence_dict:
            return word_canonical

    return None


def select_evidence_highlights(
    skill_matches: list[dict[str, Any]],
    candidate_skills: list[dict[str, Any]],
    *,
    limit: int = 3,
    projects: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Select top evidence highlights from strong matches with session references.

    Args:
        skill_matches: SkillMatchDetail dicts from FitAssessment.
        candidate_skills: SkillEntry dicts from CandidateProfile (with evidence[]).
        projects: ProjectSummary dicts for technology tag lookup by project name.
    """
    taxonomy = _get_taxonomy()

    # Build project → technologies lookup
    project_techs: dict[str, list[str]] = {}
    for proj in (projects or []):
        name = proj.get("project_name", "").lower()
        if name:
            project_techs[name] = proj.get("technologies", [])
    # Build lookup from skill name to evidence list
    skill_evidence: dict[str, list[dict]] = {}
    for skill in candidate_skills:
        name = skill.get("name", "").lower()
        evidence = skill.get("evidence", [])
        if evidence:
            skill_evidence[name] = evidence

    # Prefer corroborated strong matches, also include exceeds
    strong = [
        m for m in skill_matches
        if m.get("match_status") in ("strong_match", "exceeds")
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
        # Use matched_skill (canonical name) for lookup, fall back to requirement
        lookup_key = (match.get("matched_skill") or match["requirement"]).lower()
        resolved = _resolve_skill_key(lookup_key, skill_evidence, taxonomy)
        evidence_list = skill_evidence.get(resolved, []) if resolved else []
        if not evidence_list:
            continue

        # Pick highest-confidence session reference
        best = max(evidence_list, key=lambda e: e.get("confidence", 0))
        session_date = best.get("session_date", "")
        if session_date:
            try:
                dt = datetime.fromisoformat(str(session_date).replace("Z", "+00:00"))
                formatted_date = dt.strftime("%b %Y")
            except (ValueError, TypeError):
                formatted_date = str(session_date)[:7]
        else:
            formatted_date = ""

        project_name = best.get("project_context", "")
        tags = project_techs.get(project_name.lower(), []) or [match["requirement"]]
        result.append({
            "heading": match["requirement"].title(),
            "quote": best.get("evidence_snippet", ""),
            "project": project_name,
            "date": formatted_date,
            "tags": tags,
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

    yaml_str = yaml.safe_dump(
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
    return date.today().isoformat()


# ── Export Orchestrator ──


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
    # storage.get_assessment() returns a row dict where 'data' is already JSON-parsed.
    # Top-level 'should_apply' is coerced to bool by storage —
    # always read from the nested 'data' dict for original string values.
    raw_data = assessment_data.get("data", {})
    if isinstance(raw_data, str):
        full_data = json.loads(raw_data)
    else:
        full_data = raw_data

    # Load profiles
    merged_profile = json.loads(merged_profile_path.read_text(encoding="utf-8"))
    candidate_profile = json.loads(candidate_profile_path.read_text(encoding="utf-8"))

    # Extract fields
    title = full_data.get("job_title", "Engineer")
    company = full_data.get("company_name", "Unknown")
    slug = generate_slug(title, company)

    skill_matches_raw = full_data.get("skill_matches", [])
    action_items = full_data.get("action_items", [])

    # Build merged skill lookup for depth/sessions/discovery
    taxonomy = _get_taxonomy()
    merged_skills = {s["name"].lower(): s for s in merged_profile.get("skills", [])}

    # Select and enrich skill matches
    selected_matches = select_skill_matches(skill_matches_raw)
    enriched_matches = []
    for match in selected_matches:
        req = match["requirement"]
        # Use matched_skill (canonical name) for the join, fall back to requirement.
        # Resolve through taxonomy when the key doesn't match directly.
        join_key = (match.get("matched_skill") or req).lower()
        resolved_key = _resolve_skill_key(join_key, merged_skills, taxonomy)
        merged = merged_skills.get(resolved_key, {}) if resolved_key else {}
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
        projects=merged_profile.get("projects", []),
    )
    patterns = select_patterns(merged_profile.get("patterns", []))

    # Collect tech stack from job for project relevance
    job_techs = [m.get("requirement", "") for m in skill_matches_raw]
    projects = select_projects(merged_profile.get("projects", []), job_techs)
    gaps = select_gaps(skill_matches_raw, action_items)

    # Validate minimum content thresholds
    threshold_errors = []
    if len(enriched_matches) < 3:
        threshold_errors.append(
            f"Skill matches: {len(enriched_matches)} found, minimum 3 required"
        )
    if len(projects) < 1:
        threshold_errors.append(
            "Projects: 0 found, minimum 1 required"
        )
    if threshold_errors:
        raise ValueError(
            "Export failed — insufficient content for a credible fit page:\n  - "
            + "\n  - ".join(threshold_errors)
        )

    # Warn about hidden optional sections
    hidden = []
    if not evidence:
        hidden.append("Evidence Highlights")
    if not patterns:
        hidden.append("Behavioral Patterns")
    if not gaps:
        hidden.append("Gap Transparency")
    if hidden:
        print(
            f"Note: {', '.join(hidden)} section(s) will be hidden (no content available)",
            file=sys.stderr,
        )

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
