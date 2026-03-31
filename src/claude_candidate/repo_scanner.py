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

from claude_candidate.commit_filter import RawCommit
from claude_candidate.schemas.repo_profile import RepoEvidence, RepoProfile, SkillRepoEvidence

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

_LLM_IMPORT_TO_SKILL: dict[str, str] = {
	"anthropic": "llm",
	"openai": "llm",
	"langchain": "llm",
	"llama_index": "llm",
	"transformers": "llm",
	"cohere": "llm",
	"together": "llm",
	"groq": "llm",
	"mistralai": "llm",
}

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
	skill_crafting = _detect_skill_crafting_signals(path)
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
		# Skill-crafting loop signals
		skill_crafting_signals=skill_crafting,
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
	prod = [_resolve_package(k, pkg_map) for k in data.get("dependencies", {})]
	dev = [_resolve_package(k, pkg_map) for k in data.get("devDependencies", {})]
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
	"test*.sh",
	"*_test.sh",
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
		signals.get("claude_handoffs_count", 0) > 0 or signals.get("claude_grill_sessions", 0) > 0
	)
	has_workflow_tools = signals.get("has_ralph_loops", False) or signals.get(
		"has_settings_local", False
	)
	has_persistence = signals.get("claude_memory_files", 0) > 0 or signals.get(
		"has_worktree_discipline", False
	)

	if has_protocol and has_workflow_tools and has_persistence:
		return "expert"

	return "advanced"


# ---------------------------------------------------------------------------
# Helper: skill-crafting loop detection
# ---------------------------------------------------------------------------


def _detect_skill_crafting_signals(path: Path) -> dict[str, int]:
	"""Detect skill-crafting loop evidence per the v0.8 spec.

	Returns counts for 7 signals that indicate meta-development patterns:
	iterating on AI skills, building eval harnesses, prompt iteration.

	Uses a single directory walk to avoid multiple rglob passes.
	"""
	# Collect paths in a single traversal
	skill_mds: list[Path] = []
	dirs_seen: set[Path] = set()
	prompt_iterations = 0
	grading_rubrics = 0
	skill_test_corpus = 0
	ab_test_evidence = 0

	for entry in path.rglob("*"):
		if any(part in SKIP_DIRS for part in entry.parts):
			continue

		if entry.is_dir():
			dirs_seen.add(entry)
			continue

		# Files only from here on
		if entry.name == "SKILL.md":
			skill_mds.append(entry)

		parent = entry.parent

		# 3. prompt_iterations: files in */prompts/*.md
		if parent.name == "prompts" and entry.suffix == ".md":
			prompt_iterations += 1
			# 7. grading_rubrics: */prompts/grade*.md
			if entry.name.startswith("grade"):
				grading_rubrics += 1

		# 4. skill_test_corpus: files in */tests/fixtures/ (direct children)
		if parent.name == "fixtures" and parent.parent and parent.parent.name == "tests":
			skill_test_corpus += 1

		# 5. ab_test_evidence: files in */evidence/ (direct children)
		if parent.name == "evidence":
			ab_test_evidence += 1

	# 1. skills_authored
	signals: dict[str, int] = {"skills_authored": len(skill_mds)}

	# 2. eval_harnesses: eval/ dirs that are siblings of SKILL.md
	eval_harnesses = 0
	for skill_md in skill_mds:
		if (skill_md.parent / "eval") in dirs_seen:
			eval_harnesses += 1
	signals["eval_harnesses"] = eval_harnesses

	signals["prompt_iterations"] = prompt_iterations
	signals["skill_test_corpus"] = skill_test_corpus
	signals["ab_test_evidence"] = ab_test_evidence

	# 6. meta_skill_count: SKILL.md files that reference other skills
	meta_skill_count = 0
	for skill_md in skill_mds:
		try:
			content = skill_md.read_text(errors="ignore")
			if "SKILL.md" in content or "invoke" in content.lower():
				meta_skill_count += 1
		except OSError:
			pass
	signals["meta_skill_count"] = meta_skill_count

	signals["grading_rubrics"] = grading_rubrics

	return signals


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
# Helper: raw commit fetching
# ---------------------------------------------------------------------------

_COMMIT_SEP = "\x1f"  # ASCII Unit Separator — used to delimit fields in git log


