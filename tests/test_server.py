"""Tests for the FastAPI backend server."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from asgi_lifespan import LifespanManager
from httpx import ASGITransport, AsyncClient

from claude_candidate.server import create_app
from claude_candidate import __version__


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path):
	"""App with no profiles loaded."""
	return create_app(data_dir=tmp_path)


@pytest.fixture
def app_with_profile(
	tmp_path: Path,
	sample_candidate_profile_json: str,
	sample_resume_profile_json: str,
):
	"""App with candidate and resume profiles written to data_dir."""
	(tmp_path / "candidate_profile.json").write_text(sample_candidate_profile_json)
	(tmp_path / "resume_profile.json").write_text(sample_resume_profile_json)
	return create_app(data_dir=tmp_path)


@pytest.fixture
async def client(app):
	async with LifespanManager(app) as manager:
		transport = ASGITransport(app=manager.app)
		async with AsyncClient(transport=transport, base_url="http://test") as c:
			yield c


@pytest.fixture
async def client_with_profile(app_with_profile):
	async with LifespanManager(app_with_profile) as manager:
		transport = ASGITransport(app=manager.app)
		async with AsyncClient(transport=transport, base_url="http://test") as c:
			yield c


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


class TestHealthEndpoint:
	async def test_health_returns_200(self, client: AsyncClient):
		resp = await client.get("/api/health")
		assert resp.status_code == 200

	async def test_health_has_required_fields(self, client: AsyncClient):
		resp = await client.get("/api/health")
		data = resp.json()
		assert data["status"] == "ok"
		assert data["version"] == __version__
		assert "profile_loaded" in data

	async def test_health_profile_loaded_false_without_profile(self, client: AsyncClient):
		resp = await client.get("/api/health")
		assert resp.json()["profile_loaded"] is False

	async def test_health_profile_loaded_true_with_profile(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.get("/api/health")
		assert resp.json()["profile_loaded"] is True


# ---------------------------------------------------------------------------
# Profile status
# ---------------------------------------------------------------------------


class TestProfileStatus:
	async def test_no_profile_shows_all_false(self, client: AsyncClient):
		resp = await client.get("/api/profile/status")
		assert resp.status_code == 200
		data = resp.json()
		assert data["has_candidate_profile"] is False
		assert data["has_resume_profile"] is False
		assert data["has_curated_resume"] is False
		assert data["merge_available"] is False
		assert data["hashes"] == {}

	async def test_with_profiles_shows_loaded(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.get("/api/profile/status")
		assert resp.status_code == 200
		data = resp.json()
		assert data["has_candidate_profile"] is True
		assert data["has_resume_profile"] is True
		# merge_available is true whenever candidate profile is present
		assert data["merge_available"] is True
		assert "candidate" in data["hashes"]
		assert "resume" in data["hashes"]


# ---------------------------------------------------------------------------
# Mtime-based cache
# ---------------------------------------------------------------------------


class TestMtimeCache:
	"""Verify that get_profiles() picks up file changes without a server restart."""

	@pytest.fixture
	def data_dir(self, tmp_path: Path, sample_candidate_profile_json: str):
		"""Return tmp_path with a candidate_profile.json already written."""
		(tmp_path / "candidate_profile.json").write_text(sample_candidate_profile_json)
		return tmp_path

	@pytest.fixture
	async def client_and_dir(self, data_dir: Path):
		"""Client whose data_dir is exposed for in-test file manipulation."""
		app = create_app(data_dir=data_dir)
		async with LifespanManager(app) as manager:
			transport = ASGITransport(app=manager.app)
			async with AsyncClient(transport=transport, base_url="http://test") as c:
				yield c, data_dir

	async def test_profile_reload_on_file_change(self, client_and_dir):
		"""Modifying a profile file mid-request is picked up on the next call."""
		client, data_dir = client_and_dir

		# First request — caches initial data
		resp1 = await client.get("/api/profile/status")
		assert resp1.json()["has_candidate_profile"] is True
		hash1 = resp1.json()["hashes"]["candidate"]

		# Overwrite the file with a slightly different dict to change its content + mtime
		import os

		new_data = {"skills": [], "_marker": "updated"}
		(data_dir / "candidate_profile.json").write_text(json.dumps(new_data))
		# Force a distinct mtime_ns to avoid flakiness on coarse-resolution filesystems
		future_ns = (data_dir / "candidate_profile.json").stat().st_mtime_ns + 1_000_000_000
		os.utime(data_dir / "candidate_profile.json", ns=(future_ns, future_ns))

		# Second request — should detect the new mtime and reload
		resp2 = await client.get("/api/profile/status")
		hash2 = resp2.json()["hashes"]["candidate"]
		assert hash1 != hash2, "Hash should change after file update"

	async def test_profile_removed_from_cache_when_file_deleted(self, client_and_dir):
		"""Deleting a profile file removes it from the cache on the next request."""
		client, data_dir = client_and_dir

		resp1 = await client.get("/api/profile/status")
		assert resp1.json()["has_candidate_profile"] is True

		(data_dir / "candidate_profile.json").unlink()

		resp2 = await client.get("/api/profile/status")
		assert resp2.json()["has_candidate_profile"] is False

	async def test_new_profile_file_picked_up(
		self, client_and_dir, sample_resume_profile_json: str
	):
		"""A profile file created after startup is picked up on the next request."""
		client, data_dir = client_and_dir

		resp1 = await client.get("/api/profile/status")
		assert resp1.json()["has_resume_profile"] is False

		(data_dir / "resume_profile.json").write_text(sample_resume_profile_json)

		resp2 = await client.get("/api/profile/status")
		assert resp2.json()["has_resume_profile"] is True

	async def test_corrupt_file_keeps_stale_data(self, client_and_dir):
		"""A corrupt JSON file keeps the last good cached data and doesn't crash."""
		import time

		client, data_dir = client_and_dir

		resp1 = await client.get("/api/profile/status")
		assert resp1.json()["has_candidate_profile"] is True
		hash1 = resp1.json()["hashes"]["candidate"]

		time.sleep(0.01)  # ensure mtime differs
		(data_dir / "candidate_profile.json").write_text("{ invalid json !!!")

		resp2 = await client.get("/api/profile/status")
		# Stale data is preserved — still present, same hash
		assert resp2.json()["has_candidate_profile"] is True
		assert resp2.json()["hashes"]["candidate"] == hash1


