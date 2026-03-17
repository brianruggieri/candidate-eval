"""
QuickMatchEngine: Produces FitAssessments by comparing a MergedEvidenceProfile
against a parsed job posting and optional company profile.

Scores three dimensions equally:
1. Skill gap analysis (33%)
2. Company/mission alignment (33%)
3. Culture fit signals (33%)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from claude_candidate.schemas.candidate_profile import DepthLevel, DEPTH_RANK, PatternType
from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.fit_assessment import (
    DimensionScore,
    FitAssessment,
    SkillMatchDetail,
    score_to_grade,
    score_to_verdict,
)
from claude_candidate.schemas.job_requirements import (
    QuickRequirement,
    RequirementPriority,
    PRIORITY_WEIGHT,
)
from claude_candidate.schemas.merged_profile import (
    EvidenceSource,
    MergedEvidenceProfile,
    MergedSkillEvidence,
)


# ---------------------------------------------------------------------------
# Named constants (no magic numbers)
# ---------------------------------------------------------------------------

# Confidence thresholds for pattern-based evidence
PATTERN_CONFIDENCE_HIGH = 0.85
PATTERN_CONFIDENCE_LOW = 0.6

# Pattern frequency synthetic counts
PATTERN_FREQ_RARE = 3
PATTERN_FREQ_OCCASIONAL = 10
PATTERN_FREQ_COMMON = 25
PATTERN_FREQ_DOMINANT = 50

# Depth match rank offsets
DEPTH_EXCEEDS_OFFSET = 1

# Skill match status scores
STATUS_SCORE_EXCEEDS = 1.0
STATUS_SCORE_STRONG = 0.85
STATUS_SCORE_PARTIAL = 0.55
STATUS_SCORE_ADJACENT = 0.3
STATUS_SCORE_NONE = 0.0

# Status ranking for "best match" selection
STATUS_RANK_EXCEEDS = 4
STATUS_RANK_STRONG = 3
STATUS_RANK_PARTIAL = 2
STATUS_RANK_ADJACENT = 1
STATUS_RANK_NONE = 0

# Mission alignment score adjustments
MISSION_NEUTRAL_SCORE = 0.5
MISSION_DOMAIN_BONUS = 0.15
MISSION_TECH_OVERLAP_WEIGHT = 0.2
MISSION_OSS_BONUS = 0.1
MISSION_NO_ENRICHMENT_BASE = 0.3
MISSION_NO_ENRICHMENT_RANGE = 0.4
MISSION_SCORE_MAX = 1.0

# Culture fit score parameters
CULTURE_NEUTRAL_SCORE = 0.5
CULTURE_BASE_SCORE = 0.3
CULTURE_SIGNAL_WEIGHT = 0.6
CULTURE_ESTABLISHED_MATCH = 0.7
CULTURE_EMERGING_MATCH = 0.3
CULTURE_FULL_MATCH = 1
CULTURE_SCORE_MIN = 0.0
CULTURE_SCORE_MAX = 1.0

# Display limits
TOP_SKILL_DETAILS = 5
MAX_TECH_OVERLAP_DISPLAY = 5
MAX_GAP_NAMES = 2
MAX_RESUME_ITEMS = 3
MAX_ACTION_ITEMS = 6

# Rounding precision
SCORE_PRECISION = 3
TIMING_PRECISION = 2


# ---------------------------------------------------------------------------
# Lookup tables
# ---------------------------------------------------------------------------

# Minimum depth required for each seniority level
SENIORITY_DEPTH_FLOOR: dict[str, DepthLevel] = {
    "junior": DepthLevel.USED,
    "mid": DepthLevel.APPLIED,
    "senior": DepthLevel.DEEP,
    "staff": DepthLevel.DEEP,
    "principal": DepthLevel.EXPERT,
    "director": DepthLevel.DEEP,
    "unknown": DepthLevel.APPLIED,
}

# Skill name abbreviation variants
SKILL_VARIANTS: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "k8s": "kubernetes",
    "pg": "postgresql",
    "postgres": "postgresql",
    "node": "node.js",
    "react.js": "react",
    "vue.js": "vue",
    "next.js": "nextjs",
}

# Pattern strength → DepthLevel
PATTERN_STRENGTH_TO_DEPTH: dict[str, DepthLevel] = {
    "emerging": DepthLevel.USED,
    "established": DepthLevel.APPLIED,
    "strong": DepthLevel.DEEP,
    "exceptional": DepthLevel.EXPERT,
}

# Pattern frequency → synthetic session count
PATTERN_FREQ_TO_COUNT: dict[str, int] = {
    "rare": PATTERN_FREQ_RARE,
    "occasional": PATTERN_FREQ_OCCASIONAL,
    "common": PATTERN_FREQ_COMMON,
    "dominant": PATTERN_FREQ_DOMINANT,
}

# Match status → numeric score
STATUS_SCORE: dict[str, float] = {
    "exceeds": STATUS_SCORE_EXCEEDS,
    "strong_match": STATUS_SCORE_STRONG,
    "partial_match": STATUS_SCORE_PARTIAL,
    "adjacent": STATUS_SCORE_ADJACENT,
    "no_evidence": STATUS_SCORE_NONE,
}

# Match status → rank for comparison
STATUS_RANK: dict[str, int] = {
    "exceeds": STATUS_RANK_EXCEEDS,
    "strong_match": STATUS_RANK_STRONG,
    "partial_match": STATUS_RANK_PARTIAL,
    "adjacent": STATUS_RANK_ADJACENT,
    "no_evidence": STATUS_RANK_NONE,
}

# Match status → display marker
STATUS_MARKER: dict[str, str] = {
    "exceeds": "++",
    "strong_match": "+",
    "partial_match": "~",
    "adjacent": "?",
    "no_evidence": "-",
}

# Verdict → explanatory text
VERDICT_TEXT: dict[str, str] = {
    "strong_yes": "This is a strong fit worth pursuing.",
    "yes": "This is a solid fit that merits an application.",
    "maybe": (
        "This is a mixed fit — worth applying if the role excites you, "
        "but expect gaps to come up."
    ),
    "probably_not": (
        "Significant gaps exist. Consider whether the role aligns "
        "with your growth goals before applying."
    ),
    "no": (
        "Fundamental misalignment between your profile "
        "and this role's requirements."
    ),
}

# Evidence source → human-readable label
SOURCE_LABEL: dict[EvidenceSource, str] = {
    EvidenceSource.CORROBORATED: "Corroborated by both resume and sessions",
    EvidenceSource.SESSIONS_ONLY: "Demonstrated in sessions (not on resume)",
    EvidenceSource.RESUME_ONLY: "Listed on resume (no session evidence)",
    EvidenceSource.CONFLICTING: "Evidence conflicts between resume and sessions",
}

# Culture signal → (PatternType, description) alignment mapping
CULTURE_ALIGNMENTS: dict[str, tuple[PatternType | None, str | None]] = {
    "move fast": (
        PatternType.ITERATIVE_REFINEMENT,
        "Iterative approach aligns with fast-paced culture",
    ),
    "quality first": (
        PatternType.TESTING_INSTINCT,
        "Testing instinct aligns with quality focus",
    ),
    "documentation": (
        PatternType.DOCUMENTATION_DRIVEN,
        "Documentation-driven approach matches",
    ),
    "collaborative": (
        PatternType.COMMUNICATION_CLARITY,
        "Clear communication style supports collaboration",
    ),
    "autonomous": (
        PatternType.SCOPE_MANAGEMENT,
        "Self-directed scope management aligns",
    ),
    "open source": (None, None),
    "pair programming": (
        PatternType.COMMUNICATION_CLARITY,
        "Communication clarity supports pairing",
    ),
    "remote": (
        PatternType.DOCUMENTATION_DRIVEN,
        "Documentation habits support remote work",
    ),
    "agile": (
        PatternType.ITERATIVE_REFINEMENT,
        "Iterative refinement fits agile methodology",
    ),
}


# ---------------------------------------------------------------------------
# Data transfer objects (reduce positional parameter counts)
# ---------------------------------------------------------------------------

@dataclass
class AssessmentInput:
    """Groups the inputs for an assessment to keep parameter counts low."""

    requirements: list[QuickRequirement]
    company: str
    title: str
    posting_url: str | None = None
    source: str = "paste"
    seniority: str = "unknown"
    culture_signals: list[str] | None = None
    tech_stack: list[str] | None = None
    company_profile: CompanyProfile | None = None


@dataclass
class SummaryInput:
    """Groups summary-generation inputs."""

    overall_score: float
    skill_dim: DimensionScore
    mission_dim: DimensionScore
    culture_dim: DimensionScore
    company: str
    title: str
    must_coverage: str


# ---------------------------------------------------------------------------
# Skill matching helpers (module-level)
# ---------------------------------------------------------------------------

def _find_exact_match(
    normalized: str,
    profile: MergedEvidenceProfile,
) -> MergedSkillEvidence | None:
    """Return an exact skill match from the profile."""
    return profile.get_skill(normalized)


def _find_fuzzy_match(
    normalized: str,
    profile: MergedEvidenceProfile,
) -> MergedSkillEvidence | None:
    """Return a fuzzy skill match (substring or known variant)."""
    for skill in profile.skills:
        if normalized in skill.name or skill.name in normalized:
            return skill
        if _is_variant_match(normalized, skill.name):
            return skill
    return None


def _is_variant_match(query: str, skill_name: str) -> bool:
    """Check whether query and skill_name are known abbreviation variants."""
    return (
        SKILL_VARIANTS.get(query) == skill_name
        or SKILL_VARIANTS.get(skill_name) == query
    )


def _pattern_confidence(strength: str) -> float:
    """Return confidence score for a pattern strength level."""
    if strength in ("strong", "exceptional"):
        return PATTERN_CONFIDENCE_HIGH
    return PATTERN_CONFIDENCE_LOW


def _find_pattern_match(
    normalized: str,
    profile: MergedEvidenceProfile,
) -> MergedSkillEvidence | None:
    """Synthesize a MergedSkillEvidence from a matching behavioral pattern."""
    for pattern in profile.patterns:
        if pattern.pattern_type.value != normalized:
            continue
        depth = PATTERN_STRENGTH_TO_DEPTH.get(pattern.strength, DepthLevel.APPLIED)
        freq = PATTERN_FREQ_TO_COUNT.get(pattern.frequency, PATTERN_FREQ_OCCASIONAL)
        return MergedSkillEvidence(
            name=pattern.pattern_type.value,
            source=EvidenceSource.SESSIONS_ONLY,
            session_depth=depth,
            session_frequency=freq,
            session_evidence_count=len(pattern.evidence),
            effective_depth=depth,
            confidence=_pattern_confidence(pattern.strength),
            discovery_flag=True,
        )
    return None


def _find_skill_match(
    skill_name: str,
    profile: MergedEvidenceProfile,
) -> MergedSkillEvidence | None:
    """Find a skill in the merged profile via exact, fuzzy, or pattern match."""
    normalized = skill_name.lower().strip()
    return (
        _find_exact_match(normalized, profile)
        or _find_fuzzy_match(normalized, profile)
        or _find_pattern_match(normalized, profile)
    )


def _assess_depth_match(
    skill: MergedSkillEvidence,
    required_depth: DepthLevel,
) -> str:
    """Assess how well a skill's depth matches a requirement."""
    actual_rank = DEPTH_RANK.get(skill.effective_depth, 0)
    required_rank = DEPTH_RANK.get(required_depth, 0)

    if actual_rank >= required_rank + DEPTH_EXCEEDS_OFFSET:
        return "exceeds"
    if actual_rank >= required_rank:
        return "strong_match"
    if actual_rank >= required_rank - DEPTH_EXCEEDS_OFFSET:
        return "partial_match"
    return "adjacent"


