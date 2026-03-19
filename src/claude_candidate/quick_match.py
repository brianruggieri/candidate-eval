"""
QuickMatchEngine: Produces FitAssessments by comparing a MergedEvidenceProfile
against a parsed job posting and optional company profile.

Scores three dimensions with adaptive weighting based on company data richness:
1. Skill gap analysis (50–85% depending on data availability)
2. Company/mission alignment (10–25%)
3. Culture fit signals (5–25%)
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from datetime import datetime

from claude_candidate.schemas.candidate_profile import DepthLevel, DEPTH_RANK
from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.skill_taxonomy import SkillTaxonomy
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
# Lazy-loaded taxonomy (module-level singleton)
# ---------------------------------------------------------------------------

_taxonomy: SkillTaxonomy | None = None


def _get_taxonomy() -> SkillTaxonomy:
    global _taxonomy
    if _taxonomy is None:
        _taxonomy = SkillTaxonomy.load_default()
    return _taxonomy


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
MISSION_TEXT_OVERLAP_WEIGHT = 0.15
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

# Pattern strength → culture match value
CULTURE_PATTERN_STRENGTH_SCORE: dict[str, float] = {
    "exceptional": 1.0,
    "strong": 1.0,
    "established": CULTURE_ESTABLISHED_MATCH,
    "emerging": CULTURE_EMERGING_MATCH,
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
    """Check whether query and skill_name are canonical equivalents (aliases only).

    Deliberately excludes 'related' skills (e.g. docker/kubernetes, react/javascript)
    to avoid inflating match scores. Related skills should map to 'adjacent' status,
    not be treated as the same skill.
    """
    taxonomy = _get_taxonomy()
    canon_query = taxonomy.canonicalize(query)
    canon_skill = taxonomy.canonicalize(skill_name)
    return canon_query == canon_skill


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


def _score_mission_text_alignment(
    profile: MergedEvidenceProfile,
    company_profile: CompanyProfile,
) -> tuple[float, list[str]]:
    """Score mission text alignment; return (bonus, detail_lines).

    Computes keyword overlap between the company's mission statement /
    product description and the candidate's skill names and project
    descriptions.
    """
    text_sources = []
    if company_profile.mission_statement:
        text_sources.append(company_profile.mission_statement)
    text_sources.append(company_profile.product_description)
    if not text_sources:
        return 0.0, []

    combined_text = " ".join(text_sources).lower()
    candidate_keywords: set[str] = {s.name.lower() for s in profile.skills}
    for proj in profile.projects:
        for tech in proj.technologies:
            candidate_keywords.add(tech.lower())

    matched = {kw for kw in candidate_keywords if kw in combined_text}
    if not matched:
        return 0.0, []

    ratio = len(matched) / max(len(candidate_keywords), 1)
    detail = f"Mission text overlap: {', '.join(sorted(matched)[:MAX_TECH_OVERLAP_DISPLAY])}"
    return ratio * MISSION_TEXT_OVERLAP_WEIGHT, [detail]


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

def _match_signal_to_pattern(
    signal: str,
    profile: MergedEvidenceProfile,
) -> tuple[float, str | None]:
    """Match a single culture signal directly to a candidate pattern by name.

    Checks whether any of the candidate's observed patterns have a pattern_type
    whose value (the enum string) appears as a substring of the culture signal,
    or the culture signal appears as a substring of the pattern_type value.
    Returns (match_value, detail_or_None).
    """
    signal_lower = signal.lower()
    for pat in profile.patterns:
        pt_value = pat.pattern_type.value  # e.g. "documentation_driven"
        # Normalize pattern type to words for comparison
        pt_words = pt_value.replace("_", " ")
        if pt_words in signal_lower or signal_lower in pt_words:
            score = CULTURE_PATTERN_STRENGTH_SCORE.get(pat.strength, CULTURE_EMERGING_MATCH)
            if pat.strength in ("strong", "exceptional"):
                return score, f"Strong {pt_words} pattern aligns with '{signal}'"
            if pat.strength == "established":
                return score, f"Established {pt_words} pattern aligns with '{signal}'"
            return score, None
    return 0.0, None


# ---------------------------------------------------------------------------
# Adaptive dimension weighting
# ---------------------------------------------------------------------------

# Weight tuples: (skill, mission, culture)
_WEIGHTS_RICH     = (0.50, 0.25, 0.25)
_WEIGHTS_MODERATE = (0.60, 0.20, 0.20)
_WEIGHTS_SPARSE   = (0.70, 0.15, 0.15)
_WEIGHTS_NONE     = (0.85, 0.10, 0.05)


def _redistribute_culture_weight(
    skill_w: float,
    mission_w: float,
    culture_w: float,
) -> tuple[float, float]:
    """Redistribute culture weight proportionally to skill and mission.

    Returns (new_skill_w, new_mission_w) — culture weight becomes 0 at call site.
    """
    total_remaining = skill_w + mission_w
    if total_remaining == 0.0:
        # Degenerate case: split evenly
        half = culture_w / 2.0
        return skill_w + half, mission_w + half
    skill_ratio = skill_w / total_remaining
    mission_ratio = mission_w / total_remaining
    return skill_w + culture_w * skill_ratio, mission_w + culture_w * mission_ratio


def _compute_weights(
    company_profile: CompanyProfile | None,
) -> tuple[float, float, float]:
    """Return (skill_weight, mission_weight, culture_weight) based on company data richness.

    Tiers:
      rich     → 50/25/25  (mission + tech stack + culture keywords present)
      moderate → 60/20/20  (tech stack + some fields)
      sparse   → 70/15/15  (just job posting, minimal enrichment)
      None     → 85/10/5   (no company data at all)
    """
    if company_profile is None:
        return _WEIGHTS_NONE
    quality = company_profile.enrichment_quality
    if quality == "rich":
        return _WEIGHTS_RICH
    if quality == "moderate":
        return _WEIGHTS_MODERATE
    return _WEIGHTS_SPARSE


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
        skill_w, mission_w, culture_w = _compute_weights(inp.company_profile)

        # Redistribute culture weight to skill and mission when insufficient data
        if culture_dim.insufficient_data:
            skill_w, mission_w = _redistribute_culture_weight(
                skill_w, mission_w, culture_w,
            )
            culture_w = 0.0

        skill_dim.weight = skill_w
        mission_dim.weight = mission_w
        culture_dim.weight = culture_w
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
        """Score mission alignment using three signals when a company profile is available.

        Signals:
        1. Tech stack overlap — company's known technologies vs candidate skills
        2. Industry/domain match — company's product domain vs candidate project domains
        3. Mission text alignment — keyword overlap between mission text and candidate skills
        """
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

        text_bonus, text_details = _score_mission_text_alignment(
            self.profile, company_profile,
        )
        score += text_bonus
        details.extend(text_details)

        return min(score, MISSION_SCORE_MAX), details

    # -- dimension 3: culture fit -------------------------------------------

    def _score_culture_fit(
        self,
        culture_signals: list[str],
        company_profile: CompanyProfile | None,
    ) -> DimensionScore:
        """Score culture/working style fit via direct pattern matching.

        Compares each culture signal to the candidate's observed behavioral
        patterns. If no signals are present, or if the candidate has no
        patterns, marks insufficient_data=True.
        """
        all_signals = self._collect_culture_signals(
            culture_signals, company_profile,
        )
        if not all_signals or not self.profile.patterns:
            return self._neutral_culture_dimension()

        matches, total_signals, details = self._evaluate_culture_signals(
            all_signals,
        )
        score = self._compute_culture_score(matches, total_signals)

        if company_profile and company_profile.remote_policy != "unknown":
            policy = company_profile.remote_policy.replace("_", " ")
            details.append(f"Work policy: {policy}")

        if not details:
            details = ["Culture alignment assessment based on available signals"]

        confidence = matches / total_signals if total_signals > 0 else 0.0

        return DimensionScore(
            dimension="culture_fit",
            score=round(score, SCORE_PRECISION),
            grade=score_to_grade(score),
            summary=f"Culture fit based on {total_signals} pattern signals",
            details=details,
            confidence=round(confidence, SCORE_PRECISION),
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
        """Return a neutral culture dimension when data is insufficient."""
        return DimensionScore(
            dimension="culture_fit",
            score=CULTURE_NEUTRAL_SCORE,
            grade=score_to_grade(CULTURE_NEUTRAL_SCORE),
            summary="Insufficient culture data for assessment",
            details=["No culture signals or candidate patterns available"],
            confidence=0.0,
            insufficient_data=True,
        )

    def _evaluate_culture_signals(
        self,
        signals: list[str],
    ) -> tuple[float, int, list[str]]:
        """Match culture signals directly against candidate patterns.

        Returns (total_match_value, signal_count, detail_lines).
        """
        matches = 0.0
        total_signals = len(signals)
        details: list[str] = []

        for signal in signals:
            value, detail = _match_signal_to_pattern(signal, self.profile)
            matches += value
            if detail:
                details.append(detail)

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
