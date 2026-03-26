# Depth Model v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace session-based depth inference with resume-anchored + repo-evidenced skill profiling, redefine confidence as match quality.

**Architecture:** New `repo_scanner` module scans GitHub repos for tech stack, maturity, and AI signals. New `merge_triad()` combines resume (anchor) + repos (receipts). Matching engine moves confidence to match time and eliminates generic fallback matches.

**Tech Stack:** Python 3.13, pydantic v2, click, pytest, aiosqlite, GitHub API (via `gh` CLI)

---

### Task 1: Repo Scanner Schemas

**Files:**
- Create: `src/claude_candidate/schemas/repo_profile.py`
- Test: `tests/test_repo_profile.py`

- [ ] **Step 1: Write failing test for RepoEvidence model**

```python
# tests/test_repo_profile.py
from datetime import datetime, timezone

from claude_candidate.schemas.repo_profile import RepoEvidence, RepoProfile, SkillRepoEvidence


class TestRepoEvidence:
	def test_minimal_repo_evidence(self) -> None:
		ev = RepoEvidence(
			name="test-repo",
			url="https://github.com/user/test-repo",
			description="A test repo",
			created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
			last_pushed=datetime(2026, 3, 25, tzinfo=timezone.utc),
			commit_span_days=84,
			languages={"TypeScript": 250000, "JavaScript": 50000},
			dependencies=["react", "typescript", "jest"],
			dev_dependencies=["vitest", "eslint"],
			has_tests=True,
			test_framework="vitest",
			test_file_count=15,
			has_ci=True,
			ci_complexity="standard",
			releases=3,
			has_changelog=True,
			has_claude_md=True,
			has_agents_md=False,
			has_copilot_instructions=False,
			llm_imports=["anthropic"],
			has_eval_framework=False,
			has_prompt_templates=True,
			claude_dir_exists=True,
			claude_plans_count=5,
			claude_specs_count=2,
			claude_handoffs_count=8,
			claude_grill_sessions=1,
			claude_memory_files=3,
			has_settings_local=True,
			has_ralph_loops=False,
			has_superpowers_brainstorms=True,
			has_worktree_discipline=True,
			ai_maturity_level="advanced",
			file_count=180,
			directory_depth=4,
			source_modules=6,
		)
		assert ev.name == "test-repo"
		assert ev.ai_maturity_level == "advanced"
		assert ev.commit_span_days == 84

	def test_ai_maturity_must_be_valid(self) -> None:
		"""ai_maturity_level must be basic|intermediate|advanced|expert."""
		import pytest
		from pydantic import ValidationError

		with pytest.raises(ValidationError):
			RepoEvidence(
				name="bad",
				url=None,
				description=None,
				created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
				last_pushed=datetime(2026, 1, 1, tzinfo=timezone.utc),
				commit_span_days=0,
				languages={},
				dependencies=[],
				dev_dependencies=[],
				has_tests=False,
				test_framework=None,
				test_file_count=0,
				has_ci=False,
				ci_complexity="basic",
				releases=0,
				has_changelog=False,
				has_claude_md=False,
				has_agents_md=False,
				has_copilot_instructions=False,
				llm_imports=[],
				has_eval_framework=False,
				has_prompt_templates=False,
				claude_dir_exists=False,
				claude_plans_count=0,
				claude_specs_count=0,
				claude_handoffs_count=0,
				claude_grill_sessions=0,
				claude_memory_files=0,
				has_settings_local=False,
				has_ralph_loops=False,
				has_superpowers_brainstorms=False,
				has_worktree_discipline=False,
				ai_maturity_level="legendary",  # invalid
				file_count=0,
				directory_depth=0,
				source_modules=0,
			)


class TestSkillRepoEvidence:
	def test_skill_repo_evidence(self) -> None:
		sre = SkillRepoEvidence(
			repos=5,
			total_bytes=2_800_000,
			first_seen=datetime(2026, 1, 30, tzinfo=timezone.utc),
			last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
			frameworks=["react", "vitest", "bun"],
			test_coverage=True,
		)
		assert sre.repos == 5
		assert sre.frameworks == ["react", "vitest", "bun"]


class TestRepoProfile:
	def test_repo_profile_aggregation(self) -> None:
		profile = RepoProfile(
			repos=[],
			scan_date=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_start=datetime(2026, 1, 30, tzinfo=timezone.utc),
			repo_timeline_end=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_days=55,
			skill_evidence={},
			repos_with_tests=7,
			repos_with_ci=5,
			repos_with_releases=2,
			repos_with_ai_signals=4,
		)
		assert profile.repo_timeline_days == 55
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_repo_profile.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'claude_candidate.schemas.repo_profile'`