def _parse_numstat_log(output: str) -> list[RawCommit]:
	"""Parse the output of ``git log --format=COMMIT<US>%H<US>%s<US>%aI --numstat``.

	Each commit block starts with a COMMIT line followed by zero or more numstat
	lines (additions<TAB>deletions<TAB>path). Blocks are separated by blank lines.
	"""
	commits: list[RawCommit] = []
	current: RawCommit | None = None

	for line in output.splitlines():
		line = line.rstrip()
		if not line:
			continue

		if line.startswith(f"COMMIT{_COMMIT_SEP}"):
			# Flush previous commit
			if current is not None:
				commits.append(current)

			parts = line.split(_COMMIT_SEP)
			if len(parts) < 4:
				current = None
				continue

			_, hash_str, subject, date_str = parts[0], parts[1], parts[2], parts[3]
			try:
				ts = datetime.fromisoformat(date_str)
				if ts.tzinfo is None:
					ts = ts.replace(tzinfo=timezone.utc)
			except (ValueError, IndexError):
				ts = datetime(2000, 1, 1, tzinfo=timezone.utc)

			current = RawCommit(
				hash=hash_str,
				message=subject,
				timestamp=ts,
			)
			continue

		# Numstat line: additions<TAB>deletions<TAB>path
		if current is not None and "\t" in line:
			cols = line.split("\t")
			if len(cols) >= 3:
				try:
					add = int(cols[0]) if cols[0] != "-" else 0
					delete = int(cols[1]) if cols[1] != "-" else 0
					current.additions += add
					current.deletions += delete
					current.files_changed += 1
				except ValueError:
					pass

	# Flush final commit
	if current is not None:
		commits.append(current)

	return commits


def _fetch_raw_commits(path: Path, max_commits: int = 200) -> list[RawCommit]:
	"""Fetch raw commits from a local git repo using a single git log pass.

	Uses ``git log -N --format=COMMIT<US>%H<US>%s<US>%aI --numstat --`` to get
	commit metadata and diff stats in one call.

	Args:
		path: Path to the git repository.
		max_commits: Maximum number of commits to fetch.

	Returns:
		List of RawCommit objects, most recent first.
	"""
	fmt = f"COMMIT{_COMMIT_SEP}%H{_COMMIT_SEP}%s{_COMMIT_SEP}%aI"
	try:
		result = subprocess.run(
			[
				"git", "-C", str(path),
				"log", f"-{max_commits}",
				f"--format={fmt}",
				"--numstat",
				"--",
			],
			capture_output=True,
			text=True,
			timeout=30,
		)
		if result.returncode != 0:
			return []
		return _parse_numstat_log(result.stdout)
	except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
		return []


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


# ---------------------------------------------------------------------------
# GitHub API scanner
# ---------------------------------------------------------------------------

_DEFAULT_CACHE_DIR = Path.home() / ".claude-candidate" / "repo-cache"
_DEFAULT_SEARCH_DIRS = [
	Path.home() / "git",
	Path.home() / "projects",
	Path.home() / "code",
	Path.home() / "repos",
]


def _gh_api(endpoint: str) -> dict:
	"""
	Call `gh api <endpoint>` and return the parsed JSON result.

	Raises RuntimeError if gh is not authenticated or the call fails.
	"""
	try:
		result = subprocess.run(
			["gh", "api", endpoint],
			capture_output=True,
			text=True,
			timeout=30,
		)
	except FileNotFoundError:
		raise RuntimeError(
			"gh CLI not found. Install it from https://cli.github.com/ and run `gh auth login`."
		)

	if result.returncode != 0:
		raise RuntimeError(
			f"gh api {endpoint!r} failed (exit {result.returncode}): {result.stderr.strip()}"
		)

	try:
		return json.loads(result.stdout)
	except json.JSONDecodeError as exc:
		raise RuntimeError(
			f"gh api {endpoint!r} returned non-JSON output: {result.stdout[:200]!r}"
		) from exc


def _find_local_clone(
	repo_name: str,
	search_dirs: list[Path] | None = None,
) -> Path | None:
	"""
	Look for an existing local clone of *repo_name* in common directories.

	*repo_name* is the short name (the part after the slash in owner/repo).
	Returns the clone path if found, None otherwise.
	"""
	dirs = search_dirs if search_dirs is not None else _DEFAULT_SEARCH_DIRS
	for base in dirs:
		candidate = base / repo_name
		if candidate.is_dir() and (candidate / ".git").exists():
			return candidate
	return None


