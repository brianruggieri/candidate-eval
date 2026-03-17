"""Session scanner: discovers JSONL session log files."""
from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class SessionInfo(BaseModel):
    """Metadata about a discovered session file."""

    model_config = ConfigDict(frozen=True)

    path: Path
    session_id: str
    project_hint: str
    file_size_bytes: int = Field(ge=0)


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
