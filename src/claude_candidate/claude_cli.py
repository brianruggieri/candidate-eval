"""
Thin wrapper around the ``claude --print`` CLI.

All failures raise ``ClaudeCLIError`` — callers decide how to handle them.
"""

from __future__ import annotations

import subprocess


class ClaudeCLIError(Exception):
    """Raised when the Claude CLI is unavailable or returns an error."""


def check_claude_available() -> bool:
    """Return True if the ``claude`` CLI is installed and responds."""
    try:
        result = subprocess.run(
            ["claude", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result.returncode == 0
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return False


def call_claude(prompt: str, *, timeout: int = 60) -> str:
    """Run ``claude --print -p <prompt>`` and return stdout.

    Args:
        prompt: The prompt text to send.
        timeout: Seconds before the subprocess is killed.

    Returns:
        Non-empty stdout from the Claude CLI.

    Raises:
        ClaudeCLIError: If the CLI is missing, times out, exits non-zero,
            or returns empty output.
    """
    try:
        result = subprocess.run(
            ["claude", "--print", "-p", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except FileNotFoundError as exc:
        raise ClaudeCLIError("claude CLI not found — install it and ensure it is on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise ClaudeCLIError(f"claude CLI timed out after {timeout}s") from exc
    except OSError as exc:
        raise ClaudeCLIError(f"OS error running claude CLI: {exc}") from exc

    if result.returncode != 0:
        stderr_snippet = result.stderr.strip()[:200]
        raise ClaudeCLIError(
            f"claude CLI exited {result.returncode}: {stderr_snippet}"
        )

    output = result.stdout.strip()
    if not output:
        raise ClaudeCLIError("claude CLI returned empty output")

    return output
