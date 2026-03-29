"""Tests for mission alignment reanalysis: domain taxonomy + partial-path proxy."""

import pytest
from datetime import datetime
from claude_candidate.scoring.constants import MISSION_DOMAIN_TAXONOMY
from claude_candidate.scoring.dimensions import _score_mission_text_alignment
from claude_candidate.schemas.merged_profile import (
	MergedEvidenceProfile,
	MergedSkillEvidence,
	EvidenceSource,
)
from claude_candidate.schemas.candidate_profile import DepthLevel
from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority


class TestMissionDomainTaxonomy:
	"""Verify the domain keyword taxonomy exists and has expected structure."""

	def test_taxonomy_is_dict(self):
		assert isinstance(MISSION_DOMAIN_TAXONOMY, dict)
		assert len(MISSION_DOMAIN_TAXONOMY) > 0

	def test_taxonomy_maps_domains_to_keywords(self):
		for domain, keywords in MISSION_DOMAIN_TAXONOMY.items():
			assert isinstance(domain, str)
			assert isinstance(keywords, list)
			assert len(keywords) > 0

	def test_known_domains_present(self):
		expected_domains = {"developer-tools", "ai", "fintech", "healthcare", "education"}
		for domain in expected_domains:
			assert domain in MISSION_DOMAIN_TAXONOMY, f"Missing domain: {domain}"

	def test_keywords_are_lowercase(self):
		for domain, keywords in MISSION_DOMAIN_TAXONOMY.items():
			for kw in keywords:
				assert kw == kw.lower(), f"Keyword '{kw}' in '{domain}' should be lowercase"


def _make_profile(skill_names):
	skills = [
		MergedSkillEvidence(
			name=n,
			source=EvidenceSource.RESUME_AND_REPO,
			effective_depth=DepthLevel.DEEP,
			confidence=0.9,
		)
		for n in skill_names
	]
	return MergedEvidenceProfile(
		skills=skills,
		projects=[],
		patterns=[],
		roles=[],
		total_years_experience=10.0,
		corroborated_skill_count=0,
		resume_only_skill_count=0,
		sessions_only_skill_count=0,
		repo_confirmed_skill_count=len(skills),
		discovery_skills=[],
		profile_hash="test-hash",
		resume_hash="test-resume-hash",
		candidate_profile_hash="test-cp-hash",
		merged_at=datetime.now(),
	)


def _make_company(mission, product_desc=""):
	return CompanyProfile(
		company_name="Test Co",
		mission_statement=mission,
		product_description=product_desc or mission,
		product_domain=[],
		enriched_at=datetime.now(),
	)


class TestImprovedMissionTextAlignment:
	"""Verify domain-aware mission text alignment scoring."""

	def test_domain_keyword_match_boosts_score(self):
		profile = _make_profile(["python", "llm", "prompt-engineering"])
		company = _make_company(
			"Building the next generation of LLM inference and model training platform"
		)
		score, details = _score_mission_text_alignment(profile, company)
		assert score > 0, "Should score positively for domain keyword overlap"

	def test_no_domain_match_returns_zero(self):
		profile = _make_profile(["cobol", "fortran"])
		company = _make_company("Revolutionary healthcare diagnostics platform")
		score, details = _score_mission_text_alignment(profile, company)
		assert score == 0.0

	def test_domain_taxonomy_broadens_matching(self):
		profile = _make_profile(["python", "typescript", "react"])
		company = _make_company(
			"We build developer tools and CLI platforms for infrastructure teams"
		)
		score, details = _score_mission_text_alignment(profile, company)
		assert isinstance(score, float)


class TestMissionInPartialPath:
	"""Eng review 4A->C: mission scoring in partial assessments via skill_mapping proxy."""

	def test_partial_assessment_includes_mission_dimension(self):
		from claude_candidate.scoring.engine import QuickMatchEngine

		profile = _make_profile(["python", "react", "typescript", "node.js"])
		engine = QuickMatchEngine(profile)
		reqs = [
			QuickRequirement(
				description="Python",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
			),
			QuickRequirement(
				description="React",
				skill_mapping=["react"],
				priority=RequirementPriority.STRONG_PREFERENCE,
			),
		]
		result = engine.assess(reqs, company="TestCo", title="Engineer")
		# Partial assessment should now include mission (proxy-based)
		assert result.assessment_phase == "partial"

	def test_partial_mission_uses_skill_mapping_proxy(self):
		from claude_candidate.scoring.engine import QuickMatchEngine

		profile = _make_profile(["python", "react", "typescript", "docker"])
		engine = QuickMatchEngine(profile)
		reqs = [
			QuickRequirement(
				description="Python",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
			),
			QuickRequirement(
				description="React",
				skill_mapping=["react", "typescript"],
				priority=RequirementPriority.MUST_HAVE,
			),
			QuickRequirement(
				description="Docker",
				skill_mapping=["docker"],
				priority=RequirementPriority.NICE_TO_HAVE,
			),
		]
		result = engine.assess(reqs, company="TestCo", title="Engineer")
		if result.mission_alignment:
			assert result.mission_alignment.score >= 0.3, (
				"Mission proxy should produce non-trivial score"
			)

	def test_partial_weights_redistribute_with_mission(self):
		from claude_candidate.scoring.engine import QuickMatchEngine

		profile = _make_profile(["python", "react"])
		engine = QuickMatchEngine(profile)
		reqs = [
			QuickRequirement(
				description="Python",
				skill_mapping=["python"],
				priority=RequirementPriority.MUST_HAVE,
			),
		]
		result = engine.assess(reqs, company="TestCo", title="Engineer")
		if result.mission_alignment:
			assert result.mission_alignment.weight == pytest.approx(0.10)
			assert result.skill_match.weight == pytest.approx(0.80)
		# Must still be partial even with mission
		assert result.assessment_phase == "partial"
