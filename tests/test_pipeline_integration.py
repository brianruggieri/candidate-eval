"""Integration tests for the unified parsing pipeline."""

import json
from pathlib import Path

import pytest

from claude_candidate.requirement_parser import (
	build_extraction_prompt,
	CACHE_PROMPT_VERSION,
)


POSTING_DIR = Path(__file__).parent / "golden_set" / "postings"


def _load_posting(name: str) -> dict:
	path = POSTING_DIR / f"{name}.json"
	return json.loads(path.read_text())


class TestCachePromptVersion:
	"""Verify the cache version key exists and is a non-empty string."""

	def test_cache_version_is_string(self):
		assert isinstance(CACHE_PROMPT_VERSION, str)
		assert len(CACHE_PROMPT_VERSION) > 0

	def test_prompt_includes_all_requirement_fields(self):
		"""Both CLI and server prompts must extract the same requirement fields."""
		prompt = build_extraction_prompt("Test", "Some job posting text")
		# Fields that must appear in the extraction prompt
		for field in [
			"description",
			"skill_mapping",
			"priority",
			"years_experience",
			"education_level",
			"is_eligibility",
			"source_text",
		]:
			assert field in prompt, f"Missing field '{field}' in extraction prompt"


class TestFullPipelineIntegration:
	"""Integration test for full pipeline (raw text -> parser -> scoring)."""

	@pytest.fixture
	def engine(self):
		"""Build a scoring engine from the same profile the benchmark uses."""
		from claude_candidate.scoring.engine import QuickMatchEngine
		from claude_candidate.merger import merge_with_curated, merge_candidate_only
		from claude_candidate.schemas.candidate_profile import CandidateProfile
		from claude_candidate.schemas.curated_resume import CuratedResume

		data_dir = Path.home() / ".claude-candidate"
		cp_path = data_dir / "candidate_profile.json"
		if not cp_path.exists():
			pytest.skip("No candidate_profile.json available for integration test")

		cp = CandidateProfile.from_json(cp_path.read_text())
		curated_path = data_dir / "curated_resume.json"
		if curated_path.exists():
			curated = CuratedResume.model_validate_json(curated_path.read_text())
			profile = merge_with_curated(cp, curated)
		else:
			profile = merge_candidate_only(cp)
		return QuickMatchEngine(profile)

	@pytest.mark.parametrize(
		"posting_name",
		[p.stem for p in sorted(POSTING_DIR.glob("*.json"))[:5]]
		if POSTING_DIR.exists()
		else [],
	)
	def test_full_pipeline_produces_valid_assessment(self, posting_name, engine):
		"""Raw requirements -> QuickRequirement[] -> FitAssessment with valid structure."""
		posting = _load_posting(posting_name)

		from claude_candidate.schemas.job_requirements import QuickRequirement
		from claude_candidate.requirement_parser import compute_distillation_weights

		reqs = []
		for r in posting.get("requirements", []):
			try:
				reqs.append(QuickRequirement(**r))
			except Exception:
				continue
		if not reqs:
			pytest.skip(f"No valid requirements in {posting_name}")

		compute_distillation_weights(reqs)

		result = engine.assess(
			reqs,
			company=posting.get("company", "Unknown"),
			title=posting.get("title", "Unknown"),
		)
		assert 0.0 <= result.overall_score <= 1.0
		assert result.overall_grade in [
			"A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F",
		]
		assert len(result.skill_matches) > 0
		assert result.assessment_phase == "partial"  # No company profile = partial
