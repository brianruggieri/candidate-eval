"""
Company Enrichment Engine

Fetches and heuristically extracts public information about companies
from their web presence. Results are cached locally with a 7-day TTL.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from claude_candidate.schemas.company_profile import CompanyProfile

# ---------------------------------------------------------------------------
# Heuristic keyword tables
# ---------------------------------------------------------------------------

_TECH_KEYWORDS: list[str] = [
	"python",
	"typescript",
	"javascript",
	"react",
	"vue",
	"angular",
	"nodejs",
	"node.js",
	"go",
	"golang",
	"rust",
	"java",
	"kotlin",
	"swift",
	"ruby",
	"rails",
	"php",
	"elixir",
	"scala",
	"clojure",
	"haskell",
	"c++",
	"c#",
	"dotnet",
	".net",
	"kubernetes",
	"k8s",
	"docker",
	"terraform",
	"aws",
	"gcp",
	"azure",
	"postgresql",
	"postgres",
	"mysql",
	"sqlite",
	"mongodb",
	"redis",
	"kafka",
	"graphql",
	"grpc",
	"fastapi",
	"django",
	"flask",
	"nextjs",
	"next.js",
	"spark",
	"airflow",
	"dbt",
	"snowflake",
	"bigquery",
]

_CULTURE_KEYWORDS: list[tuple[str, str]] = [
	# (pattern_in_text, canonical_keyword)
	("remote-first", "remote-first"),
	("remote first", "remote-first"),
	("open-source", "open-source"),
	("open source", "open-source"),
	("agile", "agile"),
	("scrum", "scrum"),
	("devops", "devops"),
	("diversity", "diversity"),
	("inclusion", "inclusion"),
	("work-life balance", "work-life-balance"),
	("work life balance", "work-life-balance"),
	("async", "async-culture"),
	("asynchronous", "async-culture"),
	("fast-paced", "fast-paced"),
	("fast paced", "fast-paced"),
	("startup", "startup"),
	("mission-driven", "mission-driven"),
	("mission driven", "mission-driven"),
	("collaborative", "collaborative"),
	("transparency", "transparency"),
	("flat structure", "flat-structure"),
	("flat organization", "flat-structure"),
]

_REMOTE_SIGNALS: list[tuple[str, str]] = [
	# (pattern, policy)
	(r"remote[-\s]first", "remote_first"),
	(r"fully remote", "remote_first"),
	(r"100% remote", "remote_first"),
	(r"all roles are.*remote", "remote_first"),
	(r"work from anywhere", "remote_first"),
	(r"hybrid", "hybrid"),
	(r"flexible work", "hybrid"),
	(r"in[-\s]office", "in_office"),
	(r"on[-\s]site", "in_office"),
	(r"on site", "in_office"),
	(r"office[-\s]based", "in_office"),
]

_DOMAIN_SIGNALS: list[tuple[str, str]] = [
	# (pattern, domain)
	(r"developer tool", "devtools"),
	(r"devtool", "devtools"),
	(r"developer platform", "devtools"),
	(r"engineering platform", "devtools"),
	(r"machine learning|deep learning|large language model|llm|generative ai|gen\s*ai|nlp", "ai-ml"),
	(r"\bai\b.*(?:platform|tool|product|company)|(?:platform|tool|product|company).*\bai\b", "ai-ml"),
	(r"artificial intelligence", "ai-ml"),
	(r"fintech|financial technology|payments|banking|lending|insurance tech", "fintech"),
	(r"healthcare|health tech|medical|clinical|patient|ehr|emr", "healthcare"),
	(r"security|cybersecurity|infosec|soc\b|siem|zero trust", "security"),
	(r"e[-\s]?commerce|retail tech|marketplace|shopping", "ecommerce"),
	(r"data platform|data infrastructure|data pipeline|analytics platform", "data-infra"),
	(r"cloud infrastructure|infrastructure as code|iac|platform engineering", "cloud-infra"),
	(r"edtech|education technology|learning platform|online learning|lms\b", "edtech"),
	(r"hr tech|human resources|talent management|workforce", "hrtech"),
	(r"martech|marketing technology|adtech|advertising tech", "martech"),
]


# ---------------------------------------------------------------------------
# HTML stripping utility
# ---------------------------------------------------------------------------

def _strip_html(html: str) -> str:
	"""Remove HTML tags and decode common entities from a string."""
	# Remove <script> and <style> blocks entirely
	html = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", html, flags=re.DOTALL | re.IGNORECASE)
	# Remove all remaining tags
	html = re.sub(r"<[^>]+>", " ", html)
	# Decode a handful of common HTML entities
	entities = {
		"&amp;": "&",
		"&lt;": "<",
		"&gt;": ">",
		"&quot;": '"',
		"&#39;": "'",
		"&nbsp;": " ",
		"&ndash;": "-",
		"&mdash;": "-",
	}
	for entity, replacement in entities.items():
		html = html.replace(entity, replacement)
	# Collapse whitespace
	html = re.sub(r"\s+", " ", html).strip()
	return html


# ---------------------------------------------------------------------------
# Public: fetch_page_text
# ---------------------------------------------------------------------------

def fetch_page_text(url: str) -> str:
	"""Fetch *url* with httpx (sync) and return plain text with HTML stripped.

	Returns an empty string on any network or HTTP error.
	"""
	headers = {"User-Agent": "claude-candidate/0.2 (job-search-tool)"}
	try:
		response = httpx.get(url, headers=headers, timeout=15.0, follow_redirects=True)
		response.raise_for_status()
		return _strip_html(response.text)
	except Exception:
		return ""


# ---------------------------------------------------------------------------
# Public: extract_company_info
# ---------------------------------------------------------------------------

def extract_company_info(company_name: str, page_text: str, url: str) -> dict[str, Any]:
	"""Heuristically extract company signals from *page_text*.

	Returns a dict whose keys map to CompanyProfile fields.
	"""
	text_lower = page_text.lower()

	# --- tech stack --------------------------------------------------------
	tech_stack: list[str] = []
	seen_tech: set[str] = set()
	for kw in _TECH_KEYWORDS:
		pattern = re.escape(kw)
		if re.search(r"\b" + pattern + r"\b", text_lower):
			canonical = kw.lower()
			if canonical not in seen_tech:
				tech_stack.append(kw)
				seen_tech.add(canonical)

	# --- culture keywords --------------------------------------------------
	culture_kws: list[str] = []
	seen_culture: set[str] = set()
	for pattern, canonical in _CULTURE_KEYWORDS:
		if pattern.lower() in text_lower and canonical not in seen_culture:
			culture_kws.append(canonical)
			seen_culture.add(canonical)

	# --- remote policy -----------------------------------------------------
	remote_policy = "unknown"
	for pattern, policy in _REMOTE_SIGNALS:
		if re.search(pattern, text_lower):
			remote_policy = policy
			break  # First match wins; more specific patterns come first

	# --- product domain ----------------------------------------------------
	product_domain: list[str] = []
	seen_domain: set[str] = set()
	for pattern, domain in _DOMAIN_SIGNALS:
		if re.search(pattern, text_lower) and domain not in seen_domain:
			product_domain.append(domain)
			seen_domain.add(domain)

	# --- product description -----------------------------------------------
	# Find sentences that mention the company name (case-insensitive).
	# Fall back to the first 2 sentences if no match.
	product_description = ""
	sentences = re.split(r"(?<=[.!?])\s+", page_text)
	name_lower = company_name.lower()
	matching = [s for s in sentences if name_lower in s.lower() and len(s) > 20]
	if matching:
		product_description = " ".join(matching[:2])
	elif sentences:
		product_description = " ".join(s for s in sentences[:2] if s)

	# Trim to a reasonable length
	if len(product_description) > 500:
		product_description = product_description[:500].rsplit(" ", 1)[0]

	return {
		"company_name": company_name,
		"product_description": product_description,
		"product_domain": product_domain,
		"tech_stack_public": tech_stack,
		"culture_keywords": culture_kws,
		"remote_policy": remote_policy,
		"sources": [url] if url else [],
	}


# ---------------------------------------------------------------------------
# CompanyEnrichmentEngine
# ---------------------------------------------------------------------------

class CompanyEnrichmentEngine:
	"""Fetch, extract, and cache company information.

	Parameters
	----------
	cache_dir:
		Directory for JSON cache files. Defaults to
		``~/.claude-candidate/company_cache``.
	"""

	def __init__(self, cache_dir: Path | None = None) -> None:
		if cache_dir is None:
			cache_dir = Path.home() / ".claude-candidate" / "company_cache"
		self.cache_dir: Path = Path(cache_dir)
		self.cache_dir.mkdir(parents=True, exist_ok=True)

	# ------------------------------------------------------------------
	# Cache key / path helpers
	# ------------------------------------------------------------------

	def _cache_key(self, company_name: str) -> str:
		"""Normalise *company_name* to a safe filename key."""
		# Strip leading/trailing whitespace, collapse internal runs
		name = " ".join(company_name.strip().split())
		# Normalise unicode to ASCII
		name = unicodedata.normalize("NFKD", name)
		name = name.encode("ascii", "ignore").decode("ascii")
		# Lower-case, replace non-alphanumeric with underscores, collapse runs
		name = re.sub(r"[^a-z0-9]+", "_", name.lower())
		name = name.strip("_")
		return name

	def _cache_path(self, company_name: str) -> Path:
		return self.cache_dir / f"{self._cache_key(company_name)}.json"

	# ------------------------------------------------------------------
	# Cache I/O
	# ------------------------------------------------------------------

	def get_cached(self, company_name: str, max_age_days: int = 7) -> CompanyProfile | None:
		"""Return a cached CompanyProfile if it exists and is within TTL."""
		path = self._cache_path(company_name)
		if not path.exists():
			return None
		try:
			data = json.loads(path.read_text(encoding="utf-8"))
			profile = CompanyProfile.model_validate(data)
			cutoff = datetime.now(tz=timezone.utc) - timedelta(days=max_age_days)
			enriched_at = profile.enriched_at
			# Ensure tz-aware comparison
			if enriched_at.tzinfo is None:
				enriched_at = enriched_at.replace(tzinfo=timezone.utc)
			if enriched_at < cutoff:
				return None
			return profile
		except Exception:
			return None

	def save_cache(self, profile: CompanyProfile) -> None:
		"""Serialise *profile* to its cache file."""
		path = self._cache_path(profile.company_name)
		path.write_text(profile.model_dump_json(indent=2), encoding="utf-8")

	# ------------------------------------------------------------------
	# Profile building
	# ------------------------------------------------------------------

	def build_profile(self, info: dict[str, Any]) -> CompanyProfile:
		"""Build a CompanyProfile from extracted *info*, computing quality score."""
		# Count distinct signals:
		# tech stack, culture keywords, remote policy (non-unknown),
		# mission statement, product description, product domain
		signals = 0
		if info.get("tech_stack_public"):
			signals += 1
		if info.get("culture_keywords"):
			signals += 1
		if info.get("remote_policy", "unknown") != "unknown":
			signals += 1
		if info.get("mission_statement"):
			signals += 1
		if info.get("product_description"):
			signals += 1
		if info.get("product_domain"):
			signals += 1

		if signals >= 3:
			quality = "rich"
		elif signals >= 1:
			quality = "moderate"
		else:
			quality = "sparse"

		return CompanyProfile(
			company_name=info["company_name"],
			company_url=info.get("company_url"),
			mission_statement=info.get("mission_statement"),
			product_description=info.get("product_description") or "",
			product_domain=info.get("product_domain") or [],
			tech_stack_public=info.get("tech_stack_public") or [],
			culture_keywords=info.get("culture_keywords") or [],
			remote_policy=info.get("remote_policy", "unknown"),
			sources=info.get("sources") or [],
			enriched_at=datetime.now(tz=timezone.utc),
			enrichment_quality=quality,
		)

	# ------------------------------------------------------------------
	# Main entry point
	# ------------------------------------------------------------------

	def enrich(self, company_name: str, company_url: str | None = None) -> CompanyProfile:
		"""Return a CompanyProfile for *company_name*, using cache when available.

		If a fresh cached entry exists it is returned immediately. Otherwise
		the company's website is fetched and heuristically parsed.
		On any failure a sparse profile is returned.
		"""
		# 1. Cache hit?
		cached = self.get_cached(company_name)
		if cached is not None:
			return cached

		# 2. Fetch page text (graceful degradation if no URL or fetch fails)
		page_text = ""
		sources: list[str] = []
		if company_url:
			page_text = fetch_page_text(company_url)
			if page_text:
				sources.append(company_url)

		# 3. Extract heuristic signals
		if page_text:
			info = extract_company_info(company_name, page_text, company_url or "")
		else:
			info = {
				"company_name": company_name,
				"company_url": company_url,
				"product_description": "",
				"product_domain": [],
				"tech_stack_public": [],
				"culture_keywords": [],
				"remote_policy": "unknown",
				"sources": sources,
			}

		info["company_url"] = company_url

		# 4. Build and cache profile
		profile = self.build_profile(info)
		self.save_cache(profile)
		return profile