def scan_github_repo(
	repo_slug: str,
	cache_dir: Path | None = None,
) -> "RepoEvidence":
	"""
	Scan a GitHub repository and return RepoEvidence.

	Strategy (local-first):
	  1. Check common local directories for an existing clone.
	     If found, delegate to ``scan_local_repo()`` and set the URL from the slug.
	  2. If not found locally, check the cache dir (~/.claude-candidate/repo-cache/).
	     Re-clone only if the cache entry is absent or older than 24 hours.
	  3. Fetch repo metadata (created_at, description, pushed_at) and language bytes
	     from the GitHub API and override the values from the local/cached clone
	     (API data is more accurate for these fields).
	  4. Use the GitHub API release count instead of the local tag count (tags are
	     not fetched in treeless clones).

	Args:
		repo_slug: ``owner/repo`` string, e.g. ``"brianruggieri/claude-code-pulse"``.
		cache_dir:  Directory to store clones. Defaults to
		            ``~/.claude-candidate/repo-cache/``.

	Returns:
		:class:`~claude_candidate.schemas.repo_profile.RepoEvidence`
	"""
	import shutil
	from datetime import timedelta

	if "/" not in repo_slug:
		raise ValueError(f"repo_slug must be 'owner/repo', got: {repo_slug!r}")

	repo_name = repo_slug.split("/", 1)[1]
	clone_url = f"https://github.com/{repo_slug}.git"
	html_url = f"https://github.com/{repo_slug}"

	effective_cache_dir = cache_dir or _DEFAULT_CACHE_DIR

	# ------------------------------------------------------------------
	# 1. Local-first lookup
	# ------------------------------------------------------------------
	local_path = _find_local_clone(repo_name)
	if local_path is not None:
		evidence = scan_local_repo(local_path)
		# Override URL with canonical GitHub URL
		evidence = evidence.model_copy(update={"url": html_url})
		# Still fetch API metadata for accuracy
		try:
			meta = _gh_api(f"repos/{repo_slug}")
			lang_bytes = _gh_api(f"repos/{repo_slug}/languages")
			releases_data = _gh_api(f"repos/{repo_slug}/releases")
			created_at = datetime.fromisoformat(meta["created_at"].replace("Z", "+00:00"))
			last_pushed = datetime.fromisoformat(meta["pushed_at"].replace("Z", "+00:00"))
			evidence = evidence.model_copy(
				update={
					"created_at": created_at,
					"last_pushed": last_pushed,
					"description": meta.get("description"),
					"languages": lang_bytes,
					"releases": len(releases_data),
				}
			)
		except Exception:
			pass
		return evidence

	# ------------------------------------------------------------------
	# 2. Cache-based clone
	# ------------------------------------------------------------------
	effective_cache_dir.mkdir(parents=True, exist_ok=True)
	clone_path = effective_cache_dir / repo_name

	_24h = timedelta(hours=24)
	needs_clone = True
	if clone_path.exists() and (clone_path / ".git").exists():
		# Check age via git log timestamp of the HEAD commit
		try:
			result = subprocess.run(
				["git", "-C", str(clone_path), "log", "-1", "--format=%ct"],
				capture_output=True,
				text=True,
				timeout=10,
			)
			commit_ts = int(result.stdout.strip())
			commit_time = datetime.fromtimestamp(commit_ts, tz=timezone.utc)
			age = datetime.now(tz=timezone.utc) - commit_time
			# Re-clone if older than 24 hours
			if age < _24h:
				needs_clone = False
		except Exception:
			# Can't determine age — re-clone to be safe
			needs_clone = True

	if needs_clone:
		if clone_path.exists():
			shutil.rmtree(clone_path)
		# Treeless clone: full commit graph, no blob content fetched eagerly.
		# This is fast and still supports git log for commit span.
		subprocess.run(
			["git", "clone", "--filter=blob:none", clone_url, str(clone_path)],
			capture_output=True,
			check=True,
			timeout=300,
		)

	# ------------------------------------------------------------------
	# 3. Run local scanner on the cached clone
	# ------------------------------------------------------------------
	evidence = scan_local_repo(clone_path)

	# ------------------------------------------------------------------
	# 4. Override with GitHub API data (more accurate)
	# ------------------------------------------------------------------
	description: str | None = evidence.description
	created_at: datetime = evidence.created_at
	last_pushed: datetime = evidence.last_pushed
	lang_bytes: dict[str, int] = evidence.languages
	releases_count: int = evidence.releases

	try:
		meta = _gh_api(f"repos/{repo_slug}")
		lang_bytes = _gh_api(f"repos/{repo_slug}/languages")
		releases_data = _gh_api(f"repos/{repo_slug}/releases")
		description = meta.get("description")
		created_at = datetime.fromisoformat(meta["created_at"].replace("Z", "+00:00"))
		last_pushed = datetime.fromisoformat(meta["pushed_at"].replace("Z", "+00:00"))
		releases_count = len(releases_data)
	except Exception:
		# Fall back to locally-derived values already assigned above
		pass

	# Recompute commit_span_days from API timestamps (more reliable than treeless clone)
	commit_span_days = max(0, (last_pushed - created_at).days)

	evidence = evidence.model_copy(
		update={
			"name": repo_name,
			"url": html_url,
			"description": description,
			"created_at": created_at,
			"last_pushed": last_pushed,
			"commit_span_days": commit_span_days,
			"languages": lang_bytes,
			"releases": releases_count,
		}
	)

	return evidence


