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


def _find_skill_match(
    skill_name: str,
    profile: MergedEvidenceProfile,
) -> MergedSkillEvidence | None:
    """Find a skill in the merged profile, trying exact, fuzzy, then pattern match."""
    normalized = skill_name.lower().strip()

    # Exact match
    exact = profile.get_skill(normalized)
    if exact:
        return exact

    # Fuzzy: check if skill_name is a substring or close variant
    for skill in profile.skills:
        if normalized in skill.name or skill.name in normalized:
            return skill
        # Handle common variants
        variants = {
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
        if variants.get(normalized) == skill.name or variants.get(skill.name) == normalized:
            return skill

    # Pattern match: if the skill_name maps to a ProblemSolvingPattern type,
    # synthesize a MergedSkillEvidence from the pattern data.
    # This bridges requirements like "modular_thinking" or "architecture_first"
    # to behavioral evidence from session logs.
    pattern_strength_to_depth = {
        "emerging": DepthLevel.USED,
        "established": DepthLevel.APPLIED,
        "strong": DepthLevel.DEEP,
        "exceptional": DepthLevel.EXPERT,
    }
    pattern_freq_to_count = {
        "rare": 3,
        "occasional": 10,
        "common": 25,
        "dominant": 50,
    }

    for pattern in profile.patterns:
        if pattern.pattern_type.value == normalized:
            depth = pattern_strength_to_depth.get(pattern.strength, DepthLevel.APPLIED)
            freq = pattern_freq_to_count.get(pattern.frequency, 10)
            return MergedSkillEvidence(
                name=pattern.pattern_type.value,
                source=EvidenceSource.SESSIONS_ONLY,
                session_depth=depth,
                session_frequency=freq,
                session_evidence_count=len(pattern.evidence),
                effective_depth=depth,
                confidence=0.85 if pattern.strength in ("strong", "exceptional") else 0.6,
                discovery_flag=True,
            )

    return None


def _assess_depth_match(
    skill: MergedSkillEvidence,
    required_depth: DepthLevel,
) -> str:
    """Assess how well a skill's depth matches a requirement."""
    actual_rank = DEPTH_RANK.get(skill.effective_depth, 0)
    required_rank = DEPTH_RANK.get(required_depth, 0)

    if actual_rank >= required_rank + 1:
        return "exceeds"
    elif actual_rank >= required_rank:
        return "strong_match"
    elif actual_rank >= required_rank - 1:
        return "partial_match"
    else:
        return "adjacent"


def _evidence_summary(skill: MergedSkillEvidence) -> str:
    """Generate a brief evidence summary for a matched skill."""
    parts = []
    if skill.source == EvidenceSource.CORROBORATED:
        parts.append("Corroborated by both resume and sessions")
    elif skill.source == EvidenceSource.SESSIONS_ONLY:
        parts.append("Demonstrated in sessions (not on resume)")
    elif skill.source == EvidenceSource.RESUME_ONLY:
        parts.append("Listed on resume (no session evidence)")
    elif skill.source == EvidenceSource.CONFLICTING:
        parts.append("Evidence conflicts between resume and sessions")

    if skill.session_frequency:
        parts.append(f"{skill.session_frequency} sessions")
    if skill.resume_years:
        parts.append(f"{skill.resume_years}y on resume")

    parts.append(f"depth: {skill.effective_depth.value}")

    return ". ".join(parts)


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
        start_time = time.time()

        # Dimension 1: Skill match
        skill_dim, skill_details = self._score_skill_match(requirements, seniority)

        # Dimension 2: Mission alignment
        mission_dim = self._score_mission_alignment(
            company, tech_stack or [], company_profile
        )

        # Dimension 3: Culture fit
        culture_dim = self._score_culture_fit(
            culture_signals or [], company_profile
        )

        # Overall score (equal weighting)
        overall_score = (
            skill_dim.score * skill_dim.weight
            + mission_dim.score * mission_dim.weight
            + culture_dim.score * culture_dim.weight
        )

        # Must-have coverage
        must_haves = [d for d in skill_details if d.priority == "must_have"]
        must_met = sum(1 for d in must_haves if d.match_status in ("strong_match", "exceeds"))
        must_coverage = f"{must_met}/{len(must_haves)} must-haves met" if must_haves else "No must-haves specified"

        # Strongest match and biggest gap
        strong_matches = [d for d in skill_details if d.match_status in ("strong_match", "exceeds")]
        gaps = [d for d in skill_details if d.match_status == "no_evidence" and d.priority in ("must_have", "strong_preference")]

        strongest = strong_matches[0].requirement if strong_matches else "None identified"
        biggest_gap = gaps[0].requirement if gaps else "None — all requirements addressed"

        # Discovery: skills in sessions but not resume
        resume_gaps = [
            s.name for s in self.profile.skills
            if s.discovery_flag and any(
                s.name in r.skill_mapping or any(s.name in sm for sm in r.skill_mapping)
                for r in requirements
            )
        ]

        # Unverified: resume skills relevant to role without session backing
        all_required = set()
        for r in requirements:
            all_required.update(s.lower() for s in r.skill_mapping)

        resume_unverified = [
            s.name for s in self.profile.skills
            if s.source == EvidenceSource.RESUME_ONLY and s.name in all_required
        ]

        # Overall summary
        summary = self._generate_summary(
            overall_score, skill_dim, mission_dim, culture_dim,
            company, title, must_coverage
        )

        # Action items
        action_items = self._generate_action_items(
            overall_score, gaps, resume_gaps, resume_unverified, company
        )

        elapsed = time.time() - start_time

        return FitAssessment(
            assessment_id=str(uuid.uuid4()),
            assessed_at=datetime.now(),
            job_title=title,
            company_name=company,
            posting_url=posting_url,
            source=source,
            overall_score=round(overall_score, 3),
            overall_grade=score_to_grade(overall_score),
            overall_summary=summary,
            skill_match=skill_dim,
            mission_alignment=mission_dim,
            culture_fit=culture_dim,
            skill_matches=skill_details,
            must_have_coverage=must_coverage,
            strongest_match=strongest if isinstance(strongest, str) else strongest,
            biggest_gap=biggest_gap if isinstance(biggest_gap, str) else biggest_gap,
            resume_gaps_discovered=resume_gaps,
            resume_unverified=resume_unverified,
            company_profile_summary=(
                company_profile.product_description if company_profile
                else f"No enrichment data available for {company}"
            ),
            company_enrichment_quality=(
                company_profile.enrichment_quality if company_profile else "none"
            ),
            should_apply=score_to_verdict(overall_score),
            action_items=action_items,
            profile_hash=self.profile.profile_hash,
            time_to_assess_seconds=round(elapsed, 2),
        )

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

            # Try to find a matching skill for any of the requirement's skill mappings
            best_match: MergedSkillEvidence | None = None
            best_status = "no_evidence"

            for skill_name in req.skill_mapping:
                found = _find_skill_match(skill_name, self.profile)
                if found:
                    status = _assess_depth_match(found, depth_floor)
                    # Keep the best match
                    status_rank = {"exceeds": 4, "strong_match": 3, "partial_match": 2, "adjacent": 1, "no_evidence": 0}
                    if status_rank.get(status, 0) > status_rank.get(best_status, 0):
                        best_match = found
                        best_status = status

            # Score this requirement
            status_score = {
                "exceeds": 1.0,
                "strong_match": 0.85,
                "partial_match": 0.55,
                "adjacent": 0.3,
                "no_evidence": 0.0,
            }
            req_score = status_score.get(best_status, 0.0)

            # Adjust by evidence confidence
            if best_match:
                req_score *= best_match.confidence

            weighted_score += req_score * weight

            details.append(SkillMatchDetail(
                requirement=req.description,
                priority=req.priority.value,
                match_status=best_status,
                candidate_evidence=_evidence_summary(best_match) if best_match else "No evidence found",
                evidence_source=best_match.source if best_match else EvidenceSource.RESUME_ONLY,
                confidence=best_match.confidence if best_match else 0.0,
            ))

        score = weighted_score / total_weight if total_weight > 0 else 0.0

        # Build dimension summary
        met = sum(1 for d in details if d.match_status in ("strong_match", "exceeds"))
        partial = sum(1 for d in details if d.match_status == "partial_match")
        missing = sum(1 for d in details if d.match_status == "no_evidence")

        summary = f"{met} requirements strongly matched, {partial} partial, {missing} gaps."
        detail_points = []
        for d in sorted(details, key=lambda x: PRIORITY_WEIGHT.get(RequirementPriority(x.priority), 0), reverse=True)[:5]:
            emoji = {"exceeds": "++", "strong_match": "+", "partial_match": "~", "adjacent": "?", "no_evidence": "-"}
            detail_points.append(f"[{emoji.get(d.match_status, '?')}] {d.requirement}: {d.match_status.replace('_', ' ')}")

        return DimensionScore(
            dimension="skill_match",
            score=round(score, 3),
            grade=score_to_grade(score),
            summary=summary,
            details=detail_points or ["No requirements to evaluate"],
        ), details

    def _score_mission_alignment(
        self,
        company: str,
        tech_stack: list[str],
        company_profile: CompanyProfile | None,
    ) -> DimensionScore:
        """Score company/mission alignment."""
        score = 0.5  # Neutral default when no enrichment data
        details: list[str] = []

        if company_profile:
            # Domain overlap
            candidate_domains = set()
            for proj in self.profile.projects:
                for tech in proj.technologies:
                    candidate_domains.add(tech.lower())
            for role in self.profile.roles:
                if role.domain:
                    candidate_domains.add(role.domain.lower())

            company_domains = {d.lower() for d in company_profile.product_domain}
            domain_overlap = candidate_domains & company_domains
            if domain_overlap:
                score += 0.15
                details.append(f"Domain overlap: {', '.join(sorted(domain_overlap))}")

            # Tech stack overlap
            company_techs = {t.lower() for t in company_profile.tech_stack_public}
            candidate_techs = {s.name for s in self.profile.skills}
            tech_overlap = company_techs & candidate_techs
            if tech_overlap:
                overlap_ratio = len(tech_overlap) / max(len(company_techs), 1)
                score += overlap_ratio * 0.2
                details.append(f"Tech overlap: {', '.join(sorted(tech_overlap)[:5])}")

            # OSS alignment
            has_oss = any(p.public_repo_url for p in self.profile.projects)
            if has_oss and company_profile.oss_activity_level in ("active", "very_active"):
                score += 0.1
                details.append("Strong open source alignment")

            # Blog topic relevance
            if company_profile.recent_blog_topics:
                details.append(f"Engineering blog active: {len(company_profile.recent_blog_topics)} recent posts")

            score = min(score, 1.0)
        else:
            # Without enrichment, check tech stack from posting
            if tech_stack:
                posting_techs = {t.lower() for t in tech_stack}
                candidate_techs = {s.name for s in self.profile.skills}
                tech_overlap = posting_techs & candidate_techs
                if tech_overlap:
                    ratio = len(tech_overlap) / max(len(posting_techs), 1)
                    score = 0.3 + ratio * 0.4
                    details.append(f"Tech stack overlap: {', '.join(sorted(tech_overlap)[:5])}")

            details.append("Limited enrichment data — score based on posting tech stack only")

        if not details:
            details = ["Insufficient data for mission alignment assessment"]

        return DimensionScore(
            dimension="mission_alignment",
            score=round(score, 3),
            grade=score_to_grade(score),
            summary=f"Mission alignment with {company}: {score_to_grade(score)}",
            details=details,
        )

    def _score_culture_fit(
        self,
        culture_signals: list[str],
        company_profile: CompanyProfile | None,
    ) -> DimensionScore:
        """Score culture/working style fit."""
        score = 0.5  # Neutral default
        details: list[str] = []

        all_signals = list(culture_signals)
        if company_profile:
            all_signals.extend(company_profile.culture_keywords)

        if not all_signals:
            return DimensionScore(
                dimension="culture_fit",
                score=0.5,
                grade=score_to_grade(0.5),
                summary="Insufficient culture signals for assessment",
                details=["No culture signals found in posting or company profile"],
            )

        signals_lower = {s.lower() for s in all_signals}

        # Map culture signals to candidate patterns
        pattern_types = {p.pattern_type for p in self.profile.patterns}
        pattern_strengths = {p.pattern_type: p.strength for p in self.profile.patterns}

        # Culture signal → pattern alignment mapping
        alignments = {
            "move fast": (PatternType.ITERATIVE_REFINEMENT, "Iterative approach aligns with fast-paced culture"),
            "quality first": (PatternType.TESTING_INSTINCT, "Testing instinct aligns with quality focus"),
            "documentation": (PatternType.DOCUMENTATION_DRIVEN, "Documentation-driven approach matches"),
            "collaborative": (PatternType.COMMUNICATION_CLARITY, "Clear communication style supports collaboration"),
            "autonomous": (PatternType.SCOPE_MANAGEMENT, "Self-directed scope management aligns"),
            "open source": (None, None),  # Handled separately
            "pair programming": (PatternType.COMMUNICATION_CLARITY, "Communication clarity supports pairing"),
            "remote": (PatternType.DOCUMENTATION_DRIVEN, "Documentation habits support remote work"),
            "agile": (PatternType.ITERATIVE_REFINEMENT, "Iterative refinement fits agile methodology"),
        }

        matches = 0
        total_signals = 0

        for signal_key, (pattern, description) in alignments.items():
            if any(signal_key in s for s in signals_lower):
                total_signals += 1
                if pattern and pattern in pattern_types:
                    strength = pattern_strengths.get(pattern, "emerging")
                    if strength in ("strong", "exceptional"):
                        matches += 1
                        details.append(f"Strong: {description}")
                    elif strength == "established":
                        matches += 0.7
                        details.append(f"Good: {description}")
                    else:
                        matches += 0.3

        # Open source check
        if any("open source" in s for s in signals_lower):
            total_signals += 1
            has_oss = any(p.public_repo_url for p in self.profile.projects)
            if has_oss:
                matches += 1
                details.append("Active open source contributor")
            else:
                details.append("No public OSS contributions found")

        if total_signals > 0:
            score = 0.3 + (matches / total_signals) * 0.6
        else:
            score = 0.5

        # Remote policy alignment (from company profile)
        if company_profile and company_profile.remote_policy != "unknown":
            details.append(f"Work policy: {company_profile.remote_policy.replace('_', ' ')}")

        score = min(max(score, 0.0), 1.0)

        if not details:
            details = ["Culture alignment assessment based on available signals"]

        return DimensionScore(
            dimension="culture_fit",
            score=round(score, 3),
            grade=score_to_grade(score),
            summary=f"Culture fit based on {total_signals} detected signals",
            details=details,
        )

    def _generate_summary(
        self,
        overall_score: float,
        skill_dim: DimensionScore,
        mission_dim: DimensionScore,
        culture_dim: DimensionScore,
        company: str,
        title: str,
        must_coverage: str,
    ) -> str:
        """Generate the overall summary paragraph."""
        grade = score_to_grade(overall_score)
        verdict = score_to_verdict(overall_score)

        verdict_text = {
            "strong_yes": "This is a strong fit worth pursuing.",
            "yes": "This is a solid fit that merits an application.",
            "maybe": "This is a mixed fit — worth applying if the role excites you, but expect gaps to come up.",
            "probably_not": "Significant gaps exist. Consider whether the role aligns with your growth goals before applying.",
            "no": "Fundamental misalignment between your profile and this role's requirements.",
        }

        strongest = max(
            [("Skills", skill_dim.score), ("Mission", mission_dim.score), ("Culture", culture_dim.score)],
            key=lambda x: x[1],
        )
        weakest = min(
            [("Skills", skill_dim.score), ("Mission", mission_dim.score), ("Culture", culture_dim.score)],
            key=lambda x: x[1],
        )

        return (
            f"Overall {grade} fit for {title} at {company}. "
            f"{must_coverage}. "
            f"Strongest dimension: {strongest[0]} ({score_to_grade(strongest[1])}). "
            f"Weakest dimension: {weakest[0]} ({score_to_grade(weakest[1])}). "
            f"{verdict_text.get(verdict, '')}"
        )

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

        if verdict in ("strong_yes", "yes"):
            items.append("Generate full application package for this role")

        if resume_gaps:
            items.append(
                f"Update resume to include: {', '.join(resume_gaps[:3])} "
                f"(demonstrated in sessions but missing from resume)"
            )

        if gaps:
            gap_names = [g.requirement for g in gaps[:2]]
            items.append(f"Key gaps to address: {', '.join(gap_names)}")

        if resume_unverified:
            items.append(
                f"Resume claims without session evidence: {', '.join(resume_unverified[:3])} "
                f"— prepare to discuss these in interviews"
            )

        if verdict in ("maybe", "probably_not"):
            items.append(f"Research {company}'s engineering blog and recent projects before deciding")

        if not items:
            items.append("Review the detailed skill breakdown for more context")

        return items[:6]
