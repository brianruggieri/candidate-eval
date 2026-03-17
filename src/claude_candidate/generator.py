"""
Deliverable generator for resume bullets, cover letters, and interview prep.

Uses ``claude --print`` CLI for high-quality generation with template-based
fallback when the CLI is unavailable or errors out.
"""

from __future__ import annotations

import subprocess

from claude_candidate.schemas.fit_assessment import FitAssessment, SkillMatchDetail
from claude_candidate.schemas.merged_profile import MergedEvidenceProfile

CLAUDE_TIMEOUT_SECONDS = 60

# Match statuses considered "positive" evidence
POSITIVE_STATUSES = {"strong_match", "exceeds", "partial_match"}

# Match status display labels
STATUS_LABELS: dict[str, str] = {
    "exceeds": "exceeding requirements",
    "strong_match": "strong proficiency",
    "partial_match": "working knowledge",
    "adjacent": "related experience",
    "no_evidence": "no direct evidence",
}

# Template opening for cover letters
COVER_LETTER_OPENING = "I am excited to apply for the {title} position at {company}."

# Template closing for cover letters
COVER_LETTER_CLOSING = (
    "I would welcome the opportunity to discuss how my background aligns "
    "with your team's needs. Thank you for your consideration."
)

# Maximum number of bullet points to generate
MAX_BULLETS = 8

# Maximum strong matches to highlight in cover letter body
MAX_COVER_LETTER_HIGHLIGHTS = 3


# ---------------------------------------------------------------------------
# Claude CLI integration
# ---------------------------------------------------------------------------


