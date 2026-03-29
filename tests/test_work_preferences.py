"""Tests for WorkPreferences schema, culture scoring, and CLI integration."""

from __future__ import annotations


import pytest

from claude_candidate.schemas.work_preferences import WorkPreferences


class TestWorkPreferencesSchema:
	"""Tests for the WorkPreferences pydantic model."""

	def test_defaults(self):
		prefs = WorkPreferences()
		assert prefs.remote_preference == "flexible"
		assert prefs.company_size == []
		assert prefs.culture_values == []
		assert prefs.culture_avoid == []

	def test_has_preferences_false_on_defaults(self):
		prefs = WorkPreferences()
		assert prefs.has_preferences is False

	def test_has_preferences_true_remote(self):
		prefs = WorkPreferences(remote_preference="remote_first")
		assert prefs.has_preferences is True

	def test_has_preferences_true_size(self):
		prefs = WorkPreferences(company_size=["startup"])
		assert prefs.has_preferences is True

	def test_has_preferences_true_values(self):
		prefs = WorkPreferences(culture_values=["collaboration"])
		assert prefs.has_preferences is True

	def test_has_preferences_true_avoid(self):
		prefs = WorkPreferences(culture_avoid=["micromanagement"])
		assert prefs.has_preferences is True

	def test_roundtrip_json(self, tmp_path):
		prefs = WorkPreferences(
			remote_preference="hybrid",
			company_size=["startup", "mid"],
			culture_values=["autonomy", "transparency"],
			culture_avoid=["crunch culture"],
		)
		path = tmp_path / "prefs.json"
		prefs.save(path)
		loaded = WorkPreferences.load(path)
		assert loaded is not None
		assert loaded.remote_preference == "hybrid"
		assert loaded.company_size == ["startup", "mid"]
		assert loaded.culture_values == ["autonomy", "transparency"]
		assert loaded.culture_avoid == ["crunch culture"]

	def test_load_missing_file(self, tmp_path):
		path = tmp_path / "nonexistent.json"
		assert WorkPreferences.load(path) is None

	def test_save_creates_parent_dirs(self, tmp_path):
		prefs = WorkPreferences(remote_preference="in_office")
		path = tmp_path / "sub" / "dir" / "prefs.json"
		prefs.save(path)
		assert path.exists()
		loaded = WorkPreferences.load(path)
		assert loaded is not None
		assert loaded.remote_preference == "in_office"

	def test_model_validate_from_dict(self):
		data = {
			"remote_preference": "remote_first",
			"company_size": ["enterprise"],
			"culture_values": ["innovation"],
			"culture_avoid": [],
		}
		prefs = WorkPreferences.model_validate(data)
		assert prefs.remote_preference == "remote_first"
		assert prefs.company_size == ["enterprise"]


class TestServerWorkPreferencesIntegration:
	"""Structural test verifying server assess_full uses work_preferences."""

	def test_server_imports_work_preferences(self):
		"""Verify the server module can import work_preferences-related code."""
		import inspect
		import claude_candidate.server as srv

		source = inspect.getsource(srv)
		assert "work_preferences" in source
		assert "_score_culture_preferences" in source

	def test_server_loads_preferences_from_home(self):
		"""Verify server assess_full path references work_preferences.json."""
		import inspect
		import claude_candidate.server as srv

		source = inspect.getsource(srv)
		assert "work_preferences.json" in source


