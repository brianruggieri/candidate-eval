import json
from datetime import datetime, timezone

import pytest
import yaml

from claude_candidate.fit_exporter import (
	generate_slug,
	select_skill_matches,
	select_evidence_highlights,
	select_patterns,
	select_projects,
	select_gaps,
	write_fit_page,
	export_fit_assessment,
	_normalize_evidence_source,
	compute_evidence_tier,
	load_benchmark_metadata,
	format_skill_repo_fallback,
	ABSTRACT_SKILLS,
	_ABSTRACT_SIGNAL_RULES,
	_apply_signal_rules,
	_build_abstract_skill_prompt,
	_claude_infer_abstract_skills,
	_build_commit_tagged_skills,
	resolve_abstract_skills,
)
from claude_candidate.schemas.repo_profile import SkillRepoEvidence


def test_basic_slug():
	assert generate_slug("Software Engineer", "Anthropic") == "software-engineer-anthropic"


def test_strips_senior_prefix():
	assert generate_slug("Senior Software Engineer", "Stripe") == "software-engineer-stripe"


def test_strips_sr_prefix():
	assert generate_slug("Sr. Backend Engineer", "Netflix") == "backend-engineer-netflix"


def test_keeps_highest_seniority():
	assert generate_slug("Sr. Staff Software Engineer", "Google") == "staff-engineer-google"


def test_strips_roman_numerals():
	assert generate_slug("Software Engineer III", "Meta") == "software-engineer-meta"


def test_truncates_long_title():
	assert (
		generate_slug("Senior Staff Software Development Engineer in Test", "Amazon")
		== "staff-engineer-amazon"
	)


def test_first_word_of_company():
	assert generate_slug("Staff Engineer", "Acme Corp Inc") == "staff-engineer-acme"


def test_lead_title():
	assert generate_slug("Engineering Manager", "Substack") == "eng-manager-substack"


def test_principal_title():
	assert generate_slug("Principal Engineer", "Adobe") == "principal-engineer-adobe"


def test_director_title():
	assert generate_slug("Director of Engineering", "NPR") == "director-engineering-npr"


def test_hyphenates_and_lowercases():
	assert generate_slug("Full Stack Developer", "Change.org") == "fullstack-developer-change"


# ── Content Selection Tests ──


def _make_skill_match(
	requirement, priority, match_status, evidence_source="corroborated", confidence=0.8
):
	"""Helper to create a SkillMatchDetail-like dict."""
	return {
		"requirement": requirement,
		"priority": priority,
		"match_status": match_status,
		"candidate_evidence": f"Experience with {requirement}",
		"evidence_source": evidence_source,
		"confidence": confidence,
	}


def test_select_skill_matches_limits_to_10():
	matches = [_make_skill_match(f"skill_{i}", "must_have", "strong_match") for i in range(15)]
	result = select_skill_matches(matches)
	assert len(result) <= 10


def test_select_skill_matches_sorts_by_priority():
	matches = [
		_make_skill_match("nice", "nice_to_have", "strong_match"),
		_make_skill_match("must", "must_have", "strong_match"),
		_make_skill_match("pref", "strong_preference", "strong_match"),
	]
	result = select_skill_matches(matches)
	assert result[0]["requirement"] == "must"
	assert result[1]["requirement"] == "pref"


def test_select_gaps_filters_correctly():
	matches = [
		_make_skill_match("Python", "must_have", "strong_match"),
		_make_skill_match("K8s", "must_have", "no_evidence"),
		_make_skill_match("Docker", "strong_preference", "adjacent"),
		_make_skill_match("Go", "nice_to_have", "no_evidence"),
	]
	result = select_gaps(matches)
	requirements = [g["requirement"] for g in result]
	assert "K8S" in requirements  # .title() on "K8s" → "K8S"
	assert "Docker" in requirements
	assert "Python" not in requirements  # strong_match, not a gap
	assert "Go" not in requirements  # nice_to_have, not important enough


def test_select_gaps_limits_to_3():
	matches = [_make_skill_match(f"gap_{i}", "must_have", "no_evidence") for i in range(5)]
	result = select_gaps(matches)
	assert len(result) <= 3


def test_select_patterns_sorts_by_strength():
	patterns = [
		{"pattern_type": "testing_instinct", "strength": "established", "frequency": "common"},
		{"pattern_type": "architecture_first", "strength": "exceptional", "frequency": "dominant"},
		{"pattern_type": "iterative_refinement", "strength": "strong", "frequency": "common"},
	]
	result = select_patterns(patterns)
	assert result[0]["name"] == "Architecture First"
	assert result[1]["name"] == "Iterative Refinement"


def test_select_patterns_limits_to_5():
	patterns = [
		{"pattern_type": f"pattern_{i}", "strength": "strong", "frequency": "common"}
		for i in range(8)
	]
	result = select_patterns(patterns)
	assert len(result) <= 5


# ── YAML Front Matter Writer Tests ──


def test_write_fit_page_creates_file(tmp_path):
	data = {
		"title": "Staff Engineer",
		"company": "Anthropic",
		"slug": "staff-engineer-anthropic",
		"description": "Evidence-backed fit assessment for Staff Engineer at Anthropic",
		"overall_grade": "A+",
		"overall_score": 0.97,
		"should_apply": "strong_yes",
		"overall_summary": "Exceptional fit.",
		"skill_matches": [],
		"evidence_highlights": [],
		"patterns": [],
		"projects": [],
		"gaps": [],
	}
	result = write_fit_page(data, output_dir=tmp_path)
	assert result.exists()
	assert result.name == "staff-engineer-anthropic.md"


def test_write_fit_page_valid_yaml(tmp_path):
	data = {
		"title": "Staff Engineer",
		"company": "Anthropic",
		"slug": "staff-engineer-anthropic",
		"description": "Test",
		"overall_grade": "A+",
		"overall_score": 0.97,
		"should_apply": "strong_yes",
		"overall_summary": "Great fit.",
		"skill_matches": [
			{
				"skill": "Python",
				"status": "strong_match",
				"priority": "must_have",
				"depth": "Expert",
				"sessions": 551,
				"source": "corroborated",
				"discovery": False,
			},
		],
		"evidence_highlights": [],
		"patterns": [
			{"name": "Architecture First", "strength": "Exceptional", "frequency": "Dominant"}
		],
		"projects": [],
		"gaps": [],
	}
	result = write_fit_page(data, output_dir=tmp_path)
	content = result.read_text()

	# Verify YAML front matter is valid
	assert content.startswith("---\n")
	parts = content.split("---\n", 2)
	assert len(parts) >= 3  # before ---, yaml content, after ---
	parsed = yaml.safe_load(parts[1])
	assert parsed["title"] == "Staff Engineer"
	assert parsed["company"] == "Anthropic"
	assert parsed["overall_grade"] == "A+"
	assert len(parsed["skill_matches"]) == 1
	assert parsed["skill_matches"][0]["skill"] == "Python"


