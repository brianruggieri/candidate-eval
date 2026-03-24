"""Tests for the AI engineering scoring module."""

from __future__ import annotations

import pytest

from claude_candidate.ai_scoring import (
	compute_ai_engineering_score,
	score_ai_domain,
	score_error_recovery,
	score_orchestration,
	score_prompt_engineering,
	score_tool_ecosystem,
)


# ---------------------------------------------------------------------------
# Helpers: message factories
# ---------------------------------------------------------------------------


def tool_use_block(name: str, input_: dict | None = None) -> dict:
	return {"type": "tool_use", "id": "tu_001", "name": name, "input": input_ or {}}


def text_block(text: str) -> dict:
	return {"type": "text", "text": text}


def tool_result_block(content: str, is_error: bool = False) -> dict:
	return {"type": "tool_result", "content": content, "is_error": is_error}


def assistant_msg(*blocks: dict) -> dict:
	return {"role": "assistant", "content": list(blocks), "raw": {}}


def user_msg(text: str) -> dict:
	return {"role": "user", "content": [text_block(text)], "raw": {}}


def user_msg_with_result(content: str, is_error: bool = False) -> dict:
	return {"role": "user", "content": [tool_result_block(content, is_error)], "raw": {}}


# ---------------------------------------------------------------------------
# score_orchestration
# ---------------------------------------------------------------------------


class TestScoreOrchestration:
	def test_empty_messages_returns_zero(self) -> None:
		assert score_orchestration([]) == 0.0

	def test_no_orchestration_signals(self) -> None:
		messages = [
			assistant_msg(text_block("Hello"), tool_use_block("Bash", {"command": "ls"})),
			user_msg_with_result("file1.py"),
		]
		score = score_orchestration(messages)
		assert 0.0 <= score <= 1.0
		assert score < 0.3

	def test_agent_usage_raises_score(self) -> None:
		messages = [
			assistant_msg(
				tool_use_block("Agent", {"prompt": "do something", "subagent_type": "general"})
			),
			user_msg_with_result("done"),
		]
		score = score_orchestration(messages)
		assert score > 0.0

	def test_task_lifecycle_raises_score(self) -> None:
		messages = [
			assistant_msg(tool_use_block("TaskCreate", {"title": "Fix bug"})),
			user_msg_with_result("task created"),
			assistant_msg(tool_use_block("TaskUpdate", {"id": "1", "status": "in_progress"})),
			user_msg_with_result("updated"),
			assistant_msg(tool_use_block("TaskList", {})),
			user_msg_with_result("[]"),
		]
		score = score_orchestration(messages)
		assert score > 0.1

	def test_parallel_tool_invocations_raises_score(self) -> None:
		messages = [
			assistant_msg(
				tool_use_block("Bash", {"command": "ls"}),
				tool_use_block("Read", {"file_path": "/foo.py"}),
				tool_use_block("Glob", {"pattern": "**/*.py"}),
			),
			user_msg_with_result("results"),
		]
		score = score_orchestration(messages)
		assert score > 0.0

	def test_team_creation_raises_score(self) -> None:
		messages = [
			assistant_msg(tool_use_block("TeamCreate", {"name": "my-team"})),
			user_msg_with_result("team created"),
			assistant_msg(tool_use_block("SendMessage", {"content": "hello"})),
			user_msg_with_result("sent"),
		]
		score = score_orchestration(messages)
		assert score > 0.2

	def test_subagent_diversity_raises_score(self) -> None:
		messages = [
			assistant_msg(
				tool_use_block("Agent", {"subagent_type": "code_review", "prompt": "review"})
			),
			user_msg_with_result("reviewed"),
			assistant_msg(
				tool_use_block("Agent", {"subagent_type": "research", "prompt": "find info"})
			),
			user_msg_with_result("found"),
		]
		score = score_orchestration(messages)
		assert score > 0.2

	def test_full_orchestration_session_scores_high(self) -> None:
		messages = [
			assistant_msg(tool_use_block("TeamCreate", {"name": "my-team"})),
			user_msg_with_result("team created"),
			assistant_msg(tool_use_block("TaskCreate", {"title": "Task A"})),
			user_msg_with_result("created"),
			assistant_msg(
				tool_use_block("Agent", {"subagent_type": "code_review", "prompt": "review"}),
				tool_use_block("Agent", {"subagent_type": "research", "prompt": "research"}),
			),
			user_msg_with_result("done"),
			assistant_msg(tool_use_block("SendMessage", {"content": "results"})),
			user_msg_with_result("sent"),
			assistant_msg(tool_use_block("TaskUpdate", {"id": "1", "status": "completed"})),
			user_msg_with_result("updated"),
		]
		score = score_orchestration(messages)
		assert score >= 0.7

	def test_returns_float_in_range(self) -> None:
		messages = [assistant_msg(tool_use_block("Bash", {"command": "echo hi"}))]
		score = score_orchestration(messages)
		assert isinstance(score, float)
		assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# score_ai_domain
