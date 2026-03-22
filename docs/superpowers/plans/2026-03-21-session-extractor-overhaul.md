# Session Extractor Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the monolithic 749-line extractor with a three-extractor architecture that extracts 50+ skills (from 15), covers AI-native and behavioral signals, and optionally enriches with ML embeddings.

**Architecture:** Three independent extractors (CodeSignalExtractor, BehaviorSignalExtractor, CommSignalExtractor) each analyze session JSONL files for different signal types. A SignalMerger aggregates their outputs into the existing CandidateProfile schema. An optional ML enrichment layer upgrades matching and evidence quality when torch is installed.

**Tech Stack:** Python 3.11+, pydantic v2, ruptures (change point detection), sentence-transformers (optional ML)

**Spec:** `docs/superpowers/specs/2026-03-21-session-extractor-overhaul-design.md`

**Conventions:**
- Venv: `.venv/bin/python -m pytest` for tests, `.venv/bin/python` for scripts
- Indentation: tabs (defer to editor config)
- Line length: 100 (ruff)
- Before running any command: `source ~/.nvm/nvm.sh && nvm use` is NOT needed (Python project)
- Always run `source .venv/bin/activate` or use `.venv/bin/python` prefix

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `src/claude_candidate/extractors/__init__.py` | ExtractorProtocol, NormalizedSession, SignalResult, SkillSignal, PatternSignal, ProjectSignal |
| `src/claude_candidate/extractors/code_signals.py` | CodeSignalExtractor — file extensions, content patterns, imports, package commands |
| `src/claude_candidate/extractors/behavior_signals.py` | BehaviorSignalExtractor — tool patterns, agent orchestration, git workflow, quality practices |
| `src/claude_candidate/extractors/comm_signals.py` | CommSignalExtractor — steering, scope mgmt, grill-me, handoffs |
| `src/claude_candidate/extractors/signal_merger.py` | SignalMerger — aggregation, depth scoring, pattern merging, velocity, profile assembly |
| `src/claude_candidate/data/package_to_skill_map.json` | ~200 package→skill mappings |
| `src/claude_candidate/enrichment/__init__.py` | enrichment_available() gate |
| `src/claude_candidate/enrichment/embedding_matcher.py` | Semantic skill matching via MiniLM |
| `src/claude_candidate/enrichment/evidence_selector.py` | Embedding-based snippet relevance |
| `src/claude_candidate/enrichment/learning_velocity.py` | Enhanced sophistication classification |
| `tests/test_extractors/__init__.py` | Test package |
| `tests/test_extractors/test_code_signals.py` | CodeSignalExtractor tests |
| `tests/test_extractors/test_behavior_signals.py` | BehaviorSignalExtractor tests |
| `tests/test_extractors/test_comm_signals.py` | CommSignalExtractor tests |
| `tests/test_extractors/test_signal_merger.py` | SignalMerger tests |
| `tests/test_extractors/test_interfaces.py` | Shared type validation tests |
| `tests/test_taxonomy_patterns.py` | Anti-greedy pattern validation |
| `tests/test_enrichment.py` | ML enrichment tests (skip if no torch) |
| `tests/fixtures/sessions/agent_orchestration_session.jsonl` | Fixture: Agent tool_use, TaskCreate, Skill events |
| `tests/fixtures/sessions/steering_session.jsonl` | Fixture: user corrections, scope management, grill-me |
| `tests/fixtures/sessions/import_heavy_session.jsonl` | Fixture: Python/JS imports, package commands |

### Modified files
| File | Change |
|------|--------|
| `src/claude_candidate/extractor.py` | Refactor to thin orchestrator calling three extractors + merger |
| `src/claude_candidate/data/taxonomy.json` | Add content_patterns to all 63 entries that lack them |
| `pyproject.toml` | Add `ruptures` to deps, add `[ml]` optional-dependencies |

### Unchanged files (must not break)
| File | Constraint |
|------|-----------|
| `src/claude_candidate/quick_match.py` | Do not modify — scoring engine is calibrated |
| `src/claude_candidate/fit_exporter.py` | Do not modify — shipped in PR #9 |
| `src/claude_candidate/cli.py` | Do not modify CLI interface — `sessions scan` keeps working |
| `src/claude_candidate/schemas/candidate_profile.py` | Do not modify — output schema stays as-is |
| `tests/golden_set/benchmark_accuracy.py` | Must still pass 24/24 after all changes |

---

## Task 1: Shared Interfaces & NormalizedSession

**Depends on:** nothing (start here)
**Files:**
- Create: `src/claude_candidate/extractors/__init__.py`
- Create: `tests/test_extractors/__init__.py`
- Create: `tests/test_extractors/test_interfaces.py`

- [ ] **Step 1: Write interface tests**

```python
# tests/test_extractors/test_interfaces.py
"""Tests for shared extractor interface types."""
import pytest
from datetime import datetime, timezone

from claude_candidate.extractors import (
	NormalizedSession,
	SignalResult,
	SkillSignal,
	PatternSignal,
	ProjectSignal,
)
from claude_candidate.schemas.candidate_profile import DepthLevel, PatternType


class TestSkillSignal:
	def test_valid_skill_signal(self):
		sig = SkillSignal(
			canonical_name="python",
			source="import_statement",
			confidence=0.85,
			depth_hint=DepthLevel.APPLIED,
			evidence_snippet="from fastapi import FastAPI",
			evidence_type="direct_usage",
		)
		assert sig.canonical_name == "python"
		assert sig.confidence == 0.85

	def test_confidence_bounds(self):
		with pytest.raises(Exception):
			SkillSignal(
				canonical_name="python",
				source="import_statement",
				confidence=1.5,  # out of range
				evidence_snippet="test",
			)

	def test_snippet_max_length(self):
		with pytest.raises(Exception):
			SkillSignal(
				canonical_name="python",
				source="import_statement",
				confidence=0.8,
				evidence_snippet="x" * 501,  # too long
			)

	def test_all_source_types_accepted(self):
		sources = [
			"file_extension", "content_pattern", "import_statement",
			"package_command", "tool_usage", "agent_dispatch",
			"skill_invocation", "user_message", "git_workflow",
			"quality_signal",
		]
		for source in sources:
			sig = SkillSignal(
				canonical_name="test",
				source=source,
				confidence=0.5,
				evidence_snippet="test evidence",
			)
			assert sig.source == source


class TestSignalResult:
	def test_empty_signal_result(self):
		result = SignalResult(
			session_id="abc-123",
			session_date=datetime.now(timezone.utc),
			project_context="candidate-eval",
		)
		assert result.skills == {}
		assert result.patterns == []
		assert result.project_signals is None

	def test_with_skills_and_patterns(self):
		skill = SkillSignal(
			canonical_name="python",
			source="file_extension",
			confidence=0.9,
			evidence_snippet="test.py",
		)
		pattern = PatternSignal(
			pattern_type=PatternType.ITERATIVE_REFINEMENT,
			session_ids=["abc-123"],
			confidence=0.8,
			description="Write→Bash→Write cycle observed",
			evidence_snippet="Edited file, ran tests, edited again",
		)
		result = SignalResult(
			session_id="abc-123",
			session_date=datetime.now(timezone.utc),
			project_context="candidate-eval",
			skills={"python": [skill]},
			patterns=[pattern],
		)
		assert "python" in result.skills
		assert len(result.patterns) == 1


class TestNormalizedSession:
	def test_from_messages(self):
		session = NormalizedSession(
			session_id="abc-123",
			timestamp=datetime.now(timezone.utc),
			cwd="/Users/test/git/myproject",
			project_context="myproject",
			git_branch="feat/new-feature",
			messages=[],
		)
		assert session.project_context == "myproject"
		assert session.git_branch == "feat/new-feature"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_extractors/test_interfaces.py -v`
Expected: FAIL — module `claude_candidate.extractors` does not exist

- [ ] **Step 3: Implement shared interfaces**

