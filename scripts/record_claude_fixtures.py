"""
record_claude_fixtures.py — Standalone script to record golden fixtures.

Reads tests/fixtures/sample_job_posting.txt, calls ``claude --print`` with
the requirement-extraction prompt, and saves the raw response to
tests/fixtures/claude_responses/parse_swe_posting.json.

Usage:
    python scripts/record_claude_fixtures.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
POSTING_FILE = REPO_ROOT / "tests" / "fixtures" / "sample_job_posting.txt"
OUTPUT_DIR = REPO_ROOT / "tests" / "fixtures" / "claude_responses"
OUTPUT_FILE = OUTPUT_DIR / "parse_swe_posting.json"

PARSE_PROMPT_TEMPLATE = """\
Extract job requirements from the following job posting as a JSON array.
Each element must have these fields:
  - description: string, concise description of the requirement
  - skill_mapping: non-empty array of lowercase skill/technology strings
  - priority: one of "must_have", "strong_preference", "nice_to_have", "implied"
  - source_text: the verbatim sentence or phrase from the posting

Return ONLY a valid JSON array with no commentary or markdown fences.

Job posting:
{posting_text}
"""

CLAUDE_TIMEOUT_SECONDS = 60


def main() -> int:
    if not POSTING_FILE.exists():
        print(f"ERROR: Sample posting not found: {POSTING_FILE}", file=sys.stderr)
        return 1

    posting_text = POSTING_FILE.read_text()
    prompt = PARSE_PROMPT_TEMPLATE.format(posting_text=posting_text)

    print(f"Calling claude --print for {POSTING_FILE.name}...")
    result = subprocess.run(
        ["claude", "--print", "-p", prompt],
        capture_output=True,
        text=True,
        timeout=CLAUDE_TIMEOUT_SECONDS,
    )

    if result.returncode != 0:
        print(f"ERROR: claude CLI failed (exit {result.returncode}):", file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        return 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(result.stdout)
    print(f"Saved response to {OUTPUT_FILE}")
    print(f"  {len(result.stdout)} bytes written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
