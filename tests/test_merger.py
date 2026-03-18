"""Tests for the profile merger — dual-source evidence classification and merging."""

from __future__ import annotations


from claude_candidate.schemas.candidate_profile import DepthLevel
from claude_candidate.schemas.merged_profile import EvidenceSource
from claude_candidate.merger import (
    classify_evidence_source,
    merge_profiles,
    merge_candidate_only,
    merge_resume_only,
)


class TestClassifyEvidenceSource:
    def test_corroborated_same_depth(self):
        source = classify_evidence_source(True, True, DepthLevel.DEEP, DepthLevel.DEEP)
        assert source == EvidenceSource.CORROBORATED

    def test_corroborated_close_depth(self):
        source = classify_evidence_source(True, True, DepthLevel.APPLIED, DepthLevel.DEEP)
        assert source == EvidenceSource.CORROBORATED  # Only 1 level apart

    def test_conflicting_wide_depth_gap(self):
        source = classify_evidence_source(True, True, DepthLevel.EXPERT, DepthLevel.USED)
        assert source == EvidenceSource.CONFLICTING  # 2+ levels apart

    def test_resume_only(self):
        source = classify_evidence_source(True, False, DepthLevel.APPLIED, None)
        assert source == EvidenceSource.RESUME_ONLY

    def test_sessions_only(self):
        source = classify_evidence_source(False, True, None, DepthLevel.DEEP)
        assert source == EvidenceSource.SESSIONS_ONLY


