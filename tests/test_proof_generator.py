"""Tests for the proof package generator."""

from __future__ import annotations

from datetime import datetime

from claude_candidate.proof_generator import (
    generate_proof_package,
    _header_section,
    _summary_section,
    _dimension_scores_section,
)
from claude_candidate.schemas.fit_assessment import (
    DimensionScore,
    FitAssessment,
    SkillMatchDetail,
)
from claude_candidate.schemas.session_manifest import (
    CorpusStatistics,
    RedactionSummary,
    SessionManifest,
)
from claude_candidate.schemas.merged_profile import (
    EvidenceSource,
    MergedEvidenceProfile,
    MergedSkillEvidence,
)
from claude_candidate.schemas.candidate_profile import DepthLevel


def _make_assessment() -> FitAssessment:
    """Build a minimal FitAssessment for testing."""
    return FitAssessment(
        assessment_id="test-001",
        assessed_at=datetime(2026, 3, 15, 12, 0, 0),
        job_title="Senior Engineer",
        company_name="Acme Corp",
        posting_url="https://example.com/job/123",
        source="linkedin",
        overall_score=0.78,
        overall_grade="B+",
        overall_summary="Strong technical match with good culture alignment.",
        should_apply="yes",
        skill_match=DimensionScore(
            dimension="skill_match",
            score=0.82,
            grade="A-",
            summary="Good skills coverage",
            details=["[+] Python: strong match", "[~] Kubernetes: partial match"],
        ),
        mission_alignment=DimensionScore(
            dimension="mission_alignment",
            score=0.75,
            grade="B",
            summary="Moderate alignment",
            details=["Tech overlap: python, react"],
        ),
        culture_fit=DimensionScore(
            dimension="culture_fit",
            score=0.77,
            grade="B+",
            summary="Good fit",
            details=["Strong: Iterative approach aligns with fast-paced culture"],
        ),
        skill_matches=[
            SkillMatchDetail(
                requirement="Python experience",
                priority="must_have",
                match_status="strong_match",
                candidate_evidence="Expert-level Python in 18 sessions",
                evidence_source=EvidenceSource.CORROBORATED,
                confidence=0.95,
            ),
            SkillMatchDetail(
                requirement="Kubernetes",
                priority="strong_preference",
                match_status="partial_match",
                candidate_evidence="Some container work in 3 sessions",
                evidence_source=EvidenceSource.SESSIONS_ONLY,
                confidence=0.55,
            ),
        ],
        must_have_coverage="4/5",
        strongest_match="Python",
        biggest_gap="Kubernetes",
        resume_gaps_discovered=["fastapi", "pydantic"],
        resume_unverified=["java"],
        action_items=["Highlight Python expertise", "Address Kubernetes gap"],
        company_profile_summary="Acme Corp builds developer tools.",
        company_enrichment_quality="good",
        profile_hash="abc123def456",
        time_to_assess_seconds=1.23,
    )


def _make_manifest() -> SessionManifest:
    """Build a minimal SessionManifest for testing."""
    return SessionManifest(
        manifest_id="manifest-001",
        generated_at=datetime(2026, 3, 15, 12, 0, 0),
        pipeline_version="0.2.0",
        run_id="run-001",
        sessions=[],
        corpus_statistics=CorpusStatistics(
            total_sessions=42,
            total_lines=50000,
            total_tokens_estimate=2000000,
            date_range_start=datetime(2025, 1, 1),
            date_range_end=datetime(2026, 3, 1),
            date_span_days=425,
            sessions_per_month={"2025-01": 5, "2025-02": 7},
            unique_projects=12,
            technologies_overview={"python": 30, "typescript": 20},
            average_session_length_tokens=47619,
            median_session_length_tokens=40000,
            longest_session_tokens=120000,
        ),
        redaction_summary=RedactionSummary(
            total_redactions=150,
            redactions_by_type={"api_key": 50, "email": 100},
            sessions_with_redactions=30,
            sessions_without_redactions=12,
            heaviest_redaction_session="session-007",
            redaction_density=0.03,
            sample_redaction_types=["api_key", "email"],
        ),
        public_repo_correlations=[],
        pipeline_artifacts=[],
        manifest_hash="deadbeef1234567890",
    )