# ---------------------------------------------------------------------------
# Repo Profile Aggregation
# ---------------------------------------------------------------------------

# Map GitHub-style language names (from FILE_EXTENSION_MAP values / GH API)
# to canonical taxonomy skill names.
_LANGUAGE_TO_SKILL: dict[str, str] = {
	"Python": "python",
	"TypeScript": "typescript",
	"JavaScript": "javascript",
	"Shell": "shell",
	"Rust": "rust",
	"Go": "go",
	"Java": "java",
	"Ruby": "ruby",
	"C": "c",
	"C++": "cpp",
	"C#": "csharp",
	"Swift": "swift",
	"Kotlin": "kotlin",
	"Dart": "dart",
	"HTML": "html",
	"CSS": "css",
	"SQL": "sql",
	"Vue": "vue",
	"Svelte": "svelte",
}

# Map test file extensions back to language names for test_coverage detection.
_TEST_EXT_TO_LANGUAGE: dict[str, str] = {
	".py": "Python",
	".ts": "TypeScript",
	".tsx": "TypeScript",
	".js": "JavaScript",
	".jsx": "JavaScript",
	".rs": "Rust",
	".go": "Go",
	".sh": "Shell",
}


def _detect_test_languages(repo: RepoEvidence, path: Path | None = None) -> set[str]:
	"""
	Return the set of GitHub-style language names that have test coverage
	in this repo, based on test file extensions found.
	"""
	languages_with_tests: set[str] = set()

	if not repo.has_tests:
		return languages_with_tests

	# If we have the path, actually scan for test files and their extensions
	if path is not None:
		for pat in _TEST_FILE_PATTERNS:
			for f in path.rglob(pat):
				if any(part in SKIP_DIRS for part in f.parts):
					continue
				lang = _TEST_EXT_TO_LANGUAGE.get(f.suffix.lower())
				if lang:
					languages_with_tests.add(lang)
	else:
		# Infer from test_framework
		framework = repo.test_framework
		if framework in ("pytest",):
			languages_with_tests.add("Python")
		elif framework in ("jest", "vitest", "bun"):
			languages_with_tests.add("JavaScript")
			languages_with_tests.add("TypeScript")
		elif framework in ("cargo",):
			languages_with_tests.add("Rust")

	return languages_with_tests


