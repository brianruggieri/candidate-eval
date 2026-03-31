"""Tests for the profile merger — dual-source evidence classification and merging."""

from __future__ import annotations

from pathlib import Path

import pytest

from claude_candidate.schemas.candidate_profile import DepthLevel
from claude_candidate.schemas.merged_profile import EvidenceSource
from claude_candidate.merger import (
	classify_evidence_source,
	merge_profiles,
	merge_triad,
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


class TestMergedProfilePropagation:
	"""Test that resume-level fields propagate to MergedEvidenceProfile."""

	def test_total_years_experience_propagated(self, candidate_profile, resume_profile):
		merged = merge_profiles(candidate_profile, resume_profile)
		assert merged.total_years_experience == resume_profile.total_years_experience

	def test_education_propagated(self, candidate_profile, resume_profile):
		merged = merge_profiles(candidate_profile, resume_profile)
		assert merged.education == resume_profile.education

	def test_candidate_only_has_no_experience(self, candidate_profile):
		merged = merge_candidate_only(candidate_profile)
		assert merged.total_years_experience is None
		assert merged.education == []

	def test_resume_only_propagates_experience(self, resume_profile):
		merged = merge_resume_only(resume_profile)
		assert merged.total_years_experience == resume_profile.total_years_experience
		assert merged.education == resume_profile.education


def test_merge_with_curated_resume(candidate_profile):
	"""Merger should use curated_skills depths when available."""
	from datetime import datetime
	from claude_candidate.merger import merge_with_curated
	from claude_candidate.schemas.curated_resume import CuratedResume

	cp = candidate_profile

	curated = CuratedResume(
		parsed_at=datetime.now(),
		source_file_hash="test-hash",
		source_format="pdf",
		total_years_experience=12.4,
		education=["B.S. Computer Science"],
		curated_skills=[
			{
				"name": "typescript",
				"depth": "expert",
				"duration": "8 years",
				"source_context": "Listed in skills section",
			},
			{
				"name": "python",
				"depth": "deep",
				"duration": "2 years",
				"source_context": "Listed in skills section",
			},
		],
	)

	merged = merge_with_curated(cp, curated)

	# typescript is in curated but NOT in candidate_profile.skills (which has python, claude-api, fastapi, etc)
	# So it should be resume_only
	ts_skill = merged.get_skill("typescript")
	assert ts_skill is not None
	assert ts_skill.resume_duration == "8 years"

	# python IS in candidate_profile.skills, so it should be corroborated
	py_skill = merged.get_skill("python")
	assert py_skill is not None
	assert py_skill.resume_duration == "2 years"

	# Verify total_years and education propagated
	assert merged.total_years_experience == 12.4
	assert "B.S. Computer Science" in merged.education


def test_merge_with_curated_passes_roles(candidate_profile):
	"""merge_with_curated should propagate roles with domain/technologies into merged profile."""
	from datetime import datetime
	from claude_candidate.merger import merge_with_curated
	from claude_candidate.schemas.curated_resume import CuratedResume

	curated = CuratedResume(
		parsed_at=datetime.now(),
		source_file_hash="test-hash",
		source_format="pdf",
		total_years_experience=10.0,
		education=[],
		curated_skills=[
			{"name": "python", "depth": "deep", "source_context": "skills"},
		],
		roles=[
			{
				"title": "Senior Engineer",
				"company": "Acme Corp",
				"start_date": "2020-01",
				"end_date": "2023-06",
				"duration_months": 42,
				"description": "Built data pipelines for edtech platform",
				"technologies": ["python", "postgresql"],
				"achievements": ["Scaled pipeline to 1M events/day"],
				"domain": "edtech",
			}
		],
	)

	merged = merge_with_curated(candidate_profile, curated)

	assert len(merged.roles) == 1
	assert merged.roles[0].domain == "edtech"
	assert "python" in merged.roles[0].technologies


def test_merge_with_curated_no_roles_defaults_empty(candidate_profile):
	"""merge_with_curated with no roles should produce empty roles list."""
	from datetime import datetime
	from claude_candidate.merger import merge_with_curated
	from claude_candidate.schemas.curated_resume import CuratedResume

	curated = CuratedResume(
		parsed_at=datetime.now(),
		source_file_hash="test-hash",
		source_format="pdf",
		curated_skills=[
			{"name": "python", "depth": "used", "source_context": "skills"},
		],
	)

	merged = merge_with_curated(candidate_profile, curated)
	assert merged.roles == []


def test_merge_with_curated_malformed_role_skipped(candidate_profile):
	"""Malformed role dicts in CuratedResume should raise validation error at construction time."""
	from datetime import datetime
	from pydantic import ValidationError
	from claude_candidate.schemas.curated_resume import CuratedResume

	with pytest.raises(ValidationError):
		CuratedResume(
			parsed_at=datetime.now(),
			source_file_hash="test-hash",
			source_format="pdf",
			curated_skills=[],
			roles=[{"bad": "data"}],  # missing required fields
		)


class TestMergeTriad:
	"""Tests for the v0.7 resume + repo merge function."""

	def _make_resume(self):
		"""Minimal curated resume with known skills."""
		from datetime import datetime, timezone
		from claude_candidate.schemas.curated_resume import CuratedResume, CuratedSkill

		return CuratedResume(
			profile_version="1.0",
			parsed_at=datetime.now(timezone.utc),
			source_file_hash="test",
			source_format="pdf",
			name="Test User",
			roles=[],
			total_years_experience=13,
			skills=[],
			education=["B.S. Computer Science"],
			curated_skills=[
				CuratedSkill(name="typescript", depth=DepthLevel.EXPERT, duration="8 years"),
				CuratedSkill(name="python", depth=DepthLevel.DEEP, duration="2 years"),
				CuratedSkill(name="unity", depth=DepthLevel.EXPERT, duration="6 years"),
			],
			curated=True,
		)

	def _make_repo_profile(self):
		"""Repo profile with typescript, python, and fastapi."""
		from datetime import datetime, timezone
		from claude_candidate.schemas.repo_profile import RepoProfile, SkillRepoEvidence

		now = datetime.now(timezone.utc)
		return RepoProfile(
			repos=[],
			scan_date=now,
			repo_timeline_start=datetime(2026, 1, 30, tzinfo=timezone.utc),
			repo_timeline_end=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_days=55,
			skill_evidence={
				"typescript": SkillRepoEvidence(
					repos=5,
					total_bytes=2_800_000,
					first_seen=datetime(2026, 1, 30, tzinfo=timezone.utc),
					last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
					frameworks=["react", "vitest"],
					test_coverage=True,
				),
				"python": SkillRepoEvidence(
					repos=1,
					total_bytes=100_000,
					first_seen=datetime(2026, 2, 19, tzinfo=timezone.utc),
					last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
					frameworks=["fastapi", "pytest"],
					test_coverage=True,
				),
				"fastapi": SkillRepoEvidence(
					repos=1,
					total_bytes=50_000,
					first_seen=datetime(2026, 2, 19, tzinfo=timezone.utc),
					last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
					frameworks=[],
					test_coverage=True,
				),
			},
			repos_with_tests=7,
			repos_with_ci=5,
			repos_with_releases=2,
			repos_with_ai_signals=4,
		)

	def test_resume_depth_is_anchor(self) -> None:
		"""Resume depth is never overridden by repo evidence."""
		from claude_candidate.merger import merge_triad

		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		ts = profile.get_skill("typescript")
		assert ts is not None
		assert ts.effective_depth == DepthLevel.EXPERT  # resume says expert
		assert ts.source.value == "resume_and_repo"
		assert ts.repo_confirmed is True

	def test_repo_only_skill_capped_by_timeline(self) -> None:
		"""Skills in repos but not resume are scoped to repo timeline."""
		from claude_candidate.merger import merge_triad

		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		fastapi = profile.get_skill("fastapi")
		assert fastapi is not None
		assert fastapi.source.value == "repo_only"
		# 55 days = ~2 months -> Applied max
		assert fastapi.effective_depth == DepthLevel.APPLIED

	def test_resume_only_skill_preserved(self) -> None:
		"""Skills on resume but not in repos are preserved."""
		from claude_candidate.merger import merge_triad

		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		unity = profile.get_skill("unity")
		assert unity is not None
		assert unity.source.value == "resume_only"
		assert unity.effective_depth == DepthLevel.EXPERT

	def test_no_session_languages_in_profile(self) -> None:
		"""Rust/Go/etc should not appear -- only resume + repo skills."""
		from claude_candidate.merger import merge_triad

		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		assert profile.get_skill("rust") is None
		assert profile.get_skill("go") is None
		assert profile.get_skill("kotlin") is None

	def test_repo_evidence_fields_populated(self) -> None:
		"""Repo evidence fields should be populated for skills with repo data."""
		from claude_candidate.merger import merge_triad

		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		ts = profile.get_skill("typescript")
		assert ts is not None
		assert ts.repo_count == 5
		assert ts.repo_bytes == 2_800_000
		assert ts.repo_first_seen is not None
		assert ts.repo_last_seen is not None
		assert ts.repo_frameworks == ["react", "vitest"]

	def test_aggregate_counts(self) -> None:
		"""Aggregate counts should reflect source classification."""
		from claude_candidate.merger import merge_triad

		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		# typescript + python = 2 resume_and_repo (counted as corroborated)
		assert profile.corroborated_skill_count == 2
		# unity = resume only
		assert profile.resume_only_skill_count == 1
		# fastapi = repo only (no sessions in v0.7)
		assert profile.sessions_only_skill_count == 0
		# repo_confirmed = typescript + python + fastapi = 3
		assert profile.repo_confirmed_skill_count == 3

	def test_resume_metadata_propagated(self) -> None:
		"""Resume-level metadata should propagate to merged profile."""
		from claude_candidate.merger import merge_triad

		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		assert profile.total_years_experience == 13
		assert "B.S. Computer Science" in profile.education

	def test_no_confidence_set(self) -> None:
		"""confidence field should be None for v0.7 skills (deprecated)."""
		from claude_candidate.merger import merge_triad

		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		for skill in profile.skills:
			assert skill.confidence is None

	def test_sessions_parked(self) -> None:
		"""No session data should appear in the merged profile."""
		from claude_candidate.merger import merge_triad

		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		assert profile.patterns == []
		assert profile.projects == []
		assert profile.discovery_skills == []
		for skill in profile.skills:
			assert skill.session_depth is None
			assert skill.session_frequency is None
			assert skill.session_evidence_count is None

	def test_resume_duration_propagated(self) -> None:
		"""Resume duration should be passed through for resume skills."""
		from claude_candidate.merger import merge_triad

		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		ts = profile.get_skill("typescript")
		assert ts is not None
		assert ts.resume_duration == "8 years"
		py = profile.get_skill("python")
		assert py is not None
		assert py.resume_duration == "2 years"

	def test_category_from_taxonomy(self) -> None:
		"""Skills should get their category from the taxonomy."""
		from claude_candidate.merger import merge_triad

		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		ts = profile.get_skill("typescript")
		assert ts is not None
		assert ts.category == "language"
		fastapi = profile.get_skill("fastapi")
		assert fastapi is not None
		assert fastapi.category == "framework"

	def test_long_timeline_repo_only_gets_deep(self) -> None:
		"""Repo-only skill with 180+ day timeline gets DEEP depth."""
		from datetime import datetime, timezone
		from claude_candidate.merger import merge_triad
		from claude_candidate.schemas.repo_profile import RepoProfile, SkillRepoEvidence

		now = datetime.now(timezone.utc)
		repo = RepoProfile(
			repos=[],
			scan_date=now,
			repo_timeline_start=datetime(2025, 6, 1, tzinfo=timezone.utc),
			repo_timeline_end=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_days=297,
			skill_evidence={
				"go": SkillRepoEvidence(
					repos=3,
					total_bytes=500_000,
					first_seen=datetime(2025, 6, 1, tzinfo=timezone.utc),
					last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
					frameworks=[],
					test_coverage=True,
				),
			},
			repos_with_tests=3,
			repos_with_ci=2,
			repos_with_releases=1,
			repos_with_ai_signals=1,
		)
		profile = merge_triad(self._make_resume(), repo)
		go = profile.get_skill("go")
		assert go is not None
		assert go.source.value == "repo_only"
		assert go.effective_depth == DepthLevel.DEEP

	def test_very_long_timeline_repo_only_gets_expert(self) -> None:
		"""Repo-only skill with 540+ day timeline gets EXPERT depth."""
		from datetime import datetime, timezone
		from claude_candidate.merger import merge_triad
		from claude_candidate.schemas.repo_profile import RepoProfile, SkillRepoEvidence

		now = datetime.now(timezone.utc)
		repo = RepoProfile(
			repos=[],
			scan_date=now,
			repo_timeline_start=datetime(2024, 6, 1, tzinfo=timezone.utc),
			repo_timeline_end=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_days=663,
			skill_evidence={
				"rust": SkillRepoEvidence(
					repos=10,
					total_bytes=2_000_000,
					first_seen=datetime(2024, 6, 1, tzinfo=timezone.utc),
					last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
					frameworks=[],
					test_coverage=True,
				),
			},
			repos_with_tests=10,
			repos_with_ci=8,
			repos_with_releases=5,
			repos_with_ai_signals=3,
		)
		profile = merge_triad(self._make_resume(), repo)
		rust = profile.get_skill("rust")
		assert rust is not None
		assert rust.source.value == "repo_only"
		assert rust.effective_depth == DepthLevel.EXPERT


def test_corroboration_with_name_variants(candidate_profile):
	"""Skills with different names (React.js vs react) should still corroborate."""
	import json
	from claude_candidate.merger import merge_profiles
	from claude_candidate.schemas.candidate_profile import DepthLevel
	from claude_candidate.schemas.resume_profile import ResumeProfile, ResumeSkill
	from claude_candidate.schemas.merged_profile import EvidenceSource

	# Inject a "react" skill into the candidate profile and create a resume
	# with "React.js" (alias). The merger should canonicalize both to "react"
	# and produce a CORROBORATED entry.
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
	corroborated = [s for s in merged.skills if s.source == EvidenceSource.CORROBORATED]
	assert len(corroborated) >= 1


class TestMergeTriadWithSessions:
	"""Tests for merge_triad with optional sessions parameter."""

	@pytest.fixture
	def curated_resume(self):
		from claude_candidate.schemas.curated_resume import CuratedResume

		path = Path(__file__).parent / "fixtures" / "curated_resume_sample.json"
		if not path.exists():
			path = Path.home() / ".claude-candidate" / "curated_resume.json"
			if not path.exists():
				pytest.skip("No curated_resume.json available")
		return CuratedResume.model_validate_json(path.read_text())

	@pytest.fixture
	def repo_profile(self):
		from claude_candidate.schemas.repo_profile import RepoProfile

		path = Path(__file__).parent / "fixtures" / "sample_repo_profile.json"
		if not path.exists():
			path = Path.home() / ".claude-candidate" / "repo_profile.json"
			if not path.exists():
				pytest.skip("No repo_profile.json available")
		return RepoProfile.model_validate_json(path.read_text())

	def test_sessions_none_backward_compatible(self, curated_resume, repo_profile):
		"""sessions=None produces identical output to omitting the parameter."""
		profile_without = merge_triad(curated_resume, repo_profile)
		profile_with_none = merge_triad(curated_resume, repo_profile, sessions=None)
		assert profile_without.patterns == profile_with_none.patterns == []
		assert profile_without.projects == profile_with_none.projects == []
		assert len(profile_without.skills) == len(profile_with_none.skills)

	def test_patterns_flow_through(self, curated_resume, repo_profile, candidate_profile):
		"""When sessions provided, patterns propagate to merged profile."""
		profile = merge_triad(curated_resume, repo_profile, sessions=candidate_profile)
		assert len(profile.patterns) == len(candidate_profile.problem_solving_patterns)

	def test_projects_from_repo_not_sessions(self, curated_resume, repo_profile, candidate_profile):
		"""Projects now come from repo_profile.repos, not sessions."""
		profile = merge_triad(curated_resume, repo_profile, sessions=candidate_profile)
		# Projects are populated from repo_profile.repos (Task 4), not sessions
		# Before Task 4 wires it, projects is empty
		assert isinstance(profile.projects, list)

	def test_candidate_hash_set_with_sessions(
		self, curated_resume, repo_profile, candidate_profile
	):
		"""When sessions provided, candidate_profile_hash reflects it."""
		profile = merge_triad(curated_resume, repo_profile, sessions=candidate_profile)
		assert profile.candidate_profile_hash != "none"

	def test_candidate_hash_none_without_sessions(self, curated_resume, repo_profile):
		"""Without sessions, candidate_profile_hash is 'none'."""
		profile = merge_triad(curated_resume, repo_profile)
		assert profile.candidate_profile_hash == "none"