def _evidence_summary(skill: MergedSkillEvidence) -> str:
    """Generate a brief evidence summary for a matched skill."""
    parts = []
    label = SOURCE_LABEL.get(skill.source)
    if label:
        parts.append(label)
    if skill.session_frequency:
        parts.append(f"{skill.session_frequency} sessions")
    if skill.resume_years:
        parts.append(f"{skill.resume_years}y on resume")
    parts.append(f"depth: {skill.effective_depth.value}")
    return ". ".join(parts)


# ---------------------------------------------------------------------------
# Skill scoring helpers
# ---------------------------------------------------------------------------

def _find_best_skill(
    req: QuickRequirement,
    profile: MergedEvidenceProfile,
    depth_floor: DepthLevel,
) -> tuple[MergedSkillEvidence | None, str]:
    """Find the best matching skill for a requirement across all mappings."""
    best_match: MergedSkillEvidence | None = None
    best_status = "no_evidence"
    for skill_name in req.skill_mapping:
        found = _find_skill_match(skill_name, profile)
        if not found:
            continue
        status = _assess_depth_match(found, depth_floor)
        if STATUS_RANK.get(status, 0) > STATUS_RANK.get(best_status, 0):
            best_match = found
            best_status = status
    return best_match, best_status


def _score_requirement(
    best_match: MergedSkillEvidence | None,
    best_status: str,
) -> float:
    """Compute the score for one requirement given its best match."""
    req_score = STATUS_SCORE.get(best_status, STATUS_SCORE_NONE)
    if best_match:
        req_score *= best_match.confidence
    return req_score


