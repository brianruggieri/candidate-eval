"""
Signal extractor: reads sanitized JSONL session content, extracts structured
signals (technologies, problem-solving patterns, project summaries), and builds
a complete CandidateProfile.

Every skill claim traces back to a SessionReference with a valid evidence
snippet (non-empty, <= 500 chars).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from claude_candidate.ai_scoring import compute_ai_engineering_score
from claude_candidate.schemas.candidate_profile import (
    CandidateProfile,
    DepthLevel,
    PatternType,
    ProblemSolvingPattern,
    ProjectComplexity,
    ProjectSummary,
    SessionReference,
    SkillEntry,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_SNIPPET_LENGTH = 500
ELLIPSIS_SUFFIX = "..."
TOP_N_LANGUAGES = 5
TOP_N_DOMAINS = 5
DEFAULT_CONFIDENCE = 0.7

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
}

DOCKERFILE_NAMES: set[str] = {"Dockerfile", "dockerfile"}

CONTENT_PATTERNS: dict[str, list[str]] = {
    "fastapi": ["fastapi", "from fastapi"],
    "pydantic": ["pydantic", "BaseModel"],
    "pytest": ["pytest", "def test_"],
    "react": ["import React", "useState", "useEffect"],
    "docker": ["dockerfile", "docker-compose", "docker build"],
    "sqlalchemy": ["sqlalchemy", "Column(", "Base.metadata"],
    "git": ["git commit", "git push", "git branch"],
}

CATEGORY_MAP: dict[str, str] = {
    "python": "language",
    "javascript": "language",
    "typescript": "language",
    "rust": "language",
    "go": "language",
    "java": "language",
    "sql": "language",
    "fastapi": "framework",
    "react": "framework",
    "pydantic": "framework",
    "sqlalchemy": "framework",
    "pytest": "tool",
    "docker": "tool",
    "git": "tool",
    "postgresql": "platform",
    "aws": "platform",
    "yaml": "tool",
    "toml": "tool",
    "json": "tool",
    "html": "language",
    "css": "language",
}

LANGUAGE_NAMES: set[str] = {
    k for k, v in CATEGORY_MAP.items() if v == "language"
}

# Depth thresholds: (min_frequency, min_tool_count) -> DepthLevel
# Frequency = number of sessions the skill appears in
# Tool count = total tool_calls in sessions where this skill is used
DEPTH_THRESHOLDS: list[tuple[int, int, DepthLevel]] = [
    (8, 3, DepthLevel.EXPERT),
    (5, 2, DepthLevel.DEEP),
    (3, 1, DepthLevel.APPLIED),
    (2, 0, DepthLevel.USED),
]

# AI score thresholds for depth inference (from ai_scoring.py)
AI_SCORE_EXPERT: float = 0.75
AI_SCORE_DEEP: float = 0.55
AI_SCORE_INTERMEDIATE: float = 0.35

# Cross-session aggregation weights
AI_PEAK_WEIGHT: float = 0.7
AI_CONSISTENCY_WEIGHT: float = 0.3

# Keywords that classify a skill as AI-related
AI_SKILL_KEYWORDS: frozenset[str] = frozenset(
    {
        "llm",
        "prompt",
        "ai",
        "ml",
        "machine-learning",
        "rag",
        "embedding",
        "langchain",
        "openai",
        "anthropic",
        "claude",
    }
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class SessionSignals:
    """Extracted signals from a single session."""

    session_id: str = ""
    project_hint: str = ""
    technologies: list[str] = field(default_factory=list)
    tool_calls: list[str] = field(default_factory=list)
    patterns_observed: list[str] = field(default_factory=list)
    evidence_snippets: list[str] = field(default_factory=list)
    line_count: int = 0
    timestamp: str = ""
    ai_scores: dict[str, float | str] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# JSONL parsing
# ---------------------------------------------------------------------------


def _is_valid_json_line(line: str) -> bool:
    """Check if a line is valid JSON (non-empty, parseable)."""
    stripped = line.strip()
    if not stripped:
        return False
    try:
        json.loads(stripped)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def parse_session_lines(lines: list[str]) -> list[dict]:
    """Parse JSONL lines, skip malformed and empty lines."""
    results: list[dict] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            results.append(json.loads(stripped))
        except (json.JSONDecodeError, ValueError):
            continue
    return results


# ---------------------------------------------------------------------------
# Technology extraction
# ---------------------------------------------------------------------------


def _detect_from_file_path(path: str) -> list[str]:
    """Detect technologies from file path extension."""
    filename = path.rsplit("/", maxsplit=1)[-1]
    if filename in DOCKERFILE_NAMES:
        return ["docker"]
    dot_idx = filename.rfind(".")
    if dot_idx < 0:
        return []
    ext = filename[dot_idx:].lower()
    return list(FILE_EXTENSION_MAP.get(ext, []))


def _detect_from_content(content: str) -> list[str]:
    """Detect technologies from content keywords and patterns."""
    lower = content.lower()
    found: list[str] = []
    for tech, patterns in CONTENT_PATTERNS.items():
        if any(p.lower() in lower for p in patterns):
            found.append(tech)
    return found


def _get_text_from_message(msg: dict[str, Any]) -> str:
    """Extract plain text from a user or assistant message dict."""
    message = msg.get("message", {})
    content = message.get("content", [])
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return " ".join(parts)


def _get_tool_input(msg: dict[str, Any]) -> dict[str, Any]:
    """Extract tool input dict from a tool_use message."""
    tool_use = msg.get("toolUse", {})
    return tool_use.get("input", {})


def extract_technologies(messages: list[dict]) -> list[str]:
    """Detect technologies from file extensions and content across messages."""
    seen: set[str] = set()
    for msg in messages:
        _collect_techs_from_message(msg, seen)
    return sorted(seen)


def _collect_techs_from_message(
    msg: dict[str, Any],
    seen: set[str],
) -> None:
    """Collect technologies from a single message into the seen set."""
    msg_type = msg.get("type", "")
    if msg_type == "tool_use":
        _collect_techs_from_tool(msg, seen)
    elif msg_type == "assistant":
        _collect_techs_from_assistant(msg, seen)
    elif msg_type == "user":
        text = _get_text_from_message(msg)
        for tech in _detect_from_content(text):
            seen.add(tech)


def _collect_techs_from_assistant(
    msg: dict[str, Any],
    seen: set[str],
) -> None:
    """Collect techs from assistant message content blocks."""
    content = msg.get("message", {}).get("content", [])
    if not isinstance(content, list):
        return
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "tool_use":
            _collect_techs_from_tool_block(block, seen)
        elif block.get("type") == "text":
            for tech in _detect_from_content(block.get("text", "")):
                seen.add(tech)


def _collect_techs_from_tool_block(
    block: dict[str, Any],
    seen: set[str],
) -> None:
    """Collect techs from a tool_use content block."""
    tool_input = block.get("input", {})
    file_path = tool_input.get("file_path", "")
    if file_path:
        for tech in _detect_from_file_path(file_path):
            seen.add(tech)
    content = tool_input.get("content", "")
    if content:
        for tech in _detect_from_content(content):
            seen.add(tech)


def _collect_techs_from_tool(
    msg: dict[str, Any],
    seen: set[str],
) -> None:
    """Collect technologies from a tool_use message."""
    tool_input = _get_tool_input(msg)
    file_path = tool_input.get("file_path", "")
    if file_path:
        for tech in _detect_from_file_path(file_path):
            seen.add(tech)
    content = tool_input.get("content", "")
    if content:
        for tech in _detect_from_content(content):
            seen.add(tech)


# ---------------------------------------------------------------------------
# Signal extraction helpers
# ---------------------------------------------------------------------------


def _extract_tool_calls(messages: list[dict]) -> list[str]:
    """Extract tool names from both top-level and nested tool_use."""
    tools: list[str] = []
    for msg in messages:
        tools.extend(_tools_from_message(msg))
    return tools


def _tools_from_message(msg: dict[str, Any]) -> list[str]:
    """Get tool names from a single message."""
    if msg.get("type") == "tool_use":
        name = msg.get("toolUse", {}).get("name", "")
        return [name] if name else []
    if msg.get("type") != "assistant":
        return []
    return _tools_from_assistant_content(msg)


def _tools_from_assistant_content(
    msg: dict[str, Any],
) -> list[str]:
    """Extract tool names from assistant message content blocks."""
    content = msg.get("message", {}).get("content", [])
    if not isinstance(content, list):
        return []
    return [
        block.get("name", "")
        for block in content
        if isinstance(block, dict)
        and block.get("type") == "tool_use"
        and block.get("name")
    ]


def _truncate_snippet(text: str) -> str:
    """Enforce 500-char max with ellipsis if truncated."""
    if len(text) <= MAX_SNIPPET_LENGTH:
        return text
    cutoff = MAX_SNIPPET_LENGTH - len(ELLIPSIS_SUFFIX)
    return text[:cutoff] + ELLIPSIS_SUFFIX


def _extract_evidence_snippets(messages: list[dict]) -> list[str]:
    """Extract short text summaries from assistant messages."""
    snippets: list[str] = []
    for msg in messages:
        if msg.get("type") != "assistant":
            continue
        text = _get_text_from_message(msg)
        if text.strip():
            snippets.append(_truncate_snippet(text.strip()))
    return snippets


def _extract_session_id(messages: list[dict]) -> str:
    """Extract the session ID from the first message with one."""
    for msg in messages:
        sid = msg.get("sessionId", "")
        if sid:
            return sid
    return "unknown"


def _extract_timestamp(messages: list[dict]) -> str:
    """Extract the earliest timestamp from messages."""
    for msg in messages:
        ts = msg.get("timestamp", "")
        if ts:
            return ts
    return ""


def _extract_project_hint(messages: list[dict]) -> str:
    """Extract project hint from cwd field of messages."""
    for msg in messages:
        cwd = msg.get("cwd", "")
        if cwd:
            return cwd.rsplit("/", maxsplit=1)[-1]
    return "unknown"


def _detect_patterns(
    tool_calls: list[str],
    technologies: list[str],
) -> list[str]:
    """Detect problem-solving patterns from tool usage and technologies."""
    patterns: list[str] = []
    write_count = tool_calls.count("Write")
    bash_count = tool_calls.count("Bash")
    read_count = tool_calls.count("Read")
    if write_count >= 2 and bash_count >= 1:
        patterns.append("iterative_refinement")
    if read_count >= 1 and write_count >= 1:
        patterns.append("architecture_first")
    if any("test" in t for t in technologies):
        patterns.append("testing_instinct")
    unique_extensions = len(set(technologies))
    if unique_extensions >= 3:
        patterns.append("modular_thinking")
    return patterns


# ---------------------------------------------------------------------------
# Full session extraction
# ---------------------------------------------------------------------------


def extract_session_signals(content: str) -> SessionSignals:
    """Full extraction from one session's JSONL content."""
    if not content.strip():
        return SessionSignals(session_id="unknown")
    lines = content.strip().splitlines()
    messages = parse_session_lines(lines)
    if not messages:
        return SessionSignals(
            session_id="unknown",
            line_count=len(lines),
        )
    technologies = extract_technologies(messages)
    tool_calls = _extract_tool_calls(messages)
    patterns = _detect_patterns(tool_calls, technologies)
    snippets = _extract_evidence_snippets(messages)
    ai_scores = compute_ai_engineering_score(messages)
    return SessionSignals(
        session_id=_extract_session_id(messages),
        project_hint=_extract_project_hint(messages),
        technologies=technologies,
        tool_calls=tool_calls,
        patterns_observed=patterns,
        evidence_snippets=snippets,
        line_count=len(lines),
        timestamp=_extract_timestamp(messages),
        ai_scores=ai_scores,
    )


