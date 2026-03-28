"""
FastAPI backend server for claude-candidate.

Exposes REST endpoints consumed by the Chrome extension and CLI tools.
Manages a local AssessmentStore and serves profile/assessment data.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from claude_candidate import __version__
import claude_candidate.claude_cli as _claude_cli
from claude_candidate.storage import AssessmentStore


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------


class AssessRequest(BaseModel):
	posting_text: str
	company: str
	title: str
	posting_url: str | None = None
	requirements: list[dict[str, Any]] | None = None
	seniority: str = "unknown"
	culture_signals: list[str] | None = None
	tech_stack: list[str] | None = None


class ShortlistAddRequest(BaseModel):
	company_name: str
	job_title: str
	posting_url: str | None = None
	assessment_id: str | None = None
	notes: str | None = None
	salary: str | None = None
	location: str | None = None
	overall_grade: str | None = None


class ShortlistUpdateRequest(BaseModel):
	status: str | None = None
	notes: str | None = None
	assessment_id: str | None = None


class ProofRequest(BaseModel):
	assessment_id: str


class GenerateRequest(BaseModel):
	assessment_id: str
	deliverable_type: str  # "resume_bullets", "cover_letter", "interview_prep"


class AssessFullRequest(BaseModel):
	assessment_id: str


class ExtractPostingRequest(BaseModel):
	url: str
	title: str
	text: str


class PostingExtraction(BaseModel):
	company: str = ""
	title: str = ""
	description: str = ""
	url: str = ""
	source: str = "web"
	location: str | None = None
	seniority: str | None = None
	remote: bool | None = None
	salary: str | None = None
	requirements: list[dict] | None = None


# ---------------------------------------------------------------------------
# URL normalization
# ---------------------------------------------------------------------------

_TRACKING_PARAMS = re.compile(
	r"^(utm_\w+|trk|eBP|trackingId|tracking_id|refId|fbclid|gclid|mc_[ce]id|_hsenc|_hsmi)$",
	re.IGNORECASE,
)


def _normalize_cache_url(url: str) -> str:
	"""Strip tracking params from URLs for cache key stability.

	Job boards and email links append session-specific params that change
	per visit. The path (and any non-tracking params) is the canonical identifier.
	Fragments are always stripped; remaining params are sorted for stable hashing.
	"""
	parsed = urlparse(url)
	if not parsed.query:
		# Still strip fragment for consistency
		return urlunparse(parsed._replace(fragment="")) if parsed.fragment else url
	params = parse_qs(parsed.query, keep_blank_values=True)
	filtered = {k: v for k, v in params.items() if not _TRACKING_PARAMS.match(k)}
	if filtered:
		sorted_items: list[tuple[str, str]] = []
		for key in sorted(filtered.keys()):
			for value in sorted(filtered[key]):
				sorted_items.append((key, value))
		new_query = urlencode(sorted_items)
	else:
		new_query = ""
	return urlunparse(parsed._replace(query=new_query, fragment=""))


# ---------------------------------------------------------------------------
# Education auto-tagging
# ---------------------------------------------------------------------------

_DEGREE_CONTEXT = r"(?:\s+(?:in|or|degree|program|from|required|preferred|equivalent)|\s*[,;/]|$)"

_EDUCATION_PATTERNS: list[tuple[str, re.Pattern]] = [
	("phd", re.compile(r"\b(?:ph\.?d|doctorate|doctoral)\b", re.IGNORECASE)),
	("master", re.compile(r"\b(?:m\.?s\.?c|master'?s?|m\.?eng)\b", re.IGNORECASE)),
	(
		"master",
		re.compile(r"\b(?:m\.?s\.?)" + _DEGREE_CONTEXT, re.IGNORECASE),
	),
	("bachelor", re.compile(r"\b(?:b\.?s\.?c|bachelor'?s?|b\.?eng)\b", re.IGNORECASE)),
	(
		"bachelor",
		re.compile(r"\b(?:b\.?s\.?|b\.?a\.?)" + _DEGREE_CONTEXT, re.IGNORECASE),
	),
]


def _auto_tag_education(requirements: list[dict]) -> None:
	"""Set education_level on requirements that mention degrees but weren't tagged by extraction."""
	for req in requirements:
		if not isinstance(req, dict):
			continue
		if req.get("education_level"):
			continue  # already tagged
		desc = str(req.get("description", ""))
		for level, pattern in _EDUCATION_PATTERNS:
			if pattern.search(desc):
				req["education_level"] = level
				break


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------