def _build_skill_detail(
    req: QuickRequirement,
    best_match: MergedSkillEvidence | None,
    best_status: str,
) -> SkillMatchDetail:
    """Build a SkillMatchDetail for one requirement."""
    return SkillMatchDetail(
        requirement=req.description,
        priority=req.priority.value,
        match_status=best_status,
        candidate_evidence=(
            _evidence_summary(best_match) if best_match else "No evidence found"
        ),
        evidence_source=(
            best_match.source if best_match else EvidenceSource.RESUME_ONLY
        ),
        confidence=best_match.confidence if best_match else 0.0,
    )


def _format_detail_point(detail: SkillMatchDetail) -> str:
    """Format a single skill detail into a display string."""
    marker = STATUS_MARKER.get(detail.match_status, "?")
    status_label = detail.match_status.replace("_", " ")
    return f"[{marker}] {detail.requirement}: {status_label}"


def _build_skill_dimension(
    score: float,
    details: list[SkillMatchDetail],
) -> DimensionScore:
    """Build the skill_match DimensionScore from scored details."""
    met = sum(1 for d in details if d.match_status in ("strong_match", "exceeds"))
    partial = sum(1 for d in details if d.match_status == "partial_match")
    missing = sum(1 for d in details if d.match_status == "no_evidence")
    summary = f"{met} requirements strongly matched, {partial} partial, {missing} gaps."

    sorted_details = sorted(
        details,
        key=lambda x: PRIORITY_WEIGHT.get(RequirementPriority(x.priority), 0),
        reverse=True,
    )[:TOP_SKILL_DETAILS]
    detail_points = [_format_detail_point(d) for d in sorted_details]

    return DimensionScore(
        dimension="skill_match",
        score=round(score, SCORE_PRECISION),
        grade=score_to_grade(score),
        summary=summary,
        details=detail_points or ["No requirements to evaluate"],
    )