class TestPreferencesOnboardCLI:
	"""Tests for the preferences CLI commands."""

	def test_onboard_accept_defaults(self, tmp_path):
		from click.testing import CliRunner
		from claude_candidate.cli import main

		out_path = tmp_path / "prefs.json"
		runner = CliRunner()
		result = runner.invoke(main, ["preferences", "onboard", "--accept-defaults", "-o", str(out_path)])
		assert result.exit_code == 0
		assert out_path.exists()
		loaded = WorkPreferences.load(out_path)
		assert loaded is not None
		assert loaded.has_preferences is False

	def test_onboard_interactive(self, tmp_path):
		from click.testing import CliRunner
		from claude_candidate.cli import main

		out_path = tmp_path / "prefs.json"
		runner = CliRunner()
		# Simulate: remote=1 (remote_first), size=1,2, values=autonomy, avoid=crunch
		result = runner.invoke(
			main,
			["preferences", "onboard", "-o", str(out_path)],
			input="1\n1,2\nautonomy\ncrunch\n",
		)
		assert result.exit_code == 0
		loaded = WorkPreferences.load(out_path)
		assert loaded is not None
		assert loaded.remote_preference == "remote_first"
		assert loaded.company_size == ["startup", "mid"]
		assert loaded.culture_values == ["autonomy"]
		assert loaded.culture_avoid == ["crunch"]

	def test_show_missing_file(self, tmp_path):
		from click.testing import CliRunner
		from claude_candidate.cli import main

		runner = CliRunner()
		result = runner.invoke(main, ["preferences", "show", "--path", str(tmp_path / "nope.json")])
		assert result.exit_code == 0
		assert "No preferences found" in result.output

	def test_show_existing_file(self, tmp_path):
		from click.testing import CliRunner
		from claude_candidate.cli import main

		prefs = WorkPreferences(
			remote_preference="hybrid",
			company_size=["startup"],
			culture_values=["autonomy"],
			culture_avoid=["crunch"],
		)
		path = tmp_path / "prefs.json"
		prefs.save(path)

		runner = CliRunner()
		result = runner.invoke(main, ["preferences", "show", "--path", str(path)])
		assert result.exit_code == 0
		assert "hybrid" in result.output
		assert "startup" in result.output
		assert "autonomy" in result.output
		assert "crunch" in result.output

	def test_preferences_group_registered(self):
		from click.testing import CliRunner
		from claude_candidate.cli import main

		runner = CliRunner()
		result = runner.invoke(main, ["preferences", "--help"])
		assert result.exit_code == 0
		assert "onboard" in result.output
		assert "show" in result.output


class TestCultureEngineIntegration:
	"""Tests for culture preferences wired into the QuickMatchEngine."""

	def test_assess_without_preferences_has_no_culture_dim(
		self, candidate_profile, resume_profile, quick_requirements
	):
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		result = engine.assess(
			requirements=quick_requirements,
			company="Test",
			title="Engineer",
		)
		assert result.culture_fit is None

	def test_assess_with_preferences_produces_culture_dim(
		self, candidate_profile, resume_profile, quick_requirements
	):
		from datetime import datetime
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.schemas.company_profile import CompanyProfile

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
			culture_values=["innovation"],
		)
		company = CompanyProfile(
			company_name="CultureCo",
			product_description="Culture test",
			product_domain=[],
			remote_policy="remote_first",
			company_size="startup",
			culture_keywords=["innovation", "autonomy"],
			enriched_at=datetime.now(),
		)
		result = engine.assess(
			requirements=quick_requirements,
			company="CultureCo",
			title="Engineer",
			company_profile=company,
			work_preferences=prefs,
		)
		assert result.culture_fit is not None
		assert result.culture_fit.dimension == "culture_fit"
		# With culture_dim present, phase is "full" per existing logic
		assert result.assessment_phase == "full"

	def test_culture_dim_affects_overall_score(
		self, candidate_profile, resume_profile, quick_requirements
	):
		from datetime import datetime
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.schemas.company_profile import CompanyProfile

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)

		# Baseline: no preferences
		baseline = engine.assess(
			requirements=quick_requirements,
			company="Test",
			title="Engineer",
		)

		# With preferences + company profile → culture dimension scored
		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
			culture_values=["innovation"],
		)
		company = CompanyProfile(
			company_name="CultureCo",
			product_description="Culture test",
			product_domain=[],
			remote_policy="remote_first",
			company_size="startup",
			culture_keywords=["innovation"],
			enriched_at=datetime.now(),
		)
		with_culture = engine.assess(
			requirements=quick_requirements,
			company="CultureCo",
			title="Engineer",
			company_profile=company,
			work_preferences=prefs,
		)
		# Scores differ because culture dimension is now factored in
		assert with_culture.overall_score != baseline.overall_score

	def test_avoid_cap_one_caps_at_b_plus(
		self, candidate_profile, resume_profile, quick_requirements
	):
		from datetime import datetime
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.schemas.company_profile import CompanyProfile

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
			culture_values=["innovation"],
			culture_avoid=["micromanagement"],  # 1 hit
		)
		company = CompanyProfile(
			company_name="BadCo",
			product_description="Bad culture",
			product_domain=[],
			remote_policy="remote_first",
			company_size="startup",
			culture_keywords=["innovation", "micromanagement"],
			enriched_at=datetime.now(),
		)
		result = engine.assess(
			requirements=quick_requirements,
			company="BadCo",
			title="Engineer",
			company_profile=company,
			work_preferences=prefs,
		)
		# Overall score should be capped at 0.799 (B+ cap)
		assert result.overall_score <= 0.799

	def test_avoid_cap_two_plus_caps_at_b_minus(
		self, candidate_profile, resume_profile, quick_requirements
	):
		from datetime import datetime
		from claude_candidate.merger import merge_profiles
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.schemas.company_profile import CompanyProfile

		merged = merge_profiles(candidate_profile, resume_profile)
		engine = QuickMatchEngine(merged)
		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
			culture_values=["innovation"],
			culture_avoid=["micromanagement", "crunch"],  # 2 hits
		)
		company = CompanyProfile(
			company_name="AwfulCo",
			product_description="Terrible culture",
			product_domain=[],
			remote_policy="remote_first",
			company_size="startup",
			culture_keywords=["innovation", "micromanagement", "crunch"],
			enriched_at=datetime.now(),
		)
		result = engine.assess(
			requirements=quick_requirements,
			company="AwfulCo",
			title="Engineer",
			company_profile=company,
			work_preferences=prefs,
		)
		# Overall score should be capped at 0.699 (B- cap)
		assert result.overall_score <= 0.699

	def test_work_preferences_field_on_assessment_input(self):
		from claude_candidate.scoring.engine import AssessmentInput

		inp = AssessmentInput(
			requirements=[],
			company="Test",
			title="Engineer",
			work_preferences=WorkPreferences(remote_preference="hybrid"),
		)
		assert inp.work_preferences is not None
		assert inp.work_preferences.remote_preference == "hybrid"