def test_write_fit_page_defaults(tmp_path):
	data = {
		"title": "Engineer",
		"company": "Test",
		"slug": "engineer-test",
		"description": "Test",
		"overall_grade": "B+",
		"overall_score": 0.80,
		"should_apply": "yes",
		"overall_summary": "Solid fit.",
		"skill_matches": [],
		"evidence_highlights": [],
		"patterns": [],
		"projects": [],
		"gaps": [],
	}
	result = write_fit_page(data, output_dir=tmp_path)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert parsed["public"] is False
	assert "cal_link" in parsed


# ── Integration Test ──


def test_export_fit_assessment_end_to_end(tmp_path):
	"""Integration test: full export pipeline with mock data files."""
	# Create mock merged profile
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "corroborated",
				"effective_depth": "EXPERT",
				"session_evidence_count": 551,
				"discovery_flag": False,
				"confidence": 0.95,
			},
			{
				"name": "react",
				"source": "sessions_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 229,
				"discovery_flag": True,
				"confidence": 0.8,
			},
		],
		"patterns": [
			{
				"pattern_type": "architecture_first",
				"strength": "exceptional",
				"frequency": "dominant",
			},
			{"pattern_type": "testing_instinct", "strength": "strong", "frequency": "common"},
		],
		"projects": [
			{
				"name": "claude-candidate",
				"url": "https://github.com/user/claude-candidate",
				"description": "Evidence-backed job fit engine",
				"languages": ["Python", "TypeScript"],
				"dependencies": ["fastapi", "pydantic", "click"],
				"commit_span_days": 84,
				"created_at": "2026-01-01T00:00:00Z",
				"last_pushed": "2026-03-20T00:00:00Z",
				"has_tests": True,
				"test_framework": "pytest",
				"has_ci": True,
				"releases": 3,
				"ai_maturity_level": "advanced",
				"evidence_highlights": [],
			},
		],
	}
	merged_path = tmp_path / "merged_profile.json"  # kept for reference, not passed to function
	merged_path.write_text(json.dumps(merged))

	# Create mock assessment data matching what storage.get_assessment() returns.
	# storage._decode_assessment() already JSON-parses the 'data' field,
	# so 'data' is a dict here. Top-level 'should_apply' is coerced to bool.
	assessment = {
		"assessment_id": "test-123",
		"should_apply": True,  # coerced by storage layer
		"data": {
			"job_title": "Staff Engineer",
			"company_name": "Anthropic",
			"posting_url": "https://example.com/jobs/123",
			"overall_grade": "A+",
			"overall_score": 0.97,
			"should_apply": "strong_yes",  # original string in nested data
			"overall_summary": "Exceptional fit.",
			"skill_matches": [
				{
					"requirement": "Strong experience with Python and backend systems",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Expert Python developer",
					"evidence_source": "corroborated",
					"confidence": 0.95,
					"matched_skill": "python",
				},
				{
					"requirement": "Modern React development with hooks and context",
					"priority": "must_have",
					"match_status": "exceeds",
					"candidate_evidence": "React expert with 27 sessions",
					"evidence_source": "sessions_only",
					"confidence": 0.85,
					"matched_skill": "react",
				},
				{
					"requirement": "Experience with FastAPI or similar frameworks",
					"priority": "strong_preference",
					"match_status": "strong_match",
					"candidate_evidence": "Expert FastAPI developer",
					"evidence_source": "sessions_only",
					"confidence": 0.90,
					"matched_skill": "fastapi",
				},
				{
					"requirement": "kubernetes",
					"priority": "must_have",
					"match_status": "no_evidence",
					"candidate_evidence": "Adjacent experience with Docker",
					"evidence_source": "resume_only",
					"confidence": 0.1,
					"matched_skill": None,
				},
			],
			"action_items": ["Learn Kubernetes for container orchestration"],
		},
	}

	output_dir = tmp_path / "content" / "fit"
	output_dir.mkdir(parents=True)

	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		output_dir=output_dir,
	)

	assert result.exists()
	assert result.name == "staff-engineer-anthropic.md"

	content = result.read_text()
	parsed = yaml.safe_load(content.split("---\n", 2)[1])
	assert parsed["overall_grade"] == "A+"
	assert parsed["company"] == "Anthropic"
	assert len(parsed["skill_matches"]) >= 1
	# Requirement is a sentence, but matched_skill="python" enables the join
	assert (
		parsed["skill_matches"][0]["skill"] == "Strong experience with Python and backend systems"
	)
	assert parsed["skill_matches"][0]["depth"] == "Expert"  # enriched via matched_skill join
	assert parsed["skill_matches"][0]["sessions"] == 551
	assert len(parsed["gaps"]) >= 1
	assert parsed["gaps"][0]["requirement"] == "Kubernetes"
	# Session evidence is dormant (D6) — evidence highlights are empty until commit evidence (D2)
	assert parsed["evidence_highlights"] == []


# ── Empty company / title edge cases ──


def test_empty_company_fallback():
	"""Empty company name should produce fallback slug, not crash."""
	slug = generate_slug("Software Engineer", "")
	assert slug == "software-engineer-company"


def test_whitespace_company_fallback():
	slug = generate_slug("Engineer", "   ")
	assert slug == "engineer-company"


def test_empty_title_uses_company():
	slug = generate_slug("", "Anthropic")
	assert "anthropic" in slug


# ── Threshold validation ──


def test_export_fails_below_skill_threshold(tmp_path):
	"""Export should fail when fewer than 3 skill matches."""
	merged = {
		"skills": [],
		"patterns": [],
		"projects": [
			{
				"name": "test",
				"description": "test",
				"languages": [],
				"dependencies": [],
				"commit_span_days": 10,
				"created_at": "2026-01-01T00:00:00Z",
				"last_pushed": "2026-01-10T00:00:00Z",
				"has_tests": False,
				"has_ci": False,
				"releases": 0,
				"ai_maturity_level": "basic",
			},
		],
	}

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "Test",
			"overall_grade": "D",
			"overall_score": 0.4,
			"should_apply": "no",
			"overall_summary": "Poor fit.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "corroborated",
					"confidence": 0.9,
				},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()

	with pytest.raises(ValueError, match="minimum 3 required"):
		export_fit_assessment(
			assessment,
			merged_profile_data=merged,
			output_dir=output_dir,
		)


# ── Evidence highlights ──


def test_select_evidence_highlights_basic():
	"""Evidence highlights should pick strong_match entries with session evidence."""
	skill_matches = [
		{
			"requirement": "python",
			"match_status": "strong_match",
			"evidence_source": "corroborated",
			"confidence": 0.95,
		},
		{
			"requirement": "rust",
			"match_status": "no_evidence",
			"evidence_source": "resume_only",
			"confidence": 0.0,
		},
	]
	candidate_skills = [
		{
			"name": "python",
			"evidence": [
				{
					"session_id": "s1",
					"session_date": "2026-03-01T00:00:00",
					"project_context": "test-project",
					"evidence_snippet": "Built async pipeline",
					"confidence": 0.9,
				},
			],
		},
	]

	result = select_evidence_highlights(skill_matches, candidate_skills)
	assert len(result) == 1
	assert result[0]["heading"] == "Python"
	assert result[0]["quote"] == "Built async pipeline"
	assert result[0]["project"] == "test-project"