# ---------------------------------------------------------------------------
# Mission alignment helpers
# ---------------------------------------------------------------------------

def _candidate_domain_set(profile: MergedEvidenceProfile) -> set[str]:
    """Collect candidate domain keywords from projects and roles."""
    domains: set[str] = set()
    for proj in profile.projects:
        for tech in proj.technologies:
            domains.add(tech.lower())
    for role in profile.roles:
        if role.domain:
            domains.add(role.domain.lower())
    return domains


def _candidate_skill_names(profile: MergedEvidenceProfile) -> set[str]:
    """Return the set of candidate skill names."""
    return {s.name for s in profile.skills}


def _score_domain_overlap(
    profile: MergedEvidenceProfile,
    company_profile: CompanyProfile,
) -> tuple[float, list[str]]:
    """Score domain overlap; return (bonus, detail_lines)."""
    candidate_domains = _candidate_domain_set(profile)
    company_domains = {d.lower() for d in company_profile.product_domain}
    overlap = candidate_domains & company_domains
    if overlap:
        return MISSION_DOMAIN_BONUS, [
            f"Domain overlap: {', '.join(sorted(overlap))}"
        ]
    return 0.0, []


def _score_tech_overlap(
    profile: MergedEvidenceProfile,
    company_profile: CompanyProfile,
) -> tuple[float, list[str]]:
    """Score tech-stack overlap; return (bonus, detail_lines)."""
    company_techs = {t.lower() for t in company_profile.tech_stack_public}
    candidate_techs = _candidate_skill_names(profile)
    overlap = company_techs & candidate_techs
    if overlap:
        ratio = len(overlap) / max(len(company_techs), 1)
        detail = f"Tech overlap: {', '.join(sorted(overlap)[:MAX_TECH_OVERLAP_DISPLAY])}"
        return ratio * MISSION_TECH_OVERLAP_WEIGHT, [detail]
    return 0.0, []


def _score_oss_alignment(
    profile: MergedEvidenceProfile,
    company_profile: CompanyProfile,
) -> tuple[float, list[str]]:
    """Score open-source alignment; return (bonus, detail_lines)."""
    has_oss = any(p.public_repo_url for p in profile.projects)
    if has_oss and company_profile.oss_activity_level in ("active", "very_active"):
        return MISSION_OSS_BONUS, ["Strong open source alignment"]
    return 0.0, []


def _blog_details(company_profile: CompanyProfile) -> list[str]:
    """Return detail line for engineering blog activity, if any."""
    if company_profile.recent_blog_topics:
        count = len(company_profile.recent_blog_topics)
        return [f"Engineering blog active: {count} recent posts"]
    return []


