"""
CLI entry point for claude-candidate.

Provides subcommands for each pipeline stage plus a `poc` command
that runs the full v0.1 proof-of-concept flow.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import click

from claude_candidate import __version__

if TYPE_CHECKING:
    from claude_candidate.extractor import SessionSignals
    from claude_candidate.session_scanner import SessionInfo


@click.group()
@click.version_option(__version__)
@click.pass_context
def main(ctx: click.Context) -> None:
    """claude-candidate: Honest job fit assessment from your resume + Claude Code sessions."""
    ctx.ensure_object(dict)
    # Commands that require Claude CLI
    needs_claude = {"assess", "generate", "generate-deliverable", "job"}
    if ctx.invoked_subcommand in needs_claude:
        from claude_candidate.claude_cli import check_claude_available

        if not check_claude_available():
            click.echo(
                "Error: Claude CLI is required for this command but was not found.\n"
                "Install from https://docs.anthropic.com/claude-code",
                err=True,
            )
            ctx.exit(1)


@main.command()
@click.option("--profile", "-p", type=click.Path(exists=True), required=True,
              help="Path to CandidateProfile JSON")
@click.option("--resume", "-r", type=click.Path(exists=True), required=False,
              help="Path to ResumeProfile JSON (optional)")
@click.option("--job", "-j", type=click.Path(exists=True), required=True,
              help="Path to job posting text file")
@click.option("--company", "-c", required=True, help="Company name")
@click.option("--title", "-t", required=True, help="Job title")
@click.option("--seniority", "-s", default="unknown",
              type=click.Choice(["junior", "mid", "senior", "staff", "principal", "director", "unknown"]),
              help="Seniority level")
@click.option("--output", "-o", type=click.Path(), help="Output file for assessment JSON")
def assess(
    profile: str,
    resume: str | None,
    job: str,
    company: str,
    title: str,
    seniority: str,
    output: str | None,
) -> None:
    """Run a quick match assessment against a job posting."""
    from claude_candidate.schemas.candidate_profile import CandidateProfile
    from claude_candidate.schemas.job_requirements import QuickRequirement
    from claude_candidate.schemas.resume_profile import ResumeProfile
    from claude_candidate.quick_match import QuickMatchEngine

    click.echo(f"Loading candidate profile from {profile}...")
    cp = CandidateProfile.from_json(Path(profile).read_text())

    rp = None
    if resume:
        click.echo(f"Loading resume profile from {resume}...")
        rp = ResumeProfile.from_json(Path(resume).read_text())

    merged = _merge_profile(cp, rp)
    click.echo(f"  Merged: {merged.corroborated_skill_count} corroborated, "
                f"{merged.sessions_only_skill_count} sessions-only, "
                f"{merged.resume_only_skill_count} resume-only")

    click.echo(f"Loading job posting from {job}...")
    job_text = Path(job).read_text()

    # Parse requirements from the job text
    # In v0.1, requirements are provided as a simple JSON list alongside the text
    req_path = Path(job).with_suffix(".requirements.json")
    if req_path.exists():
        click.echo(f"Loading requirements from {req_path}...")
        req_data = json.loads(req_path.read_text())
        requirements = [QuickRequirement(**r) for r in req_data]
    else:
        click.echo("Parsing requirements with Claude...")
        from claude_candidate.requirement_parser import parse_requirements_with_claude
        requirements = parse_requirements_with_claude(job_text)
        click.echo(f"  Extracted {len(requirements)} requirements")

    # Run assessment
    click.echo(f"\nAssessing fit for {title} at {company}...")
    engine = QuickMatchEngine(merged)
    assessment = engine.assess(
        requirements=requirements,
        company=company,
        title=title,
        posting_url=None,
        source="cli",
        seniority=seniority,
    )

    # Output
    if output:
        Path(output).write_text(assessment.to_json())
        click.echo(f"\nFull assessment written to {output}")

    _print_assessment_card(assessment)


@main.command()
@click.option("--assessment", "-a", type=click.Path(exists=True), required=True,
              help="Path to assessment JSON file")
@click.option("--output", "-o", type=click.Path(),
              help="Output path for proof package markdown")
def proof(assessment: str, output: str | None) -> None:
    """Generate a proof package from an assessment."""
    from claude_candidate.schemas.fit_assessment import FitAssessment
    from claude_candidate.proof_generator import generate_proof_package

    click.echo(f"Loading assessment from {assessment}...")
    assessment_obj = FitAssessment.from_json(Path(assessment).read_text())

    click.echo("Generating proof package...")
    proof_markdown = generate_proof_package(assessment=assessment_obj)

    if output:
        Path(output).write_text(proof_markdown)
        click.echo(f"Proof package written to {output}")
    else:
        click.echo(proof_markdown)


@main.command("generate-deliverable")
@click.option("--assessment", "-a", type=click.Path(exists=True), required=True,
              help="Path to assessment JSON file")
@click.option("--type", "-t", "deliverable_type",
              type=click.Choice(["resume-bullets", "cover-letter", "interview-prep"]),
              required=True,
              help="Type of deliverable to generate")
@click.option("--output", "-o", type=click.Path(),
              help="Output path for generated deliverable")
def generate_deliverable(assessment: str, deliverable_type: str, output: str | None) -> None:
    """Generate text deliverables (resume bullets, cover letter, interview prep) from an assessment."""
    from claude_candidate.schemas.fit_assessment import FitAssessment
    from claude_candidate.generator import (
        generate_resume_bullets,
        generate_cover_letter,
        generate_interview_prep,
    )

    click.echo(f"Loading assessment from {assessment}...")
    assessment_obj = FitAssessment.from_json(Path(assessment).read_text())

    click.echo(f"Generating {deliverable_type}...")
    result: str | list[str]
    if deliverable_type == "resume-bullets":
        result = generate_resume_bullets(assessment=assessment_obj)
        content = "\n".join(f"- {b}" for b in result)
    elif deliverable_type == "cover-letter":
        result = generate_cover_letter(assessment=assessment_obj)
        content = result
    else:  # interview-prep
        result = generate_interview_prep(assessment=assessment_obj)
        content = result

    if output:
        Path(output).write_text(content)
        click.echo(f"Deliverable written to {output}")
    else:
        click.echo(content)


@main.command("generate")
@click.option("--job", "shortlist_id", type=int, required=True, help="Shortlist ID to generate for")
@click.option("--output-dir", default="site", help="Output directory")
@click.option("--deploy/--no-deploy", default=True, help="Auto-deploy via wrangler")
@click.option("--db", default=None, help="Database path")
def generate_site(shortlist_id: int, output_dir: str, deploy: bool, db: str | None) -> None:
    """Generate cover letter site page for a shortlisted job and deploy."""
    import asyncio
    import subprocess
    import json as _json

    from claude_candidate.storage import AssessmentStore
    from claude_candidate.generator import generate_site_narrative
    from claude_candidate.site_renderer import render_cover_letter_site

    db_path = Path(db) if db else Path.home() / ".claude-candidate" / "assessments.db"

    if not db_path.exists():
        click.echo(f"Database not found at {db_path}", err=True)
        raise SystemExit(1)

    async def _load_data():
        store = AssessmentStore(db_path)
        await store.initialize()
        try:
            # Load shortlist entry
            items = await store.list_shortlist()
            entry = next((i for i in items if i["id"] == shortlist_id), None)
            if entry is None:
                return None, None, None

            # Load assessment
            assessment_id = entry.get("assessment_id")
            assessment_record = None
            if assessment_id:
                assessment_record = await store.get_assessment(assessment_id)

            # Load company research
            company_name = entry.get("company_name", "")
            research = await store.get_cached_company_research(company_name)

            return entry, assessment_record, research or {}
        finally:
            await store.close()

    entry, assessment_record, company_research = asyncio.run(_load_data())

    if entry is None:
        click.echo(f"Shortlist ID {shortlist_id} not found.", err=True)
        raise SystemExit(1)

    if assessment_record is None:
        click.echo(
            f"No assessment found for shortlist ID {shortlist_id}. "
            "Run an assessment first.",
            err=True,
        )
        raise SystemExit(1)

    # The assessment data is in the 'data' field
    assessment_data = assessment_record.get("data", {})
    if isinstance(assessment_data, str):
        assessment_data = _json.loads(assessment_data)

    # Merge top-level record fields into assessment_data for convenience
    for key in ("company_name", "job_title", "overall_grade", "assessment_id"):
        if key not in assessment_data and key in assessment_record:
            assessment_data[key] = assessment_record[key]

    click.echo(f"Generating site page for {entry['company_name']} — {entry['job_title']}...")

    # Generate narrative
    click.echo("  Generating narrative...")
    narrative = generate_site_narrative(assessment_data, company_research)

    # Build evidence highlights from top matched skills
    skill_matches = assessment_data.get("skill_matches", [])
    positive_statuses = {"exceeds", "strong_match", "partial_match"}
    top_matches = [
        m for m in skill_matches
        if m.get("match_status") in positive_statuses
    ][:3]

    evidence_highlights = []
    for m in top_matches:
        techs = []
        req = m.get("requirement", "")
        # Use the requirement as a technology tag
        if req:
            techs.append(req)
        evidence_highlights.append({
            "title": req,
            "description": m.get("candidate_evidence", ""),
            "technologies": techs,
        })

    # Render the page
    click.echo("  Rendering HTML...")
    output_path = render_cover_letter_site(
        assessment=assessment_data,
        narrative=narrative,
        evidence_highlights=evidence_highlights,
        output_dir=Path(output_dir),
    )
    click.echo(f"  Written: {output_path}")

    # Deploy via wrangler
    if deploy:
        click.echo("  Deploying via wrangler...")
        try:
            result = subprocess.run(
                ["wrangler", "pages", "deploy", output_dir, "--project-name=roojerry-com"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0:
                click.echo("  Deployed successfully.")
                if result.stdout:
                    click.echo(result.stdout)
            else:
                click.echo(f"  Deploy failed (exit {result.returncode}):", err=True)
                if result.stderr:
                    click.echo(result.stderr, err=True)
        except FileNotFoundError:
            click.echo(
                "  wrangler not found. Install with: npm i -g wrangler\n"
                "  You can deploy manually: wrangler pages deploy site/ --project-name=<project>",
                err=True,
            )
        except subprocess.TimeoutExpired:
            click.echo("  Deploy timed out after 120s.", err=True)


@main.command()
@click.option("--db", default=None, help="Database path")
def shortlist(db: str | None) -> None:
    """List shortlisted jobs with grades."""
    import asyncio
    from claude_candidate.storage import AssessmentStore

    async def _list():
        data_dir = Path(db).parent if db else Path.home() / ".claude-candidate"
        db_path = Path(db) if db else data_dir / "assessments.db"
        store = AssessmentStore(db_path)
        await store.initialize()
        items = await store.list_shortlist()
        await store.close()
        return items

    items = asyncio.run(_list())

    if not items:
        click.echo("No shortlisted jobs.")
        return

    # Print table header
    click.echo(f"{'Grade':<6} {'Company':<20} {'Title':<30} {'Location':<15} {'Salary':<15} {'Added':<12}")
    click.echo("-" * 100)
    for item in items:
        click.echo(
            f"{item.get('overall_grade', '--'):<6} "
            f"{item['company_name'][:19]:<20} "
            f"{item['job_title'][:29]:<30} "
            f"{(item.get('location') or '--')[:14]:<15} "
            f"{(item.get('salary') or '--')[:14]:<15} "
            f"{item.get('added_at', '--')[:10]:<12}"
        )


@main.command("export-fit")
@click.argument("assessment_id")
@click.option(
    "--output-dir", "-o",
    type=click.Path(exists=True, file_okay=False),
    required=True,
    help="Directory to write the Hugo markdown file (e.g., ../roojerry/content/fit/)",
)
@click.option(
    "--db",
    type=click.Path(),
    default=None,
    help="Path to assessments.db (default: ~/.claude-candidate/assessments.db)",
)
@click.option(
    "--cal-link",
    default=None,
    help="Cal.com booking link (default: from fit_exporter module).",
)
def export_fit(assessment_id: str, output_dir: str, db: str | None, cal_link: str | None) -> None:
    """Export a FitAssessment as a Hugo markdown file for the fit landing page."""
    import asyncio
    from claude_candidate.fit_exporter import export_fit_assessment, _DEFAULT_CAL_LINK
    from claude_candidate.storage import AssessmentStore

    data_dir = Path.home() / ".claude-candidate"
    db_path = Path(db) if db else data_dir / "assessments.db"
    merged_path = data_dir / "merged_profile.json"
    candidate_path = data_dir / "candidate_profile.json"

    # Validate paths
    if not db_path.exists():
        click.echo(f"Error: Database not found at {db_path}", err=True)
        raise SystemExit(1)
    if not merged_path.exists():
        click.echo(f"Error: Merged profile not found at {merged_path}", err=True)
        raise SystemExit(1)
    if not candidate_path.exists():
        click.echo(f"Error: Candidate profile not found at {candidate_path}", err=True)
        raise SystemExit(1)

    # Load assessment from DB
    async def _load():
        store = AssessmentStore(db_path)
        await store.initialize()
        try:
            return await store.get_assessment(assessment_id)
        finally:
            await store.close()

    assessment = asyncio.run(_load())
    if not assessment:
        click.echo(f"Error: Assessment '{assessment_id}' not found.", err=True)
        raise SystemExit(1)

    # Export
    result_path = export_fit_assessment(
        assessment,
        merged_profile_path=merged_path,
        candidate_profile_path=candidate_path,
        output_dir=Path(output_dir),
        cal_link=cal_link or _DEFAULT_CAL_LINK,
    )

    slug = result_path.stem
    click.echo(f"Exported: {result_path}")
    click.echo(f"URL:      roojerry.com/fit/{slug}")


def _extract_basic_requirements(text: str) -> list:
    """
    Basic keyword-based requirement extraction for v0.1 PoC.

    This is a placeholder for the full Claude Code-powered parser.
    Looks for common patterns in job postings to extract requirements.
    """
    from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority

    requirements: list[QuickRequirement] = []
    lines = text.lower().split("\n")

    # Common tech keywords to look for
    tech_keywords = {
        "python": ["python"],
        "typescript": ["typescript", "ts"],
        "javascript": ["javascript", "js"],
        "react": ["react", "react.js"],
        "node.js": ["node", "node.js"],
        "docker": ["docker", "containers"],
        "kubernetes": ["kubernetes", "k8s"],
        "aws": ["aws", "amazon web services"],
        "gcp": ["gcp", "google cloud"],
        "postgresql": ["postgresql", "postgres"],
        "git": ["git"],
        "ci/cd": ["ci/cd", "cicd", "continuous integration"],
        "rest-api": ["rest", "api", "restful"],
        "graphql": ["graphql"],
        "machine-learning": ["machine learning", "ml"],
        "llm": ["llm", "large language model"],
        "prompt-engineering": ["prompt engineering", "prompting"],
        "agent": ["agent", "multi-agent", "agentic"],
    }

    text_lower = text.lower()
    for tech, keywords in tech_keywords.items():
        if any(kw in text_lower for kw in keywords):
            # Guess priority based on context
            priority = RequirementPriority.NICE_TO_HAVE
            for line in lines:
                if any(kw in line for kw in keywords):
                    if any(w in line for w in ["required", "must", "need", "essential"]):
                        priority = RequirementPriority.MUST_HAVE
                        break
                    elif any(w in line for w in ["preferred", "ideal", "bonus", "plus"]):
                        priority = RequirementPriority.STRONG_PREFERENCE
                        break

            requirements.append(QuickRequirement(
                description=f"Experience with {tech}",
                skill_mapping=[tech],
                priority=priority,
                source_text="",
            ))

    if not requirements:
        # Fallback: create a generic requirement
        requirements.append(QuickRequirement(
            description="General software engineering",
            skill_mapping=["python", "git"],
            priority=RequirementPriority.MUST_HAVE,
            source_text="",
        ))

    return requirements


# === Job commands ===

@main.group()
def job() -> None:
    """Job posting analysis commands."""
    pass


@job.command()
@click.argument("posting_file", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), help="Output path for requirements JSON")
def parse(posting_file: str, output: str | None) -> None:
    """Parse a job posting into structured requirements."""
    from claude_candidate.requirement_parser import parse_requirements_with_claude
    import json

    posting_text = Path(posting_file).read_text()
    click.echo("Parsing requirements...")

    requirements = parse_requirements_with_claude(posting_text)
    click.echo(f"  Found {len(requirements)} requirements")

    result = [r.model_dump(mode="json") for r in requirements]
    json_output = json.dumps(result, indent=2)

    if output:
        Path(output).write_text(json_output)
        click.echo(f"  Written to {output}")
    else:
        click.echo(json_output)


# === Match commands ===

@main.group()
def match() -> None:
    """Matching and correlation commands."""
    pass


@match.command()
@click.option("--github-user", required=True, help="GitHub username for public repo lookup")
@click.option("--profile", "-p", type=click.Path(exists=True),
              help="CandidateProfile JSON for correlation")
@click.option("--output", "-o", type=click.Path(), help="Output path for correlations JSON")
def correlate(github_user: str, profile: str | None, output: str | None) -> None:
    """Correlate public GitHub repos with session evidence."""
    from claude_candidate.correlator import fetch_public_repos, correlate_repos
    from claude_candidate.extractor import SessionSignals
    import json

    signals_list: list[SessionSignals] = []
    if profile:
        from claude_candidate.schemas.candidate_profile import CandidateProfile
        cp = CandidateProfile.from_json(Path(profile).read_text())
        for skill in cp.skills:
            sid = skill.evidence[0].session_id if skill.evidence else ""
            signals_list.append(SessionSignals(session_id=sid, technologies=[skill.name]))

    click.echo(f"Fetching public repos for {github_user}...")
    repos = fetch_public_repos(github_user)
    click.echo(f"  Found {len(repos)} repos")

    correlations = correlate_repos(repos=repos, signals_list=signals_list)
    click.echo(f"  Correlated {len(correlations)} repos")

    result = [c.model_dump(mode="json") for c in correlations]
    json_output = json.dumps(result, indent=2)

    if output:
        Path(output).write_text(json_output)
        click.echo(f"  Written to {output}")
    else:
        click.echo(json_output)


def _print_assessment_card(assessment) -> None:
    """Print a formatted assessment card to the terminal."""
    try:
        import rich  # noqa: F401
        _print_rich_card(assessment)
    except ImportError:
        _print_plain_card(assessment)


def _print_rich_card(assessment) -> None:
    """Print assessment card using rich library."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()

    # Color mapping
    grade_colors = {
        "A": "green", "A+": "green", "A-": "green",
        "B": "blue", "B+": "blue", "B-": "blue",
        "C": "yellow", "C+": "yellow", "C-": "yellow",
        "D": "red", "F": "red",
    }
    color = grade_colors.get(assessment.overall_grade, "white")

    # Header
    console.print()
    console.print(Panel(
        f"[bold]{assessment.company_name}[/bold]\n"
        f"{assessment.job_title}\n"
        f"\n"
        f"Overall: [{color} bold]{assessment.overall_grade}[/] ({assessment.overall_score:.0%})\n"
        f"{'█' * int(assessment.overall_score * 20)}{'░' * (20 - int(assessment.overall_score * 20))}",
        title="claude-candidate",
        border_style=color,
    ))

    # Dimensions
    table = Table(show_header=True, header_style="bold")
    table.add_column("Dimension", width=18)
    table.add_column("Score", width=8, justify="center")
    table.add_column("Grade", width=6, justify="center")
    table.add_column("Bar", width=20)

    for dim in [assessment.skill_match, assessment.experience_match, assessment.education_match,
                 assessment.mission_alignment, assessment.culture_fit]:
        if dim is None:
            continue
        bar = "█" * int(dim.score * 20) + "░" * (20 - int(dim.score * 20))
        dim_color = grade_colors.get(dim.grade, "white")
        label = dim.dimension.replace("_", " ").title()
        table.add_row(label, f"{dim.score:.0%}", f"[{dim_color}]{dim.grade}[/]", bar)

    console.print(table)

    # Key stats
    console.print(f"\n  ✓ {assessment.must_have_coverage}")
    console.print(f"  ★ Strongest: {assessment.strongest_match}")
    console.print(f"  △ Gap: {assessment.biggest_gap}")

    if assessment.resume_gaps_discovered:
        console.print(f"\n  💡 {len(assessment.resume_gaps_discovered)} skills your resume doesn't mention")
        for skill in assessment.resume_gaps_discovered[:3]:
            console.print(f"     → {skill}")

    if assessment.resume_unverified:
        console.print(f"\n  ⚠  {len(assessment.resume_unverified)} resume claims without session evidence")
        for skill in assessment.resume_unverified[:3]:
            console.print(f"     → {skill}")

    # Verdict
    verdict_emoji = {
        "strong_yes": "🟢 STRONG YES",
        "yes": "🟢 YES",
        "maybe": "🟡 MAYBE",
        "probably_not": "🟠 PROBABLY NOT",
        "no": "🔴 NO",
    }
    verdict = verdict_emoji.get(assessment.should_apply, assessment.should_apply)
    console.print(f"\n  Verdict: [bold]{verdict}[/bold]")

    # Action items
    if assessment.action_items:
        console.print("\n  Next steps:")
        for item in assessment.action_items:
            console.print(f"    → {item}")

    console.print(f"\n  ⏱  Assessed in {assessment.time_to_assess_seconds:.1f}s")
    console.print()


