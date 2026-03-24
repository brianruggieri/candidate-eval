"""Tests for the sanitizer module — secret detection and text redaction."""

from __future__ import annotations

import pytest

from claude_candidate.sanitizer import (
	RedactionResult,
	SecretFinding,
	detect_secrets,
	sanitize_text,
)


class TestDetectSecrets:
	def test_detects_api_key_patterns(self) -> None:
		text = "Using key sk-abcdefghij1234567890 for the API call."
		findings = detect_secrets(text)
		categories = {f.category for f in findings}
		assert "api_key" in categories

	def test_detects_key_prefix_pattern(self) -> None:
		text = "Set key-abcdefghijklmnopqrstu as your access token."
		findings = detect_secrets(text)
		categories = {f.category for f in findings}
		assert "api_key" in categories

	def test_detects_env_var_api_keys(self) -> None:
		text = "OPENAI_API_KEY=sk-mysupersecretkeyvalue1234"
		findings = detect_secrets(text)
		categories = {f.category for f in findings}
		assert "api_key" in categories

	def test_detects_aws_keys(self) -> None:
		text = "AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
		findings = detect_secrets(text)
		categories = {f.category for f in findings}
		assert "api_key" in categories

	def test_detects_github_tokens(self) -> None:
		text = "Token: ghp_1234567890abcdefghijklmnopqrstuv"
		findings = detect_secrets(text)
		categories = {f.category for f in findings}
		assert "api_key" in categories

	def test_detects_bearer_tokens(self) -> None:
		text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
		findings = detect_secrets(text)
		categories = {f.category for f in findings}
		assert "auth_token" in categories

	def test_detects_token_assignments(self) -> None:
		text = "token = eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9abcdefghij"
		findings = detect_secrets(text)
		categories = {f.category for f in findings}
		assert "auth_token" in categories

	def test_detects_email_addresses(self) -> None:
		text = "Contact me at alice@example.com for more info."
		findings = detect_secrets(text)
		categories = {f.category for f in findings}
		assert "pii" in categories

	def test_detects_absolute_paths(self) -> None:
		text = "File saved to /Users/alice/projects/myapp/config.py"
		findings = detect_secrets(text)
		categories = {f.category for f in findings}
		assert "absolute_path" in categories

	def test_detects_home_absolute_paths(self) -> None:
		text = "Running script at /home/bob/scripts/deploy.sh"
		findings = detect_secrets(text)
		categories = {f.category for f in findings}
		assert "absolute_path" in categories

	def test_no_false_positives_on_clean_text(self) -> None:
		text = (
			"We used Python and TypeScript to build a REST API. "
			"The project lives in a relative path like src/models/user.py. "
			"React hooks made state management cleaner."
		)
		findings = detect_secrets(text)
		assert findings == []

	def test_finding_has_correct_span(self) -> None:
		text = "My email is test@example.com and that's it."
		findings = detect_secrets(text)
		pii = [f for f in findings if f.category == "pii"]
		assert len(pii) == 1
		assert text[pii[0].start : pii[0].end] == pii[0].matched_text

	def test_multiple_findings_in_one_text(self) -> None:
		text = (
			"User alice@example.com with token sk-abcdef12345678901234 "
			"at /Users/alice/repos/project/main.py"
		)
		findings = detect_secrets(text)
		categories = {f.category for f in findings}
		assert "pii" in categories
		assert "api_key" in categories
		assert "absolute_path" in categories


class TestSanitizeText:
	def test_replaces_api_keys(self) -> None:
		text = "API_KEY=sk-supersecretkey1234567890"
		result = sanitize_text(text)
		assert "sk-supersecretkey1234567890" not in result.sanitized
		assert "[REDACTED]" in result.sanitized

	def test_replaces_absolute_paths(self) -> None:
		text = "Config loaded from /Users/alice/myapp/config.json"
		result = sanitize_text(text)
		assert "/Users/alice" not in result.sanitized
		assert "[PATH_REDACTED]" in result.sanitized

	def test_preserves_relative_paths(self) -> None:
		text = "See src/utils/helpers.py for the implementation."
		result = sanitize_text(text)
		assert "src/utils/helpers.py" in result.sanitized

	def test_preserves_technology_signals(self) -> None:
		text = "Used React, TypeScript, and Python with FastAPI."
		result = sanitize_text(text)
		assert "React" in result.sanitized
		assert "TypeScript" in result.sanitized
		assert "Python" in result.sanitized
		assert "FastAPI" in result.sanitized

	def test_returns_redaction_summary(self) -> None:
		text = "Email me at bob@example.com or use API key sk-abc1234567890abcdef12"
		result = sanitize_text(text)
		assert result.redaction_count >= 2
		assert isinstance(result.redactions_by_type, dict)

	def test_redaction_count_matches_by_type_total(self) -> None:
		text = "Email: dev@test.com, key: sk-longkeyvalue12345678"
		result = sanitize_text(text)
		assert result.redaction_count == sum(result.redactions_by_type.values())

	def test_handles_empty_input(self) -> None:
		result = sanitize_text("")
		assert result.sanitized == ""
		assert result.redaction_count == 0
		assert result.redactions_by_type == {}

	def test_handles_clean_text(self) -> None:
		text = "Built a pipeline using asyncio and SQLite."
		result = sanitize_text(text)
		assert result.sanitized == text
		assert result.redaction_count == 0

	def test_idempotent(self) -> None:
		text = "Token: ghp_1234567890abcdefghijklmnopqrstuv at /home/user/app/run.py"
		first = sanitize_text(text)
		second = sanitize_text(first.sanitized)
		assert first.sanitized == second.sanitized

	def test_result_is_redaction_result_type(self) -> None:
		result = sanitize_text("hello world")
		assert isinstance(result, RedactionResult)

	def test_secret_finding_is_frozen(self) -> None:
		finding = SecretFinding(
			category="api_key",
			start=0,
			end=5,
			matched_text="sk-ab",
		)
		with pytest.raises(Exception):
			finding.category = "mutated"  # type: ignore[misc]

	def test_anthropic_api_key_detected(self) -> None:
		text = "ANTHROPIC_API_KEY=sk-ant-api03-secretkeyvalue1234567890"
		result = sanitize_text(text)
		assert "sk-ant-api03-secretkeyvalue1234567890" not in result.sanitized
		assert result.redaction_count >= 1

	def test_bearer_token_case_insensitive(self) -> None:
		text = "authorization: bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9"
		result = sanitize_text(text)
		assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result.sanitized
