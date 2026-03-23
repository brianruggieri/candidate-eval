"""
Profile merger: Combines ResumeProfile and CandidateProfile
into a unified MergedEvidenceProfile with provenance tracking.
"""

from __future__ import annotations

from datetime import datetime

from claude_candidate.manifest import hash_json_stable
from claude_candidate.schemas.candidate_profile import CandidateProfile, DepthLevel, DEPTH_RANK
from claude_candidate.schemas.merged_profile import (
    EvidenceSource,
    MergedEvidenceProfile,
    MergedSkillEvidence,
)
from claude_candidate.schemas.curated_resume import CuratedResume
from claude_candidate.schemas.resume_profile import ResumeProfile
from claude_candidate.skill_taxonomy import SkillTaxonomy


_taxonomy: SkillTaxonomy | None = None


def _get_taxonomy() -> SkillTaxonomy:
    global _taxonomy
    if _taxonomy is None:
        _taxonomy = SkillTaxonomy.load_default()
    return _taxonomy


def classify_evidence_source(
    in_resume: bool,
    in_sessions: bool,
    resume_depth: DepthLevel | None,
    session_depth: DepthLevel | None,
) -> EvidenceSource:
    """Classify the evidence source for a skill."""
    if in_resume and in_sessions:
        # Check for conflict: if depths differ by 2+ levels, it's conflicting.
        # Skip conflict check if either side is MENTIONED — that means "no depth
        # data available", not "low skill". Common in resumes that list skills
        # without depth information.
        if resume_depth and session_depth:
            r_rank = DEPTH_RANK.get(resume_depth, 0)
            s_rank = DEPTH_RANK.get(session_depth, 0)
            both_have_depth = r_rank > 0 and s_rank > 0
            if both_have_depth and abs(r_rank - s_rank) >= 2:
                return EvidenceSource.CONFLICTING
        return EvidenceSource.CORROBORATED
    elif in_resume:
        return EvidenceSource.RESUME_ONLY
    elif in_sessions:
        return EvidenceSource.SESSIONS_ONLY
    # Shouldn't reach here, but defensive
    return EvidenceSource.RESUME_ONLY


def merge_profiles(
    candidate_profile: CandidateProfile,
    resume_profile: ResumeProfile,
) -> MergedEvidenceProfile:
    """
    Merge CandidateProfile and ResumeProfile into a unified evidence view.

    Algorithm:
    1. Collect all unique skill names from both sources
    2. For each: classify source, compute effective depth and confidence
    3. Carry over patterns/projects from sessions, roles from resume
    4. Identify discovery skills (sessions_only with depth >= applied)
    """
    taxonomy = _get_taxonomy()

    # Normalize skill names via taxonomy BEFORE building lookup dicts
    from claude_candidate.schemas.resume_profile import ResumeSkill
    from claude_candidate.schemas.candidate_profile import SkillEntry
    resume_skills: dict[str, ResumeSkill] = {}
    for s in resume_profile.skills:
        canonical = taxonomy.canonicalize(s.name)
        resume_skills[canonical] = s

    session_skills: dict[str, SkillEntry] = {}
    for s in candidate_profile.skills:
        canonical = taxonomy.canonicalize(s.name)
        session_skills[canonical] = s

    all_skill_names = set(resume_skills.keys()) | set(session_skills.keys())

    merged_skills: list[MergedSkillEvidence] = []
    corroborated_count = 0
    resume_only_count = 0
    sessions_only_count = 0
    discovery_skills: list[str] = []

    for name in sorted(all_skill_names):
        r_skill = resume_skills.get(name)
        s_skill = session_skills.get(name)

        in_resume = r_skill is not None
        in_sessions = s_skill is not None

        r_depth = r_skill.implied_depth if r_skill else None
        s_depth = s_skill.depth if s_skill else None

        source = classify_evidence_source(in_resume, in_sessions, r_depth, s_depth)

        effective_depth = MergedSkillEvidence.compute_effective_depth(
            source, r_depth, s_depth
        )
        confidence = MergedSkillEvidence.compute_confidence(
            source,
            s_skill.frequency if s_skill else None,
            r_skill.source_context if r_skill else None,
        )

        is_discovery = (
            source == EvidenceSource.SESSIONS_ONLY
            and DEPTH_RANK.get(s_depth, 0) >= DEPTH_RANK[DepthLevel.APPLIED]
        )

        if source == EvidenceSource.CORROBORATED:
            corroborated_count += 1
        elif source == EvidenceSource.RESUME_ONLY:
            resume_only_count += 1
        elif source == EvidenceSource.SESSIONS_ONLY:
            sessions_only_count += 1

        if is_discovery:
            discovery_skills.append(name)

        merged_skills.append(MergedSkillEvidence(
            name=name,
            source=source,
            resume_depth=r_depth,
            resume_context=r_skill.source_context if r_skill else None,
            resume_years=r_skill.years_experience if r_skill else None,
            session_depth=s_depth,
            session_frequency=s_skill.frequency if s_skill else None,
            session_evidence_count=(s_skill.total_evidence_count or len(s_skill.evidence)) if s_skill else None,
            session_recency=s_skill.recency if s_skill else None,
            effective_depth=effective_depth,
            confidence=confidence,
            discovery_flag=is_discovery,
        ))

    # Sort: corroborated first, then by effective depth descending
    source_order = {
        EvidenceSource.CORROBORATED: 0,
        EvidenceSource.SESSIONS_ONLY: 1,
        EvidenceSource.RESUME_ONLY: 2,
        EvidenceSource.CONFLICTING: 3,
    }
    merged_skills.sort(key=lambda s: (
        source_order.get(s.source, 9),
        -DEPTH_RANK.get(s.effective_depth, 0),
    ))

    # Compute hashes for provenance
    resume_hash = resume_profile.source_file_hash
    candidate_hash = candidate_profile.manifest_hash
    merged_dict = {"resume": resume_hash, "candidate": candidate_hash}
    profile_hash = hash_json_stable(merged_dict)

    merged = MergedEvidenceProfile(
        skills=merged_skills,
        patterns=candidate_profile.problem_solving_patterns,
        projects=candidate_profile.projects,
        roles=resume_profile.roles,
        corroborated_skill_count=corroborated_count,
        resume_only_skill_count=resume_only_count,
        sessions_only_skill_count=sessions_only_count,
        discovery_skills=discovery_skills,
        profile_hash=profile_hash,
        resume_hash=resume_hash,
        candidate_profile_hash=candidate_hash,
        merged_at=datetime.now(),
    )
    merged.total_years_experience = resume_profile.total_years_experience
    merged.education = resume_profile.education
    return merged