def _try_claude_generation(prompt: str) -> str | None:
    """Try Claude CLI, return None on failure."""
    try:
        result = subprocess.run(
            ["claude", "--print", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=CLAUDE_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None
        output = result.stdout.strip()
        return output if output else None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


# ---------------------------------------------------------------------------
# Prompt builders
# ---------------------------------------------------------------------------


def _build_bullet_prompt(
    assessment: FitAssessment,
    profile: MergedEvidenceProfile | None,
) -> str:
    """Build a prompt for Claude to generate resume bullets."""
    matches_text = _format_matches_for_prompt(assessment.skill_matches)
    return (
        f"Generate tailored resume bullet points for a {assessment.job_title} "
        f"role at {assessment.company_name}.\n\n"
        f"Skill matches:\n{matches_text}\n\n"
        "Format: action verb + specific achievement + technology context. "
        "Return only the bullet points, one per line, prefixed with a dash."
    )


def _build_cover_letter_prompt(
    assessment: FitAssessment,
    profile: MergedEvidenceProfile | None,
) -> str:
    """Build a prompt for Claude to generate a cover letter."""
    matches_text = _format_matches_for_prompt(assessment.skill_matches)
    return (
        f"Write a professional cover letter for a {assessment.job_title} "
        f"position at {assessment.company_name}.\n\n"
        f"Candidate fit: {assessment.overall_summary}\n"
        f"Skill matches:\n{matches_text}\n\n"
        "Tone: professional but authentic. Length: 300-500 words. "
        "Reference specific skills and evidence. Do not use placeholders."
    )


def _build_interview_prompt(
    assessment: FitAssessment,
    profile: MergedEvidenceProfile | None,
) -> str:
    """Build a prompt for Claude to generate interview prep notes."""
    matches_text = _format_matches_for_prompt(assessment.skill_matches)
    return (
        f"Generate interview preparation notes for a {assessment.job_title} "
        f"role at {assessment.company_name}.\n\n"
        f"Skill matches:\n{matches_text}\n\n"
        "Organize by: Technical Discussion Points, Behavioral Examples, "
        "and Questions to Ask. Reference specific evidence."
    )


def _format_matches_for_prompt(matches: list[SkillMatchDetail]) -> str:
    """Format skill matches into a readable string for prompts."""
    lines = []
    for m in matches:
        lines.append(
            f"- {m.requirement} ({m.match_status}): {m.candidate_evidence}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Template fallbacks
# ---------------------------------------------------------------------------


def _build_bullet_from_match(match: SkillMatchDetail) -> str:
    """Create a single resume bullet from a skill match."""
    status_label = STATUS_LABELS.get(match.match_status, "experience")
    return (
        f"Demonstrated {status_label} in {match.requirement}, "
        f"backed by {match.evidence_source.value.replace('_', ' ')} evidence"
    )


def _build_talking_point(match: SkillMatchDetail) -> str:
    """Create a talking point for interview prep."""
    status_label = STATUS_LABELS.get(match.match_status, "experience")
    return (
        f"{match.requirement}: {status_label} — "
        f"{match.candidate_evidence}"
    )


def _template_resume_bullets(assessment: FitAssessment) -> list[str]:
    """Template-based fallback for resume bullets."""
    positive = [
        m for m in assessment.skill_matches
        if m.match_status in POSITIVE_STATUSES
    ]
    if not positive:
        positive = assessment.skill_matches[:MAX_BULLETS]
    return [_build_bullet_from_match(m) for m in positive[:MAX_BULLETS]]


def _template_cover_letter(assessment: FitAssessment) -> str:
    """Template-based fallback for cover letter."""
    opening = COVER_LETTER_OPENING.format(
        title=assessment.job_title,
        company=assessment.company_name,
    )
    body_paragraphs = _build_cover_body(assessment)
    closing = COVER_LETTER_CLOSING
    return f"{opening}\n\n{body_paragraphs}\n\n{closing}"


def _build_cover_body(assessment: FitAssessment) -> str:
    """Build the body paragraphs of a template cover letter."""
    strong = [
        m for m in assessment.skill_matches
        if m.match_status in ("strong_match", "exceeds")
    ][:MAX_COVER_LETTER_HIGHLIGHTS]
    if not strong:
        strong = assessment.skill_matches[:MAX_COVER_LETTER_HIGHLIGHTS]

    lines = []
    lines.append(
        f"With a track record aligned to the requirements of this "
        f"{assessment.job_title} role, I bring a combination of skills "
        f"that match what {assessment.company_name} is looking for."
    )
    for match in strong:
        status_label = STATUS_LABELS.get(match.match_status, "experience")
        lines.append(
            f"In {match.requirement}, I have demonstrated "
            f"{status_label}, supported by "
            f"{match.evidence_source.value.replace('_', ' ')} evidence."
        )
    lines.append(
        f"Overall, my profile represents a {assessment.overall_grade} fit "
        f"for this position, with {assessment.must_have_coverage}."
    )
    return "\n\n".join(lines)


def _template_interview_prep(assessment: FitAssessment) -> str:
    """Template-based fallback for interview prep."""
    sections = [
        _build_technical_section(assessment),
        _build_behavioral_section(assessment),
        _build_questions_section(assessment),
    ]
    return "\n\n".join(sections)


def _build_technical_section(assessment: FitAssessment) -> str:
    """Build the Technical Discussion Points section."""
    lines = ["## Technical Discussion Points"]
    for match in assessment.skill_matches:
        lines.append(f"- {_build_talking_point(match)}")
    return "\n".join(lines)


def _build_behavioral_section(assessment: FitAssessment) -> str:
    """Build the Behavioral Examples section."""
    lines = ["## Behavioral Examples"]
    strong = [
        m for m in assessment.skill_matches
        if m.match_status in ("strong_match", "exceeds")
    ]
    if strong:
        lines.append(
            f"- Problem Solving: Demonstrated depth across "
            f"{len(strong)} requirement areas with strong evidence"
        )
    gaps = [
        m for m in assessment.skill_matches
        if m.match_status == "no_evidence"
    ]
    if gaps:
        gap_names = ", ".join(g.requirement for g in gaps[:3])
        lines.append(
            f"- Growth Mindset: Opportunity to discuss learning "
            f"plans for {gap_names}"
        )
    if len(lines) == 1:
        lines.append("- Discuss specific projects and outcomes from experience")
    return "\n".join(lines)


def _build_questions_section(assessment: FitAssessment) -> str:
    """Build the Questions to Ask section."""
    lines = ["## Questions to Ask"]
    lines.append(
        f"- How does the {assessment.job_title} role contribute to "
        f"{assessment.company_name}'s current priorities?"
    )
    tech_skills = [
        m.requirement for m in assessment.skill_matches
        if m.match_status in ("strong_match", "exceeds")
    ]
    if tech_skills:
        lines.append(
            f"- What does the tech stack look like for "
            f"{tech_skills[0]} work on the team?"
        )
    lines.append(
        "- What does a successful first 90 days look like in this role?"
    )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_resume_bullets(
    *,
    assessment: FitAssessment,
    profile: MergedEvidenceProfile | None = None,
) -> list[str]:
    """Generate tailored resume bullets from assessment data."""
    prompt = _build_bullet_prompt(assessment, profile)
    claude_result = _try_claude_generation(prompt)
    if claude_result:
        return _parse_bullet_lines(claude_result)
    return _template_resume_bullets(assessment)


def _parse_bullet_lines(text: str) -> list[str]:
    """Parse Claude output into a list of bullet strings."""
    lines = [
        line.lstrip("- ").strip()
        for line in text.splitlines()
        if line.strip() and line.strip() != "-"
    ]
    return [line for line in lines if line]


def generate_cover_letter(
    *,
    assessment: FitAssessment,
    profile: MergedEvidenceProfile | None = None,
) -> str:
    """Generate a personalized cover letter."""
    prompt = _build_cover_letter_prompt(assessment, profile)
    claude_result = _try_claude_generation(prompt)
    if claude_result:
        return claude_result
    return _template_cover_letter(assessment)


def generate_interview_prep(
    *,
    assessment: FitAssessment,
    profile: MergedEvidenceProfile | None = None,
) -> str:
    """Generate interview preparation notes."""
    prompt = _build_interview_prompt(assessment, profile)
    claude_result = _try_claude_generation(prompt)
    if claude_result:
        return claude_result
    return _template_interview_prep(assessment)
