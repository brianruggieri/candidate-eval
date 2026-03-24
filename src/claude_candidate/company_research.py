"""Claude-powered company research module.

Calls Claude CLI to research a company and returns structured data
about mission, values, culture, tech philosophy, and more.
"""

from __future__ import annotations

import json

import claude_candidate.claude_cli as _claude_cli

_RESEARCH_PROMPT = """\
Research the company "{company_name}" and return a JSON object with the following fields:

- "mission": a one-sentence summary of the company's mission
- "values": an array of core company values (strings)
- "culture_signals": an array of culture signals or traits (strings)
- "tech_philosophy": a brief description of their engineering/tech philosophy
- "ai_native": boolean — true if the company is AI-native or heavily AI-focused
- "product_domains": an array of product domains or industries they operate in
- "team_size_signal": a rough description of team size (e.g. "startup (<50)", "mid-size (50-500)", "enterprise (500+)")

Return ONLY valid JSON, no commentary or markdown. Example format:
{{
  "mission": "...",
  "values": ["...", "..."],
  "culture_signals": ["...", "..."],
  "tech_philosophy": "...",
  "ai_native": false,
  "product_domains": ["...", "..."],
  "team_size_signal": "..."
}}
"""


def _strip_code_fences(text: str) -> str:
	"""Remove markdown code fences (```json ... ``` or ``` ... ```) from text."""
	stripped = text.strip()
	if stripped.startswith("```"):
		lines = stripped.splitlines()
		# Drop first line (```json or ```) and last line (```)
		inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
		stripped = "\n".join(inner).strip()
	return stripped


def research_company(company_name: str, *, timeout: int = 60) -> dict:
	"""Call Claude to research a company. Returns structured dict.

	Args:
	    company_name: The name of the company to research.
	    timeout: Seconds before the CLI subprocess is killed.

	Returns:
	    Parsed dict with company research fields.

	Raises:
	    claude_candidate.claude_cli.ClaudeCLIError: If the CLI call fails.
	    ValueError: If the response cannot be parsed as JSON.
	"""
	prompt = _RESEARCH_PROMPT.format(company_name=company_name)
	raw = _claude_cli.call_claude(prompt, timeout=timeout)
	cleaned = _strip_code_fences(raw)
	try:
		return json.loads(cleaned)
	except (json.JSONDecodeError, ValueError) as exc:
		raise ValueError(f"Failed to parse company research response as JSON: {exc}") from exc
