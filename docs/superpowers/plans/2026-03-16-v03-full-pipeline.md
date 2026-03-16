# v0.3 Full Pipeline Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build all 5 priority features (session extractor, Claude-powered parsing, repo correlator, proof packages, deliverables) into one working v0.3.0 app via a rolling agent team pipeline.

**Architecture:** Lead + Rolling Specialists team (5 agents). Phase 1 builds the session pipeline (P1) + QA baseline. Phase 2 adds intelligence (P2+P3). Phase 3 adds output generation (P4+P5). Each phase has a user checkpoint. See `docs/superpowers/specs/2026-03-16-v03-agent-team-design.md` for the full spec.

**Tech Stack:** Python 3.11+, Pydantic v2, FastAPI, Click, httpx, aiosqlite, pymupdf, pytest + vcrpy + syrupy + hypothesis + pytest-subprocess, Playwright, Chrome MV3 extension

**Code Standards:** Functions <= 20 lines, cyclomatic complexity <= 5, cognitive complexity <= 8, positional params <= 3, 4-space indent, 100-char line width, absolute imports only, no magic numbers, no commented-out code, no single-letter vars outside loop iterators.

---

## Chunk 1: Setup & P1 Session Scanner

### Task 0: Project Setup (Lead)

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1: Create feature branch**

```bash
git checkout -b feat/v0.3-agent-pipeline
```

- [ ] **Step 2: Add new dev dependencies to pyproject.toml**

Add to `[project.optional-dependencies]` dev section:

```toml
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "asgi-lifespan>=2.1",
    "mypy>=1.11",
    "ruff>=0.7",
    "vcrpy>=8.0",
    "pytest-recording>=0.13",
    "syrupy>=4.0",
    "hypothesis>=6.100",
    "pytest-subprocess>=1.5",
    "pytest-playwright>=0.5",
]
```

- [ ] **Step 3: Add new directories to .gitignore**

Append to `.gitignore`:
```
.superpowers/
```

- [ ] **Step 4: Install updated dependencies**

```bash
cd /Users/brianruggieri/git/candidate-eval
source .venv/bin/activate
pip install -e ".[dev]"
```

- [ ] **Step 5: Create new fixture/test directories**

```bash
mkdir -p tests/fixtures/sessions
mkdir -p tests/fixtures/claude_responses
mkdir -p tests/fixtures/golden_outputs
mkdir -p tests/cassettes
mkdir -p scripts
```

- [ ] **Step 6: Verify existing tests still pass**

```bash
pytest tests/ -v
```
Expected: 195 tests pass.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore tests/fixtures/sessions/.gitkeep tests/fixtures/claude_responses/.gitkeep tests/fixtures/golden_outputs/.gitkeep tests/cassettes/.gitkeep scripts/.gitkeep
git commit -m "Add v0.3 dev dependencies and test directories"
```

---

### Task 1: Create Sanitized Session Fixtures (Session Pipeline Agent)

**Files:**
- Create: `tests/fixtures/sessions/simple_python_session.jsonl`
- Create: `tests/fixtures/sessions/multi_tech_session.jsonl`
- Create: `tests/fixtures/sessions/empty_session.jsonl`
- Create: `tests/fixtures/sessions/malformed_session.jsonl`

- [ ] **Step 1: Examine real session JSONL format**

Read 2-3 real session files from `~/.claude/projects/` to understand the message types and structure. Key fields: `type`, `data`, `uuid`, `timestamp`, `sessionId`, `cwd`. Message types include: `progress`, `user`, `assistant`, `tool_use`, `tool_result`, `file-history-snapshot`.

- [ ] **Step 2: Create simple_python_session.jsonl**

Create a sanitized fixture that mimics a real session with Python/FastAPI work. Must contain:
- A `progress` message with hook data (SessionStart)
- A `user` message asking to build something
- An `assistant` message discussing the approach
- A `tool_use` message (e.g., Write tool creating a `.py` file)
- A `tool_result` with content
- Technology signals: "python", "fastapi", "pydantic", "pytest"
- All paths replaced with generic paths (`/home/user/project/...`)
- All PII replaced with placeholders
- Session ID is a fake UUID

- [ ] **Step 3: Create multi_tech_session.jsonl**

A longer fixture with multiple technology signals: Python, TypeScript, React, Docker, PostgreSQL. Include tool calls that reference multiple file types (`.py`, `.tsx`, `.sql`, `.dockerfile`).

- [ ] **Step 4: Create empty_session.jsonl**

A minimal valid session — just a SessionStart progress message and nothing else.

- [ ] **Step 5: Create malformed_session.jsonl**

A file with some valid JSONL lines and some invalid ones (broken JSON, empty lines, truncated). Tests that the scanner handles gracefully.

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/sessions/
git commit -m "Add sanitized session JSONL test fixtures"
```

---

### Task 2: Session Scanner (Session Pipeline Agent)

**Files:**
- Create: `src/claude_candidate/session_scanner.py`
- Create: `tests/test_session_scanner.py`

The scanner finds JSONL session files on disk and returns metadata about each. It does NOT read content — that's the sanitizer/extractor's job.

- [ ] **Step 1: Write failing tests for session discovery**

Create `tests/test_session_scanner.py`:

```python
"""Tests for session file discovery."""
from pathlib import Path

from claude_candidate.session_scanner import discover_sessions, SessionInfo


class TestDiscoverSessions:
    def test_finds_jsonl_files(self, tmp_path):
        """Discovers .jsonl files in the projects directory."""
        project_dir = tmp_path / "projects" / "project-abc"
        project_dir.mkdir(parents=True)
        session_file = project_dir / "abc-123.jsonl"
        session_file.write_text('{"type":"user"}\n')

        results = discover_sessions(tmp_path / "projects")
        assert len(results) == 1
        assert results[0].path == session_file

    def test_skips_non_jsonl(self, tmp_path):
        """Ignores non-JSONL files."""
        project_dir = tmp_path / "projects" / "project-abc"
        project_dir.mkdir(parents=True)
        (project_dir / "config.json").write_text("{}")
        (project_dir / "notes.txt").write_text("hello")

        results = discover_sessions(tmp_path / "projects")
        assert len(results) == 0

    def test_empty_directory(self, tmp_path):
        """Returns empty list for empty directory."""
        projects_dir = tmp_path / "projects"
        projects_dir.mkdir()
        results = discover_sessions(projects_dir)
        assert len(results) == 0

    def test_nonexistent_directory(self, tmp_path):
        """Returns empty list for nonexistent directory."""
        results = discover_sessions(tmp_path / "nonexistent")
        assert len(results) == 0

    def test_extracts_project_hint(self, tmp_path):
        """Extracts project name from directory path."""
        project_dir = tmp_path / "projects" / "-Users-dev-git-myproject"
        project_dir.mkdir(parents=True)
        (project_dir / "sess.jsonl").write_text('{"type":"user"}\n')

        results = discover_sessions(tmp_path / "projects")
        assert results[0].project_hint == "-Users-dev-git-myproject"

    def test_extracts_session_id_from_filename(self, tmp_path):
        """Uses filename (sans extension) as session_id."""
        project_dir = tmp_path / "projects" / "proj"
        project_dir.mkdir(parents=True)
        (project_dir / "abc-def-123.jsonl").write_text('{"type":"user"}\n')

        results = discover_sessions(tmp_path / "projects")
        assert results[0].session_id == "abc-def-123"

    def test_multiple_projects(self, tmp_path):
        """Discovers sessions across multiple project directories."""
        for name in ["proj-a", "proj-b"]:
            d = tmp_path / "projects" / name
            d.mkdir(parents=True)
            (d / "session.jsonl").write_text('{"type":"user"}\n')

        results = discover_sessions(tmp_path / "projects")
        assert len(results) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_session_scanner.py -v
```
Expected: FAIL — `ModuleNotFoundError: No module named 'claude_candidate.session_scanner'`