def _mission_from_posting(
    profile: MergedEvidenceProfile,
    tech_stack: list[str],
) -> tuple[float, list[str]]:
    """Score mission alignment from the posting tech stack alone."""
    score = MISSION_NEUTRAL_SCORE
    details: list[str] = []
    if tech_stack:
        posting_techs = {t.lower() for t in tech_stack}
        candidate_techs = _candidate_skill_names(profile)
        overlap = posting_techs & candidate_techs
        if overlap:
            ratio = len(overlap) / max(len(posting_techs), 1)
            score = MISSION_NO_ENRICHMENT_BASE + ratio * MISSION_NO_ENRICHMENT_RANGE
            details.append(
                f"Tech stack overlap: "
                f"{', '.join(sorted(overlap)[:MAX_TECH_OVERLAP_DISPLAY])}"
            )
    details.append(
        "Limited enrichment data — score based on posting tech stack only"
    )
    return score, details


# ---------------------------------------------------------------------------
# Culture fit helpers
# ---------------------------------------------------------------------------

def _score_culture_signal(
    pattern: PatternType | None,
    description: str | None,
    pattern_types: set[PatternType],
    pattern_strengths: dict[PatternType, str],
) -> tuple[float, str | None]:
    """Score a single culture signal alignment. Returns (match_value, detail)."""
    if not pattern or pattern not in pattern_types:
        return 0.0, None
    strength = pattern_strengths.get(pattern, "emerging")
    if strength in ("strong", "exceptional"):
        return CULTURE_FULL_MATCH, f"Strong: {description}"
    if strength == "established":
        return CULTURE_ESTABLISHED_MATCH, f"Good: {description}"
    return CULTURE_EMERGING_MATCH, None


def _score_oss_culture(
    signals_lower: set[str],
    profile: MergedEvidenceProfile,
) -> tuple[float, str | None, bool]:
    """Check open-source culture signal. Returns (match_value, detail, found)."""
    if not any("open source" in sig for sig in signals_lower):
        return 0.0, None, False
    has_oss = any(p.public_repo_url for p in profile.projects)
    if has_oss:
        return CULTURE_FULL_MATCH, "Active open source contributor", True
    return 0.0, "No public OSS contributions found", True


# ---------------------------------------------------------------------------
# Assessment result builders
# ---------------------------------------------------------------------------

def _compute_overall_score(
    skill_dim: DimensionScore,
    mission_dim: DimensionScore,
    culture_dim: DimensionScore,
) -> float:
    """Compute weighted overall score from three dimensions."""
    return (
        skill_dim.score * skill_dim.weight
        + mission_dim.score * mission_dim.weight
        + culture_dim.score * culture_dim.weight
    )


def _must_have_coverage(details: list[SkillMatchDetail]) -> str:
    """Summarize must-have requirement coverage."""
    must_haves = [d for d in details if d.priority == "must_have"]
    if not must_haves:
        return "No must-haves specified"
    met = sum(
        1 for d in must_haves if d.match_status in ("strong_match", "exceeds")
    )
    return f"{met}/{len(must_haves)} must-haves met"


def _strongest_and_gap(
    details: list[SkillMatchDetail],
) -> tuple[str, str]:
    """Identify the strongest match and biggest gap from skill details."""
    strong = [
        d for d in details if d.match_status in ("strong_match", "exceeds")
    ]
    gaps = [
        d for d in details
        if d.match_status == "no_evidence"
        and d.priority in ("must_have", "strong_preference")
    ]
    strongest = strong[0].requirement if strong else "None identified"
    biggest_gap = (
        gaps[0].requirement if gaps else "None — all requirements addressed"
    )
    return strongest, biggest_gap


def _discover_resume_gaps(
    profile: MergedEvidenceProfile,
    requirements: list[QuickRequirement],
) -> list[str]:
    """Find skills demonstrated in sessions but missing from resume."""
    return [
        s.name for s in profile.skills
        if s.discovery_flag and any(
            s.name in r.skill_mapping
            or any(s.name in sm for sm in r.skill_mapping)
            for r in requirements
        )
    ]


def _find_resume_unverified(
    profile: MergedEvidenceProfile,
    requirements: list[QuickRequirement],
) -> list[str]:
    """Find resume skills relevant to the role without session backing."""
    all_required: set[str] = set()
    for req in requirements:
        all_required.update(s.lower() for s in req.skill_mapping)
    return [
        s.name for s in profile.skills
        if s.source == EvidenceSource.RESUME_ONLY and s.name in all_required
    ]


# ---------------------------------------------------------------------------
# QuickMatchEngine
# ---------------------------------------------------------------------------

