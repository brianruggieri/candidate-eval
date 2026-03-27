"""
Requirement parser for job postings.

Uses ``claude --print`` CLI for NLP-based extraction of job requirements.
``ClaudeCLIError`` propagates to the caller on CLI failures; only malformed
JSON/ValueError from the response falls back to the keyword parser.
``parse_requirements_fallback()`` remains available for offline / testing use.
"""

from __future__ import annotations

import json

import claude_candidate.claude_cli as _claude_cli
from claude_candidate.claude_cli import call_claude
from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority, PRIORITY_WEIGHT

CLAUDE_TIMEOUT_SECONDS = 60

PARSE_PROMPT_TEMPLATE = """\
Extract job requirements from the following job posting as a JSON array.
Each element must have these fields:
  - description: string, concise description of the requirement
  - skill_mapping: non-empty array of lowercase skill/technology strings
  - priority: one of "must_have", "strong_preference", "nice_to_have", "implied"
  - source_text: the verbatim sentence or phrase from the posting
  - is_eligibility: boolean, true ONLY for non-skill logistical/eligibility requirements
    (work authorization, visa sponsorship, travel willingness, language proficiency,
    relocation, security clearance, mission/values alignment statements).
    Set false for technical skills, domain experience, and education requirements.
    Education requirements (bachelor's, master's, PhD) are NOT eligibility — leave
    is_eligibility false and use the education_level field for those.
    If a requirement mixes a skill with an eligibility item, split into two entries.
  - parent_id: string or null. If a requirement mentions multiple distinct skills
    (e.g., 'Python and React'), split it into separate requirements with one skill each.
    Set parent_id to a shared identifier (e.g., 'compound-1') linking all parts of the
    original compound. Simple requirements: parent_id null.

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

MAX_EXTRACTION_TEXT = 15_000
CACHE_PROMPT_VERSION = "v2"  # Bump when prompt changes to invalidate 7-day cache


def build_extraction_prompt(title: str, text: str) -> str:
	"""Build the full posting extraction prompt (company + metadata + requirements).

	Used by both the server (via extract_posting_with_claude) and can be used
	by CLI for full-posting extraction. This is the canonical prompt — do not
	duplicate in server.py.
	"""
	truncated = text[:MAX_EXTRACTION_TEXT]
	return (
		"Extract the job posting from this web page text. "
		"Return ONLY valid JSON with these fields:\n"
		"- company: string (the hiring company name)\n"
		"- title: string (the job title)\n"
		"- description: string (full job description including requirements and qualifications)\n"
		"- location: string or null\n"
		"- seniority: string or null (one of: junior, mid, senior, staff, principal, director)\n"
		"- remote: boolean or null\n"
		"- salary: string or null\n"
		"- requirements: array of objects, each with:\n"
		"  - description: string (human-readable requirement)\n"
		'  - skill_mapping: array of strings (normalized skill names, e.g. ["python", "django"])\n'
		"  - priority: string (one of: must_have, strong_preference, nice_to_have, implied)\n"
		'  - years_experience: integer or null (e.g. 5 for "5+ years")\n'
		'  - education_level: string or null (e.g. "bachelor", "master", "phd")\n'
		"  - source_text: the verbatim sentence or phrase from the posting\n"
		"  - is_eligibility: boolean, true ONLY for non-skill logistical/eligibility requirements\n"
		"    (work authorization, visa sponsorship, travel willingness, language proficiency,\n"
		"    relocation, security clearance, mission/values alignment statements). False for technical\n"
		"    skills, domain experience, and education requirements. Education (bachelor/master/PhD) is\n"
		"    NOT eligibility. Split mixed requirements into separate entries.\n"
		"  - parent_id: string or null. If this requirement was split from a compound requirement\n"
		"    that mentions multiple distinct skills (e.g., '5+ years of Python and React'), set\n"
		"    parent_id to a shared identifier (e.g., 'compound-1') linking all parts. Each split\n"
		"    requirement should have only ONE skill in skill_mapping. Simple single-skill\n"
		"    requirements should have parent_id: null.\n\n"
		"For requirements, extract every qualification, skill, or experience mentioned in the posting. "
		"Use must_have for requirements labeled required/must/essential, "
		"strong_preference for strongly preferred/highly desired, "
		"nice_to_have for preferred/bonus/plus, "
		"and implied for unlabeled qualifications that are clearly expected.\n\n"
		"If this page does not contain a job posting, return all fields as null.\n\n"
		f"Page title: {title}\n"
		f"Page text:\n{truncated}"
	)


def extract_posting_with_claude(title: str, text: str) -> dict:
	"""Extract a full job posting using the canonical extraction prompt.

	Returns a dict with company, title, description, location, seniority,
	remote, salary, and requirements (list of dicts with normalized skill_mapping).

	Raises ClaudeCLIError on CLI failure. Raises ValueError on invalid JSON.
	"""
	prompt = build_extraction_prompt(title, text)
	raw = _claude_cli.call_claude(prompt, timeout=120)

	cleaned = _strip_markdown_fences(raw)
	parsed = json.loads(cleaned)
	if not isinstance(parsed, dict):
		raise ValueError(f"Expected JSON object, got {type(parsed).__name__}")

	# Normalize skill mappings through taxonomy
	if "requirements" in parsed and isinstance(parsed["requirements"], list):
		normalize_skill_mappings(parsed["requirements"])
		# Convert raw dicts to QuickRequirement for weight computation, then back
		validated = _validate_requirements(parsed["requirements"])
		if validated:
			compute_distillation_weights(validated)
			parsed["requirements"] = [r.model_dump() for r in validated]

	return parsed


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
			compute_distillation_weights(results)
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
		requirements.append(
			QuickRequirement(
				description=f"Experience with {tech}",
				skill_mapping=[tech],
				priority=priority,
				source_text="",
			)
		)

	if not requirements:
		requirements.append(
			QuickRequirement(
				description="General software engineering",
				skill_mapping=["python", "git"],
				priority=RequirementPriority.MUST_HAVE,
				source_text="",
			)
		)

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


def compute_distillation_weights(requirements: list[QuickRequirement]) -> list[QuickRequirement]:
	"""Compute weight_override for distilled requirements.

	For requirements sharing a parent_id, weight_override = base_priority_weight / group_size.
	This preserves the total weight of the original compound requirement.
	Requirements without parent_id are left unchanged.

	Mutates in place and returns the list for chaining.
	"""
	groups: dict[str, list[QuickRequirement]] = {}
	for req in requirements:
		if req.parent_id:
			groups.setdefault(req.parent_id, []).append(req)
	for parent_id, group in groups.items():
		priorities = {req.priority for req in group}
		if len(priorities) != 1:
			raise ValueError(
				f"Inconsistent priorities for requirements with parent_id {parent_id!r}: "
				f"{sorted(p.value for p in priorities)}"
			)
		base_weight = PRIORITY_WEIGHT.get(group[0].priority, 1.0)
		override = base_weight / len(group)
		for req in group:
			req.weight_override = override
	return requirements