- [ ] **Step 3: Write the schema module**

```python
# src/claude_candidate/schemas/repo_profile.py
"""
RepoProfile: Evidence extracted from GitHub repos.

Produced by `repos scan`. Provides verifiable, concrete evidence of
what the candidate built — languages, dependencies, tests, CI/CD,
releases, and AI engineering artifacts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class RepoEvidence(BaseModel):
	"""Evidence extracted from a single repository."""

	name: str
	url: str | None
	description: str | None
	created_at: datetime
	last_pushed: datetime
	commit_span_days: int = Field(ge=0)

	# Tech stack (ground truth)
	languages: dict[str, int]  # language → bytes
	dependencies: list[str]  # resolved via package_to_skill_map
	dev_dependencies: list[str]  # test/build tooling

	# Maturity signals
	has_tests: bool
	test_framework: str | None
	test_file_count: int = Field(ge=0)
	has_ci: bool
	ci_complexity: Literal["basic", "standard", "advanced"]
	releases: int = Field(ge=0)
	has_changelog: bool

	# AI engineering signals
	has_claude_md: bool
	has_agents_md: bool
	has_copilot_instructions: bool
	llm_imports: list[str]
	has_eval_framework: bool
	has_prompt_templates: bool

	# Agentic development sophistication
	claude_dir_exists: bool
	claude_plans_count: int = Field(ge=0)
	claude_specs_count: int = Field(ge=0)
	claude_handoffs_count: int = Field(ge=0)
	claude_grill_sessions: int = Field(ge=0)
	claude_memory_files: int = Field(ge=0)
	has_settings_local: bool
	has_ralph_loops: bool
	has_superpowers_brainstorms: bool
	has_worktree_discipline: bool

	# AI maturity composite
	ai_maturity_level: Literal["basic", "intermediate", "advanced", "expert"]

	# Architecture signals
	file_count: int = Field(ge=0)
	directory_depth: int = Field(ge=0)
	source_modules: int = Field(ge=0)


class SkillRepoEvidence(BaseModel):
	"""Aggregated repo evidence for a single skill across all repos."""

	repos: int = Field(ge=0)
	total_bytes: int = Field(ge=0)
	first_seen: datetime
	last_seen: datetime
	frameworks: list[str] = Field(default_factory=list)
	test_coverage: bool = False


class RepoProfile(BaseModel):
	"""Aggregate profile from all scanned repos."""

	repos: list[RepoEvidence]
	scan_date: datetime
	repo_timeline_start: datetime
	repo_timeline_end: datetime
	repo_timeline_days: int = Field(ge=0)

	# Aggregated per-skill evidence
	skill_evidence: dict[str, SkillRepoEvidence] = Field(default_factory=dict)

	# Aggregated maturity
	repos_with_tests: int = Field(ge=0)
	repos_with_ci: int = Field(ge=0)
	repos_with_releases: int = Field(ge=0)
	repos_with_ai_signals: int = Field(ge=0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_repo_profile.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/schemas/repo_profile.py tests/test_repo_profile.py
git commit -m "feat: add RepoEvidence and RepoProfile schemas"
```

---

### Task 2: Local Repo Filesystem Scanner

**Files:**
- Create: `src/claude_candidate/repo_scanner.py`
- Test: `tests/test_repo_scanner.py`

- [ ] **Step 1: Write failing test for scanning a local repo**

