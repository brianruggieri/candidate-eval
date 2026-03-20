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
from claude_candidate.schemas.fit_assessment import FitAssessment

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