# ---------------------------------------------------------------------------


class TestScoreAiDomain:
	def test_empty_messages_returns_zero(self) -> None:
		assert score_ai_domain([]) == 0.0

	def test_no_ai_patterns(self) -> None:
		messages = [
			assistant_msg(text_block("Here is the code to list files.")),
			user_msg("ok"),
		]
		score = score_ai_domain(messages)
		assert score < 0.2

	def test_import_patterns_raise_score(self) -> None:
		messages = [
			assistant_msg(text_block("import anthropic\nclient = anthropic.Anthropic()")),
		]
		score = score_ai_domain(messages)
		assert score > 0.0

	def test_api_call_patterns_raise_score(self) -> None:
		messages = [
			assistant_msg(
				text_block("response = client.messages.create(model='claude-3-5-sonnet')")
			),
		]
		score = score_ai_domain(messages)
		assert score > 0.0

	def test_rag_patterns_raise_score(self) -> None:
		messages = [
			assistant_msg(
				text_block("Use embedding vectors for retrieval. Chunk the documents first.")
			),
		]
		score = score_ai_domain(messages)
		assert score > 0.0

	def test_eval_patterns_raise_score(self) -> None:
		messages = [
			assistant_msg(
				text_block(
					"We need to evaluate the model output using benchmark metrics and score it."
				)
			),
		]
		score = score_ai_domain(messages)
		assert score > 0.0

	def test_structured_output_patterns_raise_score(self) -> None:
		messages = [
			assistant_msg(
				text_block("Use response_model=MySchema and tool_use with json_schema validation.")
			),
		]
		score = score_ai_domain(messages)
		assert score > 0.0

	def test_guardrail_patterns_raise_score(self) -> None:
		messages = [
			assistant_msg(text_block("Apply content_filter and moderation to ensure safety.")),
		]
		score = score_ai_domain(messages)
		assert score > 0.0

	def test_full_ai_session_scores_high(self) -> None:
		messages = [
			assistant_msg(
				text_block(
					"import anthropic\nimport openai\n"
					"client = anthropic.Anthropic()\n"
					"response = client.messages.create(model='claude-3-5-sonnet')\n"
					"Use response_model=OutputSchema for structured output.\n"
					"Apply embedding and vector search for RAG retrieval.\n"
					"Run evaluate() to benchmark the model metric score.\n"
					"Add content_filter and moderation safety layer."
				)
			),
		]
		score = score_ai_domain(messages)
		assert score >= 0.7

	def test_returns_float_in_range(self) -> None:
		messages = [assistant_msg(text_block("some code here"))]
		score = score_ai_domain(messages)
		assert isinstance(score, float)
		assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# score_prompt_engineering
# ---------------------------------------------------------------------------


class TestScorePromptEngineering:
	def test_empty_messages_returns_zero(self) -> None:
		assert score_prompt_engineering([]) == 0.0

	def test_no_prompt_engineering_signals(self) -> None:
		messages = [
			user_msg("fix the bug"),
			assistant_msg(text_block("Sure, let me fix it.")),
		]
		score = score_prompt_engineering(messages)
		assert score < 0.3

	def test_xml_tags_raise_score(self) -> None:
		messages = [
			user_msg("<task>Fix the login bug</task><context>The auth module</context>"),
		]
		score = score_prompt_engineering(messages)
		assert score > 0.0

	def test_markdown_headers_raise_score(self) -> None:
		messages = [
			user_msg("# Task\nFix the bug.\n## Context\nThe auth module."),
		]
		score = score_prompt_engineering(messages)
		assert score > 0.0

	def test_constraint_language_raises_score(self) -> None:
		messages = [
			user_msg(
				"You must never modify tests. Always run the linter first. Do not edit config files."
			),
		]
		score = score_prompt_engineering(messages)
		assert score > 0.0

	def test_output_format_spec_raises_score(self) -> None:
		messages = [
			user_msg(
				"Respond in JSON. Format as a list. Return a dict with keys 'name' and 'score'."
			),
		]
		score = score_prompt_engineering(messages)
		assert score > 0.0

	def test_role_specification_raises_score(self) -> None:
		messages = [
			user_msg(
				"You are an expert Python developer. Act as a senior engineer. Your role is to review code."
			),
		]
		score = score_prompt_engineering(messages)
		assert score > 0.0

	def test_full_prompt_engineering_scores_high(self) -> None:
		messages = [
			user_msg(
				"You are an expert code reviewer. Your role is to find bugs.\n"
				"# Task\nReview the authentication module.\n"
				"<constraints>You must never skip tests. Always check edge cases.</constraints>\n"
				'Respond in JSON with format: {"issues": [...]}.\n'
				'Example: {"issues": [{"file": "auth.py", "line": 42}]}'
			),
		]
		score = score_prompt_engineering(messages)
		assert score >= 0.6

	def test_returns_float_in_range(self) -> None:
		messages = [user_msg("do something")]
		score = score_prompt_engineering(messages)
		assert isinstance(score, float)
		assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# score_tool_ecosystem
