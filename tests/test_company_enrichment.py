"""Tests for the company enrichment engine — extraction logic and caching."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path


from claude_candidate.schemas.company_profile import CompanyProfile


# ---------------------------------------------------------------------------
# TestExtractCompanyInfo
# ---------------------------------------------------------------------------


class TestExtractCompanyInfo:
	"""Tests for heuristic extraction from page text."""

	def test_company_name_in_result(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = "Acme Corp builds developer tools for modern software teams."
		result = extract_company_info("Acme Corp", text, "https://acmecorp.io")
		assert result["company_name"] == "Acme Corp"

	def test_product_description_non_empty(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = (
			"Acme Corp is the leading platform for continuous delivery. "
			"We help engineering teams ship faster with confidence. "
			"Our tools integrate with every major CI system."
		)
		result = extract_company_info("Acme Corp", text, "https://acmecorp.io")
		assert result.get("product_description"), "product_description should be non-empty"
		assert len(result["product_description"]) > 0

	def test_detects_tech_stack_python(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = "Our backend is built entirely in Python and uses PostgreSQL for storage."
		result = extract_company_info("TechCo", text, "https://techco.io")
		stack = [t.lower() for t in result.get("tech_stack_public", [])]
		assert "python" in stack

	def test_detects_tech_stack_typescript_react(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = (
			"The frontend is a TypeScript + React application with a Kubernetes-based deployment."
		)
		result = extract_company_info("FrontCo", text, "https://frontco.io")
		stack = [t.lower() for t in result.get("tech_stack_public", [])]
		assert "typescript" in stack
		assert "react" in stack

	def test_detects_tech_stack_kubernetes(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = "We run everything on Kubernetes clusters in AWS."
		result = extract_company_info("CloudCo", text, "https://cloudco.io")
		stack = [t.lower() for t in result.get("tech_stack_public", [])]
		assert "kubernetes" in stack

	def test_detects_remote_first_policy(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = "We are a remote-first company. All roles are fully remote."
		result = extract_company_info("RemoteCo", text, "https://remoteco.io")
		assert result.get("remote_policy") == "remote_first"

	def test_detects_hybrid_policy(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = "We offer a flexible hybrid work model from our San Francisco office."
		result = extract_company_info("HybridCo", text, "https://hybridco.io")
		assert result.get("remote_policy") == "hybrid"

	def test_detects_in_office_policy(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = (
			"We believe in in-office collaboration. All employees work from our NYC headquarters."
		)
		result = extract_company_info("OfficeCo", text, "https://officeco.io")
		assert result.get("remote_policy") == "in_office"

	def test_unknown_remote_policy_when_no_signal(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = "We build great software products for enterprise customers."
		result = extract_company_info("GenericCo", text, "https://genericco.io")
		assert result.get("remote_policy") == "unknown"

	def test_detects_product_domain_devtools(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = "Our developer tools help engineering teams write better code."
		result = extract_company_info("DevToolCo", text, "https://devtoolco.io")
		domains = [d.lower() for d in result.get("product_domain", [])]
		assert any("devtools" in d or "developer" in d for d in domains)

	def test_detects_product_domain_ai_ml(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = "We build machine learning infrastructure for AI-powered applications."
		result = extract_company_info("AICo", text, "https://aico.io")
		domains = [d.lower() for d in result.get("product_domain", [])]
		assert any("ai" in d or "ml" in d for d in domains)

	def test_detects_culture_keywords_open_source(self):
		from claude_candidate.company_enrichment import extract_company_info

		text = "We are an open-source company that believes in community-driven development."
		result = extract_company_info("OSCo", text, "https://osco.io")
		keywords = [k.lower() for k in result.get("culture_keywords", [])]
		assert any("open-source" in k or "open source" in k for k in keywords)

	def test_url_added_to_sources(self):
		from claude_candidate.company_enrichment import extract_company_info

		url = "https://example.com/about"
		result = extract_company_info("ExampleCo", "Some text.", url)
		assert url in result.get("sources", [])

	def test_empty_text_returns_sparse_result(self):
		from claude_candidate.company_enrichment import extract_company_info

		result = extract_company_info("EmptyCo", "", "https://emptyco.io")
		assert result["company_name"] == "EmptyCo"
		assert result.get("tech_stack_public", []) == []


# ---------------------------------------------------------------------------
# TestCompanyEnrichmentEngine
# ---------------------------------------------------------------------------


class TestCompanyEnrichmentEngine:
	"""Tests for caching, profile building, and the enrich() orchestration."""

	def _make_profile_dict(self, company_name: str = "TestCo", days_ago: int = 1) -> dict:
		"""Return a JSON-serialisable dict matching CompanyProfile."""
		enriched_at = datetime.now(tz=timezone.utc) - timedelta(days=days_ago)
		return {
			"company_name": company_name,
			"company_url": "https://testco.io",
			"product_description": "Builds amazing things",
			"product_domain": ["developer-tooling"],
			"tech_stack_public": ["python", "react"],
			"culture_keywords": ["remote-first"],
			"remote_policy": "remote_first",
			"enriched_at": enriched_at.isoformat(),
			"sources": ["https://testco.io"],
			"enrichment_quality": "moderate",
			"oss_activity_level": "unknown",
		}

	def test_cache_hit_returns_profile(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		profile_dict = self._make_profile_dict("CacheHitCo", days_ago=1)

		# Manually write the cache file using the engine's own key mechanism
		cache_path = engine._cache_path("CacheHitCo")
		cache_path.write_text(json.dumps(profile_dict))

		result = engine.get_cached("CacheHitCo")
		assert result is not None
		assert isinstance(result, CompanyProfile)
		assert result.company_name == "CacheHitCo"

	def test_cache_miss_returns_none(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		result = engine.get_cached("NonExistentCompany")
		assert result is None

	def test_cache_expiry_returns_none(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		# Write an 8-day-old cache entry (beyond 7-day TTL)
		profile_dict = self._make_profile_dict("OldCo", days_ago=8)
		cache_path = engine._cache_path("OldCo")
		cache_path.write_text(json.dumps(profile_dict))

		result = engine.get_cached("OldCo", max_age_days=7)
		assert result is None

	def test_cache_within_ttl_returned(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		# 6 days old — still within 7-day TTL
		profile_dict = self._make_profile_dict("FreshCo", days_ago=6)
		cache_path = engine._cache_path("FreshCo")
		cache_path.write_text(json.dumps(profile_dict))

		result = engine.get_cached("FreshCo", max_age_days=7)
		assert result is not None
		assert result.company_name == "FreshCo"

	def test_save_cache_writes_file(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		profile = CompanyProfile(
			company_name="SaveTestCo",
			product_description="Saves things",
			product_domain=["fintech"],
			enriched_at=datetime.now(tz=timezone.utc),
			enrichment_quality="sparse",
		)
		engine.save_cache(profile)

		cache_path = engine._cache_path("SaveTestCo")
		assert cache_path.exists()
		data = json.loads(cache_path.read_text())
		assert data["company_name"] == "SaveTestCo"

	def test_build_profile_produces_company_profile(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		info = {
			"company_name": "BuildCo",
			"company_url": "https://buildco.io",
			"product_description": "Builds great things",
			"product_domain": ["developer-tooling"],
			"tech_stack_public": ["python", "typescript", "kubernetes"],
			"culture_keywords": ["remote-first", "open-source"],
			"remote_policy": "remote_first",
			"sources": ["https://buildco.io"],
		}
		profile = engine.build_profile(info)

		assert isinstance(profile, CompanyProfile)
		assert profile.company_name == "BuildCo"
		assert profile.remote_policy == "remote_first"
		assert "python" in profile.tech_stack_public

	def test_build_profile_rich_quality_with_many_signals(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		info = {
			"company_name": "RichCo",
			"product_description": "Rich product description here",
			"product_domain": ["ai-ml"],
			"tech_stack_public": ["python", "react", "kubernetes"],
			"culture_keywords": ["agile", "remote-first"],
			"remote_policy": "remote_first",
			"mission_statement": "Democratize AI for everyone",
			"sources": ["https://richco.io"],
		}
		profile = engine.build_profile(info)
		assert profile.enrichment_quality == "rich"

	def test_build_profile_moderate_quality_with_some_signals(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		info = {
			"company_name": "ModerateCo",
			"product_description": "Something",
			"product_domain": ["fintech"],
			"tech_stack_public": ["go"],  # 1 signal
			"culture_keywords": ["agile"],  # 2nd signal
			"remote_policy": "unknown",
			"sources": [],
		}
		profile = engine.build_profile(info)
		assert profile.enrichment_quality in ("moderate", "rich")

	def test_build_profile_sparse_quality_with_no_signals(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		info = {
			"company_name": "SparseCo",
			"product_description": "",
			"product_domain": [],
			"tech_stack_public": [],
			"culture_keywords": [],
			"remote_policy": "unknown",
			"sources": [],
		}
		profile = engine.build_profile(info)
		assert profile.enrichment_quality == "sparse"

	def test_enrich_returns_profile_without_url(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		# No URL — should degrade gracefully to sparse profile
		profile = engine.enrich("NoUrlCo", company_url=None)

		assert isinstance(profile, CompanyProfile)
		assert profile.company_name == "NoUrlCo"
		assert profile.enrichment_quality == "sparse"

	def test_enrich_uses_cache_on_second_call(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		# Prime the cache manually
		profile_dict = self._make_profile_dict("CachedEnrichCo", days_ago=1)
		cache_path = engine._cache_path("CachedEnrichCo")
		cache_path.write_text(json.dumps(profile_dict))

		result = engine.enrich("CachedEnrichCo", company_url="https://cachedco.io")
		assert result.company_name == "CachedEnrichCo"
		# Should come from cache without a network call
		assert result.enrichment_quality == "moderate"

	def test_cache_key_normalizes_name(self, tmp_path: Path):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=tmp_path)
		key1 = engine._cache_key("Acme Corp")
		key2 = engine._cache_key("  Acme  Corp  ")
		# Both should produce a safe filename
		assert key1 == key2
		# Should not contain spaces
		assert " " not in key1

	def test_default_cache_dir_used_when_none(self):
		from claude_candidate.company_enrichment import CompanyEnrichmentEngine

		engine = CompanyEnrichmentEngine(cache_dir=None)
		# Default should be under ~/.claude-candidate/company_cache
		assert "claude-candidate" in str(engine.cache_dir)
		assert "company_cache" in str(engine.cache_dir)