# ---------------------------------------------------------------------------
# Profile building
# ---------------------------------------------------------------------------


def _classify_category(tech: str) -> str:
    """Map technology name to category; defaults to 'tool'."""
    return CATEGORY_MAP.get(tech.lower(), "tool")


def _is_ai_skill(skill_name: str) -> bool:
    """Check if a skill name is AI-related."""
    lower = skill_name.lower()
    return any(kw in lower for kw in AI_SKILL_KEYWORDS)


def _aggregate_ai_scores(sessions: list[SessionSignals]) -> float | None:
    """Aggregate AI composite scores across sessions. 70% peak + 30% consistency."""
    scores = [
        float(s.ai_scores["composite"])
        for s in sessions
        if s.ai_scores and "composite" in s.ai_scores
    ]
    if not scores:
        return None
    peak = max(scores)
    consistency = sum(scores) / len(scores)
    return peak * AI_PEAK_WEIGHT + consistency * AI_CONSISTENCY_WEIGHT


def _infer_depth(
    frequency: int,
    *,
    tool_count: int,
    ai_composite_score: float | None = None,
) -> DepthLevel:
    """Infer skill depth from frequency and tool usage count.

    When ai_composite_score is provided (AI-related skills), use it to
    determine depth instead of the frequency/tool_count heuristics.
    """
    if ai_composite_score is not None:
        if ai_composite_score >= AI_SCORE_EXPERT:
            return DepthLevel.EXPERT
        if ai_composite_score >= AI_SCORE_DEEP:
            return DepthLevel.DEEP
        if ai_composite_score >= AI_SCORE_INTERMEDIATE:
            return DepthLevel.APPLIED
        return DepthLevel.MENTIONED

    for min_freq, min_tools, level in DEPTH_THRESHOLDS:
        if frequency >= min_freq and tool_count >= min_tools:
            return level
    return DepthLevel.MENTIONED


