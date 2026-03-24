"""Tests for the claude_cli wrapper module."""

from __future__ import annotations

import subprocess

import pytest

from claude_candidate.claude_cli import ClaudeCLIError, call_claude, check_claude_available


class TestCheckClaudeAvailable:
	def test_returns_true_when_cli_exists(self, fp):
		fp.register_subprocess(
			["claude", "--version"],
			returncode=0,
			stdout="claude 1.0.0",
		)
		assert check_claude_available() is True

	def test_returns_false_when_cli_missing(self, fp):
		fp.register_subprocess(
			["claude", "--version"],
			callback=lambda _: (_ for _ in ()).throw(FileNotFoundError("No such file")),
		)
		assert check_claude_available() is False

	def test_returns_false_on_nonzero_exit(self, fp):
		fp.register_subprocess(
			["claude", "--version"],
			returncode=1,
			stdout="",
		)
		assert check_claude_available() is False

	def test_returns_false_on_timeout(self, fp):
		fp.register_subprocess(
			["claude", "--version"],
			callback=lambda _: (_ for _ in ()).throw(subprocess.TimeoutExpired("claude", 10)),
		)
		assert check_claude_available() is False


class TestCallClaude:
	def test_returns_stdout_on_success(self, fp):
		fp.register_subprocess(
			["claude", "--print", "-p", fp.any()],
			returncode=0,
			stdout="Generated content here",
		)
		result = call_claude("test prompt")
		assert result == "Generated content here"

	def test_raises_on_nonzero_exit(self, fp):
		fp.register_subprocess(
			["claude", "--print", "-p", fp.any()],
			returncode=1,
			stdout="",
			stderr="error: something went wrong",
		)
		with pytest.raises(ClaudeCLIError, match="exited 1"):
			call_claude("test prompt")

	def test_raises_on_timeout(self, fp):
		fp.register_subprocess(
			["claude", "--print", "-p", fp.any()],
			callback=lambda _: (_ for _ in ()).throw(subprocess.TimeoutExpired("claude", 60)),
		)
		with pytest.raises(ClaudeCLIError, match="timed out"):
			call_claude("test prompt")

	def test_raises_on_empty_output(self, fp):
		fp.register_subprocess(
			["claude", "--print", "-p", fp.any()],
			returncode=0,
			stdout="   ",
		)
		with pytest.raises(ClaudeCLIError, match="empty output"):
			call_claude("test prompt")

	def test_raises_when_cli_not_found(self, fp):
		fp.register_subprocess(
			["claude", "--print", "-p", fp.any()],
			callback=lambda _: (_ for _ in ()).throw(FileNotFoundError("No such file")),
		)
		with pytest.raises(ClaudeCLIError, match="not found"):
			call_claude("test prompt")

	def test_accepts_custom_timeout(self, fp):
		fp.register_subprocess(
			["claude", "--print", "-p", fp.any()],
			returncode=0,
			stdout="Result",
		)
		result = call_claude("test prompt", timeout=120)
		assert result == "Result"

	def test_strips_surrounding_whitespace(self, fp):
		fp.register_subprocess(
			["claude", "--print", "-p", fp.any()],
			returncode=0,
			stdout="  trimmed output  \n",
		)
		result = call_claude("test prompt")
		assert result == "trimmed output"
