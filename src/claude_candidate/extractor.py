"""
Signal extractor: reads sanitized JSONL session content, extracts structured
signals (technologies, problem-solving patterns, project summaries), and builds
a complete CandidateProfile.

Every skill claim traces back to a SessionReference with a valid evidence
snippet (non-empty, <= 500 chars).
"""

from __future__ import annotations

import functools
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import ahocorasick
import orjson

from claude_candidate.ai_scoring import compute_ai_engineering_score
from claude_candidate.extractors import NormalizedSession
from claude_candidate.message_format import NormalizedMessage, normalize_messages
from claude_candidate.skill_taxonomy import SkillTaxonomy
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

@functools.cache
def _get_content_patterns() -> dict[str, list[str]]:
    """Lazy-load content patterns from the taxonomy (cached after first call)."""
    return SkillTaxonomy.load_default().get_content_patterns()


@functools.cache
def _get_content_automaton() -> ahocorasick.Automaton:
    """Build Aho-Corasick automaton from taxonomy content patterns."""
    patterns = _get_content_patterns()
    automaton = ahocorasick.Automaton()
    # Multiple skills can share the same pattern string, so store lists
    pattern_to_skills: dict[str, list[str]] = {}
    for skill, pattern_list in patterns.items():
        for p in pattern_list:
            key = p.lower()
            pattern_to_skills.setdefault(key, []).append(skill)
    for key, skills in pattern_to_skills.items():
        automaton.add_word(key, skills)
    automaton.make_automaton()
    return automaton

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
    "openai": "platform",
    "anthropic": "platform",
    "langchain": "framework",
    "llm": "domain",
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
        orjson.loads(stripped)
        return True
    except (orjson.JSONDecodeError, ValueError):
        return False


def parse_session_lines(lines: list[str]) -> list[dict]:
    """Parse JSONL lines, skip malformed and empty lines."""
    results: list[dict] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        try:
            results.append(orjson.loads(stripped))
        except (orjson.JSONDecodeError, ValueError):
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
    """Detect technologies from content using Aho-Corasick multi-pattern matching."""
    automaton = _get_content_automaton()
    found: set[str] = set()
    content_lower = content.lower()
    for _, skills in automaton.iter(content_lower):
        for skill in skills:
            found.add(skill)
    return list(found)


def extract_technologies(messages: list[NormalizedMessage]) -> list[str]:
    """Detect technologies from file extensions and content across normalized messages."""
    seen: set[str] = set()
    for msg in messages:
        _collect_techs_from_normalized(msg, seen)
    return sorted(seen)


def _collect_techs_from_normalized(
    msg: NormalizedMessage,
    seen: set[str],
) -> None:
    """Collect technologies from a single normalized message into the seen set."""
    for block in msg["content"]:
        block_type = block.get("type", "")
        if block_type == "tool_use":
            tool_input = block.get("input", {})
            file_path = tool_input.get("file_path", "")
            if file_path:
                for tech in _detect_from_file_path(file_path):
                    seen.add(tech)
            content = tool_input.get("content", "")
            if content:
                for tech in _detect_from_content(content):
                    seen.add(tech)
        elif block_type == "text":
            for tech in _detect_from_content(block.get("text", "")):
                seen.add(tech)


# ---------------------------------------------------------------------------
# Signal extraction helpers
# ---------------------------------------------------------------------------


def _extract_tool_calls(messages: list[NormalizedMessage]) -> list[str]:
    """Extract tool names from normalized messages."""
    tools: list[str] = []
    for msg in messages:
        for block in msg["content"]:
            if block.get("type") == "tool_use":
                name = block.get("name", "")
                if name:
                    tools.append(name)
    return tools


def _truncate_snippet(text: str) -> str:
    """Enforce 500-char max with ellipsis if truncated."""
    if len(text) <= MAX_SNIPPET_LENGTH:
        return text
    cutoff = MAX_SNIPPET_LENGTH - len(ELLIPSIS_SUFFIX)
    return text[:cutoff] + ELLIPSIS_SUFFIX


def _extract_evidence_snippets(messages: list[NormalizedMessage]) -> list[str]:
    """Extract short text summaries from assistant messages."""
    snippets: list[str] = []
    for msg in messages:
        if msg["role"] != "assistant":
            continue
        parts: list[str] = []
        for block in msg["content"]:
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        text = " ".join(parts).strip()
        if text:
            snippets.append(_truncate_snippet(text))
    return snippets


