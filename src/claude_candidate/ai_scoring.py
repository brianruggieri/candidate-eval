"""
AI Engineering Scoring Module

Scores Claude Code session messages across five dimensions that signal
AI engineering depth. Each dimension returns 0.0–1.0. The composite
score uses a weighted average, and a level label is assigned.

No external dependencies — pure string/dict inspection.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from claude_candidate.message_format import NormalizedMessage

# ---------------------------------------------------------------------------
# Weights (must sum to 1.0)
# ---------------------------------------------------------------------------

WEIGHT_ORCHESTRATION: float = 0.25
WEIGHT_AI_DOMAIN: float = 0.25
WEIGHT_PROMPT_ENGINEERING: float = 0.20
WEIGHT_TOOL_ECOSYSTEM: float = 0.15
WEIGHT_ERROR_RECOVERY: float = 0.15

# Level thresholds
LEVEL_EXPERT: float = 0.75
LEVEL_ADVANCED: float = 0.55
LEVEL_INTERMEDIATE: float = 0.35

# Frequency bonus: applied when a signal category appears multiple times
FREQUENCY_BONUS: float = 0.05
FREQUENCY_BONUS_MAX: float = 0.10  # cap total bonus

# Standard Claude Code tool names (not counted as "custom")
STANDARD_TOOLS: frozenset[str] = frozenset(
	{
		"Bash",
		"Read",
		"Write",
		"Edit",
		"Glob",
		"Grep",
		"Agent",
		"TaskCreate",
		"TaskUpdate",
		"TaskList",
		"SendMessage",
		"TeamCreate",
	}
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _iter_tool_uses(messages: list["NormalizedMessage"]) -> list[dict[str, Any]]:
	"""Return all tool_use blocks from normalized messages."""
	blocks: list[dict[str, Any]] = []
	for msg in messages:
		for block in msg["content"]:
			if block.get("type") == "tool_use":
				blocks.append(block)
	return blocks


def _iter_text_content(messages: list["NormalizedMessage"]) -> list[str]:
	"""Return all text strings found in normalized message content."""
	texts: list[str] = []
	for msg in messages:
		for block in msg["content"]:
			block_type = block.get("type", "")
			if block_type == "text":
				text = block.get("text", "")
				if text:
					texts.append(text)
			elif block_type == "tool_result":
				c = block.get("content", "")
				if isinstance(c, str) and c:
					texts.append(c)
	return texts


def _clamp(value: float) -> float:
	return max(0.0, min(1.0, value))


def _score_from_hits(found: int, total: int, extra_bonus: float = 0.0) -> float:
	"""Normalize found/total to 0-1 and add a bounded frequency bonus."""
	if total == 0:
		return 0.0
	base = found / total
	return _clamp(base + extra_bonus)


# ---------------------------------------------------------------------------
# 1. Orchestration Sophistication (25%)
# ---------------------------------------------------------------------------

# Signal categories and their detection logic (evaluated as presence booleans)
_ORCHESTRATION_SIGNALS = 6  # total possible categories


def score_orchestration(messages: list["NormalizedMessage"]) -> float:
	"""Score orchestration sophistication based on agentic tool usage patterns."""
	if not messages:
		return 0.0

	tool_uses = _iter_tool_uses(messages)
	tool_names = [t.get("name", "") for t in tool_uses]
	tool_inputs = [t.get("input", {}) for t in tool_uses]

	# Category 1: Any Agent tool call
	uses_agent = any(n == "Agent" for n in tool_names)

	# Category 2: Subagent type diversity (>1 distinct subagent_type)
	subagent_types = {
		inp["subagent_type"]
		for inp in tool_inputs
		if isinstance(inp, dict) and "subagent_type" in inp
	}
	has_subagent_diversity = len(subagent_types) >= 2

	# Category 3: Task lifecycle (TaskCreate + TaskUpdate or TaskList)
	task_tools = {n for n in tool_names if n in {"TaskCreate", "TaskUpdate", "TaskList"}}
	has_task_lifecycle = len(task_tools) >= 2

	# Category 4: Parallel tool invocations (multiple tool_use in one message)
	has_parallel = any(
		sum(1 for b in msg["content"] if b.get("type") == "tool_use") >= 2 for msg in messages
	)

	# Category 5: Team creation
	has_team = "TeamCreate" in tool_names

	# Category 6: Inter-agent messaging
	has_messaging = "SendMessage" in tool_names

	found = sum(
		[
			uses_agent,
			has_subagent_diversity,
			has_task_lifecycle,
			has_parallel,
			has_team,
			has_messaging,
		]
	)

	# Frequency bonus: multiple Agent calls beyond the first
	agent_count = tool_names.count("Agent")
	bonus = FREQUENCY_BONUS if agent_count > 1 else 0.0

	return _score_from_hits(found, _ORCHESTRATION_SIGNALS, bonus)


# ---------------------------------------------------------------------------
# 2. AI Domain Knowledge (25%)
# ---------------------------------------------------------------------------

_AI_DOMAIN_PATTERNS: dict[str, list[str]] = {
	"imports": [r"\banthropics?\b", r"\bopenai\b", r"\blangchain\b", r"\bllama_index\b"],
	"api_calls": [r"client\.messages\.create", r"ChatCompletion", r"claude-[34]", r"gpt-[34]"],
	"structured_output": [r"\bresponse_model\b", r"\bjson_schema\b", r"\btool_use\b"],
	"rag": [r"\bembedding\b", r"\bvector\b", r"\bretrieval\b", r"\bchunk\b"],
	"eval": [r"\bevaluate\b", r"\bbenchmark\b", r"\bmetric\b", r"\bscore\b"],
	"guardrails": [r"\bcontent_filter\b", r"\bmoderation\b", r"\bsafety\b"],
}

_AI_DOMAIN_TOTAL = len(_AI_DOMAIN_PATTERNS)


def score_ai_domain(messages: list["NormalizedMessage"]) -> float:
	"""Score AI domain knowledge by detecting LLM/ML pattern categories in text."""
	if not messages:
		return 0.0

	all_text = " ".join(_iter_text_content(messages))
	if not all_text:
		return 0.0

	found = 0
	total_hits = 0
	for _category, patterns in _AI_DOMAIN_PATTERNS.items():
		category_hit = any(re.search(p, all_text, re.IGNORECASE) for p in patterns)
		if category_hit:
			found += 1
			total_hits += sum(1 for p in patterns if re.search(p, all_text, re.IGNORECASE))

	# Frequency bonus: hitting many patterns within categories
	bonus = min(FREQUENCY_BONUS_MAX, FREQUENCY_BONUS * max(0, total_hits - found))

	return _score_from_hits(found, _AI_DOMAIN_TOTAL, bonus)


# ---------------------------------------------------------------------------
# 3. Prompt Engineering (20%)
# ---------------------------------------------------------------------------

_PROMPT_ENG_TOTAL = 5  # five signal categories


def score_prompt_engineering(messages: list["NormalizedMessage"]) -> float:
	"""Score prompt engineering sophistication from user/assistant text patterns."""
	if not messages:
		return 0.0

	all_text = " ".join(_iter_text_content(messages))
	if not all_text:
		return 0.0

	# Category 1: Structured formatting (XML tags or markdown headers)
	has_structured = bool(
		re.search(r"<[a-zA-Z_][a-zA-Z0-9_]*>", all_text)
		or re.search(r"^#{1,3}\s+\S", all_text, re.MULTILINE)
	)

	# Category 2: Constraint language
	has_constraints = bool(re.search(r"\b(must|never|always|do not)\b", all_text, re.IGNORECASE))

	# Category 3: Output format specification
	has_output_spec = bool(
		re.search(
			r"(respond in json|format as|return a (list|dict|array)|output as)",
			all_text,
			re.IGNORECASE,
		)
	)

	# Category 4: Role specification
	has_role_spec = bool(re.search(r"\b(you are|act as|your role)\b", all_text, re.IGNORECASE))

	# Category 5: Few-shot / example patterns
	has_examples = bool(
		re.search(r"\b(example|sample|for instance|e\.g\.|such as)\b", all_text, re.IGNORECASE)
	)

	found = sum([has_structured, has_constraints, has_output_spec, has_role_spec, has_examples])

	# Frequency bonus: multiple constraint or role mentions
	constraint_count = len(re.findall(r"\b(must|never|always|do not)\b", all_text, re.IGNORECASE))
	bonus = FREQUENCY_BONUS if constraint_count >= 3 else 0.0

	return _score_from_hits(found, _PROMPT_ENG_TOTAL, bonus)


# ---------------------------------------------------------------------------
# 4. Tool Ecosystem (15%)
# ---------------------------------------------------------------------------

_TOOL_ECOSYSTEM_TOTAL = 5  # five tool categories


def score_tool_ecosystem(messages: list["NormalizedMessage"]) -> float:
	"""Score tool ecosystem diversity beyond standard Claude Code tools."""
	if not messages:
		return 0.0

	tool_uses = _iter_tool_uses(messages)
	if not tool_uses:
		return 0.0

	tool_names = [t.get("name", "") for t in tool_uses]
	# Also check bash command contents for gh patterns
	bash_commands = [
		t.get("input", {}).get("command", "") for t in tool_uses if t.get("name") == "Bash"
	]

	# Category 1: MCP server tools (name contains "mcp__")
	has_mcp = any("mcp__" in n for n in tool_names)

	# Category 2: Browser automation
	has_browser = any("playwright" in n.lower() or "browser" in n.lower() for n in tool_names)

	# Category 3: GitHub API (gh CLI in bash commands or gh-related tool names)
	has_github = any(re.search(r"\bgh\b", cmd) for cmd in bash_commands) or any(
		"github" in n.lower() for n in tool_names
	)

	# Category 4: Web research tools
	has_web_research = any(n in {"WebSearch", "WebFetch"} for n in tool_names)

	# Category 5: Custom / specialized tools (not in standard set, not mcp__, not browser)
	custom_tools = [
		n
		for n in set(tool_names)
		if n not in STANDARD_TOOLS
		and "mcp__" not in n
		and "playwright" not in n.lower()
		and "browser" not in n.lower()
		and n not in {"WebSearch", "WebFetch"}
	]
	has_custom = bool(custom_tools)

	found = sum([has_mcp, has_browser, has_github, has_web_research, has_custom])

	# Frequency bonus: many distinct non-standard tool names
	distinct_non_standard = len({n for n in tool_names if n not in STANDARD_TOOLS})
	bonus = FREQUENCY_BONUS if distinct_non_standard >= 3 else 0.0

	return _score_from_hits(found, _TOOL_ECOSYSTEM_TOTAL, bonus)


# ---------------------------------------------------------------------------
# 5. Error Recovery (15%)
# ---------------------------------------------------------------------------

_ERROR_RECOVERY_TOTAL = 4  # four recovery pattern categories


def score_error_recovery(messages: list["NormalizedMessage"]) -> float:
	"""Score error recovery patterns: test-fix cycles, diagnostics, refinement."""
	if not messages:
		return 0.0

	tool_uses = _iter_tool_uses(messages)
	all_text = " ".join(_iter_text_content(messages))

	# Build a sequence of (tool_name, is_error_result) for pattern detection
	event_seq: list[tuple[str, bool]] = []
	for msg in messages:
		for block in msg["content"]:
			btype = block.get("type", "")
			if btype == "tool_use":
				event_seq.append((block.get("name", ""), False))
			elif btype == "tool_result":
				result_text = str(block.get("content", "")).lower()
				is_error = block.get("is_error", False) or any(
					kw in result_text
					for kw in ("failed", "error", "traceback", "exception", "assert")
				)
				event_seq.append(("__result__", is_error))

	# Category 1: Test-fix cycle — error result followed by Edit/Write (fix attempt)
	has_test_fix = False
	for i, (name, is_err) in enumerate(event_seq):
		if is_err:
			rest = [e[0] for e in event_seq[i + 1 : i + 6]]
			if any(n in {"Edit", "Write"} for n in rest):
				has_test_fix = True
				break

	# Category 2: Diagnostic before fix — Read/Grep before Edit
	has_diagnostic = False
	for i, (name, _) in enumerate(event_seq):
		if name in {"Read", "Grep"}:
			for j in range(i + 1, min(i + 5, len(event_seq))):
				if event_seq[j][0] in {"Edit", "Write"}:
					has_diagnostic = True
					break
		if has_diagnostic:
			break

	# Category 3: Iterative refinement — same file edited 2+ times
	edit_targets: list[str] = []
	for msg in messages:
		for block in msg["content"]:
			if block.get("type") == "tool_use":
				if block.get("name") in {"Edit", "Write"}:
					fp = block.get("input", {}).get("file_path", "")
					if fp:
						edit_targets.append(fp)
	has_refinement = len(edit_targets) != len(set(edit_targets))

	# Category 4: Error acknowledgment in assistant text
	has_acknowledgment = bool(
		re.search(
			r"\b(error|failed|fail|fix|retry|incorrect|wrong|broken)\b", all_text, re.IGNORECASE
		)
	)

	found = sum([has_test_fix, has_diagnostic, has_refinement, has_acknowledgment])

	# Frequency bonus: multiple distinct error-fix cycles
	error_results = sum(1 for _, is_err in event_seq if is_err)
	bonus = FREQUENCY_BONUS if error_results >= 2 else 0.0

	return _score_from_hits(found, _ERROR_RECOVERY_TOTAL, bonus)


# ---------------------------------------------------------------------------
# Composite scorer
# ---------------------------------------------------------------------------


def compute_ai_engineering_score(messages: list["NormalizedMessage"]) -> dict[str, float | str]:
	"""Compute composite AI engineering score from session messages.

	Returns a dict with keys: orchestration, ai_domain, prompt_engineering,
	tool_ecosystem, error_recovery, composite, level.
	"""
	orchestration = score_orchestration(messages)
	ai_domain = score_ai_domain(messages)
	prompt_engineering = score_prompt_engineering(messages)
	tool_ecosystem = score_tool_ecosystem(messages)
	error_recovery = score_error_recovery(messages)

	composite = (
		orchestration * WEIGHT_ORCHESTRATION
		+ ai_domain * WEIGHT_AI_DOMAIN
		+ prompt_engineering * WEIGHT_PROMPT_ENGINEERING
		+ tool_ecosystem * WEIGHT_TOOL_ECOSYSTEM
		+ error_recovery * WEIGHT_ERROR_RECOVERY
	)
	composite = _clamp(composite)

	if composite >= LEVEL_EXPERT:
		level = "expert"
	elif composite >= LEVEL_ADVANCED:
		level = "advanced"
	elif composite >= LEVEL_INTERMEDIATE:
		level = "intermediate"
	else:
		level = "beginner"

	return {
		"orchestration": orchestration,
		"ai_domain": ai_domain,
		"prompt_engineering": prompt_engineering,
		"tool_ecosystem": tool_ecosystem,
		"error_recovery": error_recovery,
		"composite": composite,
		"level": level,
	}