def _make_profile() -> MergedEvidenceProfile:
    """Build a minimal MergedEvidenceProfile for testing."""
    return MergedEvidenceProfile(
        skills=[
            MergedSkillEvidence(
                name="python",
                source=EvidenceSource.CORROBORATED,
                effective_depth=DepthLevel.EXPERT,
                confidence=0.95,
                session_frequency=30,
            ),
            MergedSkillEvidence(
                name="fastapi",
                source=EvidenceSource.SESSIONS_ONLY,
                effective_depth=DepthLevel.DEEP,
                confidence=0.8,
                session_frequency=10,
                discovery_flag=True,
            ),
            MergedSkillEvidence(
                name="java",
                source=EvidenceSource.RESUME_ONLY,
                effective_depth=DepthLevel.APPLIED,
                confidence=0.3,
            ),
        ],
        patterns=[],
        projects=[],
        roles=[],
        corroborated_skill_count=1,
        resume_only_skill_count=1,
        sessions_only_skill_count=1,
        discovery_skills=["fastapi"],
        profile_hash="abc123def456",
        resume_hash="resume-hash-001",
        candidate_profile_hash="cp-hash-001",
        merged_at=datetime(2026, 3, 15, 12, 0, 0),
    )


# -----------------------------------------------------------------------
# TestGenerateProofPackage
# -----------------------------------------------------------------------


class TestGenerateProofPackage:
    """Tests for the top-level generate_proof_package function."""

    def test_produces_valid_markdown(self):
        result = generate_proof_package(assessment=_make_assessment())
        assert isinstance(result, str)
        assert result.startswith("# ")
        # Should have multiple sections with markdown headers
        assert result.count("## ") >= 3

    def test_contains_company_and_title(self):
        result = generate_proof_package(assessment=_make_assessment())
        assert "Acme Corp" in result
        assert "Senior Engineer" in result

    def test_contains_overall_grade(self):
        result = generate_proof_package(assessment=_make_assessment())
        assert "B+" in result

    def test_contains_skills_evidence(self):
        result = generate_proof_package(assessment=_make_assessment())
        assert "Python experience" in result
        assert "strong_match" in result or "Strong Match" in result
        assert "corroborated" in result or "Corroborated" in result

    def test_contains_dimension_scores(self):
        result = generate_proof_package(assessment=_make_assessment())
        assert "skill_match" in result or "Skill Match" in result
        assert "mission_alignment" in result or "Mission Alignment" in result
        assert "culture_fit" in result or "Culture Fit" in result

    def test_contains_manifest_hash(self):
        manifest = _make_manifest()
        result = generate_proof_package(
            assessment=_make_assessment(),
            manifest=manifest,
        )
        assert "deadbeef1234567890" in result

    def test_no_absolute_paths(self):
        result = generate_proof_package(
            assessment=_make_assessment(),
            manifest=_make_manifest(),
            profile=_make_profile(),
        )
        # No absolute file-system paths should appear in the output
        assert "/Users/" not in result
        assert "/home/" not in result
        assert "C:\\" not in result

    def test_works_without_manifest(self):
        result = generate_proof_package(assessment=_make_assessment())
        assert isinstance(result, str)
        assert "Manifest" in result or "manifest" in result

    def test_works_without_profile(self):
        result = generate_proof_package(
            assessment=_make_assessment(),
            manifest=_make_manifest(),
        )
        assert isinstance(result, str)
        assert "Skills" in result or "skills" in result


# -----------------------------------------------------------------------
# TestSections
# -----------------------------------------------------------------------


class TestSections:
    """Tests for individual section-rendering functions."""

    def test_header_section(self):
        section = _header_section(_make_assessment())
        assert "Acme Corp" in section
        assert "Senior Engineer" in section
        assert "B+" in section
        assert section.startswith("# ")

    def test_summary_section(self):
        section = _summary_section(_make_assessment())
        assert "Strong technical match" in section
        assert "yes" in section.lower()

    def test_dimension_scores_section(self):
        section = _dimension_scores_section(_make_assessment())
        assert "0.82" in section or "82" in section
        assert "0.75" in section or "75" in section
        assert "0.77" in section or "77" in section
        assert "A-" in section
        assert "B" in section