def _extract_session_id(messages: list[NormalizedMessage]) -> str:
    """Extract the session ID from the first message with one."""
    for msg in messages:
        sid = msg["raw"].get("sessionId", "")
        if sid:
            return sid
    return "unknown"


def _extract_timestamp(messages: list[NormalizedMessage]) -> str:
    """Extract the earliest timestamp from messages."""
    for msg in messages:
        ts = msg["raw"].get("timestamp", "")
        if ts:
            return ts
    return ""


def _extract_project_hint(messages: list[NormalizedMessage]) -> str:
    """Extract project hint from cwd field of messages."""
    for msg in messages:
        cwd = msg["raw"].get("cwd", "")
        if cwd:
            return cwd.rsplit("/", maxsplit=1)[-1]
    return "unknown"


def _extract_git_branch(messages: list[NormalizedMessage]) -> str | None:
    """Extract git branch from the first message that has one."""
    for msg in messages:
        branch = msg["raw"].get("gitBranch", "")
        if branch:
            return branch
    return None


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
    raw_messages = parse_session_lines(lines)
    if not raw_messages:
        return SessionSignals(
            session_id="unknown",
            line_count=len(lines),
        )
    messages = normalize_messages(raw_messages)
    cwd = next((m["raw"].get("cwd", "") for m in messages if m["raw"].get("cwd")), "")
    session = NormalizedSession(  # noqa: F841 — used in Task 9
        session_id=_extract_session_id(messages),
        timestamp=_parse_timestamp(_extract_timestamp(messages)),
        cwd=cwd,
        project_context=_extract_project_hint(messages),
        git_branch=_extract_git_branch(messages),
        messages=messages,
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
    """Check if a skill name is AI-related.

    Uses word-boundary matching to avoid false positives like "rails"
    matching "ai" or "html" matching "ml".
    """
    lower = skill_name.lower()
    return any(re.search(rf'\b{re.escape(kw)}\b', lower) for kw in AI_SKILL_KEYWORDS)


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


# Reverse map: technology name -> file extension for synthetic file paths
_TECH_TO_EXTENSION: dict[str, str] = {}
for _ext, _techs in FILE_EXTENSION_MAP.items():
    for _tech in _techs:
        if _tech not in _TECH_TO_EXTENSION:
            _TECH_TO_EXTENSION[_tech] = _ext


def _signals_to_normalized_session(signals: SessionSignals) -> NormalizedSession:
    """Convert a SessionSignals object to a NormalizedSession.

    Transitional shim: SessionSignals has already aggregated the raw data,
    so we reconstruct synthetic NormalizedMessages from what's available.
    The extractors will find skills from:
    - CodeSignalExtractor: file extensions from technologies, content patterns
      in evidence_snippets
    - BehaviorSignalExtractor: tool names in tool_calls
    - CommSignalExtractor: limited (no raw user messages in SessionSignals)
    """
    from claude_candidate.message_format import NormalizedMessage

    messages: list[NormalizedMessage] = []
    raw_base: dict = {
        "sessionId": signals.session_id,
        "timestamp": signals.timestamp,
        "cwd": "",
        "gitBranch": "",
    }

    # Reconstruct tool_use messages from tool_calls
    # NormalizedMessage is a TypedDict — use plain dict literals for clarity.
    for tool_name in signals.tool_calls:
        messages.append({
            "role": "tool_use",
            "content": [{"type": "tool_use", "name": tool_name, "input": {}}],
            "raw": dict(raw_base),
        })

    # Reconstruct synthetic Write tool_use messages from technologies
    # so CodeSignalExtractor can detect them via file extensions
    for tech in signals.technologies:
        ext = _TECH_TO_EXTENSION.get(tech)
        if ext:
            messages.append({
                "role": "tool_use",
                "content": [{
                    "type": "tool_use",
                    "name": "Write",
                    "input": {"file_path": f"/synthetic/file{ext}", "content": ""},
                }],
                "raw": dict(raw_base),
            })

    # Reconstruct assistant text messages from evidence_snippets
    for snippet in signals.evidence_snippets:
        messages.append({
            "role": "assistant",
            "content": [{"type": "text", "text": snippet}],
            "raw": dict(raw_base),
        })

    return NormalizedSession(
        session_id=signals.session_id,
        timestamp=_parse_timestamp(signals.timestamp),
        cwd="",
        project_context=_sanitize_project_hint(signals.project_hint),
        git_branch=None,
        messages=messages,
    )


def build_candidate_profile(
    *,
    signals_list: list[SessionSignals],
    manifest_hash: str,
) -> CandidateProfile:
    """Build a complete CandidateProfile from extracted session signals.

    Uses the three-extractor pipeline (CodeSignalExtractor,
    BehaviorSignalExtractor, CommSignalExtractor) + SignalMerger.
    """
    from claude_candidate.extractors.code_signals import CodeSignalExtractor
    from claude_candidate.extractors.behavior_signals import BehaviorSignalExtractor
    from claude_candidate.extractors.comm_signals import CommSignalExtractor
    from claude_candidate.extractors.signal_merger import SignalMerger

    if not signals_list:
        return _build_empty_profile(manifest_hash)

    # Convert SessionSignals to NormalizedSessions
    sessions = [_signals_to_normalized_session(s) for s in signals_list]

    # Run three extractors
    code_ext = CodeSignalExtractor()
    behavior_ext = BehaviorSignalExtractor()
    comm_ext = CommSignalExtractor()

    all_results = []
    for session in sessions:
        all_results.append(code_ext.extract_session(session))
        all_results.append(behavior_ext.extract_session(session))
        all_results.append(comm_ext.extract_session(session))

    # Merge and build profile
    merger = SignalMerger()
    profile = merger.merge(all_results, manifest_hash=manifest_hash)

    # Optional ML enrichment
    from claude_candidate.enrichment import enrichment_available
    if enrichment_available():
        try:
            from claude_candidate.enrichment.embedding_matcher import EmbeddingMatcher
            # Future: apply enrichment passes here
            pass
        except Exception:
            pass  # Graceful degradation

    return profile


def build_profile_from_signal_results(
    *,
    results: list,
    manifest_hash: str,
) -> CandidateProfile:
    """Build a CandidateProfile directly from pre-computed SignalResult objects.

    This is the preferred path — extractors run on full NormalizedSession data
    (no lossy SessionSignals intermediate). Used by the CLI when processing
    raw JSONL files.
    """
    from claude_candidate.extractors.signal_merger import SignalMerger

    if not results:
        return _build_empty_profile(manifest_hash)

    merger = SignalMerger()
    profile = merger.merge(results, manifest_hash=manifest_hash)

    # Optional ML enrichment
    from claude_candidate.enrichment import enrichment_available
    if enrichment_available():
        try:
            from claude_candidate.enrichment.embedding_matcher import EmbeddingMatcher
            pass
        except Exception:
            pass

    return profile


def extract_session_to_signals(content: str, session_id: str = "", project_hint: str = "") -> list:
    """Extract SignalResults directly from raw JSONL content.

    Parses JSONL, normalizes messages, builds NormalizedSession, and runs
    all three extractors. Returns list of 3 SignalResult objects.
    This bypasses the lossy SessionSignals intermediate.
    """
    from claude_candidate.extractors.code_signals import CodeSignalExtractor
    from claude_candidate.extractors.behavior_signals import BehaviorSignalExtractor
    from claude_candidate.extractors.comm_signals import CommSignalExtractor

    if not content.strip():
        return []

    lines = content.strip().splitlines()
    raw_messages = parse_session_lines(lines)
    if not raw_messages:
        return []

    messages = normalize_messages(raw_messages)

    # Extract session metadata from messages
    sid = session_id or _extract_session_id(messages)
    cwd = next((m["raw"].get("cwd", "") for m in messages if m["raw"].get("cwd")), "")
    project = project_hint or _extract_project_hint(messages)
    git_branch = _extract_git_branch(messages)
    timestamp = _parse_timestamp(_extract_timestamp(messages))

    session = NormalizedSession(
        session_id=sid,
        timestamp=timestamp,
        cwd=cwd,
        project_context=_sanitize_project_hint(project),
        git_branch=git_branch,
        messages=messages,
    )

    # Run all three extractors
    code_ext = CodeSignalExtractor()
    behavior_ext = BehaviorSignalExtractor()
    comm_ext = CommSignalExtractor()

    return [
        code_ext.extract_session(session),
        behavior_ext.extract_session(session),
        comm_ext.extract_session(session),
    ]


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