# ---------------------------------------------------------------------------


class TestScoreToolEcosystem:
	def test_empty_messages_returns_zero(self) -> None:
		assert score_tool_ecosystem([]) == 0.0

	def test_only_standard_tools_scores_low(self) -> None:
		messages = [
			assistant_msg(tool_use_block("Bash", {"command": "ls"})),
			assistant_msg(tool_use_block("Read", {"file_path": "/foo.py"})),
			assistant_msg(
				tool_use_block(
					"Edit", {"file_path": "/foo.py", "old_string": "x", "new_string": "y"}
				)
			),
			assistant_msg(tool_use_block("Write", {"file_path": "/bar.py", "content": ""})),
			assistant_msg(tool_use_block("Glob", {"pattern": "*.py"})),
			assistant_msg(tool_use_block("Grep", {"pattern": "foo"})),
		]
		score = score_tool_ecosystem(messages)
		assert score < 0.3

	def test_mcp_tools_raise_score(self) -> None:
		messages = [
			assistant_msg(
				tool_use_block("mcp__playwright__browser_navigate", {"url": "http://example.com"})
			),
		]
		score = score_tool_ecosystem(messages)
		assert score > 0.0

	def test_browser_automation_raises_score(self) -> None:
		messages = [
			assistant_msg(
				tool_use_block("mcp__plugin_playwright_playwright__browser_snapshot", {})
			),
			assistant_msg(tool_use_block("mcp__plugin_playwright_playwright__browser_click", {})),
		]
		score = score_tool_ecosystem(messages)
		assert score > 0.1

	def test_github_api_raises_score(self) -> None:
		messages = [
			assistant_msg(
				tool_use_block("Bash", {"command": "gh pr create --title 'fix' --body 'desc'"})
			),
		]
		score = score_tool_ecosystem(messages)
		assert score > 0.0

	def test_web_research_tools_raise_score(self) -> None:
		messages = [
			assistant_msg(tool_use_block("WebSearch", {"query": "python async patterns"})),
			assistant_msg(tool_use_block("WebFetch", {"url": "https://docs.python.org"})),
		]
		score = score_tool_ecosystem(messages)
		assert score > 0.1

	def test_diverse_tool_ecosystem_scores_high(self) -> None:
		messages = [
			assistant_msg(
				tool_use_block("mcp__context7__resolve_library_id", {"library": "fastapi"})
			),
			assistant_msg(
				tool_use_block(
					"mcp__plugin_playwright_playwright__browser_navigate",
					{"url": "http://localhost"},
				)
			),
			assistant_msg(tool_use_block("WebSearch", {"query": "fastapi docs"})),
			assistant_msg(tool_use_block("Bash", {"command": "gh api repos/foo/bar"})),
			assistant_msg(tool_use_block("MyCustomTool", {"input": "data"})),
		]
		score = score_tool_ecosystem(messages)
		assert score >= 0.5

	def test_returns_float_in_range(self) -> None:
		messages = [assistant_msg(tool_use_block("Bash", {"command": "ls"}))]
		score = score_tool_ecosystem(messages)
		assert isinstance(score, float)
		assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# score_error_recovery
# ---------------------------------------------------------------------------