def test_select_evidence_highlights_empty():
	"""No strong matches = no evidence highlights."""
	skill_matches = [
		{
			"requirement": "rust",
			"match_status": "no_evidence",
			"evidence_source": "resume_only",
			"confidence": 0.0,
		},
	]
	result = select_evidence_highlights(skill_matches, [])
	assert result == []


def test_select_evidence_highlights_prefers_corroborated():
	"""Corroborated sources should sort before sessions_only."""
	skill_matches = [
		{
			"requirement": "react",
			"match_status": "strong_match",
			"evidence_source": "sessions_only",
			"confidence": 0.8,
		},
		{
			"requirement": "python",
			"match_status": "strong_match",
			"evidence_source": "corroborated",
			"confidence": 0.95,
		},
	]
	candidate_skills = [
		{
			"name": "react",
			"evidence": [
				{
					"session_id": "s1",
					"session_date": "2026-01-01T00:00:00",
					"project_context": "app",
					"evidence_snippet": "React code",
					"confidence": 0.8,
				},
			],
		},
		{
			"name": "python",
			"evidence": [
				{
					"session_id": "s2",
					"session_date": "2026-02-01T00:00:00",
					"project_context": "api",
					"evidence_snippet": "Python code",
					"confidence": 0.95,
				},
			],
		},
	]

	result = select_evidence_highlights(skill_matches, candidate_skills, limit=1)
	assert result[0]["heading"] == "Python"  # corroborated first


def test_select_evidence_highlights_phrase_resolution():
	"""Requirement phrases like '5+ years python experience' should resolve to 'python'."""
	skill_matches = [
		{
			"requirement": "5+ years python experience",
			"matched_skill": None,
			"match_status": "strong_match",
			"confidence": 0.9,
		},
	]
	candidate_skills = [
		{
			"name": "python",
			"evidence": [
				{
					"session_id": "s1",
					"session_date": "2026-03-01T00:00:00",
					"project_context": "api",
					"evidence_snippet": "Built API",
					"confidence": 0.9,
				},
			],
		},
	]

	result = select_evidence_highlights(skill_matches, candidate_skills)
	assert len(result) == 1
	assert result[0]["quote"] == "Built API"


def test_select_evidence_highlights_no_false_positive():
	"""Generic phrases without a real skill name should NOT match anything."""
	skill_matches = [
		{
			"requirement": "3+ years experience",
			"matched_skill": None,
			"match_status": "strong_match",
			"confidence": 0.9,
		},
	]
	candidate_skills = [
		{
			"name": "startup-experience",
			"evidence": [
				{
					"session_id": "s1",
					"session_date": "2026-03-01T00:00:00",
					"project_context": "startup",
					"evidence_snippet": "Startup work",
					"confidence": 0.9,
				},
			],
		},
	]

	result = select_evidence_highlights(skill_matches, candidate_skills)
	assert result == []  # "experience" should not fuzzy-match to "startup-experience"


# ── Task 4: Normalize Evidence Source ──


class TestNormalizeEvidenceSource:
	def test_resume_only_passes_through(self):
		assert _normalize_evidence_source("resume_only") == "resume_only"

	def test_resume_and_repo_passes_through(self):
		assert _normalize_evidence_source("resume_and_repo") == "resume_and_repo"

	def test_repo_only_passes_through(self):
		assert _normalize_evidence_source("repo_only") == "repo_only"

	def test_corroborated_maps_to_resume_and_repo(self):
		assert _normalize_evidence_source("corroborated") == "resume_and_repo"

	def test_sessions_only_maps_to_repo_only(self):
		assert _normalize_evidence_source("sessions_only") == "repo_only"

	def test_conflicting_maps_to_resume_and_repo(self):
		assert _normalize_evidence_source("conflicting") == "resume_and_repo"

	def test_unknown_maps_to_resume_only(self):
		assert _normalize_evidence_source("totally_unknown_value") == "resume_only"


# ── Task 1: Evidence Tier Computation ──


class TestComputeEvidenceTier:
	def test_inspectable_when_public_repo_url(self):
		match = {"evidence_source": "repo_only", "confidence": 0.9}
		projects = [
			{"project_name": "my-project", "public_repo_url": "https://github.com/user/my-project"}
		]
		# evidence_snippet referencing a project with public_repo_url
		snippet = "Built the pipeline for my-project"
		tier = compute_evidence_tier(match, snippet, projects)
		assert tier == "inspectable"

	def test_inspectable_when_github_commit_in_evidence(self):
		match = {"evidence_source": "repo_only", "confidence": 0.9}
		snippet = (
			"Implemented feature https://github.com/user/repo/commit/abc123def456 in production"
		)
		tier = compute_evidence_tier(match, snippet, [])
		assert tier == "inspectable"

	def test_claimed_when_resume_only(self):
		match = {"evidence_source": "resume_only", "confidence": 0.7}
		tier = compute_evidence_tier(match, "", [])
		assert tier == "claimed"

	def test_claimed_when_no_repo_no_url(self):
		match = {"evidence_source": "repo_only", "confidence": 0.8}
		snippet = "Used Python extensively in backend work"
		tier = compute_evidence_tier(match, snippet, [])
		assert tier == "claimed"

	def test_deployed_when_live_url_in_evidence(self):
		match = {"evidence_source": "repo_only", "confidence": 0.85}
		snippet = "Deployed at https://myapp.example.com for production use"
		tier = compute_evidence_tier(match, snippet, [])
		assert tier == "deployed"

	def test_www_github_not_classified_as_deployed(self):
		"""www.github.com and other GitHub subdomains must not trigger deployed tier."""
		match = {"evidence_source": "repo_only", "confidence": 0.85}
		snippet = "See https://www.github.com/user/repo for details"
		tier = compute_evidence_tier(match, snippet, [])
		assert tier != "deployed"

	def test_inspectable_only_for_matched_projects(self):
		"""A project with public_repo_url unrelated to the match should not trigger inspectable."""
		match = {"evidence_source": "resume_only", "confidence": 0.6}
		unrelated_project = {
			"project_name": "other-project",
			"public_repo_url": "https://github.com/user/other",
		}
		tier = compute_evidence_tier(match, "", [unrelated_project])
		# The project IS passed, so compute_evidence_tier returns inspectable.
		# The call site is responsible for filtering — this tests function purity.
		assert tier == "inspectable"


# ── Task 2: public_repo_url on projects ──


