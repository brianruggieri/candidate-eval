"""Tests for the FastAPI backend server."""

from __future__ import annotations

from pathlib import Path

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
		assert data["has_merged_profile"] is False
		assert data["hashes"] == {}

	async def test_with_profiles_shows_loaded(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.get("/api/profile/status")
		assert resp.status_code == 200
		data = resp.json()
		assert data["has_candidate_profile"] is True
		assert data["has_resume_profile"] is True
		# Merged profile is only written when explicitly requested
		assert data["has_merged_profile"] is False
		assert "candidate" in data["hashes"]
		assert "resume" in data["hashes"]


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
# Watchlist endpoints
# ---------------------------------------------------------------------------


SAMPLE_WATCHLIST_ITEM = {
	"company_name": "Startup Co",
	"job_title": "Backend Engineer",
	"posting_url": "https://startup.io/jobs/42",
	"notes": "Great culture",
}


class TestWatchlistEndpoints:
	async def test_add_watchlist_item(self, client: AsyncClient):
		resp = await client.post("/api/watchlist", json=SAMPLE_WATCHLIST_ITEM)
		assert resp.status_code == 201
		data = resp.json()
		assert "id" in data
		assert data["company_name"] == "Startup Co"
		assert data["status"] == "watching"

	async def test_list_watchlist_empty(self, client: AsyncClient):
		resp = await client.get("/api/watchlist")
		assert resp.status_code == 200
		assert resp.json() == []

	async def test_list_watchlist_returns_added(self, client: AsyncClient):
		await client.post("/api/watchlist", json=SAMPLE_WATCHLIST_ITEM)
		resp = await client.get("/api/watchlist")
		assert len(resp.json()) == 1

	async def test_list_watchlist_filter_by_status(self, client: AsyncClient):
		add_resp = await client.post("/api/watchlist", json=SAMPLE_WATCHLIST_ITEM)
		wid = add_resp.json()["id"]

		# Update to applied
		await client.patch(f"/api/watchlist/{wid}", json={"status": "applied"})

		watching = await client.get("/api/watchlist?status=watching")
		applied = await client.get("/api/watchlist?status=applied")
		assert len(watching.json()) == 0
		assert len(applied.json()) == 1

	async def test_update_watchlist_status(self, client: AsyncClient):
		add_resp = await client.post("/api/watchlist", json=SAMPLE_WATCHLIST_ITEM)
		wid = add_resp.json()["id"]

		patch_resp = await client.patch(f"/api/watchlist/{wid}", json={"status": "applied"})
		assert patch_resp.status_code == 200
		assert patch_resp.json()["updated"] is True

	async def test_update_watchlist_notes(self, client: AsyncClient):
		add_resp = await client.post("/api/watchlist", json=SAMPLE_WATCHLIST_ITEM)
		wid = add_resp.json()["id"]

		await client.patch(f"/api/watchlist/{wid}", json={"notes": "Updated notes"})

		items = await client.get("/api/watchlist")
		entry = next(i for i in items.json() if i["id"] == wid)
		assert entry["notes"] == "Updated notes"

	async def test_update_nonexistent_watchlist(self, client: AsyncClient):
		resp = await client.patch("/api/watchlist/99999", json={"status": "applied"})
		assert resp.status_code == 404

	async def test_delete_watchlist_item(self, client: AsyncClient):
		add_resp = await client.post("/api/watchlist", json=SAMPLE_WATCHLIST_ITEM)
		wid = add_resp.json()["id"]

		del_resp = await client.delete(f"/api/watchlist/{wid}")
		assert del_resp.status_code == 200
		assert del_resp.json()["deleted"] is True

		# Confirm gone
		items = await client.get("/api/watchlist")
		assert all(i["id"] != wid for i in items.json())

	async def test_delete_nonexistent_watchlist(self, client: AsyncClient):
		resp = await client.delete("/api/watchlist/99999")
		assert resp.status_code == 404

	async def test_add_watchlist_with_assessment_id(self, client_with_profile: AsyncClient):
		# Create an assessment first
		assess_resp = await client_with_profile.post("/api/assess", json=SAMPLE_ASSESS_PAYLOAD)
		aid = assess_resp.json()["assessment_id"]

		# Add to watchlist referencing the assessment
		wl_payload = {**SAMPLE_WATCHLIST_ITEM, "assessment_id": aid}
		resp = await client_with_profile.post("/api/watchlist", json=wl_payload)
		assert resp.status_code == 201
		assert resp.json()["assessment_id"] == aid

	async def test_list_watchlist_limit(self, client: AsyncClient):
		for i in range(5):
			await client.post("/api/watchlist", json={
				"company_name": f"Company {i}",
				"job_title": "Engineer",
			})
		resp = await client.get("/api/watchlist?limit=3")
		assert len(resp.json()) == 3