```python
# src/claude_candidate/extractors/__init__.py
"""
Shared interfaces for the three-extractor architecture.

All extractors produce SignalResult objects. The SignalMerger consumes them.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from claude_candidate.message_format import NormalizedMessage
from claude_candidate.schemas.candidate_profile import DepthLevel, PatternType


# ---------------------------------------------------------------------------
# NormalizedSession — wraps NormalizedMessage list with session metadata
# ---------------------------------------------------------------------------


class NormalizedSession(BaseModel):
	"""Session-level container wrapping NormalizedMessage list with metadata.

	This is NOT a rename of NormalizedMessage — it is a session-level wrapper.
	All three extractors receive the same NormalizedSession.
	"""

	model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

	session_id: str
	timestamp: datetime
	cwd: str
	project_context: str
	git_branch: str | None = None
	messages: list[NormalizedMessage]


# ---------------------------------------------------------------------------
# Signal types — output of each extractor
# ---------------------------------------------------------------------------


class SkillSignal(BaseModel):
	"""A single skill detection from one extractor."""

	model_config = ConfigDict(frozen=True)

	canonical_name: str
	source: Literal[
		"file_extension",
		"content_pattern",
		"import_statement",
		"package_command",
		"tool_usage",
		"agent_dispatch",
		"skill_invocation",
		"user_message",
		"git_workflow",
		"quality_signal",
	]
	confidence: float = Field(ge=0.0, le=1.0, default=0.7)
	depth_hint: DepthLevel | None = None
	evidence_snippet: str = Field(max_length=500)  # required — SessionReference rejects empty
	evidence_type: Literal[
		"direct_usage",
		"architecture_decision",
		"debugging",
		"teaching",
		"evaluation",
		"integration",
		"refactor",
		"testing",
		"review",
		"planning",
	] = "direct_usage"
	metadata: dict[str, Any] = Field(default_factory=dict)


class PatternSignal(BaseModel):
	"""A behavioral or communication pattern detection.

	Does NOT carry frequency/strength — those are computed by SignalMerger.
	"""

	model_config = ConfigDict(frozen=True)

	pattern_type: PatternType
	session_ids: list[str]
	confidence: float = Field(ge=0.0, le=1.0, default=0.7)
	description: str
	evidence_snippet: str = Field(max_length=500)  # required — must provide evidence
	metadata: dict[str, Any] = Field(default_factory=dict)


class ProjectSignal(BaseModel):
	"""Project-level enrichment from a single session."""

	model_config = ConfigDict(frozen=True)

	key_decisions: list[str] = Field(default_factory=list)
	challenges: list[str] = Field(default_factory=list)
	description_fragments: list[str] = Field(default_factory=list)


class SignalResult(BaseModel):
	"""One extraction layer's output for a single session."""

	model_config = ConfigDict(frozen=True)

	session_id: str
	session_date: datetime
	project_context: str
	git_branch: str | None = None
	skills: dict[str, list[SkillSignal]] = Field(default_factory=dict)
	patterns: list[PatternSignal] = Field(default_factory=list)
	project_signals: ProjectSignal | None = None
	metrics: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Extractor protocol
# ---------------------------------------------------------------------------


class ExtractorProtocol(Protocol):
	"""Contract for all three extractors."""

	def extract_session(self, session: NormalizedSession) -> SignalResult:
		"""Extract signals from a single normalized session."""
		...

	def name(self) -> str:
		"""Extractor identifier for logging and source tracking."""
		...
```

Also create: `tests/test_extractors/__init__.py` (empty file).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_extractors/test_interfaces.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/extractors/__init__.py tests/test_extractors/
git commit -m "Add shared extractor interfaces: SignalResult, SkillSignal, NormalizedSession"
```

---

## Task 2: Add ruptures dependency and package_to_skill_map

**Depends on:** nothing (can run parallel with Task 1)
**Files:**
- Modify: `pyproject.toml`
- Create: `src/claude_candidate/data/package_to_skill_map.json`

- [ ] **Step 1: Update pyproject.toml**

Add `ruptures` to dependencies. Add `[ml]` optional-dependencies group:

In `pyproject.toml`, add `"ruptures>=1.1.8"` to the `dependencies` list.

Add a new optional-dependencies group:
```toml
[project.optional-dependencies]
dev = [...]  # existing
ml = [
    "torch>=2.2",
    "sentence-transformers>=3.0",
    "scikit-learn>=1.4",
]
```

- [ ] **Step 2: Install new dependency**

Run: `.venv/bin/pip install -e ".[dev]"`
Expected: ruptures installs successfully

- [ ] **Step 3: Create package_to_skill_map.json**

Create `src/claude_candidate/data/package_to_skill_map.json` with ~200 package→skill mappings. This is the lookup table for import parsing and package command detection.

Structure: `{ "package_name": "canonical_skill_name" }`

Key mappings to include (grouped by ecosystem):

**Python packages:**
```json
{
  "fastapi": "fastapi",
  "flask": "flask",
  "django": "django",
  "pydantic": "pydantic",
  "sqlalchemy": "sqlalchemy",
  "pytest": "pytest",
  "hypothesis": "testing",
  "boto3": "aws",
  "botocore": "aws",
  "torch": "pytorch",
  "tensorflow": "tensorflow",
  "numpy": "data-science",
  "pandas": "data-science",
  "scikit-learn": "machine-learning",
  "langchain": "langchain",
  "openai": "openai",
  "anthropic": "anthropic",
  "redis": "redis",
  "psycopg2": "postgresql",
  "asyncpg": "postgresql",
  "aiohttp": "python",
  "httpx": "python",
  "click": "python",
  "rich": "python",
  "uvicorn": "fastapi",
  "gunicorn": "python",
  "celery": "python",
  "dramatiq": "python",
  "pyyaml": "yaml",
  "toml": "toml",
  "jinja2": "python",
  "playwright": "testing",
  "selenium": "testing",
  "docker": "docker",
  "kubernetes": "kubernetes",
  "terraform": "terraform",
  "aiosqlite": "sql",
  "pymupdf": "python",
  "rapidfuzz": "python",
  "datafog": "security"
}
```

**npm/JS packages:**
```json
{
  "react": "react",
  "react-dom": "react",
  "next": "nextjs",
  "vue": "vue",
  "nuxt": "vue",
  "angular": "angular",
  "express": "node.js",
  "fastify": "node.js",
  "hono": "node.js",
  "typescript": "typescript",
  "jest": "testing",
  "vitest": "testing",
  "playwright": "testing",
  "puppeteer": "testing",
  "three": "three-js",
  "@aws-sdk/client-s3": "aws",
  "prisma": "sql",
  "drizzle-orm": "sql",
  "tailwindcss": "css",
  "postcss": "css",
  "@anthropic-ai/sdk": "anthropic",
  "openai": "openai",
  "langchain": "langchain",
  "redis": "redis",
  "pg": "postgresql",
  "mongodb": "mongodb",
  "graphql": "api-design",
  "zod": "typescript",
  "webpack": "javascript",
  "vite": "javascript",
  "esbuild": "javascript",
  "bun": "javascript",
  "eslint": "javascript",
  "prettier": "javascript",
  "husky": "ci-cd"
}
```

**Rust crates:**
```json
{
  "tokio": "rust",
  "serde": "rust",
  "axum": "rust",
  "actix-web": "rust",
  "diesel": "sql",
  "sqlx": "sql",
  "clap": "rust",
  "reqwest": "rust",
  "wasm-bindgen": "webgl"
}
```

**Go modules:**
```json
{
  "gin-gonic/gin": "go",
  "gorilla/mux": "go",
  "gorm.io/gorm": "sql",
  "aws/aws-sdk-go": "aws"
}
```

Include approximately 200 total entries covering the most common packages across Python, JS/TS, Rust, and Go ecosystems.

- [ ] **Step 4: Verify data loads**

Run: `.venv/bin/python -c "import json; d = json.loads(open('src/claude_candidate/data/package_to_skill_map.json').read()); print(f'{len(d)} package mappings loaded')"`
Expected: `~200 package mappings loaded`

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/claude_candidate/data/package_to_skill_map.json
git commit -m "Add ruptures dependency, ml optional deps, package-to-skill map"
```