def create_app(data_dir: Path | None = None) -> FastAPI:
	"""
	Create and configure the FastAPI application.

	Endpoints are defined inside this function so they capture `store` and
	`profiles` via closure — no global state needed.
	"""
	_data_dir = data_dir or Path.home() / ".claude-candidate"

	# Mutable state shared by lifespan and endpoints via closure
	_state: dict[str, Any] = {
		"store": None,
		"profiles": {},
		"profile_mtimes": {},  # {profile_type: float} — last-read mtime per file
	}

	# Profile files tracked for mtime-based cache invalidation.
	# "merged" is intentionally excluded — the server always builds it on the fly.
	profile_files: dict[str, Path] = {
		"candidate": _data_dir / "candidate_profile.json",
		"resume": _data_dir / "resume_profile.json",
		"curated_resume": _data_dir / "curated_resume.json",
		"repo_profile": _data_dir / "repo_profile.json",
	}

	@asynccontextmanager
	async def lifespan(app: FastAPI):
		# Startup
		_data_dir.mkdir(parents=True, exist_ok=True)
		store = AssessmentStore(_data_dir / "assessments.db")
		await store.initialize()
		_state["store"] = store

		# Pre-load profile JSON files and record their mtimes
		for profile_type, profile_path in profile_files.items():
			try:
				mtime = profile_path.stat().st_mtime
			except OSError:
				continue
			try:
				_state["profiles"][profile_type] = json.loads(profile_path.read_text())
				_state["profile_mtimes"][profile_type] = mtime
			except (json.JSONDecodeError, OSError):
				pass

		yield

		# Shutdown
		if _state["store"] is not None:
			await _state["store"].close()
			_state["store"] = None

	app = FastAPI(
		title="claude-candidate",
		version=__version__,
		lifespan=lifespan,
	)

	app.add_middleware(
		CORSMiddleware,
		allow_origin_regex=r"(chrome-extension://.*|http://localhost.*)",
		allow_credentials=True,
		allow_methods=["*"],
		allow_headers=["*"],
	)

	# ------------------------------------------------------------------
	# Helper accessors (closures over _state)
	# ------------------------------------------------------------------

	def get_store() -> AssessmentStore:
		store = _state["store"]
		if store is None:
			raise HTTPException(status_code=503, detail="Store not initialized")
		return store

	def get_profiles() -> dict[str, Any]:
		"""Return cached profiles, reloading any file whose mtime has changed.

		Cost: one os.stat() per tracked file per call (~10 µs total).
		File data is re-read only when the mtime is newer than last load.
		"""
		for profile_type, profile_path in profile_files.items():
			try:
				current_mtime = profile_path.stat().st_mtime_ns
			except OSError:
				# File deleted or inaccessible — remove from cache
				_state["profiles"].pop(profile_type, None)
				_state["profile_mtimes"].pop(profile_type, None)
				continue
			cached_mtime = _state["profile_mtimes"].get(profile_type)
			if cached_mtime is None or current_mtime != cached_mtime:
				try:
					_state["profiles"][profile_type] = json.loads(profile_path.read_text())
					_state["profile_mtimes"][profile_type] = current_mtime
				except (json.JSONDecodeError, OSError) as exc:
					logger.warning(
						"Failed to reload %s profile from %s: %s — keeping stale data",
						profile_type,
						profile_path,
						exc,
					)
		return _state["profiles"]

	def _profile_hash(data: dict[str, Any]) -> str:
		return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:16]

	def _build_merged_profile():
		"""Build a MergedEvidenceProfile using the best available evidence.

		Precedence:
		  1. curated_resume + repo_profile → merge_triad() [v0.7 primary]
		  2. curated_resume + candidate_profile → merge_with_curated() [fallback]
		  3. resume_profile + candidate_profile → merge_profiles()
		  4. candidate_profile only → merge_candidate_only()

		merge_triad does NOT require a CandidateProfile (sessions are parked
		in v0.7), so it can produce a merged profile even without one.
		"""
		from claude_candidate.schemas.candidate_profile import CandidateProfile
		from claude_candidate.schemas.resume_profile import ResumeProfile
		from claude_candidate.schemas.curated_resume import CuratedResume
		from claude_candidate.schemas.repo_profile import RepoProfile
		from claude_candidate.merger import (
			merge_profiles,
			merge_candidate_only,
			merge_triad,
			merge_with_curated,
		)
		from pydantic import ValidationError

		profiles = get_profiles()

		# Try v0.7 primary path: curated_resume + repo_profile → merge_triad
		curated_data = profiles.get("curated_resume")
		repo_data = profiles.get("repo_profile")

		if curated_data and repo_data:
			try:
				curated = CuratedResume.model_validate(
					curated_data if isinstance(curated_data, dict) else curated_data.model_dump()
				)
				repo = RepoProfile.model_validate(repo_data)
				# Load sessions for culture fit (best-effort)
				sessions = None
				candidate_data = profiles.get("candidate")
				if candidate_data:
					try:
						sessions = CandidateProfile.model_validate(candidate_data)
					except Exception:
						pass  # sessions are best-effort
				logger.info(
					f"merge path: merge_triad (curated_resume + repo_profile"
					f"{' + sessions' if sessions else ''})"
				)
				return merge_triad(curated, repo, sessions=sessions)
			except ValidationError:
				logger.warning("merge_triad validation failed — falling back to legacy path")

		# Fallback: need a candidate profile for older merge paths
		candidate_data = profiles.get("candidate")
		if candidate_data is None:
			# Without candidate profile AND without triad data, nothing to merge
			return None

		cp = CandidateProfile.model_validate(candidate_data)

		# Fallback 2: curated_resume + candidate_profile → merge_with_curated
		if curated_data:
			try:
				curated = CuratedResume.model_validate(
					curated_data if isinstance(curated_data, dict) else curated_data.model_dump()
				)
				logger.info("merge path: merge_with_curated (curated_resume + sessions)")
				return merge_with_curated(cp, curated)
			except ValidationError:
				pass  # fall through to resume_profile or candidate_only

		# Fallback 3: resume_profile + candidate_profile → merge_profiles
		resume_data = profiles.get("resume")
		if resume_data:
			logger.info("merge path: merge_profiles (resume_profile + sessions)")
			rp = ResumeProfile.model_validate(resume_data)
			return merge_profiles(cp, rp)

		# Fallback 4: sessions only
		logger.info("merge path: merge_candidate_only (sessions only)")
		return merge_candidate_only(cp)

	# ------------------------------------------------------------------
	# Health
	# ------------------------------------------------------------------

	@app.get("/api/health")
	async def health():
		profiles = get_profiles()
		profile_loaded = bool(profiles.get("curated_resume") or profiles.get("candidate"))
		return {
			"status": "ok",
			"version": __version__,
			"profile_loaded": profile_loaded,
		}

	# ------------------------------------------------------------------
	# Profile status
	# ------------------------------------------------------------------

	@app.get("/api/profile/status")
	async def profile_status():
		profiles = get_profiles()
		hashes: dict[str, str] = {}

		candidate_data = profiles.get("candidate")
		resume_data = profiles.get("resume")
		curated_data = profiles.get("curated_resume")
		repo_data = profiles.get("repo_profile")

		if candidate_data:
			hashes["candidate"] = _profile_hash(candidate_data)
		if resume_data:
			hashes["resume"] = _profile_hash(resume_data)
		if curated_data:
			hashes["curated_resume"] = _profile_hash(curated_data)
		if repo_data:
			hashes["repo_profile"] = _profile_hash(repo_data)

		# merge_available: true when triad path (curated + repo) or
		# legacy path (candidate profile) can produce a merged profile.
		# Note: this is a best-effort heuristic based on file presence.
		# _build_merged_profile() may fall back to a different path if
		# validation fails (e.g. malformed curated_resume or repo_profile).
		triad_available = curated_data is not None and repo_data is not None
		legacy_available = candidate_data is not None

		return {
			"has_candidate_profile": candidate_data is not None,
			"has_resume_profile": resume_data is not None,
			"has_curated_resume": curated_data is not None,
			"has_repo_profile": repo_data is not None,
			"merge_available": triad_available or legacy_available,
			"merge_path": (
				"merge_triad"
				if triad_available
				else "merge_with_curated"
				if curated_data and legacy_available
				else "merge_profiles"
				if resume_data and legacy_available
				else "merge_candidate_only"
				if legacy_available
				else "none"
			),
			"hashes": hashes,
		}

	# ------------------------------------------------------------------
	# Assess
	# ------------------------------------------------------------------

	async def _run_quick_assess(req: AssessRequest) -> dict[str, Any]:
		"""
		Run QuickMatchEngine (local-only, no Claude calls) and persist the result.

		Returns the assessment dict. Raises HTTPException on missing profile
		or missing requirements.
		"""
		from claude_candidate.schemas.job_requirements import QuickRequirement
		from claude_candidate.scoring import QuickMatchEngine

		store = get_store()

		merged = _build_merged_profile()
		if merged is None:
			raise HTTPException(
				status_code=422,
				detail="No candidate profile loaded. Place candidate_profile.json in the data directory.",
			)

		# Build requirements — filter out invalid entries from Claude
		requirements = []
		if req.requirements:
			for r in req.requirements:
				try:
					requirements.append(QuickRequirement(**r))
				except Exception:
					continue  # Skip malformed requirements

		if not requirements:
			raise HTTPException(
				status_code=422,
				detail="No valid requirements provided — extraction required before assessment.",
			)

		# Load curated eligibility for gate evaluation
		from claude_candidate.schemas.curated_resume import CandidateEligibility
		from pydantic import ValidationError

		curated_eligibility: CandidateEligibility | None = None
		curated_data = get_profiles().get("curated_resume")
		if isinstance(curated_data, dict):
			try:
				curated_eligibility = CandidateEligibility.model_validate(
					curated_data.get("eligibility", {})
				)
			except ValidationError:
				logger.debug("Could not parse curated eligibility — using defaults")

		# Run assessment
		engine = QuickMatchEngine(merged)
		assessment = engine.assess(
			requirements=requirements,
			company=req.company,
			title=req.title,
			posting_url=req.posting_url,
			source="api",
			seniority=req.seniority,
			culture_signals=req.culture_signals,
			tech_stack=req.tech_stack,
			curated_eligibility=curated_eligibility,
		)

		# Persist
		assessment_dict = json.loads(assessment.to_json())
		# Store input requirements for future reassessment
		assessment_dict["input_requirements"] = [r.model_dump() for r in requirements]
		assessment_dict["input_meta"] = {
			"company": req.company,
			"title": req.title,
			"posting_url": req.posting_url,
			"seniority": req.seniority,
			"culture_signals": req.culture_signals,
			"tech_stack": req.tech_stack,
		}
		flat: dict[str, Any] = {
			"assessment_id": assessment.assessment_id,
			"assessed_at": assessment.assessed_at.isoformat(),
			"job_title": assessment.job_title,
			"company_name": assessment.company_name,
			"posting_url": assessment.posting_url,
			"overall_score": assessment.overall_score,
			"overall_grade": assessment.overall_grade,
			"should_apply": assessment.should_apply,
			"data": assessment_dict,
		}
		await store.save_assessment(flat)

		return assessment_dict

	@app.post("/api/assess")
	async def assess(req: AssessRequest):
		return await _run_quick_assess(req)

	@app.post("/api/assess/partial")
	async def assess_partial(req: AssessRequest):
		"""
		Fast partial assessment using local QuickMatchEngine only (no Claude calls).

		Returns the assessment immediately. Callers can subsequently POST to
		/api/assess/full with the returned assessment_id to generate deliverables.
		"""
		return await _run_quick_assess(req)

	@app.post("/api/assess/full")
	async def assess_full(req: AssessFullRequest):
		"""
		Enrich a partial assessment with mission/culture scoring and company research.

		Runs company research (cached per company), loads pre-computed AI
		engineering scores from the candidate profile, computes mission and
		culture dimensions locally, recomputes the overall score across all
		five dimensions, and sets ``assessment_phase = "full"``.

		Does NOT generate deliverables — use ``/api/generate`` for that.
		"""
		import asyncio
		from datetime import datetime

		from claude_candidate.schemas.company_profile import CompanyProfile
		from claude_candidate.schemas.fit_assessment import (
			score_to_grade,
			score_to_verdict,
		)
		from claude_candidate.scoring import QuickMatchEngine

		store = get_store()
		row = await store.get_assessment(req.assessment_id)
		if row is None:
			raise HTTPException(status_code=404, detail="Assessment not found")

		data = row["data"] if row.get("data") and isinstance(row["data"], dict) else row
		company = data.get("company_name", "")

		# 1. Company research (cached per company, best-effort)
		research = None
		if company:
			cached = await store.get_cached_company_research(company)
			if cached:
				research = cached
			else:
				from claude_candidate.company_research import research_company

				loop = asyncio.get_event_loop()
				try:
					result = await loop.run_in_executor(None, lambda: research_company(company))
					await store.cache_company_research(company, result)
					research = result
				except Exception:
					pass  # Company research is best-effort

		# 2. AI engineering scores from candidate profile (pre-computed)
		profiles = get_profiles()
		candidate_data = profiles.get("candidate")
		ai_scores = None
		if candidate_data:
			ai_scores = candidate_data.get("ai_engineering_scores")

		# 3. Build a CompanyProfile from research data (if available)
		company_profile = None
		if research:
			# Determine enrichment quality based on available fields
			field_count = sum(
				1
				for k in (
					"mission",
					"values",
					"culture_signals",
					"tech_philosophy",
					"product_domains",
				)
				if research.get(k)
			)
			if field_count >= 4:
				quality = "rich"
			elif field_count >= 2:
				quality = "moderate"
			else:
				quality = "sparse"

			company_profile = CompanyProfile(
				company_name=company,
				mission_statement=research.get("mission"),
				product_description=research.get("mission") or f"{company} company",
				product_domain=research.get("product_domains") or [],
				tech_stack_public=research.get("tech_stack", []),
				culture_keywords=research.get("culture_signals") or [],
				company_size=research.get("team_size_signal"),
				enriched_at=datetime.now(),
				enrichment_quality=quality,
			)

		# 4. Build merged profile and engine to compute mission/culture
		merged_profile = _build_merged_profile()

		mission_dim = None
		culture_dim = None
		if merged_profile:
			engine = QuickMatchEngine(merged_profile)

			# Extract tech_stack and culture_signals from the existing assessment data
			tech_stack = data.get("skill_match", {}).get("details", [])
			# Use culture signals from company research or empty list
			culture_signals = research.get("culture_signals", []) if research else []

			mission_dim = engine._score_mission_alignment(
				company=company,
				tech_stack=company_profile.tech_stack_public if company_profile else [],
				company_profile=company_profile,
			)
			culture_dim = engine._score_culture_fit(
				culture_signals=culture_signals,
				company_profile=company_profile,
			)

		# 5. Recompute overall score with all five dimensions
		# Parse existing dimension scores from the assessment data
		skill_score = data.get("skill_match", {}).get("score", 0.5)
		experience_score = (data.get("experience_match") or {}).get("score")
		education_score = (data.get("education_match") or {}).get("score")
		mission_score = mission_dim.score if mission_dim else 0.5
		culture_score = culture_dim.score if culture_dim else 0.5

		# Full assessment weights: skill 40%, experience 20%, education 10%,
		# mission 15%, culture 15%
		weighted_total = skill_score * 0.40
		weighted_total += (experience_score if experience_score is not None else 0.5) * 0.20
		weighted_total += (education_score if education_score is not None else 0.5) * 0.10
		weighted_total += mission_score * 0.15
		weighted_total += culture_score * 0.15

		overall_score = round(min(max(weighted_total, 0.0), 1.0), 3)
		overall_grade = score_to_grade(overall_score)

		# Re-apply eligibility hard cap — unmet gates override the recomputed score regardless of dimension weights
		stored_gates = data.get("eligibility_gates", [])
		if any(g.get("status") == "unmet" for g in stored_gates):
			overall_score = 0.0
			overall_grade = "F"

		# Update dimension weights in the returned data
		if mission_dim:
			mission_dim.weight = 0.15
		if culture_dim:
			culture_dim.weight = 0.15

		# 5b. Narrative verdict + receptivity signal (best-effort)
		narrative_result = None
		try:
			from claude_candidate.generator import generate_narrative_verdict

			loop = asyncio.get_event_loop()
			# Build a snapshot of assessment context for the narrative prompt
			_narrative_assessment = dict(data)
			_narrative_assessment["overall_grade"] = overall_grade
			narrative_result = await loop.run_in_executor(
				None,
				lambda: generate_narrative_verdict(_narrative_assessment, research or {}),
			)
		except Exception:
			pass  # Narrative is best-effort

		# 6. Merge into updated assessment data
		updated = dict(data)
		updated["assessment_phase"] = "full"
		updated["overall_score"] = overall_score
		updated["overall_grade"] = overall_grade
		updated["should_apply"] = score_to_verdict(overall_score)
		if mission_dim:
			updated["mission_alignment"] = mission_dim.model_dump()
		if culture_dim:
			updated["culture_fit"] = culture_dim.model_dump()
		if ai_scores:
			updated["ai_engineering_scores"] = ai_scores
		if narrative_result:
			updated["narrative_verdict"] = narrative_result.get("narrative")
			updated["receptivity_level"] = narrative_result.get("receptivity")
			updated["receptivity_reason"] = narrative_result.get("receptivity_reason")

		# Update skill/experience/education weights for consistency
		if updated.get("skill_match"):
			updated["skill_match"]["weight"] = 0.40
		if updated.get("experience_match"):
			updated["experience_match"]["weight"] = 0.20
		if updated.get("education_match"):
			updated["education_match"]["weight"] = 0.10

		# 7. Save updated assessment to store
		flat: dict[str, Any] = {
			"assessment_id": data.get("assessment_id", req.assessment_id),
			"assessed_at": data.get("assessed_at"),
			"job_title": data.get("job_title"),
			"company_name": company,
			"posting_url": data.get("posting_url"),
			"overall_score": overall_score,
			"overall_grade": overall_grade,
			"should_apply": updated["should_apply"],
			"data": updated,
		}
		await store.save_assessment(flat)

		return updated

	# ------------------------------------------------------------------
	# Assessment list / detail / delete
	# ------------------------------------------------------------------

	@app.get("/api/assessments")
	async def list_assessments(
		limit: int = Query(default=50, ge=1, le=200),
		offset: int = Query(default=0, ge=0),
	):
		store = get_store()
		rows = await store.list_assessments(limit=limit, offset=offset)
		# Return the full nested data where available, otherwise the flat row
		results = []
		for row in rows:
			if row.get("data") and isinstance(row["data"], dict):
				results.append(row["data"])
			else:
				results.append(row)
		return results

	@app.get("/api/assessments/{assessment_id}")
	async def get_assessment(assessment_id: str):
		store = get_store()
		row = await store.get_assessment(assessment_id)
		if row is None:
			raise HTTPException(status_code=404, detail="Assessment not found")
		if row.get("data") and isinstance(row["data"], dict):
			return row["data"]
		return row

	@app.delete("/api/assessments/{assessment_id}")
	async def delete_assessment(assessment_id: str):
		store = get_store()
		deleted = await store.delete_assessment(assessment_id)
		if not deleted:
			raise HTTPException(status_code=404, detail="Assessment not found")
		return {"deleted": True, "assessment_id": assessment_id}

	# ------------------------------------------------------------------
	# Bulk reassess
	# ------------------------------------------------------------------

	@app.post("/api/assessments/reassess")
	async def reassess_all():
		"""Re-score all assessments against the current profile and engine."""
		import asyncio
		from claude_candidate.schemas.job_requirements import QuickRequirement
		from claude_candidate.scoring import QuickMatchEngine
		from claude_candidate.requirement_parser import CACHE_PROMPT_VERSION
		from claude_candidate.schemas.curated_resume import CandidateEligibility
		from pydantic import ValidationError

		merged = _build_merged_profile()
		if merged is None:
			raise HTTPException(status_code=422, detail="No profile loaded.")

		# Load curated eligibility once
		curated_eligibility: CandidateEligibility | None = None
		curated_data = get_profiles().get("curated_resume")
		if isinstance(curated_data, dict):
			try:
				curated_eligibility = CandidateEligibility.model_validate(
					curated_data.get("eligibility", {})
				)
			except ValidationError:
				pass

		store = get_store()
		all_assessments = await store.list_assessments(limit=1000)

		# Pre-fetch posting cache for fallback requirement recovery
		cached_postings = await store.list_cached_postings(limit=1000)
		posting_cache_by_hash: dict[str, dict] = {}
		posting_cache_by_url: dict[str, dict] = {}
		for cp in cached_postings:
			posting_cache_by_hash[cp["url_hash"]] = cp.get("data", {})
			# Also index by normalized URL for version-agnostic lookup
			url = cp.get("url", "")
			if url:
				posting_cache_by_url[url] = cp.get("data", {})

		def _resolve_requirements(data: dict) -> list[QuickRequirement] | None:
			"""Try to recover requirements from assessment data or posting cache."""
			# Path 1: stored input_requirements
			input_reqs = data.get("input_requirements")
			if input_reqs and isinstance(input_reqs, list):
				reqs = []
				for r in input_reqs:
					try:
						reqs.append(QuickRequirement(**r))
					except Exception:
						continue
				if reqs:
					return reqs

			# Path 2: posting cache fallback (by hash, then by normalized URL)
			posting_url = data.get("posting_url")
			if posting_url:
				cache_url = _normalize_cache_url(posting_url)
				url_hash = hashlib.sha256(
					f"{CACHE_PROMPT_VERSION}:{cache_url}".encode()
				).hexdigest()[:16]
				cached = posting_cache_by_hash.get(url_hash)
				# Fallback: match by normalized URL (ignores cache version)
				if not cached:
					cached = posting_cache_by_url.get(cache_url)
				if cached and isinstance(cached.get("requirements"), list):
					reqs = []
					for r in cached["requirements"]:
						try:
							reqs.append(QuickRequirement(**r))
						except Exception:
							continue
					if reqs:
						return reqs

			return None

		def _run_batch():
			"""CPU-bound: score all assessments. Runs in executor thread."""
			engine = QuickMatchEngine(merged)
			results = []
			for a in all_assessments:
				aid = a.get("assessment_id", "")
				data = a.get("data", {})
				old_grade = data.get("overall_grade", "?")
				old_score = data.get("overall_score", 0)

				reqs = _resolve_requirements(data)
				if reqs is None:
					results.append({
						"assessment_id": aid,
						"status": "skipped",
						"reason": "no_requirements",
						"company": data.get("company_name", ""),
						"title": data.get("job_title", ""),
					})
					continue

				meta = data.get("input_meta") or {}
				assessment = engine.assess(
					requirements=reqs,
					company=meta.get("company") or data.get("company_name", ""),
					title=meta.get("title") or data.get("job_title", ""),
					posting_url=meta.get("posting_url") or data.get("posting_url"),
					source="reassess",
					seniority=meta.get("seniority", "unknown"),
					culture_signals=meta.get("culture_signals"),
					tech_stack=meta.get("tech_stack"),
					curated_eligibility=curated_eligibility,
				)

				new_dict = json.loads(assessment.to_json())
				# Store recovered requirements so future reassessments don't need cache
				new_dict["input_requirements"] = [r.model_dump() for r in reqs]
				new_dict["input_meta"] = meta if meta else {
					"company": data.get("company_name", ""),
					"title": data.get("job_title", ""),
					"posting_url": data.get("posting_url"),
					"seniority": "unknown",
				}

				results.append({
					"assessment_id": aid,
					"status": "updated",
					"company": assessment.company_name,
					"title": assessment.job_title,
					"old_grade": old_grade,
					"new_grade": assessment.overall_grade,
					"old_score": old_score,
					"new_score": assessment.overall_score,
					"changed": old_grade != assessment.overall_grade,
					"_full": new_dict,  # used for persistence, stripped before response
				})
			return results

		loop = asyncio.get_event_loop()
		results = await loop.run_in_executor(None, _run_batch)

		# Batch persist updated assessments
		updated = 0
		for r in results:
			if r["status"] != "updated":
				continue
			full = r.pop("_full")
			flat = {
				"assessment_id": r["assessment_id"],
				"assessed_at": full.get("assessed_at"),
				"job_title": r["title"],
				"company_name": r["company"],
				"posting_url": full.get("posting_url"),
				"overall_score": r["new_score"],
				"overall_grade": r["new_grade"],
				"should_apply": full.get("should_apply"),
				"data": full,
			}
			await store.save_assessment(flat)
			updated += 1

		skipped = sum(1 for r in results if r["status"] == "skipped")
		changed = sum(1 for r in results if r.get("changed"))

		return {
			"total": len(results),
			"updated": updated,
			"skipped": skipped,
			"changed": changed,
			"results": results,  # lightweight summaries (no _full)
		}

	# ------------------------------------------------------------------
	# Proof package
	# ------------------------------------------------------------------

	@app.post("/api/proof")
	async def generate_proof(req: ProofRequest):
		from claude_candidate.schemas.fit_assessment import FitAssessment
		from claude_candidate.proof_generator import generate_proof_package

		store = get_store()
		row = await store.get_assessment(req.assessment_id)
		if row is None:
			raise HTTPException(status_code=404, detail="Assessment not found")

		data = row["data"] if row.get("data") and isinstance(row["data"], dict) else row
		assessment = FitAssessment.model_validate(data)
		proof_markdown = generate_proof_package(assessment=assessment)
		return {"proof_package": proof_markdown}

	# ------------------------------------------------------------------
	# Deliverable generation
	# ------------------------------------------------------------------

	@app.post("/api/generate")
	async def generate_deliverable(req: GenerateRequest):
		from claude_candidate.schemas.fit_assessment import FitAssessment
		from claude_candidate.generator import (
			generate_resume_bullets,
			generate_cover_letter,
			generate_interview_prep,
		)

		store = get_store()
		row = await store.get_assessment(req.assessment_id)
		if row is None:
			raise HTTPException(status_code=404, detail="Assessment not found")

		data = row["data"] if row.get("data") and isinstance(row["data"], dict) else row
		assessment = FitAssessment.from_json(json.dumps(data))

		if req.deliverable_type == "resume_bullets":
			result = generate_resume_bullets(assessment=assessment)
			return {"deliverable_type": req.deliverable_type, "result": result}
		elif req.deliverable_type == "cover_letter":
			result = generate_cover_letter(assessment=assessment)
			return {"deliverable_type": req.deliverable_type, "result": result}
		elif req.deliverable_type == "interview_prep":
			result = generate_interview_prep(assessment=assessment)
			return {"deliverable_type": req.deliverable_type, "result": result}
		else:
			raise HTTPException(
				status_code=422,
				detail=f"Unknown deliverable_type: {req.deliverable_type!r}. "
				"Must be one of: resume_bullets, cover_letter, interview_prep",
			)

	# ------------------------------------------------------------------
	# Shortlist
	# ------------------------------------------------------------------

	@app.post("/api/shortlist", status_code=201)
	async def add_shortlist(req: ShortlistAddRequest):
		store = get_store()

		# Dedup: if posting_url already exists, update assessment linkage and return existing.
		# Only assessment_id is updateable via dedup; other fields retain their original values.
		# Normalize URL to match variants (tracking params, trailing slashes, fragments).
		if req.posting_url:
			normalized_url = _normalize_cache_url(req.posting_url)
			existing = await store.find_shortlist_by_url(normalized_url)
			if existing:
				if req.assessment_id and req.assessment_id != existing.get("assessment_id"):
					await store.update_shortlist(
						existing["id"], assessment_id=req.assessment_id
					)
					existing["assessment_id"] = req.assessment_id
				return {
					"id": existing["id"],
					"company_name": existing.get("company_name", ""),
					"job_title": existing.get("job_title", ""),
					"posting_url": existing.get("posting_url", ""),
					"assessment_id": existing.get("assessment_id"),
					"notes": existing.get("notes"),
					"status": existing.get("status", "shortlisted"),
					"salary": existing.get("salary"),
					"location": existing.get("location"),
					"overall_grade": existing.get("overall_grade"),
					"already_exists": True,
				}

		normalized_url = _normalize_cache_url(req.posting_url) if req.posting_url else req.posting_url
		sid = await store.add_to_shortlist(
			company_name=req.company_name,
			job_title=req.job_title,
			posting_url=normalized_url,
			assessment_id=req.assessment_id,
			notes=req.notes,
			salary=req.salary,
			location=req.location,
			overall_grade=req.overall_grade,
		)
		return {
			"id": sid,
			"company_name": req.company_name,
			"job_title": req.job_title,
			"posting_url": normalized_url,
			"assessment_id": req.assessment_id,
			"notes": req.notes,
			"status": "shortlisted",
			"salary": req.salary,
			"location": req.location,
			"overall_grade": req.overall_grade,
		}

	@app.get("/api/shortlist")
	async def list_shortlist(
		status: str | None = Query(default=None),
		limit: int = Query(default=50, ge=1, le=200),
	):
		store = get_store()
		return await store.list_shortlist(status=status, limit=limit)

	@app.get("/api/shortlist/enriched")
	async def list_shortlist_enriched(
		status: str | None = Query(default=None),
		limit: int = Query(default=50, ge=1, le=200),
	):
		store = get_store()
		return await store.list_shortlist_enriched(status=status, limit=limit)

	@app.patch("/api/shortlist/{shortlist_id}")
	async def update_shortlist(shortlist_id: int, req: ShortlistUpdateRequest):
		store = get_store()
		updated = await store.update_shortlist(
			shortlist_id=shortlist_id,
			status=req.status,
			notes=req.notes,
			assessment_id=req.assessment_id,
		)
		if not updated:
			raise HTTPException(status_code=404, detail="Shortlist entry not found")
		return {"updated": True, "id": shortlist_id}

	@app.delete("/api/shortlist/{shortlist_id}")
	async def delete_shortlist(shortlist_id: int):
		store = get_store()
		removed = await store.remove_from_shortlist(shortlist_id)
		if not removed:
			raise HTTPException(status_code=404, detail="Shortlist entry not found")
		return {"deleted": True, "id": shortlist_id}

	# ------------------------------------------------------------------
	# Extract posting
	# ------------------------------------------------------------------

	def _infer_source(url: str) -> str:
		lower = url.lower()
		if "linkedin.com" in lower:
			return "linkedin"
		if "greenhouse.io" in lower:
			return "greenhouse"
		if "lever.co" in lower:
			return "lever"
		if "indeed.com" in lower:
			return "indeed"
		return "web"

	@app.post("/api/extract-posting")
	async def extract_posting(req: ExtractPostingRequest):
		from claude_candidate.requirement_parser import (
			extract_posting_with_claude,
			CACHE_PROMPT_VERSION,
		)

		store = get_store()
		cache_url = _normalize_cache_url(req.url)
		url_hash = hashlib.sha256(f"{CACHE_PROMPT_VERSION}:{cache_url}".encode()).hexdigest()[:16]

		cached = await store.get_cached_posting(url_hash)
		if cached is not None:
			logger.info("extract-posting cache hit: %s", cache_url[:80])
			return cached

		if not _claude_cli.check_claude_available():
			logger.warning("extract-posting: Claude CLI not available")
			raise HTTPException(status_code=503, detail="Claude CLI not available for extraction")

		import asyncio

		logger.info("extract-posting: extracting %s (%d chars)", cache_url[:80], len(req.text))
		try:
			parsed = await asyncio.get_event_loop().run_in_executor(
				None, lambda: extract_posting_with_claude(req.title, req.text)
			)
		except _claude_cli.ClaudeCLIError as exc:
			logger.warning("extract-posting: Claude CLI error for %s: %s", cache_url[:80], exc)
			raise HTTPException(status_code=503, detail=f"Claude CLI error: {exc}") from exc
		except (json.JSONDecodeError, ValueError) as exc:
			logger.warning("extract-posting: invalid JSON from Claude for %s", cache_url[:80])
			raise HTTPException(
				status_code=502,
				detail="Extraction failed: invalid response from Claude",
			) from exc

		# Auto-tag education (server-specific post-processing)
		if "requirements" in parsed and isinstance(parsed["requirements"], list):
			_auto_tag_education(parsed["requirements"])

		if "requirements" not in parsed:
			logger.info(
				"extract-posting: Claude response missing requirements field for %s",
				cache_url[:80],
			)
		elif not isinstance(parsed["requirements"], list):
			logger.warning(
				"extract-posting: Claude returned non-list requirements for %s",
				cache_url[:80],
			)
		elif len(parsed["requirements"]) == 0:
			logger.warning("extract-posting: Claude returned 0 requirements for %s", cache_url[:80])
		else:
			logger.info(
				"extract-posting: extracted %d requirements for %s",
				len(parsed["requirements"]),
				cache_url[:80],
			)

		# Coerce requirements to list[dict] or None to prevent Pydantic ValidationError
		raw_reqs = parsed.get("requirements")
		if isinstance(raw_reqs, list):
			raw_reqs = [r for r in raw_reqs if isinstance(r, dict)]
		else:
			raw_reqs = None

		source = _infer_source(req.url)
		result = PostingExtraction(
			company=parsed.get("company") or "",
			title=parsed.get("title") or "",
			description=parsed.get("description") or "",
			url=cache_url,
			source=source,
			location=parsed.get("location"),
			seniority=parsed.get("seniority"),
			remote=parsed.get("remote"),
			salary=parsed.get("salary"),
			requirements=raw_reqs,
		)
		result_dict = result.model_dump()
		# Don't cache extractions with 0 requirements — allows immediate retry
		if raw_reqs:
			await store.cache_posting(url_hash, cache_url, result_dict)
		else:
			logger.info(
				"extract-posting: skipping cache write (0 requirements) for %s",
				cache_url[:80],
			)
		return result_dict

	@app.get("/dashboard", response_class=HTMLResponse)
	async def dashboard():
		html_path = Path(__file__).parent / "static" / "dashboard.html"
		return HTMLResponse(html_path.read_text())

	return app
