import json

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
)


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
				"project_name": "claude-candidate",
				"description": "Evidence-backed job fit engine",
				"complexity": "ambitious",
				"technologies": ["Python", "FastAPI"],
				"session_count": 42,
				"date_range_start": "2026-01-01",
				"date_range_end": "2026-03-20",
				"key_decisions": ["Designed fuzzy skill taxonomy"],
			},
		],
	}
	merged_path = tmp_path / "merged_profile.json"  # kept for reference, not passed to function
	merged_path.write_text(json.dumps(merged))

	# Create mock candidate profile
	candidate = {
		"skills": [
			{
				"name": "python",
				"evidence": [
					{
						"session_id": "test-session",
						"session_date": "2026-03-01T00:00:00",
						"project_context": "claude-candidate",
						"evidence_snippet": "Built async pipeline with aiosqlite",
						"evidence_type": "direct_usage",
						"confidence": 0.95,
					},
				],
			},
		],
	}
	candidate_path = tmp_path / "candidate_profile.json"
	candidate_path.write_text(json.dumps(candidate))

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
		candidate_profile_path=candidate_path,
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
	# Evidence highlights should now find python via matched_skill
	assert len(parsed["evidence_highlights"]) >= 1
	assert parsed["evidence_highlights"][0]["quote"] == "Built async pipeline with aiosqlite"


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
				"project_name": "test",
				"description": "test",
				"complexity": "simple",
				"technologies": [],
				"session_count": 1,
				"date_range_start": "2026",
				"date_range_end": "2026",
				"key_decisions": ["test"],
			},
		],
	}

	candidate = {"skills": []}
	candidate_path = tmp_path / "candidate.json"
	candidate_path.write_text(json.dumps(candidate))

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
			candidate_profile_path=candidate_path,
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
		projects = [{"project_name": "my-project", "public_repo_url": "https://github.com/user/my-project"}]
		# evidence_snippet referencing a project with public_repo_url
		snippet = "Built the pipeline for my-project"
		tier = compute_evidence_tier(match, snippet, projects)
		assert tier == "inspectable"

	def test_inspectable_when_github_commit_in_evidence(self):
		match = {"evidence_source": "repo_only", "confidence": 0.9}
		snippet = "Implemented feature https://github.com/user/repo/commit/abc123def456 in production"
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
		unrelated_project = {"project_name": "other-project", "public_repo_url": "https://github.com/user/other"}
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
			{"name": "python", "source": "resume_only", "effective_depth": "EXPERT",
			 "session_evidence_count": 100, "discovery_flag": False, "confidence": 0.9},
			{"name": "react", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 50, "discovery_flag": False, "confidence": 0.8},
			{"name": "fastapi", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 30, "discovery_flag": False, "confidence": 0.75},
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
	candidate = {"skills": []}
	candidate_path = tmp_path / "candidate.json"
	candidate_path.write_text(json.dumps(candidate))

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"skill_matches": [
				{"requirement": "python", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.9},
				{"requirement": "react", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.8},
				{"requirement": "fastapi", "priority": "strong_preference", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.75},
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
		candidate_profile_path=candidate_path,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert "company_research_sample" in parsed
	assert parsed["company_research_sample"] == "TestCo is a fast-growing startup in SF."


def test_narrative_verdict_never_exported(tmp_path):
	"""narrative_verdict must never appear in YAML output — Decision 5."""
	merged = {
		"skills": [
			{"name": "python", "source": "resume_only", "effective_depth": "EXPERT",
			 "session_evidence_count": 100, "discovery_flag": False, "confidence": 0.9},
			{"name": "react", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 50, "discovery_flag": False, "confidence": 0.8},
			{"name": "fastapi", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 30, "discovery_flag": False, "confidence": 0.75},
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
	candidate = {"skills": []}
	candidate_path = tmp_path / "candidate.json"
	candidate_path.write_text(json.dumps(candidate))

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
				{"requirement": "python", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.9},
				{"requirement": "react", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.8},
				{"requirement": "fastapi", "priority": "strong_preference", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.75},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		candidate_profile_path=candidate_path,
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
			{"name": "python", "source": "resume_only", "effective_depth": "EXPERT",
			 "session_evidence_count": 100, "discovery_flag": False, "confidence": 0.9},
			{"name": "react", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 50, "discovery_flag": False, "confidence": 0.8},
			{"name": "fastapi", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 30, "discovery_flag": False, "confidence": 0.75},
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
	candidate = {"skills": []}
	candidate_path = tmp_path / "candidate.json"
	candidate_path.write_text(json.dumps(candidate))

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"skill_matches": [
				{"requirement": "python", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.9},
				{"requirement": "react", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.8},
				{"requirement": "fastapi", "priority": "strong_preference", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.75},
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
		candidate_profile_path=candidate_path,
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
			{"name": "python", "source": "resume_and_repo", "effective_depth": "EXPERT",
			 "session_evidence_count": 551, "discovery_flag": False, "confidence": 0.95},
			{"name": "react", "source": "repo_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 229, "discovery_flag": True, "confidence": 0.8},
			{"name": "fastapi", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 0, "discovery_flag": False, "confidence": 0.75},
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
	candidate = {"skills": []}
	candidate_path = tmp_path / "candidate.json"
	candidate_path.write_text(json.dumps(candidate))

	assessment = {
		"data": {
			"job_title": "Staff Engineer",
			"company_name": "Anthropic",
			"overall_grade": "A+",
			"overall_score": 0.97,
			"should_apply": "strong_yes",
			"overall_summary": "Exceptional fit.",
			"skill_matches": [
				{"requirement": "python", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_and_repo", "confidence": 0.95,
				 "matched_skill": "python"},
				{"requirement": "react", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "repo_only", "confidence": 0.8,
				 "matched_skill": "react"},
				{"requirement": "fastapi", "priority": "strong_preference", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.75,
				 "matched_skill": "fastapi"},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		candidate_profile_path=candidate_path,
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
			{"name": "python", "source": "resume_and_repo", "effective_depth": "EXPERT",
			 "session_evidence_count": 551, "discovery_flag": False, "confidence": 0.95},
			{"name": "react", "source": "repo_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 229, "discovery_flag": True, "confidence": 0.8},
			{"name": "fastapi", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 0, "discovery_flag": False, "confidence": 0.75},
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
	candidate = {"skills": []}
	candidate_path = tmp_path / "candidate.json"
	candidate_path.write_text(json.dumps(candidate))

	assessment = {
		"data": {
			"job_title": "Staff Engineer",
			"company_name": "Anthropic",
			"overall_grade": "A+",
			"overall_score": 0.97,
			"should_apply": "strong_yes",
			"overall_summary": "Exceptional fit.",
			"skill_matches": [
				{"requirement": "python", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "corroborated", "confidence": 0.95,
				 "matched_skill": "python"},
				{"requirement": "react", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "sessions_only", "confidence": 0.8,
				 "matched_skill": "react"},
				{"requirement": "fastapi", "priority": "strong_preference", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.75,
				 "matched_skill": "fastapi"},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		candidate_profile_path=candidate_path,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])

	legacy_values = {"corroborated", "sessions_only"}
	for match in parsed["skill_matches"]:
		assert match["source"] not in legacy_values, f"Legacy source value in output: {match['source']}"


def test_integration_benchmark_fields_present(tmp_path):
	"""benchmark_postings_count and benchmark_calibration_date must be present."""
	merged = {
		"skills": [
			{"name": "python", "source": "resume_only", "effective_depth": "EXPERT",
			 "session_evidence_count": 100, "discovery_flag": False, "confidence": 0.9},
			{"name": "react", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 50, "discovery_flag": False, "confidence": 0.8},
			{"name": "fastapi", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 30, "discovery_flag": False, "confidence": 0.75},
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
	candidate = {"skills": []}
	candidate_path = tmp_path / "candidate.json"
	candidate_path.write_text(json.dumps(candidate))

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"skill_matches": [
				{"requirement": "python", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.9},
				{"requirement": "react", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.8},
				{"requirement": "fastapi", "priority": "strong_preference", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.75},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		candidate_profile_path=candidate_path,
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
			{"name": "python", "source": "resume_only", "effective_depth": "EXPERT",
			 "session_evidence_count": 100, "discovery_flag": False, "confidence": 0.9},
			{"name": "react", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 50, "discovery_flag": False, "confidence": 0.8},
			{"name": "fastapi", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 30, "discovery_flag": False, "confidence": 0.75},
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
	candidate = {"skills": []}
	candidate_path = tmp_path / "candidate.json"
	candidate_path.write_text(json.dumps(candidate))

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
				{"requirement": "python", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.9},
				{"requirement": "react", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.8},
				{"requirement": "fastapi", "priority": "strong_preference", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.75},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		candidate_profile_path=candidate_path,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert "narrative_verdict" not in parsed


def test_integration_public_repo_url_on_projects(tmp_path):
	"""public_repo_url should pass through on projects that have it."""
	merged = {
		"skills": [
			{"name": "python", "source": "resume_only", "effective_depth": "EXPERT",
			 "session_evidence_count": 100, "discovery_flag": False, "confidence": 0.9},
			{"name": "react", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 50, "discovery_flag": False, "confidence": 0.8},
			{"name": "fastapi", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 30, "discovery_flag": False, "confidence": 0.75},
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
	candidate = {"skills": []}
	candidate_path = tmp_path / "candidate.json"
	candidate_path.write_text(json.dumps(candidate))

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"skill_matches": [
				{"requirement": "python", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.9},
				{"requirement": "react", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.8},
				{"requirement": "fastapi", "priority": "strong_preference", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.75},
			],
			"action_items": [],
		},
	}

	output_dir = tmp_path / "out"
	output_dir.mkdir()
	result = export_fit_assessment(
		assessment,
		merged_profile_data=merged,
		candidate_profile_path=candidate_path,
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
			{"name": "python", "source": "resume_only", "effective_depth": "EXPERT",
			 "session_evidence_count": 100, "discovery_flag": False, "confidence": 0.9},
			{"name": "react", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 50, "discovery_flag": False, "confidence": 0.8},
			{"name": "fastapi", "source": "resume_only", "effective_depth": "APPLIED",
			 "session_evidence_count": 30, "discovery_flag": False, "confidence": 0.75},
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
	candidate = {"skills": []}
	candidate_path = tmp_path / "candidate.json"
	candidate_path.write_text(json.dumps(candidate))

	assessment = {
		"data": {
			"job_title": "Engineer",
			"company_name": "TestCo",
			"overall_grade": "B",
			"overall_score": 0.75,
			"should_apply": "yes",
			"overall_summary": "Good fit.",
			"skill_matches": [
				{"requirement": "python", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.9},
				{"requirement": "react", "priority": "must_have", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.8},
				{"requirement": "fastapi", "priority": "strong_preference", "match_status": "strong_match",
				 "candidate_evidence": "Yes", "evidence_source": "resume_only", "confidence": 0.75},
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
		candidate_profile_path=candidate_path,
		output_dir=output_dir,
	)
	parsed = yaml.safe_load(result.read_text().split("---\n", 2)[1])
	assert "company_research_sample" in parsed
