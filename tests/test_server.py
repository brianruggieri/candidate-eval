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


class TestAssessFullEndpoint:
	async def test_assess_full_not_found_returns_404(self, client_with_profile: AsyncClient):
		resp = await client_with_profile.post(
			"/api/assess/full", json={"assessment_id": "nonexistent"}
		)
		assert resp.status_code == 404

	async def test_assess_full_returns_deliverables(self, client_with_profile: AsyncClient):
		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		with patch(
			"claude_candidate.generator.call_claude",
			side_effect=[
				"- Led Python backend refactor",
				"Dear Hiring Manager, ...",
				"## Technical Discussion Points",
			],
		):
			resp = await client_with_profile.post(
				"/api/assess/full", json={"assessment_id": aid}
			)

		assert resp.status_code == 200
		data = resp.json()
		assert "deliverables" in data
		assert "resume_bullets" in data["deliverables"]
		assert "cover_letter" in data["deliverables"]
		assert "interview_prep" in data["deliverables"]

	async def test_assess_full_preserves_assessment_fields(self, client_with_profile: AsyncClient):
		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		with patch("claude_candidate.generator.call_claude", return_value="stub"):
			resp = await client_with_profile.post(
				"/api/assess/full", json={"assessment_id": aid}
			)

		data = resp.json()
		assert data["assessment_id"] == aid
		assert "overall_score" in data
		assert "should_apply" in data

	async def test_assess_full_returns_error_when_claude_unavailable(
		self, client_with_profile: AsyncClient
	):
		from claude_candidate.claude_cli import ClaudeCLIError

		partial = await client_with_profile.post("/api/assess/partial", json=SAMPLE_ASSESS_PAYLOAD)
		aid = partial.json()["assessment_id"]

		with patch(
			"claude_candidate.generator.call_claude",
			side_effect=ClaudeCLIError("claude not found"),
		):
			resp = await client_with_profile.post(
				"/api/assess/full", json={"assessment_id": aid}
			)

		# Should still return 200 with an error field, not crash
		assert resp.status_code == 200
		data = resp.json()
		assert "error" in data


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

SAMPLE_CLAUDE_JSON = json.dumps({
    "company": "Acme Corp",
    "title": "Senior Backend Engineer",
    "description": "Build scalable services. Requirements: 5+ years Python, strong system design skills.",
    "location": "San Francisco, CA",
    "seniority": "senior",
    "remote": True,
    "salary": "$180k-$220k",
})

SAMPLE_CLAUDE_JSON_WITH_REQUIREMENTS = json.dumps({
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
})


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
            patch("claude_candidate.claude_cli.call_claude", return_value=SAMPLE_CLAUDE_JSON) as mock_claude,
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
        null_response = json.dumps({
            "company": None,
            "title": None,
            "description": None,
            "location": None,
            "seniority": None,
            "remote": None,
            "salary": None,
        })
        with (
            patch("claude_candidate.claude_cli.check_claude_available", return_value=True),
            patch("claude_candidate.claude_cli.call_claude", return_value=null_response),
        ):
            resp = await client.post(
                "/api/extract-posting",
                json={"url": "https://acme.com/about", "title": "About Us", "text": "We are a company."},
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
            patch("claude_candidate.claude_cli.call_claude", return_value=SAMPLE_CLAUDE_JSON_WITH_REQUIREMENTS),
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
