"""Tests for the deliverable generator."""

from __future__ import annotations

from datetime import datetime


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
        bullets = generate_resume_bullets(assessment=assessment)
        assert isinstance(bullets, list)
        assert len(bullets) > 0

    def test_bullets_reference_skills(self):
        from claude_candidate.generator import generate_resume_bullets

        assessment = _make_assessment()
        bullets = generate_resume_bullets(assessment=assessment)
        combined = " ".join(bullets).lower()
        # At least one skill from the matches should appear
        assert "python" in combined or "react" in combined or "docker" in combined

    def test_bullets_are_nonempty_strings(self):
        from claude_candidate.generator import generate_resume_bullets

        assessment = _make_assessment()
        bullets = generate_resume_bullets(assessment=assessment)
        for bullet in bullets:
            assert isinstance(bullet, str)
            assert len(bullet.strip()) > 0

    def test_works_without_profile(self):
        from claude_candidate.generator import generate_resume_bullets

        assessment = _make_assessment()
        bullets = generate_resume_bullets(assessment=assessment, profile=None)
        assert isinstance(bullets, list)
        assert len(bullets) > 0


# ---------------------------------------------------------------------------
# TestGenerateCoverLetter
# ---------------------------------------------------------------------------


class TestGenerateCoverLetter:
    def test_produces_nonempty_string(self):
        from claude_candidate.generator import generate_cover_letter

        assessment = _make_assessment()
        letter = generate_cover_letter(assessment=assessment)
        assert isinstance(letter, str)
        assert len(letter) > 0

    def test_contains_company_name(self):
        from claude_candidate.generator import generate_cover_letter

        assessment = _make_assessment(company="WidgetCo")
        letter = generate_cover_letter(assessment=assessment)
        assert "WidgetCo" in letter

    def test_contains_job_title(self):
        from claude_candidate.generator import generate_cover_letter

        assessment = _make_assessment(title="Staff Backend Engineer")
        letter = generate_cover_letter(assessment=assessment)
        assert "Staff Backend Engineer" in letter

    def test_no_template_placeholders(self):
        from claude_candidate.generator import generate_cover_letter

        assessment = _make_assessment()
        letter = generate_cover_letter(assessment=assessment)
        assert "{" not in letter
        assert "}" not in letter

    def test_reasonable_length(self):
        from claude_candidate.generator import generate_cover_letter

        assessment = _make_assessment()
        letter = generate_cover_letter(assessment=assessment)
        word_count = len(letter.split())
        assert word_count >= 50
        assert word_count <= 2000


# ---------------------------------------------------------------------------
# TestGenerateInterviewPrep
# ---------------------------------------------------------------------------


class TestGenerateInterviewPrep:
    def test_produces_nonempty_string(self):
        from claude_candidate.generator import generate_interview_prep

        assessment = _make_assessment()
        prep = generate_interview_prep(assessment=assessment)
        assert isinstance(prep, str)
        assert len(prep) > 0

    def test_contains_technical_section(self):
        from claude_candidate.generator import generate_interview_prep

        assessment = _make_assessment()
        prep = generate_interview_prep(assessment=assessment)
        assert "Technical" in prep

    def test_contains_questions_section(self):
        from claude_candidate.generator import generate_interview_prep

        assessment = _make_assessment()
        prep = generate_interview_prep(assessment=assessment)
        assert "Questions" in prep

    def test_references_skills(self):
        from claude_candidate.generator import generate_interview_prep

        assessment = _make_assessment()
        prep = generate_interview_prep(assessment=assessment).lower()
        assert "python" in prep or "react" in prep or "docker" in prep


# ---------------------------------------------------------------------------
# TestTryClaude
# ---------------------------------------------------------------------------


class TestTryClaude:
    def test_returns_none_on_missing_cli(self, fp):
        from claude_candidate.generator import _try_claude_generation

        fp.register_subprocess(
            ["claude", "--print", "-p", fp.any()],
            returncode=1,
            stdout="",
            stderr="command not found",
        )
        result = _try_claude_generation("test prompt")
        assert result is None

    def test_returns_none_on_timeout(self, fp):
        import subprocess

        from claude_candidate.generator import _try_claude_generation

        fp.register_subprocess(
            ["claude", "--print", "-p", fp.any()],
            callback=lambda _: (_ for _ in ()).throw(subprocess.TimeoutExpired("claude", 60)),
        )
        result = _try_claude_generation("test prompt")
        assert result is None

    def test_returns_stdout_on_success(self, fp):
        from claude_candidate.generator import _try_claude_generation

        fp.register_subprocess(
            ["claude", "--print", "-p", fp.any()],
            returncode=0,
            stdout="Generated content here",
        )
        result = _try_claude_generation("test prompt")
        assert result == "Generated content here"

    def test_returns_none_on_empty_stdout(self, fp):
        from claude_candidate.generator import _try_claude_generation

        fp.register_subprocess(
            ["claude", "--print", "-p", fp.any()],
            returncode=0,
            stdout="   ",
        )
        result = _try_claude_generation("test prompt")
        assert result is None


# ---------------------------------------------------------------------------
# TestBuildBulletFromMatch
# ---------------------------------------------------------------------------


class TestBuildBulletFromMatch:
    def test_includes_requirement_name(self):
        from claude_candidate.generator import _build_bullet_from_match

        match = _make_skill_match(requirement="Python proficiency")
        bullet = _build_bullet_from_match(match)
        assert "Python proficiency" in bullet

    def test_returns_nonempty_string(self):
        from claude_candidate.generator import _build_bullet_from_match

        match = _make_skill_match()
        bullet = _build_bullet_from_match(match)
        assert isinstance(bullet, str)
        assert len(bullet.strip()) > 0


# ---------------------------------------------------------------------------
# TestBuildTalkingPoint
# ---------------------------------------------------------------------------


class TestBuildTalkingPoint:
    def test_includes_requirement(self):
        from claude_candidate.generator import _build_talking_point

        match = _make_skill_match(requirement="Docker & Kubernetes")
        point = _build_talking_point(match)
        assert "Docker & Kubernetes" in point

    def test_returns_nonempty_string(self):
        from claude_candidate.generator import _build_talking_point

        match = _make_skill_match()
        point = _build_talking_point(match)
        assert isinstance(point, str)
        assert len(point.strip()) > 0