def merge_with_curated(
    candidate_profile: CandidateProfile,
    curated_resume: CuratedResume,
) -> MergedEvidenceProfile:
    """Merge CandidateProfile with a validated CuratedResume.

    Uses curated_skills with type-safe depths instead of raw dicts.
    This replaces merge_profiles() when curated data is available.
    """
    taxonomy = _get_taxonomy()

    # Build session skill lookup
    from claude_candidate.schemas.candidate_profile import SkillEntry
    session_skills: dict[str, SkillEntry] = {}
    for s in candidate_profile.skills:
        canonical = taxonomy.canonicalize(s.name)
        session_skills[canonical] = s

    # Build curated resume lookup — depth is already a DepthLevel enum
    from claude_candidate.schemas.curated_resume import CuratedSkill
    curated_lookup: dict[str, CuratedSkill] = {}
    for cs in curated_resume.curated_skills:
        canonical = taxonomy.canonicalize(cs.name)
        existing = curated_lookup.get(canonical)
        if existing is None:
            curated_lookup[canonical] = cs
        else:
            if DEPTH_RANK.get(cs.depth, 0) > DEPTH_RANK.get(existing.depth, 0):
                curated_lookup[canonical] = cs

    all_names = set(session_skills.keys()) | set(curated_lookup.keys())
    merged_skills = []
    counts = {"corroborated": 0, "resume_only": 0, "sessions_only": 0}
    discovery_skills = []

    for name in sorted(all_names):
        s_skill = session_skills.get(name)
        c_skill = curated_lookup.get(name)

        in_sessions = s_skill is not None
        in_resume = c_skill is not None

        r_depth = c_skill.depth if c_skill else None
        s_depth = s_skill.depth if s_skill else None

        source = classify_evidence_source(in_resume, in_sessions, r_depth, s_depth)
        effective_depth = MergedSkillEvidence.compute_effective_depth(source, r_depth, s_depth)
        confidence = MergedSkillEvidence.compute_confidence(
            source,
            s_skill.frequency if s_skill else None,
            c_skill.source_context if c_skill else None,
        )

        is_discovery = (
            source == EvidenceSource.SESSIONS_ONLY
            and DEPTH_RANK.get(s_depth, 0) >= DEPTH_RANK[DepthLevel.APPLIED]
        )

        if source == EvidenceSource.CORROBORATED:
            counts["corroborated"] += 1
        elif source == EvidenceSource.RESUME_ONLY:
            counts["resume_only"] += 1
        elif source == EvidenceSource.SESSIONS_ONLY:
            counts["sessions_only"] += 1

        if is_discovery:
            discovery_skills.append(name)

        merged_skills.append(MergedSkillEvidence(
            name=name,
            source=source,
            resume_depth=r_depth,
            resume_context=c_skill.source_context if c_skill else None,
            resume_years=None,  # curated uses duration string instead
            resume_duration=c_skill.duration if c_skill else None,
            session_depth=s_depth,
            session_frequency=s_skill.frequency if s_skill else None,
            session_evidence_count=(s_skill.total_evidence_count or len(s_skill.evidence)) if s_skill else None,
            session_recency=s_skill.recency if s_skill else None,
            effective_depth=effective_depth,
            confidence=confidence,
            discovery_flag=is_discovery,
        ))

    # Sort by source priority then depth
    source_order = {
        EvidenceSource.CORROBORATED: 0,
        EvidenceSource.SESSIONS_ONLY: 1,
        EvidenceSource.RESUME_ONLY: 2,
        EvidenceSource.CONFLICTING: 3,
    }
    merged_skills.sort(key=lambda s: (
        source_order.get(s.source, 9),
        -DEPTH_RANK.get(s.effective_depth, 0),
    ))

    profile_hash = hash_json_stable({
        "candidate": candidate_profile.manifest_hash,
        "curated": curated_resume.model_dump_json(),
    })

    merged = MergedEvidenceProfile(
        skills=merged_skills,
        patterns=candidate_profile.problem_solving_patterns,
        projects=candidate_profile.projects,
        roles=curated_resume.roles,
        corroborated_skill_count=counts["corroborated"],
        resume_only_skill_count=counts["resume_only"],
        sessions_only_skill_count=counts["sessions_only"],
        discovery_skills=discovery_skills,
        profile_hash=profile_hash,
        resume_hash=curated_resume.source_file_hash,
        candidate_profile_hash=candidate_profile.manifest_hash,
        merged_at=datetime.now(),
    )
    merged.total_years_experience = curated_resume.total_years_experience
    merged.education = curated_resume.education
    return merged


