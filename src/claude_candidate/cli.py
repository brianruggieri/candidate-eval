"""
CLI entry point for claude-candidate.

Provides subcommands for each pipeline stage plus a `poc` command
that runs the full v0.1 proof-of-concept flow.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import click

from claude_candidate import __version__


@click.group()
@click.version_option(__version__)
def main() -> None:
    """claude-candidate: Honest job fit assessment from your resume + Claude Code sessions."""
    pass


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
    from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority
    from claude_candidate.schemas.resume_profile import ResumeProfile
    from claude_candidate.merger import merge_profiles, merge_candidate_only
    from claude_candidate.quick_match import QuickMatchEngine

    click.echo(f"Loading candidate profile from {profile}...")
    cp = CandidateProfile.from_json(Path(profile).read_text())

    if resume:
        click.echo(f"Loading resume profile from {resume}...")
        rp = ResumeProfile.from_json(Path(resume).read_text())
        merged = merge_profiles(cp, rp)
        click.echo(f"  Merged: {merged.corroborated_skill_count} corroborated, "
                    f"{merged.sessions_only_skill_count} sessions-only, "
                    f"{merged.resume_only_skill_count} resume-only")
    else:
        click.echo("No resume provided — using sessions only")
        merged = merge_candidate_only(cp)

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
        click.echo("No .requirements.json found — using placeholder requirements")
        click.echo("  (Full implementation will use Claude Code to parse requirements from text)")
        requirements = _extract_basic_requirements(job_text)

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


def _print_assessment_card(assessment) -> None:
    """Print a formatted assessment card to the terminal."""
    try:
        from rich.console import Console
        from rich.panel import Panel
        from rich.table import Table
        from rich.text import Text
        _print_rich_card(assessment)
    except ImportError:
        _print_plain_card(assessment)


def _print_rich_card(assessment) -> None:
    """Print assessment card using rich library."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text

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

    for dim in [assessment.skill_match, assessment.mission_alignment, assessment.culture_fit]:
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
    bar = lambda score: "█" * int(score * 20) + "░" * (20 - int(score * 20))

    print(f"\n{'='*50}")
    print(f"  {assessment.company_name}")
    print(f"  {assessment.job_title}")
    print(f"{'─'*50}")
    print(f"  Overall: {assessment.overall_grade} ({assessment.overall_score:.0%})")
    print(f"  {bar(assessment.overall_score)}")
    print()
    print(f"  Skills:  {bar(assessment.skill_match.score)} {assessment.skill_match.grade}")
    print(f"  Mission: {bar(assessment.mission_alignment.score)} {assessment.mission_alignment.grade}")
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
    from claude_candidate.merger import merge_profiles, merge_candidate_only

    cp = CandidateProfile.from_json(Path(candidate).read_text())

    if resume:
        rp = ResumeProfile.from_json(Path(resume).read_text())
        merged = merge_profiles(cp, rp)
    else:
        merged = merge_candidate_only(cp)

    Path(output).write_text(merged.to_json())
    click.echo(f"Merged profile written to {output}")
    click.echo(f"  Skills: {len(merged.skills)}")
    click.echo(f"  Corroborated: {merged.corroborated_skill_count}")
    click.echo(f"  Sessions-only: {merged.sessions_only_skill_count}")
    click.echo(f"  Resume-only: {merged.resume_only_skill_count}")
    if merged.discovery_skills:
        click.echo(f"  Discovery: {', '.join(merged.discovery_skills)}")


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


if __name__ == "__main__":
    main()
