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
    needs_claude = {"assess", "generate", "job"}
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


@main.command()
@click.option("--assessment", "-a", type=click.Path(exists=True), required=True,
              help="Path to assessment JSON file")
@click.option("--type", "-t", "deliverable_type",
              type=click.Choice(["resume-bullets", "cover-letter", "interview-prep"]),
              required=True,
              help="Type of deliverable to generate")
@click.option("--output", "-o", type=click.Path(),
              help="Output path for generated deliverable")
def generate(assessment: str, deliverable_type: str, output: str | None) -> None:
    """Generate deliverables from an assessment."""
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


@resume.command("onboard")
@click.argument("resume_path", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path(), default=None,
              help="Output path for curated profile (default: ~/.claude-candidate/curated_resume.json)")
def resume_onboard(resume_path: str, output: str | None) -> None:
    """Interactive resume onboarding: parse and curate skill depths."""
    from claude_candidate.resume_parser import ingest_resume
    from claude_candidate.schemas.candidate_profile import DepthLevel

    raw_profile = ingest_resume(Path(resume_path))
    click.echo(f"\nParsed {len(raw_profile.skills)} skills from resume.\n")

    if not raw_profile.skills:
        click.echo("No skills found in resume. Nothing to curate.")
        return

    depth_choices = [d.value for d in DepthLevel]
    curated_skills = []

    for skill in raw_profile.skills:
        click.echo(f"Skill: {skill.name}")
        if skill.years_experience:
            click.echo(f"  Detected: ~{skill.years_experience} years")
        if skill.source_context:
            click.echo(f"  Context: {skill.source_context[:80]}")

        depth_str = click.prompt(
            "  Depth",
            type=click.Choice(depth_choices, case_sensitive=False),
            default=skill.implied_depth.value if skill.implied_depth else "used",
        )
        duration = click.prompt(
            "  Experience duration (e.g. '3 years', '2 months')",
            default="",
            show_default=False,
        )

        curated_skills.append({
            "name": skill.name,
            "depth": depth_str,
            "duration": duration if duration else None,
            "source_context": skill.source_context,
            "curated": True,
        })
        click.echo()

    # Save curated profile
    output_path = Path(output) if output else Path.home() / ".claude-candidate" / "curated_resume.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    curated_data = raw_profile.model_dump(mode="json")
    curated_data["curated_skills"] = curated_skills
    curated_data["curated"] = True

    with open(output_path, "w") as f:
        json.dump(curated_data, f, indent=2, default=str)

    click.echo(f"Curated profile saved: {output_path}")
    click.echo(f"  {len(curated_skills)} skills curated")


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
    from claude_candidate.extractor import build_candidate_profile

    search_dir = Path(session_dir) if session_dir else _default_sessions_dir()
    click.echo(f"Scanning sessions in {search_dir}...")
    sessions_found = discover_sessions(search_dir)
    click.echo(f"  Found {len(sessions_found)} session files")
    if not sessions_found:
        click.echo("No sessions found. Nothing to do.")
        return
    signals_list = _process_sessions(sessions_found)
    manifest_hash = hash_string("|".join(s.session_id for s in signals_list))
    profile = build_candidate_profile(signals_list=signals_list, manifest_hash=manifest_hash)
    click.echo(f"  Skills found: {len(profile.skills)}")
    click.echo(f"  Sessions processed: {profile.session_count}")
    output_path = Path(output) if output else _default_profile_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(profile.to_json())
    click.echo(f"  Profile written to {output_path}")


def _process_sessions(sessions_found: list[SessionInfo]) -> list[SessionSignals]:
    """Sanitize and extract signals from discovered sessions."""
    from claude_candidate.sanitizer import sanitize_text
    from claude_candidate.extractor import extract_session_signals

    signals_list: list[SessionSignals] = []
    for info in sessions_found:
        raw_content = info.path.read_text(errors="replace")
        sanitized = sanitize_text(raw_content)
        signals = extract_session_signals(sanitized.sanitized)
        signals.session_id = info.session_id
        signals.project_hint = info.project_hint
        signals_list.append(signals)
    return signals_list


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
def whitelist_setup(session_dir: str | None) -> None:
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


if __name__ == "__main__":
    main()