class TestMergeProfiles:
    def test_merge_produces_all_skills(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)

        # Normalize names the same way the merger does before comparing
        from claude_candidate.skill_taxonomy import SkillTaxonomy
        taxonomy = SkillTaxonomy.load_default()

        cp_names = {taxonomy.canonicalize(s.name) for s in candidate_profile.skills}
        rp_names = {taxonomy.canonicalize(s.name) for s in resume_profile.skills}
        merged_names = {s.name for s in merged.skills}

        assert cp_names.issubset(merged_names)
        assert rp_names.issubset(merged_names)

    def test_corroborated_skills_detected(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)

        # Python is in both profiles
        python = merged.get_skill("python")
        assert python is not None
        assert python.source == EvidenceSource.CORROBORATED

    def test_sessions_only_skills_detected(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)

        # claude-api is in sessions but not resume
        claude_api = merged.get_skill("claude-api")
        assert claude_api is not None
        assert claude_api.source == EvidenceSource.SESSIONS_ONLY

    def test_resume_only_skills_detected(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)

        # java is in resume but not sessions
        java = merged.get_skill("java")
        assert java is not None
        assert java.source == EvidenceSource.RESUME_ONLY

    def test_discovery_skills_flagged(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)

        # Sessions-only skills with depth >= applied should be discoveries
        for skill in merged.skills:
            if skill.source == EvidenceSource.SESSIONS_ONLY and skill.discovery_flag:
                from claude_candidate.schemas.candidate_profile import DEPTH_RANK
                assert DEPTH_RANK[skill.effective_depth] >= DEPTH_RANK[DepthLevel.APPLIED]

    def test_discovery_skills_list(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        assert len(merged.discovery_skills) > 0
        # claude-api should be a discovery (sessions-only with expert depth)
        assert "claude-api" in merged.discovery_skills

    def test_counts_are_consistent(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)

        total = (
            merged.corroborated_skill_count
            + merged.resume_only_skill_count
            + merged.sessions_only_skill_count
        )
        # May have conflicting skills too, but these three should cover most
        assert total <= len(merged.skills)

    def test_patterns_carried_from_sessions(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        assert len(merged.patterns) == len(candidate_profile.problem_solving_patterns)

    def test_roles_carried_from_resume(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        assert len(merged.roles) == len(resume_profile.roles)

    def test_provenance_hashes_set(self, candidate_profile, resume_profile):
        merged = merge_profiles(candidate_profile, resume_profile)
        assert merged.profile_hash
        assert merged.resume_hash == resume_profile.source_file_hash
        assert merged.candidate_profile_hash == candidate_profile.manifest_hash


class TestMergeCandidateOnly:
    def test_all_skills_sessions_only(self, candidate_profile):
        merged = merge_candidate_only(candidate_profile)

        for skill in merged.skills:
            assert skill.source == EvidenceSource.SESSIONS_ONLY

    def test_no_roles(self, candidate_profile):
        merged = merge_candidate_only(candidate_profile)
        assert merged.roles == []

    def test_resume_hash_is_none(self, candidate_profile):
        merged = merge_candidate_only(candidate_profile)
        assert merged.resume_hash == "none"


class TestMergeResumeOnly:
    def test_all_skills_resume_only(self, resume_profile):
        merged = merge_resume_only(resume_profile)

        for skill in merged.skills:
            assert skill.source == EvidenceSource.RESUME_ONLY

    def test_no_patterns(self, resume_profile):
        merged = merge_resume_only(resume_profile)
        assert merged.patterns == []

    def test_no_projects(self, resume_profile):
        merged = merge_resume_only(resume_profile)
        assert merged.projects == []


def test_corroboration_with_name_variants(candidate_profile):
    """Skills with different names (React.js vs react) should still corroborate."""
    import json
    from pathlib import Path
    from claude_candidate.merger import merge_profiles
    from claude_candidate.schemas.candidate_profile import DepthLevel
    from claude_candidate.schemas.resume_profile import ResumeProfile, ResumeSkill
    from claude_candidate.schemas.merged_profile import EvidenceSource

    # Build a minimal resume that uses the alias form "React.js"
    # while the candidate_profile fixture has "react" (from sessions).
    # First inject "react" into the candidate profile if it's not there already.
    # The fixture may or may not have react — we build a fresh resume that
    # uses the alias so the test is deterministic.

    # Get the first skill from candidate_profile to borrow its session dates
    first_skill = candidate_profile.skills[0]

    # Build a ResumeProfile that references the alias form of that skill
    # so we can test alias → canonical resolution in the merger.
    # Use "Python" (alias: "py") vs "python" in sessions for a deterministic test.
    python_in_sessions = any(
        s.name == "python" for s in candidate_profile.skills
    )
    if not python_in_sessions:
        # Fall back to building a minimal profile using the React alias test
        # by injecting a "react" skill into a copy of the candidate profile
        from datetime import datetime, timezone
        from claude_candidate.schemas.candidate_profile import SkillEntry, SessionReference
        import copy

        now = datetime.now(tz=timezone.utc)
        # We'll use the candidate_profile as-is and just check that the
        # alias resolution works for Python (which is in both fixtures)
        pass

    # The sample_candidate_profile.json fixture has "python" in session skills.
    # We create a resume that lists "Python" (capital P) or "py" (alias)
    # to exercise the alias normalization path.
    from datetime import datetime, timezone
    now = datetime.now(tz=timezone.utc)
    resume = ResumeProfile(
        parsed_at=now,
        source_file_hash="variant-test-hash",
        source_format="txt",
        skills=[
            ResumeSkill(
                name="React.js",  # alias for "react" in taxonomy
                source_context="Built React.js applications",
                implied_depth=DepthLevel.APPLIED,
                recency="current_role",
            )
        ],
        roles=[],
    )

    # Patch the candidate_profile to ensure it has a "react" skill
    # by using from_json on a modified version
    profile_data = json.loads(candidate_profile.to_json())
    first_skill_data = profile_data["skills"][0]
    react_skill = {
        "name": "react",
        "category": "framework",
        "depth": "deep",
        "frequency": 10,
        "recency": first_skill_data["recency"],
        "first_seen": first_skill_data["first_seen"],
        "evidence": [first_skill_data["evidence"][0]],
        "context_notes": None,
    }
    profile_data["skills"].append(react_skill)

    from claude_candidate.schemas.candidate_profile import CandidateProfile
    candidate_with_react = CandidateProfile.model_validate(profile_data)

    merged = merge_profiles(candidate_with_react, resume)
    corroborated = [
        s for s in merged.skills
        if s.source == EvidenceSource.CORROBORATED
    ]
    assert len(corroborated) >= 1
