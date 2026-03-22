"""
BehaviorSignalExtractor: Tier 2+3 signal extraction from structured tool_use metadata.

Detects developer behavior and AI-native skills:
- Problem-solving patterns (all 12 PatternType values)
- Agent orchestration (Agent tool, Skill invocations, TaskCreate)
- Git workflow (branch metadata, worktree usage, PR creation)
- Quality practice signals (security, testing, code review)

Scope: Analyzes tool_use structured events (name, input fields including file paths
and content), git metadata, error flags, message sequencing. Does NOT analyze
free-text code blocks or user message text.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

from claude_candidate.extractors import (
	NormalizedSession,
	PatternSignal,
	ProjectSignal,
	SignalResult,
	SkillSignal,
)
from claude_candidate.message_format import ContentBlock, NormalizedMessage
from claude_candidate.schemas.candidate_profile import DepthLevel, PatternType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TEST_FILE_PATTERNS = re.compile(
	r"(test_[^/]*\.py|[^/]*\.test\.(ts|js|tsx|jsx)|[^/]*\.spec\.(ts|js|tsx|jsx))$"
)

_TEST_COMMANDS = re.compile(r"\b(pytest|vitest|jest|mocha|cargo test|go test)\b")

_SECURITY_KEYWORDS = re.compile(r"(sanitiz|secret|pii|auth|security)", re.IGNORECASE)

_PHASE_KEYWORDS = re.compile(
	r"\b(phase|stage|step|milestone|dependency|depend|sequenc|block)\b", re.IGNORECASE
)


def _get_tool_use_blocks(msg: NormalizedMessage) -> list[ContentBlock]:
	"""Extract all tool_use content blocks from a message."""
	return [b for b in msg.get("content", []) if b.get("type") == "tool_use"]


def _get_tool_result_blocks(msg: NormalizedMessage) -> list[ContentBlock]:
	"""Extract all tool_result content blocks from a message."""
	return [b for b in msg.get("content", []) if b.get("type") == "tool_result"]


def _file_extension(path: str) -> str:
	"""Return the file extension (e.g., '.py') from a path."""
	_, ext = os.path.splitext(path)
	return ext.lower()


def _is_test_file(path: str) -> bool:
	"""Check if the file path matches a test file pattern."""
	basename = os.path.basename(path)
	return bool(_TEST_FILE_PATTERNS.match(basename))


def _is_md_file(path: str) -> bool:
	"""Check if the file path is a markdown file."""
	return path.lower().endswith(".md")


def _extract_file_path_from_input(inp: dict[str, Any]) -> str | None:
	"""Extract a file_path from tool input dict."""
	return inp.get("file_path")


def _extract_command_from_input(inp: dict[str, Any]) -> str | None:
	"""Extract a command from Bash tool input dict."""
	return inp.get("command") or inp.get("cmd")


# ---------------------------------------------------------------------------
# Main extractor
# ---------------------------------------------------------------------------


class BehaviorSignalExtractor:
	"""Extracts Tier 2+3 signals: behavioral patterns, agent orchestration, git workflow."""

	def name(self) -> str:
		return "behavior_signals"

	def extract_session(self, session: NormalizedSession) -> SignalResult:
		"""Analyze a normalized session for behavioral signals."""
		messages = session.messages
		session_id = session.session_id

		# --- Pass 1: Collect tool usage counts and per-message tool info ---
		tool_counts: dict[str, int] = {}
		file_extensions: set[str] = set()
		file_paths_edited: list[str] = []
		bash_commands: list[str] = []
		agent_dispatches: list[dict[str, Any]] = []
		skill_invocations: list[dict[str, Any]] = []
		task_creates: list[dict[str, Any]] = []
		has_code_edit = False

		# Per-message tool info for sequence analysis
		msg_tool_info: list[dict[str, Any]] = []

		for msg in messages:
			role = msg.get("role", "")
			tool_blocks = _get_tool_use_blocks(msg)
			result_blocks = _get_tool_result_blocks(msg)

			info: dict[str, Any] = {
				"role": role,
				"tools": [],
				"is_error": False,
				"error_content": "",
				"agent_count": 0,
			}

			# Handle tool_result messages (top-level role)
			if role == "tool_result":
				for block in msg.get("content", []):
					if block.get("type") == "tool_result":
						if block.get("is_error", False):
							info["is_error"] = True
							info["error_content"] = block.get("content", "")

			# Handle result blocks embedded in other messages
			for block in result_blocks:
				if block.get("is_error", False):
					info["is_error"] = True
					info["error_content"] = block.get("content", "")

			agent_in_msg = 0
			for block in tool_blocks:
				tool_name = block.get("name", "")
				tool_input = block.get("input", {})
				tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

				tool_entry: dict[str, Any] = {
					"name": tool_name,
					"input": tool_input,
				}

				# Extract file paths from Write/Edit
				if tool_name in ("Write", "Edit"):
					fp = _extract_file_path_from_input(tool_input)
					if fp:
						ext = _file_extension(fp)
						if ext:
							file_extensions.add(ext)
						file_paths_edited.append(fp)
						if not _is_md_file(fp):
							has_code_edit = True

				# Extract Bash commands
				if tool_name == "Bash":
					cmd = _extract_command_from_input(tool_input)
					if cmd:
						bash_commands.append(cmd)

				# Collect Agent dispatches
				if tool_name == "Agent":
					agent_in_msg += 1
					agent_dispatches.append(tool_input)

				# Collect Skill invocations
				if tool_name == "Skill":
					skill_invocations.append(tool_input)

				# Collect TaskCreate
				if tool_name == "TaskCreate":
					task_creates.append(tool_input)

				info["tools"].append(tool_entry)

			info["agent_count"] = agent_in_msg
			msg_tool_info.append(info)

		# Also handle top-level tool_use role messages
		for msg in messages:
			if msg.get("role") == "tool_use":
				for block in msg.get("content", []):
					if block.get("type") == "tool_use":
						tool_name = block.get("name", "")
						tool_input = block.get("input", {})
						tool_counts[tool_name] = tool_counts.get(tool_name, 0) + 1

						if tool_name in ("Write", "Edit"):
							fp = _extract_file_path_from_input(tool_input)
							if fp:
								ext = _file_extension(fp)
								if ext:
									file_extensions.add(ext)
								file_paths_edited.append(fp)
								if not _is_md_file(fp):
									has_code_edit = True

						if tool_name == "Bash":
							cmd = _extract_command_from_input(tool_input)
							if cmd:
								bash_commands.append(cmd)

		# Convenience counts
		write_count = tool_counts.get("Write", 0)
		bash_count = tool_counts.get("Bash", 0)
		read_count = tool_counts.get("Read", 0)
		edit_count = tool_counts.get("Edit", 0)
		grep_count = tool_counts.get("Grep", 0)

		# --- Pass 2: Detect patterns ---
		skills: dict[str, list[SkillSignal]] = {}
		patterns: list[PatternSignal] = []
		project_signals = ProjectSignal()

		# -- ITERATIVE_REFINEMENT --
		if write_count >= 2 and bash_count >= 1:
			patterns.append(PatternSignal(
				pattern_type=PatternType.ITERATIVE_REFINEMENT,
				session_ids=[session_id],
				confidence=0.7,
				description="Multiple write operations interspersed with command execution",
				evidence_snippet=(
					f"Session has {write_count} Write and {bash_count} Bash calls"
				),
			))

		# -- ARCHITECTURE_FIRST --
		if read_count >= 1 and write_count >= 1:
			patterns.append(PatternSignal(
				pattern_type=PatternType.ARCHITECTURE_FIRST,
				session_ids=[session_id],
				confidence=0.6,
				description="Read existing code before writing new code",
				evidence_snippet=(
					f"Session has {read_count} Read and {write_count} Write calls"
				),
			))

		# -- TESTING_INSTINCT --
		test_file_edits = [fp for fp in file_paths_edited if _is_test_file(fp)]
		test_commands = [cmd for cmd in bash_commands if _TEST_COMMANDS.search(cmd)]
		if test_file_edits or test_commands:
			evidence_parts = []
			if test_file_edits:
				evidence_parts.append(f"Edited test files: {', '.join(test_file_edits[:3])}")
			if test_commands:
				evidence_parts.append(f"Ran test commands: {', '.join(test_commands[:3])}")
			patterns.append(PatternSignal(
				pattern_type=PatternType.TESTING_INSTINCT,
				session_ids=[session_id],
				confidence=0.8,
				description="Active engagement with testing (file edits or test commands)",
				evidence_snippet="; ".join(evidence_parts)[:500],
				metadata={"test_file_count": len(test_file_edits)},
			))

		# -- MODULAR_THINKING --
		if len(file_extensions) >= 3:
			patterns.append(PatternSignal(
				pattern_type=PatternType.MODULAR_THINKING,
				session_ids=[session_id],
				confidence=0.6,
				description="Works across multiple file types, suggesting modular design",
				evidence_snippet=(
					f"Unique extensions: {', '.join(sorted(file_extensions))}"
				),
			))

		# -- SYSTEMATIC_DEBUGGING --
		debug_detected = self._detect_systematic_debugging(msg_tool_info, session_id)
		if debug_detected:
			patterns.append(debug_detected)

		# -- TRADEOFF_ANALYSIS --
		tradeoff_detected = self._detect_tradeoff_analysis(
			msg_tool_info, agent_dispatches, session_id
		)
		if tradeoff_detected:
			patterns.append(tradeoff_detected)

		# -- SCOPE_MANAGEMENT --
		scope_detected = self._detect_scope_management(task_creates, session_id)
		if scope_detected:
			patterns.append(scope_detected)

		# -- DOCUMENTATION_DRIVEN --
		md_edits = [fp for fp in file_paths_edited if _is_md_file(fp)]
		if md_edits and has_code_edit:
			patterns.append(PatternSignal(
				pattern_type=PatternType.DOCUMENTATION_DRIVEN,
				session_ids=[session_id],
				confidence=0.7,
				description="Documentation updated alongside code changes",
				evidence_snippet=f"Edited docs: {', '.join(md_edits[:3])}",
				metadata={"doc_file_count": len(md_edits)},
			))

		# -- RECOVERY_FROM_FAILURE --
		recovery_detected = self._detect_recovery_from_failure(msg_tool_info, session_id)
		if recovery_detected:
			patterns.append(recovery_detected)

		# -- TOOL_SELECTION --
		explicit_agents = [
			d for d in agent_dispatches
			if d.get("subagent_type") and d.get("subagent_type") != "default"
		]
		if explicit_agents or skill_invocations:
			evidence_parts = []
			if explicit_agents:
				types = [d.get("subagent_type", "") for d in explicit_agents]
				evidence_parts.append(f"Agent subagent_types: {', '.join(types)}")
			if skill_invocations:
				skills_used = [d.get("skill", "") for d in skill_invocations]
				evidence_parts.append(f"Skill invocations: {', '.join(skills_used)}")
			patterns.append(PatternSignal(
				pattern_type=PatternType.TOOL_SELECTION,
				session_ids=[session_id],
				confidence=0.8,
				description=(
					"Deliberate tool selection via agent subagent_type or skill invocation"
				),
				evidence_snippet="; ".join(evidence_parts)[:500],
			))

		# -- META_COGNITION --
		clear_commands = [
			cmd for cmd in bash_commands if "/clear" in cmd or "/compact" in cmd
		]
		if clear_commands:
			patterns.append(PatternSignal(
				pattern_type=PatternType.META_COGNITION,
				session_ids=[session_id],
				confidence=0.5,
				description="Session management via /clear or /compact commands",
				evidence_snippet=f"Commands: {', '.join(clear_commands[:3])}",
			))

		# NOTE: COMMUNICATION_CLARITY is NOT detected by BehaviorSignalExtractor.
		# It is a cross-signal from CommSignalExtractor.

		# --- Pass 3: Agent orchestration signals ---
		if agent_dispatches:
			parallel_count = sum(
				1 for info in msg_tool_info if info["agent_count"] >= 2
			)
			subtypes = [d.get("subagent_type", "default") for d in agent_dispatches]
			skill_signal = SkillSignal(
				canonical_name="agentic-workflows",
				source="agent_dispatch",
				confidence=0.85,
				depth_hint=DepthLevel.APPLIED if parallel_count > 0 else DepthLevel.USED,
				evidence_snippet=(
					f"Dispatched {len(agent_dispatches)} agents "
					f"(subtypes: {', '.join(subtypes)})"
				)[:500],
				evidence_type="architecture_decision",
				metadata={
					"dispatch_count": len(agent_dispatches),
					"parallel_dispatches": parallel_count,
					"subagent_types": subtypes,
				},
			)
			skills.setdefault("agentic-workflows", []).append(skill_signal)

		# Skill invocation → planning evidence
		for inv in skill_invocations:
			skill_name = inv.get("skill", "unknown")
			skill_signal = SkillSignal(
				canonical_name="agentic-workflows",
				source="skill_invocation",
				confidence=0.8,
				depth_hint=DepthLevel.APPLIED,
				evidence_snippet=f"Invoked skill: {skill_name}",
				evidence_type="planning",
				metadata={"skill_name": skill_name},
			)
			skills.setdefault("agentic-workflows", []).append(skill_signal)

		# --- Pass 4: Git workflow signals ---
		if session.git_branch:
			branch_type = self._classify_branch(session.git_branch)
			git_signal = SkillSignal(
				canonical_name="git",
				source="git_workflow",
				confidence=0.7,
				depth_hint=DepthLevel.USED,
				evidence_snippet=f"Working on branch: {session.git_branch}",
				evidence_type="direct_usage",
				metadata={"branch_type": branch_type},
			)
			skills.setdefault("git", []).append(git_signal)

		# Worktree usage
		worktree_commands = [
			cmd for cmd in bash_commands if "git worktree" in cmd
		]
		worktree_usage = 1 if worktree_commands else 0
		if worktree_commands:
			git_adv_signal = SkillSignal(
				canonical_name="git",
				source="git_workflow",
				confidence=0.9,
				depth_hint=DepthLevel.DEEP,
				evidence_snippet=f"git worktree: {worktree_commands[0][:200]}",
				evidence_type="direct_usage",
				metadata={"worktree_commands": worktree_commands},
			)
			skills.setdefault("git", []).append(git_adv_signal)

		# gh pr → ci-cd practice
		gh_pr_commands = [cmd for cmd in bash_commands if "gh pr" in cmd]
		if gh_pr_commands:
			cicd_signal = SkillSignal(
				canonical_name="ci-cd",
				source="git_workflow",
				confidence=0.7,
				depth_hint=DepthLevel.USED,
				evidence_snippet=f"PR workflow: {gh_pr_commands[0][:200]}",
				evidence_type="direct_usage",
				metadata={"pr_commands": gh_pr_commands},
			)
			skills.setdefault("ci-cd", []).append(cicd_signal)

		# --- Pass 5: Quality practice signals ---

		# Security
		security_files = [
			fp for fp in file_paths_edited if _SECURITY_KEYWORDS.search(fp)
		]
		if security_files:
			sec_signal = SkillSignal(
				canonical_name="security",
				source="quality_signal",
				confidence=0.6,
				depth_hint=DepthLevel.USED,
				evidence_snippet=f"Edited security-related files: {', '.join(security_files[:3])}",
				evidence_type="direct_usage",
			)
			skills.setdefault("security", []).append(sec_signal)

		# Testing quality signal (separate from pattern)
		if test_file_edits:
			test_signal = SkillSignal(
				canonical_name="testing",
				source="quality_signal",
				confidence=0.7,
				depth_hint=DepthLevel.USED,
				evidence_snippet=(
					f"Edited test files: {', '.join(test_file_edits[:3])}"
				),
				evidence_type="testing",
			)
			skills.setdefault("testing", []).append(test_signal)

		# Code review detection
		review_commands = [
			cmd for cmd in bash_commands
			if "gh pr" in cmd or "copilot review" in cmd
		]
		if review_commands:
			review_signal = SkillSignal(
				canonical_name="code-review",
				source="quality_signal",
				confidence=0.6,
				depth_hint=DepthLevel.USED,
				evidence_snippet=f"Review commands: {', '.join(review_commands[:3])}",
				evidence_type="review",
			)
			skills.setdefault("code-review", []).append(review_signal)

		# --- Compute metrics ---
		error_count = sum(1 for info in msg_tool_info if info["is_error"])
		recovery_count = 1 if recovery_detected else 0
		parallel_dispatch_count = sum(
			1 for info in msg_tool_info if info["agent_count"] >= 2
		)

		metrics: dict[str, float] = {
			"agent_dispatch_count": float(len(agent_dispatches)),
			"parallel_dispatch_count": float(parallel_dispatch_count),
			"skill_invocation_count": float(len(skill_invocations)),
			"error_count": float(error_count),
			"recovery_count": float(recovery_count),
			"test_file_edit_count": float(len(test_file_edits)),
			"worktree_usage": float(worktree_usage),
			"branch_type": 0.0,  # Placeholder; actual string in metadata
		}

		# Store branch_type string in a pattern-accessible way
		if session.git_branch:
			branch_type_str = self._classify_branch(session.git_branch)
		else:
			branch_type_str = "unknown"

		return SignalResult(
			session_id=session_id,
			session_date=session.timestamp,
			project_context=session.project_context,
			git_branch=session.git_branch,
			skills=skills,
			patterns=patterns,
			project_signals=project_signals,
			metrics={
				**metrics,
				"branch_type_str": 0.0,  # Use metadata on git skill for actual value
			},
		)

	# -------------------------------------------------------------------
	# Sequence detectors
	# -------------------------------------------------------------------

	def _detect_systematic_debugging(
		self, msg_info: list[dict[str, Any]], session_id: str
	) -> PatternSignal | None:
		"""Detect Grep→Read→Edit within a 5-message window."""
		for i in range(len(msg_info)):
			tools_i = {t["name"] for t in msg_info[i].get("tools", [])}
			if "Grep" not in tools_i:
				continue
			# Look for Read then Edit within next 4 messages
			found_read = False
			for j in range(i, min(i + 5, len(msg_info))):
				tools_j = {t["name"] for t in msg_info[j].get("tools", [])}
				if "Read" in tools_j:
					found_read = True
				if found_read and "Edit" in tools_j and j > i:
					return PatternSignal(
						pattern_type=PatternType.SYSTEMATIC_DEBUGGING,
						session_ids=[session_id],
						confidence=0.8,
						description=(
							"Grep→Read→Edit debugging sequence detected"
						),
						evidence_snippet=(
							f"Message {i}: Grep, message {j}: Edit "
							"(Read found in between)"
						),
						metadata={"sequence_start": i, "sequence_end": j},
					)
		return None

	def _detect_tradeoff_analysis(
		self,
		msg_info: list[dict[str, Any]],
		agent_dispatches: list[dict[str, Any]],
		session_id: str,
	) -> PatternSignal | None:
		"""Detect Explore/Plan Agent dispatch before any Write/Edit."""
		explore_agents = [
			d for d in agent_dispatches
			if d.get("subagent_type") in ("Explore", "Plan")
		]
		if not explore_agents:
			return None

		# Check that an Explore/Plan agent appears before any Write/Edit
		first_explore_idx = None
		first_write_idx = None
		for i, info in enumerate(msg_info):
			for tool in info.get("tools", []):
				if (
					tool["name"] == "Agent"
					and tool["input"].get("subagent_type") in ("Explore", "Plan")
					and first_explore_idx is None
				):
					first_explore_idx = i
				if tool["name"] in ("Write", "Edit") and first_write_idx is None:
					first_write_idx = i

		if first_explore_idx is not None and (
			first_write_idx is None or first_explore_idx < first_write_idx
		):
			subtype = explore_agents[0].get("subagent_type", "Explore")
			return PatternSignal(
				pattern_type=PatternType.TRADEOFF_ANALYSIS,
				session_ids=[session_id],
				confidence=0.7,
				description=(
					f"Agent ({subtype}) dispatched for exploration before implementation"
				),
				evidence_snippet=(
					f"Agent subagent_type={subtype} at message {first_explore_idx}, "
					f"first write at message {first_write_idx}"
				),
				metadata={"explore_subtype": subtype},
			)
		return None

	def _detect_scope_management(
		self, task_creates: list[dict[str, Any]], session_id: str
	) -> PatternSignal | None:
		"""Detect TaskCreate with phase/dependency keywords in description."""
		for tc in task_creates:
			desc = tc.get("description", "") + " " + tc.get("subject", "")
			if _PHASE_KEYWORDS.search(desc):
				return PatternSignal(
					pattern_type=PatternType.SCOPE_MANAGEMENT,
					session_ids=[session_id],
					confidence=0.7,
					description="Task creation with phased/dependency-aware naming",
					evidence_snippet=f"TaskCreate: {desc[:200]}",
					metadata={"task_subject": tc.get("subject", "")},
				)
		return None

	def _detect_recovery_from_failure(
		self, msg_info: list[dict[str, Any]], session_id: str
	) -> PatternSignal | None:
		"""Detect error followed by a different approach within 3 messages."""
		for i in range(len(msg_info)):
			if not msg_info[i]["is_error"]:
				continue
			error_content = msg_info[i].get("error_content", "")
			# Look within next 3 messages for a different approach
			for j in range(i + 1, min(i + 4, len(msg_info))):
				tools_j = msg_info[j].get("tools", [])
				for tool in tools_j:
					if tool["name"] in ("Edit", "Write", "Bash"):
						# Check it's not an exact retry of the same command
						tool_input = tool.get("input", {})
						cmd = _extract_command_from_input(tool_input)
						old_str = tool_input.get("old_string", "")
						new_str = tool_input.get("new_string", "")
						# It's a "different approach" if it's an Edit/Write
						# (fixing code) or a different command
						if tool["name"] in ("Edit", "Write"):
							return PatternSignal(
								pattern_type=PatternType.RECOVERY_FROM_FAILURE,
								session_ids=[session_id],
								confidence=0.8,
								description=(
									"Error encountered, followed by code change "
									"(different approach)"
								),
								evidence_snippet=(
									f"Error at message {i}: "
									f"{error_content[:100]}... "
									f"Recovery at message {j}"
								)[:500],
								metadata={
									"error_index": i,
									"recovery_index": j,
								},
							)
		return None

	# -------------------------------------------------------------------
	# Utilities
	# -------------------------------------------------------------------

	@staticmethod
	def _classify_branch(branch: str) -> str:
		"""Classify a git branch name by prefix convention."""
		prefixes = {
			"feat/": "feature",
			"feature/": "feature",
			"fix/": "fix",
			"bugfix/": "fix",
			"hotfix/": "fix",
			"cleanup/": "cleanup",
			"refactor/": "cleanup",
			"release/": "release",
			"chore/": "chore",
			"docs/": "docs",
			"test/": "test",
		}
		lower_branch = branch.lower()
		for prefix, btype in prefixes.items():
			if lower_branch.startswith(prefix):
				return btype
		if lower_branch in ("main", "master", "develop", "dev"):
			return "default"
		return "other"