```python
# tests/test_repo_scanner.py
from pathlib import Path

from claude_candidate.repo_scanner import scan_local_repo


class TestScanLocalRepo:
	def test_scan_candidate_eval(self) -> None:
		"""Scan this repo itself as a known baseline."""
		repo_path = Path(__file__).parent.parent  # project root
		evidence = scan_local_repo(repo_path)

		assert evidence.name == "candidate-eval"
		assert "Python" in evidence.languages
		assert evidence.languages["Python"] > 100_000  # substantial Python codebase
		assert evidence.has_tests is True
		assert evidence.test_framework == "pytest"
		assert evidence.test_file_count > 30
		assert evidence.has_ci is False  # no .github/workflows in this repo
		assert evidence.has_claude_md is True
		assert evidence.claude_dir_exists is True
		assert evidence.ai_maturity_level in ("advanced", "expert")

	def test_scan_detects_dependencies(self) -> None:
		"""Dependencies from pyproject.toml are resolved."""
		repo_path = Path(__file__).parent.parent
		evidence = scan_local_repo(repo_path)

		assert "pydantic" in evidence.dependencies or "fastapi" in evidence.dependencies
		assert "pytest" in evidence.dev_dependencies or "hypothesis" in evidence.dev_dependencies

	def test_scan_detects_llm_imports(self) -> None:
		"""LLM-related imports are detected in source files."""
		repo_path = Path(__file__).parent.parent
		evidence = scan_local_repo(repo_path)

		# candidate-eval uses anthropic SDK indirectly via claude CLI
		# but has direct imports for embeddings
		assert isinstance(evidence.llm_imports, list)

	def test_scan_commit_span(self) -> None:
		"""Commit span is computed from git log."""
		repo_path = Path(__file__).parent.parent
		evidence = scan_local_repo(repo_path)

		assert evidence.commit_span_days > 0
		assert evidence.created_at < evidence.last_pushed
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_repo_scanner.py::TestScanLocalRepo::test_scan_candidate_eval -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement `scan_local_repo()`**

Create `src/claude_candidate/repo_scanner.py` with functions:
- `scan_local_repo(path: Path) → RepoEvidence` — full filesystem scan
- `_detect_languages(path: Path) → dict[str, int]` — walk files, count bytes by extension using the same `FILE_EXTENSION_MAP` approach from `code_signals.py`
- `_parse_dependencies(path: Path) → tuple[list[str], list[str]]` — parse pyproject.toml, package.json, Cargo.toml; resolve through `package_to_skill_map.json`; return (deps, dev_deps)
- `_detect_tests(path: Path) → tuple[bool, str | None, int]` — find test dirs, config files, count test files
- `_detect_ci(path: Path) → tuple[bool, str]` — parse .github/workflows, classify complexity
- `_detect_ai_signals(path: Path) → dict` — CLAUDE.md, .claude/ artifacts, LLM imports, eval frameworks
- `_compute_ai_maturity(signals: dict) → str` — derive basic/intermediate/advanced/expert
- `_git_commit_span(path: Path) → tuple[datetime, datetime, int]` — first/last commit dates + span days
- `_count_releases(path: Path) → int` — count git tags matching semver pattern

Each function is pure filesystem analysis — no API calls. Use `subprocess.run(["git", "log", ...])` for git operations.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_repo_scanner.py -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/repo_scanner.py tests/test_repo_scanner.py
git commit -m "feat: add local repo filesystem scanner"
```

---

### Task 3: GitHub API Repo Scanner

**Files:**
- Modify: `src/claude_candidate/repo_scanner.py`
- Test: `tests/test_repo_scanner.py`

- [ ] **Step 1: Write failing test for GitHub API scanning**

```python
# tests/test_repo_scanner.py (add to existing)
import pytest


class TestScanGitHubRepo:
	@pytest.mark.slow
	def test_scan_public_repo(self) -> None:
		"""Scan a known public repo via GitHub API."""
		from claude_candidate.repo_scanner import scan_github_repo

		evidence = scan_github_repo("brianruggieri/claude-code-pulse")

		assert evidence.name == "claude-code-pulse"
		assert evidence.url == "https://github.com/brianruggieri/claude-code-pulse"
		assert "Shell" in evidence.languages
		assert evidence.has_tests is True
		assert evidence.has_ci is True
		assert evidence.releases >= 5
		assert evidence.commit_span_days > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_repo_scanner.py::TestScanGitHubRepo -v --run-slow`
Expected: FAIL with `ImportError: cannot import name 'scan_github_repo'`

- [ ] **Step 3: Implement `scan_github_repo()`**

Add to `repo_scanner.py`:
- `scan_github_repo(repo_slug: str, cache_dir: Path | None) → RepoEvidence` — uses `gh api` for languages, releases; clones to `~/.claude-candidate/repo-cache/` for deeper analysis; reuses cached clones
- `_gh_api(endpoint: str) → dict` — wrapper around `subprocess.run(["gh", "api", endpoint])`
- `_find_local_clone(repo_name: str, search_dirs: list[Path]) → Path | None` — check ~/git/ and other configured paths for existing clones before falling back to API

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_repo_scanner.py::TestScanGitHubRepo -v --run-slow`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/repo_scanner.py tests/test_repo_scanner.py
git commit -m "feat: add GitHub API repo scanner with local-first lookup"
```

