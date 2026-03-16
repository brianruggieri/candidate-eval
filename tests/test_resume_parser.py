"""Tests for resume_parser module."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES_DIR = Path(__file__).parent / "fixtures"
SAMPLE_RESUME = FIXTURES_DIR / "sample_resume.txt"


class TestTextExtraction:
    """Tests for extract_text_from_file."""

    def test_extract_from_txt(self):
        from claude_candidate.resume_parser import extract_text_from_file

        text = extract_text_from_file(SAMPLE_RESUME)
        assert "BRIAN RUGGIERI" in text
        assert "Senior Software Engineer" in text
        assert "TechCorp" in text
        assert "Python" in text

    def test_unsupported_format(self, tmp_path):
        from claude_candidate.resume_parser import extract_text_from_file

        bad_file = tmp_path / "resume.odt"
        bad_file.write_text("some content")
        with pytest.raises(ValueError, match="Unsupported"):
            extract_text_from_file(bad_file)

    def test_missing_file(self, tmp_path):
        from claude_candidate.resume_parser import extract_text_from_file

        missing = tmp_path / "nonexistent.txt"
        with pytest.raises(FileNotFoundError):
            extract_text_from_file(missing)


class TestResumeTextParsing:
    """Tests for parse_resume_text."""

    @pytest.fixture
    def sample_text(self):
        return SAMPLE_RESUME.read_text()

    def test_produces_resume_profile(self, sample_text):
        from claude_candidate.resume_parser import parse_resume_text
        from claude_candidate.schemas.resume_profile import ResumeProfile

        profile = parse_resume_text(sample_text)
        assert isinstance(profile, ResumeProfile)

    def test_extracts_skills(self, sample_text):
        from claude_candidate.resume_parser import parse_resume_text

        profile = parse_resume_text(sample_text)
        skill_names = profile.all_skill_names()
        assert "python" in skill_names
        assert "typescript" in skill_names

    def test_extracts_roles(self, sample_text):
        from claude_candidate.resume_parser import parse_resume_text

        profile = parse_resume_text(sample_text)
        company_names = [r.company.lower() for r in profile.roles]
        assert any("techcorp" in c for c in company_names)

    def test_extracts_name(self, sample_text):
        from claude_candidate.resume_parser import parse_resume_text

        profile = parse_resume_text(sample_text)
        assert profile.name is not None
        assert "BRIAN" in profile.name.upper() or "Brian" in profile.name

    def test_extracts_location(self, sample_text):
        from claude_candidate.resume_parser import parse_resume_text

        profile = parse_resume_text(sample_text)
        assert profile.location is not None
        assert "San Francisco" in profile.location or "CA" in profile.location

    def test_extracts_education(self, sample_text):
        from claude_candidate.resume_parser import parse_resume_text

        profile = parse_resume_text(sample_text)
        assert len(profile.education) > 0
        assert any("Berkeley" in e or "Computer Science" in e for e in profile.education)

    def test_extracts_certifications(self, sample_text):
        from claude_candidate.resume_parser import parse_resume_text

        profile = parse_resume_text(sample_text)
        assert len(profile.certifications) > 0
        assert any("AWS" in c for c in profile.certifications)

    def test_extracts_summary(self, sample_text):
        from claude_candidate.resume_parser import parse_resume_text

        profile = parse_resume_text(sample_text)
        assert profile.professional_summary is not None
        assert len(profile.professional_summary) > 0

    def test_applied_depth_for_skills_in_role_and_section(self, sample_text):
        """Skills in both role bullets and skills section should be APPLIED."""
        from claude_candidate.resume_parser import parse_resume_text
        from claude_candidate.schemas.candidate_profile import DepthLevel

        profile = parse_resume_text(sample_text)
        python_skill = profile.get_skill("python")
        assert python_skill is not None
        assert python_skill.implied_depth == DepthLevel.APPLIED

    def test_current_role_recency(self, sample_text):
        """Skills from the current role should have current_role recency."""
        from claude_candidate.resume_parser import parse_resume_text

        profile = parse_resume_text(sample_text)
        # FastAPI is in TechCorp (current) and skills section
        fastapi_skill = profile.get_skill("fastapi")
        assert fastapi_skill is not None
        assert fastapi_skill.recency == "current_role"

    def test_previous_role_recency(self, sample_text):
        """Skills unique to previous roles should have previous_role recency."""
        from claude_candidate.resume_parser import parse_resume_text

        profile = parse_resume_text(sample_text)
        # Apache Spark only in StartupCo (previous role)
        spark_skill = profile.get_skill("apache spark")
        assert spark_skill is not None
        assert spark_skill.recency in ("previous_role", "historical")

    def test_source_format_default(self, sample_text):
        from claude_candidate.resume_parser import parse_resume_text

        profile = parse_resume_text(sample_text)
        assert profile.source_format == "txt"


class TestIngestResume:
    """Tests for ingest_resume (full pipeline)."""

    def test_ingest_produces_resume_profile(self):
        from claude_candidate.resume_parser import ingest_resume
        from claude_candidate.schemas.resume_profile import ResumeProfile

        profile = ingest_resume(SAMPLE_RESUME)
        assert isinstance(profile, ResumeProfile)

    def test_ingest_sets_source_format(self):
        from claude_candidate.resume_parser import ingest_resume

        profile = ingest_resume(SAMPLE_RESUME)
        assert profile.source_format == "txt"

    def test_ingest_sets_64char_hash(self):
        from claude_candidate.resume_parser import ingest_resume

        profile = ingest_resume(SAMPLE_RESUME)
        assert len(profile.source_file_hash) == 64
        assert all(c in "0123456789abcdef" for c in profile.source_file_hash)

    def test_round_trip_serialization(self):
        from claude_candidate.resume_parser import ingest_resume
        from claude_candidate.schemas.resume_profile import ResumeProfile

        profile = ingest_resume(SAMPLE_RESUME)
        json_str = profile.to_json()
        restored = ResumeProfile.from_json(json_str)
        assert restored.name == profile.name
        assert restored.source_file_hash == profile.source_file_hash
        assert len(restored.skills) == len(profile.skills)
        assert len(restored.roles) == len(profile.roles)