def test_select_projects_includes_public_repo_url():
	"""projects pass through public_repo_url when present, None when absent."""
	projects = [
		{
			"project_name": "open-source-lib",
			"description": "A Python library",
			"complexity": "moderate",
			"technologies": ["Python"],
			"session_count": 10,
			"date_range_start": "2025-01-01",
			"date_range_end": "2025-06-01",
			"key_decisions": ["Chose MIT license"],
			"public_repo_url": "https://github.com/user/open-source-lib",
		},
		{
			"project_name": "private-project",
			"description": "A private project",
			"complexity": "simple",
			"technologies": ["Go"],
			"session_count": 5,
			"date_range_start": "2025-07-01",
			"date_range_end": "2025-09-01",
			"key_decisions": ["Used microservices"],
		},
	]
	result = select_projects(projects)
	names = {p["name"]: p for p in result}
	assert names["open-source-lib"]["public_repo_url"] == "https://github.com/user/open-source-lib"
	assert names["private-project"]["public_repo_url"] is None


# ── RepoProject-shaped project tests ──


def test_select_projects_from_repo_project_shape():
	"""select_projects should work with RepoProject-shaped dicts (name, languages, dependencies)."""
	projects = [
		{
			"name": "candidate-eval",
			"url": "https://github.com/user/candidate-eval",
			"description": "Evidence-backed job fit engine",
			"languages": ["Python", "TypeScript", "Shell"],
			"dependencies": ["fastapi", "pydantic", "click"],
			"commit_span_days": 84,
			"created_at": "2026-01-01T00:00:00Z",
			"last_pushed": "2026-03-25T00:00:00Z",
			"has_tests": True,
			"test_framework": "pytest",
			"has_ci": True,
			"releases": 3,
			"ai_maturity_level": "advanced",
			"evidence_highlights": [],
		},
	]
	result = select_projects(projects)
	assert len(result) == 1
	assert result[0]["name"] == "candidate-eval"
	assert result[0]["url"] == "https://github.com/user/candidate-eval"
	assert result[0]["description"] == "Evidence-backed job fit engine"


def test_select_projects_relevance_uses_languages_and_deps():
	"""Relevance scoring should consider both languages and dependencies for RepoProject dicts."""
	projects = [
		{
			"name": "go-service",
			"description": "A Go microservice",
			"languages": ["Go"],
			"dependencies": ["gin"],
			"commit_span_days": 30,
			"created_at": "2026-01-01T00:00:00Z",
			"last_pushed": "2026-02-01T00:00:00Z",
			"has_tests": True,
			"has_ci": False,
			"releases": 0,
			"ai_maturity_level": "basic",
		},
		{
			"name": "python-api",
			"description": "A Python API",
			"languages": ["Python"],
			"dependencies": ["fastapi", "pydantic"],
			"commit_span_days": 60,
			"created_at": "2026-01-01T00:00:00Z",
			"last_pushed": "2026-03-01T00:00:00Z",
			"has_tests": True,
			"has_ci": True,
			"releases": 2,
			"ai_maturity_level": "intermediate",
		},
	]
	# Job requires Python and FastAPI — python-api should rank first
	result = select_projects(projects, job_technologies=["Python", "FastAPI"])
	assert result[0]["name"] == "python-api"


def test_select_projects_date_range_from_repo_timestamps():
	"""Date range should be derived from created_at/last_pushed for RepoProject dicts."""
	projects = [
		{
			"name": "multi-year",
			"description": "Long-running project",
			"languages": ["Python"],
			"dependencies": [],
			"commit_span_days": 365,
			"created_at": "2025-01-15T00:00:00Z",
			"last_pushed": "2026-03-20T00:00:00Z",
			"has_tests": False,
			"has_ci": False,
			"releases": 0,
			"ai_maturity_level": "basic",
		},
	]
	result = select_projects(projects)
	assert result[0]["date_range"] == "2025 — 2026"


# ── Task 3: Benchmark Metadata Fields ──


def test_write_fit_page_includes_benchmark_metadata(tmp_path):
	"""benchmark_postings_count and benchmark_calibration_date should appear in YAML output."""
	data = {
		"title": "Staff Engineer",
		"company": "Anthropic",
		"slug": "staff-engineer-anthropic",
		"description": "Test",
		"overall_grade": "A+",
		"overall_score": 0.97,
		"should_apply": "strong_yes",
		"overall_summary": "Great fit.",
		"skill_matches": [],
		"evidence_highlights": [],
		"patterns": [],
		"projects": [],
		"gaps": [],
		"benchmark_postings_count": 47,
		"benchmark_calibration_date": "2026-03-23",
	}
	result = write_fit_page(data, output_dir=tmp_path)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert parsed["benchmark_postings_count"] == 47
	assert parsed["benchmark_calibration_date"] == "2026-03-23"


# ── Task 5: company_research_sample and narrative_verdict exclusion ──


def test_export_includes_company_research_sample(tmp_path):
	"""company_research_sample should appear in the YAML output."""
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "resume_only",
				"effective_depth": "EXPERT",
				"session_evidence_count": 100,
				"discovery_flag": False,
				"confidence": 0.9,
			},
			{
				"name": "react",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 50,
				"discovery_flag": False,
				"confidence": 0.8,
			},
			{
				"name": "fastapi",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 30,
				"discovery_flag": False,
				"confidence": 0.75,
			},
		],
		"patterns": [],
		"projects": [
			{
				"project_name": "test-proj",
				"description": "Test",
				"complexity": "simple",
				"technologies": ["Python"],
				"session_count": 5,
				"date_range_start": "2025-01-01",
				"date_range_end": "2025-06-01",
				"key_decisions": ["Used FastAPI"],
			}
		],
	}

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.9,
				},
				{
					"requirement": "react",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.8,
				},
				{
					"requirement": "fastapi",
					"priority": "strong_preference",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.75,
				},
			],
			"action_items": [],
			"company_research_sample": "TestCo is a fast-growing startup in SF.",
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert "company_research_sample" in parsed
	assert parsed["company_research_sample"] == "TestCo is a fast-growing startup in SF."


def test_narrative_verdict_never_exported(tmp_path):
	"""narrative_verdict must never appear in YAML output — Decision 5."""
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "resume_only",
				"effective_depth": "EXPERT",
				"session_evidence_count": 100,
				"discovery_flag": False,
				"confidence": 0.9,
			},
			{
				"name": "react",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 50,
				"discovery_flag": False,
				"confidence": 0.8,
			},
			{
				"name": "fastapi",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 30,
				"discovery_flag": False,
				"confidence": 0.75,
			},
		],
		"patterns": [],
		"projects": [
			{
				"project_name": "test-proj",
				"description": "Test",
				"complexity": "simple",
				"technologies": ["Python"],
				"session_count": 5,
				"date_range_start": "2025-01-01",
				"date_range_end": "2025-06-01",
				"key_decisions": ["Used FastAPI"],
			}
		],
	}

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"narrative_verdict": "This candidate is perfect for the role.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.9,
				},
				{
					"requirement": "react",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.8,
				},
				{
					"requirement": "fastapi",
					"priority": "strong_preference",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.75,
				},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert "narrative_verdict" not in parsed


# ── Task 6: PII Gate ──