def _print_plain_card(assessment) -> None:
    """Fallback plain text output."""
    def bar(score):
        return "█" * int(score * 20) + "░" * (20 - int(score * 20))

    print(f"\n{'='*50}")
    print(f"  {assessment.company_name}")
    print(f"  {assessment.job_title}")
    print(f"{'─'*50}")
    print(f"  Overall: {assessment.overall_grade} ({assessment.overall_score:.0%})")
    print(f"  {bar(assessment.overall_score)}")
    print()
    print(f"  Skills:  {bar(assessment.skill_match.score)} {assessment.skill_match.grade}")
    if assessment.experience_match:
        print(f"  Exper.:  {bar(assessment.experience_match.score)} {assessment.experience_match.grade}")
    if assessment.education_match:
        print(f"  Educ.:   {bar(assessment.education_match.score)} {assessment.education_match.grade}")
    if assessment.mission_alignment:
        print(f"  Mission: {bar(assessment.mission_alignment.score)} {assessment.mission_alignment.grade}")
    if assessment.culture_fit:
        print(f"  Culture: {bar(assessment.culture_fit.score)} {assessment.culture_fit.grade}")
    print()
    print(f"  ✓ {assessment.must_have_coverage}")
    print(f"  ★ Strongest: {assessment.strongest_match}")
    print(f"  △ Gap: {assessment.biggest_gap}")

    if assessment.resume_gaps_discovered:
        print(f"\n  💡 {len(assessment.resume_gaps_discovered)} skills sessions show but resume doesn't")

    verdict_text = {
        "strong_yes": "STRONG YES", "yes": "YES", "maybe": "MAYBE",
        "probably_not": "PROBABLY NOT", "no": "NO",
    }
    print(f"\n  Verdict: {verdict_text.get(assessment.should_apply, assessment.should_apply)}")

    if assessment.action_items:
        print("\n  Next steps:")
        for item in assessment.action_items:
            print(f"    → {item}")

    print(f"\n  Assessed in {assessment.time_to_assess_seconds:.1f}s")
    print(f"{'='*50}\n")


