"""Incremental extraction cache — skip unchanged session files."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from claude_candidate.session_scanner import SessionInfo


# Cache version — bump when extraction logic changes
CACHE_VERSION = "2"


def _cache_path() -> Path:
	return Path.home() / ".claude-candidate" / "extraction_cache.json"


def _hash_file(path: Path) -> str:
	"""Fast file hash using size + mtime + first/last 4KB."""
	stat = path.stat()
	hasher = hashlib.sha256()
	hasher.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
	with open(path, "rb") as f:
		hasher.update(f.read(4096))
		if stat.st_size > 4096:
			f.seek(-4096, 2)
			hasher.update(f.read(4096))
	return hasher.hexdigest()


def load_cache() -> dict[str, Any]:
	"""Load the extraction cache. Returns empty dict if missing or wrong version."""
	cp = _cache_path()
	if not cp.exists():
		return {}
	try:
		data = json.loads(cp.read_text())
		if data.get("version") != CACHE_VERSION:
			return {}
		return data.get("entries", {})
	except (json.JSONDecodeError, KeyError):
		return {}


def save_cache(entries: dict[str, Any]) -> None:
	"""Save the extraction cache."""
	cp = _cache_path()
	cp.parent.mkdir(parents=True, exist_ok=True)
	cp.write_text(json.dumps({"version": CACHE_VERSION, "entries": entries}, default=str))