def _parse_timestamp(ts: str) -> datetime:
    """Parse an ISO timestamp string to timezone-aware datetime."""
    if not ts:
        return _default_timestamp()
    try:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return _ensure_utc(parsed)
    except (ValueError, TypeError):
        return _default_timestamp()


def _default_timestamp() -> datetime:
    """Return a default timezone-aware timestamp."""
    from datetime import timezone
    return datetime(2026, 1, 1, tzinfo=timezone.utc)


def _ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime is timezone-aware (UTC if naive)."""
    from datetime import timezone
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def _sanitize_project_hint(hint: str) -> str:
    """Strip user path prefix from Claude project directory names."""
    # "-Users-brianruggieri-git-myproject" -> "myproject"
    parts = hint.split("-")
    git_indices = [i for i, p in enumerate(parts) if p == "git"]
    if git_indices:
        return "-".join(parts[git_indices[-1] + 1:]) or hint
    return hint


def _build_session_ref(
    signals: SessionSignals,
    snippet: str,
) -> SessionReference:
    """Build a SessionReference from signals and a snippet."""
    return SessionReference(
        session_id=signals.session_id,
        session_date=_parse_timestamp(signals.timestamp),
        project_context=_sanitize_project_hint(signals.project_hint),
        evidence_snippet=_truncate_snippet(snippet),
        evidence_type="direct_usage",
        confidence=DEFAULT_CONFIDENCE,
    )


def _pick_snippet(signals: SessionSignals) -> str:
    """Pick the best evidence snippet from a session's signals."""
    if signals.evidence_snippets:
        return signals.evidence_snippets[0]
    if signals.technologies:
        return f"Used {', '.join(signals.technologies[:5])}"
    return f"Session {signals.session_id}"


