"""
FastAPI backend server for claude-candidate.

Exposes REST endpoints consumed by the Chrome extension and CLI tools.
Manages a local AssessmentStore and serves profile/assessment data.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
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
		"""Build a MergedEvidenceProfile using the best available resume data.

		Precedence (mirrors CLI's ``_merge_profile``):
		  1. curated_resume.json with ``curated_skills`` → merge_with_curated()
		  2. resume_profile.json → merge_profiles()
		  3. No resume at all → merge_candidate_only()

		Returns None when no candidate profile is loaded.
		"""
		from claude_candidate.schemas.candidate_profile import CandidateProfile
		from claude_candidate.schemas.resume_profile import ResumeProfile
		from claude_candidate.merger import (
			merge_profiles,
			merge_candidate_only,
			merge_with_curated,
		)

		profiles = get_profiles()
		candidate_data = profiles.get("candidate")
		if candidate_data is None:
			return None

		cp = CandidateProfile.model_validate(candidate_data)

		curated_data = profiles.get("curated_resume")
		if curated_data:
			from claude_candidate.schemas.curated_resume import CuratedResume
			from pydantic import ValidationError

			try:
				curated = CuratedResume.model_validate(
					curated_data if isinstance(curated_data, dict) else curated_data.model_dump()
				)
				return merge_with_curated(cp, curated)
			except ValidationError:
				pass  # fall through to resume_profile or candidate_only

		resume_data = profiles.get("resume")
		if resume_data:
			rp = ResumeProfile.model_validate(resume_data)
			return merge_profiles(cp, rp)

		return merge_candidate_only(cp)

	# ------------------------------------------------------------------
	# Health
	# ------------------------------------------------------------------

	@app.get("/api/health")
	async def health():
		profiles = get_profiles()
		profile_loaded = bool(profiles.get("candidate"))
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

		if candidate_data:
			hashes["candidate"] = _profile_hash(candidate_data)
		if resume_data:
			hashes["resume"] = _profile_hash(resume_data)
		if curated_data:
			hashes["curated_resume"] = _profile_hash(curated_data)

		return {
			"has_candidate_profile": candidate_data is not None,
			"has_resume_profile": resume_data is not None,
			"has_curated_resume": curated_data is not None,
			# merge_available: true when a candidate profile is loaded.
			# The server always merges on the fly — no merged_profile.json needed.
			"merge_available": candidate_data is not None,
			"hashes": hashes,
		}

	# ------------------------------------------------------------------
	# Assess
	# ------------------------------------------------------------------

	async def _run_quick_assess(req: AssessRequest) -> dict[str, Any]:
		"""
		Run QuickMatchEngine (local-only, no Claude calls) and persist the result.

		Returns the assessment dict. Raises HTTPException on missing profile.
		"""
		from claude_candidate.schemas.job_requirements import QuickRequirement
		from claude_candidate.quick_match import QuickMatchEngine
		from claude_candidate.cli import _extract_basic_requirements

		store = get_store()

		merged = _build_merged_profile()
		if merged is None:
			raise HTTPException(
				status_code=422,
				detail="No candidate profile loaded. Place candidate_profile.json in the data directory.",
			)

		# Build requirements — filter out invalid entries from Claude
		if req.requirements:
			requirements = []
			for r in req.requirements:
				try:
					requirements.append(QuickRequirement(**r))
				except Exception:
					continue  # Skip malformed requirements
			if not requirements:
				requirements = _extract_basic_requirements(req.posting_text)
		else:
			requirements = _extract_basic_requirements(req.posting_text)

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
		)

		# Persist
		assessment_dict = json.loads(assessment.to_json())
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
		from claude_candidate.quick_match import QuickMatchEngine

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
		sid = await store.add_to_shortlist(
			company_name=req.company_name,
			job_title=req.job_title,
			posting_url=req.posting_url,
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
			"posting_url": req.posting_url,
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

	MAX_EXTRACTION_TEXT = 15_000

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

	def _build_extraction_prompt(title: str, text: str) -> str:
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
			"  - is_eligibility: boolean, true ONLY for non-skill logistical/eligibility requirements\n"
			"    (work authorization, visa sponsorship, travel willingness, language proficiency,\n"
			"    relocation, security clearance, mission/values alignment). False for technical skills,\n"
			"    domain experience, and education requirements. Education (bachelor/master/PhD) is NOT\n"
			"    eligibility. Split mixed requirements into separate entries.\n\n"
			"For requirements, extract every qualification, skill, or experience mentioned in the posting. "
			"Use must_have for requirements labeled required/must/essential, "
			"strong_preference for strongly preferred/highly desired, "
			"nice_to_have for preferred/bonus/plus, "
			"and implied for unlabeled qualifications that are clearly expected.\n\n"
			"If this page does not contain a job posting, return all fields as null.\n\n"
			f"Page title: {title}\n"
			f"Page text:\n{truncated}"
		)

	@app.post("/api/extract-posting")
	async def extract_posting(req: ExtractPostingRequest):
		store = get_store()
		url_hash = hashlib.sha256(req.url.encode()).hexdigest()[:16]

		cached = await store.get_cached_posting(url_hash)
		if cached is not None:
			return cached

		if not _claude_cli.check_claude_available():
			raise HTTPException(status_code=503, detail="Claude CLI not available for extraction")

		import asyncio

		prompt = _build_extraction_prompt(req.title, req.text)
		try:
			raw = await asyncio.get_event_loop().run_in_executor(
				None, lambda: _claude_cli.call_claude(prompt, timeout=30)
			)
		except _claude_cli.ClaudeCLIError as exc:
			raise HTTPException(status_code=503, detail=f"Claude CLI error: {exc}") from exc

		try:
			cleaned = raw.strip()
			if cleaned.startswith("```"):
				cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned
			if cleaned.endswith("```"):
				cleaned = cleaned.rsplit("```", 1)[0]
			cleaned = cleaned.strip()
			parsed = json.loads(cleaned)
		except (json.JSONDecodeError, ValueError) as exc:
			raise HTTPException(
				status_code=502,
				detail="Extraction failed: invalid response from Claude",
			) from exc

		# Normalize skill mappings through taxonomy
		if "requirements" in parsed and isinstance(parsed["requirements"], list):
			from claude_candidate.requirement_parser import normalize_skill_mappings

			normalize_skill_mappings(parsed["requirements"])

		source = _infer_source(req.url)
		result = PostingExtraction(
			company=parsed.get("company") or "",
			title=parsed.get("title") or "",
			description=parsed.get("description") or "",
			url=req.url,
			source=source,
			location=parsed.get("location"),
			seniority=parsed.get("seniority"),
			remote=parsed.get("remote"),
			salary=parsed.get("salary"),
			requirements=parsed.get("requirements"),
		)
		result_dict = result.model_dump()
		await store.cache_posting(url_hash, req.url, result_dict)
		return result_dict

	return app
