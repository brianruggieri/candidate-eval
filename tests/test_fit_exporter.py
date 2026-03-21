import json

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
	assert generate_slug("Senior Staff Software Development Engineer in Test", "Amazon") == "staff-engineer-amazon"


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


def _make_skill_match(requirement, priority, match_status, evidence_source="corroborated", confidence=0.8):
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
	assert "K8s" in requirements
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
	patterns = [{"pattern_type": f"pattern_{i}", "strength": "strong", "frequency": "common"} for i in range(8)]
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
			{"skill": "Python", "status": "strong_match", "priority": "must_have",
			 "depth": "Expert", "sessions": 551, "source": "corroborated", "discovery": False},
		],
		"evidence_highlights": [],
		"patterns": [{"name": "Architecture First", "strength": "Exceptional", "frequency": "Dominant"}],
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
			{"pattern_type": "architecture_first", "strength": "exceptional", "frequency": "dominant"},
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
	merged_path = tmp_path / "merged_profile.json"
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
		"should_apply": True,
		"data": {
			"job_title": "Staff Engineer",
			"company_name": "Anthropic",
			"posting_url": "https://example.com/jobs/123",
			"overall_grade": "A+",
			"overall_score": 0.97,
			"should_apply": "strong_yes",
			"overall_summary": "Exceptional fit.",
			"skill_matches": [
				{
					"requirement": "python",
					"priority": "must_have",
					"match_status": "strong_match",
					"candidate_evidence": "Expert Python developer",
					"evidence_source": "corroborated",
					"confidence": 0.95,
				},
				{
					"requirement": "kubernetes",
					"priority": "must_have",
					"match_status": "no_evidence",
					"candidate_evidence": "Adjacent experience with Docker",
					"evidence_source": "resume_only",
					"confidence": 0.1,
				},
			],
			"action_items": ["Learn Kubernetes for container orchestration"],
		},
	}

	output_dir = tmp_path / "content" / "fit"
	output_dir.mkdir(parents=True)

	result = export_fit_assessment(
		assessment,
		merged_profile_path=merged_path,
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
	assert parsed["skill_matches"][0]["skill"] == "python"
	assert len(parsed["gaps"]) >= 1
	assert parsed["gaps"][0]["requirement"] == "kubernetes"