def _build_skill_entries(
    signals_list: list[SessionSignals],
) -> list[SkillEntry]:
    """Aggregate technologies across sessions into SkillEntries."""
    tech_data: dict[str, list[SessionSignals]] = {}
    for signals in signals_list:
        for tech in signals.technologies:
            tech_data.setdefault(tech, []).append(signals)
    return [
        _build_one_skill(tech, sessions)
        for tech, sessions in sorted(tech_data.items())
    ]


def _build_one_skill(
    tech: str,
    sessions: list[SessionSignals],
) -> SkillEntry:
    """Build a single SkillEntry for one technology."""
    frequency = len(sessions)
    tool_count = sum(len(s.tool_calls) for s in sessions)
    timestamps = [_parse_timestamp(s.timestamp) for s in sessions]
    evidence = [
        _build_session_ref(s, _pick_snippet(s)) for s in sessions
    ]
    ai_score = _aggregate_ai_scores(sessions) if _is_ai_skill(tech) else None
    return SkillEntry(
        name=tech,
        category=_classify_category(tech),
        depth=_infer_depth(frequency, tool_count=tool_count, ai_composite_score=ai_score),
        frequency=frequency,
        recency=max(timestamps),
        first_seen=min(timestamps),
        evidence=evidence,
    )


def _build_patterns(
    signals_list: list[SessionSignals],
) -> list[ProblemSolvingPattern]:
    """Build ProblemSolvingPatterns from aggregated session signals."""
    pattern_sessions: dict[str, list[SessionSignals]] = {}
    for signals in signals_list:
        for pat in signals.patterns_observed:
            pattern_sessions.setdefault(pat, []).append(signals)
    return [
        _build_one_pattern(name, sessions)
        for name, sessions in sorted(pattern_sessions.items())
    ]