# === Manifest commands ===

@main.group()
def manifest() -> None:
    """Session manifest and verification commands."""
    pass


@manifest.command("create")
@click.argument("session_paths", nargs=-1, type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default="manifest.json")
def manifest_create(session_paths: tuple[str, ...], output: str) -> None:
    """Create a session manifest from JSONL files."""
    from claude_candidate.manifest import scan_sessions, create_manifest

    paths = [Path(p) for p in session_paths]

    # Expand directories
    expanded: list[Path] = []
    for p in paths:
        if p.is_dir():
            expanded.extend(p.rglob("*.jsonl"))
        else:
            expanded.append(p)

    click.echo(f"Scanning {len(expanded)} session files...")
    records = scan_sessions(expanded)
    click.echo(f"  Found {len(records)} valid sessions")

    manifest_obj = create_manifest(records)
    Path(output).write_text(manifest_obj.to_json())
    click.echo(f"Manifest written to {output}")
    click.echo(f"  Hash: {manifest_obj.manifest_hash}")


@manifest.command("verify")
@click.argument("manifest_path", type=click.Path(exists=True))
def manifest_verify(manifest_path: str) -> None:
    """Verify a manifest's internal consistency."""
    from claude_candidate.manifest import verify_manifest
    from claude_candidate.schemas.session_manifest import SessionManifest

    m = SessionManifest.from_json(Path(manifest_path).read_text())
    result = verify_manifest(m)

    if result["valid"]:
        click.echo("✓ Manifest is valid")
    else:
        click.echo("✗ Manifest verification failed:")
        for error in result["errors"]:
            click.echo(f"  - {error}")