---

## Task 3: Expand taxonomy content_patterns (63 entries)

**Depends on:** nothing (can run parallel with Tasks 1-2)
**Files:**
- Modify: `src/claude_candidate/data/taxonomy.json`
- Create: `tests/test_taxonomy_patterns.py`

- [ ] **Step 1: Write anti-greedy validation test**

```python
# tests/test_taxonomy_patterns.py
"""Validate taxonomy content_patterns don't over-match."""
import json
from pathlib import Path

import pytest

TAXONOMY_PATH = Path("src/claude_candidate/data/taxonomy.json")


class TestTaxonomyPatterns:
	@pytest.fixture
	def taxonomy(self):
		return json.loads(TAXONOMY_PATH.read_text())

	def test_all_entries_have_content_patterns(self, taxonomy):
		"""Every taxonomy entry must have non-empty content_patterns."""
		missing = [
			name for name, info in taxonomy.items()
			if not info.get("content_patterns")
		]
		assert missing == [], f"Entries missing content_patterns: {missing}"

	def test_no_single_character_patterns(self, taxonomy):
		"""No pattern should be a single character."""
		for name, info in taxonomy.items():
			for pattern in info.get("content_patterns", []):
				assert len(pattern) > 1, f"{name} has single-char pattern: {pattern}"

	def test_no_overly_common_patterns(self, taxonomy):
		"""No pattern should be a common English word that would match everything."""
		too_common = {"the", "a", "an", "is", "it", "in", "on", "to", "for", "of", "and", "or"}
		for name, info in taxonomy.items():
			for pattern in info.get("content_patterns", []):
				assert pattern.lower() not in too_common, (
					f"{name} has overly common pattern: {pattern}"
				)

	def test_practices_have_multiple_patterns(self, taxonomy):
		"""Practice-category entries should have 2+ patterns to avoid false positives."""
		for name, info in taxonomy.items():
			if info.get("category") == "practice":
				patterns = info.get("content_patterns", [])
				assert len(patterns) >= 2, (
					f"Practice '{name}' needs 2+ patterns, has {len(patterns)}"
				)

	def test_patterns_are_lowercase_or_mixed(self, taxonomy):
		"""Patterns should not be ALL CAPS (likely a mistake)."""
		for name, info in taxonomy.items():
			for pattern in info.get("content_patterns", []):
				assert not pattern.isupper() or len(pattern) <= 4, (
					f"{name} has ALL CAPS pattern: {pattern} (use mixed case)"
				)
```

- [ ] **Step 2: Run test to verify it fails (missing patterns)**

Run: `.venv/bin/python -m pytest tests/test_taxonomy_patterns.py::TestTaxonomyPatterns::test_all_entries_have_content_patterns -v`
Expected: FAIL — 63 entries missing content_patterns

- [ ] **Step 3: Add content_patterns to all 63 entries**

Read the current `src/claude_candidate/data/taxonomy.json` and add `content_patterns` to every entry that lacks them. Follow these rules per category:

**Languages** — import/syntax patterns:
- `python`: `["import ", "from ", "def ", "class ", ".py"]`
- `typescript`: `["import {", "export ", ": string", ": number", ".ts"]`
- `javascript`: `["require(", "module.exports", "const ", ".js"]`
- `rust`: `["fn ", "let mut", "impl ", "use ", ".rs"]`
- `go`: `["func ", "package ", "import (", ".go"]`
- `java`: `["public class", "import java", "void ", ".java"]`
- `sql`: `["SELECT ", "INSERT INTO", "CREATE TABLE", "ALTER TABLE"]`
- `c`: `["#include ", "int main", "printf(", "malloc("]`
- `cpp`: `["#include <", "std::", "namespace ", "template<"]`
- `csharp`: `["using System", "namespace ", "public class", ".cs"]`
- `kotlin`: `["fun ", "val ", "var ", "class ", ".kt"]`
- `html-css`: `["<!DOCTYPE", "<html", "<div", "<body"]`

**Frameworks** (no existing patterns) — import + API:
- `node.js`: `["require(", "module.exports", "process.env", "express("]`
- `vue`: `["<template>", "defineComponent", "v-bind", "v-model"]`
- `nextjs`: `["next/", "getServerSideProps", "getStaticProps", "NextResponse"]`
- `pytorch`: `["import torch", "torch.nn", "torch.tensor", "backward()"]`
- `tensorflow`: `["import tensorflow", "tf.keras", "tf.constant"]`
- `spring`: `["@SpringBoot", "@RestController", "@Autowired"]`

**Platforms** (no existing patterns) — CLI + SDK:
- `aws`: `["aws ", "boto3", "from aws_cdk", "AWS::", "s3://"]`
- `gcp`: `["gcloud ", "from google.cloud", "gs://"]`
- `azure`: `["az ", "azure-", "from azure"]`
- `kubernetes`: `["kubectl ", "apiVersion:", "kind: Deployment", "k8s"]`

**Tools** (partially covered) — command patterns:
- `postgresql`: `["psql", "pg_dump", "CREATE TABLE", "postgres"]`
- `redis`: `["redis-cli", "REDIS_URL", "redis.Redis"]`
- `terraform`: `["terraform ", "resource \"", "provider \""]`

**Practices** — require 2+ co-occurring or highly specific terms:
- `ci-cd`: `[".github/workflows", "pipeline", "deploy", "CI/CD"]`
- `testing`: `["def test_", "describe(", "it(", "expect(", "assert"]`
- `api-design`: `["endpoint", "REST", "GraphQL", "OpenAPI", "/api/"]`
- `devops`: `["Dockerfile", "docker-compose", "nginx", "systemctl"]`
- `security`: `["sanitiz", "XSS", "CORS", "RBAC", "encrypt", "auth"]`
- `agile`: `["sprint", "standup", "backlog", "user story"]`
- `frontend-development`: `["useState", "component", "CSS", "responsive"]`
- `backend-development`: `["endpoint", "middleware", "ORM", "migration"]`
- `full-stack`: `["frontend", "backend", "fullstack", "full-stack"]`
- `system-design`: `["architecture", "scalab", "load balanc", "microservice"]`
- `prototyping`: `["prototype", "proof of concept", "MVP", "spike"]`
- `open-source`: `["open source", "MIT license", "contributing", "CHANGELOG"]`
- `software-engineering`: `["refactor", "code review", "pull request", "technical debt"]`
- `production-systems`: `["production", "monitoring", "incident", "SLA"]`
- `technical-writing`: `["documentation", "README", "docstring", "API docs"]`
- `product-development`: `["user story", "feature flag", "A/B test", "roadmap"]`
- `startup-experience`: `["MVP", "pivot", "product-market fit", "launch"]`
- `metrics`: `["KPI", "dashboard", "analytics", "tracking"]`
- `mlops`: `["model serving", "feature store", "ML pipeline", "model registry"]`
- `prompt-engineering`: `["prompt", "system prompt", "few-shot", "chain of thought"]`

**Domains** — conservative terminology:
- `machine-learning`: `["model training", "neural network", "gradient", "epoch"]`
- `rag`: `["retrieval augmented", "vector store", "embedding", "semantic search"]`
- `data-science`: `["dataframe", "pandas", "matplotlib", "jupyter"]`
- `distributed-systems`: `["consensus", "partition tolerance", "sharding", "replication"]`
- `cloud-infrastructure`: `["EC2", "Lambda", "load balancer", "auto-scaling"]`
- `game-development`: `["game loop", "sprite", "physics engine", "collision"]`
- `developer-tools`: `["CLI", "plugin", "extension", "SDK"]`
- `authentication`: `["OAuth", "JWT", "session token", "SAML"]`
- `edtech`: `["curriculum", "assessment", "learning management", "student"]`
- `creative-tools`: `["canvas", "rendering", "3D", "animation"]`
- `computer-science`: `["algorithm", "data structure", "complexity", "recursion"]`