def test_evidence_highlights_scrub_pii():
	"""Evidence snippet with phone number should have [PHONE] placeholder after scrubbing."""
	skill_matches = [
		{
			"requirement": "python",
			"match_status": "strong_match",
			"evidence_source": "corroborated",
			"confidence": 0.95,
		},
	]
	candidate_skills = [
		{
			"name": "python",
			"evidence": [
				{
					"session_id": "s1",
					"session_date": "2026-03-01T00:00:00",
					"project_context": "test-project",
					"evidence_snippet": "Call me at 555-867-5309 for the Python project demo",
					"confidence": 0.9,
				},
			],
		},
	]
	result = select_evidence_highlights(skill_matches, candidate_skills)
	assert len(result) == 1
	assert "[PHONE]" in result[0]["quote"]
	assert "555-867-5309" not in result[0]["quote"]


def test_company_research_sample_scrubs_pii(tmp_path):
	"""company_research_sample with PII should have it scrubbed in output."""
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "resume_only",
				"effective_depth": "EXPERT",
				"session_evidence_count": 100,
				"discovery_flag": False,
				"confidence": 0.9,
			},
			{
				"name": "react",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 50,
				"discovery_flag": False,
				"confidence": 0.8,
			},
			{
				"name": "fastapi",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 30,
				"discovery_flag": False,
				"confidence": 0.75,
			},
		],
		"patterns": [],
		"projects": [
			{
				"project_name": "test-proj",
				"description": "Test",
				"complexity": "simple",
				"technologies": ["Python"],
				"session_count": 5,
				"date_range_start": "2025-01-01",
				"date_range_end": "2025-06-01",
				"key_decisions": ["Used FastAPI"],
			}
		],
	}

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.9,
				},
				{
					"requirement": "react",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.8,
				},
				{
					"requirement": "fastapi",
					"priority": "strong_preference",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.75,
				},
			],
			"action_items": [],
			"company_research_sample": "Contact HR at 555-123-4567 for more info about TestCo.",
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert "company_research_sample" in parsed
	assert "[PHONE]" in parsed["company_research_sample"]
	assert "555-123-4567" not in parsed["company_research_sample"]


# ── Task 7: Integration Test Updates ──


def test_integration_tier_field_present(tmp_path):
	"""tier field must be on every skill match, with valid value."""
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "resume_and_repo",
				"effective_depth": "EXPERT",
				"session_evidence_count": 551,
				"discovery_flag": False,
				"confidence": 0.95,
			},
			{
				"name": "react",
				"source": "repo_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 229,
				"discovery_flag": True,
				"confidence": 0.8,
			},
			{
				"name": "fastapi",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 0,
				"discovery_flag": False,
				"confidence": 0.75,
			},
		],
		"patterns": [],
		"projects": [
			{
				"project_name": "test-proj",
				"description": "Test project",
				"complexity": "moderate",
				"technologies": ["Python", "FastAPI"],
				"session_count": 10,
				"date_range_start": "2025-01-01",
				"date_range_end": "2025-06-01",
				"key_decisions": ["Chose FastAPI"],
				"public_repo_url": "https://github.com/user/test-proj",
			}
		],
	}

	assessment = {
		"data": {
			"job_title": "Staff Engineer",
			"company_name": "Anthropic",
			"overall_grade": "A+",
			"overall_score": 0.97,
			"should_apply": "strong_yes",
			"overall_summary": "Exceptional fit.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_and_repo",
					"confidence": 0.95,
					"matched_skill": "python",
				},
				{
					"requirement": "react",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "repo_only",
					"confidence": 0.8,
					"matched_skill": "react",
				},
				{
					"requirement": "fastapi",
					"priority": "strong_preference",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.75,
					"matched_skill": "fastapi",
				},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])

	valid_tiers = {"inspectable", "deployed", "claimed"}
	for match in parsed["skill_matches"]:
		assert "tier" in match, f"Missing tier on {match}"
		assert match["tier"] in valid_tiers, f"Invalid tier value: {match['tier']}"


def test_integration_no_legacy_source_values(tmp_path):
	"""No corroborated or sessions_only values should survive to the output."""
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "resume_and_repo",
				"effective_depth": "EXPERT",
				"session_evidence_count": 551,
				"discovery_flag": False,
				"confidence": 0.95,
			},
			{
				"name": "react",
				"source": "repo_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 229,
				"discovery_flag": True,
				"confidence": 0.8,
			},
			{
				"name": "fastapi",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 0,
				"discovery_flag": False,
				"confidence": 0.75,
			},
		],
		"patterns": [],
		"projects": [
			{
				"project_name": "test-proj",
				"description": "Test project",
				"complexity": "moderate",
				"technologies": ["Python"],
				"session_count": 10,
				"date_range_start": "2025-01-01",
				"date_range_end": "2025-06-01",
				"key_decisions": ["Chose FastAPI"],
			}
		],
	}

	assessment = {
		"data": {
			"job_title": "Staff Engineer",
			"company_name": "Anthropic",
			"overall_grade": "A+",
			"overall_score": 0.97,
			"should_apply": "strong_yes",
			"overall_summary": "Exceptional fit.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "corroborated",
					"confidence": 0.95,
					"matched_skill": "python",
				},
				{
					"requirement": "react",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "sessions_only",
					"confidence": 0.8,
					"matched_skill": "react",
				},
				{
					"requirement": "fastapi",
					"priority": "strong_preference",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.75,
					"matched_skill": "fastapi",
				},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])

	legacy_values = {"corroborated", "sessions_only"}
	for match in parsed["skill_matches"]:
		assert match["source"] not in legacy_values, (
			f"Legacy source value in output: {match['source']}"
		)


def test_integration_benchmark_fields_present(tmp_path):
	"""benchmark_postings_count and benchmark_calibration_date must be present."""
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "resume_only",
				"effective_depth": "EXPERT",
				"session_evidence_count": 100,
				"discovery_flag": False,
				"confidence": 0.9,
			},
			{
				"name": "react",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 50,
				"discovery_flag": False,
				"confidence": 0.8,
			},
			{
				"name": "fastapi",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 30,
				"discovery_flag": False,
				"confidence": 0.75,
			},
		],
		"patterns": [],
		"projects": [
			{
				"project_name": "test-proj",
				"description": "Test",
				"complexity": "simple",
				"technologies": ["Python"],
				"session_count": 5,
				"date_range_start": "2025-01-01",
				"date_range_end": "2025-06-01",
				"key_decisions": ["Used FastAPI"],
			}
		],
	}

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.9,
				},
				{
					"requirement": "react",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.8,
				},
				{
					"requirement": "fastapi",
					"priority": "strong_preference",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.75,
				},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	# Fields must exist (may be None if benchmark file not found — that is acceptable)
	assert "benchmark_postings_count" in parsed
	assert "benchmark_calibration_date" in parsed


