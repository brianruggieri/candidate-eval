"""
Deliverable generator for resume bullets, cover letters, and interview prep.

Uses ``claude --print`` CLI for high-quality generation. If the CLI is
unavailable or errors, ``ClaudeCLIError`` propagates to the caller — no
silent template fallbacks.
"""

from __future__ import annotations

from claude_candidate.claude_cli import ClaudeCLIError, call_claude
from claude_candidate.pii_gate import scrub_deliverable
from claude_candidate.schemas.fit_assessment import FitAssessment, SkillMatchDetail
from claude_candidate.schemas.merged_profile import MergedEvidenceProfile

__all__ = [
    "ClaudeCLIError",
    "generate_resume_bullets",
    "generate_cover_letter",
    "generate_interview_prep",
]

CLAUDE_TIMEOUT_SECONDS = 120

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

# Maximum number of bullet points to generate
MAX_BULLETS = 8

# Maximum strong matches to highlight in cover letter body
MAX_COVER_LETTER_HIGHLIGHTS = 3


# ---------------------------------------------------------------------------
# Claude CLI integration
# ---------------------------------------------------------------------------


def _call_claude(prompt: str) -> str:
    """Call Claude CLI. Raises ClaudeCLIError on any failure."""
    return call_claude(prompt, timeout=CLAUDE_TIMEOUT_SECONDS)


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
# Public API
# ---------------------------------------------------------------------------


def generate_resume_bullets(
    *,
    assessment: FitAssessment,
    profile: MergedEvidenceProfile | None = None,
) -> list[str]:
    """Generate tailored resume bullets from assessment data.

    Raises:
        ClaudeCLIError: If the Claude CLI is unavailable or returns an error.
    """
    prompt = _build_bullet_prompt(assessment, profile)
    result = _call_claude(prompt)
    bullets = _parse_bullet_lines(result)
    return [scrub_deliverable(bullet) for bullet in bullets]


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
    """Generate a personalized cover letter.

    Raises:
        ClaudeCLIError: If the Claude CLI is unavailable or returns an error.
    """
    prompt = _build_cover_letter_prompt(assessment, profile)
    return scrub_deliverable(_call_claude(prompt))


def generate_interview_prep(
    *,
    assessment: FitAssessment,
    profile: MergedEvidenceProfile | None = None,
) -> str:
    """Generate interview preparation notes.

    Raises:
        ClaudeCLIError: If the Claude CLI is unavailable or returns an error.
    """
    prompt = _build_interview_prompt(assessment, profile)
    return scrub_deliverable(_call_claude(prompt))