- [ ] **Step 3: Implement session scanner**

Create `src/claude_candidate/session_scanner.py`:

```python
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


def discover_sessions(
    projects_dir: Path,
) -> list[SessionInfo]:
    """Find all JSONL session files under a projects directory."""
    if not projects_dir.is_dir():
        return []

    sessions: list[SessionInfo] = []
    for jsonl_path in sorted(projects_dir.rglob("*.jsonl")):
        info = SessionInfo(
            path=jsonl_path,
            session_id=jsonl_path.stem,
            project_hint=_extract_project_hint(jsonl_path),
            file_size_bytes=jsonl_path.stat().st_size,
        )
        sessions.append(info)
    return sessions
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_session_scanner.py -v
```
Expected: 7 tests PASS.

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```
Expected: 202 tests pass (195 + 7 new).

- [ ] **Step 6: Run ruff**

```bash
ruff check src/claude_candidate/session_scanner.py tests/test_session_scanner.py
```
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add src/claude_candidate/session_scanner.py tests/test_session_scanner.py
git commit -m "Add session scanner for JSONL file discovery"
```

---

### Task 3: Sanitizer (Session Pipeline Agent)

**Files:**
- Create: `src/claude_candidate/sanitizer.py`
- Create: `tests/test_sanitizer.py`

The sanitizer reads raw JSONL content, strips secrets/PII/API keys, and returns sanitized content plus a redaction report.

- [ ] **Step 1: Write failing tests for secret detection**

Create `tests/test_sanitizer.py`:

```python
"""Tests for session content sanitizer."""
from claude_candidate.sanitizer import (
    sanitize_text,
    detect_secrets,
    RedactionResult,
    REDACTION_PLACEHOLDER,
)


class TestDetectSecrets:
    def test_detects_api_key_patterns(self):
        text = 'OPENAI_API_KEY=sk-abc123def456'
        findings = detect_secrets(text)
        assert len(findings) > 0
        assert any(f.category == "api_key" for f in findings)

    def test_detects_bearer_tokens(self):
        text = 'Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig'
        findings = detect_secrets(text)
        assert any(f.category == "auth_token" for f in findings)

    def test_detects_aws_keys(self):
        text = 'AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCY'
        findings = detect_secrets(text)
        assert any(f.category == "api_key" for f in findings)

    def test_detects_absolute_paths(self):
        text = '/Users/brianruggieri/git/myproject/secret.py'
        findings = detect_secrets(text)
        assert any(f.category == "absolute_path" for f in findings)

    def test_detects_email_addresses(self):
        text = 'Contact brian@example.com for details'
        findings = detect_secrets(text)
        assert any(f.category == "pii" for f in findings)

    def test_no_false_positives_on_clean_text(self):
        text = 'def hello_world():\n    print("hello")'
        findings = detect_secrets(text)
        assert len(findings) == 0


class TestSanitizeText:
    def test_replaces_api_keys(self):
        text = 'key=sk-abc123def456ghi789'
        result = sanitize_text(text)
        assert 'sk-abc123' not in result.sanitized
        assert REDACTION_PLACEHOLDER in result.sanitized
        assert result.redaction_count > 0

    def test_replaces_absolute_paths(self):
        text = 'file at /Users/brianruggieri/git/proj/main.py'
        result = sanitize_text(text)
        assert '/Users/brianruggieri' not in result.sanitized
        assert result.redaction_count > 0

    def test_preserves_relative_paths(self):
        text = 'file at src/main.py'
        result = sanitize_text(text)
        assert 'src/main.py' in result.sanitized

    def test_preserves_technology_signals(self):
        text = 'Using python with fastapi and pydantic'
        result = sanitize_text(text)
        assert 'python' in result.sanitized
        assert 'fastapi' in result.sanitized

    def test_returns_redaction_summary(self):
        text = 'key=sk-abc OPENAI_API_KEY=sk-def /Users/me/file.py'
        result = sanitize_text(text)
        assert result.redaction_count >= 2
        assert len(result.redactions_by_type) > 0

    def test_handles_empty_input(self):
        result = sanitize_text("")
        assert result.sanitized == ""
        assert result.redaction_count == 0

    def test_idempotent(self):
        """Sanitizing already-sanitized text produces same result."""
        text = 'key=sk-abc123'
        first = sanitize_text(text)
        second = sanitize_text(first.sanitized)
        assert second.sanitized == first.sanitized
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_sanitizer.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement sanitizer**

Create `src/claude_candidate/sanitizer.py`:

```python
"""Sanitizer: strips secrets, PII, and absolute paths from session content."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

REDACTION_PLACEHOLDER = "[REDACTED]"
PATH_REDACTION = "[PATH_REDACTED]"

# --- Pattern definitions ---

API_KEY_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9]{20,}"),
    re.compile(r"key-[a-zA-Z0-9]{20,}"),
    re.compile(r"(?:OPENAI|ANTHROPIC|GITHUB|AWS|SLACK|STRIPE)"
               r"[_-](?:API[_-])?(?:KEY|TOKEN|SECRET)"
               r"\s*[=:]\s*\S+", re.IGNORECASE),
    re.compile(r"AWS_SECRET_ACCESS_KEY\s*[=:]\s*\S+"),
    re.compile(r"ghp_[a-zA-Z0-9]{36}"),
    re.compile(r"gho_[a-zA-Z0-9]{36}"),
]

AUTH_TOKEN_PATTERNS = [
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE),
    re.compile(r"token\s*[=:]\s*[A-Za-z0-9\-._~+/]{20,}", re.IGNORECASE),
]

PII_PATTERNS = [
    re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
]

ABSOLUTE_PATH_PATTERN = re.compile(
    r"/(?:Users|home)/[a-zA-Z0-9._-]+(?:/[^\s\"'`,;)}\]]+)+"
)


@dataclass(frozen=True)
class SecretFinding:
    """A detected secret or sensitive data."""

    category: str
    start: int
    end: int
    matched_text: str


@dataclass
class RedactionResult:
    """Result of sanitizing a text block."""

    sanitized: str
    redaction_count: int
    redactions_by_type: dict[str, int] = field(
        default_factory=dict
    )


PATTERN_GROUPS: list[tuple[str, list[re.Pattern]]] = [
    ("api_key", API_KEY_PATTERNS),
    ("auth_token", AUTH_TOKEN_PATTERNS),
    ("pii", PII_PATTERNS),
]


def _scan_patterns(
    text: str, category: str, patterns: list[re.Pattern],
) -> list[SecretFinding]:
    """Find all matches for a category's patterns."""
    return [
        SecretFinding(category, m.start(), m.end(), m.group())
        for p in patterns for m in p.finditer(text)
    ]