**Soft skills** — behavioral keywords:
- `communication`: `["explain", "clarify", "document", "present"]`
- `collaboration`: `["pair", "code review", "team", "merge request"]`
- `leadership`: `["mentoring", "onboard", "delegate", "architecture decision"]`
- `problem-solving`: `["debug", "root cause", "hypothesis", "investigate"]`
- `adaptability`: `["pivot", "new approach", "learn", "unfamiliar"]`
- `ownership`: `["end-to-end", "ship", "maintain", "on-call"]`

Note: these are starter patterns. After initial extraction run, review session hit rates and refine any that exceed 30% match rate. Some patterns (especially practices/domains/soft_skills) may need to be made stricter.

- [ ] **Step 4: Run all taxonomy tests**

Run: `.venv/bin/python -m pytest tests/test_taxonomy_patterns.py -v`
Expected: all PASS

- [ ] **Step 5: Run existing tests to verify no regressions**

Run: `.venv/bin/python -m pytest tests/test_skill_taxonomy.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/data/taxonomy.json tests/test_taxonomy_patterns.py
git commit -m "Expand taxonomy: content_patterns for all 78 entries"
```

---

## Task 4: Refactor extractor.py to thin orchestrator

**Depends on:** Task 1 (shared interfaces exist)
**Files:**
- Modify: `src/claude_candidate/extractor.py`

This task refactors the existing extractor to use `NormalizedSession` and the orchestrator pattern, while **keeping existing behavior identical**. The three new extractors are stubbed — they delegate to the existing logic. This is a refactoring step, not a feature step.

- [ ] **Step 1: Run existing tests to establish baseline**

Run: `.venv/bin/python -m pytest tests/test_extractor.py -v`
Expected: all PASS — record count for comparison

- [ ] **Step 2: Add NormalizedSession construction to extractor**

At the top of `extract_session_signals()`, after normalizing messages, construct a `NormalizedSession`:

```python
from claude_candidate.extractors import NormalizedSession

# Inside extract_session_signals, after normalize_messages:
cwd = next((m["raw"].get("cwd", "") for m in messages if m["raw"].get("cwd")), "")
session = NormalizedSession(
	session_id=_extract_session_id(messages),
	timestamp=_parse_timestamp(_extract_timestamp(messages)),
	cwd=cwd,
	project_context=_extract_project_hint(messages),
	git_branch=_extract_git_branch(messages),
	messages=messages,
)
```

Add helper `_extract_git_branch`:
```python
def _extract_git_branch(messages: list[NormalizedMessage]) -> str | None:
	for msg in messages:
		branch = msg["raw"].get("gitBranch", "")
		if branch:
			return branch
	return None
```

- [ ] **Step 3: Run tests — should still all pass**

Run: `.venv/bin/python -m pytest tests/test_extractor.py -v`
Expected: all PASS — same count as baseline

- [ ] **Step 4: Commit**

```bash
git add src/claude_candidate/extractor.py
git commit -m "Refactor extractor: add NormalizedSession construction"
```

---

## Task 5: CodeSignalExtractor (Tier 1)

**Depends on:** Tasks 1, 2, 3 (interfaces, package map, taxonomy patterns)
**Files:**
- Create: `src/claude_candidate/extractors/code_signals.py`
- Create: `tests/test_extractors/test_code_signals.py`
- Create: `tests/fixtures/sessions/import_heavy_session.jsonl`

**This task can run in a parallel worktree.**

- [ ] **Step 1: Create test fixture with imports and package commands**

Create `tests/fixtures/sessions/import_heavy_session.jsonl` — a synthetic session JSONL containing:
- Assistant messages with Python imports (`from fastapi import FastAPI`, `import boto3`)
- Assistant messages with JS imports (`import React from 'react'`, `import { useState } from 'react'`)
- Bash tool_use with `pip install playwright httpx`
- Bash tool_use with `npm install next @anthropic-ai/sdk`
- File paths: `.py`, `.tsx`, `.go` files
- Content with taxonomy patterns for fastapi, pydantic, pytest

Use the same JSONL structure as existing fixtures in `tests/fixtures/sessions/`.

- [ ] **Step 2: Write CodeSignalExtractor tests**

```python
# tests/test_extractors/test_code_signals.py
"""Tests for CodeSignalExtractor."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_candidate.extractors import NormalizedSession, SkillSignal
from claude_candidate.extractors.code_signals import CodeSignalExtractor
from claude_candidate.message_format import normalize_messages

FIXTURES = Path("tests/fixtures/sessions")


def _load_session(filename: str) -> NormalizedSession:
	"""Load a fixture JSONL file into a NormalizedSession."""
	lines = (FIXTURES / filename).read_text().strip().splitlines()
	raw_events = [json.loads(line) for line in lines if line.strip()]
	messages = normalize_messages(raw_events)
	session_id = "test-session"
	for msg in messages:
		sid = msg["raw"].get("sessionId", "")
		if sid:
			session_id = sid
			break
	return NormalizedSession(
		session_id=session_id,
		timestamp=datetime.now(timezone.utc),
		cwd="/Users/test/git/myproject",
		project_context="myproject",
		messages=messages,
	)


class TestCodeSignalExtractor:
	@pytest.fixture
	def extractor(self):
		return CodeSignalExtractor()

	def test_name(self, extractor):
		assert extractor.name() == "code_signals"

	def test_detects_python_from_file_extension(self, extractor):
		session = _load_session("simple_python_session.jsonl")
		result = extractor.extract_session(session)
		skill_names = set(result.skills.keys())
		assert "python" in skill_names

	def test_detects_fastapi_from_content_pattern(self, extractor):
		session = _load_session("simple_python_session.jsonl")
		result = extractor.extract_session(session)
		assert "fastapi" in result.skills

	def test_detects_imports(self, extractor):
		session = _load_session("import_heavy_session.jsonl")
		result = extractor.extract_session(session)
		skill_names = set(result.skills.keys())
		# Should detect from import statements
		assert "fastapi" in skill_names
		assert "aws" in skill_names  # from boto3 import

	def test_detects_package_commands(self, extractor):
		session = _load_session("import_heavy_session.jsonl")
		result = extractor.extract_session(session)
		# Should find skills from pip/npm install commands
		has_package_source = any(
			sig.source == "package_command"
			for sigs in result.skills.values()
			for sig in sigs
		)
		assert has_package_source

	def test_import_source_has_correct_confidence(self, extractor):
		session = _load_session("import_heavy_session.jsonl")
		result = extractor.extract_session(session)
		for sigs in result.skills.values():
			for sig in sigs:
				if sig.source == "import_statement":
					assert sig.confidence == 0.85
				elif sig.source == "package_command":
					assert sig.confidence == 0.7

	def test_multi_tech_session(self, extractor):
		session = _load_session("multi_tech_session.jsonl")
		result = extractor.extract_session(session)
		skill_names = set(result.skills.keys())
		# multi_tech has python, typescript, react, docker
		assert len(skill_names) >= 3

	def test_empty_session(self, extractor):
		session = NormalizedSession(
			session_id="empty",
			timestamp=datetime.now(timezone.utc),
			cwd="/tmp",
			project_context="test",
			messages=[],
		)
		result = extractor.extract_session(session)
		assert result.skills == {}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_extractors/test_code_signals.py -v`
Expected: FAIL — `code_signals` module doesn't exist

- [ ] **Step 4: Implement CodeSignalExtractor**

Create `src/claude_candidate/extractors/code_signals.py`. This absorbs:
- Existing `FILE_EXTENSION_MAP` and `_detect_from_file_path()`
- Existing `_detect_from_content()` and `_get_content_patterns()`
- New: `_detect_from_imports()` — regex parsers for Python/JS/TS/Rust/Go import statements
- New: `_detect_from_package_commands()` — regex parsers for pip/npm/cargo/go install commands
- Both new methods use `package_to_skill_map.json` for resolution

