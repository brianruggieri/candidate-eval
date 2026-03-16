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

        # Should have union of all skills
        cp_names = {s.name for s in candidate_profile.skills}
        rp_names = {s.name for s in resume_profile.skills}
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