---

### Task 4: Repo Profile Aggregation

**Files:**
- Modify: `src/claude_candidate/repo_scanner.py`
- Test: `tests/test_repo_scanner.py`

- [ ] **Step 1: Write failing test for profile aggregation**

```python
# tests/test_repo_scanner.py (add to existing)
class TestBuildRepoProfile:
	def test_aggregate_skill_evidence(self) -> None:
		"""Multiple repos aggregate into per-skill evidence."""
		from claude_candidate.repo_scanner import build_repo_profile

		repo_path = Path(__file__).parent.parent
		profile = build_repo_profile(
			local_repos=[repo_path],
			github_repos=[],
		)

		assert profile.repo_timeline_days > 0
		assert "python" in profile.skill_evidence
		python_ev = profile.skill_evidence["python"]
		assert python_ev.repos >= 1
		assert python_ev.total_bytes > 0
		assert profile.repos_with_tests >= 1

	def test_timeline_scales_with_repos(self) -> None:
		"""Timeline span covers earliest to latest across all repos."""
		from claude_candidate.repo_scanner import build_repo_profile

		repo_path = Path(__file__).parent.parent
		profile = build_repo_profile(
			local_repos=[repo_path],
			github_repos=[],
		)

		assert profile.repo_timeline_start <= profile.repo_timeline_end
		assert profile.repo_timeline_days == (
			profile.repo_timeline_end - profile.repo_timeline_start
		).days
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_repo_scanner.py::TestBuildRepoProfile -v`
Expected: FAIL with `ImportError: cannot import name 'build_repo_profile'`

- [ ] **Step 3: Implement `build_repo_profile()`**

Add to `repo_scanner.py`:
- `build_repo_profile(local_repos, github_repos, config_path) → RepoProfile`
- Scans each repo (local-first, API fallback)
- Aggregates `SkillRepoEvidence` per canonical skill name (using taxonomy for language name resolution)
- Computes timeline from min/max commit dates across all repos
- Writes result to `~/.claude-candidate/repo_profile.json`

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_repo_scanner.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/repo_scanner.py tests/test_repo_scanner.py
git commit -m "feat: add repo profile aggregation with skill evidence rollup"
```

---

### Task 5: CLI Commands for Repo Scanning

**Files:**
- Modify: `src/claude_candidate/cli.py`
- Test: `tests/test_cli.py` (add new test class)

- [ ] **Step 1: Write failing test for `repos scan` command**

```python
# tests/test_cli.py (add to existing)
from click.testing import CliRunner
from claude_candidate.cli import main


class TestReposCLI:
	def test_repos_list_shows_configured(self, tmp_path: Path) -> None:
		"""repos list shows configured repos."""
		config = tmp_path / "repos.json"
		config.write_text('{"github_repos": ["user/repo1"], "local_repos": [], "exclude": []}')
		runner = CliRunner()
		result = runner.invoke(main, ["repos", "list", "--config", str(config)])
		assert result.exit_code == 0
		assert "user/repo1" in result.output

	def test_repos_scan_produces_profile(self, tmp_path: Path) -> None:
		"""repos scan creates repo_profile.json."""
		import json
		project_root = Path(__file__).parent.parent
		config = tmp_path / "repos.json"
		config.write_text(json.dumps({
			"github_repos": [],
			"local_repos": [str(project_root)],
			"exclude": [],
		}))
		data_dir = tmp_path / "data"
		data_dir.mkdir()
		runner = CliRunner()
		result = runner.invoke(main, [
			"repos", "scan",
			"--config", str(config),
			"--data-dir", str(data_dir),
		])
		assert result.exit_code == 0
		assert (data_dir / "repo_profile.json").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli.py::TestReposCLI -v`
Expected: FAIL

- [ ] **Step 3: Implement `repos` CLI group**

Add to `cli.py`:
- `@main.group() repos` — group for repo commands
- `@repos.command() list` — show configured repos
- `@repos.command() scan` — scan repos, write repo_profile.json
- Options: `--config` (path to repos.json), `--data-dir` (output directory)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_cli.py::TestReposCLI -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/cli.py tests/test_cli.py
git commit -m "feat: add repos scan/list CLI commands"
```

---

### Task 6: EvidenceSource Enum + MergedSkillEvidence Schema Update

