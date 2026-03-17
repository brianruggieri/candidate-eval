"""Tests for the GitHub public repo correlator."""

from __future__ import annotations

import pytest

from claude_candidate.extractor import SessionSignals
from claude_candidate.schemas.session_manifest import PublicRepoCorrelation


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_signals(
    session_id: str = "sess-001",
    technologies: list[str] | None = None,
    timestamp: str = "2026-01-15T10:00:00Z",
) -> SessionSignals:
    return SessionSignals(
        session_id=session_id,
        project_hint="my-project",
        technologies=technologies or [],
        tool_calls=[],
        patterns_observed=[],
        evidence_snippets=[],
        line_count=100,
        timestamp=timestamp,
    )


def make_repo_info(
    name: str = "my-repo",
    language: str | None = "Python",
    topics: list[str] | None = None,
    created_at: str = "2025-06-01T00:00:00Z",
    pushed_at: str = "2026-01-10T00:00:00Z",
):
    from claude_candidate.correlator import RepoInfo

    return RepoInfo(
        name=name,
        full_name=f"octocat/{name}",
        url=f"https://github.com/octocat/{name}",
        language=language,
        topics=topics or [],
        created_at=created_at,
        pushed_at=pushed_at,
        description=f"A repo called {name}",
    )


# ---------------------------------------------------------------------------
# TestFetchPublicRepos
# ---------------------------------------------------------------------------


class TestFetchPublicRepos:
    def test_handles_http_error(self):
        """Returns empty list on HTTP error (404, 500, etc.)."""
        import httpx
        from unittest.mock import patch

        with patch("httpx.get") as mock_get:
            mock_get.side_effect = httpx.HTTPStatusError(
                "Not Found",
                request=httpx.Request("GET", "https://api.github.com/users/nobody/repos"),
                response=httpx.Response(404),
            )
            from claude_candidate.correlator import fetch_public_repos

            result = fetch_public_repos("nobody")
        assert result == []

    def test_handles_network_error(self):
        """Returns empty list on network-level error."""
        import httpx
        from unittest.mock import patch

        with patch("httpx.get") as mock_get:
            mock_get.side_effect = httpx.RequestError("Connection refused")
            from claude_candidate.correlator import fetch_public_repos

            result = fetch_public_repos("nobody")
        assert result == []

    def test_parses_repo_list(self):
        """Parses GitHub API response into RepoInfo list."""
        from unittest.mock import MagicMock, patch

        api_response = [
            {
                "name": "my-project",
                "full_name": "octocat/my-project",
                "html_url": "https://github.com/octocat/my-project",
                "language": "Python",
                "topics": ["python", "fastapi"],
                "created_at": "2025-01-01T00:00:00Z",
                "pushed_at": "2026-01-10T00:00:00Z",
                "description": "A test project",
            }
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = api_response
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_resp):
            from claude_candidate.correlator import fetch_public_repos

            result = fetch_public_repos("octocat")

        assert len(result) == 1
        repo = result[0]
        assert repo.name == "my-project"
        assert repo.language == "Python"
        assert repo.topics == ["python", "fastapi"]
        assert repo.url == "https://github.com/octocat/my-project"

    def test_handles_nonexistent_user(self):
        """Returns empty list for a user that raises 404."""
        import httpx
        from unittest.mock import MagicMock, patch

        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "404 Not Found",
            request=httpx.Request("GET", "https://api.github.com/users/doesnotexist999/repos"),
            response=httpx.Response(404),
        )

        with patch("httpx.get", return_value=mock_resp):
            from claude_candidate.correlator import fetch_public_repos

            result = fetch_public_repos("doesnotexist999")
        assert result == []

    def test_returns_repo_info_dataclasses(self):
        """Returned items are RepoInfo dataclass instances."""
        from unittest.mock import MagicMock, patch
        from claude_candidate.correlator import RepoInfo

        api_response = [
            {
                "name": "repo-a",
                "full_name": "user/repo-a",
                "html_url": "https://github.com/user/repo-a",
                "language": "TypeScript",
                "topics": [],
                "created_at": "2025-03-01T00:00:00Z",
                "pushed_at": "2025-12-01T00:00:00Z",
                "description": None,
            }
        ]
        mock_resp = MagicMock()
        mock_resp.json.return_value = api_response
        mock_resp.raise_for_status = MagicMock()

        with patch("httpx.get", return_value=mock_resp):
            from claude_candidate.correlator import fetch_public_repos

            result = fetch_public_repos("user")

        assert isinstance(result[0], RepoInfo)


