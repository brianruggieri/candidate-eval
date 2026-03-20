"""Tests for the deliverable generator."""

from __future__ import annotations

from datetime import datetime
from unittest.mock import patch

import pytest

from claude_candidate.claude_cli import ClaudeCLIError
from claude_candidate.generator import (
    generate_cover_letter,
    generate_interview_prep,
    generate_resume_bullets,
)
from claude_candidate.schemas.fit_assessment import (
    DimensionScore,
    FitAssessment,
    SkillMatchDetail,
)
from claude_candidate.schemas.merged_profile import EvidenceSource


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_skill_match(
    *,
    requirement: str = "Python proficiency",
    priority: str = "must_have",
    match_status: str = "strong_match",
    evidence: str = "Corroborated by both resume and sessions. 20 sessions. depth: deep",
    confidence: float = 0.9,
) -> SkillMatchDetail:
    return SkillMatchDetail(
        requirement=requirement,
        priority=priority,
        match_status=match_status,
        candidate_evidence=evidence,
        evidence_source=EvidenceSource.CORROBORATED,
        confidence=confidence,
    )


SAMPLE_SKILL_MATCHES = [
    _make_skill_match(
        requirement="Python proficiency",
        priority="must_have",
        match_status="strong_match",
    ),
    _make_skill_match(
        requirement="React experience",
        priority="strong_preference",
        match_status="partial_match",
        confidence=0.6,
    ),
    _make_skill_match(
        requirement="Docker & Kubernetes",
        priority="nice_to_have",
        match_status="strong_match",
        confidence=0.85,
    ),
]


def _make_assessment(
    *,
    company: str = "Acme Corp",
    title: str = "Senior Software Engineer",
    skill_matches: list[SkillMatchDetail] | None = None,
) -> FitAssessment:
    matches = skill_matches or SAMPLE_SKILL_MATCHES
    return FitAssessment(
        assessment_id="test-001",
        assessed_at=datetime(2026, 3, 15),
        job_title=title,
        company_name=company,
        posting_url="https://example.com/job/123",
        source="linkedin",
        overall_score=0.78,
        overall_grade="B+",
        overall_summary="Good fit overall.",
        skill_match=DimensionScore(
            dimension="skill_match",
            score=0.82,
            grade="B+",
            summary="Strong skill match.",
            details=["[+] Python: strong match"],
        ),
        mission_alignment=DimensionScore(
            dimension="mission_alignment",
            score=0.7,
            grade="B-",
            summary="Moderate mission alignment.",
            details=["Tech overlap: python, react"],
        ),
        culture_fit=DimensionScore(
            dimension="culture_fit",
            score=0.65,
            grade="C+",
            summary="Moderate culture fit.",
            details=["Iterative refinement aligns"],
        ),
        skill_matches=matches,
        must_have_coverage="1/1 must-haves met",
        strongest_match="Python proficiency",
        biggest_gap="None — all requirements addressed",
        resume_gaps_discovered=[],
        resume_unverified=[],
        company_profile_summary="Acme Corp builds developer tools.",
        company_enrichment_quality="good",
        should_apply="yes",
        action_items=["Generate full application package for this role"],
        profile_hash="abc123",
        time_to_assess_seconds=1.5,
    )


# ---------------------------------------------------------------------------
# TestGenerateResumeBullets
# ---------------------------------------------------------------------------


class TestGenerateResumeBullets:
    def test_produces_bullet_list(self):
        from claude_candidate.generator import generate_resume_bullets

        assessment = _make_assessment()
        claude_output = "- Engineered Python services handling 10k RPM\n- Led React migration"
        with patch("claude_candidate.generator.call_claude", return_value=claude_output):
            bullets = generate_resume_bullets(assessment=assessment)
        assert isinstance(bullets, list)
        assert len(bullets) > 0

    def test_bullets_are_nonempty_strings(self):
        from claude_candidate.generator import generate_resume_bullets

        assessment = _make_assessment()
        claude_output = "- Python backend\n- React frontend\n- Docker deploy"
        with patch("claude_candidate.generator.call_claude", return_value=claude_output):
            bullets = generate_resume_bullets(assessment=assessment)
        for bullet in bullets:
            assert isinstance(bullet, str)
            assert len(bullet.strip()) > 0

    def test_works_without_profile(self):
        from claude_candidate.generator import generate_resume_bullets

        assessment = _make_assessment()
        with patch("claude_candidate.generator.call_claude", return_value="- Bullet point"):
            bullets = generate_resume_bullets(assessment=assessment, profile=None)
        assert isinstance(bullets, list)
        assert len(bullets) > 0

    def test_raises_claude_cli_error_on_failure(self):
        from claude_candidate.generator import generate_resume_bullets

        assessment = _make_assessment()
        with patch(
            "claude_candidate.generator.call_claude",
            side_effect=ClaudeCLIError("CLI not found"),
        ):
            with pytest.raises(ClaudeCLIError):
                generate_resume_bullets(assessment=assessment)


# ---------------------------------------------------------------------------
# TestGenerateCoverLetter
# ---------------------------------------------------------------------------


