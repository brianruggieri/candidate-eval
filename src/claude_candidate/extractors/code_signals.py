"""
CodeSignalExtractor — Tier 1 extractor for traditional developer skills.

Detects languages, frameworks, tools, and platforms from code content via
four detection layers:
1. File extension mapping
2. Taxonomy content pattern matching
3. Import statement parsing
4. Package manager command parsing

Implements ExtractorProtocol.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from claude_candidate.extractors import (
	NormalizedSession,
	SignalResult,
	SkillSignal,
)
from claude_candidate.message_format import NormalizedMessage
from claude_candidate.skill_taxonomy import SkillTaxonomy

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SNIPPET_LENGTH = 500

FILE_EXTENSION_MAP: dict[str, list[str]] = {
	".py": ["python"],
	".js": ["javascript"],
	".ts": ["typescript"],
	".tsx": ["typescript", "react"],
	".jsx": ["javascript", "react"],
	".rs": ["rust"],
	".go": ["go"],
	".java": ["java"],
	".sql": ["postgresql"],
	".dockerfile": ["docker"],
	".yml": ["yaml"],
	".yaml": ["yaml"],
	".toml": ["toml"],
	".json": ["json"],
	".html": ["html"],
	".css": ["css"],
	".kt": ["kotlin"],
	".cs": ["csharp"],
	".c": ["c"],
	".cpp": ["cpp"],
	".h": ["c"],
	".hpp": ["cpp"],
}

DOCKERFILE_NAMES: set[str] = {"Dockerfile", "dockerfile"}

_PACKAGE_MAP_PATH = Path(__file__).parent.parent / "data" / "package_to_skill_map.json"

# Import statement regexes (compiled once)
_PYTHON_IMPORT_RE = re.compile(
	r'^\s*(?:from|import)\s+([\w.]+)', re.MULTILINE
)
_JS_TS_IMPORT_RE = re.compile(
	r'(?:import\s+.*?from\s+[\'"]|require\s*\(\s*[\'"])([@\w/.-]+)'
)
_RUST_IMPORT_RE = re.compile(
	r'^\s*use\s+([\w:]+)', re.MULTILINE
)
_GO_IMPORT_RE = re.compile(
	r'"([\w./]+)"'
)

# Package command regexes (compiled once)
_PIP_INSTALL_RE = re.compile(
	r'pip3?\s+install\s+(?:-[\w-]+\s+)*(.+)'
)
_NPM_INSTALL_RE = re.compile(
	r'(?:npm|yarn|pnpm|bun)\s+(?:install|add|i)\s+(?:-[\w-]+\s+)*(.+)'
)
_CARGO_ADD_RE = re.compile(
	r'cargo\s+(?:add|install)\s+(.+)'
)
_GO_GET_RE = re.compile(
	r'go\s+get\s+(.+)'
)


def _truncate(text: str, max_len: int = MAX_SNIPPET_LENGTH) -> str:
	"""Truncate text to max_len, appending ... if truncated."""
	if len(text) <= max_len:
		return text
	return text[: max_len - 3] + "..."


def _load_package_map() -> dict[str, str]:
	"""Load package-to-skill mapping from bundled JSON."""
	with open(_PACKAGE_MAP_PATH) as f:
		return json.load(f)


class CodeSignalExtractor:
	"""Extracts Tier 1 skills: languages, frameworks, tools, platforms from code content."""

	def __init__(self) -> None:
		self._taxonomy = SkillTaxonomy.load_default()
		self._content_patterns = self._taxonomy.get_content_patterns()
		self._package_map = _load_package_map()

	def name(self) -> str:
		return "code_signals"

	def extract_session(self, session: NormalizedSession) -> SignalResult:
		"""Run all 4 detection layers and produce a SignalResult."""
		skills: dict[str, list[SkillSignal]] = {}
		metrics: dict[str, float] = {
			"file_extension_count": 0,
			"content_pattern_count": 0,
			"import_count": 0,
			"package_command_count": 0,
		}

		for msg in session.messages:
			for block in msg["content"]:
				block_type = block.get("type", "")

				if block_type == "tool_use":
					tool_name = block.get("name", "")
					tool_input = block.get("input", {})

					file_path = tool_input.get("file_path", "")
					content = tool_input.get("content", "")
					command = tool_input.get("command", "")

					# Layer 1: File extension detection
					if file_path:
						self._detect_file_extension(
							file_path, skills, metrics,
						)

					# Layer 2: Content pattern detection (on tool_use content)
					if content:
						self._detect_content_patterns(
							content, skills, metrics,
						)

					# Layer 3: Import parsing (on code content)
					if content and file_path:
						self._detect_imports(
							content, file_path, skills, metrics,
						)

					# Layer 4: Package command parsing (Bash commands)
					if tool_name == "Bash" and command:
						self._detect_package_commands(
							command, skills, metrics,
						)

				elif block_type == "text":
					text = block.get("text", "")
					if text:
						# Layer 2: Content pattern detection (on text blocks)
						self._detect_content_patterns(
							text, skills, metrics,
						)

		return SignalResult(
			session_id=session.session_id,
			session_date=session.timestamp,
			project_context=session.project_context,
			git_branch=session.git_branch,
			skills=skills,
			metrics=metrics,
		)

	def _detect_file_extension(
		self,
		file_path: str,
		skills: dict[str, list[SkillSignal]],
		metrics: dict[str, float],
	) -> None:
		"""Layer 1: Detect skills from file extensions."""
		path = Path(file_path)
		file_name = path.name
		ext = path.suffix.lower()

		skill_names: list[str] = []

		# Check Dockerfile special names
		if file_name in DOCKERFILE_NAMES:
			skill_names.append("docker")
		elif ext in FILE_EXTENSION_MAP:
			skill_names = list(FILE_EXTENSION_MAP[ext])

		for skill_name in skill_names:
			canonical = self._taxonomy.canonicalize(skill_name)
			signal = SkillSignal(
				canonical_name=canonical,
				source="file_extension",
				confidence=0.9,
				evidence_snippet=_truncate(f"File: {file_path}"),
				evidence_type="direct_usage",
			)
			skills.setdefault(canonical, []).append(signal)
			metrics["file_extension_count"] += 1

	def _detect_content_patterns(
		self,
		text: str,
		skills: dict[str, list[SkillSignal]],
		metrics: dict[str, float],
	) -> None:
		"""Layer 2: Detect skills from taxonomy content patterns."""
		text_lower = text.lower()

		for canonical, patterns in self._content_patterns.items():
			for pattern in patterns:
				if pattern.lower() in text_lower:
					signal = SkillSignal(
						canonical_name=canonical,
						source="content_pattern",
						confidence=0.75,
						evidence_snippet=_truncate(text),
						evidence_type="direct_usage",
					)
					skills.setdefault(canonical, []).append(signal)
					metrics["content_pattern_count"] += 1
					# Only one match per skill per text block
					break

	def _detect_imports(
		self,
		content: str,
		file_path: str,
		skills: dict[str, list[SkillSignal]],
		metrics: dict[str, float],
	) -> None:
		"""Layer 3: Detect skills from import statements."""
		ext = Path(file_path).suffix.lower()

		# Choose regex based on file extension
		if ext == ".py":
			matches = _PYTHON_IMPORT_RE.findall(content)
			# For Python, extract top-level package name
			package_names = [m.split(".")[0] for m in matches]
		elif ext in {".js", ".ts", ".tsx", ".jsx"}:
			matches = _JS_TS_IMPORT_RE.findall(content)
			# For JS/TS, use the full package name (handles scoped packages)
			package_names = list(matches)
		elif ext == ".rs":
			matches = _RUST_IMPORT_RE.findall(content)
			# For Rust, extract top-level crate name
			package_names = [m.split("::")[0] for m in matches]
		elif ext == ".go":
			matches = _GO_IMPORT_RE.findall(content)
			package_names = list(matches)
		else:
			return

		for pkg in package_names:
			pkg_clean = pkg.strip()
			if not pkg_clean:
				continue

			# Look up in package_to_skill_map
			skill_name = self._package_map.get(pkg_clean)
			if skill_name is None:
				continue

			canonical = self._taxonomy.canonicalize(skill_name)
			signal = SkillSignal(
				canonical_name=canonical,
				source="import_statement",
				confidence=0.85,
				evidence_snippet=_truncate(f"import {pkg_clean} in {file_path}"),
				evidence_type="direct_usage",
			)
			skills.setdefault(canonical, []).append(signal)
			metrics["import_count"] += 1

	def _detect_package_commands(
		self,
		command: str,
		skills: dict[str, list[SkillSignal]],
		metrics: dict[str, float],
	) -> None:
		"""Layer 4: Detect skills from package manager install commands."""
		package_names: list[str] = []

		# Try each package manager pattern
		for regex in (_PIP_INSTALL_RE, _NPM_INSTALL_RE, _CARGO_ADD_RE, _GO_GET_RE):
			match = regex.search(command)
			if match:
				raw_packages = match.group(1)
				# Split on whitespace and filter out flags
				for token in raw_packages.split():
					token = token.strip()
					if token and not token.startswith("-"):
						package_names.append(token)
				break  # Only match one package manager per command

		for pkg in package_names:
			skill_name = self._package_map.get(pkg)
			if skill_name is None:
				continue

			canonical = self._taxonomy.canonicalize(skill_name)
			signal = SkillSignal(
				canonical_name=canonical,
				source="package_command",
				confidence=0.7,
				evidence_snippet=_truncate(f"Command: {command}"),
				evidence_type="direct_usage",
			)
			skills.setdefault(canonical, []).append(signal)
			metrics["package_command_count"] += 1