# ---------------------------------------------------------------------------
# Assess endpoint
# ---------------------------------------------------------------------------


SAMPLE_POSTING = """
We are looking for a Senior Python Engineer to join our backend team.
Requirements:
- 5+ years of Python experience (required)
- Strong knowledge of REST APIs (required)
- Experience with Docker and Kubernetes (preferred)
- Familiarity with LLMs or AI tooling (nice to have)
"""

SAMPLE_ASSESS_PAYLOAD = {
	"posting_text": SAMPLE_POSTING,
	"company": "Acme Corp",
	"title": "Senior Python Engineer",
	"seniority": "senior",
	"requirements": [
		{
			"description": "5+ years of Python experience",
			"skill_mapping": ["python"],
			"priority": "must_have",
			"source_text": "5+ years of Python",
		},
		{
			"description": "Experience with FastAPI or Django",
			"skill_mapping": ["fastapi", "django"],
			"priority": "must_have",
			"source_text": "FastAPI or Django",
		},
	],
}


class TestAssessEndpoint:
	async def test_assess_without_profile_returns_422(self, client: AsyncClient):
		resp = await client.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		assert resp.status_code == 422

	async def test_assess_with_profile_returns_200(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		assert resp.status_code == 200

	async def test_assess_returns_valid_assessment_fields(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		data = resp.json()
		assert "assessment_id" in data
		assert "overall_score" in data
		assert "overall_grade" in data
		assert "should_apply" in data
		assert "skill_match" in data
		assert "mission_alignment" in data
		assert "culture_fit" in data

	async def test_assess_company_name_matches(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		data = resp.json()
		assert data["company_name"] == "Acme Corp"
		assert data["job_title"] == "Senior Python Engineer"

	async def test_assess_persists_to_store(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		assessment_id = resp.json()["assessment_id"]

		# Retrieve via GET
		get_resp = await client_with_profile.get(f"/api/assessments/{assessment_id}")
		assert get_resp.status_code == 200
		assert get_resp.json()["assessment_id"] == assessment_id

	async def test_assess_with_explicit_requirements(self, client_with_profile: AsyncClient):
		payload = {
			**SAMPLE_ASSESS_PAYLOAD,
			"requirements": [
				{
					"description": "Python proficiency",
					"skill_mapping": ["python"],
					"priority": "must_have",
					"source_text": "5+ years of Python experience (required)",
				}
			],
		}
		resp = await client_with_profile.post("/api/assess", json=payload)
		assert resp.status_code == 200
		data = resp.json()
		assert len(data["skill_matches"]) >= 1

	async def test_assess_with_posting_url(self, client_with_profile: AsyncClient):
		payload = {**SAMPLE_ASSESS_PAYLOAD, "posting_url": "https://acme.io/jobs/123"}
		resp = await client_with_profile.post("/api/assess", json=payload)
		data = resp.json()
		assert data["posting_url"] == "https://acme.io/jobs/123"

	async def test_assess_overall_score_in_range(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		score = resp.json()["overall_score"]
		assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# Partial assess endpoint
# ---------------------------------------------------------------------------


class TestAssessPartialEndpoint:
	async def test_assess_partial_without_profile_returns_422(self, client: AsyncClient):
		resp = await client.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		assert resp.status_code == 422

	async def test_assess_partial_with_profile_returns_200(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		assert resp.status_code == 200

	async def test_assess_partial_returns_assessment_fields(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		data = resp.json()
		assert "assessment_id" in data
		assert "overall_score" in data
		assert "overall_grade" in data
		assert "should_apply" in data
		assert "skill_match" in data

	async def test_assess_partial_persists_to_store(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = resp.json()["assessment_id"]
		get_resp = await client_with_profile.get(f"/api/assessments/{aid}")
		assert get_resp.status_code == 200
		assert get_resp.json()["assessment_id"] == aid

	async def test_assess_partial_no_deliverables_key(self, client_with_profile: AsyncClient):
		"""Partial endpoint must NOT return deliverables (those require Claude)."""
		resp = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		assert "deliverables" not in resp.json()


# ---------------------------------------------------------------------------
# Full assess endpoint
# ---------------------------------------------------------------------------


@pytest.mark.slow
class TestAssessFullEndpoint:
	async def test_assess_full_not_found_returns_404(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post(
			"/api/assess/full", json={"assessment_id": "nonexistent"}
		)
		assert resp.status_code == 404

	async def test_assess_full_returns_full_phase(self, client_with_profile: AsyncClient):
		"""Full assessment should set assessment_phase to 'full'."""
		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		with patch(
			"claude_candidate.company_research.research_company",
			return_value={
				"mission": "Making developer tools better",
				"values": ["innovation", "quality"],
				"culture_signals": ["collaborative", "remote-friendly"],
				"tech_philosophy": "Python-first, test-driven",
				"ai_native": False,
				"product_domains": ["developer-tooling"],
				"team_size_signal": "mid-size (50-500)",
			},
		):
			resp = await client_with_profile.post("/api/assess/full", json={"assessment_id": aid})

		assert resp.status_code == 200
		data = resp.json()
		assert data["assessment_phase"] == "full"

	async def test_assess_full_has_mission_and_culture(self, client_with_profile: AsyncClient):
		"""Full assessment should populate mission_alignment and culture_fit."""
		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		with patch(
			"claude_candidate.company_research.research_company",
			return_value={
				"mission": "Building the future of work",
				"values": ["transparency", "impact"],
				"culture_signals": ["async communication", "documentation driven"],
				"tech_philosophy": "Microservices, Python, Docker",
				"ai_native": True,
				"product_domains": ["enterprise-software"],
				"team_size_signal": "startup (<50)",
			},
		):
			resp = await client_with_profile.post("/api/assess/full", json={"assessment_id": aid})

		data = resp.json()
		assert data["mission_alignment"] is not None
		assert "score" in data["mission_alignment"]
		assert "grade" in data["mission_alignment"]
		assert data["culture_fit"] is not None
		assert "score" in data["culture_fit"]
		assert "grade" in data["culture_fit"]

	async def test_assess_full_no_deliverables(self, client_with_profile: AsyncClient):
		"""Full assessment should NOT include a deliverables key."""
		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		with patch(
			"claude_candidate.company_research.research_company",
			return_value={
				"mission": "Test company",
				"values": [],
				"culture_signals": [],
				"tech_philosophy": "",
				"ai_native": False,
				"product_domains": [],
				"team_size_signal": "",
			},
		):
			resp = await client_with_profile.post("/api/assess/full", json={"assessment_id": aid})

		data = resp.json()
		assert "deliverables" not in data

	async def test_assess_full_has_letter_grade(self, client_with_profile: AsyncClient):
		"""Full assessment should have an overall letter grade."""
		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		with patch(
			"claude_candidate.company_research.research_company",
			return_value={
				"mission": "AI research company",
				"values": ["excellence"],
				"culture_signals": ["fast-paced"],
				"tech_philosophy": "LLMs and Python",
				"ai_native": True,
				"product_domains": ["ai-research"],
				"team_size_signal": "mid-size (50-500)",
			},
		):
			resp = await client_with_profile.post("/api/assess/full", json={"assessment_id": aid})

		data = resp.json()
		assert "overall_grade" in data
		assert data["overall_grade"] in {
			"A+",
			"A",
			"A-",
			"B+",
			"B",
			"B-",
			"C+",
			"C",
			"C-",
			"D",
			"F",
		}

	async def test_assess_full_preserves_assessment_fields(self, client_with_profile: AsyncClient):
		"""Full assessment should preserve core assessment fields from partial."""
		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		with patch(
			"claude_candidate.company_research.research_company",
			return_value={
				"mission": "Test company",
				"values": [],
				"culture_signals": [],
				"tech_philosophy": "",
				"ai_native": False,
				"product_domains": [],
				"team_size_signal": "",
			},
		):
			resp = await client_with_profile.post("/api/assess/full", json={"assessment_id": aid})

		data = resp.json()
		assert data["assessment_id"] == aid
		assert "overall_score" in data
		assert "should_apply" in data
		assert "skill_match" in data

	async def test_assess_full_persists_updated_assessment(self, client_with_profile: AsyncClient):
		"""Full assessment should save the updated data to the store."""
		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		with patch(
			"claude_candidate.company_research.research_company",
			return_value={
				"mission": "Test company",
				"values": [],
				"culture_signals": [],
				"tech_philosophy": "",
				"ai_native": False,
				"product_domains": [],
				"team_size_signal": "",
			},
		):
			await client_with_profile.post("/api/assess/full", json={"assessment_id": aid})

		# Verify persistence via GET
		get_resp = await client_with_profile.get(f"/api/assessments/{aid}")
		assert get_resp.status_code == 200
		stored = get_resp.json()
		assert stored["assessment_phase"] == "full"

	async def test_assess_full_works_when_company_research_fails(
		self, client_with_profile: AsyncClient
	):
		"""Full assessment should succeed even if company research fails."""
		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		with patch(
			"claude_candidate.company_research.research_company",
			side_effect=Exception("Claude unavailable"),
		):
			resp = await client_with_profile.post("/api/assess/full", json={"assessment_id": aid})

		# Should still succeed with best-effort mission/culture
		assert resp.status_code == 200
		data = resp.json()
		assert data["assessment_phase"] == "full"

	async def test_assess_full_includes_narrative(self, client_with_profile: AsyncClient):
		"""Full assessment should include narrative verdict and receptivity when available."""
		from unittest.mock import MagicMock

		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		mock_narrative = MagicMock(
			return_value={
				"narrative": "Strong backend fit with deep Python expertise.",
				"receptivity": "high",
				"receptivity_reason": "AI-native company values transparency.",
			}
		)

		# Mock the generator module so the lazy import inside assess_full succeeds
		mock_generator_module = MagicMock()
		mock_generator_module.generate_narrative_verdict = mock_narrative

		import sys

		with (
			patch(
				"claude_candidate.company_research.research_company",
				return_value={
					"mission": "AI research company",
					"values": ["excellence"],
					"culture_signals": ["fast-paced"],
					"tech_philosophy": "LLMs and Python",
					"ai_native": True,
					"product_domains": ["ai-research"],
					"team_size_signal": "mid-size (50-500)",
				},
			),
			patch.dict(sys.modules, {"claude_candidate.generator": mock_generator_module}),
		):
			resp = await client_with_profile.post("/api/assess/full", json={"assessment_id": aid})

		assert resp.status_code == 200
		data = resp.json()
		assert data["narrative_verdict"] == "Strong backend fit with deep Python expertise."
		assert data["receptivity_level"] == "high"
		assert data["receptivity_reason"] == "AI-native company values transparency."

	async def test_assess_full_succeeds_when_narrative_fails(
		self, client_with_profile: AsyncClient
	):
		"""Full assessment should succeed even if narrative generation fails."""
		from unittest.mock import MagicMock

		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		mock_narrative = MagicMock(side_effect=Exception("Claude unavailable"))
		mock_generator_module = MagicMock()
		mock_generator_module.generate_narrative_verdict = mock_narrative

		import sys

		with (
			patch(
				"claude_candidate.company_research.research_company",
				return_value={
					"mission": "Test company",
					"values": [],
					"culture_signals": [],
					"tech_philosophy": "",
					"ai_native": False,
					"product_domains": [],
					"team_size_signal": "",
				},
			),
			patch.dict(sys.modules, {"claude_candidate.generator": mock_generator_module}),
		):
			resp = await client_with_profile.post("/api/assess/full", json={"assessment_id": aid})

		assert resp.status_code == 200
		data = resp.json()
		assert data["assessment_phase"] == "full"

	@pytest.mark.slow
	async def test_full_assess_preserves_eligibility_cap(self, client_with_profile: AsyncClient):
		"""Full-assess recomputation must not undo an F grade from an unmet eligibility gate."""
		spanish_posting = (
			SAMPLE_POSTING
			+ "\n- Must be fluent in Spanish (required)\n"
			+ "- Must have active security clearance (required)\n"
		)
		partial = await client_with_profile.post(
			"/api/assess/partial",
			json={
				"posting_text": spanish_posting,
				"company": "GovCo",
				"title": "Senior Python Engineer",
				"seniority": "senior",
			},
		)
		assert partial.status_code == 200
		aid = partial.json()["assessment_id"]
		# Partial should already be F due to unmet gates
		assert partial.json()["overall_grade"] == "F"
		# Verify the unmet gate is the reason for the F, not just coincidence
		partial_gates = partial.json().get("eligibility_gates", [])
		assert any(g.get("status") == "unmet" for g in partial_gates), \
			"Expected at least one unmet eligibility gate in partial assessment"

		with patch(
			"claude_candidate.company_research.research_company",
			return_value={
				"mission": "Building secure government software",
				"values": ["security", "reliability"],
				"culture_signals": ["mission-driven", "process-oriented"],
				"tech_philosophy": "Python, secure coding practices",
				"ai_native": False,
				"product_domains": ["government-technology"],
				"team_size_signal": "large (500+)",
			},
		):
			resp = await client_with_profile.post("/api/assess/full", json={"assessment_id": aid})

		assert resp.status_code == 200
		assert resp.json()["overall_grade"] == "F"  # cap must survive full-assess recomputation


# ---------------------------------------------------------------------------
# Assessment list / detail / delete
# ---------------------------------------------------------------------------


class TestAssessmentCRUD:
	async def test_list_assessments_empty(self, client: AsyncClient):
		resp = await client.get("/api/assessments")
		assert resp.status_code == 200
		assert resp.json() == []

	async def test_list_assessments_returns_saved(self, client_with_profile: AsyncClient):
		# Save an assessment
		await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		resp = await client_with_profile.get("/api/assessments")
		assert resp.status_code == 200
		assert len(resp.json()) == 1

	async def test_list_assessments_limit(self, client_with_profile: AsyncClient):
		for _ in range(5):
			await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		resp = await client_with_profile.get("/api/assessments?limit=2")
		assert len(resp.json()) == 2

	async def test_list_assessments_offset(self, client_with_profile: AsyncClient):
		for _ in range(3):
			await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		all_resp = await client_with_profile.get("/api/assessments")
		paged_resp = await client_with_profile.get("/api/assessments?offset=2")
		assert len(paged_resp.json()) == len(all_resp.json()) - 2

	async def test_get_assessment_not_found(self, client: AsyncClient):
		resp = await client.get("/api/assessments/does-not-exist")
		assert resp.status_code == 404

	async def test_delete_assessment(self, client_with_profile: AsyncClient):
		assess_resp = await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		aid = assess_resp.json()["assessment_id"]

		del_resp = await client_with_profile.delete(f"/api/assessments/{aid}")
		assert del_resp.status_code == 200
		assert del_resp.json()["deleted"] is True

		# Should be gone
		get_resp = await client_with_profile.get(f"/api/assessments/{aid}")
		assert get_resp.status_code == 404

	async def test_delete_nonexistent_assessment(self, client: AsyncClient):
		resp = await client.delete("/api/assessments/no-such-id")
		assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Shortlist endpoints
# ---------------------------------------------------------------------------


SAMPLE_SHORTLIST_ITEM = {
	"company_name": "Startup Co",
	"job_title": "Backend Engineer",
	"posting_url": "https://startup.io/jobs/42",
	"notes": "Great culture",
}


class TestShortlistEndpoints:
	async def test_add_shortlist_item(self, client: AsyncClient):
		resp = await client.post("/api/shortlist", json=SAMPLE_SHORTLIST_ITEM)
		assert resp.status_code == 201
		data = resp.json()
		assert "id" in data
		assert data["company_name"] == "Startup Co"
		assert data["status"] == "shortlisted"

	async def test_list_shortlist_empty(self, client: AsyncClient):
		resp = await client.get("/api/shortlist")
		assert resp.status_code == 200
		assert resp.json() == []

	async def test_list_shortlist_returns_added(self, client: AsyncClient):
		await client.post("/api/shortlist", json=SAMPLE_SHORTLIST_ITEM)
		resp = await client.get("/api/shortlist")
		assert len(resp.json()) == 1

	async def test_list_shortlist_filter_by_status(self, client: AsyncClient):
		add_resp = await client.post("/api/shortlist", json=SAMPLE_SHORTLIST_ITEM)
		sid = add_resp.json()["id"]

		# Update to applied
		await client.patch(f"/api/shortlist/{sid}", json={"status": "applied"})

		shortlisted = await client.get("/api/shortlist?status=shortlisted")
		applied = await client.get("/api/shortlist?status=applied")
		assert len(shortlisted.json()) == 0
		assert len(applied.json()) == 1

	async def test_update_shortlist_status(self, client: AsyncClient):
		add_resp = await client.post("/api/shortlist", json=SAMPLE_SHORTLIST_ITEM)
		sid = add_resp.json()["id"]

		patch_resp = await client.patch(f"/api/shortlist/{sid}", json={"status": "applied"})
		assert patch_resp.status_code == 200
		assert patch_resp.json()["updated"] is True

	async def test_update_shortlist_notes(self, client: AsyncClient):
		add_resp = await client.post("/api/shortlist", json=SAMPLE_SHORTLIST_ITEM)
		sid = add_resp.json()["id"]

		await client.patch(f"/api/shortlist/{sid}", json={"notes": "Updated notes"})

		items = await client.get("/api/shortlist")
		entry = next(i for i in items.json() if i["id"] == sid)
		assert entry["notes"] == "Updated notes"

	async def test_update_nonexistent_shortlist(self, client: AsyncClient):
		resp = await client.patch("/api/shortlist/99999", json={"status": "applied"})
		assert resp.status_code == 404

	async def test_delete_shortlist_item(self, client: AsyncClient):
		add_resp = await client.post("/api/shortlist", json=SAMPLE_SHORTLIST_ITEM)
		sid = add_resp.json()["id"]

		del_resp = await client.delete(f"/api/shortlist/{sid}")
		assert del_resp.status_code == 200
		assert del_resp.json()["deleted"] is True

		# Confirm gone
		items = await client.get("/api/shortlist")
		assert all(i["id"] != sid for i in items.json())

	async def test_delete_nonexistent_shortlist(self, client: AsyncClient):
		resp = await client.delete("/api/shortlist/99999")
		assert resp.status_code == 404

	async def test_add_shortlist_with_assessment_id(self, client_with_profile: AsyncClient):
		# Create an assessment first
		assess_resp = await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		aid = assess_resp.json()["assessment_id"]

		# Add to shortlist referencing the assessment
		sl_payload = {**SAMPLE_SHORTLIST_ITEM, "assessment_id": aid}
		resp = await client_with_profile.post("/api/shortlist", json=sl_payload)
		assert resp.status_code == 201
		assert resp.json()["assessment_id"] == aid

	async def test_list_shortlist_limit(self, client: AsyncClient):
		for i in range(5):
			await client.post(
				"/api/shortlist",
				json={
					"company_name": f"Company {i}",
					"job_title": "Engineer",
				},
			)
		resp = await client.get("/api/shortlist?limit=3")
		assert len(resp.json()) == 3

	async def test_add_shortlist_with_new_fields(self, client: AsyncClient):
		payload = {
			**SAMPLE_SHORTLIST_ITEM,
			"salary": "$180k-$220k",
			"location": "Remote",
			"overall_grade": "A",
		}
		resp = await client.post("/api/shortlist", json=payload)
		assert resp.status_code == 201
		data = resp.json()
		assert data["salary"] == "$180k-$220k"
		assert data["location"] == "Remote"
		assert data["overall_grade"] == "A"

	async def test_new_fields_persisted_in_list(self, client: AsyncClient):
		payload = {
			**SAMPLE_SHORTLIST_ITEM,
			"salary": "$150k",
			"location": "NYC",
			"overall_grade": "B+",
		}
		await client.post("/api/shortlist", json=payload)
		resp = await client.get("/api/shortlist")
		entry = resp.json()[0]
		assert entry["salary"] == "$150k"
		assert entry["location"] == "NYC"
		assert entry["overall_grade"] == "B+"


# ---------------------------------------------------------------------------
# Proof package endpoint
# ---------------------------------------------------------------------------


class TestProofEndpoint:
	async def test_generate_proof(self, client_with_profile: AsyncClient):
		assess_resp = await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		assert assess_resp.status_code == 200
		assessment_id = assess_resp.json()["assessment_id"]

		resp = await client_with_profile.post("/api/proof", json={"assessment_id": assessment_id})
		assert resp.status_code == 200
		data = resp.json()
		assert "proof_package" in data
		assert len(data["proof_package"]) > 0

	async def test_proof_package_contains_assessment_id(self, client_with_profile: AsyncClient):
		assess_resp = await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		assessment_id = assess_resp.json()["assessment_id"]

		resp = await client_with_profile.post("/api/proof", json={"assessment_id": assessment_id})
		assert assessment_id in resp.json()["proof_package"]

	async def test_proof_missing_assessment(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post("/api/proof", json={"assessment_id": "nonexistent"})
		assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Deliverable generation endpoint
# ---------------------------------------------------------------------------


class TestGenerateEndpoint:
	async def _create_assessment_id(self, client: AsyncClient) -> str:
		resp = await client.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		assert resp.status_code == 200
		return resp.json()["assessment_id"]

	async def test_generate_resume_bullets(self, client_with_profile: AsyncClient):
		aid = await self._create_assessment_id(client_with_profile)
		with patch(
			"claude_candidate.generator.call_claude",
			return_value="- Led Python backend refactor\n- Built React dashboard",
		):
			resp = await client_with_profile.post(
				"/api/generate",
				json={"assessment_id": aid, "deliverable_type": "resume_bullets"},
			)
		assert resp.status_code == 200
		data = resp.json()
		assert data["deliverable_type"] == "resume_bullets"
		assert isinstance(data["result"], list)
		assert len(data["result"]) > 0

	async def test_generate_cover_letter(self, client_with_profile: AsyncClient):
		aid = await self._create_assessment_id(client_with_profile)
		with patch(
			"claude_candidate.generator.call_claude",
			return_value="Dear Hiring Manager, I am excited to apply for this role...",
		):
			resp = await client_with_profile.post(
				"/api/generate",
				json={"assessment_id": aid, "deliverable_type": "cover_letter"},
			)
		assert resp.status_code == 200
		data = resp.json()
		assert data["deliverable_type"] == "cover_letter"
		assert isinstance(data["result"], str)
		assert len(data["result"]) > 0

	async def test_generate_interview_prep(self, client_with_profile: AsyncClient):
		aid = await self._create_assessment_id(client_with_profile)
		with patch(
			"claude_candidate.generator.call_claude",
			return_value="## Technical Discussion Points\n- Python: strong\n## Questions to Ask\n- ?",
		):
			resp = await client_with_profile.post(
				"/api/generate",
				json={"assessment_id": aid, "deliverable_type": "interview_prep"},
			)
		assert resp.status_code == 200
		data = resp.json()
		assert data["deliverable_type"] == "interview_prep"
		assert isinstance(data["result"], str)
		assert len(data["result"]) > 0

	async def test_generate_unknown_type_returns_422(self, client_with_profile: AsyncClient):
		aid = await self._create_assessment_id(client_with_profile)
		resp = await client_with_profile.post(
			"/api/generate",
			json={"assessment_id": aid, "deliverable_type": "magic_letter"},
		)
		assert resp.status_code == 422

	async def test_generate_missing_assessment_returns_404(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post(
			"/api/generate",
			json={"assessment_id": "nonexistent-id", "deliverable_type": "cover_letter"},
		)
		assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Extract posting endpoint
# ---------------------------------------------------------------------------


SAMPLE_EXTRACT_PAYLOAD = {
	"url": "https://boards.greenhouse.io/acme/jobs/12345",
	"title": "Senior Backend Engineer at Acme",
	"text": "Acme Corp is hiring a Senior Backend Engineer. You will build scalable services. Requirements: 5+ years Python, strong system design skills. Location: San Francisco, CA. Remote friendly. Salary: $180k-$220k.",
}

SAMPLE_CLAUDE_JSON = json.dumps(
	{
		"company": "Acme Corp",
		"title": "Senior Backend Engineer",
		"description": "Build scalable services. Requirements: 5+ years Python, strong system design skills.",
		"location": "San Francisco, CA",
		"seniority": "senior",
		"remote": True,
		"salary": "$180k-$220k",
	}
)

SAMPLE_CLAUDE_JSON_WITH_REQUIREMENTS = json.dumps(
	{
		"company": "Acme Corp",
		"title": "Senior Backend Engineer",
		"description": "Build scalable services. Requirements: 5+ years Python, strong system design skills.",
		"location": "San Francisco, CA",
		"seniority": "senior",
		"remote": True,
		"salary": "$180k-$220k",
		"requirements": [
			{
				"description": "5+ years of Python experience",
				"skill_mapping": ["python"],
				"priority": "must_have",
				"years_experience": 5,
				"education_level": None,
			},
			{
				"description": "Strong system design skills",
				"skill_mapping": ["system design", "architecture"],
				"priority": "must_have",
				"years_experience": None,
				"education_level": None,
			},
		],
	}
)


class TestExtractPostingEndpoint:
	async def test_extracts_posting_via_claude(self, client: AsyncClient):
		"""Cache miss calls Claude and returns structured result."""
		with (
			patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
			patch("claude_candidate.claude_cli.call_claude", return_value=SAMPLE_CLAUDE_JSON),
		):
			resp = await client.post("/api/extract-posting", json=SAMPLE_EXTRACT_PAYLOAD)
		assert resp.status_code == 200
		data = resp.json()
		assert data["company"] == "Acme Corp"
		assert data["title"] == "Senior Backend Engineer"
		assert data["source"] == "greenhouse"
		assert data["remote"] is True
		assert data["salary"] == "$180k-$220k"

	async def test_returns_cached_result(self, client: AsyncClient):
		"""Second call with same URL hits cache; Claude called only once."""
		with (
			patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
			patch(
				"claude_candidate.claude_cli.call_claude", return_value=SAMPLE_CLAUDE_JSON
			) as mock_claude,
		):
			await client.post("/api/extract-posting", json=SAMPLE_EXTRACT_PAYLOAD)
			resp2 = await client.post("/api/extract-posting", json=SAMPLE_EXTRACT_PAYLOAD)
		assert resp2.status_code == 200
		assert resp2.json()["company"] == "Acme Corp"
		mock_claude.assert_called_once()

	async def test_503_when_claude_unavailable(self, client: AsyncClient):
		"""Returns 503 when check_claude_available returns False."""
		with patch("claude_candidate.claude_cli.check_claude_available", return_value=False):
			resp = await client.post("/api/extract-posting", json=SAMPLE_EXTRACT_PAYLOAD)
		assert resp.status_code == 503
		assert "Claude CLI not available" in resp.json()["detail"]

	async def test_502_on_malformed_claude_response(self, client: AsyncClient):
		"""Returns 502 when Claude returns non-JSON."""
		with (
			patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
			patch("claude_candidate.claude_cli.call_claude", return_value="this is not json"),
		):
			resp = await client.post("/api/extract-posting", json=SAMPLE_EXTRACT_PAYLOAD)
		assert resp.status_code == 502
		assert "invalid response" in resp.json()["detail"]

	async def test_infers_source_from_url(self, client: AsyncClient):
		"""Source field matches URL hostname."""
		for url, expected_source in [
			("https://boards.greenhouse.io/co/jobs/1", "greenhouse"),
			("https://jobs.lever.co/acme/xyz", "lever"),
			("https://www.linkedin.com/jobs/view/123", "linkedin"),
			("https://www.indeed.com/viewjob?jk=abc", "indeed"),
			("https://acme.com/careers/senior-engineer", "web"),
		]:
			with (
				patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
				patch("claude_candidate.claude_cli.call_claude", return_value=SAMPLE_CLAUDE_JSON),
			):
				resp = await client.post(
					"/api/extract-posting",
					json={"url": url, "title": "Engineer", "text": "job text"},
				)
			assert resp.status_code == 200, f"Failed for {url}"
			assert resp.json()["source"] == expected_source, f"Wrong source for {url}"

	async def test_truncates_long_text(self, client: AsyncClient):
		"""Text > 15k chars is truncated in the prompt sent to Claude."""
		long_text = "x" * 20_000
		captured_prompts: list[str] = []

		def capture_call(prompt: str, **kwargs):
			captured_prompts.append(prompt)
			return SAMPLE_CLAUDE_JSON

		with (
			patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
			patch("claude_candidate.claude_cli.call_claude", side_effect=capture_call),
		):
			resp = await client.post(
				"/api/extract-posting",
				json={"url": "https://acme.com/jobs/1", "title": "Engineer", "text": long_text},
			)
		assert resp.status_code == 200
		assert len(captured_prompts) == 1
		# The truncated text (15k "x"s) should appear in the prompt, but not all 20k
		assert "x" * 15_000 in captured_prompts[0]
		assert "x" * 15_001 not in captured_prompts[0]

	async def test_handles_code_fenced_json(self, client: AsyncClient):
		"""Claude response wrapped in ```json fences is parsed correctly."""
		fenced_response = f"```json\n{SAMPLE_CLAUDE_JSON}\n```"
		with (
			patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
			patch("claude_candidate.claude_cli.call_claude", return_value=fenced_response),
		):
			resp = await client.post("/api/extract-posting", json=SAMPLE_EXTRACT_PAYLOAD)
		assert resp.status_code == 200
		assert resp.json()["company"] == "Acme Corp"

	async def test_null_fields_for_non_job_page(self, client: AsyncClient):
		"""Returns 200 with empty strings for non-job pages where Claude returns nulls."""
		null_response = json.dumps(
			{
				"company": None,
				"title": None,
				"description": None,
				"location": None,
				"seniority": None,
				"remote": None,
				"salary": None,
			}
		)
		with (
			patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
			patch("claude_candidate.claude_cli.call_claude", return_value=null_response),
		):
			resp = await client.post(
				"/api/extract-posting",
				json={
					"url": "https://acme.com/about",
					"title": "About Us",
					"text": "We are a company.",
				},
			)
		assert resp.status_code == 200
		data = resp.json()
		assert data["company"] == ""
		assert data["title"] == ""
		assert data["description"] == ""
		assert data["location"] is None
		assert data["remote"] is None

	async def test_extraction_includes_requirements(self, client: AsyncClient):
		"""Extraction response includes structured requirements from Claude."""
		with (
			patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
			patch(
				"claude_candidate.claude_cli.call_claude",
				return_value=SAMPLE_CLAUDE_JSON_WITH_REQUIREMENTS,
			),
		):
			resp = await client.post(
				"/api/extract-posting",
				json={
					"url": "https://acme.com/jobs/99",
					"title": "Senior Backend Engineer at Acme",
					"text": "Acme Corp is hiring. Requirements: 5+ years Python, system design.",
				},
			)
		assert resp.status_code == 200
		data = resp.json()
		assert "requirements" in data
		assert isinstance(data["requirements"], list)
		assert len(data["requirements"]) == 2
		req0 = data["requirements"][0]
		assert req0["description"] == "5+ years of Python experience"
		assert req0["skill_mapping"] == ["python"]
		assert req0["priority"] == "must_have"
		assert req0["years_experience"] == 5

	async def test_extraction_requirements_null_when_absent(self, client: AsyncClient):
		"""Requirements is null when Claude response omits it (backward compat)."""
		with (
			patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
			patch("claude_candidate.claude_cli.call_claude", return_value=SAMPLE_CLAUDE_JSON),
		):
			resp = await client.post(
				"/api/extract-posting",
				json={
					"url": "https://acme.com/jobs/100",
					"title": "Engineer",
					"text": "Some job posting text.",
				},
			)
		assert resp.status_code == 200
		data = resp.json()
		assert data["requirements"] is None

	async def test_extraction_prompt_asks_for_requirements(self, client: AsyncClient):
		"""The prompt sent to Claude asks for requirements extraction."""
		captured_prompts: list[str] = []

		def capture_call(prompt: str, **kwargs):
			captured_prompts.append(prompt)
			return SAMPLE_CLAUDE_JSON_WITH_REQUIREMENTS

		with (
			patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
			patch("claude_candidate.claude_cli.call_claude", side_effect=capture_call),
		):
			await client.post(
				"/api/extract-posting",
				json={
					"url": "https://acme.com/jobs/101",
					"title": "Engineer",
					"text": "Some job posting text.",
				},
			)
		assert len(captured_prompts) == 1
		prompt = captured_prompts[0]
		assert "requirements" in prompt.lower()
		assert "skill_mapping" in prompt
		assert "must_have" in prompt
		assert "years_experience" in prompt
		assert "education_level" in prompt


# ---------------------------------------------------------------------------
# Assess requires requirements (no keyword fallback)
# ---------------------------------------------------------------------------


class TestAssessRequiresRequirements:
	"""Server must reject assessments when no requirements are provided."""

	@pytest.mark.asyncio
	async def test_assess_partial_rejects_null_requirements(self, app_with_profile):
		async with LifespanManager(app_with_profile):
			transport = ASGITransport(app=app_with_profile)
			async with AsyncClient(transport=transport, base_url="http://test") as client:
				resp = await client.post(
					"/api/assess/partial",
					json={
						"posting_text": "We need a Python developer with Django experience.",
						"company": "TestCo",
						"title": "Software Engineer",
						"requirements": None,
					},
				)
				assert resp.status_code == 422
				assert "requirements" in resp.json()["detail"].lower()

	@pytest.mark.asyncio
	async def test_assess_partial_rejects_empty_requirements(self, app_with_profile):
		async with LifespanManager(app_with_profile):
			transport = ASGITransport(app=app_with_profile)
			async with AsyncClient(transport=transport, base_url="http://test") as client:
				resp = await client.post(
					"/api/assess/partial",
					json={
						"posting_text": "We need a Python developer.",
						"company": "TestCo",
						"title": "Software Engineer",
						"requirements": [],
					},
				)
				assert resp.status_code == 422

	@pytest.mark.asyncio
	async def test_assess_partial_accepts_valid_requirements(self, app_with_profile):
		async with LifespanManager(app_with_profile):
			transport = ASGITransport(app=app_with_profile)
			async with AsyncClient(transport=transport, base_url="http://test") as client:
				resp = await client.post(
					"/api/assess/partial",
					json={
						"posting_text": "Python developer role",
						"company": "TestCo",
						"title": "Software Engineer",
						"requirements": [
							{
								"description": "Python experience",
								"skill_mapping": ["python"],
								"priority": "must_have",
								"source_text": "Must have Python",
							}
						],
					},
				)
				assert resp.status_code == 200


# ---------------------------------------------------------------------------
# URL normalization for cache keys
# ---------------------------------------------------------------------------


class TestUrlNormalization:
	"""Tracking params should not defeat the posting cache."""

	async def test_linkedin_tracking_params_normalized(self, client: AsyncClient):
		"""Same LinkedIn job with different tracking params should hit cache."""
		url_base = "https://www.linkedin.com/jobs/view/4385180576/"
		url_with_params = url_base + "?trk=eml-email_job_alert&eBP=abc123&trackingId=xyz"

		with (
			patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
			patch(
				"claude_candidate.claude_cli.call_claude", return_value=SAMPLE_CLAUDE_JSON
			) as mock_claude,
		):
			r1 = await client.post(
				"/api/extract-posting",
				json={"url": url_base, "title": "Test", "text": "Senior Engineer role."},
			)
			assert r1.status_code == 200

			r2 = await client.post(
				"/api/extract-posting",
				json={
					"url": url_with_params,
					"title": "Test",
					"text": "Senior Engineer role.",
				},
			)
			assert r2.status_code == 200
			assert r2.json()["company"] == "Acme Corp"
			mock_claude.assert_called_once()

	async def test_utm_params_stripped_from_any_url(self, client: AsyncClient):
		"""UTM params should be stripped from non-LinkedIn URLs too."""
		url_base = "https://greenhouse.io/jobs/senior-eng"
		url_with_utm = url_base + "?utm_source=email&utm_medium=social&ref=abc"

		with (
			patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
			patch(
				"claude_candidate.claude_cli.call_claude", return_value=SAMPLE_CLAUDE_JSON
			) as mock_claude,
		):
			r1 = await client.post(
				"/api/extract-posting",
				json={"url": url_base, "title": "Test", "text": "Some job"},
			)
			assert r1.status_code == 200

			r2 = await client.post(
				"/api/extract-posting",
				json={"url": url_with_utm, "title": "Test", "text": "Some job"},
			)
			assert r2.status_code == 200
			mock_claude.assert_called_once()

	async def test_non_tracking_params_preserved(self, client: AsyncClient):
		"""Non-tracking query params (like job IDs) should be preserved."""
		from claude_candidate.server import _normalize_cache_url

		url = "https://boards.greenhouse.io/company/jobs/123?gh_jid=456"
		normalized = _normalize_cache_url(url)
		assert "gh_jid=456" in normalized