def detect_secrets(text: str) -> list[SecretFinding]:
    """Scan text for secrets, PII, and absolute paths."""
    findings: list[SecretFinding] = []
    for category, patterns in PATTERN_GROUPS:
        findings.extend(_scan_patterns(text, category, patterns))
    findings.extend(
        _scan_patterns(text, "absolute_path", [ABSOLUTE_PATH_PATTERN])
    )
    return findings


def _build_type_counts(
    findings: list[SecretFinding],
) -> dict[str, int]:
    """Count findings per category."""
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.category] = (
            counts.get(finding.category, 0) + 1
        )
    return counts


def sanitize_text(text: str) -> RedactionResult:
    """Remove secrets and PII from text, preserving tech signals."""
    if not text:
        return RedactionResult(
            sanitized="", redaction_count=0
        )

    findings = detect_secrets(text)
    if not findings:
        return RedactionResult(
            sanitized=text, redaction_count=0
        )

    sorted_findings = sorted(
        findings, key=lambda f: f.start, reverse=True
    )

    result = text
    for finding in sorted_findings:
        placeholder = _placeholder_for(finding.category)
        result = (
            result[:finding.start]
            + placeholder
            + result[finding.end:]
        )

    return RedactionResult(
        sanitized=result,
        redaction_count=len(findings),
        redactions_by_type=_build_type_counts(findings),
    )


def _placeholder_for(category: str) -> str:
    """Return the appropriate placeholder for a category."""
    if category == "absolute_path":
        return PATH_REDACTION
    return REDACTION_PLACEHOLDER
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_sanitizer.py -v
```
Expected: 13 tests PASS.

- [ ] **Step 5: Run full suite + ruff**

```bash
pytest tests/ -v && ruff check src/claude_candidate/sanitizer.py
```
Expected: 208+ tests pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/sanitizer.py tests/test_sanitizer.py
git commit -m "Add session content sanitizer with secret detection"
```

---

### Task 4: Signal Extractor (Session Pipeline Agent)

**Files:**
- Create: `src/claude_candidate/extractor.py`
- Create: `tests/test_extractor.py`

The extractor reads sanitized JSONL content and extracts structured signals: technologies used, problem-solving patterns, project summaries. Produces a `CandidateProfile`.

- [ ] **Step 1: Write failing tests for JSONL line parsing**

Create `tests/test_extractor.py`:

```python
"""Tests for session signal extractor."""
import json
from pathlib import Path

from claude_candidate.extractor import (
    parse_session_lines,
    extract_technologies,
    extract_session_signals,
    build_candidate_profile,
    SessionSignals,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sessions"


class TestParseSessionLines:
    def test_parses_valid_jsonl(self):
        lines = [
            '{"type":"user","data":{"text":"hello"}}',
            '{"type":"assistant","data":{"text":"hi"}}',
        ]
        parsed = parse_session_lines(lines)
        assert len(parsed) == 2
        assert parsed[0]["type"] == "user"

    def test_skips_malformed_lines(self):
        lines = [
            '{"type":"user"}',
            'not valid json',
            '{"type":"assistant"}',
        ]
        parsed = parse_session_lines(lines)
        assert len(parsed) == 2

    def test_skips_empty_lines(self):
        lines = ['{"type":"user"}', '', '  ', '{"type":"assistant"}']
        parsed = parse_session_lines(lines)
        assert len(parsed) == 2


class TestExtractTechnologies:
    def test_detects_python_from_tool_use(self):
        messages = [
            {"type": "tool_use", "data": {
                "tool": "Write",
                "input": {"file_path": "/project/main.py", "content": "import fastapi"}
            }}
        ]
        techs = extract_technologies(messages)
        assert "python" in techs
        assert "fastapi" in techs

    def test_detects_typescript_from_file_extension(self):
        messages = [
            {"type": "tool_use", "data": {
                "tool": "Write",
                "input": {"file_path": "/project/app.tsx", "content": "import React"}
            }}
        ]
        techs = extract_technologies(messages)
        assert "typescript" in techs
        assert "react" in techs

    def test_no_duplicates(self):
        messages = [
            {"type": "tool_use", "data": {
                "tool": "Write",
                "input": {"file_path": "/a.py", "content": "import os"}
            }},
            {"type": "tool_use", "data": {
                "tool": "Write",
                "input": {"file_path": "/b.py", "content": "import sys"}
            }},
        ]
        techs = extract_technologies(messages)
        assert techs.count("python") == 1


class TestExtractSessionSignals:
    def test_from_fixture_file(self):
        fixture = FIXTURES_DIR / "simple_python_session.jsonl"
        if not fixture.exists():
            return  # Skip if fixture not yet created
        content = fixture.read_text()
        signals = extract_session_signals(content)
        assert len(signals.technologies) > 0
        assert signals.line_count > 0

    def test_empty_content(self):
        signals = extract_session_signals("")
        assert len(signals.technologies) == 0
        assert signals.line_count == 0


class TestBuildCandidateProfile:
    def test_builds_from_signals_list(self):
        signals_list = [
            SessionSignals(
                session_id="sess-1",
                project_hint="myproject",
                technologies=["python", "fastapi"],
                tool_calls=["Write", "Read", "Bash"],
                patterns_observed=["iterative_refinement"],
                evidence_snippets=["Built a FastAPI endpoint"],
                line_count=100,
                timestamp="2026-03-01T00:00:00Z",
            ),
        ]
        profile = build_candidate_profile(
            signals_list=signals_list,
            manifest_hash="abc123",
        )
        assert profile.session_count == 1
        assert len(profile.skills) > 0
        python_skill = profile.get_skill("python")
        assert python_skill is not None
        assert len(python_skill.evidence) >= 1
        assert len(python_skill.evidence[0].evidence_snippet) <= 500

    def test_merges_technologies_across_sessions(self):
        signals_list = [
            SessionSignals(
                session_id="s1",
                project_hint="proj",
                technologies=["python"],
                tool_calls=["Write"],
                patterns_observed=[],
                evidence_snippets=["Used python"],
                line_count=50,
                timestamp="2026-01-01T00:00:00Z",
            ),
            SessionSignals(
                session_id="s2",
                project_hint="proj",
                technologies=["python", "docker"],
                tool_calls=["Write", "Bash"],
                patterns_observed=[],
                evidence_snippets=["Used python with docker"],
                line_count=75,
                timestamp="2026-02-01T00:00:00Z",
            ),
        ]
        profile = build_candidate_profile(
            signals_list=signals_list,
            manifest_hash="abc123",
        )
        assert profile.session_count == 2
        python_skill = profile.get_skill("python")
        assert python_skill is not None
        assert python_skill.frequency == 2

    def test_evidence_snippets_max_length(self):
        long_snippet = "x" * 600
        signals_list = [
            SessionSignals(
                session_id="s1",
                project_hint="proj",
                technologies=["python"],
                tool_calls=[],
                patterns_observed=[],
                evidence_snippets=[long_snippet],
                line_count=10,
                timestamp="2026-01-01T00:00:00Z",
            ),
        ]
        profile = build_candidate_profile(
            signals_list=signals_list,
            manifest_hash="abc123",
        )
        for skill in profile.skills:
            for ref in skill.evidence:
                assert len(ref.evidence_snippet) <= 500
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_extractor.py -v
```
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement signal extractor**