# === Profile commands ===

@main.group()
def profile() -> None:
    """Profile management commands."""
    pass


@profile.command("merge")
@click.option("--candidate", "-c", type=click.Path(exists=True), required=True)
@click.option("--resume", "-r", type=click.Path(exists=True), required=False)
@click.option("--output", "-o", type=click.Path(), default="merged_profile.json")
def profile_merge(candidate: str, resume: str | None, output: str) -> None:
    """Merge candidate and resume profiles."""
    from claude_candidate.schemas.candidate_profile import CandidateProfile
    from claude_candidate.schemas.resume_profile import ResumeProfile

    cp = CandidateProfile.from_json(Path(candidate).read_text())

    rp = None
    if resume:
        rp = ResumeProfile.from_json(Path(resume).read_text())

    merged = _merge_profile(cp, rp)

    Path(output).write_text(merged.to_json())
    click.echo(f"Merged profile written to {output}")
    click.echo(f"  Skills: {len(merged.skills)}")
    click.echo(f"  Corroborated: {merged.corroborated_skill_count}")
    click.echo(f"  Sessions-only: {merged.sessions_only_skill_count}")
    click.echo(f"  Resume-only: {merged.resume_only_skill_count}")
    if merged.discovery_skills:
        click.echo(f"  Discovery: {', '.join(merged.discovery_skills)}")


# Strength bar display for pattern review
_STRENGTH_BARS = {
    "emerging":    "█░░░",
    "established": "██░░",
    "strong":      "███░",
    "exceptional": "████",
}

# Strength rank for computing delta
_STRENGTH_RANK = {
    "emerging":    1,
    "established": 2,
    "strong":      3,
    "exceptional": 4,
}