class TestGenerateCoverLetter:
    def test_produces_nonempty_string(self):
        from claude_candidate.generator import generate_cover_letter

        assessment = _make_assessment()
        fake_letter = "Dear Hiring Manager, I am excited to apply for this role at Acme Corp..."
        with patch("claude_candidate.generator.call_claude", return_value=fake_letter):
            letter = generate_cover_letter(assessment=assessment)
        assert isinstance(letter, str)
        assert len(letter) > 0

    def test_returns_claude_output_verbatim(self):
        from claude_candidate.generator import generate_cover_letter

        assessment = _make_assessment(company="WidgetCo")
        fake_letter = "Cover letter for WidgetCo mentioning Staff Backend Engineer position."
        with patch("claude_candidate.generator.call_claude", return_value=fake_letter):
            letter = generate_cover_letter(assessment=assessment)
        assert letter == fake_letter

    def test_no_template_placeholders(self):
        from claude_candidate.generator import generate_cover_letter

        assessment = _make_assessment()
        fake_letter = "A real cover letter with no placeholders."
        with patch("claude_candidate.generator.call_claude", return_value=fake_letter):
            letter = generate_cover_letter(assessment=assessment)
        assert "{" not in letter
        assert "}" not in letter

    def test_raises_claude_cli_error_on_failure(self):
        from claude_candidate.generator import generate_cover_letter

        assessment = _make_assessment()
        with patch(
            "claude_candidate.generator.call_claude",
            side_effect=ClaudeCLIError("timed out"),
        ):
            with pytest.raises(ClaudeCLIError):
                generate_cover_letter(assessment=assessment)


# ---------------------------------------------------------------------------
# TestGenerateInterviewPrep
# ---------------------------------------------------------------------------


class TestGenerateInterviewPrep:
    def test_produces_nonempty_string(self):
        from claude_candidate.generator import generate_interview_prep

        assessment = _make_assessment()
        fake_prep = "## Technical Discussion Points\n- Python: strong\n## Questions to Ask\n- ?"
        with patch("claude_candidate.generator.call_claude", return_value=fake_prep):
            prep = generate_interview_prep(assessment=assessment)
        assert isinstance(prep, str)
        assert len(prep) > 0

    def test_returns_claude_output_verbatim(self):
        from claude_candidate.generator import generate_interview_prep

        assessment = _make_assessment()
        fake_prep = "Interview prep content here."
        with patch("claude_candidate.generator.call_claude", return_value=fake_prep):
            prep = generate_interview_prep(assessment=assessment)
        assert prep == fake_prep

    def test_raises_claude_cli_error_on_failure(self):
        from claude_candidate.generator import generate_interview_prep

        assessment = _make_assessment()
        with patch(
            "claude_candidate.generator.call_claude",
            side_effect=ClaudeCLIError("CLI not found"),
        ):
            with pytest.raises(ClaudeCLIError):
                generate_interview_prep(assessment=assessment)


# ---------------------------------------------------------------------------
# TestParseBulletLines
# ---------------------------------------------------------------------------


class TestParseBulletLines:
    """Unit tests for the bullet-line parser (pure function, no CLI needed)."""

    def test_strips_dash_prefix(self):
        from claude_candidate.generator import _parse_bullet_lines

        result = _parse_bullet_lines("- First bullet\n- Second bullet")
        assert result == ["First bullet", "Second bullet"]

    def test_skips_blank_lines(self):
        from claude_candidate.generator import _parse_bullet_lines

        result = _parse_bullet_lines("- Bullet\n\n- Another")
        assert len(result) == 2

    def test_handles_no_dash_prefix(self):
        from claude_candidate.generator import _parse_bullet_lines

        result = _parse_bullet_lines("Just a line\nAnother line")
        assert len(result) == 2


# ---------------------------------------------------------------------------
# TestPIIScrubbing
# ---------------------------------------------------------------------------


class TestPIIScrubbing:
    """Verify that PII is scrubbed from all hiring-manager-facing deliverables."""

    def test_cover_letter_scrubs_phone_number(self):
        assessment = _make_assessment()
        fake_letter = "Reach me at 555-123-4567 for discussion."
        with patch("claude_candidate.generator.call_claude", return_value=fake_letter):
            letter = generate_cover_letter(assessment=assessment)
        assert "555-123-4567" not in letter
        assert "[PHONE]" in letter

    def test_cover_letter_scrubs_ssn(self):
        assessment = _make_assessment()
        fake_letter = "My SSN is 123-45-6789 for verification."
        with patch("claude_candidate.generator.call_claude", return_value=fake_letter):
            letter = generate_cover_letter(assessment=assessment)
        assert "123-45-6789" not in letter
        assert "[SSN]" in letter

    def test_cover_letter_scrubs_credit_card(self):
        assessment = _make_assessment()
        fake_letter = "Card number 4111 1111 1111 1111 on file."
        with patch("claude_candidate.generator.call_claude", return_value=fake_letter):
            letter = generate_cover_letter(assessment=assessment)
        assert "4111 1111 1111 1111" not in letter
        assert "[CREDIT_CARD]" in letter

    def test_interview_prep_scrubs_phone_number(self):
        assessment = _make_assessment()
        fake_prep = "Contact recruiter at 800-555-0199 before interview."
        with patch("claude_candidate.generator.call_claude", return_value=fake_prep):
            prep = generate_interview_prep(assessment=assessment)
        assert "800-555-0199" not in prep
        assert "[PHONE]" in prep

    def test_resume_bullets_scrubs_phone_number(self):
        assessment = _make_assessment()
        fake_output = "- Led team; call 212-555-9876 for reference"
        with patch("claude_candidate.generator.call_claude", return_value=fake_output):
            bullets = generate_resume_bullets(assessment=assessment)
        full_text = " ".join(bullets)
        assert "212-555-9876" not in full_text
        assert "[PHONE]" in full_text

    def test_clean_text_passes_through_unchanged(self):
        """Text with no PII should be returned verbatim (modulo whitespace)."""
        assessment = _make_assessment()
        clean = "Strong Python engineer with 10 years of backend experience."
        with patch("claude_candidate.generator.call_claude", return_value=clean):
            letter = generate_cover_letter(assessment=assessment)
        assert letter == clean
