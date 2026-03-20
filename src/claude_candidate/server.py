"""
FastAPI backend server for claude-candidate.

Exposes REST endpoints consumed by the Chrome extension and CLI tools.
Manages a local AssessmentStore and serves profile/assessment data.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

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


class WatchlistAddRequest(BaseModel):
    company_name: str
    job_title: str
    posting_url: str | None = None
    assessment_id: str | None = None
    notes: str | None = None


class WatchlistUpdateRequest(BaseModel):
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
    }

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Startup
        _data_dir.mkdir(parents=True, exist_ok=True)
        store = AssessmentStore(_data_dir / "assessments.db")
        await store.initialize()
        _state["store"] = store

        # Auto-discover profile JSON files
        profiles: dict[str, Any] = {}
        profile_files = {
            "candidate": _data_dir / "candidate_profile.json",
            "resume": _data_dir / "resume_profile.json",
            "merged": _data_dir / "merged_profile.json",
        }
        for profile_type, profile_path in profile_files.items():
            if profile_path.exists():
                try:
                    profiles[profile_type] = json.loads(profile_path.read_text())
                except (json.JSONDecodeError, OSError):
                    pass
        _state["profiles"] = profiles

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
        return _state["profiles"]

    def _profile_hash(data: dict[str, Any]) -> str:
        return hashlib.sha256(
            json.dumps(data, sort_keys=True).encode()
        ).hexdigest()[:16]

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    @app.get("/api/health")
    async def health():
        profiles = get_profiles()
        profile_loaded = bool(profiles.get("candidate") or profiles.get("merged"))
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
        merged_data = profiles.get("merged")

        if candidate_data:
            hashes["candidate"] = _profile_hash(candidate_data)
        if resume_data:
            hashes["resume"] = _profile_hash(resume_data)
        if merged_data:
            hashes["merged"] = _profile_hash(merged_data)

        return {
            "has_candidate_profile": candidate_data is not None,
            "has_resume_profile": resume_data is not None,
            "has_merged_profile": merged_data is not None,
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
        from claude_candidate.schemas.candidate_profile import CandidateProfile
        from claude_candidate.schemas.resume_profile import ResumeProfile
        from claude_candidate.schemas.job_requirements import QuickRequirement
        from claude_candidate.merger import merge_profiles, merge_candidate_only
        from claude_candidate.quick_match import QuickMatchEngine
        from claude_candidate.cli import _extract_basic_requirements

        profiles = get_profiles()
        store = get_store()

        candidate_data = profiles.get("candidate")
        resume_data = profiles.get("resume")

        if not candidate_data:
            raise HTTPException(
                status_code=422,
                detail="No candidate profile loaded. Place candidate_profile.json in the data directory.",
            )

        # Build merged profile
        cp = CandidateProfile.model_validate(candidate_data)
        if resume_data:
            rp = ResumeProfile.model_validate(resume_data)
            merged = merge_profiles(cp, rp)
        else:
            merged = merge_candidate_only(cp)

        # Build requirements
        if req.requirements:
            requirements = [QuickRequirement(**r) for r in req.requirements]
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
        Generate all deliverables (resume bullets, cover letter, interview prep)
        for an existing assessment via Claude.

        Returns the assessment dict merged with a ``deliverables`` key containing
        all three generated artifacts. If Claude is unavailable, returns the
        assessment with an ``error`` field describing the failure.
        """
        from claude_candidate.schemas.fit_assessment import FitAssessment
        from claude_candidate.generator import (
            ClaudeCLIError,
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

        import asyncio

        def _generate_all():
            return {
                "resume_bullets": generate_resume_bullets(assessment=assessment),
                "cover_letter": generate_cover_letter(assessment=assessment),
                "interview_prep": generate_interview_prep(assessment=assessment),
            }

        try:
            deliverables = await asyncio.get_event_loop().run_in_executor(None, _generate_all)
        except ClaudeCLIError as exc:
            return {**data, "error": str(exc)}

        return {
            **data,
            "deliverables": deliverables,
        }

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
    # Watchlist
    # ------------------------------------------------------------------

    @app.post("/api/watchlist", status_code=201)
    async def add_watchlist(req: WatchlistAddRequest):
        store = get_store()
        wid = await store.add_to_watchlist(
            company_name=req.company_name,
            job_title=req.job_title,
            posting_url=req.posting_url,
            assessment_id=req.assessment_id,
            notes=req.notes,
        )
        return {
            "id": wid,
            "company_name": req.company_name,
            "job_title": req.job_title,
            "posting_url": req.posting_url,
            "assessment_id": req.assessment_id,
            "notes": req.notes,
            "status": "watching",
        }

    @app.get("/api/watchlist")
    async def list_watchlist(
        status: str | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
    ):
        store = get_store()
        return await store.list_watchlist(status=status, limit=limit)

    @app.patch("/api/watchlist/{watchlist_id}")
    async def update_watchlist(watchlist_id: int, req: WatchlistUpdateRequest):
        store = get_store()
        updated = await store.update_watchlist(
            watchlist_id=watchlist_id,
            status=req.status,
            notes=req.notes,
            assessment_id=req.assessment_id,
        )
        if not updated:
            raise HTTPException(status_code=404, detail="Watchlist entry not found")
        return {"updated": True, "id": watchlist_id}

    @app.delete("/api/watchlist/{watchlist_id}")
    async def delete_watchlist(watchlist_id: int):
        store = get_store()
        removed = await store.remove_from_watchlist(watchlist_id)
        if not removed:
            raise HTTPException(status_code=404, detail="Watchlist entry not found")
        return {"deleted": True, "id": watchlist_id}

    # ------------------------------------------------------------------
    # Extract posting
    # ------------------------------------------------------------------

    MAX_EXTRACTION_TEXT = 15_000

    def _infer_source(url: str) -> str:
        lower = url.lower()
        if "linkedin.com" in lower: return "linkedin"
        if "greenhouse.io" in lower: return "greenhouse"
        if "lever.co" in lower: return "lever"
        if "indeed.com" in lower: return "indeed"
        return "web"

    def _build_extraction_prompt(title: str, text: str) -> str:
        truncated = text[:MAX_EXTRACTION_TEXT]
        return (
            "Extract the job posting from this web page text. "
            "Return ONLY valid JSON with these fields:\n"
            '- company: string (the hiring company name)\n'
            '- title: string (the job title)\n'
            '- description: string (full job description including requirements and qualifications)\n'
            '- location: string or null\n'
            '- seniority: string or null (one of: junior, mid, senior, staff, principal, director)\n'
            '- remote: boolean or null\n'
            '- salary: string or null\n\n'
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
                status_code=502, detail="Extraction failed: invalid response from Claude",
            ) from exc

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
        )
        result_dict = result.model_dump()
        await store.cache_posting(url_hash, req.url, result_dict)
        return result_dict

    return app