Key implementation details:
- The `extract_session()` method iterates all messages, running all 4 detection layers
- Each detection produces `SkillSignal` objects with appropriate `source` and `confidence`
- Import regex patterns:
  - Python: `r'^(?:from|import)\s+([\w.]+)'` (in code blocks or tool_use content)
  - JS/TS: `r'(?:import\s+.*?from\s+[\'"]|require\s*\(\s*[\'"])([@\w/.-]+)'`
  - Rust: `r'^use\s+([\w:]+)'`
  - Go: `r'"([\w./]+)"'` (within import blocks)
- Package command patterns:
  - `r'pip3?\s+install\s+(.+)'`
  - `r'(?:npm|yarn|pnpm|bun)\s+(?:install|add|i)\s+(.+)'`
  - `r'cargo\s+(?:add|install)\s+(.+)'`
  - `r'go\s+get\s+(.+)'`

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_extractors/test_code_signals.py -v`
Expected: all PASS

- [ ] **Step 6: Run existing extractor tests for regression**

Run: `.venv/bin/python -m pytest tests/test_extractor.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add src/claude_candidate/extractors/code_signals.py tests/test_extractors/test_code_signals.py tests/fixtures/sessions/import_heavy_session.jsonl
git commit -m "Add CodeSignalExtractor: file extensions, patterns, imports, packages"
```

---

## Task 6: BehaviorSignalExtractor (Tier 2 + 3)

**Depends on:** Task 1 (shared interfaces)
**Files:**
- Create: `src/claude_candidate/extractors/behavior_signals.py`
- Create: `tests/test_extractors/test_behavior_signals.py`
- Create: `tests/fixtures/sessions/agent_orchestration_session.jsonl`

**This task can run in a parallel worktree.**

- [ ] **Step 1: Create test fixture with agent orchestration and behavioral signals**

Create `tests/fixtures/sessions/agent_orchestration_session.jsonl` — a synthetic session containing:
- Agent tool_use events with `subagent_type: "Explore"` and `subagent_type: "default"`
- Multiple Agent tool_use in a single assistant message (parallel fan-out)
- TaskCreate tool_use with phased descriptions and dependency fields
- Skill tool_use with `skill: "superpowers:writing-plans"`
- Grep→Read→Edit sequence (debugging pattern)
- Bash error (`is_error: true`) followed by a different Bash command (recovery)
- `gh pr create` in Bash (PR workflow)
- `git worktree add` in Bash (worktree usage)
- `gitBranch: "feat/new-feature"` in raw metadata
- Edit to a `.md` file (documentation pattern)
- Edit to a `test_*.py` file (testing pattern)

Use same JSONL structure as existing fixtures.

- [ ] **Step 2: Write BehaviorSignalExtractor tests**

```python
# tests/test_extractors/test_behavior_signals.py
"""Tests for BehaviorSignalExtractor."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_candidate.extractors import NormalizedSession
from claude_candidate.extractors.behavior_signals import BehaviorSignalExtractor
from claude_candidate.message_format import normalize_messages
from claude_candidate.schemas.candidate_profile import PatternType

FIXTURES = Path("tests/fixtures/sessions")


def _load_session(filename: str) -> NormalizedSession:
	lines = (FIXTURES / filename).read_text().strip().splitlines()
	raw_events = [json.loads(line) for line in lines if line.strip()]
	messages = normalize_messages(raw_events)
	session_id = "test-session"
	git_branch = None
	for msg in messages:
		sid = msg["raw"].get("sessionId", "")
		if sid:
			session_id = sid
		branch = msg["raw"].get("gitBranch", "")
		if branch:
			git_branch = branch
	return NormalizedSession(
		session_id=session_id,
		timestamp=datetime.now(timezone.utc),
		cwd="/Users/test/git/myproject",
		project_context="myproject",
		git_branch=git_branch,
		messages=messages,
	)


class TestPatternDetection:
	@pytest.fixture
	def extractor(self):
		return BehaviorSignalExtractor()

	def test_name(self, extractor):
		assert extractor.name() == "behavior_signals"

	def test_detects_iterative_refinement(self, extractor):
		session = _load_session("simple_python_session.jsonl")
		result = extractor.extract_session(session)
		pattern_types = {p.pattern_type for p in result.patterns}
		# simple_python_session has Write + Bash calls
		assert PatternType.ITERATIVE_REFINEMENT in pattern_types

	def test_detects_recovery_from_failure(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.RECOVERY_FROM_FAILURE in pattern_types

	def test_detects_systematic_debugging(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.SYSTEMATIC_DEBUGGING in pattern_types

	def test_detects_tool_selection(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.TOOL_SELECTION in pattern_types

	def test_detects_documentation_driven(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.DOCUMENTATION_DRIVEN in pattern_types


class TestAgentOrchestration:
	@pytest.fixture
	def extractor(self):
		return BehaviorSignalExtractor()

	def test_detects_agentic_workflows_skill(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		assert "agentic-workflows" in result.skills

	def test_agent_dispatch_metadata(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		signals = result.skills.get("agentic-workflows", [])
		assert any(sig.source == "agent_dispatch" for sig in signals)

	def test_skill_invocation_detected(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		# Skill tool_use should produce TOOL_SELECTION pattern
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.TOOL_SELECTION in pattern_types

	def test_metrics_include_agent_count(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		assert "agent_dispatch_count" in result.metrics
		assert result.metrics["agent_dispatch_count"] >= 1


class TestGitWorkflow:
	@pytest.fixture
	def extractor(self):
		return BehaviorSignalExtractor()

	def test_detects_git_from_branch(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		assert "git" in result.skills

	def test_detects_worktree_usage(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		git_signals = result.skills.get("git", [])
		has_worktree = any("worktree" in sig.metadata.get("signal", "") for sig in git_signals)
		assert has_worktree


class TestEvidenceType:
	@pytest.fixture
	def extractor(self):
		return BehaviorSignalExtractor()

	def test_debugging_evidence_type(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		# Should have at least one debugging evidence type
		all_types = {
			sig.evidence_type
			for sigs in result.skills.values()
			for sig in sigs
		}
		assert "debugging" in all_types or "direct_usage" in all_types

	def test_testing_evidence_type(self, extractor):
		session = _load_session("agent_orchestration_session.jsonl")
		result = extractor.extract_session(session)
		all_types = {
			sig.evidence_type
			for sigs in result.skills.values()
			for sig in sigs
		}
		assert "testing" in all_types
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_extractors/test_behavior_signals.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 4: Implement BehaviorSignalExtractor**

Create `src/claude_candidate/extractors/behavior_signals.py`. Implements:

**Pattern detection** — all 12 PatternType values:
- Retain existing 4 heuristics (iterative_refinement, architecture_first, testing_instinct, modular_thinking)
- Add 8 new: analyze tool_use sequences, error flags, Agent/Skill/TaskCreate events

**Agent orchestration signals:**
- Count Agent tool_use events, extract subagent_type from input
- Detect parallel dispatches (multiple Agent calls in one assistant message)
- Detect worktree commands in Bash inputs
- Detect Skill invocations and map to TOOL_SELECTION pattern

**Git workflow:**
- Read gitBranch from session metadata → git skill signal
- Detect `git worktree`, `gh pr create`, branch naming patterns in Bash commands

**Quality practice signals:**
- Security: scan Edit/Write tool_use inputs for security-related file paths and keywords
- Testing: detect test file Write/Edit and test framework commands in Bash
- Code review: detect `gh pr`, "copilot review" in Bash commands

**Evidence type classification:**
- Use tool sequence context to assign appropriate evidence_type to each SkillSignal

**Metrics output:**
- `agent_dispatch_count`, `parallel_dispatch_count`, `skill_invocation_count`
- `error_count`, `recovery_count`, `test_file_edit_count`
- `worktree_usage` (boolean as 0/1), `branch_type` (feat/fix/cleanup/other)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_extractors/test_behavior_signals.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/extractors/behavior_signals.py tests/test_extractors/test_behavior_signals.py tests/fixtures/sessions/agent_orchestration_session.jsonl
git commit -m "Add BehaviorSignalExtractor: all 12 patterns, agent orchestration, git workflow"
```

---

## Task 7: CommSignalExtractor (Tier 3 + 4 cherry-picks)

**Depends on:** Task 1 (shared interfaces)
**Files:**
- Create: `src/claude_candidate/extractors/comm_signals.py`
- Create: `tests/test_extractors/test_comm_signals.py`
- Create: `tests/fixtures/sessions/steering_session.jsonl`

**This task can run in a parallel worktree.**

- [ ] **Step 1: Create test fixture with communication signals**

Create `tests/fixtures/sessions/steering_session.jsonl` — a synthetic session containing:
- A user message: `"no, just the basics for now"` (short, redirect, scope management)
- A user message: `"grill me on this, be honest"` (adversarial self-review)
- A user message: `"only one change. fade dots, not the whole background"` (steering precision)
- A user message: `"save the session and pick up fresh"` (session boundary)
- A user message referencing `.claude/plans/some-plan.md` (plan file reference)
- A long assistant response before each short user correction (to trigger steering detection)
- A Write tool_use creating a file named `handoff-context.md`
- A `/clear` command message

- [ ] **Step 2: Write CommSignalExtractor tests**

```python
# tests/test_extractors/test_comm_signals.py
"""Tests for CommSignalExtractor."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from claude_candidate.extractors import NormalizedSession
from claude_candidate.extractors.comm_signals import CommSignalExtractor
from claude_candidate.message_format import normalize_messages
from claude_candidate.schemas.candidate_profile import PatternType