def merge_candidate_only(candidate_profile: CandidateProfile) -> MergedEvidenceProfile:
    """
    Create a MergedEvidenceProfile from sessions only (no resume).

    Used when the user hasn't uploaded a resume yet. All skills are sessions_only.
    Deduplicates after canonicalization — keeps the entry with the highest depth.
    """
    taxonomy = _get_taxonomy()
    seen: dict[str, MergedSkillEvidence] = {}
    for s_skill in candidate_profile.skills:
        canonical_name = taxonomy.canonicalize(s_skill.name)
        entry = MergedSkillEvidence(
            name=canonical_name,
            source=EvidenceSource.SESSIONS_ONLY,
            session_depth=s_skill.depth,
            session_frequency=s_skill.frequency,
            session_evidence_count=s_skill.total_evidence_count or len(s_skill.evidence),
            session_recency=s_skill.recency,
            effective_depth=s_skill.depth,
            confidence=MergedSkillEvidence.compute_confidence(
                EvidenceSource.SESSIONS_ONLY, s_skill.frequency, None
            ),
            discovery_flag=True,
        )
        existing = seen.get(canonical_name)
        if existing is None or DEPTH_RANK.get(entry.effective_depth, 0) > DEPTH_RANK.get(existing.effective_depth, 0):
            seen[canonical_name] = entry
    merged_skills = list(seen.values())

    return MergedEvidenceProfile(
        skills=merged_skills,
        patterns=candidate_profile.problem_solving_patterns,
        projects=candidate_profile.projects,
        roles=[],
        corroborated_skill_count=0,
        resume_only_skill_count=0,
        sessions_only_skill_count=len(merged_skills),
        discovery_skills=[s.name for s in merged_skills],
        profile_hash=candidate_profile.manifest_hash,
        resume_hash="none",
        candidate_profile_hash=candidate_profile.manifest_hash,
        merged_at=datetime.now(),
    )


def merge_resume_only(resume_profile: ResumeProfile) -> MergedEvidenceProfile:
    """
    Create a MergedEvidenceProfile from resume only (no sessions).

    Used when the user hasn't built a CandidateProfile yet.
    All skills are resume_only. Deduplicates after canonicalization.
    """
    taxonomy = _get_taxonomy()
    seen: dict[str, MergedSkillEvidence] = {}
    for r_skill in resume_profile.skills:
        canonical_name = taxonomy.canonicalize(r_skill.name)
        entry = MergedSkillEvidence(
            name=canonical_name,
            source=EvidenceSource.RESUME_ONLY,
            resume_depth=r_skill.implied_depth,
            resume_context=r_skill.source_context,
            resume_years=r_skill.years_experience,
            effective_depth=r_skill.implied_depth,
            confidence=MergedSkillEvidence.compute_confidence(
                EvidenceSource.RESUME_ONLY, None, r_skill.source_context
            ),
        )
        existing = seen.get(canonical_name)
        if existing is None or DEPTH_RANK.get(entry.effective_depth, 0) > DEPTH_RANK.get(existing.effective_depth, 0):
            seen[canonical_name] = entry
    merged_skills = list(seen.values())

    merged = MergedEvidenceProfile(
        skills=merged_skills,
        patterns=[],
        projects=[],
        roles=resume_profile.roles,
        corroborated_skill_count=0,
        resume_only_skill_count=len(merged_skills),
        sessions_only_skill_count=0,
        discovery_skills=[],
        profile_hash=resume_profile.source_file_hash,
        resume_hash=resume_profile.source_file_hash,
        candidate_profile_hash="none",
        merged_at=datetime.now(),
    )
    merged.total_years_experience = resume_profile.total_years_experience
    merged.education = resume_profile.education
    return merged