class TestScoreErrorRecovery:
	def test_empty_messages_returns_zero(self) -> None:
		assert score_error_recovery([]) == 0.0

	def test_no_recovery_patterns_scores_low(self) -> None:
		messages = [
			assistant_msg(
				text_block("Let me implement this."),
				tool_use_block("Write", {"file_path": "/foo.py", "content": "code"}),
			),
			user_msg_with_result("ok"),
		]
		score = score_error_recovery(messages)
		assert score < 0.3

	def test_test_fix_cycle_raises_score(self) -> None:
		messages = [
			assistant_msg(tool_use_block("Bash", {"command": "pytest tests/"})),
			user_msg_with_result("FAILED tests/test_foo.py::test_bar", is_error=False),
			assistant_msg(
				tool_use_block(
					"Edit", {"file_path": "/foo.py", "old_string": "x", "new_string": "y"}
				)
			),
			assistant_msg(tool_use_block("Bash", {"command": "pytest tests/"})),
			user_msg_with_result("passed"),
		]
		score = score_error_recovery(messages)
		assert score > 0.0

	def test_diagnostic_before_fix_raises_score(self) -> None:
		messages = [
			assistant_msg(tool_use_block("Read", {"file_path": "/foo.py"})),
			user_msg_with_result("file contents"),
			assistant_msg(tool_use_block("Grep", {"pattern": "def broken"})),
			user_msg_with_result("foo.py:10: def broken():"),
			assistant_msg(
				tool_use_block(
					"Edit", {"file_path": "/foo.py", "old_string": "broken", "new_string": "fixed"}
				)
			),
			user_msg_with_result("ok"),
		]
		score = score_error_recovery(messages)
		assert score > 0.0

	def test_error_acknowledgment_raises_score(self) -> None:
		messages = [
			assistant_msg(
				text_block("I see an error here. The test failed. Let me fix the retry logic.")
			),
		]
		score = score_error_recovery(messages)
		assert score > 0.0

	def test_iterative_refinement_raises_score(self) -> None:
		messages = [
			assistant_msg(
				tool_use_block(
					"Edit", {"file_path": "/foo.py", "old_string": "a", "new_string": "b"}
				)
			),
			user_msg_with_result("ok"),
			assistant_msg(
				tool_use_block(
					"Edit", {"file_path": "/foo.py", "old_string": "b", "new_string": "c"}
				)
			),
			user_msg_with_result("ok"),
			assistant_msg(
				tool_use_block(
					"Edit", {"file_path": "/foo.py", "old_string": "c", "new_string": "d"}
				)
			),
			user_msg_with_result("ok"),
		]
		score = score_error_recovery(messages)
		assert score > 0.0

	def test_full_recovery_session_scores_high(self) -> None:
		messages = [
			# Investigate first
			assistant_msg(tool_use_block("Read", {"file_path": "/foo.py"})),
			user_msg_with_result("bad code"),
			assistant_msg(tool_use_block("Grep", {"pattern": "error"})),
			user_msg_with_result("found error"),
			# Acknowledge and fix
			assistant_msg(
				text_block("I see the error. The test failed. Let me fix and retry."),
				tool_use_block(
					"Edit", {"file_path": "/foo.py", "old_string": "bad", "new_string": "good"}
				),
			),
			user_msg_with_result("ok"),
			# Test-fix cycle
			assistant_msg(tool_use_block("Bash", {"command": "pytest tests/"})),
			user_msg_with_result("FAILED"),
			assistant_msg(
				tool_use_block(
					"Edit", {"file_path": "/foo.py", "old_string": "good", "new_string": "better"}
				)
			),
			user_msg_with_result("ok"),
			assistant_msg(tool_use_block("Bash", {"command": "pytest tests/"})),
			user_msg_with_result("passed"),
		]
		score = score_error_recovery(messages)
		assert score >= 0.6

	def test_returns_float_in_range(self) -> None:
		messages = [assistant_msg(text_block("some text"))]
		score = score_error_recovery(messages)
		assert isinstance(score, float)
		assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# compute_ai_engineering_score
# ---------------------------------------------------------------------------