# ---------------------------------------------------------------------------
# TestCorrelateRepos
# ---------------------------------------------------------------------------


class TestCorrelateRepos:
    def test_finds_tech_overlap(self):
        """Returns correlation when repo language matches session tech."""
        from claude_candidate.correlator import correlate_repos

        repos = [make_repo_info(name="py-app", language="Python")]
        signals = [make_signals(session_id="s1", technologies=["python", "fastapi"])]

        result = correlate_repos(repos=repos, signals_list=signals)

        assert len(result) == 1
        assert result[0].repo_name == "py-app"
        assert result[0].correlation_type in {"content_reference", "combined"}

    def test_no_overlap_returns_empty(self):
        """Returns empty list when no tech overlap exists."""
        from claude_candidate.correlator import correlate_repos

        repos = [make_repo_info(name="rust-app", language="Rust")]
        signals = [make_signals(session_id="s1", technologies=["python", "fastapi"])]

        result = correlate_repos(repos=repos, signals_list=signals)

        assert result == []

    def test_multiple_repos_with_varying_overlap(self):
        """Handles multiple repos; only overlapping ones returned."""
        from claude_candidate.correlator import correlate_repos

        repos = [
            make_repo_info(name="py-app", language="Python"),
            make_repo_info(name="go-app", language="Go"),
            make_repo_info(name="ts-app", language="TypeScript"),
        ]
        signals = [make_signals(session_id="s1", technologies=["python", "typescript"])]

        result = correlate_repos(repos=repos, signals_list=signals)
        names = {r.repo_name for r in result}

        assert "py-app" in names
        assert "ts-app" in names
        assert "go-app" not in names

    def test_correlation_strength_levels(self):
        """Strength levels vary based on overlap count."""
        from claude_candidate.correlator import correlate_repos

        # Strong: 3+ overlap via topics
        repos = [
            make_repo_info(
                name="full-stack",
                language="Python",
                topics=["fastapi", "react", "docker"],
            )
        ]
        signals = [
            make_signals(
                session_id="s1",
                technologies=["python", "fastapi", "react", "docker"],
            )
        ]
        result = correlate_repos(repos=repos, signals_list=signals)
        assert len(result) == 1
        assert result[0].correlation_strength == "strong"

    def test_returns_public_repo_correlation_instances(self):
        """Returns PublicRepoCorrelation model instances."""
        from claude_candidate.correlator import correlate_repos

        repos = [make_repo_info(name="py-app", language="Python")]
        signals = [make_signals(session_id="s1", technologies=["python"])]

        result = correlate_repos(repos=repos, signals_list=signals)

        assert all(isinstance(r, PublicRepoCorrelation) for r in result)

    def test_repo_url_in_result(self):
        """Correlation result includes the repo URL."""
        from claude_candidate.correlator import correlate_repos

        repos = [make_repo_info(name="py-app", language="Python")]
        signals = [make_signals(session_id="s1", technologies=["python"])]

        result = correlate_repos(repos=repos, signals_list=signals)

        assert result[0].repo_url == "https://github.com/octocat/py-app"

    def test_empty_repos_returns_empty(self):
        """Returns empty list when no repos are provided."""
        from claude_candidate.correlator import correlate_repos

        signals = [make_signals(session_id="s1", technologies=["python"])]
        result = correlate_repos(repos=[], signals_list=signals)
        assert result == []

    def test_empty_signals_returns_empty(self):
        """Returns empty list when no signals are provided."""
        from claude_candidate.correlator import correlate_repos

        repos = [make_repo_info(name="py-app", language="Python")]
        result = correlate_repos(repos=repos, signals_list=[])
        assert result == []

    def test_session_ids_included(self):
        """Correlation result session_ids contains matching session ids."""
        from claude_candidate.correlator import correlate_repos

        repos = [make_repo_info(name="py-app", language="Python")]
        signals = [
            make_signals(session_id="s1", technologies=["python"]),
            make_signals(session_id="s2", technologies=["python"]),
        ]

        result = correlate_repos(repos=repos, signals_list=signals)

        assert "s1" in result[0].session_ids
        assert "s2" in result[0].session_ids

    def test_topics_contribute_to_overlap(self):
        """Repo topics that match session technologies are counted."""
        from claude_candidate.correlator import correlate_repos

        repos = [make_repo_info(name="tools", language=None, topics=["docker", "pytest"])]
        signals = [make_signals(session_id="s1", technologies=["docker", "pytest"])]

        result = correlate_repos(repos=repos, signals_list=signals)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# TestComputeTechOverlap
