"""
GitHub Public Repo Correlator

Fetches a candidate's public GitHub repos and correlates them with session
evidence (technology overlap, filename matching) to produce corroboration
records for the SessionManifest.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from claude_candidate.extractor import SessionSignals
from claude_candidate.schemas.session_manifest import PublicRepoCorrelation


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RepoInfo:
    """Lightweight representation of a GitHub repository."""

    name: str
    full_name: str
    url: str
    language: str | None
    topics: list[str]
    created_at: str
    pushed_at: str
    description: str | None


# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------


def fetch_public_repos(github_user: str) -> list[RepoInfo]:
    """Fetch public repos for *github_user* from the GitHub API.

    Returns an empty list on any HTTP or network error.
    """
    try:
        resp = httpx.get(
            f"https://api.github.com/users/{github_user}/repos",
            params={"per_page": 100},
        )
        resp.raise_for_status()
        return [_parse_repo(r) for r in resp.json()]
    except (httpx.HTTPStatusError, httpx.RequestError):
        return []


def _parse_repo(raw: dict) -> RepoInfo:
    """Convert one GitHub API repo dict to a RepoInfo dataclass."""
    return RepoInfo(
        name=raw.get("name", ""),
        full_name=raw.get("full_name", ""),
        url=raw.get("html_url", ""),
        language=raw.get("language"),
        topics=raw.get("topics") or [],
        created_at=raw.get("created_at", ""),
        pushed_at=raw.get("pushed_at", ""),
        description=raw.get("description"),
    )


# ---------------------------------------------------------------------------
# Correlation helpers
# ---------------------------------------------------------------------------


def _compute_tech_overlap(repo: RepoInfo, session_techs: set[str]) -> int:
    """Count how many session technologies appear in the repo's language/topics."""
    repo_techs: set[str] = set()
    if repo.language:
        repo_techs.add(repo.language.lower())
    repo_techs.update(t.lower() for t in repo.topics)
    return len(repo_techs & session_techs)


def _determine_correlation_type(overlap: int, *, has_temporal: bool) -> str:
    """Return a correlation_type label based on overlap count and temporal flag."""
    if overlap > 0 and has_temporal:
        return "combined"
    if overlap > 0:
        return "content_reference"
    return "temporal"


def _determine_strength(overlap_count: int) -> str:
    """Map overlap count to a correlation_strength label."""
    if overlap_count >= 3:
        return "strong"
    if overlap_count == 2:
        return "moderate"
    return "weak"


# ---------------------------------------------------------------------------
# Main correlator
# ---------------------------------------------------------------------------


def _all_session_techs(signals_list: list[SessionSignals]) -> set[str]:
    """Aggregate all technologies from all sessions into a lowercase set."""
    techs: set[str] = set()
    for s in signals_list:
        techs.update(t.lower() for t in s.technologies)
    return techs


def _session_ids_for_tech(repo: RepoInfo, signals_list: list[SessionSignals]) -> list[str]:
    """Return session IDs whose technology set overlaps with this repo."""
    repo_techs: set[str] = set()
    if repo.language:
        repo_techs.add(repo.language.lower())
    repo_techs.update(t.lower() for t in repo.topics)
    return [
        s.session_id
        for s in signals_list
        if repo_techs & {t.lower() for t in s.technologies}
    ]


def _build_correlation(repo: RepoInfo, overlap: int, session_ids: list[str]) -> PublicRepoCorrelation:
    """Construct a PublicRepoCorrelation for a single repo."""
    corr_type = _determine_correlation_type(overlap, has_temporal=False)
    strength = _determine_strength(overlap)
    return PublicRepoCorrelation(
        repo_url=repo.url,
        repo_name=repo.name,
        session_ids=session_ids,
        commit_hashes=[],
        correlation_type=corr_type,
        correlation_strength=strength,
        notes=f"Technology overlap count: {overlap}",
    )


def correlate_repos(
    *,
    repos: list[RepoInfo],
    signals_list: list[SessionSignals],
) -> list[PublicRepoCorrelation]:
    """Correlate public repos with session signals by technology overlap.

    Returns one PublicRepoCorrelation per repo that has any overlap.
    """
    if not repos or not signals_list:
        return []
    all_techs = _all_session_techs(signals_list)
    results: list[PublicRepoCorrelation] = []
    for repo in repos:
        overlap = _compute_tech_overlap(repo, all_techs)
        if overlap == 0:
            continue
        session_ids = _session_ids_for_tech(repo, signals_list)
        results.append(_build_correlation(repo, overlap, session_ids))
    return results