def _pattern_name_to_type(name: str) -> PatternType:
    """Map a pattern string name to the PatternType enum."""
    mapping = {
        "iterative_refinement": PatternType.ITERATIVE_REFINEMENT,
        "architecture_first": PatternType.ARCHITECTURE_FIRST,
        "testing_instinct": PatternType.TESTING_INSTINCT,
        "modular_thinking": PatternType.MODULAR_THINKING,
    }
    return mapping.get(name, PatternType.ITERATIVE_REFINEMENT)


def _pattern_frequency(count: int) -> str:
    """Classify how frequently a pattern was observed."""
    if count >= 5:
        return "dominant"
    if count >= 3:
        return "common"
    if count >= 2:
        return "occasional"
    return "rare"


def _build_one_pattern(
    name: str,
    sessions: list[SessionSignals],
) -> ProblemSolvingPattern:
    """Build a single ProblemSolvingPattern."""
    evidence = [
        _build_session_ref(s, _pick_snippet(s)) for s in sessions
    ]
    return ProblemSolvingPattern(
        pattern_type=_pattern_name_to_type(name),
        frequency=_pattern_frequency(len(sessions)),
        strength="established" if len(sessions) >= 2 else "emerging",
        description=f"Observed {name} pattern across {len(sessions)} session(s)",
        evidence=evidence,
    )


def _build_projects(
    signals_list: list[SessionSignals],
) -> list[ProjectSummary]:
    """Group sessions by project hint and build ProjectSummaries."""
    project_map: dict[str, list[SessionSignals]] = {}
    for signals in signals_list:
        key = signals.project_hint or "unknown"
        project_map.setdefault(key, []).append(signals)
    return [
        _build_one_project(name, sessions)
        for name, sessions in sorted(project_map.items())
    ]


def _project_complexity(session_count: int) -> ProjectComplexity:
    """Classify project complexity by session count."""
    if session_count >= 10:
        return ProjectComplexity.AMBITIOUS
    if session_count >= 5:
        return ProjectComplexity.COMPLEX
    if session_count >= 3:
        return ProjectComplexity.MODERATE
    if session_count >= 2:
        return ProjectComplexity.SIMPLE
    return ProjectComplexity.TRIVIAL


def _build_one_project(
    name: str,
    sessions: list[SessionSignals],
) -> ProjectSummary:
    """Build a single ProjectSummary from grouped sessions."""
    all_techs: set[str] = set()
    for s in sessions:
        all_techs.update(s.technologies)
    timestamps = [_parse_timestamp(s.timestamp) for s in sessions]
    evidence = [
        _build_session_ref(s, _pick_snippet(s)) for s in sessions
    ]
    clean_name = _sanitize_project_hint(name)
    return ProjectSummary(
        project_name=clean_name,
        description=f"Project {clean_name} with {len(sessions)} session(s)",
        complexity=_project_complexity(len(sessions)),
        technologies=sorted(all_techs),
        session_count=len(sessions),
        date_range_start=min(timestamps),
        date_range_end=max(timestamps),
        evidence=evidence,
    )