class TestOldCultureCodeRemoved:
	"""Verify old pattern-based culture scoring code has been deleted."""

	def test_engine_has_no_score_culture_fit(self):
		from claude_candidate.scoring.engine import QuickMatchEngine

		assert not hasattr(QuickMatchEngine, "_score_culture_fit")

	def test_engine_has_no_collect_culture_signals(self):
		from claude_candidate.scoring.engine import QuickMatchEngine

		assert not hasattr(QuickMatchEngine, "_collect_culture_signals")

	def test_engine_has_no_neutral_culture_dimension(self):
		from claude_candidate.scoring.engine import QuickMatchEngine

		assert not hasattr(QuickMatchEngine, "_neutral_culture_dimension")

	def test_engine_has_no_evaluate_culture_signals(self):
		from claude_candidate.scoring.engine import QuickMatchEngine

		assert not hasattr(QuickMatchEngine, "_evaluate_culture_signals")

	def test_engine_has_no_compute_culture_score(self):
		from claude_candidate.scoring.engine import QuickMatchEngine

		assert not hasattr(QuickMatchEngine, "_compute_culture_score")

	def test_dimensions_has_no_match_signal_to_pattern(self):
		import claude_candidate.scoring.dimensions as dims

		assert not hasattr(dims, "_match_signal_to_pattern")


