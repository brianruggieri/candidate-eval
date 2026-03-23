"""Session scanner: discovers JSONL session log files."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SessionInfo(BaseModel):
    """Metadata about a discovered session file."""

    model_config = ConfigDict(frozen=True)

    path: Path
    session_id: str
    project_hint: str
    file_size_bytes: int = Field(ge=0)


@dataclass(frozen=True)
class ProjectSummary:
    """Aggregated metadata about a project directory (including its worktrees)."""

    project_hint: str           # canonical prefix (dir name before first --)
    display_name: str           # human-friendly (last segment after -git-)
    dir_names: tuple[str, ...]  # all directory names in this group
    session_count: int
    total_size_bytes: int
    oldest_mtime: float         # epoch timestamp of oldest session file
    newest_mtime: float         # epoch timestamp of newest session file


def _extract_display_name(dir_name: str) -> str:
    """Extract a human-friendly name from a Claude projects directory name.

    Examples:
        -Users-brianruggieri-git-candidate-eval  → candidate-eval
        -Users-brianruggieri-git-foo--worktrees-bar → foo  (worktrees stripped before call)
        -Users-brianruggieri → -Users-brianruggieri  (no -git- segment)
    """
    # Strip any worktree suffix first (defensive — caller should pass canonical)
    canonical = dir_name.split("--")[0]
    if "-git-" in canonical:
        return canonical.split("-git-")[-1]
    return canonical


def _canonical_project_key(dir_name: str) -> str:
    """Return the canonical project key: the part before the first '--'.

    This groups a project with all its worktree directories.
    """
    return dir_name.split("--")[0]


def discover_projects(projects_dir: Path) -> list[ProjectSummary]:
    """Discover projects under a Claude projects directory.

    Returns one ProjectSummary per canonical project (worktrees grouped with parent).
    Projects with no .jsonl session files are excluded.
    Results are sorted by display_name.
    """
    if not projects_dir.is_dir():
        return []

    # Group directories by canonical key
    groups: dict[str, list[str]] = {}
    for entry in projects_dir.iterdir():
        if not entry.is_dir():
            continue
        key = _canonical_project_key(entry.name)
        groups.setdefault(key, []).append(entry.name)

    summaries: list[ProjectSummary] = []
    for canonical_key, dir_names in groups.items():
        total_count = 0
        total_size = 0
        all_mtimes: list[float] = []

        for dir_name in dir_names:
            dir_path = projects_dir / dir_name
            jsonl_files = list(dir_path.glob("*.jsonl"))  # flat — sessions are not nested
            for f in jsonl_files:
                st = os.stat(f)
                total_count += 1
                total_size += st.st_size
                all_mtimes.append(st.st_mtime)

        if total_count == 0:
            continue  # skip projects with no sessions

        summaries.append(ProjectSummary(
            project_hint=canonical_key,
            display_name=_extract_display_name(canonical_key),
            dir_names=tuple(sorted(dir_names)),
            session_count=total_count,
            total_size_bytes=total_size,
            oldest_mtime=min(all_mtimes),
            newest_mtime=max(all_mtimes),
        ))

    summaries.sort(key=lambda p: p.display_name.lower())
    return summaries


def _extract_project_hint(path: Path) -> str:
    """Extract project directory name from session file path."""
    return path.parent.name


def _build_session_info(jsonl_path: Path) -> SessionInfo:
    """Create SessionInfo from a discovered JSONL file."""
    return SessionInfo(
        path=jsonl_path,
        session_id=jsonl_path.stem,
        project_hint=_extract_project_hint(jsonl_path),
        file_size_bytes=jsonl_path.stat().st_size,
    )


def discover_sessions(
    projects_dir: Path,
) -> list[SessionInfo]:
    """Find all JSONL session files under a projects directory."""
    if not projects_dir.is_dir():
        return []

    sessions = [
        _build_session_info(p)
        for p in sorted(projects_dir.rglob("*.jsonl"))
    ]
    return sessions
