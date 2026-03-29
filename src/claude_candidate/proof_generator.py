"""
Proof Package Generator: Produces a markdown document linking every skill
claim back to session evidence with cryptographic hashes.

Hiring managers can use this document to verify a candidate's assessment.
"""

from __future__ import annotations

from datetime import datetime, timezone

from claude_candidate.pii_gate import scrub_deliverable
from claude_candidate.schemas.fit_assessment import FitAssessment, SkillMatchDetail
from claude_candidate.schemas.merged_profile import MergedEvidenceProfile
from claude_candidate.schemas.session_manifest import SessionManifest

# ---------------------------------------------------------------------------
# Named constants
# ---------------------------------------------------------------------------

GENERATOR_VERSION = "0.1.0"
PRIVACY_NOTICE = (
	"This document was generated from sanitized session data. "
	"Secrets, API keys, and absolute paths are redacted via pattern matching. "
	"PII scrubbing is active: phone numbers, SSNs, credit cards, email addresses, "
	"physical addresses, and honorific-prefixed names are redacted via DataFog + regex. "
	"A session whitelist is available to restrict processing to public GitHub projects."
)
NO_MANIFEST_NOTE = "No session manifest provided for this assessment."
NO_PROFILE_NOTE = "No merged evidence profile provided for this assessment."

# Grade badge mapping
GRADE_BADGES: dict[str, str] = {
	"A+": "A+",
	"A": "A",
	"A-": "A-",
	"B+": "B+",
	"B": "B",
	"B-": "B-",
	"C+": "C+",
	"C": "C",
	"C-": "C-",
	"D": "D",
	"F": "F",
}

# Match status display labels
MATCH_STATUS_LABELS: dict[str, str] = {
	"exceeds": "Exceeds",
	"strong_match": "Strong Match",
	"partial_match": "Partial Match",
	"adjacent": "Adjacent",
	"no_evidence": "No Evidence",
}

# Evidence source display labels
EVIDENCE_SOURCE_LABELS: dict[str, str] = {
	"corroborated": "Corroborated",
	"sessions_only": "Sessions Only",
	"resume_only": "Resume Only",
	"conflicting": "Conflicting",
}

# Verdict display labels
VERDICT_LABELS: dict[str, str] = {
	"strong_yes": "Strong Yes",
	"yes": "Yes",
	"maybe": "Maybe",
	"probably_not": "Probably Not",
	"no": "No",
}

# Section separator
SECTION_SEP = "\n\n---\n\n"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_grade_badge(grade: str) -> str:
	"""Format a letter grade as a display badge."""
	label = GRADE_BADGES.get(grade, grade)
	return f"**{label}**"