**Files:**
- Modify: `src/claude_candidate/schemas/merged_profile.py`
- Test: `tests/test_merged_profile.py` (or existing tests)

- [ ] **Step 1: Write failing test for new EvidenceSource values**

```python
# tests/test_merged_profile.py (add to existing)
from claude_candidate.schemas.merged_profile import EvidenceSource, MergedSkillEvidence
from claude_candidate.schemas.candidate_profile import DepthLevel


class TestEvidenceSourceV2:
	def test_resume_and_repo_source(self) -> None:
		skill = MergedSkillEvidence(
			name="typescript",
			source=EvidenceSource.RESUME_AND_REPO,
			resume_depth=DepthLevel.EXPERT,
			resume_duration="8 years",
			repo_count=5,
			repo_bytes=2_800_000,
			repo_confirmed=True,
			effective_depth=DepthLevel.EXPERT,
		)
		assert skill.source == EvidenceSource.RESUME_AND_REPO
		assert skill.repo_confirmed is True

	def test_repo_only_source(self) -> None:
		skill = MergedSkillEvidence(
			name="fastapi",
			source=EvidenceSource.REPO_ONLY,
			repo_count=2,
			repo_bytes=50_000,
			repo_confirmed=True,
			effective_depth=DepthLevel.APPLIED,
		)
		assert skill.source == EvidenceSource.REPO_ONLY
		assert skill.resume_depth is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_merged_profile.py::TestEvidenceSourceV2 -v`
Expected: FAIL (RESUME_AND_REPO doesn't exist, repo fields don't exist)

- [ ] **Step 3: Update the schema**

Modify `merged_profile.py`:
- Add `RESUME_AND_REPO = "resume_and_repo"` to EvidenceSource
- Add repo fields to MergedSkillEvidence: `repo_count`, `repo_bytes`, `repo_first_seen`, `repo_last_seen`, `repo_frameworks`, `repo_confirmed`
- Remove `confidence` field (moves to match time)
- Keep `session_depth`, `session_frequency` etc. as optional for backward compat during migration — mark with `# deprecated: v0.8 removal` comments

- [ ] **Step 4: Run full test suite to check for breakage**

Run: `.venv/bin/python -m pytest --tb=short -q`
Expected: Fix any tests that relied on old confidence field or missing EvidenceSource values

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/schemas/merged_profile.py tests/test_merged_profile.py
git commit -m "feat: add RESUME_AND_REPO source, repo evidence fields to MergedSkillEvidence"
```

---

### Task 7: Merger Redesign — `merge_triad()`

**Files:**
- Modify: `src/claude_candidate/merger.py`
- Test: `tests/test_merger.py`

- [ ] **Step 1: Write failing test for merge_triad**

```python
# tests/test_merger.py (add to existing)
import json
from datetime import datetime, timezone
from claude_candidate.merger import merge_triad
from claude_candidate.schemas.curated_resume import CuratedResume, CuratedSkill
from claude_candidate.schemas.repo_profile import RepoProfile, SkillRepoEvidence
from claude_candidate.schemas.candidate_profile import DepthLevel