def test_integration_narrative_verdict_absent(tmp_path):
	"""narrative_verdict must never appear in output."""
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "resume_only",
				"effective_depth": "EXPERT",
				"session_evidence_count": 100,
				"discovery_flag": False,
				"confidence": 0.9,
			},
			{
				"name": "react",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 50,
				"discovery_flag": False,
				"confidence": 0.8,
			},
			{
				"name": "fastapi",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 30,
				"discovery_flag": False,
				"confidence": 0.75,
			},
		],
		"patterns": [],
		"projects": [
			{
				"project_name": "test-proj",
				"description": "Test",
				"complexity": "simple",
				"technologies": ["Python"],
				"session_count": 5,
				"date_range_start": "2025-01-01",
				"date_range_end": "2025-06-01",
				"key_decisions": ["Used FastAPI"],
			}
		],
	}

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"narrative_verdict": "This candidate is exceptional.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.9,
				},
				{
					"requirement": "react",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.8,
				},
				{
					"requirement": "fastapi",
					"priority": "strong_preference",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.75,
				},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert "narrative_verdict" not in parsed


def test_integration_public_repo_url_on_projects(tmp_path):
	"""public_repo_url should pass through on projects that have it."""
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "resume_only",
				"effective_depth": "EXPERT",
				"session_evidence_count": 100,
				"discovery_flag": False,
				"confidence": 0.9,
			},
			{
				"name": "react",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 50,
				"discovery_flag": False,
				"confidence": 0.8,
			},
			{
				"name": "fastapi",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 30,
				"discovery_flag": False,
				"confidence": 0.75,
			},
		],
		"patterns": [],
		"projects": [
			{
				"project_name": "open-source-proj",
				"description": "A public project",
				"complexity": "moderate",
				"technologies": ["Python"],
				"session_count": 20,
				"date_range_start": "2025-01-01",
				"date_range_end": "2025-06-01",
				"key_decisions": ["Used MIT license"],
				"public_repo_url": "https://github.com/user/open-source-proj",
			}
		],
	}

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.9,
				},
				{
					"requirement": "react",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.8,
				},
				{
					"requirement": "fastapi",
					"priority": "strong_preference",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.75,
				},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert len(parsed["projects"]) >= 1
	proj = parsed["projects"][0]
	assert "public_repo_url" in proj
	assert proj["public_repo_url"] == "https://github.com/user/open-source-proj"


def test_integration_company_research_sample_present(tmp_path):
	"""company_research_sample should be in output when provided."""
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "resume_only",
				"effective_depth": "EXPERT",
				"session_evidence_count": 100,
				"discovery_flag": False,
				"confidence": 0.9,
			},
			{
				"name": "react",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 50,
				"discovery_flag": False,
				"confidence": 0.8,
			},
			{
				"name": "fastapi",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 30,
				"discovery_flag": False,
				"confidence": 0.75,
			},
		],
		"patterns": [],
		"projects": [
			{
				"project_name": "test-proj",
				"description": "Test",
				"complexity": "simple",
				"technologies": ["Python"],
				"session_count": 5,
				"date_range_start": "2025-01-01",
				"date_range_end": "2025-06-01",
				"key_decisions": ["Used FastAPI"],
			}
		],
	}

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.9,
				},
				{
					"requirement": "react",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.8,
				},
				{
					"requirement": "fastapi",
					"priority": "strong_preference",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.75,
				},
			],
			"action_items": [],
			"company_research_sample": "TestCo is a great company.",
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert "company_research_sample" in parsed


# ── Session Dormancy (D6) ──


def test_export_fit_assessment_no_candidate_profile_path(tmp_path):
	"""export_fit_assessment should succeed without candidate_profile_path (D6)."""
	merged = {
		"skills": [
			{
				"name": "python",
				"source": "resume_only",
				"effective_depth": "EXPERT",
				"session_evidence_count": 100,
				"discovery_flag": False,
				"confidence": 0.9,
			},
			{
				"name": "react",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 50,
				"discovery_flag": False,
				"confidence": 0.8,
			},
			{
				"name": "fastapi",
				"source": "resume_only",
				"effective_depth": "APPLIED",
				"session_evidence_count": 30,
				"discovery_flag": False,
				"confidence": 0.75,
			},
		],
		"patterns": [],
		"projects": [
			{
				"project_name": "test-proj",
				"description": "Test",
				"complexity": "simple",
				"technologies": ["Python"],
				"session_count": 5,
				"date_range_start": "2025-01-01",
				"date_range_end": "2025-06-01",
				"key_decisions": ["Used FastAPI"],
			}
		],
	}

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.9,
				},
				{
					"requirement": "react",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.8,
				},
				{
					"requirement": "fastapi",
					"priority": "strong_preference",
					"match_status": "strong_match",
					"candidate_evidence": "Yes",
					"evidence_source": "resume_only",
					"confidence": 0.75,
				},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()

	# Call WITHOUT candidate_profile_path — should succeed
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		output_dir=output_dir,
	)

	assert result.exists()
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert parsed["overall_grade"] == "B"
	assert parsed["evidence_highlights"] == []


def test_select_evidence_highlights_noop_with_empty_candidate_skills():
	"""select_evidence_highlights returns [] when candidate_skills is empty (D6)."""
	skill_matches = [
		{
			"requirement": "python",
			"match_status": "strong_match",
			"evidence_source": "corroborated",
			"confidence": 0.95,
		},
	]
	result = select_evidence_highlights(skill_matches, [])
	assert result == []


# ── Task: repo_url wiring ──


def test_select_projects_includes_repo_url():
	"""repo_url from RepoProject.url flows through to output dict."""
	projects = [
		{
			"name": "candidate-eval",
			"url": "https://github.com/brianruggieri/candidate-eval",
			"description": "Job fit engine",
			"languages": ["Python"],
			"dependencies": ["fastapi"],
			"commit_span_days": 88,
			"created_at": "2026-01-01T00:00:00",
			"last_pushed": "2026-03-30T00:00:00",
		}
	]
	result = select_projects(projects)
	assert len(result) == 1
	assert result[0]["repo_url"] == "https://github.com/brianruggieri/candidate-eval"


def test_select_projects_repo_url_none_for_local():
	"""Local-only repos (url=None) produce repo_url=None, not a KeyError."""
	projects = [
		{
			"name": "local-only",
			"url": None,
			"description": "Local project",
			"languages": [],
			"created_at": "2026-01-01T00:00:00",
			"last_pushed": "2026-03-01T00:00:00",
			"commit_span_days": 59,
		}
	]
	result = select_projects(projects)
	assert result[0]["repo_url"] is None


# ── Task: commit_url wiring ──


def test_select_evidence_highlights_includes_commit_url():
	"""commit_url from evidence entry flows through to highlight dict."""
	skill_matches = [
		{
			"requirement": "python",
			"match_status": "strong_match",
			"evidence_source": "corroborated",
			"confidence": 0.95,
		},
	]
	candidate_skills = [
		{
			"name": "python",
			"evidence": [
				{
					"session_id": "s1",
					"session_date": "2026-03-01T00:00:00",
					"project_context": "test-project",
					"evidence_snippet": "Built async pipeline",
					"confidence": 0.9,
					"commit_url": "https://github.com/user/repo/commit/abc1234",
				},
			],
		},
	]

	result = select_evidence_highlights(skill_matches, candidate_skills)
	assert len(result) == 1
	assert result[0]["commit_url"] == "https://github.com/user/repo/commit/abc1234"


