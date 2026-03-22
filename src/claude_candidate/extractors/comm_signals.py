"""
CommSignalExtractor — Tier 3+4 communication signals.

Reads the human side of the conversation to detect steering precision,
scope management, adversarial self-review ("grill me"), and handoff discipline.

These capture "how you work" signals that no resume can show.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch
from typing import Any

from claude_candidate.extractors import (
	NormalizedSession,
	PatternSignal,
	SignalResult,
)
from claude_candidate.message_format import NormalizedMessage
from claude_candidate.schemas.candidate_profile import PatternType


# ---------------------------------------------------------------------------
# Human message filtering
# ---------------------------------------------------------------------------


def _is_human_message(msg: NormalizedMessage) -> bool:
	"""Filter to actual human input — exclude tool_result messages."""
	if msg["role"] != "user":
		return False
	# Check if content contains tool_result blocks (automated, not human)
	for block in msg["content"]:
		if block.get("type") == "tool_result":
			return False
	return True


def _get_text(msg: NormalizedMessage) -> str:
	"""Extract concatenated text from a message's content blocks."""
	parts: list[str] = []
	for block in msg["content"]:
		if block.get("type") == "text":
			text = block.get("text", "")
			if text:
				parts.append(text)
	return " ".join(parts)


def _text_length(msg: NormalizedMessage) -> int:
	"""Total character count of text content in a message."""
	return len(_get_text(msg))


# ---------------------------------------------------------------------------
# Detection patterns (compiled once)
# ---------------------------------------------------------------------------

# Steering: redirect keywords at the start of a short user message
_REDIRECT_RE = re.compile(
	r"^\s*(no[,.\s]|not\s+that|instead|actually|only|just|don'?t|stop)",
	re.IGNORECASE,
)

# Scope management
_DEFERRAL_RE = re.compile(
	r"(not\s+yet|later|just\s+.*?\s+for\s+now|let'?s\s+not|park\s+that"
	r"|out\s+of\s+scope|just\s+the\s+basics|nothing\s+fancy"
	r"|keep\s+it\s+simple|minimal)",
	re.IGNORECASE,
)
_PHASE_GATE_RE = re.compile(
	r"(phase\s+1|step\s+1\s+first|before\s+we\s+move\s+on)",
	re.IGNORECASE,
)
_SESSION_BOUNDARY_RE = re.compile(
	r"(save\s+the\s+session|pick\s+up\s+fresh|clean\s+slate|wrap\s+up)",
	re.IGNORECASE,
)

# Adversarial self-review
_GRILL_RE = re.compile(
	r"(grill\s+me|grill\s+as\s+needed)",
	re.IGNORECASE,
)
_HONESTY_RE = re.compile(
	r"(be\s+honest|be\s+critical|poke\s+holes|do\s+you\s+agree\??\s*be\s+honest)",
	re.IGNORECASE,
)
_FEEDBACK_RE = re.compile(
	r"(what\s+am\s+I\s+missing|what\s+could\s+go\s+wrong|any\s+concerns)",
	re.IGNORECASE,
)
_SELF_ASSESS_RE = re.compile(
	r"(are\s+we\s+in\s+good\s+shape|how\s+does\s+this\s+look|are\s+we\s+on\s+track)",
	re.IGNORECASE,
)

# Handoff discipline
_HANDOFF_RE = re.compile(
	r"(handoff|hand\s+off|pick\s+up\s+fresh|leave\s+context\s+for|new\s+agent)",
	re.IGNORECASE,
)
_PLAN_REF_RE = re.compile(
	r"\.claude/plans/",
	re.IGNORECASE,
)

# Context reset patterns (slash commands that reset/compress context)
_CONTEXT_RESET_RE = re.compile(
	r"(/clear|/compact|/reset)", re.IGNORECASE,
)

# Handoff file patterns (for Write/Edit tool_use detection)
_HANDOFF_FILE_PATTERNS = ("*handoff*", "*HANDOFF*")


# ---------------------------------------------------------------------------
# CommSignalExtractor
# ---------------------------------------------------------------------------