class TestCultureConstants:
	"""Verify culture preference constants are correctly defined."""

	def test_remote_weight_values(self):
		from claude_candidate.scoring.constants import (
			CULTURE_REMOTE_WEIGHT,
			CULTURE_SIZE_WEIGHT,
			CULTURE_VALUES_WEIGHT,
		)

		assert CULTURE_REMOTE_WEIGHT == 0.3
		assert CULTURE_SIZE_WEIGHT == 0.2
		assert CULTURE_VALUES_WEIGHT == 0.5
		assert abs(CULTURE_REMOTE_WEIGHT + CULTURE_SIZE_WEIGHT + CULTURE_VALUES_WEIGHT - 1.0) < 1e-9

	def test_remote_match_matrix_covers_all_combinations(self):
		from claude_candidate.scoring.constants import REMOTE_MATCH_MATRIX

		candidates = ["remote_first", "hybrid", "in_office", "flexible"]
		companies = ["remote_first", "hybrid", "in_office"]
		for cand in candidates:
			for comp in companies:
				assert (cand, comp) in REMOTE_MATCH_MATRIX, f"Missing ({cand}, {comp})"

	def test_remote_matrix_perfect_matches_score_one(self):
		from claude_candidate.scoring.constants import REMOTE_MATCH_MATRIX

		assert REMOTE_MATCH_MATRIX[("remote_first", "remote_first")] == 1.0
		assert REMOTE_MATCH_MATRIX[("hybrid", "hybrid")] == 1.0
		assert REMOTE_MATCH_MATRIX[("in_office", "in_office")] == 1.0

	def test_flexible_always_scores_one(self):
		from claude_candidate.scoring.constants import REMOTE_MATCH_MATRIX

		for policy in ("remote_first", "hybrid", "in_office"):
			assert REMOTE_MATCH_MATRIX[("flexible", policy)] == 1.0

	def test_unknown_score(self):
		from claude_candidate.scoring.constants import CULTURE_UNKNOWN_SCORE

		assert CULTURE_UNKNOWN_SCORE == 0.7

	def test_size_match_scores(self):
		from claude_candidate.scoring.constants import CULTURE_SIZE_MATCH, CULTURE_SIZE_NO_MATCH

		assert CULTURE_SIZE_MATCH == 1.0
		assert CULTURE_SIZE_NO_MATCH == 0.3

	def test_avoid_caps(self):
		from claude_candidate.scoring.constants import (
			CULTURE_AVOID_CAP_ONE,
			CULTURE_AVOID_CAP_TWO_PLUS,
		)

		assert CULTURE_AVOID_CAP_ONE == 0.799
		assert CULTURE_AVOID_CAP_TWO_PLUS == 0.699

	def test_constants_importable_from_scoring_package(self):
		from claude_candidate.scoring import (
			CULTURE_REMOTE_WEIGHT,
		)

		# Just verify they're importable (values tested above)
		assert CULTURE_REMOTE_WEIGHT is not None