# ---------------------------------------------------------------------------


class TestComputeTechOverlap:
    def test_language_counts_as_overlap(self):
        from claude_candidate.correlator import _compute_tech_overlap

        repo = make_repo_info(name="r", language="Python")
        count = _compute_tech_overlap(repo, {"python", "fastapi"})
        assert count >= 1

    def test_topic_counts_as_overlap(self):
        from claude_candidate.correlator import _compute_tech_overlap

        repo = make_repo_info(name="r", language=None, topics=["react", "typescript"])
        count = _compute_tech_overlap(repo, {"react", "typescript"})
        assert count >= 2

    def test_no_overlap_is_zero(self):
        from claude_candidate.correlator import _compute_tech_overlap

        repo = make_repo_info(name="r", language="Go", topics=[])
        count = _compute_tech_overlap(repo, {"python", "fastapi"})
        assert count == 0

    def test_language_none_does_not_crash(self):
        from claude_candidate.correlator import _compute_tech_overlap

        repo = make_repo_info(name="r", language=None)
        count = _compute_tech_overlap(repo, {"python"})
        assert count == 0


# ---------------------------------------------------------------------------
# TestDetermineCorrelationType
# ---------------------------------------------------------------------------


class TestDetermineCorrelationType:
    def test_combined_when_temporal_and_tech(self):
        from claude_candidate.correlator import _determine_correlation_type

        result = _determine_correlation_type(2, has_temporal=True)
        assert result == "combined"

    def test_content_reference_when_only_tech(self):
        from claude_candidate.correlator import _determine_correlation_type

        result = _determine_correlation_type(2, has_temporal=False)
        assert result == "content_reference"

    def test_temporal_when_no_overlap_but_temporal(self):
        from claude_candidate.correlator import _determine_correlation_type

        result = _determine_correlation_type(0, has_temporal=True)
        assert result == "temporal"

    def test_content_reference_for_overlap_only(self):
        from claude_candidate.correlator import _determine_correlation_type

        result = _determine_correlation_type(1, has_temporal=False)
        assert result == "content_reference"


# ---------------------------------------------------------------------------
# TestDetermineStrength
# ---------------------------------------------------------------------------


class TestDetermineStrength:
    def test_strong_for_three_plus(self):
        from claude_candidate.correlator import _determine_strength

        assert _determine_strength(3) == "strong"
        assert _determine_strength(5) == "strong"
        assert _determine_strength(10) == "strong"

    def test_moderate_for_two(self):
        from claude_candidate.correlator import _determine_strength

        assert _determine_strength(2) == "moderate"

    def test_weak_for_one(self):
        from claude_candidate.correlator import _determine_strength

        assert _determine_strength(1) == "weak"


# ---------------------------------------------------------------------------
# TestPublicRepoCorrelationRoundTrip
# ---------------------------------------------------------------------------


class TestPublicRepoCorrelationRoundTrip:
    def test_schema_round_trip(self):
        """PublicRepoCorrelation serializes and deserializes correctly."""
        corr = PublicRepoCorrelation(
            repo_url="https://github.com/octocat/my-repo",
            repo_name="my-repo",
            session_ids=["sess-001", "sess-002"],
            commit_hashes=[],
            correlation_type="content_reference",
            correlation_strength="moderate",
            notes="Matched via python language",
        )
        json_str = corr.model_dump_json()
        restored = PublicRepoCorrelation.model_validate_json(json_str)

        assert restored.repo_name == "my-repo"
        assert restored.session_ids == ["sess-001", "sess-002"]
        assert restored.correlation_type == "content_reference"
        assert restored.correlation_strength == "moderate"

    def test_invalid_correlation_type_raises(self):
        """Validation error for unknown correlation_type."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PublicRepoCorrelation(
                repo_url="https://github.com/x/y",
                repo_name="y",
                session_ids=[],
                commit_hashes=[],
                correlation_type="unknown_type",  # type: ignore[arg-type]
                correlation_strength="weak",
                notes="",
            )

    def test_invalid_strength_raises(self):
        """Validation error for unknown correlation_strength."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PublicRepoCorrelation(
                repo_url="https://github.com/x/y",
                repo_name="y",
                session_ids=[],
                commit_hashes=[],
                correlation_type="temporal",
                correlation_strength="ultra_strong",  # type: ignore[arg-type]
                notes="",
            )