def _top_languages(skills: list[SkillEntry]) -> list[str]:
    """Return top N language skill names by frequency."""
    langs = [s for s in skills if s.category == "language"]
    langs.sort(key=lambda s: s.frequency, reverse=True)
    return [s.name for s in langs[:TOP_N_LANGUAGES]]


def _top_domains(skills: list[SkillEntry]) -> list[str]:
    """Return top N domain/framework names as proxy for domains."""
    frameworks = [s for s in skills if s.category == "framework"]
    frameworks.sort(key=lambda s: s.frequency, reverse=True)
    return [s.name for s in frameworks[:TOP_N_DOMAINS]]


def _compute_date_range(
    signals_list: list[SessionSignals],
) -> tuple[datetime, datetime]:
    """Compute date range from timestamps across all signals."""
    if not signals_list:
        now = datetime.now()
        return now, now
    timestamps = [
        _parse_timestamp(s.timestamp) for s in signals_list
    ]
    return min(timestamps), max(timestamps)


def _assess_confidence(
    signals_list: list[SessionSignals],
) -> str:
    """Assess overall extraction confidence based on corpus size."""
    count = len(signals_list)
    if count >= 20:
        return "very_high"
    if count >= 10:
        return "high"
    if count >= 3:
        return "moderate"
    return "low"


def _assess_documentation_tendency(
    signals_list: list[SessionSignals],
) -> str:
    """Infer documentation tendency from evidence snippets."""
    total_snippets = sum(
        len(s.evidence_snippets) for s in signals_list
    )
    avg = total_snippets / max(len(signals_list), 1)
    if avg >= 4:
        return "extensive"
    if avg >= 2:
        return "thorough"
    if avg >= 1:
        return "moderate"
    return "minimal"


def _build_working_style(
    patterns: list[ProblemSolvingPattern],
) -> str:
    """Summarize working style from observed patterns."""
    if not patterns:
        return "Insufficient data to characterize working style."
    names = [p.pattern_type.value for p in patterns]
    return f"Working style includes: {', '.join(names)}."


def build_candidate_profile(
    *,
    signals_list: list[SessionSignals],
    manifest_hash: str,
) -> CandidateProfile:
    """Build a complete CandidateProfile from extracted session signals."""
    if not signals_list:
        return _build_empty_profile(manifest_hash)
    skills = _build_skill_entries(signals_list)
    patterns = _build_patterns(signals_list)
    projects = _build_projects(signals_list)
    date_start, date_end = _compute_date_range(signals_list)
    return CandidateProfile(
        generated_at=datetime.now(),
        session_count=len(signals_list),
        date_range_start=date_start,
        date_range_end=date_end,
        manifest_hash=manifest_hash,
        skills=skills,
        primary_languages=_top_languages(skills),
        primary_domains=_top_domains(skills),
        problem_solving_patterns=patterns,
        working_style_summary=_build_working_style(patterns),
        projects=projects,
        communication_style="Technical and detail-oriented",
        documentation_tendency=_assess_documentation_tendency(signals_list),
        extraction_notes=f"Extracted from {len(signals_list)} session(s)",
        confidence_assessment=_assess_confidence(signals_list),
    )


def _build_empty_profile(manifest_hash: str) -> CandidateProfile:
    """Build a minimal profile when no signals are available."""
    now = datetime.now()
    return CandidateProfile(
        generated_at=now,
        session_count=0,
        date_range_start=now,
        date_range_end=now,
        manifest_hash=manifest_hash,
        skills=[],
        primary_languages=[],
        primary_domains=[],
        problem_solving_patterns=[],
        working_style_summary="No sessions available for analysis.",
        projects=[],
        communication_style="Unknown",
        documentation_tendency="minimal",
        extraction_notes="No sessions provided",
        confidence_assessment="low",
    )
