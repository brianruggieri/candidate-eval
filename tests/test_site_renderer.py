"""Tests for the static site renderer."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import pytest

from claude_candidate.schemas.fit_assessment import DimensionScore, FitAssessment, SkillMatchDetail
from claude_candidate.schemas.merged_profile import EvidenceSource
from claude_candidate.site_renderer import (
	_make_slug,
	render_assessment_page,
	render_cover_letter_site,
)


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


def _make_skill_match(
	*,
	requirement: str = "Python proficiency",
	priority: str = "must_have",
	match_status: str = "strong_match",
	evidence: str = "Corroborated across 20 sessions.",
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


def _make_assessment(
	*,
	company: str = "Acme Corp",
	title: str = "Senior Software Engineer",
	assessment_id: str = "test-001",
	overall_score: float = 0.82,
	overall_grade: str = "B+",
	should_apply: str = "yes",
) -> FitAssessment:
	return FitAssessment(
		assessment_id=assessment_id,
		assessed_at=datetime(2026, 3, 19, 12, 0, 0),
		job_title=title,
		company_name=company,
		posting_url="https://example.com/jobs/123",
		source="linkedin",
		overall_score=overall_score,
		overall_grade=overall_grade,
		overall_summary="Strong fit overall with deep Python and cloud experience.",
		skill_match=DimensionScore(
			dimension="skill_match",
			score=0.88,
			grade="A-",
			summary="Strong technical alignment.",
			details=["Python: exceeds requirements", "Docker: strong match"],
		),
		mission_alignment=DimensionScore(
			dimension="mission_alignment",
			score=0.75,
			grade="B",
			summary="Good mission fit.",
			details=["Open-source track record aligns with company values."],
		),
		culture_fit=DimensionScore(
			dimension="culture_fit",
			score=0.70,
			grade="B-",
			summary="Reasonable culture fit.",
			details=["Iterative refinement style noted in sessions."],
		),
		skill_matches=[
			_make_skill_match(requirement="Python proficiency", priority="must_have"),
			_make_skill_match(
				requirement="React experience",
				priority="strong_preference",
				match_status="partial_match",
				confidence=0.6,
			),
		],
		must_have_coverage="2/2 must-haves met",
		strongest_match="Python proficiency",
		biggest_gap="None — all requirements addressed",
		resume_gaps_discovered=[],
		resume_unverified=[],
		company_profile_summary="Acme Corp builds enterprise developer tooling.",
		company_enrichment_quality="good",
		should_apply=should_apply,  # type: ignore[arg-type]
		action_items=["Generate full application package", "Highlight open-source contributions"],
		profile_hash="deadbeef",
		time_to_assess_seconds=2.3,
	)


SAMPLE_RESUME_HTML = "<h2>Experience</h2><p>Led backend services at scale.</p>"
SAMPLE_COVER_LETTER = (
	"Dear Hiring Manager,\n\nI am excited to apply for the Senior Software Engineer role.\n\n"
	"Sincerely,\nThe Candidate"
)


# ---------------------------------------------------------------------------
# _make_slug unit tests
# ---------------------------------------------------------------------------


class TestMakeSlug:
	def test_basic_lowercases_and_hyphenates(self):
		assert _make_slug("Acme Corp") == "acme-corp"

	def test_strips_special_characters(self):
		assert _make_slug("Widget & Co.") == "widget-co"

	def test_collapses_multiple_hyphens(self):
		assert _make_slug("A  B") == "a-b"

	def test_strips_leading_trailing_spaces(self):
		assert _make_slug("  My Company  ") == "my-company"

	def test_empty_string_returns_company(self):
		assert _make_slug("") == "company"

	def test_already_slug_passthrough(self):
		assert _make_slug("my-company") == "my-company"


# ---------------------------------------------------------------------------
# render_assessment_page: output path
# ---------------------------------------------------------------------------


class TestRenderAssessmentPagePath:
	def test_creates_index_html_at_expected_path(self, tmp_path: Path):
		assessment = _make_assessment(company="Acme Corp")
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		expected = tmp_path / "apply" / "acme-corp" / "index.html"
		assert result == expected
		assert result.exists()

	def test_creates_intermediate_directories(self, tmp_path: Path):
		assessment = _make_assessment(company="New Company LLC")
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		assert result.exists()
		assert (tmp_path / "apply" / "new-company-llc").is_dir()

	def test_returns_path_object(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		assert isinstance(result, Path)


# ---------------------------------------------------------------------------
# render_assessment_page: required meta tags
# ---------------------------------------------------------------------------


class TestMetaTags:
	def test_has_noindex_nofollow(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert 'name="robots"' in html
		assert "noindex" in html
		assert "nofollow" in html

	def test_has_og_title(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert 'property="og:title"' in html

	def test_has_og_description(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert 'property="og:description"' in html

	def test_has_og_type(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert 'property="og:type"' in html

	def test_has_viewport_meta(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert 'name="viewport"' in html


# ---------------------------------------------------------------------------
# render_assessment_page: assessment data in output
# ---------------------------------------------------------------------------


class TestAssessmentDataInOutput:
	def test_contains_company_name(self, tmp_path: Path):
		assessment = _make_assessment(company="Acme Corp")
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "Acme Corp" in html

	def test_contains_job_title(self, tmp_path: Path):
		assessment = _make_assessment(title="Senior Software Engineer")
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "Senior Software Engineer" in html

	def test_contains_overall_grade(self, tmp_path: Path):
		assessment = _make_assessment(overall_grade="B+")
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "B+" in html

	def test_contains_assessment_id(self, tmp_path: Path):
		assessment = _make_assessment(assessment_id="test-001")
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "test-001" in html

	def test_contains_overall_summary(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert assessment.overall_summary in html

	def test_contains_skill_requirement(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "Python proficiency" in html


# ---------------------------------------------------------------------------
# render_assessment_page: resume and cover letter
# ---------------------------------------------------------------------------


class TestResumeAndCoverLetter:
	def test_contains_resume_content(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "Led backend services at scale" in html

	def test_contains_cover_letter_content(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "I am excited to apply" in html

	def test_resume_html_is_rendered_not_escaped(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, "<strong>Important skill</strong>", SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		# The <strong> tag should appear as-is, not as &lt;strong&gt;
		assert "<strong>Important skill</strong>" in html

	def test_empty_resume_omits_resume_section(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(assessment, "", SAMPLE_COVER_LETTER, tmp_path)
		html = result.read_text()
		assert "Tailored Resume" not in html

	def test_empty_cover_letter_omits_cover_letter_section(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(assessment, SAMPLE_RESUME_HTML, "", tmp_path)
		html = result.read_text()
		assert "Cover Letter" not in html

	def test_resume_pdf_download_link_appears_when_provided(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment,
			SAMPLE_RESUME_HTML,
			SAMPLE_COVER_LETTER,
			tmp_path,
			resume_pdf_path="resume.pdf",
		)
		html = result.read_text()
		assert "resume.pdf" in html

	def test_cover_letter_pdf_download_link_appears_when_provided(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment,
			SAMPLE_RESUME_HTML,
			SAMPLE_COVER_LETTER,
			tmp_path,
			cover_letter_pdf_path="cover-letter.pdf",
		)
		html = result.read_text()
		assert "cover-letter.pdf" in html


# ---------------------------------------------------------------------------
# render_assessment_page: How This Works section
# ---------------------------------------------------------------------------


class TestHowItWorksSection:
	def test_contains_how_this_works_heading(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "How This Works" in html

	def test_contains_github_repo_link(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "https://github.com/brianruggieri/claude-candidate" in html

	def test_contains_session_logs_reference(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "session" in html.lower()


# ---------------------------------------------------------------------------
# render_assessment_page: no raw Jinja2 syntax
# ---------------------------------------------------------------------------


class TestNoRawTemplateSyntax:
	_JINJA_PATTERN = re.compile(r"\{\{|\{%|\{#")

	def test_no_unrendered_jinja2_expressions(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert not self._JINJA_PATTERN.search(html), (
			"Rendered HTML still contains raw Jinja2 template syntax"
		)

	def test_no_raw_template_syntax_with_a_grade(self, tmp_path: Path):
		assessment = _make_assessment(overall_grade="A+", overall_score=0.96)
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert not self._JINJA_PATTERN.search(html)

	def test_no_raw_template_syntax_with_no_assessment(self, tmp_path: Path):
		"""Minimal assessment (no resume/cover letter) should still have no syntax leaks."""
		assessment = _make_assessment(overall_grade="F", overall_score=0.1, should_apply="no")
		result = render_assessment_page(assessment, "", "", tmp_path)
		html = result.read_text()
		assert not self._JINJA_PATTERN.search(html)


# ---------------------------------------------------------------------------
# render_assessment_page: Tailwind and basic HTML structure
# ---------------------------------------------------------------------------


class TestHTMLStructure:
	def test_has_html5_doctype(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert html.strip().startswith("<!DOCTYPE html>")

	def test_has_tailwind_cdn(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "cdn.tailwindcss.com" in html

	def test_has_charset_utf8(self, tmp_path: Path):
		assessment = _make_assessment()
		result = render_assessment_page(
			assessment, SAMPLE_RESUME_HTML, SAMPLE_COVER_LETTER, tmp_path
		)
		html = result.read_text()
		assert "UTF-8" in html or "utf-8" in html


# ---------------------------------------------------------------------------
# Cover letter site page tests
# ---------------------------------------------------------------------------

SAMPLE_NARRATIVE = (
	"My strongest contribution to this role is deep Python expertise "
	"backed by 20+ sessions of real-world application. I bring production "
	"experience with cloud infrastructure, Docker orchestration, and API "
	"design that directly maps to your core requirements. The architecture "
	"patterns I use — modular services, clear interface contracts, iterative "
	"refinement — align with how your team builds software."
)

SAMPLE_EVIDENCE_HIGHLIGHTS = [
	{
		"title": "Python proficiency",
		"description": "Corroborated across 20 sessions with deep application.",
		"technologies": ["Python", "FastAPI", "asyncio"],
	},
	{
		"title": "Cloud infrastructure",
		"description": "Built and deployed containerised services on AWS.",
		"technologies": ["Docker", "AWS", "Terraform"],
	},
]


def _render_cover_letter_site(tmp_path: Path, **kwargs) -> str:
	"""Helper that renders a cover letter site page and returns the HTML."""
	assessment = kwargs.pop("assessment", _make_assessment())
	narrative = kwargs.pop("narrative", SAMPLE_NARRATIVE)
	evidence_highlights = kwargs.pop("evidence_highlights", SAMPLE_EVIDENCE_HIGHLIGHTS)
	resume_pdf_path = kwargs.pop("resume_pdf_path", None)

	result = render_cover_letter_site(
		assessment=assessment,
		narrative=narrative,
		evidence_highlights=evidence_highlights,
		output_dir=tmp_path,
		resume_pdf_path=resume_pdf_path,
	)
	return result.read_text()


class TestCoverLetterSiteTransparency:
	def test_cover_letter_site_has_transparency_badge(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "claude-candidate" in html
		assert "https://github.com/brianruggieri/claude-candidate" in html

	def test_transparency_badge_is_in_hero(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		# The badge should appear near the title, not just in the footer
		badge_pos = html.find("Built with claude-candidate")
		assert badge_pos != -1, "Transparency badge not found"


class TestCoverLetterSiteNoResume:
	def test_cover_letter_site_has_no_resume_section(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "Tailored Resume" not in html

	def test_no_cover_letter_section_heading(self, tmp_path: Path):
		"""Cover letter site replaces the old cover letter section with a narrative."""
		html = _render_cover_letter_site(tmp_path)
		# Should NOT have the old "Cover Letter" heading (distinct from "Why This Role")
		assert ">Cover Letter<" not in html


class TestCoverLetterSiteNarrative:
	def test_cover_letter_site_has_narrative(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "My strongest contribution" in html

	def test_narrative_section_heading(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "Why This Role" in html


class TestCoverLetterSiteSkillsTable:
	def test_cover_letter_site_has_skills_table(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "Skills Match" in html
		assert "Python proficiency" in html

	def test_skills_table_has_priority_and_match(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "Must Have" in html
		assert "Strong" in html  # match status badge


class TestCoverLetterSiteHowItWorks:
	def test_cover_letter_site_has_how_it_works(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "How This Works" in html

	def test_how_it_works_links_to_github(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "https://github.com/brianruggieri/claude-candidate" in html

	def test_how_it_works_mentions_evidence(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "evidence" in html.lower()


class TestCoverLetterSiteEvidenceHighlights:
	def test_evidence_highlights_render(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "Evidence Highlights" in html
		assert "Cloud infrastructure" in html

	def test_evidence_highlights_show_technologies(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "FastAPI" in html
		assert "Terraform" in html


class TestCoverLetterSiteCTA:
	def test_has_lets_talk(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "Let" in html and "Talk" in html

	def test_resume_pdf_link_when_provided(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path, resume_pdf_path="resume.pdf")
		assert "resume.pdf" in html

	def test_no_resume_pdf_link_when_omitted(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "Download Resume" not in html


class TestCoverLetterSiteFooter:
	def test_has_private_page_notice(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "Private page" in html

	def test_has_noindex(self, tmp_path: Path):
		html = _render_cover_letter_site(tmp_path)
		assert "noindex" in html


class TestCoverLetterSiteWithDict:
	"""Verify the renderer works when assessment is passed as a plain dict."""

	def test_renders_from_dict(self, tmp_path: Path):
		assessment_dict = {
			"assessment_id": "dict-test-001",
			"assessed_at": "2026-03-19T12:00:00",
			"job_title": "Staff Engineer",
			"company_name": "DictCo",
			"posting_url": "https://example.com/jobs/456",
			"overall_score": 0.75,
			"overall_grade": "B",
			"overall_summary": "Good overall fit.",
			"skill_matches": [
				{
					"requirement": "Go proficiency",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Used Go in 5 sessions.",
				},
			],
		}
		result = render_cover_letter_site(
			assessment=assessment_dict,
			narrative="Strong Go experience.",
			evidence_highlights=[],
			output_dir=tmp_path,
		)
		html = result.read_text()
		assert "DictCo" in html
		assert "Staff Engineer" in html
		assert "Go proficiency" in html