# Scenario gap-fill questions keyed by PatternType value
_SCENARIO_QUESTIONS: dict[str, dict] = {
    "systematic_debugging": {
        "q": "You're debugging a production issue. What's your first instinct?",
        "options": {
            "a": ("Check logs and traces systematically", True),
            "b": ("Try the most likely fix immediately", False),
            "c": ("Ask a colleague who worked on this area", False),
        },
    },
    "architecture_first": {
        "q": "You're starting a new feature. What do you do first?",
        "options": {
            "a": ("Write a brief design doc or diagram", True),
            "b": ("Start coding a prototype", False),
            "c": ("Research existing implementations", False),
        },
    },
    "iterative_refinement": {
        "q": "You've shipped a working v1. What's your natural next move?",
        "options": {
            "a": ("Gather feedback and plan v2 improvements", True),
            "b": ("Move on to the next project", False),
            "c": ("Write tests to lock in current behavior", False),
        },
    },
    "tradeoff_analysis": {
        "q": "You're evaluating two technical approaches. What drives your decision?",
        "options": {
            "a": ("Explicit pros/cons of each including long-term implications", True),
            "b": ("Pick the simpler one and move fast", False),
            "c": ("Go with what the team already knows", False),
        },
    },
    "scope_management": {
        "q": "Midway through a project, the requirements expand. What do you do?",
        "options": {
            "a": ("Explicitly defer the new scope and document the decision", True),
            "b": ("Absorb it — the project isn't shipped yet anyway", False),
            "c": ("Raise the timeline concern with stakeholders", False),
        },
    },
    "documentation_driven": {
        "q": "Before writing any code, what artifact do you produce first?",
        "options": {
            "a": ("A spec doc, CLAUDE.md, or design notes", True),
            "b": ("Skeleton files to establish structure", False),
            "c": ("A list of tasks in an issue tracker", False),
        },
    },
    "recovery_from_failure": {
        "q": "A technical approach you invested in clearly isn't working. What do you do?",
        "options": {
            "a": ("Pivot early and document what you learned", True),
            "b": ("Keep pushing — sunk cost rarely justifies a full pivot", False),
            "c": ("Seek a second opinion before abandoning", False),
        },
    },
    "tool_selection": {
        "q": "You need to add a new dependency. What's your process?",
        "options": {
            "a": ("Evaluate alternatives explicitly before picking one", True),
            "b": ("Use whatever I've used before and know well", False),
            "c": ("Use the most popular option in the ecosystem", False),
        },
    },
    "modular_thinking": {
        "q": "You're designing a system. What's your natural decomposition style?",
        "options": {
            "a": ("Independent modules with clear interface contracts", True),
            "b": ("Monolith first, extract later if needed", False),
            "c": ("Follow the framework's recommended structure", False),
        },
    },
    "testing_instinct": {
        "q": "When do you write tests?",
        "options": {
            "a": ("Alongside or before the feature — it's part of the work", True),
            "b": ("After the feature works, to prevent regression", False),
            "c": ("When there's time — tests are debt prevention, not blocking", False),
        },
    },
    "meta_cognition": {
        "q": "After completing a project, what do you typically reflect on?",
        "options": {
            "a": ("What the process revealed about how I work best", True),
            "b": ("What I'd build differently given the outcome", False),
            "c": ("Whether the end result met the original spec", False),
        },
    },
    "communication_clarity": {
        "q": "You need to explain a complex technical decision to a non-technical stakeholder. What do you lead with?",
        "options": {
            "a": ("The tradeoff framing: what we gain vs. what we give up", True),
            "b": ("The bottom line outcome: what this means for the product", False),
            "c": ("The analogy that makes the concept concrete", False),
        },
    },
}




def _strength_bar(strength: str) -> str:
    return _STRENGTH_BARS.get(strength, "????")


def _prompt_strength_adjust(pattern_name: str, current_strength: str) -> str | None:
    """
    Prompt user to confirm or adjust a pattern strength.

    Returns the adjusted strength string, or the original if confirmed.
    """
    bar = _strength_bar(current_strength)
    while True:
        raw = click.prompt(
            f"  Confirm (Enter) or adjust [e]merging/es[t]ablished/[s]trong/e[x]ceptional",
            default="",
            show_default=False,
        ).strip().lower()
        if raw == "":
            return current_strength
        mapping = {"e": "emerging", "t": "established", "s": "strong", "x": "exceptional"}
        if raw in mapping:
            return mapping[raw]
        # Allow full word input too
        if raw in ("emerging", "established", "strong", "exceptional"):
            return raw
        click.echo("  Invalid. Press Enter to confirm, or e/t/s/x to adjust.")


@profile.command("review")
@click.option("--candidate", "-c", type=click.Path(exists=True), required=True,
              help="Path to CandidateProfile JSON")
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output path for curated profile")
@click.option("--skip-gaps", is_flag=True, default=False,
              help="Skip scenario gap-fill questions")
def profile_review(candidate: str, output: str | None, skip_gaps: bool) -> None:
    """Interactive pattern profile review with confirm/adjust and gap-fill.

    Displays auto-detected behavioral patterns with evidence, lets you
    confirm or adjust each one, then optionally fills gaps via scenario
    questions for unobserved pattern types.

    Result is saved as a curated profile JSON linked to your resume onboard
    output (if present).
    """
    import datetime

    from claude_candidate.schemas.candidate_profile import CandidateProfile, PatternType

    cp = CandidateProfile.from_json(Path(candidate).read_text())

    click.echo()
    click.echo("=" * 60)
    click.echo("  Pattern Profile Review")
    click.echo(f"  {cp.session_count} sessions analysed  |  "
               f"{len(cp.problem_solving_patterns)} pattern(s) detected")
    click.echo("=" * 60)

    # ── Step 1: Confirm/Adjust observed patterns ─────────────────────────────

    observed_types: set[str] = set()
    curated_patterns: list[dict] = []

    if cp.problem_solving_patterns:
        click.echo()
        click.echo("Step 1 of 2 — Confirm or adjust detected patterns")
        click.echo("─" * 60)

        for pattern in cp.problem_solving_patterns:
            observed_types.add(pattern.pattern_type.value)
            session_count = len(pattern.evidence)
            bar = _strength_bar(pattern.strength)

            click.echo()
            click.echo(
                f"  {pattern.pattern_type.value:<28}  {bar} {pattern.strength}"
                f"  ({session_count} session{'s' if session_count != 1 else ''})"
            )
            click.echo(f'    "{pattern.description[:100]}{"..." if len(pattern.description) > 100 else ""}"')

            adjusted = _prompt_strength_adjust(pattern.pattern_type.value, pattern.strength)

            observed_rank = _STRENGTH_RANK.get(pattern.strength, 0)
            adjusted_rank = _STRENGTH_RANK.get(adjusted, 0)
            delta = adjusted_rank - observed_rank

            curated_patterns.append({
                "pattern_type": pattern.pattern_type.value,
                "observed_strength": pattern.strength,
                "self_reported_strength": adjusted,
                "delta": delta,
                "session_count": session_count,
                "source": "session_evidence",
            })

            if adjusted != pattern.strength:
                click.echo(f"  Adjusted: {pattern.strength} → {adjusted}  (delta: {delta:+d})")
    else:
        click.echo()
        click.echo("  No patterns detected in session data.")

    # ── Step 2: Scenario gap-fill ─────────────────────────────────────────────

    all_pattern_types = {pt.value for pt in PatternType}
    gap_types = sorted(all_pattern_types - observed_types)

    if gap_types and not skip_gaps:
        click.echo()
        click.echo("─" * 60)
        click.echo("Step 2 of 2 — Gap-fill: No session evidence for these patterns")
        click.echo("─" * 60)
        click.echo("  Answer scenario questions to self-report patterns not observed in sessions.")
        click.echo()

        for i, pt_value in enumerate(gap_types, 1):
            scenario = _SCENARIO_QUESTIONS.get(pt_value)
            if not scenario:
                # No scenario defined — skip
                continue

            click.echo(f"Q{i}: {scenario['q']}")
            for letter, (text, _is_strong) in scenario["options"].items():
                click.echo(f"  {letter}) {text}")

            while True:
                answer = click.prompt("  Answer", default="b").strip().lower()
                if answer in scenario["options"]:
                    break
                click.echo("  Please enter a, b, or c.")

            _text, is_strong = scenario["options"][answer]
            strength = "established" if is_strong else "emerging"

            curated_patterns.append({
                "pattern_type": pt_value,
                "observed_strength": None,
                "self_reported_strength": strength,
                "delta": None,
                "session_count": 0,
                "source": "scenario_gap_fill",
            })

            click.echo(f"  -> {pt_value}: self-reported {strength}")
            click.echo()

    elif gap_types and skip_gaps:
        click.echo()
        click.echo(f"  Skipping gap-fill for {len(gap_types)} unobserved pattern(s).")

    # ── Build and save curated profile ────────────────────────────────────────

    default_dir = Path.home() / ".claude-candidate"
    default_dir.mkdir(parents=True, exist_ok=True)

    curated_resume_path = default_dir / "curated_resume.json"
    resume_exists = curated_resume_path.exists()

    curated_data = {
        "curated": True,
        "curated_at": datetime.datetime.now(tz=datetime.timezone.utc).isoformat(),
        "patterns": curated_patterns,
        "resume_integration": {
            "curated_resume_path": str(curated_resume_path),
            "curated_resume_exists": resume_exists,
        },
    }

    out_path = Path(output) if output else default_dir / "curated_profile.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(curated_data, f, indent=2, default=str)

    # ── Summary ───────────────────────────────────────────────────────────────

    click.echo()
    click.echo("=" * 60)
    click.echo("  Profile Review Complete")
    click.echo("─" * 60)

    evidence_count = sum(1 for p in curated_patterns if p["source"] == "session_evidence")
    gap_count = sum(1 for p in curated_patterns if p["source"] == "scenario_gap_fill")
    adjusted_count = sum(
        1 for p in curated_patterns
        if p["source"] == "session_evidence" and p["delta"] != 0
    )

    click.echo(f"  Patterns from sessions:  {evidence_count}")
    click.echo(f"  Patterns from gap-fill:  {gap_count}")
    if adjusted_count:
        click.echo(f"  Patterns adjusted:       {adjusted_count}")

    if resume_exists:
        click.echo()
        click.echo(f"  Resume onboard found at: {curated_resume_path}")
        click.echo("  Both profiles are linked in the curated output.")

    click.echo()
    click.echo(f"  Saved: {out_path}")
    click.echo("=" * 60)
    click.echo()


