"""
Local repository filesystem scanner.

Scans a local directory tree to extract RepoEvidence — language usage, test coverage,
CI configuration, dependency graphs, and AI-tooling maturity signals.

Used by the v0.7 depth model to generate evidence from local repos before or
instead of the GitHub API scanner.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_candidate.schemas.repo_profile import RepoEvidence

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FILE_EXTENSION_MAP: dict[str, str] = {
	".py": "Python",
	".ts": "TypeScript",
	".tsx": "TypeScript",
	".js": "JavaScript",
	".jsx": "JavaScript",
	".rs": "Rust",
	".go": "Go",
	".java": "Java",
	".rb": "Ruby",
	".sh": "Shell",
	".bash": "Shell",
	".css": "CSS",
	".html": "HTML",
	".sql": "SQL",
	".swift": "Swift",
	".kt": "Kotlin",
	".c": "C",
	".h": "C",
	".cpp": "C++",
	".hpp": "C++",
	".cs": "C#",
	".dart": "Dart",
	".vue": "Vue",
	".svelte": "Svelte",
}

SKIP_DIRS: set[str] = {
	"node_modules",
	".git",
	"__pycache__",
	".venv",
	"venv",
	"dist",
	"build",
	".next",
	"target",
	".tox",
}

LLM_IMPORT_PATTERNS: list[str] = [
	"anthropic",
	"openai",
	"langchain",
	"llama_index",
	"transformers",
	"cohere",
	"together",
	"groq",
	"mistralai",
]

# Data file path, resolved relative to this module's location
_DATA_DIR = Path(__file__).parent / "data"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _get_repo_name(path: Path) -> str:
	"""
	Resolve the canonical repo name.

	Preference order:
	  1. Remote origin URL slug (e.g. "candidate-eval" from …/candidate-eval.git)
	  2. Directory name of the path
	"""
	try:
		result = subprocess.run(
			["git", "-C", str(path), "remote", "get-url", "origin"],
			capture_output=True,
			text=True,
			timeout=10,
		)
		url = result.stdout.strip()
		if url:
			# Extract last path segment, strip .git suffix
			slug = url.rstrip("/").split("/")[-1]
			if slug.endswith(".git"):
				slug = slug[:-4]
			if slug:
				return slug
	except Exception:
		pass
	return path.name


def scan_local_repo(path: Path) -> RepoEvidence:
	"""Full filesystem scan orchestrator — returns RepoEvidence for a local repo."""
	languages = _detect_languages(path)
	deps, dev_deps = _parse_dependencies(path)
	has_tests, test_framework, test_file_count = _detect_tests(path)
	has_ci, ci_complexity = _detect_ci(path)
	ai_signals = _detect_ai_signals(path)
	ai_maturity = _compute_ai_maturity(ai_signals)
	created_at, last_pushed, commit_span_days = _git_commit_span(path)
	releases = _count_releases(path)
	file_count, directory_depth, source_modules = _count_architecture_signals(path)

	has_changelog = (
		(path / "CHANGELOG.md").exists()
		or (path / "CHANGELOG").exists()
		or (path / "CHANGES.md").exists()
		or (path / "HISTORY.md").exists()
	)

	return RepoEvidence(
		name=_get_repo_name(path),
		url=None,
		description=None,
		created_at=created_at,
		last_pushed=last_pushed,
		commit_span_days=commit_span_days,
		languages=languages,
		dependencies=deps,
		dev_dependencies=dev_deps,
		has_tests=has_tests,
		test_framework=test_framework,
		test_file_count=test_file_count,
		has_ci=has_ci,
		ci_complexity=ci_complexity,
		releases=releases,
		has_changelog=has_changelog,
		# AI signals (flat)
		has_claude_md=ai_signals["has_claude_md"],
		has_agents_md=ai_signals["has_agents_md"],
		has_copilot_instructions=ai_signals["has_copilot_instructions"],
		llm_imports=ai_signals["llm_imports"],
		has_eval_framework=ai_signals["has_eval_framework"],
		has_prompt_templates=ai_signals["has_prompt_templates"],
		claude_dir_exists=ai_signals["claude_dir_exists"],
		claude_plans_count=ai_signals["claude_plans_count"],
		claude_specs_count=ai_signals["claude_specs_count"],
		claude_handoffs_count=ai_signals["claude_handoffs_count"],
		claude_grill_sessions=ai_signals["claude_grill_sessions"],
		claude_memory_files=ai_signals["claude_memory_files"],
		has_settings_local=ai_signals["has_settings_local"],
		has_ralph_loops=ai_signals["has_ralph_loops"],
		has_superpowers_brainstorms=ai_signals["has_superpowers_brainstorms"],
		has_worktree_discipline=ai_signals["has_worktree_discipline"],
		ai_maturity_level=ai_maturity,
		# Scale
		file_count=file_count,
		directory_depth=directory_depth,
		source_modules=source_modules,
	)


# ---------------------------------------------------------------------------
# Helper: language detection
# ---------------------------------------------------------------------------


def _detect_languages(path: Path) -> dict[str, int]:
	"""Walk files and count bytes by extension, skipping build/vendor dirs."""
	totals: dict[str, int] = {}

	for item in path.rglob("*"):
		# Skip blacklisted directory names anywhere in the path
		if any(part in SKIP_DIRS for part in item.parts):
			continue
		if not item.is_file():
			continue
		lang = FILE_EXTENSION_MAP.get(item.suffix.lower())
		if lang is None:
			continue
		try:
			size = item.stat().st_size
		except OSError:
			continue
		totals[lang] = totals.get(lang, 0) + size

	return totals


# ---------------------------------------------------------------------------
# Helper: dependency parsing
# ---------------------------------------------------------------------------


def _load_package_map() -> dict[str, str]:
	"""Load the package-to-skill mapping from the data directory."""
	map_path = _DATA_DIR / "package_to_skill_map.json"
	try:
		return json.loads(map_path.read_text())
	except (OSError, json.JSONDecodeError):
		return {}


def _resolve_package(name: str, pkg_map: dict[str, str]) -> str:
	"""Resolve a package name to a canonical skill name."""
	# Normalise: lowercase, replace hyphens with underscores for lookup
	key = name.lower().replace("-", "_")
	# Try original name first, then normalised form
	return pkg_map.get(name.lower(), pkg_map.get(key, name))


def _extract_toml_deps(
	data: dict[str, Any],
	pkg_map: dict[str, str],
) -> tuple[list[str], list[str]]:
	"""Extract production and dev deps from parsed pyproject.toml data."""
	prod_raw: list[str] = []
	dev_raw: list[str] = []

	project = data.get("project", {})
	# Production deps: [project.dependencies]
	for dep in project.get("dependencies", []):
		# PEP 508: split on extras/version specifiers
		name = re.split(r"[\[>=<!;,\s]", dep)[0].strip()
		if name:
			prod_raw.append(name)

	# Optional/dev deps: [project.optional-dependencies]
	opt_deps = project.get("optional-dependencies", {})
	for _group, deps in opt_deps.items():
		for dep in deps:
			name = re.split(r"[\[>=<!;,\s]", dep)[0].strip()
			if name:
				dev_raw.append(name)

	# Also pick up tool.pytest config as evidence of pytest
	tool = data.get("tool", {})
	if "pytest" in tool or "pytest.ini_options" in tool:
		if "pytest" not in dev_raw:
			dev_raw.append("pytest")

	prod = [_resolve_package(p, pkg_map) for p in prod_raw]
	dev = [_resolve_package(p, pkg_map) for p in dev_raw]
	return prod, dev


def _extract_package_json_deps(
	data: dict[str, Any],
	pkg_map: dict[str, str],
) -> tuple[list[str], list[str]]:
	prod = [
		_resolve_package(k, pkg_map) for k in data.get("dependencies", {})
	]
	dev = [
		_resolve_package(k, pkg_map) for k in data.get("devDependencies", {})
	]
	return prod, dev


def _extract_cargo_deps(
	data: dict[str, Any],
	pkg_map: dict[str, str],
) -> tuple[list[str], list[str]]:
	prod = [_resolve_package(k, pkg_map) for k in data.get("dependencies", {})]
	dev = [_resolve_package(k, pkg_map) for k in data.get("dev-dependencies", {})]
	return prod, dev


def _parse_dependencies(path: Path) -> tuple[list[str], list[str]]:
	"""Parse dependencies from pyproject.toml, package.json, or Cargo.toml."""
	pkg_map = _load_package_map()

	# Try pyproject.toml first
	pyproject = path / "pyproject.toml"
	if pyproject.exists():
		try:
			data = tomllib.loads(pyproject.read_text())
			return _extract_toml_deps(data, pkg_map)
		except Exception:
			pass

	# Try package.json
	package_json = path / "package.json"
	if package_json.exists():
		try:
			data = json.loads(package_json.read_text())
			return _extract_package_json_deps(data, pkg_map)
		except Exception:
			pass

	# Try Cargo.toml
	cargo = path / "Cargo.toml"
	if cargo.exists():
		try:
			data = tomllib.loads(cargo.read_text())
			return _extract_cargo_deps(data, pkg_map)
		except Exception:
			pass

	return [], []


# ---------------------------------------------------------------------------
# Helper: test detection
# ---------------------------------------------------------------------------


_TEST_FILE_PATTERNS = [
	"test_*.py",
	"*_test.py",
	"*.test.ts",
	"*.test.js",
	"*.spec.ts",
	"*.spec.js",
	"*_test.rs",
	"*_test.go",
]


def _detect_tests(path: Path) -> tuple[bool, str | None, int]:
	"""Returns (has_tests, test_framework, test_file_count)."""
	framework: str | None = None
	test_files: set[Path] = set()

	# Collect test files
	for pat in _TEST_FILE_PATTERNS:
		for f in path.rglob(pat):
			if not any(part in SKIP_DIRS for part in f.parts):
				test_files.add(f)

	count = len(test_files)
	has_tests = count > 0

	# Determine framework
	# pytest: pyproject.toml [tool.pytest], pytest.ini, setup.cfg [tool:pytest]
	pyproject = path / "pyproject.toml"
	if pyproject.exists():
		try:
			data = tomllib.loads(pyproject.read_text())
			tool = data.get("tool", {})
			if "pytest" in tool or "pytest.ini_options" in tool:
				framework = "pytest"
		except Exception:
			pass

	if framework is None and (path / "pytest.ini").exists():
		framework = "pytest"

	if framework is None and (path / "setup.cfg").exists():
		try:
			content = (path / "setup.cfg").read_text()
			if "[tool:pytest]" in content:
				framework = "pytest"
		except OSError:
			pass

	# Jest / Vitest
	if framework is None:
		for name in ("jest.config.js", "jest.config.ts", "jest.config.mjs"):
			if (path / name).exists():
				framework = "jest"
				break

	if framework is None:
		for name in ("vitest.config.js", "vitest.config.ts", "vitest.config.mts"):
			if (path / name).exists():
				framework = "vitest"
				break

	# Bun test
	if framework is None and (path / ".bun-test").exists():
		framework = "bun"

	# Rust / cargo test
	if framework is None:
		cargo = path / "Cargo.toml"
		if cargo.exists():
			try:
				data = tomllib.loads(cargo.read_text())
				dev_deps = data.get("dev-dependencies", {})
				test_frameworks = {"tokio-test", "mockall", "pretty_assertions"}
				if test_frameworks & set(dev_deps):
					framework = "cargo"
			except Exception:
				pass
			if framework is None and count > 0:
				framework = "cargo"

	# Fall back: if we found test files and still no framework, try inferring from files
	if framework is None and count > 0:
		py_tests = [f for f in test_files if f.suffix == ".py"]
		ts_tests = [f for f in test_files if f.suffix in (".ts", ".tsx")]
		js_tests = [f for f in test_files if f.suffix in (".js", ".jsx")]
		if py_tests:
			framework = "pytest"  # most common Python test runner
		elif ts_tests or js_tests:
			framework = "jest"

	return has_tests, framework, count


# ---------------------------------------------------------------------------
# Helper: CI detection
# ---------------------------------------------------------------------------


def _detect_ci(path: Path) -> tuple[bool, str]:
	"""Returns (has_ci, ci_complexity)."""
	has_ci = False
	workflow_files: list[Path] = []

	# GitHub Actions
	gh_workflows = path / ".github" / "workflows"
	if gh_workflows.is_dir():
		workflow_files = [f for f in gh_workflows.rglob("*.yml")]
		workflow_files += [f for f in gh_workflows.rglob("*.yaml")]
		if workflow_files:
			has_ci = True

	# GitLab CI
	if (path / ".gitlab-ci.yml").exists():
		has_ci = True

	# Jenkins
	if (path / "Jenkinsfile").exists():
		has_ci = True

	# CircleCI
	if (path / ".circleci" / "config.yml").exists():
		has_ci = True

	# Travis CI
	if (path / ".travis.yml").exists():
		has_ci = True

	if not has_ci:
		return False, "basic"

	# Compute complexity from GitHub Actions workflows
	complexity = "basic"
	if workflow_files:
		total_jobs = 0
		has_matrix = False
		has_reusable = False
		has_deploy = False
		for wf in workflow_files:
			try:
				content = wf.read_text()
				# Count jobs roughly
				total_jobs += content.count("\n  jobs:") + content.count("\njobs:")
				if "matrix:" in content:
					has_matrix = True
				if "uses:" in content and ".github/workflows/" in content:
					has_reusable = True
				if any(
					kw in content.lower()
					for kw in ("deploy", "release", "publish", "production", "staging")
				):
					has_deploy = True
			except OSError:
				pass

		if has_reusable or (has_deploy and has_matrix):
			complexity = "advanced"
		elif len(workflow_files) > 1 or has_matrix:
			complexity = "standard"

	return True, complexity


# ---------------------------------------------------------------------------
# Helper: AI signal detection
# ---------------------------------------------------------------------------


def _scan_llm_imports(path: Path) -> list[str]:
	"""Scan .py/.ts/.js files for LLM SDK imports."""
	found: set[str] = set()
	extensions = {".py", ".ts", ".tsx", ".js", ".jsx"}

	for f in path.rglob("*"):
		if any(part in SKIP_DIRS for part in f.parts):
			continue
		if not f.is_file() or f.suffix.lower() not in extensions:
			continue
		try:
			content = f.read_text(errors="ignore")
		except OSError:
			continue
		for pkg in LLM_IMPORT_PATTERNS:
			if pkg in found:
				continue
			# Match: import anthropic, from anthropic import ..., import("anthropic"), require("anthropic")
			pattern = re.compile(
				rf"(?:import\s+{re.escape(pkg)}"
				rf"|from\s+{re.escape(pkg)}\s"
				rf"|import\(['\"]?{re.escape(pkg)}"
				rf"|require\(['\"]?{re.escape(pkg)})",
				re.MULTILINE,
			)
			if pattern.search(content):
				found.add(pkg)

	return sorted(found)


def _count_md_files_in_dirs(path: Path, *dir_patterns: str) -> int:
	"""Count .md files under directories matching any of the given names."""
	count = 0
	for pattern in dir_patterns:
		for d in path.rglob(pattern):
			if d.is_dir():
				count += sum(1 for f in d.rglob("*.md") if f.is_file())
	return count


def _detect_ai_signals(path: Path) -> dict[str, Any]:
	"""Detect AI tooling signals in the repo."""
	claude_dir = path / ".claude"

	has_claude_md = (path / "CLAUDE.md").exists()
	has_agents_md = (path / "AGENTS.md").exists()
	has_copilot_instructions = (path / ".github" / "copilot-instructions.md").exists()

	llm_imports = _scan_llm_imports(path)

	# Eval framework: golden_set dir, benchmark scripts, or "eval" in dir names
	has_eval_framework = False
	for candidate in ("golden_set", "golden-set", "eval", "evals", "benchmark"):
		# Check both top-level and under tests/
		if (path / candidate).is_dir():
			has_eval_framework = True
			break
		if (path / "tests" / candidate).is_dir():
			has_eval_framework = True
			break
	if not has_eval_framework:
		# Look for benchmark scripts
		for f in path.rglob("benchmark*.py"):
			if not any(part in SKIP_DIRS for part in f.parts):
				has_eval_framework = True
				break

	# Prompt templates: prompt dir, .prompt files, or template files with prompt/system in name
	has_prompt_templates = False
	for d_name in ("prompts", "prompt", "templates"):
		if (path / d_name).is_dir():
			has_prompt_templates = True
			break
	if not has_prompt_templates:
		for f in path.rglob("*.prompt"):
			if not any(part in SKIP_DIRS for part in f.parts):
				has_prompt_templates = True
				break
	if not has_prompt_templates:
		# Files with prompt or system_prompt in name
		for f in path.rglob("*"):
			if any(part in SKIP_DIRS for part in f.parts):
				continue
			if not f.is_file():
				continue
			lower = f.name.lower()
			if ("prompt" in lower or "system_prompt" in lower) and f.suffix in (
				".py",
				".ts",
				".js",
				".txt",
				".md",
			):
				has_prompt_templates = True
				break

	claude_dir_exists = claude_dir.is_dir()

	# Plans: .claude/plans/*.md or docs/*/plans/*.md
	claude_plans_count = 0
	if (claude_dir / "plans").is_dir():
		claude_plans_count += sum(1 for f in (claude_dir / "plans").rglob("*.md") if f.is_file())
	claude_plans_count += _count_md_files_in_dirs(path / "docs", "plans")

	# Specs: .claude/specs/*.md or docs/*/specs/*.md
	claude_specs_count = 0
	if (claude_dir / "specs").is_dir():
		claude_specs_count += sum(1 for f in (claude_dir / "specs").rglob("*.md") if f.is_file())
	claude_specs_count += _count_md_files_in_dirs(path / "docs", "specs")

	# Handoffs: handoff*.md anywhere
	claude_handoffs_count = sum(
		1
		for f in path.rglob("handoff*.md")
		if f.is_file() and not any(part in SKIP_DIRS for part in f.parts)
	)

	# Grill sessions: grill*.md anywhere
	claude_grill_sessions = sum(
		1
		for f in path.rglob("grill*.md")
		if f.is_file() and not any(part in SKIP_DIRS for part in f.parts)
	)

	# Memory files: .claude/memory/ or .claude/projects/*/memory/
	claude_memory_files = 0
	memory_dir = claude_dir / "memory"
	if memory_dir.is_dir():
		claude_memory_files += sum(1 for f in memory_dir.rglob("*") if f.is_file())
	projects_dir = claude_dir / "projects"
	if projects_dir.is_dir():
		for proj in projects_dir.iterdir():
			pm = proj / "memory"
			if pm.is_dir():
				claude_memory_files += sum(1 for f in pm.rglob("*") if f.is_file())

	has_settings_local = (claude_dir / "settings.local.json").exists()

	# Ralph loops: "ralph-loop" or "ralph_loop" in any config/plan/doc file
	has_ralph_loops = False
	ralph_pattern = re.compile(r"ralph.loop|ralph_loop", re.IGNORECASE)
	search_dirs = [claude_dir, path / "docs", path / "scripts"]
	for d in search_dirs:
		if not d.is_dir():
			continue
		for f in d.rglob("*"):
			if not f.is_file():
				continue
			if f.suffix.lower() not in (".md", ".json", ".yml", ".yaml", ".txt", ".py"):
				continue
			try:
				if ralph_pattern.search(f.read_text(errors="ignore")):
					has_ralph_loops = True
					break
			except OSError:
				pass
		if has_ralph_loops:
			break
	# Also check pyproject.toml / package.json at root
	if not has_ralph_loops:
		for config_file in ("pyproject.toml", "package.json", "Makefile", "justfile"):
			cf = path / config_file
			if cf.exists():
				try:
					if ralph_pattern.search(cf.read_text(errors="ignore")):
						has_ralph_loops = True
						break
				except OSError:
					pass

	has_superpowers_brainstorms = (path / ".superpowers" / "brainstorm").is_dir()

	# Worktree discipline: .worktrees/ dir exists OR .gitignore contains "worktrees"
	has_worktree_discipline = (path / ".worktrees").is_dir()
	if not has_worktree_discipline:
		gitignore = path / ".gitignore"
		if gitignore.exists():
			try:
				if "worktrees" in gitignore.read_text():
					has_worktree_discipline = True
			except OSError:
				pass

	return {
		"has_claude_md": has_claude_md,
		"has_agents_md": has_agents_md,
		"has_copilot_instructions": has_copilot_instructions,
		"llm_imports": llm_imports,
		"has_eval_framework": has_eval_framework,
		"has_prompt_templates": has_prompt_templates,
		"claude_dir_exists": claude_dir_exists,
		"claude_plans_count": claude_plans_count,
		"claude_specs_count": claude_specs_count,
		"claude_handoffs_count": claude_handoffs_count,
		"claude_grill_sessions": claude_grill_sessions,
		"claude_memory_files": claude_memory_files,
		"has_settings_local": has_settings_local,
		"has_ralph_loops": has_ralph_loops,
		"has_superpowers_brainstorms": has_superpowers_brainstorms,
		"has_worktree_discipline": has_worktree_discipline,
	}


# ---------------------------------------------------------------------------
# Helper: AI maturity computation
# ---------------------------------------------------------------------------


def _compute_ai_maturity(signals: dict[str, Any]) -> str:
	"""
	Compute AI maturity level from signals dict.

	Tiers (each requires the previous):
	  basic        — has_claude_md
	  intermediate — + (llm_imports OR prompt_templates)
	  advanced     — + (has_eval_framework OR (plans_count > 0 AND specs_count > 0))
	  expert       — + (handoffs OR grill_sessions) + (ralph_loops OR settings_local)
	                 + (memory_files OR worktree_discipline)
	"""
	if not signals.get("has_claude_md"):
		return "basic"

	has_llm = bool(signals.get("llm_imports")) or signals.get("has_prompt_templates", False)
	if not has_llm:
		return "basic"

	has_advanced_work = signals.get("has_eval_framework", False) or (
		signals.get("claude_plans_count", 0) > 0 and signals.get("claude_specs_count", 0) > 0
	)
	if not has_advanced_work:
		return "intermediate"

	# Expert requires: (handoffs OR grill_sessions) + (ralph_loops OR settings_local)
	# + (memory_files OR worktree_discipline)
	has_protocol = (
		signals.get("claude_handoffs_count", 0) > 0
		or signals.get("claude_grill_sessions", 0) > 0
	)
	has_workflow_tools = signals.get("has_ralph_loops", False) or signals.get(
		"has_settings_local", False
	)
	has_persistence = (
		signals.get("claude_memory_files", 0) > 0
		or signals.get("has_worktree_discipline", False)
	)

	if has_protocol and has_workflow_tools and has_persistence:
		return "expert"

	return "advanced"


# ---------------------------------------------------------------------------
# Helper: git commit span
# ---------------------------------------------------------------------------


def _git_commit_span(path: Path) -> tuple[datetime, datetime, int]:
	"""
	Returns (created_at, last_pushed, commit_span_days) from git log.

	Falls back to epoch-based defaults if git is not available.
	"""
	_fallback = datetime(2000, 1, 1, tzinfo=timezone.utc)

	def _run(*args: str) -> str:
		result = subprocess.run(
			["git", "-C", str(path), *args],
			capture_output=True,
			text=True,
			timeout=15,
		)
		return result.stdout.strip()

	try:
		first_str = _run("log", "--reverse", "--format=%aI", "--max-parents=0", "--")
		# --max-parents=0 gives root commits; fall back to reverse log head
		if not first_str:
			first_str = _run("log", "--reverse", "--format=%aI")
			if "\n" in first_str:
				first_str = first_str.splitlines()[0]

		last_str = _run("log", "-1", "--format=%aI")

		if not first_str or not last_str:
			return _fallback, _fallback, 0

		created_at = datetime.fromisoformat(first_str)
		last_pushed = datetime.fromisoformat(last_str)

		# Ensure timezone-aware
		if created_at.tzinfo is None:
			created_at = created_at.replace(tzinfo=timezone.utc)
		if last_pushed.tzinfo is None:
			last_pushed = last_pushed.replace(tzinfo=timezone.utc)

		span = max(0, (last_pushed - created_at).days)
		return created_at, last_pushed, span

	except Exception:
		return _fallback, _fallback, 0


# ---------------------------------------------------------------------------
# Helper: release counting
# ---------------------------------------------------------------------------


def _count_releases(path: Path) -> int:
	"""Count git tags matching semver-like patterns (v0.1.0, 1.2.3, etc.)."""
	try:
		result = subprocess.run(
			["git", "-C", str(path), "tag", "--list"],
			capture_output=True,
			text=True,
			timeout=10,
		)
		tags = result.stdout.strip().splitlines()
		semver_re = re.compile(r"^v?\d+\.\d+(\.\d+)?")
		return sum(1 for t in tags if semver_re.match(t))
	except Exception:
		return 0


# ---------------------------------------------------------------------------
# Helper: architecture signals
# ---------------------------------------------------------------------------


def _count_architecture_signals(path: Path) -> tuple[int, int, int]:
	"""
	Returns (file_count, directory_depth, source_modules).

	file_count      — total tracked files (git ls-files | wc -l)
	directory_depth — max depth of any source directory
	source_modules  — count of top-level source directories (src/*, lib/*, etc.)
	"""
	# File count via git
	try:
		result = subprocess.run(
			["git", "-C", str(path), "ls-files"],
			capture_output=True,
			text=True,
			timeout=15,
		)
		file_count = len(result.stdout.strip().splitlines())
	except Exception:
		file_count = 0

	# Directory depth: walk all dirs, skip SKIP_DIRS, find max depth relative to path
	max_depth = 0
	try:
		for item in path.rglob("*"):
			if not item.is_dir():
				continue
			if any(part in SKIP_DIRS for part in item.parts):
				continue
			try:
				rel = item.relative_to(path)
				depth = len(rel.parts)
				if depth > max_depth:
					max_depth = depth
			except ValueError:
				pass
	except Exception:
		pass

	# Source modules: top-level source-like directories
	source_like = {"src", "lib", "pkg", "app", "core", "api", "backend", "frontend", "web"}
	source_modules = 0
	try:
		for d in path.iterdir():
			if d.is_dir() and d.name.lower() in source_like:
				source_modules += 1
	except Exception:
		pass

	return file_count, max_depth, source_modules
