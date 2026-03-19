"""Whitelist: persist and filter Claude Code sessions by project hint."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from claude_candidate.session_scanner import SessionInfo

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".claude-candidate"
WHITELIST_FILENAME = "whitelist.json"


@dataclass
class WhitelistConfig:
    projects: list[str] = field(default_factory=list)

    def is_whitelisted(self, project_hint: str) -> bool:
        return project_hint in self.projects


def load_whitelist(path: Path) -> WhitelistConfig | None:
    """Load from disk. Returns None if not found or corrupted."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return WhitelistConfig(projects=data.get("projects", []))
    except (json.JSONDecodeError, KeyError) as exc:
        logger.warning("Whitelist at %s is corrupted, ignoring: %s", path, exc)
        return None


def save_whitelist(config: WhitelistConfig, path: Path) -> None:
    """Save to disk. Creates parent dirs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"projects": config.projects}, indent=2))


def get_default_whitelist_path() -> Path:
    return DEFAULT_CONFIG_DIR / WHITELIST_FILENAME


def filter_sessions_by_whitelist(
    sessions: list[SessionInfo],
    whitelist: WhitelistConfig,
) -> list[SessionInfo]:
    """Filter sessions to whitelisted projects only."""
    return [s for s in sessions if whitelist.is_whitelisted(s.project_hint)]
