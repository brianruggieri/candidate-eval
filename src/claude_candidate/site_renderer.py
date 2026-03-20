"""
Static site renderer for FitAssessment pages.

Converts a FitAssessment into a clean, professional HTML page using Jinja2
templates. Pages are deployed to Cloudflare Pages at roojerry.com; each
assessment lives at ``site/apply/{company-slug}/index.html``.

PII scrubbing via ``scrub_deliverable()`` is applied to the rendered HTML
before it is written to disk.
"""

from __future__ import annotations

import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from claude_candidate.pii_gate import scrub_deliverable
from claude_candidate.schemas.fit_assessment import FitAssessment, SkillMatchDetail

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Characters that are safe in URL slugs
_SLUG_UNSAFE = re.compile(r"[^a-z0-9-]")
_MULTI_HYPHEN = re.compile(r"-{2,}")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_slug(company_name: str) -> str:
    """Convert a company name into a URL-safe slug.

    Examples::

        "Acme Corp"       -> "acme-corp"
        "Widget & Co."    -> "widget-co"
        "  My  Company "  -> "my-company"
    """
    slug = company_name.lower().strip()
    slug = slug.replace(" ", "-")
    slug = _SLUG_UNSAFE.sub("", slug)
    slug = _MULTI_HYPHEN.sub("-", slug)
    slug = slug.strip("-")
    return slug or "company"


def _build_env() -> Environment:
    """Return a configured Jinja2 environment backed by the templates directory."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_assessment_page(
    assessment: FitAssessment,
    resume_html: str,
    cover_letter: str,
    output_dir: Path,
    *,
    resume_pdf_path: str | None = None,
    cover_letter_pdf_path: str | None = None,
) -> Path:
    """Render an assessment to a static HTML page.

    Creates ``output_dir/apply/{slug}/index.html`` where
    ``slug = assessment.company_name.lower().replace(' ', '-')``.

    PII scrubbing is applied to the rendered HTML before it is written to
    disk so that no personally identifiable information escapes into the
    static site.

    Args:
        assessment: The FitAssessment data model to render.
        resume_html: Tailored resume content as HTML markup.
        cover_letter: Cover letter text (plain text or Markdown).
        output_dir: Root output directory (e.g. ``Path("site")``).
        resume_pdf_path: Optional relative URL for the resume PDF download
            link (e.g. ``"resume.pdf"``).  Omit to hide the download button.
        cover_letter_pdf_path: Optional relative URL for the cover letter PDF
            download link.  Omit to hide the download button.

    Returns:
        Path to the rendered ``index.html`` file.
    """
    slug = _make_slug(assessment.company_name)
    page_dir = output_dir / "apply" / slug
    page_dir.mkdir(parents=True, exist_ok=True)

    env = _build_env()
    template = env.get_template("assessment.html")

    html = template.render(
        assessment=assessment,
        resume_html=resume_html,
        cover_letter=cover_letter,
        resume_pdf_path=resume_pdf_path,
        cover_letter_pdf_path=cover_letter_pdf_path,
    )

    html = scrub_deliverable(html)

    output_path = page_dir / "index.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path


def render_cover_letter_site(
    assessment: FitAssessment | dict,
    narrative: str,
    evidence_highlights: list[dict],
    output_dir: Path | str,
    resume_pdf_path: str | None = None,
) -> Path:
    """Render the cover letter site page for a company.

    Creates ``output_dir/apply/{slug}/index.html`` with a transparency-first
    page showing fit score, skills match, narrative pitch, evidence highlights,
    and a "How This Works" explainer.

    If *assessment* is a dict (e.g. from the assessment store) it is wrapped
    in a simple namespace so Jinja2 attribute access works unchanged.

    PII scrubbing is applied to the rendered HTML before writing to disk.

    Args:
        assessment: FitAssessment model or a dict with equivalent keys.
        narrative: 150-250 word pitch narrative for the "Why This Role" section.
        evidence_highlights: List of dicts with ``title``, ``description``,
            and ``technologies`` (list of str) keys.
        output_dir: Root output directory (e.g. ``Path("site")``).
        resume_pdf_path: Optional relative URL for a resume PDF download link.

    Returns:
        Path to the rendered ``index.html`` file.
    """
    # Normalise assessment to an object with attribute access
    if isinstance(assessment, dict):
        assessment = _DictNamespace(assessment)

    company_name = (
        assessment.company_name
        if hasattr(assessment, "company_name")
        else "company"
    )
    slug = _make_slug(company_name)
    output_dir = Path(output_dir)
    page_dir = output_dir / "apply" / slug
    page_dir.mkdir(parents=True, exist_ok=True)

    env = _build_env()
    template = env.get_template("cover_letter_site.html")

    html = template.render(
        assessment=assessment,
        narrative=narrative,
        evidence_highlights=evidence_highlights,
        resume_pdf_path=resume_pdf_path,
    )

    html = scrub_deliverable(html)

    output_path = page_dir / "index.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path


class _DictNamespace:
    """Lightweight wrapper that gives a dict attribute-style access.

    Jinja2 templates use ``assessment.company_name`` etc., so when the caller
    passes a plain dict we wrap it here to avoid changing the template syntax.
    Nested dicts are also wrapped recursively on access.
    """

    def __init__(self, data: dict) -> None:
        self._data = data

    def __getattr__(self, name: str):
        try:
            val = self._data[name]
        except KeyError:
            raise AttributeError(name) from None
        if isinstance(val, dict):
            return _DictNamespace(val)
        if isinstance(val, list):
            return [
                _DictNamespace(v) if isinstance(v, dict) else v for v in val
            ]
        return val

    def __repr__(self) -> str:
        return f"_DictNamespace({self._data!r})"