class TestMergeTriad:
	def _make_resume(self) -> CuratedResume:
		"""Minimal curated resume with known skills."""
		return CuratedResume(
			profile_version="1.0",
			parsed_at=datetime.now(timezone.utc),
			source_file_hash="test",
			source_format="pdf",
			name="Test User",
			roles=[],
			total_years_experience=13,
			skills=[],
			education=["B.S. Computer Science"],
			curated_skills=[
				CuratedSkill(name="typescript", depth=DepthLevel.EXPERT, duration="8 years"),
				CuratedSkill(name="python", depth=DepthLevel.DEEP, duration="2 years"),
				CuratedSkill(name="unity", depth=DepthLevel.EXPERT, duration="6 years"),
			],
			curated=True,
		)

	def _make_repo_profile(self) -> RepoProfile:
		"""Repo profile with typescript, python, and fastapi."""
		now = datetime.now(timezone.utc)
		return RepoProfile(
			repos=[],
			scan_date=now,
			repo_timeline_start=datetime(2026, 1, 30, tzinfo=timezone.utc),
			repo_timeline_end=datetime(2026, 3, 25, tzinfo=timezone.utc),
			repo_timeline_days=55,
			skill_evidence={
				"typescript": SkillRepoEvidence(
					repos=5, total_bytes=2_800_000,
					first_seen=datetime(2026, 1, 30, tzinfo=timezone.utc),
					last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
					frameworks=["react", "vitest"],
					test_coverage=True,
				),
				"python": SkillRepoEvidence(
					repos=1, total_bytes=100_000,
					first_seen=datetime(2026, 2, 19, tzinfo=timezone.utc),
					last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
					frameworks=["fastapi", "pytest"],
					test_coverage=True,
				),
				"fastapi": SkillRepoEvidence(
					repos=1, total_bytes=50_000,
					first_seen=datetime(2026, 2, 19, tzinfo=timezone.utc),
					last_seen=datetime(2026, 3, 25, tzinfo=timezone.utc),
					frameworks=[],
					test_coverage=True,
				),
			},
			repos_with_tests=7,
			repos_with_ci=5,
			repos_with_releases=2,
			repos_with_ai_signals=4,
		)

	def test_resume_depth_is_anchor(self) -> None:
		"""Resume depth is never overridden by repo evidence."""
		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		ts = profile.get_skill("typescript")
		assert ts is not None
		assert ts.effective_depth == DepthLevel.EXPERT  # resume says expert
		assert ts.source.value == "resume_and_repo"
		assert ts.repo_confirmed is True

	def test_repo_only_skill_capped_by_timeline(self) -> None:
		"""Skills in repos but not resume are scoped to repo timeline."""
		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		fastapi = profile.get_skill("fastapi")
		assert fastapi is not None
		assert fastapi.source.value == "repo_only"
		# 55 days = ~2 months → Applied max
		assert fastapi.effective_depth == DepthLevel.APPLIED

	def test_resume_only_skill_preserved(self) -> None:
		"""Skills on resume but not in repos are preserved."""
		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		unity = profile.get_skill("unity")
		assert unity is not None
		assert unity.source.value == "resume_only"
		assert unity.effective_depth == DepthLevel.EXPERT

	def test_no_session_languages_in_profile(self) -> None:
		"""Rust/Go/etc should not appear — only resume + repo skills."""
		profile = merge_triad(self._make_resume(), self._make_repo_profile())
		assert profile.get_skill("rust") is None
		assert profile.get_skill("go") is None
		assert profile.get_skill("kotlin") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_merger.py::TestMergeTriad -v`
Expected: FAIL with `ImportError: cannot import name 'merge_triad'`

- [ ] **Step 3: Implement `merge_triad()`**

Add to `merger.py`:
- `merge_triad(curated_resume: CuratedResume, repo_profile: RepoProfile) → MergedEvidenceProfile`
- Canonicalize resume skill names via taxonomy
- For each skill in resume ∪ repo_profile.skill_evidence:
  - Determine source (resume_only, repo_only, resume_and_repo)
  - Resume depth is the anchor — never overridden
  - Repo-only skills: depth scaled by `repo_timeline_days` (≤90d → APPLIED, ≤180d → DEEP, >540d → EXPERT)
  - Populate repo evidence fields (repo_count, repo_bytes, etc.)
- No session data in v0.7

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_merger.py::TestMergeTriad -v`
Expected: PASS (all 4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/merger.py tests/test_merger.py
git commit -m "feat: add merge_triad — resume-anchored + repo-evidenced profile merge"
```

---

### Task 8: Matching Engine — Confidence as Match Quality

**Files:**
- Modify: `src/claude_candidate/quick_match.py`
- Test: `tests/test_quick_match.py`

- [ ] **Step 1: Write failing test for match-time confidence**

```python
# tests/test_quick_match.py (add to existing)
class TestMatchConfidence:
	def test_exact_match_high_confidence(self) -> None:
		"""Exact skill name match produces high confidence."""
		from claude_candidate.quick_match import compute_match_confidence

		conf = compute_match_confidence(
			candidate_skill="typescript",
			requirement_text="Expert TypeScript developer with React experience",
			match_type="exact",
		)
		assert conf >= 0.90

	def test_alias_match_good_confidence(self) -> None:
		"""Alias match produces good confidence."""
		from claude_candidate.quick_match import compute_match_confidence

		conf = compute_match_confidence(
			candidate_skill="react",
			requirement_text="Experience with React.js and modern frontend frameworks",
			match_type="exact",
		)
		assert conf >= 0.85

	def test_no_mention_in_text_low_confidence(self) -> None:
		"""Skill not mentioned in requirement text produces low confidence."""
		from claude_candidate.quick_match import compute_match_confidence

		conf = compute_match_confidence(
			candidate_skill="software-engineering",
			requirement_text="Embedded C firmware engineer with RTOS experience",
			match_type="fuzzy",
		)
		assert conf <= 0.30

	def test_no_match_zero_confidence(self) -> None:
		"""No match produces zero confidence."""
		from claude_candidate.quick_match import compute_match_confidence

		conf = compute_match_confidence(
			candidate_skill="",
			requirement_text="Anything",
			match_type="none",
		)
		assert conf == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_quick_match.py::TestMatchConfidence -v`
Expected: FAIL with `ImportError: cannot import name 'compute_match_confidence'`

- [ ] **Step 3: Implement `compute_match_confidence()`**

Add to `quick_match.py`:
- `compute_match_confidence(candidate_skill, requirement_text, match_type) → float`
- Logic:
  - `match_type == "none"` → 0.0
  - `match_type == "exact"` → check if skill name (or any alias) appears in requirement text → 1.0 if yes, 0.70 if only matched via taxonomy
  - `match_type == "fuzzy"` → check text overlap → 0.40-0.70 depending on relevance
  - Generic skills matching domain-specific text → 0.0 (the key change: no more `software-engineering` matching everything)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_quick_match.py::TestMatchConfidence -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/quick_match.py tests/test_quick_match.py
git commit -m "feat: add compute_match_confidence — match quality scoring at match time"
```

---

### Task 9: Remove Ralph Loop Band-Aids

**Files:**
- Modify: `src/claude_candidate/quick_match.py`
- Modify: `tests/test_quick_match.py`

- [ ] **Step 1: Identify and remove band-aid code**

Remove from `quick_match.py`:
- Skill concentration penalty block (~lines 1669-1716)
- Weak must-have ratio penalty block (~lines 1718-1735)
- Sessions-only language cap in `_find_best_skill()` (~lines 1129-1140)
- Session depth cap in `_best_available_depth()` (the `_SESSION_DEPTH_CAPS` block)
- Expanded domain gap keywords (revert to original set, keep core mechanism)
- Tiered domain gap cap (revert to single B+ cap)

- [ ] **Step 2: Update domain gap test**

Revert `test_domain_does_not_fire_when_keyword_in_two_reqs` back to threshold 3 if it was changed.

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest --tb=short -q`
Expected: PASS (some tests may need adjustment for removed band-aids)

- [ ] **Step 4: Commit**

```bash
git add src/claude_candidate/quick_match.py tests/test_quick_match.py
git commit -m "fix: remove ralph loop band-aids — clean scoring for v0.7"
```

---

### Task 10: Curated Resume Fixes + Taxonomy Aliases

**Files:**
- Modify: `~/.claude-candidate/curated_resume.json` (data file, not in repo)
- Modify: `src/claude_candidate/data/taxonomy.json`
- Test: `tests/test_skill_taxonomy.py`

- [ ] **Step 1: Write failing test for new aliases**

```python
# tests/test_skill_taxonomy.py (add to existing)
class TestNewAliases:
	def test_ai_provider_abstraction_resolves(self) -> None:
		from claude_candidate.skill_taxonomy import SkillTaxonomy
		tax = SkillTaxonomy.load(Path("src/claude_candidate/data/taxonomy.json"))
		assert tax.canonicalize("ai provider abstraction") == "agentic-workflows"

	def test_ai_augmented_dev_tooling_resolves(self) -> None:
		from claude_candidate.skill_taxonomy import SkillTaxonomy
		tax = SkillTaxonomy.load(Path("src/claude_candidate/data/taxonomy.json"))
		assert tax.canonicalize("ai-augmented development tooling") == "developer-tools"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_skill_taxonomy.py::TestNewAliases -v`
Expected: FAIL (aliases not yet added)

- [ ] **Step 3: Add aliases to taxonomy.json**

Add `"ai provider abstraction"` to `agentic-workflows.aliases` array.
Add `"ai-augmented development tooling"` to `developer-tools.aliases` array.

- [ ] **Step 4: Fix curated_resume.json**

Change `"llm integration (anthropic"` to `"llm"` in the curated_skills array.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/test_skill_taxonomy.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/data/taxonomy.json tests/test_skill_taxonomy.py
git commit -m "fix: add taxonomy aliases for orphaned resume skills, fix truncated LLM skill"
```

---

### Task 11: Dead Code Removal

**Files:**
- Modify: `src/claude_candidate/extractor.py`
- Modify: `src/claude_candidate/schemas/candidate_profile.py`

- [ ] **Step 1: Remove dead functions from extractor.py**

Remove: `build_candidate_profile()` (lines 803-851), `_build_skill_entries()` + 5 helpers (lines 531-657), `_signals_to_normalized_session()` (lines 732-800), `CATEGORY_MAP` (lines 92-118), unused `session` variable (line 384).

- [ ] **Step 2: Remove unused schema fields**

Remove `context_notes` from `SkillEntry` in `candidate_profile.py`.
Remove `counter_evidence` from `ProblemSolvingPattern` in `candidate_profile.py`.

- [ ] **Step 3: Run full test suite**

Run: `.venv/bin/python -m pytest --tb=short -q`
Expected: PASS — any test referencing removed code needs updating

- [ ] **Step 4: Commit**

```bash
git add src/claude_candidate/extractor.py src/claude_candidate/schemas/candidate_profile.py
git commit -m "chore: remove ~430 lines of dead code from extractor and schemas"
```

---

### Task 12: Wire merge_triad into Server + CLI

**Files:**
- Modify: `src/claude_candidate/server.py`
- Modify: `src/claude_candidate/cli.py`

- [ ] **Step 1: Update server profile loading**

In `server.py`, update the profile loading logic to:
1. Check for `repo_profile.json` in data dir
2. If found, use `merge_triad(curated_resume, repo_profile)`
3. If not found, fall back to existing `merge_with_curated()`

- [ ] **Step 2: Update CLI assess command**

In `cli.py`, update the assess command to use `merge_triad()` when `repo_profile.json` exists.

- [ ] **Step 3: Add `profile rebuild` CLI command**

Add `@profile.command("rebuild")` that re-merges resume + repos into a fresh profile.

- [ ] **Step 4: Run full test suite**

Run: `.venv/bin/python -m pytest --tb=short -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/server.py src/claude_candidate/cli.py
git commit -m "feat: wire merge_triad into server and CLI with fallback"
```

---

### Task 13: Benchmark + Recalibration

**Files:**
- Modify: `tests/golden_set/expected_grades.json`

- [ ] **Step 1: Create repos.json config**

Write `~/.claude-candidate/repos.json` with all 11 public repos + candidate-eval local path.

- [ ] **Step 2: Run repo scan**

Run: `.venv/bin/python -m claude_candidate.cli repos scan`
Verify: `~/.claude-candidate/repo_profile.json` created with all repos.

- [ ] **Step 3: Rebuild profile**

Run: `.venv/bin/python -m claude_candidate.cli profile rebuild`
Verify: Merged profile uses resume + repos, no session languages (rust/go/kotlin/java/cpp gone).

- [ ] **Step 4: Run benchmark**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Record: exact match count, within-1 count, off-by-2+ count.

- [ ] **Step 5: Recalibrate expected grades**

Review each off-by-2+ posting. For each:
- If the new grade is MORE CORRECT than the old expectation → update expected_grades.json
- If the new grade is WRONG → investigate and fix the matching/merger logic
- Document rationale for each recalibration

Target: all 47 within ±1 after recalibration.

- [ ] **Step 6: Run benchmark again to confirm**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Expected: All 47 within ±1.

- [ ] **Step 7: Commit**

```bash
git add tests/golden_set/expected_grades.json
git commit -m "fix: recalibrate golden set expected grades for v0.7 depth model"
```

---

### Task 14: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest --tb=short -q`
Expected: 1224+ passed, 0 failed

- [ ] **Step 2: Run slow tests**

Run: `.venv/bin/python -m pytest --run-slow --tb=short -q`
Expected: All pass including integration tests

- [ ] **Step 3: Start server and verify extension works**

Run: `.venv/bin/python -m claude_candidate.cli server start`
Open a LinkedIn posting in Chrome with the extension.
Verify: Assessment loads, shows repo-backed evidence, no phantom language skills.

- [ ] **Step 4: Verify success criteria**

Checklist:
- [ ] All 47 golden set postings within ±1 of expected
- [ ] Zero false language expertise in profile (no Rust/Go/Kotlin/Java/C++)
- [ ] Resume depth never overridden
- [ ] Confidence reflects match quality, not evidence quality
- [ ] Repo timeline scales (not hardcoded)
- [ ] Tests pass

- [ ] **Step 5: Final commit + push**

```bash
git push origin feat/golden-set-expansion-calibration
```