FIXTURES = Path("tests/fixtures/sessions")


def _load_session(filename: str) -> NormalizedSession:
	lines = (FIXTURES / filename).read_text().strip().splitlines()
	raw_events = [json.loads(line) for line in lines if line.strip()]
	messages = normalize_messages(raw_events)
	return NormalizedSession(
		session_id="test-session",
		timestamp=datetime.now(timezone.utc),
		cwd="/Users/test/git/myproject",
		project_context="myproject",
		messages=messages,
	)


class TestSteeringPrecision:
	@pytest.fixture
	def extractor(self):
		return CommSignalExtractor()

	def test_detects_steering(self, extractor):
		session = _load_session("steering_session.jsonl")
		result = extractor.extract_session(session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.COMMUNICATION_CLARITY in pattern_types

	def test_steering_metadata_count(self, extractor):
		session = _load_session("steering_session.jsonl")
		result = extractor.extract_session(session)
		clarity = [p for p in result.patterns if p.pattern_type == PatternType.COMMUNICATION_CLARITY]
		assert len(clarity) >= 1
		assert clarity[0].metadata.get("steering_count", 0) >= 1


class TestScopeManagement:
	@pytest.fixture
	def extractor(self):
		return CommSignalExtractor()

	def test_detects_scope_management(self, extractor):
		session = _load_session("steering_session.jsonl")
		result = extractor.extract_session(session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.SCOPE_MANAGEMENT in pattern_types

	def test_deferral_count(self, extractor):
		session = _load_session("steering_session.jsonl")
		result = extractor.extract_session(session)
		scope = [p for p in result.patterns if p.pattern_type == PatternType.SCOPE_MANAGEMENT]
		assert len(scope) >= 1
		assert scope[0].metadata.get("deferral_count", 0) >= 1


class TestAdversarialSelfReview:
	@pytest.fixture
	def extractor(self):
		return CommSignalExtractor()

	def test_detects_grill_me(self, extractor):
		session = _load_session("steering_session.jsonl")
		result = extractor.extract_session(session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.META_COGNITION in pattern_types

	def test_grill_count(self, extractor):
		session = _load_session("steering_session.jsonl")
		result = extractor.extract_session(session)
		meta = [p for p in result.patterns if p.pattern_type == PatternType.META_COGNITION]
		assert len(meta) >= 1
		assert meta[0].metadata.get("grill_count", 0) >= 1


class TestHandoffDiscipline:
	@pytest.fixture
	def extractor(self):
		return CommSignalExtractor()

	def test_detects_handoff(self, extractor):
		session = _load_session("steering_session.jsonl")
		result = extractor.extract_session(session)
		pattern_types = {p.pattern_type for p in result.patterns}
		assert PatternType.DOCUMENTATION_DRIVEN in pattern_types

	def test_handoff_metadata(self, extractor):
		session = _load_session("steering_session.jsonl")
		result = extractor.extract_session(session)
		doc = [p for p in result.patterns if p.pattern_type == PatternType.DOCUMENTATION_DRIVEN]
		assert len(doc) >= 1
		meta = doc[0].metadata
		assert meta.get("handoff_count", 0) >= 1 or meta.get("plan_references", 0) >= 1


class TestHumanMessageFiltering:
	@pytest.fixture
	def extractor(self):
		return CommSignalExtractor()

	def test_filters_tool_results(self, extractor):
		"""tool_result messages masquerading as user role should be filtered."""
		session = _load_session("steering_session.jsonl")
		result = extractor.extract_session(session)
		# Should not crash, and should only analyze actual human messages
		assert result.session_id == "test-session"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_extractors/test_comm_signals.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 4: Implement CommSignalExtractor**

Create `src/claude_candidate/extractors/comm_signals.py`. Implements:

**Human message filtering:**
- Filter to only actual human messages: `role == "user"` AND content blocks are text (not tool_result)
- Include command messages: `/clear`, `/compact`, `/model`

**Steering Precision:**
- For each user message: check if it's short (< 150 chars), follows a long assistant message (> 1000 chars text content), and contains redirect keywords ("no", "not that", "instead", "actually", "only", "just", "don't")
- Count total steering events, precision corrections ("only one change", "just the X")
- Output: COMMUNICATION_CLARITY pattern with metadata

**Scope Management:**
- Scan user messages for deferral phrases: "not yet", "later", "just X for now", "let's not", "park that", "out of scope"
- Detect phase-gating: "phase 1", "step 1 first", "before we move on"
- Detect session boundaries: "save the session", "pick up fresh", "clean slate", "wrap up"
- Count each category
- Output: SCOPE_MANAGEMENT pattern with metadata

**Adversarial Self-Review:**
- Scan for: "grill me", "be honest", "be critical", "poke holes", "what am I missing", "any concerns"
- Count grill_count, honesty_requests, self_assessments
- Output: META_COGNITION pattern with metadata

**Handoff Discipline:**
- Scan user messages for: "handoff", "pick up fresh", "leave context for"
- Check Write tool_use file paths for `*handoff*` or `*HANDOFF*`
- Detect `/clear` commands followed by structured opening messages
- Detect `.claude/plans/` path references in user text
- Output: DOCUMENTATION_DRIVEN pattern with metadata

**Metrics output:**
- `human_message_count`, `steering_count`, `deferral_count`, `grill_count`, `handoff_count`, `context_reset_count`

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_extractors/test_comm_signals.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/extractors/comm_signals.py tests/test_extractors/test_comm_signals.py tests/fixtures/sessions/steering_session.jsonl
git commit -m "Add CommSignalExtractor: steering, scope mgmt, grill-me, handoffs"
```

---

## Task 8: SignalMerger + Learning Velocity

**Depends on:** Tasks 5, 6, 7 (all three extractors)
**Files:**
- Create: `src/claude_candidate/extractors/signal_merger.py`
- Create: `tests/test_extractors/test_signal_merger.py`

- [ ] **Step 1: Write SignalMerger tests**

```python
# tests/test_extractors/test_signal_merger.py
"""Tests for SignalMerger."""
from datetime import datetime, timezone

import pytest

from claude_candidate.extractors import SignalResult, SkillSignal, PatternSignal, ProjectSignal
from claude_candidate.extractors.signal_merger import SignalMerger
from claude_candidate.schemas.candidate_profile import (
	CandidateProfile,
	DepthLevel,
	PatternType,
)


def _make_signal_result(
	session_id: str = "s1",
	skills: dict | None = None,
	patterns: list | None = None,
	project_signals: ProjectSignal | None = None,
	metrics: dict | None = None,
) -> SignalResult:
	return SignalResult(
		session_id=session_id,
		session_date=datetime.now(timezone.utc),
		project_context="myproject",
		skills=skills or {},
		patterns=patterns or [],
		project_signals=project_signals,
		metrics=metrics or {},
	)


class TestSkillAggregation:
	def test_deduplicates_across_extractors(self):
		merger = SignalMerger()
		code_result = _make_signal_result(skills={
			"python": [SkillSignal(
				canonical_name="python", source="file_extension",
				confidence=0.9, evidence_snippet="test.py",
			)],
		})
		behavior_result = _make_signal_result(skills={
			"python": [SkillSignal(
				canonical_name="python", source="tool_usage",
				confidence=0.6, evidence_snippet="Edited Python file",
			)],
		})
		profile = merger.merge(
			[code_result, behavior_result],
			manifest_hash="test",
		)
		python = profile.get_skill("python")
		assert python is not None
		# Should have evidence from both sources
		assert len(python.evidence) >= 1

	def test_cross_extractor_confidence_boost(self):
		merger = SignalMerger()
		# Same skill from two different extractors → should boost
		results = [
			_make_signal_result(session_id="s1", skills={
				"docker": [SkillSignal(
					canonical_name="docker", source="file_extension",
					confidence=0.9, evidence_snippet="Dockerfile",
				)],
			}),
			_make_signal_result(session_id="s1", skills={
				"docker": [SkillSignal(
					canonical_name="docker", source="content_pattern",
					confidence=0.75, evidence_snippet="docker build",
				)],
			}),
		]
		profile = merger.merge(results, manifest_hash="test")
		docker = profile.get_skill("docker")
		assert docker is not None

	def test_confidence_capped_at_one(self):
		merger = SignalMerger()
		results = [
			_make_signal_result(skills={
				"python": [SkillSignal(
					canonical_name="python", source="file_extension",
					confidence=0.95, evidence_snippet="test",
				)],
			}),
			_make_signal_result(skills={
				"python": [SkillSignal(
					canonical_name="python", source="import_statement",
					confidence=0.95, evidence_snippet="import os",
				)],
			}),
			_make_signal_result(skills={
				"python": [SkillSignal(
					canonical_name="python", source="tool_usage",
					confidence=0.95, evidence_snippet="python test",
				)],
			}),
		]
		profile = merger.merge(results, manifest_hash="test")
		# Internal confidence should not exceed 1.0


class TestDepthScoring:
	def test_import_only_capped_at_used(self):
		merger = SignalMerger()
		results = [
			_make_signal_result(session_id=f"s{i}", skills={
				"boto3_skill": [SkillSignal(
					canonical_name="aws", source="import_statement",
					confidence=0.85, evidence_snippet="import boto3",
				)],
			})
			for i in range(10)  # many sessions but only imports
		]
		profile = merger.merge(results, manifest_hash="test")
		aws = profile.get_skill("aws")
		if aws:
			assert aws.depth.value in ("mentioned", "used")

	def test_debugging_evidence_boosts_depth(self):
		merger = SignalMerger()
		results = [
			_make_signal_result(session_id=f"s{i}", skills={
				"python": [SkillSignal(
					canonical_name="python", source="file_extension",
					confidence=0.9, evidence_snippet="debugging python",
					evidence_type="debugging",
				)],
			})
			for i in range(5)
		]
		profile = merger.merge(results, manifest_hash="test")
		python = profile.get_skill("python")
		assert python is not None
		# Debugging evidence should push depth higher than frequency alone


class TestPatternAggregation:
	def test_merges_same_pattern_across_sessions(self):
		merger = SignalMerger()
		results = [
			_make_signal_result(
				session_id=f"s{i}",
				patterns=[PatternSignal(
					pattern_type=PatternType.ITERATIVE_REFINEMENT,
					session_ids=[f"s{i}"],
					confidence=0.8,
					description="Write→Bash cycle",
					evidence_snippet="test",
				)],
			)
			for i in range(5)
		]
		profile = merger.merge(results, manifest_hash="test")
		ir = [p for p in profile.problem_solving_patterns
			  if p.pattern_type == PatternType.ITERATIVE_REFINEMENT]
		assert len(ir) == 1
		assert ir[0].frequency in ("common", "dominant")

	def test_all_12_pattern_types_accepted(self):
		merger = SignalMerger()
		results = [
			_make_signal_result(patterns=[PatternSignal(
				pattern_type=pt,
				session_ids=["s1"],
				confidence=0.7,
				description=f"Detected {pt.value}",
				evidence_snippet="test evidence",
			)])
			for pt in PatternType
		]
		profile = merger.merge(results, manifest_hash="test")
		assert len(profile.problem_solving_patterns) == 12


class TestProjectEnrichment:
	def test_replaces_generic_description(self):
		merger = SignalMerger()
		results = [
			_make_signal_result(
				project_signals=ProjectSignal(
					description_fragments=["Built a job matching pipeline with FastAPI"],
					key_decisions=["Chose pydantic v2 over dataclasses for validation"],
					challenges=["Regex backtracking on 61MB session files"],
				),
			),
		]
		profile = merger.merge(results, manifest_hash="test")
		project = profile.projects[0] if profile.projects else None
		assert project is not None
		assert "matching pipeline" in project.description.lower() or len(project.description) > 20
		assert len(project.key_decisions) >= 1
		assert len(project.challenges_overcome) >= 1


class TestProfileAssembly:
	def test_produces_valid_candidate_profile(self):
		merger = SignalMerger()
		results = [
			_make_signal_result(skills={
				"python": [SkillSignal(
					canonical_name="python", source="file_extension",
					confidence=0.9, evidence_snippet="test.py",
				)],
			}),
		]
		profile = merger.merge(results, manifest_hash="test")
		assert isinstance(profile, CandidateProfile)
		assert profile.session_count >= 1
		assert len(profile.skills) >= 1

	def test_empty_results_produces_valid_profile(self):
		merger = SignalMerger()
		profile = merger.merge([], manifest_hash="test")
		assert isinstance(profile, CandidateProfile)
		assert profile.session_count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_extractors/test_signal_merger.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement SignalMerger**

Create `src/claude_candidate/extractors/signal_merger.py`. Implements:

**`merge(results: list[SignalResult], manifest_hash: str) -> CandidateProfile`:**

1. **Skill aggregation** — group all SkillSignals by canonical_name across all results. Union evidence, max confidence, cross-extractor boost (+0.1 for 2 sources, +0.15 for 3, capped at 1.0).

2. **Depth scoring** — retain existing frequency + tool_count heuristics from current extractor. Add modifiers: debugging evidence +1, architecture +1, multi-source +1, import-only cap at USED, package-only cap at MENTIONED.

3. **Pattern aggregation** — group PatternSignals by pattern_type, merge session_id lists, compute frequency (≥5 dominant, ≥3 common, ≥2 occasional, ≥1 rare) and strength.

4. **Project enrichment** — group by project_context, merge description_fragments, key_decisions, challenges from ProjectSignal objects. Replace generic descriptions.

5. **Agentic Learning Velocity** — sort sessions chronologically. For each agentic skill (agent_orchestration, task_decomposition, skill_workflows, context_management, worktree_isolation), score sophistication 0-3 using metrics from BehaviorSignalExtractor and metadata from CommSignalExtractor. Run `ruptures.Pelt` for change point detection if ≥10 sessions. Populate `skill_trajectory` and `learning_velocity_notes`.

6. **Profile assembly** — build CandidateProfile with all fields populated. Derive communication_style from CommSignalExtractor metrics. Derive working_style_summary from top patterns.

**Category mapping:** Use `SkillTaxonomy.load_default().get_category()` for canonical skills. Map `"runtime"` → `"platform"`. Fallback to `"tool"` for unknown categories.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_extractors/test_signal_merger.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/extractors/signal_merger.py tests/test_extractors/test_signal_merger.py
git commit -m "Add SignalMerger: aggregation, depth scoring, patterns, velocity"
```

---

## Task 9: Wire orchestrator and integration test

**Depends on:** Tasks 4, 5, 6, 7, 8 (all extractors + merger)
**Files:**
- Modify: `src/claude_candidate/extractor.py`

- [ ] **Step 1: Run existing tests to establish baseline**

Run: `.venv/bin/python -m pytest tests/test_extractor.py -v`
Expected: all PASS

- [ ] **Step 2: Update extractor.py to use three-extractor pipeline**

Refactor `build_candidate_profile()` (the top-level function called by the CLI) to:
1. Construct `NormalizedSession` objects from session content
2. Fan out to `CodeSignalExtractor`, `BehaviorSignalExtractor`, `CommSignalExtractor`
3. Collect all `SignalResult` objects
4. Pass to `SignalMerger.merge()`
5. Return the `CandidateProfile`

Keep the existing `extract_session_signals()` function as a compatibility shim that delegates to the new pipeline. The CLI calls `build_candidate_profile()`, so as long as that returns the same `CandidateProfile` type, nothing downstream breaks.

- [ ] **Step 3: Run ALL tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all PASS — both new extractor tests and existing tests

- [ ] **Step 4: Run accuracy benchmark**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Expected: 24/24 within 1 grade

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/extractor.py
git commit -m "Wire three-extractor pipeline into main orchestrator"
```

---

## Task 10: ML Enrichment Layer

**Depends on:** Task 9 (pipeline working end-to-end)
**Files:**
- Create: `src/claude_candidate/enrichment/__init__.py`
- Create: `src/claude_candidate/enrichment/embedding_matcher.py`
- Create: `src/claude_candidate/enrichment/evidence_selector.py`
- Create: `src/claude_candidate/enrichment/learning_velocity.py`
- Create: `tests/test_enrichment.py`

- [ ] **Step 1: Write enrichment gate and tests**

```python
# src/claude_candidate/enrichment/__init__.py
"""Optional ML enrichment layer. No-op if torch/sentence-transformers not installed."""

def enrichment_available() -> bool:
	try:
		import torch  # noqa: F401
		import sentence_transformers  # noqa: F401
		return True
	except ImportError:
		return False
```

```python
# tests/test_enrichment.py
"""Tests for ML enrichment layer."""
import pytest
from claude_candidate.enrichment import enrichment_available


class TestEnrichmentGate:
	def test_enrichment_available_returns_bool(self):
		result = enrichment_available()
		assert isinstance(result, bool)

	@pytest.mark.skipif(
		not enrichment_available(),
		reason="ML dependencies not installed",
	)
	def test_embedding_matcher_loads(self):
		from claude_candidate.enrichment.embedding_matcher import EmbeddingMatcher
		matcher = EmbeddingMatcher()
		assert matcher is not None
```

- [ ] **Step 2: Implement embedding_matcher.py**

Only runs when `enrichment_available()` returns True. Implements:
- Load `all-MiniLM-L6-v2` model (cached by sentence-transformers)
- Pre-compute taxonomy embeddings (cached to `~/.claude-candidate/embeddings_cache.npz`)
- `match_skill(text: str) -> tuple[str, float]` — returns (canonical_name, similarity)
- `upgrade_matches(profile: CandidateProfile) -> CandidateProfile` — re-score low-confidence skills

- [ ] **Step 3: Implement evidence_selector.py**

- `select_best_snippet(skill_label: str, candidates: list[str]) -> str`
- Pre-filter: drop < 100 chars, pure questions
- Score by cosine similarity to skill embedding

- [ ] **Step 4: Implement learning_velocity.py**

- `enhance_sophistication_scores(adoption_curves: dict) -> dict`
- Embed agent dispatch prompts for semantic sophistication classification
- Re-run change point detection on improved scores

- [ ] **Step 5: Wire enrichment into orchestrator**

In `extractor.py`, after `SignalMerger.merge()`:
```python
from claude_candidate.enrichment import enrichment_available
if enrichment_available():
    from claude_candidate.enrichment.embedding_matcher import EmbeddingMatcher
    # ... apply enrichment passes
```

- [ ] **Step 6: Run all tests**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all PASS (enrichment tests skip if no torch)

- [ ] **Step 7: Commit**

```bash
git add src/claude_candidate/enrichment/ tests/test_enrichment.py
git commit -m "Add optional ML enrichment: embeddings, evidence selection, velocity"
```

---

## Task 11: End-to-End Verification

**Depends on:** Task 10 (everything wired)
**Files:** none (verification only)

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -v`
Expected: all PASS

- [ ] **Step 2: Run extraction on real sessions**

Run: `.venv/bin/python -m claude_candidate.cli sessions scan`
Expected: completes without error, generates `~/.claude-candidate/candidate_profile.json`

- [ ] **Step 3: Check skill counts**

Run:
```bash
.venv/bin/python -c "
import json; from pathlib import Path
cp = json.loads((Path.home() / '.claude-candidate/candidate_profile.json').read_text())
print(f'Extracted skills: {len(cp[\"skills\"])}')
for s in sorted(cp['skills'], key=lambda x: -x['frequency']):
    print(f'  {s[\"name\"]:30s} depth={s[\"depth\"]:10s} freq={s[\"frequency\"]}')
print(f'Patterns: {len(cp[\"problem_solving_patterns\"])}')
for p in cp['problem_solving_patterns']:
    print(f'  {p[\"pattern_type\"]:30s} freq={p[\"frequency\"]}')
print(f'Projects: {len(cp[\"projects\"])}')
"
```
Expected: **50+ skills** (success criterion #1)

- [ ] **Step 4: Run merge and check corroboration**

Run:
```bash
.venv/bin/python -m claude_candidate.cli profile merge
.venv/bin/python -c "
import json; from pathlib import Path
mp = json.loads((Path.home() / '.claude-candidate/merged_profile.json').read_text())
print(f'Merged skills: {len(mp[\"skills\"])}')
print(f'Corroborated: {mp[\"corroborated_skill_count\"]}')
print(f'Sessions-only: {mp[\"sessions_only_skill_count\"]}')
print(f'Resume-only: {mp[\"resume_only_skill_count\"]}')
"
```
Expected: **15+ corroborated** (success criterion #2)

- [ ] **Step 5: Run accuracy benchmark**

Run: `.venv/bin/python tests/golden_set/benchmark_accuracy.py`
Expected: **24/24 within 1 grade** (success criterion #4)

- [ ] **Step 6: Verify learning velocity populated**

Run:
```bash
.venv/bin/python -c "
import json; from pathlib import Path
cp = json.loads((Path.home() / '.claude-candidate/candidate_profile.json').read_text())
print(f'Skill trajectory: {cp.get(\"skill_trajectory\", \"NOT SET\")}')
print(f'Learning velocity notes: {cp.get(\"learning_velocity_notes\", \"NOT SET\")}')
"
```
Expected: skill_trajectory populated with adoption curve data, learning_velocity_notes has summary

- [ ] **Step 7: Check all 12 pattern types**

Run:
```bash
.venv/bin/python -c "
import json; from pathlib import Path
cp = json.loads((Path.home() / '.claude-candidate/candidate_profile.json').read_text())
types = {p['pattern_type'] for p in cp['problem_solving_patterns']}
print(f'Pattern types found: {len(types)}/12')
for t in sorted(types):
    print(f'  {t}')
all_12 = {'systematic_debugging', 'architecture_first', 'iterative_refinement',
           'tradeoff_analysis', 'scope_management', 'documentation_driven',
           'recovery_from_failure', 'tool_selection', 'modular_thinking',
           'testing_instinct', 'meta_cognition', 'communication_clarity'}
missing = all_12 - types
if missing:
    print(f'MISSING: {missing}')
"
```
Expected: all 12 pattern types present (success criterion #5)

- [ ] **Step 8: Final commit (if any fixes needed)**

Stage only the specific files that were fixed, then commit:
```bash
git add <specific-files-that-changed>
git commit -m "Fix integration issues from end-to-end verification"
```