class CommSignalExtractor:
	"""Extracts Tier 3+4 signals: steering, scope management, grill-me, handoffs."""

	def name(self) -> str:
		return "comm_signals"

	def extract_session(self, session: NormalizedSession) -> SignalResult:
		messages = session.messages
		human_messages = [m for m in messages if _is_human_message(m)]

		# --- Steering precision ---
		steering = self._detect_steering(messages)

		# --- Scope management ---
		scope = self._detect_scope_management(human_messages)

		# --- Adversarial self-review ---
		meta = self._detect_adversarial_review(human_messages)

		# --- Handoff discipline ---
		handoff = self._detect_handoff(human_messages, messages)

		# --- Assemble patterns ---
		patterns: list[PatternSignal] = []

		if steering["steering_count"] > 0:
			patterns.append(PatternSignal(
				pattern_type=PatternType.COMMUNICATION_CLARITY,
				session_ids=[session.session_id],
				confidence=min(0.6 + steering["steering_count"] * 0.1, 0.95),
				description=(
					f"Steering precision: {steering['steering_count']} concise "
					f"redirections after verbose assistant output"
				),
				evidence_snippet=steering["evidence"][:500],
				metadata={
					"steering_count": steering["steering_count"],
					"steering_precision_ratio": steering["steering_precision_ratio"],
				},
			))

		if scope["deferral_count"] > 0 or scope["phase_gates"] > 0 or scope["clean_exits"] > 0:
			total = scope["deferral_count"] + scope["phase_gates"] + scope["clean_exits"]
			patterns.append(PatternSignal(
				pattern_type=PatternType.SCOPE_MANAGEMENT,
				session_ids=[session.session_id],
				confidence=min(0.6 + total * 0.1, 0.95),
				description=(
					f"Scope control: {scope['deferral_count']} deferrals, "
					f"{scope['phase_gates']} phase gates, "
					f"{scope['clean_exits']} clean exits"
				),
				evidence_snippet=scope["evidence"][:500],
				metadata={
					"deferral_count": scope["deferral_count"],
					"phase_gates": scope["phase_gates"],
					"clean_exits": scope["clean_exits"],
				},
			))

		if meta["grill_count"] > 0 or meta["honesty_requests"] > 0:
			total = (
				meta["grill_count"] + meta["honesty_requests"]
				+ meta["feedback_invitations"] + meta["self_assessments"]
			)
			patterns.append(PatternSignal(
				pattern_type=PatternType.META_COGNITION,
				session_ids=[session.session_id],
				confidence=min(0.6 + total * 0.1, 0.95),
				description=(
					f"Adversarial self-review: {meta['grill_count']} grill requests, "
					f"{meta['honesty_requests']} honesty requests"
				),
				evidence_snippet=meta["evidence"][:500],
				metadata={
					"grill_count": meta["grill_count"],
					"honesty_requests": meta["honesty_requests"],
					"feedback_invitations": meta["feedback_invitations"],
					"self_assessments": meta["self_assessments"],
				},
			))

		if handoff["handoff_count"] > 0 or handoff["plan_references"] > 0:
			total = (
				handoff["handoff_count"]
				+ handoff["context_resets"]
				+ handoff["plan_references"]
			)
			patterns.append(PatternSignal(
				pattern_type=PatternType.DOCUMENTATION_DRIVEN,
				session_ids=[session.session_id],
				confidence=min(0.6 + total * 0.1, 0.95),
				description=(
					f"Handoff discipline: {handoff['handoff_count']} handoffs, "
					f"{handoff['plan_references']} plan references"
				),
				evidence_snippet=handoff["evidence"][:500],
				metadata={
					"handoff_count": handoff["handoff_count"],
					"context_resets": handoff["context_resets"],
					"plan_references": handoff["plan_references"],
				},
			))

		# --- Metrics ---
		metrics: dict[str, float] = {
			"human_message_count": float(len(human_messages)),
			"steering_count": float(steering["steering_count"]),
			"deferral_count": float(scope["deferral_count"]),
			"grill_count": float(meta["grill_count"]),
			"handoff_count": float(handoff["handoff_count"]),
			"context_reset_count": float(handoff["context_resets"]),
		}

		return SignalResult(
			session_id=session.session_id,
			session_date=session.timestamp,
			project_context=session.project_context,
			git_branch=session.git_branch,
			patterns=patterns,
			metrics=metrics,
		)

	# -------------------------------------------------------------------
	# Detection methods
	# -------------------------------------------------------------------

	def _detect_steering(
		self, messages: list[NormalizedMessage],
	) -> dict[str, Any]:
		"""Detect short redirections after long assistant output."""
		steering_count = 0
		total_pairs = 0
		evidence_parts: list[str] = []

		for i in range(len(messages) - 1):
			if messages[i]["role"] != "assistant":
				continue
			next_msg = messages[i + 1]
			if not _is_human_message(next_msg):
				continue

			total_pairs += 1
			user_text = _get_text(next_msg)
			assistant_len = _text_length(messages[i])

			if (
				len(user_text) < 150
				and assistant_len > 1000
				and _REDIRECT_RE.search(user_text)
			):
				steering_count += 1
				evidence_parts.append(user_text)

		precision_ratio = (
			steering_count / total_pairs if total_pairs > 0 else 0.0
		)

		return {
			"steering_count": steering_count,
			"steering_precision_ratio": round(precision_ratio, 3),
			"evidence": "; ".join(evidence_parts) if evidence_parts else "",
		}

	def _detect_scope_management(
		self, human_messages: list[NormalizedMessage],
	) -> dict[str, Any]:
		"""Detect deferrals, phase-gating, and session boundary language."""
		deferral_count = 0
		phase_gates = 0
		clean_exits = 0
		evidence_parts: list[str] = []

		for msg in human_messages:
			text = _get_text(msg)
			if _DEFERRAL_RE.search(text):
				deferral_count += 1
				evidence_parts.append(text)
			if _PHASE_GATE_RE.search(text):
				phase_gates += 1
				if text not in evidence_parts:
					evidence_parts.append(text)
			if _SESSION_BOUNDARY_RE.search(text):
				clean_exits += 1
				if text not in evidence_parts:
					evidence_parts.append(text)

		return {
			"deferral_count": deferral_count,
			"phase_gates": phase_gates,
			"clean_exits": clean_exits,
			"evidence": "; ".join(evidence_parts) if evidence_parts else "",
		}

	def _detect_adversarial_review(
		self, human_messages: list[NormalizedMessage],
	) -> dict[str, Any]:
		"""Detect grill-me, honesty requests, and feedback invitations."""
		grill_count = 0
		honesty_requests = 0
		feedback_invitations = 0
		self_assessments = 0
		evidence_parts: list[str] = []

		for msg in human_messages:
			text = _get_text(msg)
			if _GRILL_RE.search(text):
				grill_count += 1
				evidence_parts.append(text)
			if _HONESTY_RE.search(text):
				honesty_requests += 1
				if text not in evidence_parts:
					evidence_parts.append(text)
			if _FEEDBACK_RE.search(text):
				feedback_invitations += 1
				if text not in evidence_parts:
					evidence_parts.append(text)
			if _SELF_ASSESS_RE.search(text):
				self_assessments += 1
				if text not in evidence_parts:
					evidence_parts.append(text)

		return {
			"grill_count": grill_count,
			"honesty_requests": honesty_requests,
			"feedback_invitations": feedback_invitations,
			"self_assessments": self_assessments,
			"evidence": "; ".join(evidence_parts) if evidence_parts else "",
		}

	def _detect_handoff(
		self,
		human_messages: list[NormalizedMessage],
		all_messages: list[NormalizedMessage],
	) -> dict[str, Any]:
		"""Detect handoff language, Write to handoff files, plan references."""
		handoff_count = 0
		context_resets = 0
		plan_references = 0
		evidence_parts: list[str] = []

		# Scan human messages for handoff language, plan references, and context resets
		for msg in human_messages:
			text = _get_text(msg)
			if _HANDOFF_RE.search(text):
				handoff_count += 1
				evidence_parts.append(text)
			if _PLAN_REF_RE.search(text):
				plan_references += 1
				if text not in evidence_parts:
					evidence_parts.append(text)
			if _CONTEXT_RESET_RE.search(text):
				context_resets += 1

		# Scan all messages for Write/Edit to handoff files
		for msg in all_messages:
			if msg["role"] not in ("assistant", "tool_use"):
				continue
			for block in msg["content"]:
				if block.get("type") != "tool_use":
					continue
				tool_name = block.get("name", "")
				if tool_name not in ("Write", "Edit"):
					continue
				file_path = block.get("input", {}).get("file_path", "")
				if any(fnmatch(file_path, pat) for pat in _HANDOFF_FILE_PATTERNS):
					handoff_count += 1
					snippet = f"Write to {file_path}"
					if snippet not in evidence_parts:
						evidence_parts.append(snippet)

		return {
			"handoff_count": handoff_count,
			"context_resets": context_resets,
			"plan_references": plan_references,
			"evidence": "; ".join(evidence_parts) if evidence_parts else "",
		}