class TestComputeAiEngineeringScore:
	def test_empty_messages(self) -> None:
		result = compute_ai_engineering_score([])
		assert result["composite"] == 0.0
		assert result["level"] == "beginner"

	def test_returns_all_dimension_keys(self) -> None:
		messages = [assistant_msg(text_block("hello"))]
		result = compute_ai_engineering_score(messages)
		assert "composite" in result
		assert "level" in result
		assert "orchestration" in result
		assert "ai_domain" in result
		assert "prompt_engineering" in result
		assert "tool_ecosystem" in result
		assert "error_recovery" in result

	def test_composite_is_weighted_average(self) -> None:
		# With all scores at 1.0, composite must be 1.0
		messages_all_high = [
			assistant_msg(
				tool_use_block("Agent", {"subagent_type": "code_review", "prompt": "review"}),
				tool_use_block("Agent", {"subagent_type": "research", "prompt": "research"}),
			),
			user_msg_with_result("done"),
			assistant_msg(tool_use_block("TeamCreate", {"name": "team"})),
			user_msg_with_result("created"),
			assistant_msg(tool_use_block("TaskCreate", {"title": "task"})),
			user_msg_with_result("created"),
			assistant_msg(tool_use_block("SendMessage", {"content": "msg"})),
			user_msg_with_result("sent"),
		]
		result = compute_ai_engineering_score(messages_all_high)
		# Composite must be a weighted combination of the five dimensions
		expected = (
			result["orchestration"] * 0.25
			+ result["ai_domain"] * 0.25
			+ result["prompt_engineering"] * 0.20
			+ result["tool_ecosystem"] * 0.15
			+ result["error_recovery"] * 0.15
		)
		assert abs(result["composite"] - expected) < 1e-9

	def test_level_beginner(self) -> None:
		result = compute_ai_engineering_score([])
		assert result["level"] == "beginner"

	def test_level_intermediate(self) -> None:
		# Force a composite of ~0.4 via known messages
		messages = [
			user_msg("You are a Python expert. Always use type hints."),
			assistant_msg(text_block("import openai\nclient = openai.OpenAI()")),
		]
		result = compute_ai_engineering_score(messages)
		# Just check level classification logic is applied
		composite = result["composite"]
		if composite >= 0.75:
			assert result["level"] == "expert"
		elif composite >= 0.55:
			assert result["level"] == "advanced"
		elif composite >= 0.35:
			assert result["level"] == "intermediate"
		else:
			assert result["level"] == "beginner"

	def test_level_expert_threshold(self) -> None:
		# Build a session that hits many signals across all dimensions
		messages = [
			# Orchestration
			assistant_msg(tool_use_block("TeamCreate", {"name": "team"})),
			user_msg_with_result("created"),
			assistant_msg(tool_use_block("TaskCreate", {"title": "task"})),
			user_msg_with_result("created"),
			assistant_msg(
				tool_use_block("Agent", {"subagent_type": "code_review", "prompt": "review"}),
				tool_use_block("Agent", {"subagent_type": "research", "prompt": "research"}),
			),
			user_msg_with_result("done"),
			assistant_msg(tool_use_block("SendMessage", {"content": "msg"})),
			user_msg_with_result("sent"),
			assistant_msg(tool_use_block("TaskUpdate", {"id": "1", "status": "completed"})),
			user_msg_with_result("updated"),
			# AI domain
			assistant_msg(
				text_block(
					"import anthropic\nimport openai\n"
					"client = anthropic.Anthropic()\n"
					"response = client.messages.create(model='claude-3-5-sonnet')\n"
					"Use response_model=Schema for structured output.\n"
					"Embed with vector store for retrieval.\n"
					"Run evaluate() to benchmark metric score.\n"
					"Add content_filter moderation safety."
				)
			),
			# Prompt engineering
			user_msg(
				"You are an expert AI engineer. Your role is to build pipelines.\n"
				"<task>Build a RAG system</task>\n"
				"# Requirements\n1. Must use embeddings\n2. Never skip validation\n"
				'Respond in JSON. Format as: {"pipeline": {...}}'
			),
			# Tool ecosystem
			assistant_msg(tool_use_block("WebSearch", {"query": "RAG patterns"})),
			user_msg_with_result("results"),
			assistant_msg(tool_use_block("mcp__context7__resolve", {"library": "langchain"})),
			user_msg_with_result("docs"),
			# Error recovery
			assistant_msg(tool_use_block("Bash", {"command": "pytest tests/"})),
			user_msg_with_result("FAILED"),
			assistant_msg(text_block("The test failed. Let me fix this error.")),
			assistant_msg(tool_use_block("Read", {"file_path": "/rag.py"})),
			user_msg_with_result("contents"),
			assistant_msg(
				tool_use_block(
					"Edit", {"file_path": "/rag.py", "old_string": "bad", "new_string": "good"}
				)
			),
			user_msg_with_result("ok"),
			assistant_msg(tool_use_block("Bash", {"command": "pytest tests/"})),
			user_msg_with_result("passed"),
		]
		result = compute_ai_engineering_score(messages)
		assert result["composite"] >= 0.55  # at least advanced
		assert result["level"] in {"advanced", "expert"}

	def test_all_scores_in_range(self) -> None:
		messages = [assistant_msg(text_block("import anthropic"))]
		result = compute_ai_engineering_score(messages)
		for key in (
			"orchestration",
			"ai_domain",
			"prompt_engineering",
			"tool_ecosystem",
			"error_recovery",
			"composite",
		):
			assert 0.0 <= result[key] <= 1.0, f"{key} out of range: {result[key]}"
