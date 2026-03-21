"""
Requirement parser for job postings.

Uses ``claude --print`` CLI for NLP-based extraction of job requirements.
``ClaudeCLIError`` propagates to the caller on CLI failures; only malformed
JSON/ValueError from the response falls back to the keyword parser.
``parse_requirements_fallback()`` remains available for offline / testing use.
"""

from __future__ import annotations

import json

from claude_candidate.claude_cli import call_claude
from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority

CLAUDE_TIMEOUT_SECONDS = 60

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

# Keyword → canonical skill name mapping for fallback
TECH_KEYWORDS: dict[str, list[str]] = {
    "python": ["python"],
    "typescript": ["typescript", "ts"],
    "javascript": ["javascript", "js"],
    "react": ["react", "react.js"],
    "node.js": ["node", "node.js"],
    "docker": ["docker", "containers"],
    "kubernetes": ["kubernetes", "k8s"],
    "aws": ["aws", "amazon web services"],
    "gcp": ["gcp", "google cloud"],
    "postgresql": ["postgresql", "postgres"],
    "git": ["git"],
    "ci/cd": ["ci/cd", "cicd", "continuous integration"],
    "rest-api": ["rest", "api", "restful"],
    "graphql": ["graphql"],
    "machine-learning": ["machine learning", "ml"],
    "llm": ["llm", "large language model"],
    "prompt-engineering": ["prompt engineering", "prompting"],
    "agent": ["agent", "multi-agent", "agentic"],
}

MUST_HAVE_WORDS = {"required", "must", "need", "essential"}
STRONG_PREFERENCE_WORDS = {"preferred", "ideal"}
NICE_TO_HAVE_WORDS = {"bonus", "plus", "nice to have", "optional"}


def parse_requirements_with_claude(posting_text: str) -> list[QuickRequirement]:
    """Parse job requirements using Claude CLI.

    ``ClaudeCLIError`` propagates so callers know the CLI is broken.
    Only malformed JSON / bad-schema responses fall back to the keyword parser,
    because the CLI worked but returned unusable output.
    """
    prompt = PARSE_PROMPT_TEMPLATE.format(posting_text=posting_text)
    raw = call_claude(prompt, timeout=CLAUDE_TIMEOUT_SECONDS)  # raises ClaudeCLIError on failure
    try:
        results = parse_requirements_from_response(raw)
        if results:
            return results
    except (json.JSONDecodeError, ValueError):
        pass
    return parse_requirements_fallback(posting_text)


def _strip_markdown_fences(text: str) -> str:
    """Remove leading/trailing ```json ... ``` or ``` ... ``` wrappers."""
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        # Drop first line (```json or ```) and last line (```)
        inner = lines[1:-1] if lines[-1].strip() == "```" else lines[1:]
        stripped = "\n".join(inner).strip()
    return stripped


def parse_requirements_from_response(response: str) -> list[QuickRequirement]:
    """Parse a Claude JSON response into QuickRequirement objects."""
    try:
        cleaned = _strip_markdown_fences(response)
        data = json.loads(cleaned)
        if not isinstance(data, list):
            return []
        return _validate_requirements(data)
    except (json.JSONDecodeError, ValueError):
        return []


def _validate_requirements(data: list[dict]) -> list[QuickRequirement]:
    """Convert raw dicts to QuickRequirements, skipping any invalid entries."""
    results: list[QuickRequirement] = []
    for item in data:
        try:
            results.append(QuickRequirement(**item))
        except Exception:
            continue
    return results


def parse_requirements_fallback(text: str) -> list[QuickRequirement]:
    """Keyword-based fallback: scan text for tech names and infer priority from context."""
    requirements: list[QuickRequirement] = []
    text_lower = text.lower()
    lines = text_lower.splitlines()

    for tech, keywords in TECH_KEYWORDS.items():
        if not any(kw in text_lower for kw in keywords):
            continue
        priority = _infer_priority(lines, keywords)
        requirements.append(QuickRequirement(
            description=f"Experience with {tech}",
            skill_mapping=[tech],
            priority=priority,
            source_text="",
        ))

    if not requirements:
        requirements.append(QuickRequirement(
            description="General software engineering",
            skill_mapping=["python", "git"],
            priority=RequirementPriority.MUST_HAVE,
            source_text="",
        ))

    return requirements


def _infer_priority(lines: list[str], keywords: list[str]) -> RequirementPriority:
    """Determine requirement priority from surrounding context words."""
    for line in lines:
        if not any(kw in line for kw in keywords):
            continue
        if any(w in line for w in MUST_HAVE_WORDS):
            return RequirementPriority.MUST_HAVE
        if any(w in line for w in STRONG_PREFERENCE_WORDS):
            return RequirementPriority.STRONG_PREFERENCE
        if any(w in line for w in NICE_TO_HAVE_WORDS):
            return RequirementPriority.NICE_TO_HAVE
    return RequirementPriority.NICE_TO_HAVE


_taxonomy_singleton = None


def _get_taxonomy():
    global _taxonomy_singleton
    if _taxonomy_singleton is None:
        from claude_candidate.skill_taxonomy import SkillTaxonomy
        _taxonomy_singleton = SkillTaxonomy.load_default()
    return _taxonomy_singleton


def normalize_skill_mappings(requirements: list[dict], taxonomy=None) -> list[dict]:
    """Normalize skill_mapping entries through the taxonomy.

    Matched entries are replaced with canonical names.
    Unmatched entries are preserved as-is.
    Returns modified requirements list (mutates in place).
    """
    if taxonomy is None:
        taxonomy = _get_taxonomy()

    for req in requirements:
        normalized = []
        for skill_name in req.get("skill_mapping", []):
            canonical = taxonomy.match(skill_name)
            normalized.append(canonical if canonical else skill_name)
        # Deduplicate while preserving order
        seen = set()
        deduped = []
        for name in normalized:
            if name not in seen:
                seen.add(name)
                deduped.append(name)
        req["skill_mapping"] = deduped
    return requirements
