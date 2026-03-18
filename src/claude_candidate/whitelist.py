"""Whitelist: persist and filter Claude Code sessions by project hint."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".claude-candidate"
WHITELIST_FILENAME = "whitelist.json"


@dataclass
class WhitelistConfig:
	projects: list[str] = field(default_factory=list)

	def is_whitelisted(self, project_hint: str) -> bool:
		return project_hint in self.projects


def load_whitelist(path: Path) -> WhitelistConfig | None:
	"""Load from disk. Returns None if not found."""
	if not path.exists():
		return None
	data = json.loads(path.read_text())
	return WhitelistConfig(projects=data.get("projects", []))


def save_whitelist(config: WhitelistConfig, path: Path) -> None:
	"""Save to disk. Creates parent dirs."""
	path.parent.mkdir(parents=True, exist_ok=True)
	path.write_text(json.dumps({"projects": config.projects}, indent=2))


def get_default_whitelist_path() -> Path:
	return DEFAULT_CONFIG_DIR / WHITELIST_FILENAME


def filter_sessions_by_whitelist(
	sessions: list[object],
	whitelist: WhitelistConfig,
) -> list[object]:
	"""Filter sessions to whitelisted projects only."""
	return [s for s in sessions if whitelist.is_whitelisted(s.project_hint)]  # type: ignore[attr-defined]