# === Resume commands ===

@main.group()
def resume() -> None:
    """Resume management commands."""
    pass


@resume.command("ingest")
@click.argument("resume_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output path for the ResumeProfile JSON. Defaults to ~/.claude-candidate/resume_profile.json")
def resume_ingest(resume_path: str, output: str | None) -> None:
    """Parse a resume file and save the structured profile."""
    from claude_candidate.resume_parser import ingest_resume

    path = Path(resume_path)
    click.echo(f"Parsing resume: {path.name}")

    profile = ingest_resume(path)

    # Determine output path
    if output:
        out_path = Path(output)
    else:
        default_dir = Path.home() / ".claude-candidate"
        default_dir.mkdir(parents=True, exist_ok=True)
        out_path = default_dir / "resume_profile.json"

    out_path.write_text(profile.to_json())

    click.echo(f"  Name:        {profile.name or '(not detected)'}")
    click.echo(f"  Title:       {profile.current_title or '(not detected)'}")
    click.echo(f"  Location:    {profile.location or '(not detected)'}")
    click.echo(f"  Roles:       {len(profile.roles)}")
    click.echo(f"  Skills:      {len(profile.skills)}")
    if profile.total_years_experience is not None:
        click.echo(f"  Experience:  ~{profile.total_years_experience:.1f} years")
    click.echo(f"  Hash:        {profile.source_file_hash[:16]}...")
    click.echo(f"\nProfile written to {out_path}")


DEPTH_KEYS = {"1": "mentioned", "2": "used", "3": "applied", "4": "deep", "5": "expert"}
DEPTH_LABELS = "1=mentioned 2=used 3=applied 4=deep 5=expert"


def _prompt_depth(skill_name: str, default: str) -> str:
    """Prompt for depth with single-key input (1-5) or full name."""
    default_key = next((k for k, v in DEPTH_KEYS.items() if v == default), "2")
    while True:
        raw = click.prompt(
            f"  [{DEPTH_LABELS}]",
            default=default_key,
            show_default=True,
        ).strip().lower()
        if raw in DEPTH_KEYS:
            return DEPTH_KEYS[raw]
        if raw in DEPTH_KEYS.values():
            return raw
        click.echo(f"  Invalid: enter 1-5 or a depth name")


@resume.command("onboard")
@click.argument("resume_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output path for curated profile (default: ~/.claude-candidate/curated_resume.json)")
@click.option("--accept-defaults", is_flag=True, default=False,
              help="Accept all parser defaults without prompting")
def resume_onboard(resume_path: str, output: str | None, accept_defaults: bool) -> None:
    """Interactive resume onboarding: parse and curate skill depths.

    Rate each skill with single-key input (1-5) for depth.
    Duration is only prompted for deep (4) and expert (5) skills.
    Use --accept-defaults to skip all prompts and use parser-inferred depths.
    """
    from claude_candidate.resume_parser import ingest_resume
    from claude_candidate.schemas.candidate_profile import DepthLevel

    raw_profile = ingest_resume(Path(resume_path))
    click.echo(f"\nParsed {len(raw_profile.skills)} skills from resume.")

    if not raw_profile.skills:
        click.echo("No skills found in resume. Nothing to curate.")
        return

    if not accept_defaults:
        click.echo(f"Rate each skill: {DEPTH_LABELS}, Enter=accept default, duration for deep/expert only.\n")

    curated_skills = []

    for i, skill in enumerate(raw_profile.skills, 1):
        default_depth = skill.implied_depth.value if skill.implied_depth else "used"

        if accept_defaults:
            depth_str = default_depth
            duration = None
        else:
            click.echo(f"({i}/{len(raw_profile.skills)}) {skill.name}")
            depth_str = _prompt_depth(skill.name, default_depth)

            # Only ask duration for deep/expert — the skills that matter most
            duration = None
            if depth_str in ("deep", "expert"):
                duration = click.prompt(
                    "  Duration (e.g. '3y', '6mo')",
                    default="",
                    show_default=False,
                ).strip() or None

        curated_skills.append({
            "name": skill.name,
            "depth": depth_str,
            "duration": duration,
            "source_context": skill.source_context,
            "curated": True,
        })

    # Summary
    from collections import Counter
    depths = Counter(s["depth"] for s in curated_skills)
    click.echo(f"\n{len(curated_skills)} skills: " + ", ".join(
        f"{v} {k}" for k, v in sorted(depths.items(), key=lambda x: -x[1])
    ))

    # Save curated profile
    output_path = Path(output) if output else Path.home() / ".claude-candidate" / "curated_resume.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    curated_data = raw_profile.model_dump(mode="json")
    curated_data["curated_skills"] = curated_skills
    curated_data["curated"] = True

    with open(output_path, "w") as f:
        json.dump(curated_data, f, indent=2, default=str)

    click.echo(f"Saved: {output_path}")


# === Server commands ===

@main.group()
def server() -> None:
    """Manage the local backend server."""
    pass


@server.command("start")
@click.option("--host", default="127.0.0.1", help="Host to bind the server to")
@click.option("--port", default=7429, help="Port to listen on")
@click.option("--data-dir", type=click.Path(), default=None,
              help="Data directory for profiles and assessments DB")