def _format_match_status(status: str) -> str:
	"""Format a match status string for display."""
	return MATCH_STATUS_LABELS.get(status, status.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Section generators
# ---------------------------------------------------------------------------


def _header_section(assessment: FitAssessment) -> str:
	"""Render the proof package header with company, title, and grade."""
	date_str = assessment.assessed_at.strftime("%Y-%m-%d")
	lines = [
		f"# Proof Package: {assessment.job_title} at {assessment.company_name}",
		"",
		f"- **Overall Grade:** {_format_grade_badge(assessment.overall_grade)}",
		f"- **Overall Score:** {assessment.overall_score:.2f}",
		f"- **Recommendation:** {VERDICT_LABELS.get(assessment.should_apply, assessment.should_apply)}",
		f"- **Generated:** {date_str}",
		f"- **Assessment ID:** `{assessment.assessment_id}`",
	]
	return "\n".join(lines)


def _summary_section(assessment: FitAssessment) -> str:
	"""Render the assessment summary section."""
	verdict = VERDICT_LABELS.get(
		assessment.should_apply,
		assessment.should_apply,
	)
	lines = [
		"## Assessment Summary",
		"",
		assessment.overall_summary,
		"",
		f"**Verdict:** {verdict}",
		f"**Must-Have Coverage:** {assessment.must_have_coverage}",
		f"**Strongest Match:** {assessment.strongest_match}",
		f"**Biggest Gap:** {assessment.biggest_gap}",
	]
	return "\n".join(lines)


def _skill_row(skill: SkillMatchDetail) -> str:
	"""Format a single skill match as a markdown table row."""
	source_label = EVIDENCE_SOURCE_LABELS.get(
		skill.evidence_source.value,
		skill.evidence_source.value,
	)
	status_label = _format_match_status(skill.match_status)
	return (
		f"| {skill.requirement} | {skill.priority} | {status_label} "
		f"| {source_label} | {skill.candidate_evidence} |"
	)


def _skills_evidence_section(assessment: FitAssessment) -> str:
	"""Render the skills evidence table mapping requirements to evidence."""
	header = [
		"## Skills Evidence",
		"",
		"| Requirement | Priority | Match Status | Evidence Source | Evidence |",
		"|---|---|---|---|---|",
	]
	rows = [_skill_row(s) for s in assessment.skill_matches]
	return "\n".join(header + rows)


def _skills_matrix_section(
	assessment: FitAssessment,
	*,
	profile: MergedEvidenceProfile | None = None,
) -> str:
	"""Render the skills matrix breakdown by evidence source."""
	lines = ["## Skills Matrix", ""]
	if profile:
		lines.extend(
			[
				f"- **Corroborated:** {profile.corroborated_skill_count}",
				f"- **Sessions Only:** {profile.sessions_only_skill_count}",
				f"- **Resume Only:** {profile.resume_only_skill_count}",
				f"- **Discovery:** {len(profile.discovery_skills)}",
			]
		)
	else:
		lines.append(_matrix_from_assessment(assessment))
	_append_gap_lists(lines, assessment)
	return "\n".join(lines)


def _matrix_from_assessment(assessment: FitAssessment) -> str:
	"""Build a skills matrix summary from assessment data alone."""
	corroborated = sum(
		1 for s in assessment.skill_matches if s.evidence_source.value == "corroborated"
	)
	sessions_only = sum(
		1 for s in assessment.skill_matches if s.evidence_source.value == "sessions_only"
	)
	resume_only = sum(
		1 for s in assessment.skill_matches if s.evidence_source.value == "resume_only"
	)
	return (
		f"- **Corroborated:** {corroborated}\n"
		f"- **Sessions Only:** {sessions_only}\n"
		f"- **Resume Only:** {resume_only}\n"
		f"- **Discovery:** {len(assessment.resume_gaps_discovered)}"
	)


def _append_gap_lists(
	lines: list[str],
	assessment: FitAssessment,
) -> None:
	"""Append resume gap and unverified claim lists to output lines."""
	if assessment.resume_gaps_discovered:
		names = ", ".join(assessment.resume_gaps_discovered)
		lines.append(f"\n**Resume Gaps Discovered:** {names}")
	if assessment.resume_unverified:
		names = ", ".join(assessment.resume_unverified)
		lines.append(f"\n**Resume Unverified:** {names}")


def _dimension_scores_section(assessment: FitAssessment) -> str:
	"""Render the dimension scores breakdown."""
	lines = ["## Dimension Scores", ""]
	for dim in (
		assessment.skill_match,
		assessment.mission_alignment,
		assessment.culture_fit,
	):
		if dim is None:
			continue
		label = dim.dimension.replace("_", " ").title()
		lines.append(f"### {label}: {dim.score:.2f} ({_format_grade_badge(dim.grade)})")
		lines.append("")
		lines.append(dim.summary)
		lines.append("")
	return "\n".join(lines)


def _manifest_section(manifest: SessionManifest | None) -> str:
	"""Render the manifest verification section."""
	lines = ["## Manifest Verification", ""]
	if manifest is None:
		lines.append(NO_MANIFEST_NOTE)
		return "\n".join(lines)
	lines.extend(
		[
			f"- **Manifest Hash:** `{manifest.manifest_hash}`",
			f"- **Manifest ID:** `{manifest.manifest_id}`",
			f"- **Session Count:** {manifest.corpus_statistics.total_sessions}",
			f"- **Pipeline Version:** {manifest.pipeline_version}",
		]
	)
	return "\n".join(lines)


def _footer_section() -> str:
	"""Render the proof package footer with version and privacy notice."""
	timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
	lines = [
		"## Footer",
		"",
		f"- **Generator Version:** {GENERATOR_VERSION}",
		f"- **Generated At:** {timestamp}",
		f"- **Profile Privacy:** {PRIVACY_NOTICE}",
	]
	return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_proof_package(
	*,
	assessment: FitAssessment,
	manifest: SessionManifest | None = None,
	profile: MergedEvidenceProfile | None = None,
) -> str:
	"""Generate a markdown proof package from an assessment."""
	sections = [
		_header_section(assessment),
		_summary_section(assessment),
		_skills_evidence_section(assessment),
		_skills_matrix_section(assessment, profile=profile),
		_dimension_scores_section(assessment),
		_manifest_section(manifest),
		_footer_section(),
	]
	return scrub_deliverable(SECTION_SEP.join(sections) + "\n")