Create `src/claude_candidate/extractor.py`. This is the core extraction logic. Key design:

- `parse_session_lines(lines)` — parse JSONL, skip malformed
- `extract_technologies(messages)` — detect tech from file extensions, imports, tool names
- `extract_session_signals(content)` — full extraction from one session file
- `build_candidate_profile(signals_list, manifest_hash)` — aggregate signals into CandidateProfile

Technology detection uses file extensions (`.py` -> python, `.tsx` -> typescript/react, etc.) and content pattern matching (import statements, tool usage). The KNOWN_TECHNOLOGIES map should include at least 30 technologies.

Pattern detection maps tool usage patterns to PatternType:
- Heavy Bash + Write -> `iterative_refinement`
- Read before Write -> `architecture_first`
- Test files written first -> `testing_instinct`
- Error messages followed by fixes -> `systematic_debugging`

Evidence snippets are truncated to 500 chars max per the schema constraint.

The full implementation should follow the 20-line function limit. Break large functions into focused helpers.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_extractor.py -v
```
Expected: all tests PASS.

- [ ] **Step 5: Run full suite + ruff**

```bash
pytest tests/ -v && ruff check src/claude_candidate/extractor.py
```
Expected: 220+ tests pass, ruff clean.

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/extractor.py tests/test_extractor.py
git commit -m "Add session signal extractor for CandidateProfile generation"
```

---

### Task 5: Wire CLI Command (Lead)

**Files:**
- Modify: `src/claude_candidate/cli.py`

- [ ] **Step 1: Write failing test for sessions scan command**

Add to `tests/test_integration.py`:

```python
class TestSessionsScanCommand:
    def test_scan_with_fixtures(self, tmp_path, fixtures_dir):
        """Scan fixture session files and produce a CandidateProfile."""
        sessions_dir = fixtures_dir / "sessions"
        output_path = tmp_path / "profile.json"

        result = runner.invoke(main, [
            "sessions", "scan",
            "--session-dir", str(sessions_dir),
            "--output", str(output_path),
        ])

        assert result.exit_code == 0
        assert output_path.exists()

        from claude_candidate.schemas.candidate_profile import CandidateProfile
        profile = CandidateProfile.from_json(output_path.read_text())
        assert profile.session_count > 0
        assert len(profile.skills) > 0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_integration.py::TestSessionsScanCommand -v
```
Expected: FAIL — no `sessions` command group.

- [ ] **Step 3: Add sessions command group to CLI**

Add to `cli.py`:

```python
@main.group()
def sessions() -> None:
    """Manage Claude Code session scanning."""
    pass


@sessions.command()
@click.option("--session-dir", type=click.Path(exists=True),
              help="Directory containing session JSONL files")
@click.option("--output", "-o", type=click.Path(),
              help="Output path for CandidateProfile JSON")
def scan(session_dir: str | None, output: str | None) -> None:
    """Scan session logs and build a CandidateProfile."""
    from claude_candidate.session_scanner import discover_sessions
    from claude_candidate.sanitizer import sanitize_text
    from claude_candidate.extractor import (
        extract_session_signals,
        build_candidate_profile,
    )
    from claude_candidate.manifest import hash_string

    search_dir = Path(session_dir) if session_dir else _default_sessions_dir()
    click.echo(f"Scanning sessions in {search_dir}...")

    sessions_found = discover_sessions(search_dir)
    click.echo(f"  Found {len(sessions_found)} session files")

    if not sessions_found:
        click.echo("No sessions found. Nothing to do.")
        return

    signals_list = []
    for info in sessions_found:
        raw_content = info.path.read_text(errors="replace")
        sanitized = sanitize_text(raw_content)
        signals = extract_session_signals(sanitized.sanitized)
        signals.session_id = info.session_id
        signals.project_hint = info.project_hint
        signals_list.append(signals)

    manifest_hash = hash_string(
        "|".join(s.session_id for s in signals_list)
    )
    profile = build_candidate_profile(
        signals_list=signals_list,
        manifest_hash=manifest_hash,
    )

    click.echo(f"  Skills found: {len(profile.skills)}")
    click.echo(f"  Sessions processed: {profile.session_count}")

    output_path = Path(output) if output else _default_profile_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(profile.to_json())
    click.echo(f"  Profile written to {output_path}")


def _default_sessions_dir() -> Path:
    return Path.home() / ".claude" / "projects"


def _default_profile_path() -> Path:
    return (
        Path.home()
        / ".claude-candidate"
        / "candidate_profile.json"
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/test_integration.py::TestSessionsScanCommand -v
```
Expected: PASS.

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v
```
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/cli.py tests/test_integration.py
git commit -m "Add sessions scan CLI command"
```

---

### Task 6: Test Against Real Sessions (Session Pipeline Agent)

**Files:** None new — validation task.

- [ ] **Step 1: Run scanner against real sessions**

```bash
cd /Users/brianruggieri/git/candidate-eval
source .venv/bin/activate
claude-candidate sessions scan --output /tmp/real_profile.json
```

- [ ] **Step 2: Inspect the output**

Read `/tmp/real_profile.json` and verify:
- `session_count` matches expected number of sessions
- `skills` list contains real technologies the user has worked with
- No absolute paths appear in any field
- No raw session content appears (only evidence snippets <= 500 chars)
- Evidence snippets are meaningful, not garbage
- `confidence_assessment` is reasonable

- [ ] **Step 3: Verify privacy**

```bash
grep -i "brianruggieri" /tmp/real_profile.json
grep -i "sk-" /tmp/real_profile.json
grep -i "@" /tmp/real_profile.json | grep -v "evidence_type"
```
Expected: no matches for any of these.

- [ ] **Step 4: Surface results to user for Checkpoint 1**

Present the real CandidateProfile to the user. Show: skill count, top technologies, session count, any unexpected findings.

---

## Chunk 2: QA Baseline (Parallel with Chunk 1)

### Task 7: Hypothesis Strategies (QA Agent)

**Files:**
- Create: `tests/strategies.py`

- [ ] **Step 1: Create hypothesis strategies for existing Pydantic models**

Create `tests/strategies.py` with reusable `st.builds()` strategies for:
- `SessionReference`
- `SkillEntry`
- `QuickRequirement`
- `CandidateProfile` (simplified — not all fields, just enough for round-trip testing)

Key constraints to encode in strategies:
- `confidence: float` must be 0.0-1.0, no NaN
- `evidence_snippet: str` must be non-empty, max 500 chars
- `frequency: int` must be >= 1
- Enum fields use `st.sampled_from()`

- [ ] **Step 2: Write property-based round-trip tests**

Add to `tests/test_schemas.py`:

```python
from hypothesis import given
from tests.strategies import session_reference_strategy, quick_requirement_strategy


class TestPropertyBased:
    @given(ref=session_reference_strategy)
    def test_session_reference_roundtrip(self, ref):
        json_str = ref.model_dump_json()
        parsed = SessionReference.model_validate_json(json_str)
        assert parsed == ref

    @given(req=quick_requirement_strategy)
    def test_quick_requirement_roundtrip(self, req):
        json_str = req.model_dump_json()
        parsed = QuickRequirement.model_validate_json(json_str)
        assert parsed == req
```

- [ ] **Step 3: Run to verify**

```bash
pytest tests/test_schemas.py::TestPropertyBased -v
```
Expected: PASS (hypothesis runs 100 examples per test by default).

- [ ] **Step 4: Commit**

```bash
git add tests/strategies.py tests/test_schemas.py
git commit -m "Add hypothesis property-based schema tests"
```

---

### Task 8: Playwright Extension Baseline (QA Agent)

**Files:**
- Create: `tests/test_visual_extension.py`

- [ ] **Step 1: Install Playwright browsers**

```bash
playwright install chromium
```

- [ ] **Step 2: Write baseline visual test for extension popup**

Create `tests/test_visual_extension.py`:

```python
"""Visual tests for Chrome extension popup."""
import pytest
from pathlib import Path
from playwright.async_api import async_playwright

EXTENSION_DIR = Path(__file__).parent.parent / "extension"


@pytest.fixture
async def extension_page():
    """Launch Chrome with extension loaded, navigate to popup."""
    async with async_playwright() as pw:
        context = await pw.chromium.launch_persistent_context(
            user_data_dir="",
            headless=False,
            args=[
                f"--disable-extensions-except={EXTENSION_DIR}",
                f"--load-extension={EXTENSION_DIR}",
            ],
        )
        # Get extension ID from service worker
        background = context.service_workers[0] if context.service_workers else None
        if background is None:
            background = await context.wait_for_event("serviceworker")
        ext_id = background.url.split("/")[2]

        page = await context.new_page()
        await page.goto(f"chrome-extension://{ext_id}/popup.html")
        yield page
        await context.close()


class TestPopupBaseline:
    @pytest.mark.skipif(
        not EXTENSION_DIR.exists(),
        reason="Extension directory not found"
    )
    async def test_popup_loads(self, extension_page):
        """Extension popup loads without errors."""
        page = extension_page
        # Should show the loading or no-backend state
        body = await page.text_content("body")
        assert body is not None
        assert len(body) > 0

    async def test_popup_width(self, extension_page):
        """Popup respects 520px width constraint."""
        page = extension_page
        width = await page.evaluate("document.body.offsetWidth")
        assert width <= 520
```

Note: Playwright Chrome extension testing requires `headless=False` (headed mode). This test may need to be marked as requiring a display. The QA agent should determine if `xvfb` or similar is needed for CI.

- [ ] **Step 3: Run baseline tests**

```bash
pytest tests/test_visual_extension.py -v --headed
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_visual_extension.py
git commit -m "Add baseline Playwright visual tests for extension popup"
```

---

## CHECKPOINT 1 GATE

At this point, pause for user review:

1. Present the real CandidateProfile generated from actual sessions
2. Show sanitizer proof (no raw content leaked)
3. All tests pass (195 original + ~30-40 new)
4. QA baseline visual tests for extension

**User must approve before Phase 2 begins.**

---

## Chunk 3: P2 Requirement Parser (Intelligence Agent)

### Task 9: Claude-Powered Requirement Parser (Intelligence Agent)

**Files:**
- Create: `src/claude_candidate/requirement_parser.py`
- Create: `tests/test_requirement_parser.py`
- Create: `scripts/record_claude_fixtures.py`
- Create: `tests/fixtures/claude_responses/parse_swe_posting.json`

- [ ] **Step 1: Record golden fixture from real Claude run**

Create `scripts/record_claude_fixtures.py`:

```python
"""Record real Claude CLI responses as test fixtures."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures" / "claude_responses"
SAMPLE_POSTINGS_DIR = Path(__file__).parent.parent / "tests" / "fixtures"


def record_fixture(posting_path: Path, output_name: str) -> None:
    """Run claude --print against a posting and save the response."""
    posting_text = posting_path.read_text()
    prompt = (
        "Parse this job posting into structured requirements. "
        "Return a JSON array where each element has: "
        "description (string), skill_mapping (list of skill name strings), "
        "priority (must_have|strong_preference|nice_to_have|implied), "
        "source_text (the original text fragment). "
        "Only return the JSON array, no other text.\n\n"
        f"{posting_text}"
    )

    result = subprocess.run(
        ["claude", "--print", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=60,
    )

    if result.returncode != 0:
        print(f"Error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    output_path = FIXTURES_DIR / f"{output_name}.json"
    output_path.write_text(result.stdout)
    print(f"Saved to {output_path}")


if __name__ == "__main__":
    record_fixture(
        SAMPLE_POSTINGS_DIR / "sample_job_posting.txt",
        "parse_swe_posting",
    )
```

Run it once to generate the fixture:
```bash
python scripts/record_claude_fixtures.py
```

- [ ] **Step 2: Write failing tests for requirement parser**

Create `tests/test_requirement_parser.py`:

```python
"""Tests for Claude-powered requirement parser."""
import json
from pathlib import Path

import pytest

from claude_candidate.requirement_parser import (
    parse_requirements_with_claude,
    parse_requirements_from_response,
    parse_requirements_fallback,
)
from claude_candidate.schemas.job_requirements import QuickRequirement

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CLAUDE_FIXTURES = FIXTURES_DIR / "claude_responses"


class TestParseRequirementsFromResponse:
    def test_parses_valid_json_array(self):
        response = json.dumps([{
            "description": "Python experience",
            "skill_mapping": ["python"],
            "priority": "must_have",
            "source_text": "Must have Python",
        }])
        reqs = parse_requirements_from_response(response)
        assert len(reqs) == 1
        assert reqs[0].skill_mapping == ["python"]

    def test_handles_json_in_markdown_block(self):
        response = '```json\n[{"description":"test","skill_mapping":["x"],"priority":"implied","source_text":""}]\n```'
        reqs = parse_requirements_from_response(response)
        assert len(reqs) == 1

    def test_returns_empty_on_invalid_json(self):
        reqs = parse_requirements_from_response("not json at all")
        assert len(reqs) == 0


class TestParseFromGoldenFixture:
    @pytest.mark.skipif(
        not (CLAUDE_FIXTURES / "parse_swe_posting.json").exists(),
        reason="Golden fixture not yet recorded",
    )
    def test_golden_swe_posting(self):
        response = (CLAUDE_FIXTURES / "parse_swe_posting.json").read_text()
        reqs = parse_requirements_from_response(response)
        assert len(reqs) >= 3
        priorities = {r.priority.value for r in reqs}
        assert "must_have" in priorities


class TestParseRequirementsFallback:
    def test_falls_back_to_keyword_matching(self):
        text = "We need a Python developer with Docker experience"
        reqs = parse_requirements_fallback(text)
        assert len(reqs) > 0
        skills = {s for r in reqs for s in r.skill_mapping}
        assert "python" in skills


class TestParseRequirementsWithClaude:
    def test_with_subprocess_fixture(self, fp):
        """Uses pytest-subprocess to replay golden output."""
        golden = CLAUDE_FIXTURES / "parse_swe_posting.json"
        if golden.exists():
            fp.register(
                ["claude", "--print", "-p", fp.any()],
                stdout=golden.read_text(),
            )
            posting = (FIXTURES_DIR / "sample_job_posting.txt").read_text()
            reqs = parse_requirements_with_claude(posting)
            assert len(reqs) >= 3
```

