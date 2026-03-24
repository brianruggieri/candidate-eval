"""Tests for the deliverable generator."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import patch

import pytest

from claude_candidate.claude_cli import ClaudeCLIError
from claude_candidate.generator import (
    CLAUDE_TIMEOUTS,
    DEFAULT_CLAUDE_TIMEOUT,
    _is_domain_mismatch,
    generate_cover_letter,
    generate_interview_prep,
    generate_narrative_verdict,
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


# ---------------------------------------------------------------------------
# TestGenerateNarrativeVerdict
# ---------------------------------------------------------------------------

SAMPLE_ASSESSMENT_DATA = {
    "company_name": "Acme Corp",
    "job_title": "Senior Python Engineer",
    "overall_grade": "B+",
    "strongest_match": "Python proficiency",
    "biggest_gap": "React experience",
    "skill_matches": [
        {
            "requirement": "Python proficiency",
            "match_status": "strong_match",
            "candidate_evidence": "20 sessions, deep expertise",
        },
        {
            "requirement": "REST APIs",
            "match_status": "strong_match",
            "candidate_evidence": "Built several production APIs",
        },
        {
            "requirement": "Docker",
            "match_status": "partial_match",
            "candidate_evidence": "Used Docker in CI pipelines",
        },
    ],
}

SAMPLE_COMPANY_RESEARCH = {
    "mission": "Making developer tools better",
    "values": ["innovation", "quality"],
    "culture_signals": ["collaborative", "remote-friendly"],
    "tech_philosophy": "Python-first, test-driven",
    "ai_native": False,
    "product_domains": ["developer-tooling"],
    "team_size_signal": "mid-size (50-500)",
}

SAMPLE_NARRATIVE_RESPONSE = json.dumps({
    "narrative": "Strong Python fit with deep backend expertise. "
                 "The candidate's API experience aligns well with Acme's developer tooling focus. "
                 "React experience gap may surface in frontend-heavy sprints.",
    "receptivity": "medium",
    "receptivity_reason": "Acme values innovation but is not explicitly AI-native, "
                          "so a transparent AI portfolio may intrigue but not guarantee traction.",
})


class TestGenerateNarrativeVerdict:
    def test_returns_structured_data(self):
        with patch("claude_candidate.generator.call_claude", return_value=SAMPLE_NARRATIVE_RESPONSE):
            result = generate_narrative_verdict(SAMPLE_ASSESSMENT_DATA, SAMPLE_COMPANY_RESEARCH)
        assert "narrative" in result
        assert "receptivity" in result
        assert "receptivity_reason" in result
        assert result["receptivity"] in ("high", "medium", "low")
        assert isinstance(result["narrative"], str)
        assert len(result["narrative"]) > 0

    def test_handles_code_fences(self):
        fenced = f"```json\n{SAMPLE_NARRATIVE_RESPONSE}\n```"
        with patch("claude_candidate.generator.call_claude", return_value=fenced):
            result = generate_narrative_verdict(SAMPLE_ASSESSMENT_DATA, SAMPLE_COMPANY_RESEARCH)
        assert result["receptivity"] == "medium"
        assert "Strong Python fit" in result["narrative"]

    def test_scrubs_pii_from_narrative(self):
        response_with_pii = json.dumps({
            "narrative": "Candidate is reachable at 555-123-4567 and has strong Python skills.",
            "receptivity": "high",
            "receptivity_reason": "AI-native company.",
        })
        with patch("claude_candidate.generator.call_claude", return_value=response_with_pii):
            result = generate_narrative_verdict(SAMPLE_ASSESSMENT_DATA, SAMPLE_COMPANY_RESEARCH)
        assert "555-123-4567" not in result["narrative"]
        assert "[PHONE]" in result["narrative"]

    def test_raises_on_invalid_json(self):
        with patch("claude_candidate.generator.call_claude", return_value="not valid json"):
            with pytest.raises(json.JSONDecodeError):
                generate_narrative_verdict(SAMPLE_ASSESSMENT_DATA, SAMPLE_COMPANY_RESEARCH)

    def test_handles_empty_research(self):
        with patch("claude_candidate.generator.call_claude", return_value=SAMPLE_NARRATIVE_RESPONSE):
            result = generate_narrative_verdict(SAMPLE_ASSESSMENT_DATA, {})
        assert "narrative" in result


# ---------------------------------------------------------------------------
# TestDomainMismatch / TestBulletPromptDomainFilter
# ---------------------------------------------------------------------------


def _make_match(requirement: str, matched_skill: str | None) -> SkillMatchDetail:
    return SkillMatchDetail(
        requirement=requirement,
        priority="must_have",
        match_status="strong_match",
        candidate_evidence="security practices: 138 sessions, expert depth",
        evidence_source=EvidenceSource.SESSIONS_ONLY,
        confidence=0.85,
        matched_skill=matched_skill,
    )


class TestDomainMismatch:
    def test_domain_mismatch_detected(self):
        """security matched to healthcare requirement is a mismatch."""
        match = _make_match(
            "Background in highly regulated industries — healthcare or financial services",
            "security",
        )
        assert _is_domain_mismatch(match) is True

    def test_no_mismatch_on_domain_skill(self):
        """A non-general skill matching a domain req is not flagged."""
        match = _make_match(
            "Experience in healthcare software",
            "healthcare-compliance",
        )
        assert _is_domain_mismatch(match) is False

    def test_no_mismatch_on_generic_req(self):
        """security matched to a plain security requirement is fine."""
        match = _make_match(
            "Strong security practices and auth experience",
            "security",
        )
        assert _is_domain_mismatch(match) is False

    def test_no_mismatch_when_matched_skill_is_none(self):
        """No matched_skill → no false positive."""
        match = _make_match(
            "Background in regulated industries",
            None,
        )
        assert _is_domain_mismatch(match) is False

    def test_no_mismatch_when_skill_equals_domain_keyword(self):
        """compliance skill on a plain compliance requirement is not a mismatch."""
        match = _make_match("Strong compliance background", "compliance")
        assert _is_domain_mismatch(match) is False


class TestBulletPromptDomainFilter:
    def test_domain_framing_stripped_from_mismatch(self):
        """When domain mismatch: prompt uses evidence text, not requirement text."""
        mismatch_match = _make_match(
            "Background in highly regulated industries — healthcare or financial services",
            "security",
        )
        clean_match = _make_match(
            "Strong Python proficiency",
            "python",
        )
        assessment = _make_assessment(skill_matches=[mismatch_match, clean_match])

        with patch("claude_candidate.generator.call_claude", return_value="- Bullet") as mock_call:
            generate_resume_bullets(assessment=assessment)
            prompt = mock_call.call_args[0][0]

        # The domain framing should NOT appear in the prompt
        assert "healthcare" not in prompt.lower()
        assert "financial services" not in prompt.lower()
        # Evidence text SHOULD appear
        assert "138 sessions" in prompt

    def test_clean_match_not_stripped(self):
        """Non-mismatch requirements are passed through unchanged."""
        clean_match = _make_match("Strong Python proficiency", "python")
        assessment = _make_assessment(skill_matches=[clean_match])

        with patch("claude_candidate.generator.call_claude", return_value="- Bullet") as mock_call:
            generate_resume_bullets(assessment=assessment)
            prompt = mock_call.call_args[0][0]

        assert "Strong Python proficiency" in prompt


# ---------------------------------------------------------------------------
# TestPerTypeTimeouts
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_assessment():
    return _make_assessment()


class TestPerTypeTimeouts:
    def test_resume_bullets_timeout(self):
        """resume-bullets uses the configured short timeout."""
        assert CLAUDE_TIMEOUTS["resume-bullets"] == 120

    def test_cover_letter_timeout(self):
        """cover-letter uses the configured long timeout."""
        assert CLAUDE_TIMEOUTS["cover-letter"] == 300

    def test_interview_prep_timeout(self):
        """interview-prep uses the configured long timeout."""
        assert CLAUDE_TIMEOUTS["interview-prep"] == 300

    def test_default_timeout_for_unknown_type(self):
        """Unknown deliverable type falls back to DEFAULT_CLAUDE_TIMEOUT."""
        assert DEFAULT_CLAUDE_TIMEOUT == 180

    def test_generate_resume_bullets_passes_correct_timeout(self, minimal_assessment):
        """generate_resume_bullets calls call_claude with resume-bullets timeout."""
        with patch("claude_candidate.generator.call_claude", return_value="- Bullet") as mock_call:
            generate_resume_bullets(assessment=minimal_assessment)
            _, kwargs = mock_call.call_args
            assert kwargs.get("timeout") == CLAUDE_TIMEOUTS["resume-bullets"]

    def test_generate_cover_letter_passes_correct_timeout(self, minimal_assessment):
        """generate_cover_letter calls call_claude with cover-letter timeout."""
        with patch("claude_candidate.generator.call_claude", return_value="Dear Hiring Manager") as mock_call:
            generate_cover_letter(assessment=minimal_assessment)
            _, kwargs = mock_call.call_args
            assert kwargs.get("timeout") == CLAUDE_TIMEOUTS["cover-letter"]

    def test_generate_interview_prep_passes_correct_timeout(self, minimal_assessment):
        """generate_interview_prep calls call_claude with interview-prep timeout."""
        with patch("claude_candidate.generator.call_claude", return_value="## Technical Topics") as mock_call:
            generate_interview_prep(assessment=minimal_assessment)
            _, kwargs = mock_call.call_args
            assert kwargs.get("timeout") == CLAUDE_TIMEOUTS["interview-prep"]

    def test_site_narrative_empty_type_resolves_to_default_timeout(self):
        """Empty deliverable_type (generate_site_narrative's path) uses DEFAULT_CLAUDE_TIMEOUT.

        generate_site_narrative calls _call_claude(prompt) with no type string, which
        defaults to "" — verify that resolves to DEFAULT_CLAUDE_TIMEOUT via CLAUDE_TIMEOUTS.get.
        """
        assert CLAUDE_TIMEOUTS.get("", DEFAULT_CLAUDE_TIMEOUT) == DEFAULT_CLAUDE_TIMEOUT