def build_repo_profile(
	local_repos: list[Path] | None = None,
	github_repos: list[str] | None = None,
	output_path: Path | None = None,
) -> RepoProfile:
	"""
	Aggregate multiple repo scans into a single RepoProfile.

	Scans all local and GitHub repos, then rolls up per-skill evidence
	(language bytes, dependency signals, timeline, test coverage) and
	computes maturity stats.

	Args:
		local_repos:  List of local filesystem paths to scan.
		github_repos: List of ``owner/repo`` slugs to scan via GitHub API.
		output_path:  If provided, write the profile JSON to this path.

	Returns:
		:class:`~claude_candidate.schemas.repo_profile.RepoProfile`
	"""
	from claude_candidate.skill_taxonomy import SkillTaxonomy

	taxonomy = SkillTaxonomy.load_default()

	all_evidence: list[RepoEvidence] = []
	# Track the local paths for test language detection
	repo_paths: list[Path | None] = []

	# 1. Scan local repos
	for path in local_repos or []:
		evidence = scan_local_repo(path)
		all_evidence.append(evidence)
		repo_paths.append(path)

	# 2. Scan GitHub repos
	for slug in github_repos or []:
		evidence = scan_github_repo(slug)
		all_evidence.append(evidence)
		repo_paths.append(None)  # no local path for cached clones

	if not all_evidence:
		now = datetime.now(tz=timezone.utc)
		profile = RepoProfile(
			repos=[],
			scan_date=now,
			repo_timeline_start=now,
			repo_timeline_end=now,
			repo_timeline_days=0,
			skill_evidence={},
			repos_with_tests=0,
			repos_with_ci=0,
			repos_with_releases=0,
			repos_with_ai_signals=0,
		)
		if output_path is not None:
			output_path.parent.mkdir(parents=True, exist_ok=True)
			output_path.write_text(profile.model_dump_json(indent=2))
		return profile

	# 3. Aggregate per-skill evidence
	# Intermediate accumulator: skill_name -> {repos: set, bytes: int, ...}
	skill_acc: dict[str, dict] = {}

	def _ensure_skill(skill: str) -> dict:
		if skill not in skill_acc:
			skill_acc[skill] = {
				"repos": set(),
				"total_bytes": 0,
				"first_seen": None,
				"last_seen": None,
				"frameworks": set(),
				"test_coverage": False,
			}
		return skill_acc[skill]

	def _update_dates(acc: dict, created: datetime, pushed: datetime) -> None:
		if acc["first_seen"] is None or created < acc["first_seen"]:
			acc["first_seen"] = created
		if acc["last_seen"] is None or pushed > acc["last_seen"]:
			acc["last_seen"] = pushed

	for i, repo in enumerate(all_evidence):
		repo_path = repo_paths[i] if i < len(repo_paths) else None

		# Detect which languages have test coverage in this repo
		test_languages = _detect_test_languages(repo, repo_path)

		# 3a. Languages -> skill evidence
		for lang_name, byte_count in repo.languages.items():
			skill = _LANGUAGE_TO_SKILL.get(lang_name)
			if skill is None:
				# Fall back to taxonomy canonicalization
				skill = taxonomy.canonicalize(lang_name)
			acc = _ensure_skill(skill)
			acc["repos"].add(repo.name)
			acc["total_bytes"] += byte_count
			_update_dates(acc, repo.created_at, repo.last_pushed)
			if lang_name in test_languages:
				acc["test_coverage"] = True

		# 3b. Dependencies -> skill evidence (0 bytes, dependency-detected)
		for dep_skill in repo.dependencies:
			canonical = taxonomy.canonicalize(dep_skill)
			acc = _ensure_skill(canonical)
			acc["repos"].add(repo.name)
			# Don't add bytes — these are dependency signals, not language bytes
			_update_dates(acc, repo.created_at, repo.last_pushed)
			acc["frameworks"].add(canonical)

		# 3c. Dev dependencies -> skill evidence
		for dep_skill in repo.dev_dependencies:
			canonical = taxonomy.canonicalize(dep_skill)
			acc = _ensure_skill(canonical)
			acc["repos"].add(repo.name)
			_update_dates(acc, repo.created_at, repo.last_pushed)
			acc["frameworks"].add(canonical)

	# 3d. AI signals -> skill evidence
	for repo in all_evidence:
		# LLM imports -> "llm" skill
		for imp in repo.llm_imports:
			skill = _LLM_IMPORT_TO_SKILL.get(imp, "llm")
			canonical = taxonomy.canonicalize(skill)
			acc = _ensure_skill(canonical)
			acc["repos"].add(repo.name)
			_update_dates(acc, repo.created_at, repo.last_pushed)
			acc["frameworks"].add(imp)

		# Prompt templates -> "prompt-engineering"
		if repo.has_prompt_templates:
			acc = _ensure_skill("prompt-engineering")
			acc["repos"].add(repo.name)
			_update_dates(acc, repo.created_at, repo.last_pushed)

		# Eval framework -> "prompt-engineering" additional signal
		if repo.has_eval_framework:
			acc = _ensure_skill("prompt-engineering")
			acc["repos"].add(repo.name)
			_update_dates(acc, repo.created_at, repo.last_pushed)
			acc["frameworks"].add("eval-framework")

		# Claude Code maturity -> "ai-process-engineering" (threshold: 2+ signals)
		cc_signals = sum([
			repo.claude_plans_count > 0,
			repo.claude_specs_count > 0,
			repo.claude_handoffs_count > 0,
			repo.claude_grill_sessions > 0,
			repo.claude_memory_files > 0,
			repo.has_settings_local,
			repo.has_ralph_loops,
			repo.has_superpowers_brainstorms,
			repo.has_worktree_discipline,
		])
		if cc_signals >= 2:
			acc = _ensure_skill("ai-process-engineering")
			acc["repos"].add(repo.name)
			_update_dates(acc, repo.created_at, repo.last_pushed)
			if repo.claude_plans_count > 0:
				acc["frameworks"].add("claude-plans")
			if repo.claude_handoffs_count > 0:
				acc["frameworks"].add("claude-handoffs")
			if repo.has_ralph_loops:
				acc["frameworks"].add("ralph-loops")
			if repo.has_worktree_discipline:
				acc["frameworks"].add("worktree-discipline")
			if repo.claude_grill_sessions > 0:
				acc["frameworks"].add("grill-sessions")
			if repo.claude_memory_files > 0:
				acc["frameworks"].add("claude-memory")

		# Skill-crafting loop signals -> enrich ai-process-engineering
		sc = repo.skill_crafting_signals
		sc_total = sum(sc.values())
		if sc_total > 0:
			acc = _ensure_skill("ai-process-engineering")
			acc["repos"].add(repo.name)
			_update_dates(acc, repo.created_at, repo.last_pushed)
			if sc.get("skills_authored", 0) > 0:
				acc["frameworks"].add("skill-authoring")
			if sc.get("eval_harnesses", 0) > 0:
				acc["frameworks"].add("eval-harness")
			if sc.get("meta_skill_count", 0) > 0:
				acc["frameworks"].add("meta-skill-composition")
			if sc.get("grading_rubrics", 0) > 0:
				acc["frameworks"].add("grading-rubric")
			if sc.get("ab_test_evidence", 0) > 0:
				acc["frameworks"].add("ab-testing")
			if sc.get("prompt_iterations", 0) > 0:
				acc["frameworks"].add("prompt-iteration")

	# Convert accumulators to SkillRepoEvidence
	skill_evidence: dict[str, SkillRepoEvidence] = {}
	for skill, acc in skill_acc.items():
		skill_evidence[skill] = SkillRepoEvidence(
			repos=len(acc["repos"]),
			total_bytes=acc["total_bytes"],
			first_seen=acc["first_seen"],
			last_seen=acc["last_seen"],
			frameworks=sorted(acc["frameworks"]),
			test_coverage=acc["test_coverage"],
		)

	# 4. Compute timeline: earliest created_at -> latest last_pushed
	earliest = min(r.created_at for r in all_evidence)
	latest = max(r.last_pushed for r in all_evidence)
	timeline_days = max(0, (latest - earliest).days)

	# 5. Compute maturity stats
	repos_with_tests = sum(1 for r in all_evidence if r.has_tests)
	repos_with_ci = sum(1 for r in all_evidence if r.has_ci)
	repos_with_releases = sum(1 for r in all_evidence if r.releases > 0)
	repos_with_ai_signals = sum(
		1
		for r in all_evidence
		if r.has_claude_md or r.has_agents_md or r.has_copilot_instructions or r.llm_imports
	)

	profile = RepoProfile(
		repos=all_evidence,
		scan_date=datetime.now(tz=timezone.utc),
		repo_timeline_start=earliest,
		repo_timeline_end=latest,
		repo_timeline_days=timeline_days,
		skill_evidence=skill_evidence,
		repos_with_tests=repos_with_tests,
		repos_with_ci=repos_with_ci,
		repos_with_releases=repos_with_releases,
		repos_with_ai_signals=repos_with_ai_signals,
	)

	# 6. Optionally write to disk
	if output_path is not None:
		output_path.parent.mkdir(parents=True, exist_ok=True)
		output_path.write_text(profile.model_dump_json(indent=2))

	return profile
