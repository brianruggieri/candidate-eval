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

SECTION_HEADERS = re.compile(
    r"^\s*(SUMMARY|OBJECTIVE|EXPERIENCE|WORK EXPERIENCE|EMPLOYMENT|SKILLS|TECHNICAL SKILLS|"
    r"EDUCATION|CERTIFICATIONS?|CERTIFICATIONS? & LICENSES?|PROJECTS?|AWARDS?|PUBLICATIONS?)\s*$",
    re.IGNORECASE,
)

ROLE_SEPARATOR = re.compile(
    r"^(.+?)\s*[|\-–—]\s*(.+)$",
)

DATE_RANGE = re.compile(
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}|\d{4})"
    r"\s*[-–—to]+\s*"
    r"((?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4}|\d{4}|Present|present|Current|current)",
    re.IGNORECASE,
)

LOCATION_PATTERN = re.compile(
    r"\b([A-Z][a-z]+(?: [A-Z][a-z]+)*),\s*([A-Z]{2})\b"
)

BULLET_LINE = re.compile(r"^\s*[-•*]\s+(.+)$")


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
    """
    sections: dict[str, list[str]] = {"HEADER": []}
    current = "HEADER"
    for line in text.splitlines():
        if SECTION_HEADERS.match(line):
            current = line.strip().upper()
            sections[current] = []
        else:
            sections.setdefault(current, []).append(line)
    return {k: "\n".join(v) for k, v in sections.items()}


# ---------------------------------------------------------------------------
# Role parsing
# ---------------------------------------------------------------------------

def _parse_roles(experience_text: str) -> list[ResumeRole]:
    """Parse the EXPERIENCE section into ResumeRole objects."""
    roles: list[ResumeRole] = []
    lines = [ln for ln in experience_text.splitlines()]

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            i += 1
            continue

        # Try to detect a role header: "Title | Company" or "Title - Company"
        role_match = ROLE_SEPARATOR.match(line)
        if role_match:
            title_part = role_match.group(1).strip()
            company_part = role_match.group(2).strip()

            # Look ahead for date range
            start_date = "unknown"
            end_date = None
            j = i + 1
            while j < len(lines) and j < i + 3:
                next_line = lines[j].strip()
                date_match = DATE_RANGE.search(next_line)
                if date_match:
                    start_date = _parse_date(date_match.group(1))
                    raw_end = date_match.group(2)
                    if raw_end.lower() in ("present", "current"):
                        end_date = None
                    else:
                        end_date = _parse_date(raw_end)
                    j += 1
                    break
                j += 1

            # Collect bullet points and Technologies lines
            bullets: list[str] = []
            technologies: list[str] = []
            k = j
            while k < len(lines):
                bl = lines[k].strip()
                if not bl:
                    k += 1
                    # Allow a single blank line gap
                    if k < len(lines) and lines[k].strip():
                        next_content = lines[k].strip()
                        # Stop if this looks like a new role header
                        if ROLE_SEPARATOR.match(next_content) or DATE_RANGE.search(next_content):
                            break
                    else:
                        break
                    continue
                # Stop at next role header
                if ROLE_SEPARATOR.match(bl) and k > i + 1:
                    break
                bullet_match = BULLET_LINE.match(lines[k])
                if bullet_match:
                    content = bullet_match.group(1).strip()
                    if content.lower().startswith("technologies:"):
                        tech_str = content[len("Technologies:"):].strip()
                        technologies = [t.strip() for t in tech_str.split(",") if t.strip()]
                    else:
                        bullets.append(content)
                k += 1

            duration = _months_between(start_date, end_date)

            roles.append(ResumeRole(
                title=title_part,
                company=company_part,
                start_date=start_date,
                end_date=end_date,
                duration_months=duration,
                description=" ".join(bullets),
                technologies=technologies,
                achievements=bullets,
            ))
            i = k
        else:
            i += 1

    return roles


# ---------------------------------------------------------------------------
# Skills section parsing
# ---------------------------------------------------------------------------

def _parse_skills_section(skills_text: str) -> set[str]:
    """
    Extract canonical skill names from the SKILLS section.

    The section is a comma/newline-separated list of skills.
    """
    found: set[str] = set()
    tokens = re.split(r"[,\n]", skills_text)
    for token in tokens:
        token = token.strip().rstrip(".,;")
        if not token:
            continue
        canonical = _normalize_skill(token)
        if canonical:
            found.add(canonical)
        # Also try extracting known skills from the token
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
        import pdfplumber
        pages: list[str] = []
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages.append(text)
        return "\n".join(pages)

    if suffix == ".docx":
        from docx import Document
        doc = Document(str(path))
        paragraphs = [p.text for p in doc.paragraphs]
        return "\n".join(paragraphs)

    raise ValueError(f"Unsupported file format: {suffix!r}. Supported: .pdf, .docx, .txt")


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
    sections = _split_sections(text)

    # ------------------------------------------------------------------
    # Identity: name, title, location from header lines
    # ------------------------------------------------------------------
    header_lines = [ln.strip() for ln in sections.get("HEADER", "").splitlines() if ln.strip()]

    name: str | None = None
    current_title: str | None = None
    location: str | None = None

    if header_lines:
        # First non-empty line is typically the name
        name = header_lines[0]
        if len(header_lines) > 1:
            current_title = header_lines[1]
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
    for key in sections:
        if "EXPERIENCE" in key or "EMPLOYMENT" in key:
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
