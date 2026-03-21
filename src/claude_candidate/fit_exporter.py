"""Export FitAssessment data as Hugo-compatible markdown for the fit landing page."""

from __future__ import annotations

import re

# Seniority prefixes in ascending order. Keep only the highest.
_SENIORITY_PREFIXES = [
	"junior", "jr", "jr.",
	"mid", "mid-level",
	"senior", "sr", "sr.",
	"staff",
	"principal",
	"distinguished",
]

_SENIORITY_MAP = {p: i for i, p in enumerate(_SENIORITY_PREFIXES)}

# Common title normalizations
_TITLE_REPLACEMENTS = {
	"engineering manager": "eng-manager",
	"engineering lead": "eng-lead",
	"full stack": "fullstack",
	"front end": "frontend",
	"front-end": "frontend",
	"back end": "backend",
	"back-end": "backend",
	"director of engineering": "director-engineering",
	"director of": "director",
	"vp of engineering": "vp-engineering",
	"vp of": "vp",
	"head of engineering": "head-engineering",
	"head of": "head",
}

_ROMAN_NUMERALS = {"i", "ii", "iii", "iv", "v", "vi"}

_FILLER_WORDS = {"in", "of", "the", "a", "an", "and", "for", "at", "to", "with"}

_ROLE_NOUNS = {
	"engineer", "developer", "architect", "manager", "lead", "director",
	"designer", "analyst", "scientist", "administrator", "consultant",
}


def generate_slug(title: str, company: str) -> str:
	"""Generate a tight, clean URL slug from job title + company name.

	Rules:
	- Strip seniority prefixes, keep only the highest-level one
	- Strip roman numeral suffixes (I, II, III, IV)
	- Apply common title normalizations (Engineering Manager → eng-manager)
	- Truncate to 2-3 core words
	- Append first word of company name
	- Lowercase, hyphenate
	"""
	title_lower = title.lower().strip()

	# Apply whole-phrase replacements first
	for phrase, replacement in _TITLE_REPLACEMENTS.items():
		if phrase in title_lower:
			title_lower = title_lower.replace(phrase, replacement)

	words = title_lower.split()

	# Strip roman numerals from end
	while words and words[-1] in _ROMAN_NUMERALS:
		words.pop()

	# Extract seniority prefixes
	highest_seniority: str | None = None
	highest_rank = -1
	remaining: list[str] = []

	for word in words:
		clean = word.rstrip(".")
		if clean in _SENIORITY_MAP:
			rank = _SENIORITY_MAP[clean]
			if rank > highest_rank:
				highest_seniority = clean.rstrip(".")
				highest_rank = rank
		else:
			remaining.append(word)

	# Remove filler words
	remaining = [w for w in remaining if w not in _FILLER_WORDS]

	# Build title part
	title_parts: list[str] = []
	keep_seniority = highest_seniority and highest_rank >= _SENIORITY_MAP.get("staff", 0)
	if keep_seniority:
		title_parts.append(highest_seniority)
		# With a seniority prefix, keep only the core role noun
		role_nouns = [w for w in remaining if w in _ROLE_NOUNS]
		if role_nouns:
			remaining = [role_nouns[-1]]
		elif remaining:
			remaining = [remaining[-1]]
	else:
		# Without seniority, truncate to 2 core words
		if len(remaining) > 2:
			remaining = remaining[:2]
	title_parts.extend(remaining)

	# Company: first word, strip special chars (split on non-alphanumeric for "Change.org")
	company_word = re.split(r"[^a-zA-Z0-9]", company.strip().split()[0])[0].lower()

	# Join and clean
	slug = "-".join(title_parts + [company_word])
	slug = re.sub(r"[^a-z0-9-]", "", slug)
	slug = re.sub(r"-+", "-", slug).strip("-")

	return slug