- [ ] **Step 3: Implement requirement parser**

Create `src/claude_candidate/requirement_parser.py`:

```python
"""Requirement parser: Claude-powered NLP extraction of job requirements."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from claude_candidate.schemas.job_requirements import (
    QuickRequirement,
    RequirementPriority,
)

CLAUDE_TIMEOUT_SECONDS = 60
PARSE_PROMPT_TEMPLATE = (
    "Parse this job posting into structured requirements. "
    "Return a JSON array where each element has: "
    "description (string), skill_mapping (list of skill name strings), "
    "priority (must_have|strong_preference|nice_to_have|implied), "
    "source_text (the original text fragment). "
    "Only return the JSON array, no other text.\n\n{posting_text}"
)


def parse_requirements_with_claude(
    posting_text: str,
) -> list[QuickRequirement]:
    """Parse requirements using Claude CLI. Falls back to keyword matching."""
    try:
        response = _call_claude_cli(posting_text)
        reqs = parse_requirements_from_response(response)
        if reqs:
            return reqs
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    return parse_requirements_fallback(posting_text)


def _call_claude_cli(posting_text: str) -> str:
    """Invoke claude --print and return stdout."""
    prompt = PARSE_PROMPT_TEMPLATE.format(
        posting_text=posting_text
    )
    result = subprocess.run(
        ["claude", "--print", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT_SECONDS,
    )
    result.check_returncode()
    return result.stdout


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` wrappers if present."""
    pattern = r"```(?:json)?\s*\n?(.*?)\n?\s*```"
    match = re.search(pattern, text, re.DOTALL)
    return match.group(1) if match else text


def parse_requirements_from_response(
    response: str,
) -> list[QuickRequirement]:
    """Parse Claude's JSON response into QuickRequirement list."""
    cleaned = _strip_markdown_fences(response.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    return _validate_requirements(data)


def _validate_requirements(
    data: list[dict],
) -> list[QuickRequirement]:
    """Validate and convert raw dicts to QuickRequirement."""
    results: list[QuickRequirement] = []
    for item in data:
        try:
            req = QuickRequirement(**item)
            results.append(req)
        except (ValueError, TypeError):
            continue
    return results


# --- Fallback: keyword matching (existing v0.1 logic) ---

TECH_KEYWORDS: dict[str, list[str]] = {
    "python": ["python"],
    "typescript": ["typescript", "ts"],
    "javascript": ["javascript", "js"],
    "react": ["react", "react.js"],
    "node.js": ["node", "node.js"],
    "docker": ["docker", "containers"],
    "kubernetes": ["kubernetes", "k8s"],
    "aws": ["aws", "amazon web services"],
    "postgresql": ["postgresql", "postgres"],
    "git": ["git"],
}

MUST_HAVE_SIGNALS = ["required", "must", "need", "essential"]
PREFERRED_SIGNALS = ["preferred", "ideal", "bonus", "plus"]


def parse_requirements_fallback(
    text: str,
) -> list[QuickRequirement]:
    """Keyword-based requirement extraction (v0.1 fallback)."""
    text_lower = text.lower()
    lines = text_lower.split("\n")
    requirements: list[QuickRequirement] = []

    for tech, keywords in TECH_KEYWORDS.items():
        if not _text_contains_keyword(text_lower, keywords):
            continue
        priority = _infer_priority(lines, keywords)
        requirements.append(QuickRequirement(
            description=f"Experience with {tech}",
            skill_mapping=[tech],
            priority=priority,
            source_text="",
        ))

    return requirements or _generic_fallback()


def _text_contains_keyword(
    text: str, keywords: list[str],
) -> bool:
    return any(kw in text for kw in keywords)


def _infer_priority(
    lines: list[str], keywords: list[str],
) -> RequirementPriority:
    """Infer priority from surrounding context."""
    for line in lines:
        if not any(kw in line for kw in keywords):
            continue
        if any(w in line for w in MUST_HAVE_SIGNALS):
            return RequirementPriority.MUST_HAVE
        if any(w in line for w in PREFERRED_SIGNALS):
            return RequirementPriority.STRONG_PREFERENCE
    return RequirementPriority.NICE_TO_HAVE


def _generic_fallback() -> list[QuickRequirement]:
    return [QuickRequirement(
        description="General software engineering",
        skill_mapping=["python", "git"],
        priority=RequirementPriority.MUST_HAVE,
        source_text="",
    )]
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_requirement_parser.py -v
```
Expected: PASS.

- [ ] **Step 5: Full suite + ruff**

```bash
pytest tests/ -v && ruff check src/claude_candidate/requirement_parser.py
```

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/requirement_parser.py tests/test_requirement_parser.py scripts/record_claude_fixtures.py
git commit -m "Add Claude-powered requirement parser with keyword fallback"
```

---

### Task 10: Public Repo Correlator (Intelligence Agent)

**Files:**
- Create: `src/claude_candidate/correlator.py`
- Create: `tests/test_correlator.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_correlator.py` with tests for:
- `fetch_public_repos(github_user)` — returns list of repo metadata
- `correlate_repos(repos, session_signals)` — finds filename/temporal/tech overlaps
- Round-trip test on `PublicRepoCorrelation` schema

Use `@pytest.mark.vcr()` decorator for HTTP tests. First run records real GitHub API responses.

Key test scenarios:
- User with public repos gets correlations
- User with no repos gets empty list
- Temporal overlap detection (repo commit dates overlap session dates)
- Filename matching (repo has same filenames as session tool_use targets)
- Technology overlap (repo languages match session technologies)

- [ ] **Step 2: Implement correlator**

Create `src/claude_candidate/correlator.py`:

Key functions:
- `fetch_public_repos(github_user)` — `httpx.get(f"https://api.github.com/users/{user}/repos")`
- `_extract_repo_metadata(repo_json)` — pull name, language, topics, created_at, pushed_at
- `correlate_repos(repos, signals_list)` — compute correlations
- `_compute_correlation_type(repo, signals)` — filename_match, temporal, content_reference, or combined
- `_compute_correlation_strength(overlap_count)` — strong (3+), moderate (2), weak (1)

All functions <= 20 lines. Use httpx for HTTP calls (existing dependency).

- [ ] **Step 3: Record VCR cassettes**

```bash
pytest tests/test_correlator.py -v --record-mode=once
```

This makes real GitHub API calls and saves responses to `tests/cassettes/`.

- [ ] **Step 4: Verify replay works**

```bash
pytest tests/test_correlator.py -v
```
Expected: PASS without network access (replaying cassettes).

- [ ] **Step 5: Full suite + ruff**

```bash
pytest tests/ -v && ruff check src/claude_candidate/correlator.py
```

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/correlator.py tests/test_correlator.py tests/cassettes/
git commit -m "Add GitHub public repo correlator with VCR cassettes"
```

---

### Task 11: Wire Claude Parser + Correlator into CLI (Intelligence Agent + Lead)

**Files:**
- Modify: `src/claude_candidate/cli.py` (Lead — update assess fallback, add `job parse` and `match correlate` commands)

Note: `quick_match.py` logic changes are minimal (the parser already produces `QuickRequirement` objects that the engine accepts). The main work is in `cli.py`.

- [ ] **Step 1: Update assess CLI command to use Claude parser**

In `cli.py`, modify the `assess` command's requirement loading logic. When no `.requirements.json` file exists, call `parse_requirements_with_claude()` instead of `_extract_basic_requirements()`.

Replace the existing fallback in `assess`:
```python
else:
    click.echo("Parsing requirements with Claude...")
    from claude_candidate.requirement_parser import parse_requirements_with_claude
    requirements = parse_requirements_with_claude(job_text)
    click.echo(f"  Extracted {len(requirements)} requirements")
```

- [ ] **Step 2: Add `job parse` CLI command**

```python
@main.group()
def job() -> None:
    """Job posting analysis commands."""
    pass


@job.command()
@click.argument("posting_file", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path())
def parse(posting_file: str, output: str | None) -> None:
    """Parse a job posting into structured requirements."""
    # ... implementation
```

- [ ] **Step 3: Add `match correlate` CLI command**

```python
@main.group()
def match() -> None:
    """Matching and correlation commands."""
    pass


@match.command()
@click.option("--github-user", required=True)
@click.option("--profile", type=click.Path(exists=True))
@click.option("--output", "-o", type=click.Path())
def correlate(github_user: str, profile: str | None, output: str | None) -> None:
    """Correlate public repos with session evidence."""
    # ... implementation
```

- [ ] **Step 4: Write integration tests for new commands**

Add to `tests/test_integration.py`:
- `TestJobParseCommand` — tests `job parse` with sample posting
- `TestMatchCorrelateCommand` — tests `match correlate` (may need VCR)

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/cli.py tests/test_integration.py
git commit -m "Wire Claude parser and correlator into CLI"
```

---

### Task 12: QA — Refactor quick_match.py for Code Standards (QA Agent)

**Files:**
- Modify: `src/claude_candidate/quick_match.py`

- [ ] **Step 1: Audit quick_match.py for violations**

Check each function against limits: <= 20 lines, cyclomatic <= 5, cognitive <= 8, positional params <= 3. The file is 590 lines — expect significant refactoring.

- [ ] **Step 2: Refactor into focused helper modules if needed**

If `quick_match.py` has too many responsibilities, consider splitting into:
- `quick_match.py` — main engine orchestration
- `skill_matching.py` — skill gap analysis dimension
- `alignment_scoring.py` — mission alignment + culture fit dimensions

Each function must be <= 20 lines. Extract named predicates for conditions. Use dispatch tables instead of elif chains. Extract magic numbers to named constants.

- [ ] **Step 3: Verify all existing tests still pass**

```bash
pytest tests/test_quick_match.py -v
```
Expected: 15 tests PASS (no behavioral changes).

- [ ] **Step 4: Run full suite + ruff**

```bash
pytest tests/ -v && ruff check src/claude_candidate/quick_match.py
```

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/quick_match.py
git commit -m "Refactor quick_match.py for code standards compliance"
```

---

### Task 12b: Visual Test — Extension with Improved Scoring (QA Agent)

**Files:**
- Modify: `tests/test_visual_extension.py`

- [ ] **Step 1: Add visual test for improved scores**

Extend `tests/test_visual_extension.py` with a test that:
- Starts the FastAPI server with a real (session-extracted) profile loaded
- Navigates to the extension popup
- Triggers an assessment against the sample job posting
- Verifies that the score bars, grade colors, and skill matches render correctly
- Checks that discovery skills (sessions-only) are highlighted

- [ ] **Step 2: Run visual test**

```bash
pytest tests/test_visual_extension.py -v --headed
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_visual_extension.py
git commit -m "Add visual test for extension with improved scoring"
```

---

## CHECKPOINT 2 GATE

Pause for user review:

1. Compare Claude-parsed requirements vs. old keyword matching on real postings
2. GitHub correlations for user's repos
3. Improved match scores with real data + NLP
4. Extension popup reflects improved scoring (visual test passes)
5. All tests pass

**User must approve before Phase 3 begins.**

---

## Chunk 4: P4 Proof Packages + P5 Deliverables (Output Agent)

### Task 13: Proof Package Generator (Output Agent)

**Files:**
- Create: `src/claude_candidate/proof_generator.py`
- Create: `tests/test_proof_generator.py`

- [ ] **Step 1: Write failing tests**

Tests for:
- `generate_proof_package(assessment, manifest, merged_profile)` — produces markdown report
- Evidence chain: every skill claim links to a SessionReference
- Manifest hash is included and verifiable
- No absolute paths in output
- Output renders as valid markdown

- [ ] **Step 2: Implement proof generator**

The proof package is a markdown document containing:
1. Header with assessment summary (company, title, overall score/grade)
2. Evidence table: each requirement mapped to candidate evidence with session references
3. Skills matrix: corroborated / resume-only / sessions-only breakdown
4. Manifest verification section (manifest_id, hash, session count)
5. Redaction summary (how many redactions, by type)
6. Timestamp and generator version

All functions <= 20 lines. Use template strings for markdown sections.

- [ ] **Step 3: Snapshot test**

```python
def test_proof_package_snapshot(snapshot):
    package = generate_proof_package(assessment, manifest, profile)
    assert package == snapshot
```

First run captures; subsequent runs detect regressions.

- [ ] **Step 4: Run tests + ruff**

```bash
pytest tests/test_proof_generator.py -v && ruff check src/claude_candidate/proof_generator.py
```

- [ ] **Step 5: Commit**

```bash
git add src/claude_candidate/proof_generator.py tests/test_proof_generator.py
git commit -m "Add proof package generator with evidence chain"
```

---

### Task 14: Deliverable Generator (Output Agent)

**Files:**
- Create: `src/claude_candidate/generator.py`
- Create: `tests/test_generator.py`

- [ ] **Step 1: Write failing tests**

Tests for:
- `generate_resume_bullets(assessment, profile)` — tailored bullets grounded in session evidence
- `generate_cover_letter(assessment, profile, company_info)` — personalized cover letter
- `generate_interview_prep(assessment, profile)` — organized interview prep notes
- No template placeholders leak (e.g., `{company_name}` should be replaced)
- Evidence grounding: every bullet traces to session data

- [ ] **Step 2: Implement deliverable generator**

Uses `claude --print` for high-quality generation. Falls back to template-based generation if Claude CLI unavailable.

Key functions:
- `generate_resume_bullets(assessment, profile)` -> list[str]
- `generate_cover_letter(assessment, profile, *, company, title)` -> str
- `generate_interview_prep(assessment, profile)` -> str
- `_call_claude_for_generation(prompt)` -> str (reuses subprocess pattern from requirement_parser)

Each deliverable is grounded in real evidence — the prompts include specific session evidence snippets and assessment scores.

- [ ] **Step 3: Record golden fixtures**

Run the generator once against real data and save outputs to `tests/fixtures/golden_outputs/`.

- [ ] **Step 4: Snapshot tests**

```python
def test_resume_bullets_snapshot(snapshot):
    bullets = generate_resume_bullets(assessment, profile)
    assert bullets == snapshot
```

- [ ] **Step 5: Run tests + ruff**

```bash
pytest tests/test_generator.py -v && ruff check src/claude_candidate/generator.py
```

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/generator.py tests/test_generator.py
git commit -m "Add deliverable generator for resume bullets, cover letter, interview prep"
```

---

### Task 15: Wire Server Endpoints + CLI Commands (Lead)

**Files:**
- Modify: `src/claude_candidate/server.py`
- Modify: `src/claude_candidate/cli.py`

**Refactor on contact:** `server.py` currently uses tab indentation (256 tab-indented lines). When adding endpoints, convert the entire file to 4-space indentation per project convention and code standards.

- [ ] **Step 0: Convert server.py from tabs to 4-space indent**

This must happen before adding new code. Use editor/tool to convert, then run existing tests to verify no breakage:
```bash
pytest tests/test_server.py -v
```

- [ ] **Step 1: Add proof package endpoint**

```python
@app.post("/api/proof")
async def generate_proof(request: ProofRequest):
    # ... generate proof package from assessment_id
```

- [ ] **Step 2: Add deliverables endpoint**

```python
@app.post("/api/generate")
async def generate_deliverables(request: GenerateRequest):
    # ... generate resume bullets, cover letter, interview prep
```

- [ ] **Step 3: Add CLI commands**

```python
@main.command()
def proof(...): ...

@main.command()
def generate(...): ...
```

- [ ] **Step 4: Write integration tests**

Add to `tests/test_integration.py`:
- `TestProofCommand`
- `TestGenerateCommand`

Add to `tests/test_server.py`:
- `TestProofEndpoint`
- `TestGenerateEndpoint`

- [ ] **Step 5: Run full suite**

```bash
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add src/claude_candidate/server.py src/claude_candidate/cli.py tests/test_integration.py tests/test_server.py
git commit -m "Wire proof and deliverable endpoints into server and CLI"
```

---

### Task 16: QA — Visual Testing of Generated Outputs (QA Agent)

**Files:**
- Create: `tests/test_visual_outputs.py`

- [ ] **Step 1: Write visual tests for proof packages**

Render proof package markdown to HTML and verify with Playwright:
- Has a header section with company/title
- Contains an evidence table
- Contains a manifest verification section
- No broken formatting (unclosed tags, raw markdown artifacts)

- [ ] **Step 2: Write visual tests for cover letters**

- Professional formatting
- No template placeholders visible
- Reasonable length (300-600 words)

- [ ] **Step 3: Full end-to-end integration test**

```python
async def test_full_pipeline_end_to_end():
    """Scan -> merge -> match -> proof -> deliverables."""
    # 1. Scan fixture sessions
    # 2. Merge with resume
    # 3. Assess against job posting
    # 4. Generate proof package
    # 5. Generate deliverables
    # Verify all outputs are valid and connected
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_visual_outputs.py
git commit -m "Add visual QA tests for proof packages and deliverables"
```

---

## CHECKPOINT 3 GATE

Pause for user review:

1. Proof package for a real job posting — would you send this to a hiring manager?
2. Generated cover letter and resume bullets — do they represent you well?
3. Interview prep notes — are they useful?
4. Visual quality of all rendered outputs

**User must approve before Final phase begins.**

---

## Chunk 5: Polish & Ship

### Task 17: Final Integration + Version Bump (Lead + QA)

**Files:**
- Modify: `src/claude_candidate/__init__.py` (version bump)
- Modify: `pyproject.toml` (version bump)
- Modify: `extension/manifest.json` (version bump)
- Modify: `README.md`

- [ ] **Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```
Expected: 300+ tests pass.

- [ ] **Step 2: Run ruff on entire codebase**

```bash
ruff check src/ tests/
```
Expected: clean.

- [ ] **Step 3: Version bump to 0.3.0**

Update version in:
- `src/claude_candidate/__init__.py`: `__version__ = "0.3.0"`
- `pyproject.toml`: `version = "0.3.0"`
- `extension/manifest.json`: `"version": "0.3.0"`

- [ ] **Step 4: Update README with new commands**

Add documentation for:
- `sessions scan` command
- `job parse` command
- `match correlate` command
- `proof` command
- `generate` command

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "Bump version to 0.3.0, update README"
```

- [ ] **Step 6: End-to-end demo**

Run the full pipeline:
```bash
claude-candidate sessions scan
claude-candidate job parse tests/fixtures/sample_job_posting.txt -o /tmp/reqs.json
claude-candidate assess --profile ~/.claude-candidate/candidate_profile.json \
    --job tests/fixtures/sample_job_posting.txt \
    --company "Example Corp" --title "Senior Engineer" -o /tmp/assessment.json
claude-candidate proof --assessment /tmp/assessment.json -o /tmp/proof.md
claude-candidate generate --assessment /tmp/assessment.json --type cover-letter -o /tmp/cover.md
```

Present results to user.

---

## CHECKPOINT 4 — FINAL GATE

1. Full end-to-end demo works
2. All tests pass (300+)
3. All touched modules comply with code standards
4. Chrome extension visual QA passes
5. Version 0.3.0

**User approves for daily use.**

---

## Agent Assignment Summary

| Task | Agent | Phase |
|------|-------|-------|
| 0: Project Setup | Lead | 1 |
| 1: Session Fixtures | Session Pipeline | 1 |
| 2: Session Scanner | Session Pipeline | 1 |
| 3: Sanitizer | Session Pipeline | 1 |
| 4: Signal Extractor | Session Pipeline | 1 |
| 5: Wire CLI | Lead | 1 |
| 6: Test Real Sessions | Session Pipeline | 1 |
| 7: Hypothesis Strategies | QA | 1 |
| 8: Playwright Baseline | QA | 1 |
| 9: Requirement Parser | Intelligence | 2 |
| 10: Repo Correlator | Intelligence | 2 |
| 11: Update Quick Match + CLI | Intelligence + Lead | 2 |
| 12: Refactor quick_match.py | QA | 2 |
| 12b: Visual Test Improved Scoring | QA | 2 |
| 13: Proof Generator | Output | 3 |
| 14: Deliverable Generator | Output | 3 |
| 15: Wire Endpoints + CLI | Lead | 3 |
| 16: Visual QA | QA | 3 |
| 17: Polish & Ship | Lead + QA | Final |

## Parallelism Within Phases

**Phase 1:** Tasks 1-6 (Session Pipeline) run in sequence. Tasks 7-8 (QA) run in parallel with Tasks 1-6.

**Phase 2:** Tasks 9-10 (Intelligence) can run in parallel. Task 11 depends on 9. Task 12 depends on 11.

**Phase 3:** Tasks 13-14 (Output) can run in parallel. Task 15 depends on 13+14. Task 16 depends on 15.

**Final:** Task 17 depends on all prior tasks.
