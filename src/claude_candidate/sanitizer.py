"""
Sanitizer: strips secrets, PII, and absolute paths from session content.

This module is the privacy trust boundary for the session pipeline. Missed
secrets here can leak real data into the CandidateProfile.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REDACTION_PLACEHOLDER = "[REDACTED]"
PATH_REDACTION = "[PATH_REDACTED]"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SecretFinding:
	"""A detected secret or sensitive data."""

	category: str  # "api_key", "auth_token", "pii", "absolute_path"
	start: int
	end: int
	matched_text: str


@dataclass
class RedactionResult:
	"""Result of sanitizing a text block."""

	sanitized: str
	redaction_count: int
	redactions_by_type: dict[str, int] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Compiled patterns
# ---------------------------------------------------------------------------

API_KEY_PATTERNS: list[re.Pattern[str]] = [
	# sk- and key- prefix secrets (20+ alphanumeric chars)
	re.compile(r"sk-[A-Za-z0-9\-_]{20,}"),
	re.compile(r"key-[A-Za-z0-9\-_]{20,}"),
	# GitHub tokens
	re.compile(r"gh[pos]_[A-Za-z0-9]{20,}"),
	# Environment variable assignments containing secrets
	re.compile(
		r"(?:OPENAI_API_KEY|ANTHROPIC_API_KEY|AWS_SECRET_ACCESS_KEY"
		r"|AWS_ACCESS_KEY_ID|API_KEY|SECRET_KEY)"
		r"\s*=\s*\S+",
		re.IGNORECASE,
	),
]

AUTH_TOKEN_PATTERNS: list[re.Pattern[str]] = [
	# Bearer tokens (case-insensitive)
	re.compile(r"(?i)bearer\s+\S{10,}"),
	# token = <value> with 20+ char values
	re.compile(r"(?i)token\s*=\s*\S{20,}"),
]

PII_PATTERNS: list[re.Pattern[str]] = [
	# Email addresses
	re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
]

ABSOLUTE_PATH_PATTERNS: list[re.Pattern[str]] = [
	# macOS/Linux home directories
	re.compile(r"""(?:/Users/[^/\s"'][^\s"']*|/home/[^/\s"'][^\s"']*)"""),
	# Windows drive-letter paths (C:\Users\...)
	re.compile(r"""[A-Z]:\\[Uu]sers\\[^\s"'\\]+(?:\\[^\s"']*)?"""),
	# UNC paths (\\server\share\...)
	re.compile(r"""\\\\[^\s"'\\]+\\[^\s"']*"""),
]

PATTERN_GROUPS: list[tuple[str, list[re.Pattern[str]]]] = [
	("api_key", API_KEY_PATTERNS),
	("auth_token", AUTH_TOKEN_PATTERNS),
	("pii", PII_PATTERNS),
	("absolute_path", ABSOLUTE_PATH_PATTERNS),
]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _scan_patterns(
	text: str,
	category: str,
	patterns: list[re.Pattern[str]],
) -> list[SecretFinding]:
	"""Find all matches for a pattern group and return findings."""
	findings: list[SecretFinding] = []
	for pattern in patterns:
		for m in pattern.finditer(text):
			findings.append(
				SecretFinding(
					category=category,
					start=m.start(),
					end=m.end(),
					matched_text=m.group(),
				)
			)
	return findings


def detect_secrets(text: str) -> list[SecretFinding]:
	"""Scan text for secrets, PII, and absolute paths."""
	findings: list[SecretFinding] = []
	for category, patterns in PATTERN_GROUPS:
		findings.extend(_scan_patterns(text, category, patterns))
	return findings


def _build_type_counts(findings: list[SecretFinding]) -> dict[str, int]:
	"""Count findings per category."""
	counts: dict[str, int] = {}
	for f in findings:
		counts[f.category] = counts.get(f.category, 0) + 1
	return counts


def _placeholder_for(category: str) -> str:
	"""Return the appropriate placeholder string for a category."""
	if category == "absolute_path":
		return PATH_REDACTION
	return REDACTION_PLACEHOLDER


def sanitize_text(text: str) -> RedactionResult:
	"""Replace all findings with placeholders and return a RedactionResult."""
	if not text:
		return RedactionResult(sanitized="", redaction_count=0)

	findings = detect_secrets(text)
	if not findings:
		return RedactionResult(sanitized=text, redaction_count=0)

	# Sort by start position descending so replacements don't shift offsets
	sorted_findings = sorted(findings, key=lambda f: f.start, reverse=True)

	result = text
	for f in sorted_findings:
		placeholder = _placeholder_for(f.category)
		result = result[: f.start] + placeholder + result[f.end :]

	return RedactionResult(
		sanitized=result,
		redaction_count=len(findings),
		redactions_by_type=_build_type_counts(findings),
	)