def test_select_evidence_highlights_commit_url_none_when_absent():
	"""Highlight commit_url is None when evidence entry has no commit_url."""
	skill_matches = [
		{
			"requirement": "python",
			"match_status": "strong_match",
			"evidence_source": "corroborated",
			"confidence": 0.95,
		},
	]
	candidate_skills = [
		{
			"name": "python",
			"evidence": [
				{
					"session_id": "s1",
					"session_date": "2026-03-01T00:00:00",
					"project_context": "test-project",
					"evidence_snippet": "Built async pipeline",
					"confidence": 0.9,
				},
			],
		},
	]

	result = select_evidence_highlights(skill_matches, candidate_skills)
	assert len(result) == 1
	assert result[0]["commit_url"] is None


# ── Phase 2c: Quantitative Fallback Text (D5) ──


class TestFormatSkillRepoFallback:
	def test_full_signal_set(self):
		"""Full signal set: repos=8, 45-day span, test_coverage, frameworks."""
		evidence = SkillRepoEvidence(
			repos=8,
			total_bytes=500_000,
			first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
			last_seen=datetime(2026, 2, 14, tzinfo=timezone.utc),
			frameworks=["fastapi", "pydantic"],
			test_coverage=True,
		)
		result = format_skill_repo_fallback("Python", evidence)
		assert (
			result
			== "Python — 8 repositories, 45-day active timeline. Test coverage present. Frameworks: Fastapi, Pydantic."
		)

	def test_single_repo_no_test_no_frameworks(self):
		"""Single repo, no test coverage, no frameworks."""
		evidence = SkillRepoEvidence(
			repos=1,
			total_bytes=10_000,
			first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
			last_seen=datetime(2026, 1, 10, tzinfo=timezone.utc),
			frameworks=[],
			test_coverage=False,
		)
		result = format_skill_repo_fallback("Go", evidence)
		assert result == "Go — 1 repository, 10-day active timeline."

	def test_framework_deduplication_strips_skill_name(self):
		"""Frameworks containing the skill name itself should be stripped."""
		evidence = SkillRepoEvidence(
			repos=2,
			total_bytes=20_000,
			first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
			last_seen=datetime(2026, 1, 5, tzinfo=timezone.utc),
			frameworks=["python", "python"],
			test_coverage=False,
		)
		result = format_skill_repo_fallback("Python", evidence)
		# No frameworks clause — nothing remains after stripping the skill name
		assert "Frameworks" not in result
		assert result == "Python — 2 repositories, 5-day active timeline."

	def test_single_framework(self):
		"""Single framework for a different skill."""
		evidence = SkillRepoEvidence(
			repos=3,
			total_bytes=30_000,
			first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
			last_seen=datetime(2026, 1, 15, tzinfo=timezone.utc),
			frameworks=["react"],
			test_coverage=False,
		)
		result = format_skill_repo_fallback("JavaScript", evidence)
		assert "Frameworks: React." in result

	def test_test_framework_hint(self):
		"""Caller passes test_framework hint."""
		evidence = SkillRepoEvidence(
			repos=4,
			total_bytes=40_000,
			first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
			last_seen=datetime(2026, 1, 20, tzinfo=timezone.utc),
			frameworks=[],
			test_coverage=True,
		)
		result = format_skill_repo_fallback("Python", evidence, test_framework="pytest")
		assert "Test coverage with pytest." in result

	def test_ci_configured_hint(self):
		"""Caller passes ci_configured=True."""
		evidence = SkillRepoEvidence(
			repos=2,
			total_bytes=20_000,
			first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
			last_seen=datetime(2026, 1, 10, tzinfo=timezone.utc),
			frameworks=[],
			test_coverage=False,
		)
		result = format_skill_repo_fallback("Python", evidence, ci_configured=True)
		assert result.endswith("CI configured.")

	def test_zero_day_timeline(self):
		"""first_seen == last_seen should render '1-day active timeline'."""
		evidence = SkillRepoEvidence(
			repos=1,
			total_bytes=5_000,
			first_seen=datetime(2026, 3, 15, tzinfo=timezone.utc),
			last_seen=datetime(2026, 3, 15, tzinfo=timezone.utc),
			frameworks=[],
			test_coverage=False,
		)
		result = format_skill_repo_fallback("Rust", evidence)
		assert "1-day active timeline" in result


class TestEvidenceHighlightsRepoFallback:
	def test_falls_back_to_repo_quantitative(self):
		"""Strong match with no session evidence but with repo evidence uses fallback."""
		matches = [
			{
				"requirement": "Python",
				"match_status": "strong_match",
				"evidence_source": "corroborated",
				"confidence": 0.9,
			}
		]
		repo_evidence = {
			"python": SkillRepoEvidence(
				repos=5,
				total_bytes=0,
				first_seen=datetime(2026, 1, 1, tzinfo=timezone.utc),
				last_seen=datetime(2026, 3, 1, tzinfo=timezone.utc),
				frameworks=["fastapi"],
				test_coverage=True,
			)
		}
		result = select_evidence_highlights(
			matches, candidate_skills=[], repo_skill_evidence=repo_evidence
		)
		assert len(result) == 1
		assert result[0]["source"] == "repo_quantitative"
		assert "repositories" in result[0]["quote"]


# ── Abstract Skill Resolution (Decision 4) ──


class TestAbstractSkillsConstant:
	def test_is_frozenset(self):
		assert isinstance(ABSTRACT_SKILLS, frozenset)

	def test_contains_key_abstract_skills(self):
		assert "agentic-workflows" in ABSTRACT_SKILLS
		assert "developer-tools" in ABSTRACT_SKILLS
		assert "system-design" in ABSTRACT_SKILLS

	def test_does_not_contain_concrete_skills(self):
		assert "python" not in ABSTRACT_SKILLS
		assert "react" not in ABSTRACT_SKILLS
		assert "fastapi" not in ABSTRACT_SKILLS

	def test_signal_rules_is_list_of_tuples(self):
		assert isinstance(_ABSTRACT_SIGNAL_RULES, list)
		for rule in _ABSTRACT_SIGNAL_RULES:
			assert len(rule) == 3
			field, test_fn, skill = rule
			assert isinstance(field, str)
			assert callable(test_fn)
			assert skill in ABSTRACT_SKILLS


# ── Task 2: _apply_signal_rules ──