class QuickMatchEngine:
    """
    Produces FitAssessments against a cached MergedEvidenceProfile.

    The profile is loaded once; multiple job postings can be assessed against it.
    """

    def __init__(self, profile: MergedEvidenceProfile):
        self.profile = profile

    def assess(
        self,
        requirements: list[QuickRequirement],
        company: str,
        title: str,
        posting_url: str | None = None,
        source: str = "paste",
        seniority: str = "unknown",
        culture_signals: list[str] | None = None,
        tech_stack: list[str] | None = None,
        company_profile: CompanyProfile | None = None,
    ) -> FitAssessment:
        """Run the three-dimensional fit assessment."""
        inp = AssessmentInput(
            requirements=requirements,
            company=company,
            title=title,
            posting_url=posting_url,
            source=source,
            seniority=seniority,
            culture_signals=culture_signals,
            tech_stack=tech_stack,
            company_profile=company_profile,
        )
        return self._run_assessment(inp)

    # -- orchestration ------------------------------------------------------

    def _run_assessment(self, inp: AssessmentInput) -> FitAssessment:
        """Orchestrate the three dimensions and assemble the result."""
        start_time = time.time()
        skill_dim, skill_details = self._score_skill_match(
            inp.requirements, inp.seniority,
        )
        mission_dim = self._score_mission_alignment(
            inp.company, inp.tech_stack or [], inp.company_profile,
        )
        culture_dim = self._score_culture_fit(
            inp.culture_signals or [], inp.company_profile,
        )
        overall_score = _compute_overall_score(skill_dim, mission_dim, culture_dim)
        elapsed = time.time() - start_time
        return self._build_assessment(
            inp, skill_dim, mission_dim, culture_dim,
            skill_details, overall_score, elapsed,
        )

    def _build_assessment(
        self,
        inp: AssessmentInput,
        skill_dim: DimensionScore,
        mission_dim: DimensionScore,
        culture_dim: DimensionScore,
        skill_details: list[SkillMatchDetail],
        overall_score: float,
        elapsed: float,
    ) -> FitAssessment:
        """Assemble the final FitAssessment from scored dimensions."""
        must_cov = _must_have_coverage(skill_details)
        strongest, biggest_gap = _strongest_and_gap(skill_details)
        resume_gaps = _discover_resume_gaps(self.profile, inp.requirements)
        resume_unverified = _find_resume_unverified(self.profile, inp.requirements)
        gaps = [
            d for d in skill_details
            if d.match_status == "no_evidence"
            and d.priority in ("must_have", "strong_preference")
        ]
        summary_inp = SummaryInput(
            overall_score=overall_score,
            skill_dim=skill_dim,
            mission_dim=mission_dim,
            culture_dim=culture_dim,
            company=inp.company,
            title=inp.title,
            must_coverage=must_cov,
        )
        return self._assemble_fit_assessment(
            inp, summary_inp, skill_dim, mission_dim, culture_dim,
            skill_details, strongest, biggest_gap, resume_gaps,
            resume_unverified, gaps, overall_score, elapsed,
        )

    def _assemble_fit_assessment(
        self,
        inp: AssessmentInput,
        summary_inp: SummaryInput,
        skill_dim: DimensionScore,
        mission_dim: DimensionScore,
        culture_dim: DimensionScore,
        skill_details: list[SkillMatchDetail],
        strongest: str,
        biggest_gap: str,
        resume_gaps: list[str],
        resume_unverified: list[str],
        gaps: list[SkillMatchDetail],
        overall_score: float,
        elapsed: float,
    ) -> FitAssessment:
        """Construct the FitAssessment pydantic model."""
        return FitAssessment(
            assessment_id=str(uuid.uuid4()),
            assessed_at=datetime.now(),
            job_title=inp.title,
            company_name=inp.company,
            posting_url=inp.posting_url,
            source=inp.source,
            overall_score=round(overall_score, SCORE_PRECISION),
            overall_grade=score_to_grade(overall_score),
            overall_summary=self._generate_summary(summary_inp),
            skill_match=skill_dim,
            mission_alignment=mission_dim,
            culture_fit=culture_dim,
            skill_matches=skill_details,
            must_have_coverage=summary_inp.must_coverage,
            strongest_match=strongest,
            biggest_gap=biggest_gap,
            resume_gaps_discovered=resume_gaps,
            resume_unverified=resume_unverified,
            company_profile_summary=(
                inp.company_profile.product_description
                if inp.company_profile
                else f"No enrichment data available for {inp.company}"
            ),
            company_enrichment_quality=(
                inp.company_profile.enrichment_quality
                if inp.company_profile
                else "none"
            ),
            should_apply=score_to_verdict(overall_score),
            action_items=self._generate_action_items(
                overall_score, gaps, resume_gaps, resume_unverified, inp.company,
            ),
            profile_hash=self.profile.profile_hash,
            time_to_assess_seconds=round(elapsed, TIMING_PRECISION),
        )

    # -- dimension 1: skill match -------------------------------------------

    def _score_skill_match(
        self,
        requirements: list[QuickRequirement],
        seniority: str,
    ) -> tuple[DimensionScore, list[SkillMatchDetail]]:
        """Score the skill gap analysis dimension."""
        depth_floor = SENIORITY_DEPTH_FLOOR.get(seniority, DepthLevel.APPLIED)
        details: list[SkillMatchDetail] = []
        weighted_score = 0.0
        total_weight = 0.0

        for req in requirements:
            weight = PRIORITY_WEIGHT.get(req.priority, 1.0)
            total_weight += weight
            best_match, best_status = _find_best_skill(
                req, self.profile, depth_floor,
            )
            weighted_score += _score_requirement(best_match, best_status) * weight
            details.append(_build_skill_detail(req, best_match, best_status))

        score = weighted_score / total_weight if total_weight > 0 else 0.0
        return _build_skill_dimension(score, details), details

    # -- dimension 2: mission alignment -------------------------------------

    def _score_mission_alignment(
        self,
        company: str,
        tech_stack: list[str],
        company_profile: CompanyProfile | None,
    ) -> DimensionScore:
        """Score company/mission alignment."""
        if company_profile:
            score, details = self._mission_with_profile(company_profile)
        else:
            score, details = _mission_from_posting(self.profile, tech_stack)

        if not details:
            details = ["Insufficient data for mission alignment assessment"]

        return DimensionScore(
            dimension="mission_alignment",
            score=round(score, SCORE_PRECISION),
            grade=score_to_grade(score),
            summary=f"Mission alignment with {company}: {score_to_grade(score)}",
            details=details,
        )

    def _mission_with_profile(
        self,
        company_profile: CompanyProfile,
    ) -> tuple[float, list[str]]:
        """Score mission alignment when a company profile is available."""
        score = MISSION_NEUTRAL_SCORE
        details: list[str] = []

        domain_bonus, domain_details = _score_domain_overlap(
            self.profile, company_profile,
        )
        score += domain_bonus
        details.extend(domain_details)

        tech_bonus, tech_details = _score_tech_overlap(
            self.profile, company_profile,
        )
        score += tech_bonus
        details.extend(tech_details)

        oss_bonus, oss_details = _score_oss_alignment(
            self.profile, company_profile,
        )
        score += oss_bonus
        details.extend(oss_details)

        details.extend(_blog_details(company_profile))
        return min(score, MISSION_SCORE_MAX), details

    # -- dimension 3: culture fit -------------------------------------------

    def _score_culture_fit(
        self,
        culture_signals: list[str],
        company_profile: CompanyProfile | None,
    ) -> DimensionScore:
        """Score culture/working style fit."""
        all_signals = self._collect_culture_signals(
            culture_signals, company_profile,
        )
        if not all_signals:
            return self._neutral_culture_dimension()

        signals_lower = {s.lower() for s in all_signals}
        matches, total_signals, details = self._evaluate_culture_signals(
            signals_lower,
        )
        score = self._compute_culture_score(matches, total_signals)

        if company_profile and company_profile.remote_policy != "unknown":
            policy = company_profile.remote_policy.replace("_", " ")
            details.append(f"Work policy: {policy}")

        if not details:
            details = ["Culture alignment assessment based on available signals"]

        return DimensionScore(
            dimension="culture_fit",
            score=round(score, SCORE_PRECISION),
            grade=score_to_grade(score),
            summary=f"Culture fit based on {total_signals} detected signals",
            details=details,
        )

    def _collect_culture_signals(
        self,
        culture_signals: list[str],
        company_profile: CompanyProfile | None,
    ) -> list[str]:
        """Merge culture signals from the posting and company profile."""
        all_signals = list(culture_signals)
        if company_profile:
            all_signals.extend(company_profile.culture_keywords)
        return all_signals

    def _neutral_culture_dimension(self) -> DimensionScore:
        """Return a neutral culture dimension when no signals exist."""
        return DimensionScore(
            dimension="culture_fit",
            score=CULTURE_NEUTRAL_SCORE,
            grade=score_to_grade(CULTURE_NEUTRAL_SCORE),
            summary="Insufficient culture signals for assessment",
            details=["No culture signals found in posting or company profile"],
        )

    def _evaluate_culture_signals(
        self,
        signals_lower: set[str],
    ) -> tuple[float, int, list[str]]:
        """Evaluate all culture alignments. Returns (matches, total, details)."""
        pattern_types = {p.pattern_type for p in self.profile.patterns}
        pattern_strengths = {
            p.pattern_type: p.strength for p in self.profile.patterns
        }
        matches = 0.0
        total_signals = 0
        details: list[str] = []

        for signal_key, (pattern, description) in CULTURE_ALIGNMENTS.items():
            if not any(signal_key in sig for sig in signals_lower):
                continue
            if signal_key == "open source":
                continue  # handled separately
            total_signals += 1
            value, detail = _score_culture_signal(
                pattern, description, pattern_types, pattern_strengths,
            )
            matches += value
            if detail:
                details.append(detail)

        oss_value, oss_detail, oss_found = _score_oss_culture(
            signals_lower, self.profile,
        )
        if oss_found:
            total_signals += 1
            matches += oss_value
        if oss_detail:
            details.append(oss_detail)

        return matches, total_signals, details

    def _compute_culture_score(self, matches: float, total: int) -> float:
        """Compute bounded culture fit score from match ratio."""
        if total > 0:
            score = CULTURE_BASE_SCORE + (matches / total) * CULTURE_SIGNAL_WEIGHT
        else:
            score = CULTURE_NEUTRAL_SCORE
        return min(max(score, CULTURE_SCORE_MIN), CULTURE_SCORE_MAX)

    # -- summary & action items ---------------------------------------------

    def _generate_summary(self, inp: SummaryInput) -> str:
        """Generate the overall summary paragraph."""
        grade = score_to_grade(inp.overall_score)
        verdict = score_to_verdict(inp.overall_score)
        strongest, weakest = self._strongest_weakest_dims(inp)
        return (
            f"Overall {grade} fit for {inp.title} at {inp.company}. "
            f"{inp.must_coverage}. "
            f"Strongest dimension: {strongest[0]} ({score_to_grade(strongest[1])}). "
            f"Weakest dimension: {weakest[0]} ({score_to_grade(weakest[1])}). "
            f"{VERDICT_TEXT.get(verdict, '')}"
        )

    def _strongest_weakest_dims(
        self,
        inp: SummaryInput,
    ) -> tuple[tuple[str, float], tuple[str, float]]:
        """Find the strongest and weakest dimension by score."""
        dims = [
            ("Skills", inp.skill_dim.score),
            ("Mission", inp.mission_dim.score),
            ("Culture", inp.culture_dim.score),
        ]
        return max(dims, key=lambda x: x[1]), min(dims, key=lambda x: x[1])

    def _generate_action_items(
        self,
        overall_score: float,
        gaps: list[SkillMatchDetail],
        resume_gaps: list[str],
        resume_unverified: list[str],
        company: str,
    ) -> list[str]:
        """Generate concrete next-step action items."""
        items: list[str] = []
        verdict = score_to_verdict(overall_score)
        self._add_verdict_actions(items, verdict, company)
        self._add_gap_actions(items, gaps, resume_gaps, resume_unverified)
        if not items:
            items.append("Review the detailed skill breakdown for more context")
        return items[:MAX_ACTION_ITEMS]

    def _add_verdict_actions(
        self,
        items: list[str],
        verdict: str,
        company: str,
    ) -> None:
        """Append action items driven by the overall verdict."""
        if verdict in ("strong_yes", "yes"):
            items.append("Generate full application package for this role")
        if verdict in ("maybe", "probably_not"):
            items.append(
                f"Research {company}'s engineering blog and "
                f"recent projects before deciding"
            )

    def _add_gap_actions(
        self,
        items: list[str],
        gaps: list[SkillMatchDetail],
        resume_gaps: list[str],
        resume_unverified: list[str],
    ) -> None:
        """Append action items related to gaps and unverified claims."""
        if resume_gaps:
            names = ", ".join(resume_gaps[:MAX_RESUME_ITEMS])
            items.append(
                f"Update resume to include: {names} "
                f"(demonstrated in sessions but missing from resume)"
            )
        if gaps:
            gap_names = [g.requirement for g in gaps[:MAX_GAP_NAMES]]
            items.append(f"Key gaps to address: {', '.join(gap_names)}")
        if resume_unverified:
            names = ", ".join(resume_unverified[:MAX_RESUME_ITEMS])
            items.append(
                f"Resume claims without session evidence: {names} "
                f"— prepare to discuss these in interviews"
            )
