"""
Resume Parser: Extract and structure resume data from PDF, DOCX, or TXT files.

Parses raw resume text into a ResumeProfile using regex heuristics.
No LLM calls — purely deterministic extraction from known patterns.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from claude_candidate.manifest import hash_file
from claude_candidate.schemas.candidate_profile import DepthLevel
from claude_candidate.schemas.resume_profile import ResumeProfile, ResumeRole, ResumeSkill


# ---------------------------------------------------------------------------
# Skill knowledge base
# ---------------------------------------------------------------------------

SKILL_ALIASES: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "k8s": "kubernetes",
    "py": "python",
    "pg": "postgresql",
    "postgres": "postgresql",
    "node": "node.js",
    "nodejs": "node.js",
    "node.js": "node.js",
    "react.js": "react",
    "vue.js": "vue",
    "angular.js": "angular",
    "tf": "terraform",
    "ml": "machine learning",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "ci/cd": "ci/cd",
    "cicd": "ci/cd",
    "continuous integration": "ci/cd",
    "rest apis": "rest apis",
    "rest api": "rest apis",
    "restful": "rest apis",
    "microservices": "microservices",
    "apache spark": "apache spark",
    "spark": "apache spark",
    "gcp": "gcp",
    "aws": "aws",
    "azure": "azure",
    "fastapi": "fastapi",
    "fast api": "fastapi",
    "redis": "redis",
    "docker": "docker",
    "kubernetes": "kubernetes",
    "git": "git",
    "postgresql": "postgresql",
    "python": "python",
    "typescript": "typescript",
    "javascript": "javascript",
    "react": "react",
    "vue": "vue",
    "angular": "angular",
    "django": "django",
    "flask": "flask",
    "spring": "spring",
    "terraform": "terraform",
    "ansible": "ansible",
    "jenkins": "jenkins",
    "github actions": "github actions",
    "elasticsearch": "elasticsearch",
    "mongodb": "mongodb",
    "mysql": "mysql",
    "sqlite": "sqlite",
    "graphql": "graphql",
}

KNOWN_SKILLS: set[str] = {
    "python",
    "typescript",
    "javascript",
    "java",
    "go",
    "rust",
    "c++",
    "c#",
    "ruby",
    "php",
    "swift",
    "kotlin",
    "scala",
    "react",
    "vue",
    "angular",
    "node.js",
    "django",
    "flask",
    "fastapi",
    "spring",
    "express",
    "next.js",
    "postgresql",
    "mysql",
    "sqlite",
    "mongodb",
    "redis",
    "elasticsearch",
    "dynamodb",
    "cassandra",
    "docker",
    "kubernetes",
    "aws",
    "gcp",
    "azure",
    "terraform",
    "ansible",
    "jenkins",
    "github actions",
    "ci/cd",
    "git",
    "linux",
    "bash",
    "graphql",
    "rest apis",
    "microservices",
    "apache spark",
    "kafka",
    "rabbitmq",
    "machine learning",
    "deep learning",
    "natural language processing",
    "pytorch",
    "tensorflow",
    "scikit-learn",
    "pandas",
    "numpy",
    "fastapi",
}


# ---------------------------------------------------------------------------
# Date parsing helpers
# ---------------------------------------------------------------------------

MONTH_MAP: dict[str, str] = {
    "january": "01", "jan": "01",
    "february": "02", "feb": "02",
    "march": "03", "mar": "03",
    "april": "04", "apr": "04",
    "may": "05",
    "june": "06", "jun": "06",
    "july": "07", "jul": "07",
    "august": "08", "aug": "08",
    "september": "09", "sep": "09", "sept": "09",
    "october": "10", "oct": "10",
    "november": "11", "nov": "11",
    "december": "12", "dec": "12",
}


def _parse_date(date_str: str) -> str:
    """Convert date string like 'January 2022' or '2022' to 'YYYY-MM' or 'YYYY'."""
    date_str = date_str.strip()
    for month_name, month_num in MONTH_MAP.items():
        pattern = re.compile(rf"\b{re.escape(month_name)}\b\s+(\d{{4}})", re.IGNORECASE)
        m = pattern.search(date_str)
        if m:
            return f"{m.group(1)}-{month_num}"
    # Just a year
    year_match = re.search(r"\d{4}", date_str)
    if year_match:
        return year_match.group(0)
    return date_str


def _months_between(start: str, end: str | None) -> int | None:
    """Rough month count between two YYYY-MM strings."""
    if end is None:
        end_dt = datetime.now()
    else:
        try:
            parts = end.split("-")
            if len(parts) == 2:
                end_dt = datetime(int(parts[0]), int(parts[1]), 1)
            else:
                end_dt = datetime(int(parts[0]), 1, 1)
        except ValueError:
            return None
    try:
        parts = start.split("-")
        if len(parts) == 2:
            start_dt = datetime(int(parts[0]), int(parts[1]), 1)
        else:
            start_dt = datetime(int(parts[0]), 1, 1)
    except ValueError:
        return None
    delta_months = (end_dt.year - start_dt.year) * 12 + (end_dt.month - start_dt.month)
    return max(0, delta_months)


# ---------------------------------------------------------------------------
# Section detection helpers
# ---------------------------------------------------------------------------

_SECTION_NAMES = [
    "PROFESSIONAL SUMMARY", "WORK EXPERIENCE", "TECHNICAL SKILLS",
    "CERTIFICATIONS? & LICENSES?", "CERTIFICATIONS?",
    "SUMMARY", "OBJECTIVE", "EXPERIENCE", "EMPLOYMENT",
    "SKILLS", "EDUCATION", "PROJECTS?", "AWARDS?", "PUBLICATIONS?",
]

# Match section headers even when two-column PDF interleaves them on one line
SECTION_HEADERS = re.compile(
    r"^\s*(" + "|".join(_SECTION_NAMES) + r")(?:\s|$)",
    re.IGNORECASE,
)

def _extract_section_name(line: str) -> str | None:
    """Extract the first recognized section header from a line.

    Handles two-column PDFs where headers like 'WORK EXPERIENCE PROFESSIONAL SUMMARY'
    appear on a single line.
    """
    m = SECTION_HEADERS.match(line.strip())
    if m:
        return m.group(1).upper().rstrip("S")  # Normalize plural
    return None

ROLE_SEPARATOR = re.compile(
    r"^(.+?)\s*[|\-–—]\s*(.+)$",
)

DATE_RANGE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}|\d{4})"
    r"\s*[-–—to]+\s*"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}|\d{4}|Present|present|Current|current)",
    re.IGNORECASE,
)

# Location: "City, ST" — used for general text matching
LOCATION_PATTERN = re.compile(
    r"(?<![a-z])([A-Z][a-z]+(?:\s[A-Z][a-z]+)?),\s*([A-Z]{2})(?:\s|$|\))"
)

# Location at end of line (for header name/location splitting)
LOCATION_EOL = re.compile(
    r"([A-Z][a-z]+(?:\s[A-Z][a-z]+)?),\s*([A-Z]{2})\s*$"
)

BULLET_LINE = re.compile(r"^\s*[-•●*►▪◦]\s*(.+)$")


def _normalize_skill(raw: str) -> str:
    """Normalize a skill token using SKILL_ALIASES."""
    cleaned = raw.strip().lower().rstrip(".,;")
    return SKILL_ALIASES.get(cleaned, cleaned)


def _extract_skills_from_text(text: str) -> set[str]:
    """Find all known skills appearing in a block of text."""
    found: set[str] = set()
    text_lower = text.lower()
    # Check multi-word skills first (longest match)
    sorted_skills = sorted(KNOWN_SKILLS, key=len, reverse=True)
    for skill in sorted_skills:
        # Use word-boundary match
        pattern = re.compile(r"\b" + re.escape(skill) + r"\b", re.IGNORECASE)
        if pattern.search(text_lower):
            found.add(skill)
    # Also check aliases
    for alias, canonical in SKILL_ALIASES.items():
        if canonical in KNOWN_SKILLS:
            pattern = re.compile(r"\b" + re.escape(alias) + r"\b", re.IGNORECASE)
            if pattern.search(text_lower):
                found.add(canonical)
    return found


def _split_sections(text: str) -> dict[str, str]:
    """
    Split resume text into named sections.

    Returns dict mapping section name (uppercased) to section body.
    A 'HEADER' key holds lines before the first recognized section.
    Handles two-column PDFs where section headers may share a line.
    """
    sections: dict[str, list[str]] = {"HEADER": []}
    current = "HEADER"
    for line in text.splitlines():
        section_name = _extract_section_name(line)
        if section_name:
            # Normalize to canonical names for lookup
            if "EXPERIENCE" in section_name or "EMPLOYMENT" in section_name:
                current = "WORK EXPERIENCE"
            elif "SKILL" in section_name:
                current = "SKILLS"
            elif "SUMMARY" in section_name or "OBJECTIVE" in section_name:
                current = "SUMMARY"
            elif "EDUCATION" in section_name:
                current = "EDUCATION"
            elif "CERTIF" in section_name:
                current = "CERTIFICATIONS"
            else:
                current = section_name
            sections.setdefault(current, [])
        else:
            sections.setdefault(current, []).append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


# ---------------------------------------------------------------------------
# Role parsing
# ---------------------------------------------------------------------------

def _parse_roles(experience_text: str) -> list[ResumeRole]:
    """Parse the EXPERIENCE section into ResumeRole objects.

    Handles two common formats:
    1. Single-line: "Title | Company" or "Title - Company" followed by date
    2. Multi-line: Title on one line, Company on next, Date on another
    """
    roles: list[ResumeRole] = []
    lines = experience_text.splitlines()

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        title_part: str | None = None
        company_part: str | None = None
        start_date = "unknown"
        end_date: str | None = None
        date_line_idx: int | None = None

        # Strategy 1: "Title | Company" or "Title - Company" on one line
        role_match = ROLE_SEPARATOR.match(line)
        if role_match:
            title_part = role_match.group(1).strip()
            company_part = role_match.group(2).strip()
            # Look ahead for date range
            for j in range(i + 1, min(i + 4, len(lines))):
                dm = DATE_RANGE.search(lines[j])
                if dm:
                    start_date = _parse_date(dm.group(1))
                    raw_end = dm.group(2)
                    end_date = None if raw_end.lower() in ("present", "current") else _parse_date(raw_end)
                    date_line_idx = j
                    break

        # Strategy 2: Multi-line — look for a date range within 1-4 lines ahead
        # If current line has no date, and a nearby line does, treat this as title
        if title_part is None:
            for j in range(i + 1, min(i + 5, len(lines))):
                next_line = lines[j].strip() if j < len(lines) else ""
                dm = DATE_RANGE.search(next_line)
                if dm:
                    # Found a date range — lines between i and j form the role header
                    # Title is current line, company is lines between
                    title_part = line
                    company_lines = []
                    for ci in range(i + 1, j):
                        cl = lines[ci].strip()
                        if cl and not DATE_RANGE.search(cl):
                            company_lines.append(cl)
                    company_part = ", ".join(company_lines) if company_lines else ""
                    start_date = _parse_date(dm.group(1))
                    raw_end = dm.group(2)
                    end_date = None if raw_end.lower() in ("present", "current") else _parse_date(raw_end)
                    date_line_idx = j
                    break

        if title_part is None or date_line_idx is None:
            i += 1
            continue

        # Clean up title/company — remove parenthetical location from company
        if company_part:
            # Strip trailing location like "Sacramento, CA (Remote)"
            company_part = re.sub(r"\s*\(.*?\)\s*$", "", company_part).strip()
            # Also strip trailing comma-separated location
            company_part = re.sub(r",\s*[A-Z]{2}\s*$", "", company_part).strip()

        # Collect bullet points and description lines after the date
        bullets: list[str] = []
        technologies: list[str] = []
        k = date_line_idx + 1
        while k < len(lines):
            bl = lines[k].strip()
            if not bl:
                k += 1
                continue

            # Stop if this looks like a new role header (has a date range nearby)
            if k + 4 < len(lines):
                future_has_date = any(
                    DATE_RANGE.search(lines[fj].strip())
                    for fj in range(k + 1, min(k + 5, len(lines)))
                    if lines[fj].strip()
                )
                # If this non-bullet line is followed by a date, it's a new role
                if future_has_date and not BULLET_LINE.match(bl):
                    break

            bullet_match = BULLET_LINE.match(lines[k])
            if bullet_match:
                content = bullet_match.group(1).strip()
                if content.lower().startswith("technologies:"):
                    tech_str = content.split(":", 1)[1].strip()
                    technologies = [t.strip() for t in tech_str.split(",") if t.strip()]
                else:
                    bullets.append(content)
            k += 1

        duration = _months_between(start_date, end_date)

        roles.append(ResumeRole(
            title=title_part,
            company=company_part or "",
            start_date=start_date,
            end_date=end_date,
            duration_months=duration,
            description=" ".join(bullets[:3]),
            technologies=technologies,
            achievements=bullets,
        ))
        i = k

    return roles


# ---------------------------------------------------------------------------
# Skills section parsing
# ---------------------------------------------------------------------------

def _parse_skills_section(skills_text: str) -> set[str]:
    """
    Extract canonical skill names from the SKILLS section.

    Handles category-grouped skills like:
        Languages: Python, TypeScript, JavaScript
        Frameworks: React, Vue, Angular
    """
    found: set[str] = set()
    for line in skills_text.splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip category header (e.g., "Languages:", "AI & Agentic Systems:")
        if ":" in line:
            line = line.split(":", 1)[1].strip()
        if not line:
            continue
        # Split by comma, pipe, semicolon
        tokens = re.split(r"[,|;]", line)
        for token in tokens:
            token = token.strip().rstrip(".,;()")
            if not token or len(token) < 2:
                continue
            # Skip category-like tokens (end with colon, all caps multi-word)
            if token.endswith(":"):
                continue
            canonical = _normalize_skill(token)
            if canonical:
                found.add(canonical)
            for s in _extract_skills_from_text(token):
                found.add(s)
    return found


# ---------------------------------------------------------------------------
# Main parser functions
# ---------------------------------------------------------------------------

def extract_text_from_file(path: Path) -> str:
    """
    Extract plain text from a .pdf, .docx, or .txt file.

    Raises:
        FileNotFoundError: if the file does not exist.
        ValueError: if the file format is not supported.
    """
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    suffix = path.suffix.lower()

    if suffix == ".txt":
        return path.read_text(encoding="utf-8", errors="replace")

    if suffix == ".pdf":
        import fitz  # pymupdf — handles multi-column layouts in reading order

        pages: list[str] = []
        doc = fitz.open(path)
        for page in doc:
            text = page.get_text("text")
            if text:
                pages.append(text)
        doc.close()
        # Strip zero-width spaces that pymupdf sometimes inserts
        result = "\n".join(pages)
        result = result.replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
        return result

    if suffix == ".docx":
        from docx import Document
        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs]
        return "\n".join(paragraphs)

    raise ValueError(f"Unsupported file format: {suffix!r}. Supported: .pdf, .docx, .txt")


def _preprocess_text(text: str) -> str:
    """Clean up extracted text for parsing.

    Fixes common PDF extraction artifacts:
    - Bullet markers (●, •) on their own line get merged with the next line
    - Multi-line bullet continuations get joined
    """
    lines = text.splitlines()
    merged: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Bullet marker on its own line — merge with next line
        if stripped in ("●", "•", "►", "▪", "◦", "-", "*") and i + 1 < len(lines):
            next_line = lines[i + 1]
            merged.append(f"● {next_line.strip()}")
            i += 2
            # Also merge continuation lines (indented, no bullet, not a new section)
            while i < len(lines):
                cont = lines[i]
                cont_stripped = cont.strip()
                if (cont_stripped
                        and not cont_stripped.startswith("●")
                        and not cont_stripped.startswith("•")
                        and not SECTION_HEADERS.match(cont_stripped)
                        and not DATE_RANGE.search(cont_stripped)
                        and len(cont_stripped) > 5
                        and cont_stripped[0].islower()):
                    # Continuation of previous bullet
                    merged[-1] += " " + cont_stripped
                    i += 1
                else:
                    break
        else:
            merged.append(line)
            i += 1
    return "\n".join(merged)


def parse_resume_text(
    text: str,
    source_format: Literal["pdf", "docx", "txt"] = "txt",
) -> ResumeProfile:
    """
    Parse raw resume text into a ResumeProfile using regex heuristics.

    Assigns DepthLevel based on where a skill appears:
    - APPLIED: skill found in role context AND in skills section
    - USED: skill found in role context only
    - MENTIONED: skill found in skills section only
    """
    text = _preprocess_text(text)
    sections = _split_sections(text)

    # ------------------------------------------------------------------
    # Identity: name, title, location from header lines
    # ------------------------------------------------------------------
    header_lines = [ln.strip() for ln in sections.get("HEADER", "").splitlines() if ln.strip()]

    name: str | None = None
    current_title: str | None = None
    location: str | None = None

    if header_lines:
        # First non-empty line is typically the name — strip location if appended
        raw_name = header_lines[0]
        loc_in_name = LOCATION_EOL.search(raw_name)
        if loc_in_name:
            location = f"{loc_in_name.group(1)}, {loc_in_name.group(2)}"
            name = raw_name[:loc_in_name.start()].strip().rstrip(",")
        else:
            name = raw_name

        # Title: look for a line that isn't a phone/email/url
        for line in header_lines[1:]:
            if re.search(r"\d{3}.*\d{4}", line):  # phone
                continue
            if "@" in line:  # email
                continue
            if re.search(r"(github|linkedin|\.com|\.io)", line, re.IGNORECASE):  # url
                continue
            if not current_title:
                current_title = line
                break

        if not location:
            for line in header_lines:
                loc_match = LOCATION_PATTERN.search(line)
                if loc_match:
                    location = f"{loc_match.group(1)}, {loc_match.group(2)}"
                    break

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    summary_text: str | None = None
    for key in sections:
        if "SUMMARY" in key or "OBJECTIVE" in key:
            body = sections[key].strip()
            if body:
                summary_text = body
            break

    # ------------------------------------------------------------------
    # Experience
    # ------------------------------------------------------------------
    experience_text = ""
    for key in ("WORK EXPERIENCE", "EXPERIENCE", "EMPLOYMENT"):
        if key in sections:
            experience_text = sections[key]
            break

    roles = _parse_roles(experience_text)

    # ------------------------------------------------------------------
    # Skills section
    # ------------------------------------------------------------------
    skills_section_text = ""
    for key in sections:
        if "SKILL" in key:
            skills_section_text = sections[key]
            break

    skills_section_set = _parse_skills_section(skills_section_text)

    # ------------------------------------------------------------------
    # Extract skills from role descriptions
    # ------------------------------------------------------------------
    # Map skill -> (set of role indices it appears in, is_current)
    role_skill_map: dict[str, set[int]] = {}
    for idx, role in enumerate(roles):
        role_text = " ".join([
            role.title,
            role.company,
            role.description,
            " ".join(role.technologies),
            " ".join(role.achievements),
        ])
        for skill in _extract_skills_from_text(role_text):
            role_skill_map.setdefault(skill, set()).add(idx)

    # Determine recency for each skill based on role position
    # roles[0] is the most recent (first in resume = current/latest)
    def _recency_for_skill(skill: str) -> Literal["current_role", "previous_role", "historical", "unknown"]:
        indices = role_skill_map.get(skill, set())
        if not indices:
            return "unknown"
        min_idx = min(indices)  # lowest index = most recent
        if min_idx == 0:
            return "current_role"
        elif min_idx == 1:
            return "previous_role"
        else:
            return "historical"

    # Union of all skills (from roles + skills section)
    all_skill_names = set(role_skill_map.keys()) | skills_section_set

    resume_skills: list[ResumeSkill] = []
    for skill_name in sorted(all_skill_names):
        in_roles = skill_name in role_skill_map
        in_section = skill_name in skills_section_set

        if in_roles and in_section:
            depth = DepthLevel.APPLIED
        elif in_roles:
            depth = DepthLevel.USED
        else:
            depth = DepthLevel.MENTIONED

        recency = _recency_for_skill(skill_name)

        # Build source_context
        if in_roles:
            role_names = [roles[i].company for i in sorted(role_skill_map[skill_name])]
            source_context = "Used at: " + ", ".join(role_names)
        else:
            source_context = "Listed in skills section"

        resume_skills.append(ResumeSkill(
            name=skill_name,
            source_context=source_context,
            implied_depth=depth,
            recency=recency,
        ))

    # ------------------------------------------------------------------
    # Education
    # ------------------------------------------------------------------
    education: list[str] = []
    for key in sections:
        if "EDUCATION" in key:
            for line in sections[key].splitlines():
                line = line.strip()
                if line:
                    education.append(line)
            break

    # ------------------------------------------------------------------
    # Certifications
    # ------------------------------------------------------------------
    certifications: list[str] = []
    for key in sections:
        if "CERTIF" in key:
            for line in sections[key].splitlines():
                line = line.strip()
                if line:
                    certifications.append(line)
            break

    # ------------------------------------------------------------------
    # Total years experience (rough estimate from roles)
    # ------------------------------------------------------------------
    total_months = sum(r.duration_months or 0 for r in roles)
    total_years = round(total_months / 12, 1) if total_months else None

    return ResumeProfile(
        parsed_at=datetime.now(),
        source_file_hash="",  # caller sets this for file ingestion
        source_format=source_format,
        name=name,
        current_title=current_title,
        location=location,
        roles=roles,
        total_years_experience=total_years,
        skills=resume_skills,
        education=education,
        certifications=certifications,
        professional_summary=summary_text,
    )


def ingest_resume(path: Path) -> ResumeProfile:
    """
    Full pipeline: extract text, parse to ResumeProfile, set file hash.

    Args:
        path: Path to the resume file (.pdf, .docx, or .txt).

    Returns:
        A fully populated ResumeProfile with source_file_hash set.
    """
    suffix = path.suffix.lower().lstrip(".")
    if suffix not in ("pdf", "docx", "txt"):
        raise ValueError(f"Unsupported resume format: .{suffix}")

    text = extract_text_from_file(path)
    source_format: Literal["pdf", "docx", "txt"] = suffix  # type: ignore[assignment]
    profile = parse_resume_text(text, source_format=source_format)
    profile.source_file_hash = hash_file(path)
    return profile