class TestScoreCulturePreferences:
	"""Tests for the _score_culture_preferences scoring function."""

	@pytest.fixture
	def _company(self):
		from datetime import datetime
		from claude_candidate.schemas.company_profile import CompanyProfile

		return CompanyProfile(
			company_name="TestCo",
			product_description="A test company",
			product_domain=["developer-tools"],
			remote_policy="remote_first",
			company_size="startup",
			culture_keywords=["autonomy", "transparency", "innovation"],
			enriched_at=datetime.now(),
		)

	@pytest.fixture
	def _prefs(self):
		return WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
			culture_values=["autonomy", "transparency"],
			culture_avoid=[],
		)

	def test_none_preferences_returns_none(self, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		assert _score_culture_preferences(None, _company) is None

	def test_default_preferences_returns_none(self, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		prefs = WorkPreferences()  # all defaults, has_preferences=False
		assert _score_culture_preferences(prefs, _company) is None

	def test_none_company_returns_none(self, _prefs):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		assert _score_culture_preferences(_prefs, None) is None

	def test_perfect_match_scores_high(self, _prefs, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		result = _score_culture_preferences(_prefs, _company)
		assert result is not None
		dim, avoid_count = result
		assert dim.dimension == "culture_fit"
		assert dim.score >= 0.8  # perfect remote + size + partial values
		assert avoid_count == 0

	def test_remote_mismatch_lowers_score(self, _prefs, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		# Baseline: perfect remote match
		perfect_result = _score_culture_preferences(_prefs, _company)
		assert perfect_result is not None
		perfect_score = perfect_result[0].score

		# Mismatched remote preference
		prefs = WorkPreferences(
			remote_preference="in_office",
			company_size=["startup"],
			culture_values=["autonomy", "transparency"],
		)
		result = _score_culture_preferences(prefs, _company)
		assert result is not None
		dim, _ = result
		# in_office vs remote_first = 0.5 penalty on remote sub-score
		assert dim.score < perfect_score

	def test_size_mismatch_lowers_score(self, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["enterprise"],
			culture_values=["autonomy", "transparency"],
		)
		result = _score_culture_preferences(prefs, _company)
		assert result is not None
		dim, _ = result
		# enterprise vs startup = SIZE_NO_MATCH
		assert dim.score < 0.9

	def test_no_values_overlap(self, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
			culture_values=["bureaucracy", "hierarchy"],
		)
		result = _score_culture_preferences(prefs, _company)
		assert result is not None
		dim, _ = result
		# values sub-score = 0 (no overlap), but remote and size match
		assert dim.score < 0.6

	def test_avoid_single_hit(self, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
			culture_values=["autonomy"],
			culture_avoid=["innovation"],  # this IS in company keywords
		)
		result = _score_culture_preferences(prefs, _company)
		assert result is not None
		_, avoid_count = result
		assert avoid_count == 1

	def test_avoid_multiple_hits(self, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
			culture_values=[],
			culture_avoid=["autonomy", "transparency"],
		)
		result = _score_culture_preferences(prefs, _company)
		assert result is not None
		_, avoid_count = result
		assert avoid_count == 2

	def test_unknown_remote_policy(self, _prefs):
		from datetime import datetime
		from claude_candidate.schemas.company_profile import CompanyProfile
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		company = CompanyProfile(
			company_name="Mystery Corp",
			product_description="Unknown",
			product_domain=[],
			remote_policy="unknown",
			enriched_at=datetime.now(),
		)
		result = _score_culture_preferences(_prefs, company)
		assert result is not None
		# Remote sub-score should be CULTURE_UNKNOWN_SCORE

	def test_unknown_company_size(self, _prefs):
		from datetime import datetime
		from claude_candidate.schemas.company_profile import CompanyProfile
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		company = CompanyProfile(
			company_name="NullSize Inc",
			product_description="No size info",
			product_domain=[],
			company_size=None,
			enriched_at=datetime.now(),
		)
		result = _score_culture_preferences(_prefs, company)
		assert result is not None

	def test_flexible_preference_scores_one_for_any_policy(self):
		from datetime import datetime
		from claude_candidate.schemas.company_profile import CompanyProfile
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		prefs = WorkPreferences(
			remote_preference="flexible",
			company_size=["startup"],
		)
		for policy in ("remote_first", "hybrid", "in_office"):
			company = CompanyProfile(
				company_name="Flex Corp",
				product_description="Flexible",
				product_domain=[],
				remote_policy=policy,
				company_size="startup",
				enriched_at=datetime.now(),
			)
			result = _score_culture_preferences(prefs, company)
			assert result is not None
			dim, _ = result
			# Remote sub-score should be 1.0 for flexible
			# Combined with size match, score should be high
			assert dim.score >= 0.7

	def test_values_case_insensitive(self, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
			culture_values=["AUTONOMY", "Transparency"],
		)
		result = _score_culture_preferences(prefs, _company)
		assert result is not None
		dim, _ = result
		# Should match despite case differences
		assert dim.score >= 0.8

	def test_avoid_case_insensitive(self, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		prefs = WorkPreferences(
			remote_preference="remote_first",
			company_size=["startup"],
			culture_avoid=["INNOVATION"],
		)
		result = _score_culture_preferences(prefs, _company)
		assert result is not None
		_, avoid_count = result
		assert avoid_count == 1

	def test_score_bounded_zero_to_one(self, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		prefs = WorkPreferences(
			remote_preference="in_office",
			company_size=["enterprise"],
			culture_values=["bureaucracy", "hierarchy"],
		)
		result = _score_culture_preferences(prefs, _company)
		assert result is not None
		dim, _ = result
		assert 0.0 <= dim.score <= 1.0

	def test_dimension_label(self, _prefs, _company):
		from claude_candidate.scoring.dimensions import _score_culture_preferences

		result = _score_culture_preferences(_prefs, _company)
		assert result is not None
		dim, _ = result
		assert dim.dimension == "culture_fit"