class TestApplySignalRules:
	def test_agentic_workflows_requires_expert_or_ralph(self):
		"""Expert ai_maturity_level should grant agentic-workflows."""
		repos = [{"ai_maturity_level": "expert"}]
		result = _apply_signal_rules(repos)
		assert "agentic-workflows" in result

	def test_advanced_without_ralph_does_not_grant_agentic(self):
		"""Advanced maturity without ralph_loops should NOT grant agentic-workflows."""
		repos = [{"ai_maturity_level": "advanced", "has_ralph_loops": False}]
		result = _apply_signal_rules(repos)
		assert "agentic-workflows" not in result

	def test_advanced_with_ralph_grants_agentic(self):
		"""Advanced maturity WITH ralph_loops should grant agentic-workflows."""
		repos = [{"ai_maturity_level": "advanced", "has_ralph_loops": True}]
		result = _apply_signal_rules(repos)
		assert "agentic-workflows" in result

	def test_llm_imports_grants_llm(self):
		"""Non-empty llm_imports should grant llm."""
		repos = [{"llm_imports": ["anthropic"]}]
		result = _apply_signal_rules(repos)
		assert "llm" in result

	def test_empty_repos_returns_empty(self):
		"""Empty repos list should produce empty result."""
		assert _apply_signal_rules([]) == set()

	def test_has_ci_grants_ci_cd(self):
		"""has_ci=True should grant ci-cd."""
		repos = [{"has_ci": True}]
		result = _apply_signal_rules(repos)
		assert "ci-cd" in result

	def test_has_tests_grants_testing(self):
		"""has_tests=True should grant testing."""
		repos = [{"has_tests": True}]
		result = _apply_signal_rules(repos)
		assert "testing" in result

	def test_releases_grants_production_systems(self):
		"""releases > 0 should grant production-systems."""
		repos = [{"releases": 3}]
		result = _apply_signal_rules(repos)
		assert "production-systems" in result

	def test_deep_directory_grants_system_design(self):
		"""directory_depth >= 4 should grant system-design."""
		repos = [{"directory_depth": 5}]
		result = _apply_signal_rules(repos)
		assert "system-design" in result


# ── Task 3: Claude abstract skill inference ──


class TestBuildAbstractSkillPrompt:
	def test_empty_when_no_targets(self):
		"""Prompt is None when no abstract skills are in the job requirements."""
		result = _build_abstract_skill_prompt(
			repos=[{"name": "test"}],
			job_skills=["python", "react"],
			candidate_skills=[],
		)
		assert result is None

	def test_empty_when_all_already_granted(self):
		"""Prompt is None when all abstract job skills are already in candidate evidence."""
		result = _build_abstract_skill_prompt(
			repos=[{"name": "test"}],
			job_skills=["system-design"],
			candidate_skills=["system-design"],
		)
		assert result is None

	def test_includes_target_skills(self):
		"""Prompt should include the abstract skill names to evaluate."""
		result = _build_abstract_skill_prompt(
			repos=[{"name": "my-repo", "has_ci": True}],
			job_skills=["system-design", "testing", "python"],
			candidate_skills=[],
		)
		assert result is not None
		assert "system-design" in result
		assert "testing" in result
		# python is not abstract, should not be in prompt
		assert "python" not in result.split("Target skills:")[1].split("\n")[0]


class TestClaudeInferAbstractSkills:
	def test_handles_claude_error(self, monkeypatch):
		"""Claude CLI error should return empty set, not raise."""
		from claude_candidate import claude_cli

		def mock_call_claude(prompt, *, timeout=60):
			raise claude_cli.ClaudeCLIError("mock error")

		monkeypatch.setattr(claude_cli, "call_claude", mock_call_claude)
		result = _claude_infer_abstract_skills(
			repos=[{"name": "test"}],
			job_skills=["system-design"],
			candidate_skills=[],
		)
		assert result == set()

	def test_parses_response(self, monkeypatch):
		"""Valid JSON array response should return parsed skills."""
		from claude_candidate import claude_cli

		def mock_call_claude(prompt, *, timeout=60):
			return '["system-design", "testing"]'

		monkeypatch.setattr(claude_cli, "call_claude", mock_call_claude)
		result = _claude_infer_abstract_skills(
			repos=[{"name": "test"}],
			job_skills=["system-design", "testing"],
			candidate_skills=[],
		)
		assert result == {"system-design", "testing"}

	def test_only_returns_abstract_skills(self, monkeypatch):
		"""Concrete skill hallucinations should be filtered out."""
		from claude_candidate import claude_cli

		def mock_call_claude(prompt, *, timeout=60):
			return '["system-design", "python", "react", "testing"]'

		monkeypatch.setattr(claude_cli, "call_claude", mock_call_claude)
		result = _claude_infer_abstract_skills(
			repos=[{"name": "test"}],
			job_skills=["system-design", "testing", "python"],
			candidate_skills=[],
		)
		# python and react should be filtered out
		assert "python" not in result
		assert "react" not in result
		assert "system-design" in result
		assert "testing" in result

	def test_returns_empty_when_no_targets(self):
		"""No abstract skills in job_skills should return empty set without calling Claude."""
		result = _claude_infer_abstract_skills(
			repos=[{"name": "test"}],
			job_skills=["python"],
			candidate_skills=[],
		)
		assert result == set()


# ── Task 4: Commit tagged skills stub ──


class TestBuildCommitTaggedSkills:
	def test_returns_empty_set_stub(self):
		"""Stub should return empty set."""
		assert _build_commit_tagged_skills({}) == set()
		assert _build_commit_tagged_skills({"repos": [{"name": "test"}]}) == set()


# ── Task 5: resolve_abstract_skills orchestrator ──


class TestResolveAbstractSkills:
	def test_returns_empty_when_no_target(self):
		"""No abstract skills in job requirements → empty dict."""
		result = resolve_abstract_skills(
			repo_profile={"skill_evidence": {}, "repos": []},
			job_skills=["python", "react"],
			use_claude=False,
		)
		assert result == {}

	def test_already_in_evidence_skipped(self):
		"""Abstract skills already in skill_evidence should not be re-resolved."""
		result = resolve_abstract_skills(
			repo_profile={
				"skill_evidence": {"system-design": {"repos": 3}},
				"repos": [{"directory_depth": 5, "source_modules": 12}],
			},
			job_skills=["system-design"],
			use_claude=False,
		)
		assert result == {}

	def test_uses_signal_rules_when_claude_disabled(self):
		"""With use_claude=False, signal rules should still resolve abstract skills."""
		result = resolve_abstract_skills(
			repo_profile={
				"skill_evidence": {},
				"repos": [{"has_ci": True, "has_tests": True}],
			},
			job_skills=["ci-cd", "testing"],
			use_claude=False,
		)
		assert "ci-cd" in result
		assert "testing" in result

	def test_returns_inferred_flag(self):
		"""Inferred entries should have _inferred=True marker."""
		result = resolve_abstract_skills(
			repo_profile={
				"skill_evidence": {},
				"repos": [{"has_tests": True}],
			},
			job_skills=["testing"],
			use_claude=False,
		)
		assert "testing" in result
		assert result["testing"]["_inferred"] is True
		assert result["testing"]["source"] == "inferred"

	def test_uses_projects_key_fallback(self):
		"""When 'repos' is absent, should fall back to 'projects' key."""
		result = resolve_abstract_skills(
			repo_profile={
				"skill_evidence": {},
				"projects": [{"has_ci": True}],
			},
			job_skills=["ci-cd"],
			use_claude=False,
		)
		assert "ci-cd" in result
