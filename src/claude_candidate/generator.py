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
    "generate_narrative_verdict",
    "generate_site_narrative",
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


# ---------------------------------------------------------------------------
# Narrative verdict
# ---------------------------------------------------------------------------

NARRATIVE_TIMEOUT_SECONDS = 30


def generate_narrative_verdict(assessment_data: dict, company_research: dict) -> dict:
    """Generate narrative verdict and receptivity signal via Claude.

    Returns dict with keys: narrative, receptivity, receptivity_reason
    """
    import json as _json

    # Build context from assessment data
    company = assessment_data.get("company_name", "Unknown")
    title = assessment_data.get("job_title", "Unknown")
    grade = assessment_data.get("overall_grade", "N/A")
    strongest = assessment_data.get("strongest_match", "N/A")
    biggest_gap = assessment_data.get("biggest_gap", "N/A")

    # Top 5 skill matches
    skill_matches = assessment_data.get("skill_matches", [])
    top_skills = skill_matches[:5]
    skills_text = "\n".join(
        f"- {m.get('requirement', 'N/A')} ({m.get('match_status', 'N/A')}): "
        f"{m.get('candidate_evidence', 'N/A')}"
        for m in top_skills
    )

    # Company research context
    research_text = "\n".join(
        f"- {k}: {v}" for k, v in company_research.items() if v
    )

    prompt = (
        "You are evaluating a candidate's fit for a specific role. "
        "Return ONLY valid JSON with these three keys:\n"
        '- "narrative": 2-3 sentences — why this is or isn\'t a good fit, '
        "the candidate's strongest angle, and what gap is most likely to come up\n"
        '- "receptivity": "high", "medium", or "low" — would this company '
        "value a transparent AI-powered portfolio application?\n"
        '- "receptivity_reason": one sentence explaining the receptivity rating\n\n'
        f"Company: {company}\n"
        f"Job title: {title}\n"
        f"Overall grade: {grade}\n"
        f"Strongest match: {strongest}\n"
        f"Biggest gap: {biggest_gap}\n\n"
        f"Top skill matches:\n{skills_text}\n\n"
        f"Company research:\n{research_text}\n"
    )

    raw = call_claude(prompt, timeout=NARRATIVE_TIMEOUT_SECONDS)

    # Strip code fences if present
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
    if cleaned.endswith("```"):
        cleaned = cleaned.rsplit("```", 1)[0]
    cleaned = cleaned.strip()

    parsed = _json.loads(cleaned)

    # Scrub PII from the narrative text
    if parsed.get("narrative"):
        parsed["narrative"] = scrub_deliverable(parsed["narrative"])

    return parsed


# ---------------------------------------------------------------------------
# Site narrative
# ---------------------------------------------------------------------------


def generate_site_narrative(assessment_data: dict, company_research: dict) -> str:
    """Generate a 150-250 word pitch narrative for the cover letter site page.

    The output is first-person, confident, and evidence-grounded — not a
    traditional cover letter tone.  Think "what I would bring to this role"
    rather than "I would love the opportunity."

    PII scrubbing is applied before returning.

    Raises:
        ClaudeCLIError: If the Claude CLI is unavailable or returns an error.
    """
    company = assessment_data.get("company_name", "Unknown")
    title = assessment_data.get("job_title", "Unknown")
    grade = assessment_data.get("overall_grade", "N/A")
    strongest = assessment_data.get("strongest_match", "N/A")
    biggest_gap = assessment_data.get("biggest_gap", "N/A")

    skill_matches = assessment_data.get("skill_matches", [])
    top_skills = skill_matches[:5]
    skills_text = "\n".join(
        f"- {m.get('requirement', 'N/A')} ({m.get('match_status', 'N/A')}): "
        f"{m.get('candidate_evidence', 'N/A')}"
        for m in top_skills
    )

    research_text = "\n".join(
        f"- {k}: {v}" for k, v in company_research.items() if v
    )

    prompt = (
        "Write a first-person pitch paragraph (150-250 words) explaining why "
        "I am a strong fit for this role. This is for a personal application "
        "page, not a formal cover letter.\n\n"
        "Rules:\n"
        "- Lead with the strongest match\n"
        "- Be specific — reference actual skills and evidence\n"
        "- Confident but not arrogant\n"
        "- No fluff, no 'I would love the opportunity' language\n"
        "- No 'Dear Hiring Manager' or letter formatting\n"
        "- 150-250 words, plain prose\n\n"
        f"Company: {company}\n"
        f"Job title: {title}\n"
        f"Overall grade: {grade}\n"
        f"Strongest match: {strongest}\n"
        f"Biggest gap: {biggest_gap}\n\n"
        f"Top skill matches:\n{skills_text}\n\n"
        f"Company research:\n{research_text}\n"
    )

    raw = _call_claude(prompt)
    return scrub_deliverable(raw.strip())