def server_start(host: str, port: int, data_dir: str | None) -> None:
    """Start the local REST API server."""
    import uvicorn
    from claude_candidate.server import create_app
    data_path = Path(data_dir) if data_dir else Path.home() / ".claude-candidate"
    app = create_app(data_dir=data_path)
    click.echo(f"Starting claude-candidate server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


# === Sessions commands ===

@main.group()
def sessions() -> None:
    """Manage Claude Code session scanning."""
    pass


@sessions.command()
@click.option("--session-dir", type=click.Path(exists=True),
              help="Directory containing session JSONL files")
@click.option("--output", "-o", type=click.Path(),
              help="Output path for CandidateProfile JSON")
def scan(session_dir: str | None, output: str | None) -> None:
    """Scan session logs and build a CandidateProfile."""
    from claude_candidate.session_scanner import discover_sessions
    from claude_candidate.manifest import hash_string
    from claude_candidate.extractor import build_profile_from_signal_results

    from claude_candidate.whitelist import load_whitelist, get_default_whitelist_path, filter_sessions_by_whitelist

    search_dir = Path(session_dir) if session_dir else _default_sessions_dir()
    click.echo(f"Scanning sessions in {search_dir}...")
    sessions_found = discover_sessions(search_dir)
    click.echo(f"  Found {len(sessions_found)} session files")

    # Only apply whitelist when using default session dir (not explicit --session-dir)
    if not session_dir:
        whitelist = load_whitelist(get_default_whitelist_path())
        if whitelist:
            sessions_found = filter_sessions_by_whitelist(sessions_found, whitelist)
            click.echo(f"  After whitelist filter: {len(sessions_found)} sessions")

    if not sessions_found:
        click.echo("No sessions found. Nothing to do.")
        return
    all_results = _process_sessions_v2(sessions_found)
    session_ids = sorted({r.session_id for r in all_results if hasattr(r, "session_id")})
    manifest_hash = hash_string("|".join(session_ids))
    profile = build_profile_from_signal_results(results=all_results, manifest_hash=manifest_hash)
    click.echo(f"  Skills found: {len(profile.skills)}")
    click.echo(f"  Sessions processed: {profile.session_count}")
    output_path = Path(output) if output else _default_profile_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(profile.to_json())
    click.echo(f"  Profile written to {output_path}")


def _process_one_session(info: SessionInfo) -> SessionSignals:
    """Process a single session file — designed for multiprocessing (legacy path)."""
    from claude_candidate.sanitizer import sanitize_text
    from claude_candidate.extractor import extract_session_signals

    raw_content = info.path.read_text(errors="replace")
    sanitized = sanitize_text(raw_content)
    signals = extract_session_signals(sanitized.sanitized)
    signals.session_id = info.session_id
    signals.project_hint = info.project_hint
    return signals


def _process_one_session_v2(info: SessionInfo) -> list:
    """Process a single session: JSONL → sanitize → 3 extractors → SignalResults.

    Returns list of 3 SignalResult objects (one per extractor).
    Designed for multiprocessing — all imports are local.
    """
    from claude_candidate.sanitizer import sanitize_text
    from claude_candidate.extractor import extract_session_to_signals

    raw_content = info.path.read_text(errors="replace")
    sanitized = sanitize_text(raw_content)
    return extract_session_to_signals(
        sanitized.sanitized,
        session_id=info.session_id,
        project_hint=info.project_hint,
    )


def _process_sessions_v2(sessions_found: list[SessionInfo]) -> list:
    """Full extraction pipeline: raw JSONL → 3 extractors, with caching + parallelism."""
    from concurrent.futures import ProcessPoolExecutor
    import os
    import json as json_mod

    from claude_candidate.extraction_cache import load_cache, save_cache, _hash_file

    cache = load_cache()
    cached_results: list = []
    to_process: list[SessionInfo] = []
    file_hashes: dict[str, str] = {}

    # Check cache — cached entries are serialized SignalResult dicts
    for info in sessions_found:
        file_hash = _hash_file(info.path)
        key = f"v2:{info.session_id}:{file_hash}"
        file_hashes[info.session_id] = key
        if key in cache:
            # Deserialize cached SignalResults
            from claude_candidate.extractors import SignalResult
            for sr_dict in cache[key]:
                cached_results.append(SignalResult.model_validate(sr_dict))
        else:
            to_process.append(info)

    click.echo(f"  Cache: {len(cached_results) // 3} cached, {len(to_process)} new/changed")

    if to_process:
        workers = min(os.cpu_count() or 4, 8)
        # Sort largest files first so big sessions start immediately on different workers
        to_process.sort(key=lambda s: s.file_size_bytes, reverse=True)
        click.echo(f"  Processing {len(to_process)} sessions with {workers} workers...")
        with ProcessPoolExecutor(max_workers=workers) as pool:
            batch_results = list(pool.map(_process_one_session_v2, to_process, chunksize=1))

        # Update cache and collect results
        for info, session_results in zip(to_process, batch_results):
            key = file_hashes[info.session_id]
            # Serialize SignalResults for cache
            cache[key] = [sr.model_dump(mode="json") for sr in session_results]
            cached_results.extend(session_results)

        save_cache(cache)

    total = len(sessions_found)
    click.echo(f"  Processed {total}/{total} (100%)")
    return cached_results


def _process_sessions(sessions_found: list[SessionInfo]) -> list[SessionSignals]:
    """Legacy path: sanitize and extract signals (kept for backward compat)."""
    from concurrent.futures import ProcessPoolExecutor
    from dataclasses import asdict
    import os

    from claude_candidate.extraction_cache import load_cache, save_cache, _hash_file
    from claude_candidate.extractor import SessionSignals

    cache = load_cache()
    cached_results: list[SessionSignals] = []
    to_process: list[SessionInfo] = []
    file_hashes: dict[str, str] = {}

    for info in sessions_found:
        file_hash = _hash_file(info.path)
        key = f"{info.session_id}:{file_hash}"
        file_hashes[info.session_id] = key
        if key in cache:
            signals = SessionSignals(**cache[key])
            cached_results.append(signals)
        else:
            to_process.append(info)

    if to_process:
        workers = min(os.cpu_count() or 4, 8)
        to_process.sort(key=lambda s: s.file_size_bytes, reverse=True)
        with ProcessPoolExecutor(max_workers=workers) as pool:
            new_results = list(pool.map(_process_one_session, to_process, chunksize=1))

        for info, signals in zip(to_process, new_results):
            key = file_hashes[info.session_id]
            cache[key] = asdict(signals)

        save_cache(cache)
        cached_results.extend(new_results)

    return cached_results


def _load_curated_resume() -> dict | None:
    """Load curated resume data from ~/.claude-candidate/curated_resume.json.

    Returns the parsed dict if the file exists, None otherwise.
    """
    curated_path = Path.home() / ".claude-candidate" / "curated_resume.json"
    if not curated_path.exists():
        return None
    return json.loads(curated_path.read_text())


def _merge_profile(
    cp,
    rp=None,
    *,
    quiet: bool = False,
):
    """Merge a CandidateProfile, preferring curated resume when available.

    Precedence:
      1. Curated resume (~/.claude-candidate/curated_resume.json) → merge_with_curated()
      2. Parsed resume (rp argument) → merge_profiles()
      3. No resume at all → merge_candidate_only()
    """
    from claude_candidate.merger import merge_profiles, merge_candidate_only, merge_with_curated

    curated = _load_curated_resume()
    if curated and curated.get("curated_skills"):
        if not quiet:
            click.echo("Using curated resume for merge")
        merged = merge_with_curated(
            cp,
            curated["curated_skills"],
            total_years=curated.get("total_years_experience"),
            education=curated.get("education", []),
        )
    elif rp is not None:
        if not quiet:
            click.echo("Using parsed resume for merge")
        merged = merge_profiles(cp, rp)
    else:
        if not quiet:
            click.echo("No resume provided — using sessions only")
        merged = merge_candidate_only(cp)
    return merged


def _default_sessions_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _default_profile_path() -> Path:
    return Path.home() / ".claude-candidate" / "candidate_profile.json"


# === Whitelist commands ===

@main.group()
def whitelist() -> None:
    """Manage session project whitelist."""
    pass


@whitelist.command("setup")
@click.option("--session-dir", type=click.Path(exists=True), default=None,
              help="Directory containing session JSONL files")
@click.option("--filter", "-f", "hint_filter", default=None,
              help="Only show projects whose hint contains this substring (e.g. 'git')")
def whitelist_setup(session_dir: str | None, hint_filter: str | None) -> None:
    """Interactive: discover projects, select which to include."""
    from claude_candidate.session_scanner import discover_sessions
    from claude_candidate.whitelist import (
        WhitelistConfig,
        get_default_whitelist_path,
        save_whitelist,
    )
    from collections import Counter

    search_dir = Path(session_dir) if session_dir else _default_sessions_dir()
    click.echo(f"Scanning sessions in {search_dir}...")
    sessions_found = discover_sessions(search_dir)
    click.echo(f"  Found {len(sessions_found)} session files")

    if not sessions_found:
        click.echo("No sessions found. Nothing to whitelist.")
        return

    counts: Counter[str] = Counter(s.project_hint for s in sessions_found)

    if hint_filter:
        counts = Counter({h: c for h, c in counts.items() if hint_filter.lower() in h.lower()})
        click.echo(f"  Filtered to {len(counts)} projects matching '{hint_filter}'")

    if not counts:
        click.echo("No projects match the filter. Nothing to whitelist.")
        return

    selected: list[str] = []

    click.echo("\nFor each project, choose whether to include it in the whitelist.")
    click.echo("Only include public GitHub projects — keep private/client work out.\n")

    for hint in sorted(counts):
        count = counts[hint]
        label = f"  {hint} ({count} session{'s' if count != 1 else ''})"
        if click.confirm(f"{label} — include?", default=False):
            selected.append(hint)

    config = WhitelistConfig(projects=selected)
    path = get_default_whitelist_path()
    save_whitelist(config, path)

    click.echo(f"\nWhitelist saved to {path}")
    click.echo(f"  Included projects ({len(selected)}): {', '.join(selected) or '(none)'}")


@whitelist.command("show")
def whitelist_show() -> None:
    """Show current whitelist."""
    from claude_candidate.whitelist import get_default_whitelist_path, load_whitelist

    path = get_default_whitelist_path()
    config = load_whitelist(path)

    if config is None:
        click.echo(f"No whitelist found at {path}")
        click.echo("Run `claude-candidate whitelist setup` to create one.")
        return

    click.echo(f"Whitelist: {path}")
    if config.projects:
        click.echo(f"  {len(config.projects)} project(s):")
        for p in sorted(config.projects):
            click.echo(f"    - {p}")
    else:
        click.echo("  (empty — no projects whitelisted)")


# === Site commands ===

@main.group()
def site() -> None:
    """Generate and manage the static application site."""
    pass


@site.command("render")
@click.option("--company", "-c", default=None,
              help="Filter to assessments matching this company name (case-insensitive substring).")
@click.option("--output-dir", "-o", type=click.Path(), default="site",
              help="Root output directory for the rendered site (default: site/).")
@click.option("--db", type=click.Path(), default=None,
              help="Path to assessments database (default: ~/.claude-candidate/assessments.db).")
def site_render(company: str | None, output_dir: str, db: str | None) -> None:
    """Render assessments to static HTML pages under site/apply/.

    Each assessment is rendered to ``{output_dir}/apply/{company-slug}/index.html``.
    Run with no arguments to render all stored assessments.

    After rendering, deploy to Cloudflare Pages:

    \b
    1. Push the site/ directory to a GitHub repo (or use Wrangler CLI):
         wrangler pages deploy site/ --project-name=<your-project>
    2. Or connect the repo to Cloudflare Pages in the dashboard and set
         the build output directory to ``site/``.
    3. Each assessment page is reachable at:
         https://<your-domain>/apply/<company-slug>/
    """
    import asyncio
    import json as _json

    from claude_candidate.schemas.fit_assessment import FitAssessment
    from claude_candidate.site_renderer import render_assessment_page
    from claude_candidate.storage import AssessmentStore

    db_path = Path(db) if db else Path.home() / ".claude-candidate" / "assessments.db"
    output_path = Path(output_dir)

    async def _load_assessments() -> list[dict]:
        store = AssessmentStore(db_path)
        await store.initialize()
        try:
            return await store.list_assessments(limit=500)
        finally:
            await store.close()

    if not db_path.exists():
        click.echo(
            f"No assessments database found at {db_path}.\n"
            "Run an assessment first with `claude-candidate assess` or via the server.",
            err=True,
        )
        return

    records = asyncio.run(_load_assessments())

    if not records:
        click.echo("No assessments found in the database. Nothing to render.")
        return

    # Apply company filter
    if company:
        filter_lower = company.lower()
        records = [r for r in records if filter_lower in (r.get("company_name") or "").lower()]
        if not records:
            click.echo(f"No assessments found matching company '{company}'.")
            return
        click.echo(f"Filtered to {len(records)} assessment(s) matching '{company}'.")
    else:
        click.echo(f"Found {len(records)} assessment(s) to render.")

    rendered_count = 0
    errors: list[str] = []

    for record in records:
        comp = record.get("company_name") or "Unknown"
        title = record.get("job_title") or "Unknown"
        try:
            # The 'data' field holds the full FitAssessment JSON as a dict
            data_field = record.get("data", {})
            assessment_json = _json.dumps(data_field)
            assessment = FitAssessment.from_json(assessment_json)

            # Placeholder content — real generation requires `claude-candidate generate`
            resume_html = (
                f"<p><em>Resume tailored for {comp} – {title} will be generated "
                f"with <code>claude-candidate generate</code>.</em></p>"
            )
            cover_letter = (
                f"Cover letter for {comp} – {title} will be generated "
                f"with `claude-candidate generate`."
            )

            out_file = render_assessment_page(
                assessment=assessment,
                resume_html=resume_html,
                cover_letter=cover_letter,
                output_dir=output_path,
            )
            click.echo(f"  Rendered: {out_file}")
            rendered_count += 1
        except Exception as exc:  # noqa: BLE001
            msg = f"  Error rendering {comp} – {title}: {exc}"
            click.echo(msg, err=True)
            errors.append(msg)

    click.echo(f"\nRendered {rendered_count} page(s) to {output_path.resolve()}/")

    if errors:
        click.echo(f"{len(errors)} page(s) failed — see errors above.", err=True)
    else:
        click.echo(
            "\nTo deploy to Cloudflare Pages:\n"
            "  wrangler pages deploy site/ --project-name=<your-project>"
        )


if __name__ == "__main__":
    main()
