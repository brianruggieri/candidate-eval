"""
QuickMatchEngine and its input dataclasses, extracted from quick_match.py.

Contains AssessmentInput, SummaryInput, and the QuickMatchEngine class with
all scoring dimensions, summary generation, and action item production.

All method bodies are verbatim copies from quick_match.py —
only import sources have changed (constants/matching/dimensions come from scoring.*).
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from claude_candidate.schemas.candidate_profile import DepthLevel
from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.curated_resume import CandidateEligibility
from claude_candidate.schemas.fit_assessment import (
	DimensionScore,
	EligibilityGate,
	FitAssessment,
	SkillMatchDetail,
	score_to_grade,
	score_to_verdict,
)
from claude_candidate.schemas.job_requirements import (
	QuickRequirement,
	RequirementPriority,
	PRIORITY_WEIGHT,
)
from claude_candidate.schemas.merged_profile import (
	EvidenceSource,
	MergedEvidenceProfile,
	MergedSkillEvidence,
)
from claude_candidate.eligibility_evaluator import evaluate_gates
from claude_candidate.scoring.constants import (
	CONFIDENCE_FLOOR,
	CULTURE_BASE_SCORE,
	CULTURE_NEUTRAL_SCORE,
	CULTURE_SCORE_MAX,
	CULTURE_SCORE_MIN,
	CULTURE_SIGNAL_WEIGHT,
	DEGREE_RANKING,
	EDUCATION_MET_SCORE,
	EDUCATION_NO_MATCH_SCORE,
	EDUCATION_NO_REQUIREMENT_SCORE,
	EDUCATION_PARTIAL_SCORE,
	EXPERIENCE_EXCEED_BONUS,
	EXPERIENCE_MET_BASE,
	EXPERIENCE_NEUTRAL_SCORE,
	EXPERIENCE_NO_REQUIREMENT_SCORE,
	EXPERIENCE_SCORE_MAX,
	MAX_ACTION_ITEMS,
	MAX_GAP_NAMES,
	MAX_RESUME_ITEMS,
	MAX_TECH_OVERLAP_DISPLAY,
	MISSION_NEUTRAL_SCORE,
	MISSION_SCORE_MAX,
	SCORE_PRECISION,
	SENIORITY_DEPTH_FLOOR,
	STATUS_SCORE,
	TIMING_PRECISION,
	VERDICT_TEXT,
	_get_taxonomy,
)
from claude_candidate.scoring.matching import (
	_assess_depth_match,
	_find_best_skill,
	_find_skill_match,
	compute_match_confidence,
)
from claude_candidate.scoring.dimensions import (
	_build_skill_detail,
	_build_skill_dimension,
	_candidate_domain_set,
	_candidate_skill_names,
	_compute_overall_score,
	_compute_weights,
	_detect_domain_gap,
	_discover_resume_gaps,
	_find_resume_unverified,
	_infer_eligibility,
	_match_signal_to_pattern,
	_mission_from_posting,
	_must_have_coverage,
	_redistribute_culture_weight,
	_score_domain_overlap,
	_score_mission_text_alignment,
	_score_requirement,
	_score_tech_overlap,
	_soft_skill_discount,
	_strongest_and_gap,
)


# ---------------------------------------------------------------------------
# Data transfer objects (reduce positional parameter counts)
# ---------------------------------------------------------------------------


@dataclass
class AssessmentInput:
	"""Groups the inputs for an assessment to keep parameter counts low."""

	requirements: list[QuickRequirement]
	company: str
	title: str
	posting_url: str | None = None
	source: str = "paste"
	seniority: str = "unknown"
	culture_signals: list[str] | None = None
	tech_stack: list[str] | None = None
	company_profile: CompanyProfile | None = None
	curated_eligibility: CandidateEligibility = field(default_factory=CandidateEligibility)


@dataclass
class SummaryInput:
	"""Groups summary-generation inputs."""

	overall_score: float
	skill_dim: DimensionScore
	company: str
	title: str
	must_coverage: str
	mission_dim: DimensionScore | None = None
	culture_dim: DimensionScore | None = None
	experience_dim: DimensionScore | None = None
	education_dim: DimensionScore | None = None


# ---------------------------------------------------------------------------
# QuickMatchEngine
# ---------------------------------------------------------------------------


class QuickMatchEngine:
	"""
	Produces FitAssessments against a cached MergedEvidenceProfile.

	The profile is loaded once; multiple job postings can be assessed against it.
	"""

	def __init__(self, profile: MergedEvidenceProfile):
		self.profile = profile

	def assess(
		self,
		requirements: list[QuickRequirement],
		company: str,
		title: str,
		posting_url: str | None = None,
		source: str = "paste",
		seniority: str = "unknown",
		culture_signals: list[str] | None = None,
		tech_stack: list[str] | None = None,
		company_profile: CompanyProfile | None = None,
		curated_eligibility: CandidateEligibility | None = None,
		elapsed: float | None = None,
	) -> FitAssessment:
		"""Run the three-dimensional fit assessment."""
		inp = AssessmentInput(
			requirements=requirements,
			company=company,
			title=title,
			posting_url=posting_url,
			source=source,
			seniority=seniority,
			culture_signals=culture_signals,
			tech_stack=tech_stack,
			company_profile=company_profile,
			curated_eligibility=curated_eligibility or CandidateEligibility(),
		)
		return self._run_assessment(inp, elapsed=elapsed)

	# -- orchestration ------------------------------------------------------

	def _run_assessment(self, inp: AssessmentInput, elapsed: float | None = None) -> FitAssessment:
		"""Orchestrate scoring dimensions and assemble the result.

		Partial assessment: scores skill_match (50%), experience_match (30%),
		education_match (20%) — mission and culture are left as None.
		"""
		start_time = time.time() if elapsed is None else 0.0

		# Partition: separate eligibility gates from scorable requirements.
		# Apply heuristic denylist as fallback for cached pre-Plan-9 postings.
		eligibility_reqs = [r for r in inp.requirements if _infer_eligibility(r)]
		scorable_reqs = [r for r in inp.requirements if not _infer_eligibility(r)]
		eligibility_gates = evaluate_gates(eligibility_reqs, inp.curated_eligibility)
		eligibility_passed = not any(g.status == "unmet" for g in eligibility_gates)

		skill_dim, skill_details = self._score_skill_match(
			scorable_reqs,
			inp.seniority,
		)
		experience_dim = self._score_experience_match(
			scorable_reqs,
			inp.seniority,
		)
		education_dim = self._score_education_match(
			scorable_reqs,
			inp.tech_stack or [],
		)

		# Partial-path mission: derive tech_stack from requirement skill_mappings
		# (eng review decision 4A→C: skill_mapping proxy, no extraction model change)
		proxy_tech_stack = list({
			skill
			for req in scorable_reqs
			for skill in req.skill_mapping
		})

		# Mission is optional in partial assessments: only score if we have any mission signal.
		mission_dim: DimensionScore | None = None
		if inp.company_profile or inp.tech_stack or proxy_tech_stack:
			mission_dim = self._score_mission_alignment(
				company=inp.company,
				tech_stack=proxy_tech_stack if not inp.tech_stack else inp.tech_stack,
				company_profile=inp.company_profile,
			)

		# Partial-assessment weights.
		# Weights must sum to 1.0 (_compute_overall_score does straight weighted sum).
		skill_dim.weight = 0.60
		experience_dim.weight = 0.20
		education_dim.weight = 0.10
		if mission_dim is not None:
			mission_dim.weight = 0.10
		else:
			# No mission signal — redistribute mission weight back to skill/experience.
			skill_dim.weight = 0.65
			experience_dim.weight = 0.25
			# education stays 0.10 → total = 1.0

		# Cap experience/education scores when skill match is weak.
		# Prevents generic experience from rescuing a poor technical fit.
		if skill_dim.score < 0.55:
			experience_dim.score = min(experience_dim.score, skill_dim.score + 0.2)
			education_dim.score = min(education_dim.score, skill_dim.score + 0.2)

		overall_score = _compute_overall_score(
			skill_dim,
			mission_dim=mission_dim,
			experience_dim=experience_dim,
			education_dim=education_dim,
		)
		pre_cap_grade: str | None = None
		unmet_gates = [g for g in eligibility_gates if g.status == "unmet"]
		if unmet_gates:
			pre_cap_grade = score_to_grade(overall_score)
			overall_score = 0.0

		# Domain penalty: cap at B+ if industry domain appears 3+ times in requirements
		# but is absent from the candidate's profile.
		_GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]
		domain_gap_term = _detect_domain_gap(scorable_reqs, self.profile)
		if domain_gap_term and not unmet_gates:  # eligibility cap already zeros score; skip
			candidate_grade = score_to_grade(overall_score)
			if _GRADE_ORDER.index(candidate_grade) < _GRADE_ORDER.index("B+"):
				if pre_cap_grade is None:
					pre_cap_grade = candidate_grade
				# Drop score to top of B+ band (just below A- threshold of 0.85)
				overall_score = min(overall_score, 0.849)

		partial_percentage = round(overall_score * 100, 1)

		if elapsed is None:
			elapsed = time.time() - start_time
		return self._build_assessment(
			inp,
			skill_dim,
			mission_dim,  # Was None — now proxy-based
			None,  # culture_dim still None for partial
			skill_details,
			overall_score,
			elapsed,
			experience_dim=experience_dim,
			education_dim=education_dim,
			partial_percentage=partial_percentage,
			eligibility_gates=eligibility_gates,
			eligibility_passed=eligibility_passed,
			scorable_reqs=scorable_reqs,
			pre_cap_grade=pre_cap_grade,
			domain_gap_term=domain_gap_term,
		)

	def _build_assessment(
		self,
		inp: AssessmentInput,
		skill_dim: DimensionScore,
		mission_dim: DimensionScore | None,
		culture_dim: DimensionScore | None,
		skill_details: list[SkillMatchDetail],
		overall_score: float,
		elapsed: float,
		experience_dim: DimensionScore | None = None,
		education_dim: DimensionScore | None = None,
		partial_percentage: float | None = None,
		eligibility_gates: list[EligibilityGate] | None = None,
		eligibility_passed: bool = True,
		scorable_reqs: list[QuickRequirement] | None = None,
		pre_cap_grade: str | None = None,
		domain_gap_term: str | None = None,
	) -> FitAssessment:
		"""Assemble the final FitAssessment from scored dimensions."""
		reqs_for_gaps = scorable_reqs if scorable_reqs is not None else inp.requirements
		must_cov = _must_have_coverage(skill_details)
		strongest, biggest_gap = _strongest_and_gap(skill_details)
		resume_gaps = _discover_resume_gaps(self.profile, reqs_for_gaps)
		resume_unverified = _find_resume_unverified(self.profile, reqs_for_gaps)
		gaps = [
			d
			for d in skill_details
			if d.match_status == "no_evidence" and d.priority in ("must_have", "strong_preference")
		]
		summary_inp = SummaryInput(
			overall_score=overall_score,
			skill_dim=skill_dim,
			company=inp.company,
			title=inp.title,
			must_coverage=must_cov,
			mission_dim=mission_dim,
			culture_dim=culture_dim,
			experience_dim=experience_dim,
			education_dim=education_dim,
		)
		return self._assemble_fit_assessment(
			inp,
			summary_inp,
			skill_dim,
			mission_dim,
			culture_dim,
			skill_details,
			strongest,
			biggest_gap,
			resume_gaps,
			resume_unverified,
			gaps,
			overall_score,
			elapsed,
			experience_dim=experience_dim,
			education_dim=education_dim,
			partial_percentage=partial_percentage,
			eligibility_gates=eligibility_gates or [],
			eligibility_passed=eligibility_passed,
			pre_cap_grade=pre_cap_grade,
			domain_gap_term=domain_gap_term,
		)

	def _assemble_fit_assessment(
		self,
		inp: AssessmentInput,
		summary_inp: SummaryInput,
		skill_dim: DimensionScore,
		mission_dim: DimensionScore | None,
		culture_dim: DimensionScore | None,
		skill_details: list[SkillMatchDetail],
		strongest: str,
		biggest_gap: str,
		resume_gaps: list[str],
		resume_unverified: list[str],
		gaps: list[SkillMatchDetail],
		overall_score: float,
		elapsed: float,
		experience_dim: DimensionScore | None = None,
		education_dim: DimensionScore | None = None,
		partial_percentage: float | None = None,
		eligibility_gates: list[EligibilityGate] | None = None,
		eligibility_passed: bool = True,
		pre_cap_grade: str | None = None,
		domain_gap_term: str | None = None,
	) -> FitAssessment:
		"""Construct the FitAssessment pydantic model."""
		is_partial = culture_dim is None  # Partial = no company research (no culture dim)
		overall_summary = self._generate_summary(summary_inp)
		action_items = self._generate_action_items(
			overall_score,
			gaps,
			resume_gaps,
			resume_unverified,
			inp.company,
		)
		if pre_cap_grade is not None:
			blocker_descriptions = "; ".join(
				g.description for g in (eligibility_gates or []) if g.status == "unmet"
			)
			overall_summary = (
				f"Eligibility blocked: {blocker_descriptions}. "
				f"Skill fit would be {pre_cap_grade} if eligible."
			)
			action_items = [
				f"Eligibility: {blocker_descriptions} — skip this role",
				*action_items[:5],
			]
		return FitAssessment(
			assessment_id=str(uuid.uuid4()),
			assessed_at=datetime.now(),
			job_title=inp.title,
			company_name=inp.company,
			posting_url=inp.posting_url,
			source=inp.source,
			assessment_phase="partial" if is_partial else "full",
			partial_percentage=partial_percentage,
			overall_score=round(overall_score, SCORE_PRECISION),
			overall_grade=score_to_grade(overall_score),
			overall_summary=overall_summary,
			skill_match=skill_dim,
			experience_match=experience_dim,
			education_match=education_dim,
			mission_alignment=mission_dim,
			culture_fit=culture_dim,
			skill_matches=skill_details,
			must_have_coverage=summary_inp.must_coverage,
			strongest_match=strongest,
			biggest_gap=biggest_gap,
			resume_gaps_discovered=resume_gaps,
			resume_unverified=resume_unverified,
			company_profile_summary=(
				inp.company_profile.product_description
				if inp.company_profile
				else f"No enrichment data available for {inp.company}"
			),
			company_enrichment_quality=(
				inp.company_profile.enrichment_quality if inp.company_profile else "none"
			),
			eligibility_gates=eligibility_gates or [],
			eligibility_passed=eligibility_passed,
			domain_gap_term=domain_gap_term,
			should_apply=score_to_verdict(overall_score),
			action_items=action_items,
			profile_hash=self.profile.profile_hash,
			time_to_assess_seconds=round(elapsed, TIMING_PRECISION),
		)

	# -- dimension 1: skill match -------------------------------------------

	def _score_skill_match(
		self,
		requirements: list[QuickRequirement],
		seniority: str,
	) -> tuple[DimensionScore, list[SkillMatchDetail]]:
		"""Score the skill gap analysis dimension."""
		depth_floor = SENIORITY_DEPTH_FLOOR.get(seniority, DepthLevel.APPLIED)
		details: list[SkillMatchDetail] = []
		weighted_score = 0.0
		total_weight = 0.0
		taxonomy = _get_taxonomy()
		effective_discount = _soft_skill_discount()

		for req in requirements:
			weight = req.weight_override if req.weight_override is not None else PRIORITY_WEIGHT.get(req.priority, 1.0)

			# Discount soft skill requirements
			is_soft_skill = False
			for skill_name in req.skill_mapping:
				canonical = taxonomy.match(skill_name)
				if canonical and taxonomy.get_category(canonical) == "soft_skill":
					is_soft_skill = True
					break
			if is_soft_skill:
				weight *= effective_discount

			total_weight += weight
			best_match, best_status, best_match_type, years_ratio = _find_best_skill(
				req,
				self.profile,
				depth_floor,
			)
			req_score = _score_requirement(best_match, best_status, req.priority, years_ratio=years_ratio)

			# Compound scoring: also check average of all constituent skills
			if len(req.skill_mapping) > 1:
				all_scores = []
				for skill_name in req.skill_mapping:
					found, _mtype = _find_skill_match(skill_name, self.profile)
					if found:
						status = _assess_depth_match(found, depth_floor, self.profile)
						conf = found.confidence if found.confidence is not None else 1.0
						adj = CONFIDENCE_FLOOR + (1.0 - CONFIDENCE_FLOOR) * conf
						all_scores.append(STATUS_SCORE.get(status, 0.0) * adj)
					else:
						all_scores.append(0.0)
				avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
				req_score = max(req_score, avg_score)

			weighted_score += req_score * weight
			details.append(_build_skill_detail(req, best_match, best_status, best_match_type))

		score = weighted_score / total_weight if total_weight > 0 else 0.0
		return _build_skill_dimension(score, details), details

	# -- dimension 2: mission alignment -------------------------------------

	def _score_mission_alignment(
		self,
		company: str,
		tech_stack: list[str],
		company_profile: CompanyProfile | None,
	) -> DimensionScore:
		"""Score company/mission alignment."""
		if company_profile:
			score, details = self._mission_with_profile(company_profile)
		else:
			score, details = _mission_from_posting(self.profile, tech_stack)

		if not details:
			details = ["Insufficient data for mission alignment assessment"]

		return DimensionScore(
			dimension="mission_alignment",
			score=round(score, SCORE_PRECISION),
			grade=score_to_grade(score),
			summary=f"Mission alignment with {company}: {score_to_grade(score)}",
			details=details,
		)

	def _mission_with_profile(
		self,
		company_profile: CompanyProfile,
	) -> tuple[float, list[str]]:
		"""Score mission alignment using three signals when a company profile is available.

		Signals:
		1. Tech stack overlap — company's known technologies vs candidate skills
		2. Industry/domain match — company's product domain vs candidate project domains
		3. Mission text alignment — keyword overlap between mission text and candidate skills
		"""
		score = MISSION_NEUTRAL_SCORE
		details: list[str] = []

		domain_bonus, domain_details = _score_domain_overlap(
			self.profile,
			company_profile,
		)
		score += domain_bonus
		details.extend(domain_details)

		tech_bonus, tech_details = _score_tech_overlap(
			self.profile,
			company_profile,
		)
		score += tech_bonus
		details.extend(tech_details)

		text_bonus, text_details = _score_mission_text_alignment(
			self.profile,
			company_profile,
		)
		score += text_bonus
		details.extend(text_details)

		return min(score, MISSION_SCORE_MAX), details

	# -- dimension 3: culture fit -------------------------------------------

	def _score_culture_fit(
		self,
		culture_signals: list[str],
		company_profile: CompanyProfile | None,
	) -> DimensionScore:
		"""Score culture/working style fit via direct pattern matching.

		Compares each culture signal to the candidate's observed behavioral
		patterns. If no signals are present, or if the candidate has no
		patterns, marks insufficient_data=True.
		"""
		all_signals = self._collect_culture_signals(
			culture_signals,
			company_profile,
		)
		if not self.profile.patterns:
			return None  # No behavioral data (sessions parked) — omit dimension
		if not all_signals:
			return self._neutral_culture_dimension()

		matches, total_signals, details = self._evaluate_culture_signals(
			all_signals,
		)
		score = self._compute_culture_score(matches, total_signals)

		if company_profile and company_profile.remote_policy != "unknown":
			policy = company_profile.remote_policy.replace("_", " ")
			details.append(f"Work policy: {policy}")

		if not details:
			details = ["Culture alignment assessment based on available signals"]

		confidence = matches / total_signals if total_signals > 0 else 0.0

		return DimensionScore(
			dimension="culture_fit",
			score=round(score, SCORE_PRECISION),
			grade=score_to_grade(score),
			summary=f"Culture fit based on {total_signals} pattern signals",
			details=details[:7],
			confidence=round(confidence, SCORE_PRECISION),
		)

	def _collect_culture_signals(
		self,
		culture_signals: list[str],
		company_profile: CompanyProfile | None,
	) -> list[str]:
		"""Merge culture signals from the posting and company profile."""
		all_signals = list(culture_signals)
		if company_profile:
			all_signals.extend(company_profile.culture_keywords)
		return all_signals

	def _neutral_culture_dimension(self) -> DimensionScore:
		"""Return a neutral culture dimension when data is insufficient."""
		return DimensionScore(
			dimension="culture_fit",
			score=CULTURE_NEUTRAL_SCORE,
			grade=score_to_grade(CULTURE_NEUTRAL_SCORE),
			summary="Insufficient culture data for assessment",
			details=["No culture signals or candidate patterns available"],
			confidence=0.0,
			insufficient_data=True,
		)

	def _evaluate_culture_signals(
		self,
		signals: list[str],
	) -> tuple[float, int, list[str]]:
		"""Match culture signals directly against candidate patterns.

		Returns (total_match_value, signal_count, detail_lines).
		"""
		matches = 0.0
		total_signals = len(signals)
		details: list[str] = []

		for signal in signals:
			value, detail = _match_signal_to_pattern(signal, self.profile)
			matches += value
			if detail:
				details.append(detail)

		return matches, total_signals, details

	def _compute_culture_score(self, matches: float, total: int) -> float:
		"""Compute bounded culture fit score from match ratio."""
		if total > 0:
			score = CULTURE_BASE_SCORE + (matches / total) * CULTURE_SIGNAL_WEIGHT
		else:
			score = CULTURE_NEUTRAL_SCORE
		return min(max(score, CULTURE_SCORE_MIN), CULTURE_SCORE_MAX)

	# -- dimension 4: experience match ---------------------------------------

	def _score_experience_match(
		self,
		requirements: list[QuickRequirement],
		seniority: str,
	) -> DimensionScore:
		"""Score experience-years alignment between candidate and requirements.

		Compares the candidate's total_years_experience against the maximum
		years_experience specified across all requirements. Returns a neutral
		score when no requirements specify years.
		"""
		# Collect years requirements from enriched QuickRequirements
		years_reqs: list[tuple[str, int]] = []
		for req in requirements:
			if req.years_experience is not None:
				years_reqs.append((req.description, req.years_experience))

		if not years_reqs:
			return DimensionScore(
				dimension="experience_match",
				score=EXPERIENCE_NO_REQUIREMENT_SCORE,
				grade=score_to_grade(EXPERIENCE_NO_REQUIREMENT_SCORE),
				summary="No specific experience-years required — effectively met",
				details=["No years requirement stated; no bar to clear"],
				insufficient_data=True,
			)

		candidate_years = self.profile.total_years_experience
		if candidate_years is None:
			return DimensionScore(
				dimension="experience_match",
				score=EXPERIENCE_NEUTRAL_SCORE,
				grade=score_to_grade(EXPERIENCE_NEUTRAL_SCORE),
				summary="Candidate experience years unknown",
				details=["No total years of experience on candidate profile"],
				insufficient_data=True,
			)

		max_required = max(yrs for _, yrs in years_reqs)
		details: list[str] = []

		if candidate_years >= max_required:
			# Candidate meets or exceeds — score in 0.7-1.0 range
			ratio = min(candidate_years / max_required, 2.0)  # Cap at 2x
			score = EXPERIENCE_MET_BASE + (ratio - 1.0) * EXPERIENCE_EXCEED_BONUS
			score = min(score, EXPERIENCE_SCORE_MAX)
		else:
			# Candidate below — proportional score in 0.0-0.7 range
			ratio = candidate_years / max_required if max_required > 0 else 0.0
			score = ratio * EXPERIENCE_MET_BASE

		for desc, yrs in years_reqs:
			if candidate_years >= yrs:
				details.append(f"Met: {yrs}+ years {desc} (have {candidate_years:.0f} yrs)")
			else:
				details.append(f"Gap: {yrs}+ years {desc} (have {candidate_years:.0f} yrs)")

		if not details:
			details = ["Experience evaluation completed"]

		return DimensionScore(
			dimension="experience_match",
			score=round(score, SCORE_PRECISION),
			grade=score_to_grade(score),
			summary=f"Experience: {candidate_years:.0f} yrs vs {max_required}+ required",
			details=details[:7],
		)

	# -- dimension 5: education match ----------------------------------------

	def _score_education_match(
		self,
		requirements: list[QuickRequirement],
		tech_stack: list[str],
	) -> DimensionScore:
		"""Score education and tech-stack alignment.

		Combines two signals when available:
		1. Education level match (candidate degree vs required degree)
		2. Tech stack overlap (posting tech stack vs candidate skills)

		Returns a neutral score when neither signal is available.
		"""
		edu_score = self._score_education_level(requirements)
		tech_score, tech_details = self._score_tech_stack_overlap(tech_stack)

		scores: list[float] = []
		details: list[str] = []

		if edu_score is not None:
			scores.append(edu_score[0])
			details.extend(edu_score[1])

		if tech_score is not None:
			scores.append(tech_score)
			details.extend(tech_details)

		if not scores:
			return DimensionScore(
				dimension="education_match",
				score=EDUCATION_NO_REQUIREMENT_SCORE,
				grade=score_to_grade(EDUCATION_NO_REQUIREMENT_SCORE),
				summary="No specific education or tech stack required — effectively met",
				details=["No education or tech stack requirement stated; no bar to clear"],
				insufficient_data=True,
			)

		score = sum(scores) / len(scores)
		if not details:
			details = ["Education/tech evaluation completed"]

		return DimensionScore(
			dimension="education_match",
			score=round(score, SCORE_PRECISION),
			grade=score_to_grade(score),
			summary=f"Education & tech stack alignment: {score_to_grade(score)}",
			details=details[:7],
		)

	def _score_education_level(
		self,
		requirements: list[QuickRequirement],
	) -> tuple[float, list[str]] | None:
		"""Score education level match. Returns None if no education requirements."""
		# Collect education requirements
		edu_reqs: list[str] = []
		for req in requirements:
			if req.education_level:
				edu_reqs.append(req.education_level.lower())

		if not edu_reqs:
			return None

		candidate_edu = self.profile.education
		if not candidate_edu:
			return (0.2, ["No education listed on candidate profile"])

		# Parse candidate's highest degree
		candidate_rank = self._highest_degree_rank(candidate_edu)
		# Parse highest required degree
		required_rank = max(DEGREE_RANKING.get(edu, 0) for edu in edu_reqs)

		details: list[str] = []
		if candidate_rank >= required_rank:
			score = EDUCATION_MET_SCORE
			details.append(
				f"Education met: have {self._rank_to_label(candidate_rank)}, "
				f"need {self._rank_to_label(required_rank)}"
			)
		elif candidate_rank > 0:
			score = EDUCATION_PARTIAL_SCORE
			details.append(
				f"Education partial: have {self._rank_to_label(candidate_rank)}, "
				f"need {self._rank_to_label(required_rank)}"
			)
		else:
			score = EDUCATION_NO_MATCH_SCORE
			details.append("Education requirement not met")

		return (score, details)

	def _score_tech_stack_overlap(
		self,
		tech_stack: list[str],
	) -> tuple[float | None, list[str]]:
		"""Score tech stack overlap. Returns (None, []) if no tech stack specified."""
		if not tech_stack:
			return None, []

		posting_techs = {t.lower() for t in tech_stack}
		candidate_techs = {s.name for s in self.profile.skills}
		overlap = posting_techs & candidate_techs

		if not overlap:
			return 0.3, [f"No tech stack overlap (0/{len(posting_techs)} match)"]

		ratio = len(overlap) / len(posting_techs)
		score = 0.3 + ratio * 0.7  # Maps 0..1 ratio to 0.3..1.0
		details = [
			f"Tech stack: {len(overlap)}/{len(posting_techs)} match "
			f"({', '.join(sorted(overlap)[:MAX_TECH_OVERLAP_DISPLAY])})"
		]
		return score, details

	@staticmethod
	def _highest_degree_rank(education: list[str]) -> int:
		"""Extract the highest degree rank from a list of education strings."""
		best = 0
		for entry in education:
			entry_lower = entry.lower()
			for keyword, rank in DEGREE_RANKING.items():
				if keyword in entry_lower:
					best = max(best, rank)
		return best

	@staticmethod
	def _rank_to_label(rank: int) -> str:
		"""Convert a degree rank back to a human label."""
		for label, r in DEGREE_RANKING.items():
			if r == rank:
				return label
		return "unknown"

	# -- summary & action items ---------------------------------------------

	def _generate_summary(self, inp: SummaryInput) -> str:
		"""Generate the overall summary paragraph."""
		grade = score_to_grade(inp.overall_score)
		verdict = score_to_verdict(inp.overall_score)
		strongest, weakest = self._strongest_weakest_dims(inp)
		return (
			f"Overall {grade} fit for {inp.title} at {inp.company}. "
			f"{inp.must_coverage}. "
			f"Strongest dimension: {strongest[0]} ({score_to_grade(strongest[1])}). "
			f"Weakest dimension: {weakest[0]} ({score_to_grade(weakest[1])}). "
			f"{VERDICT_TEXT.get(verdict, '')}"
		)

	def _strongest_weakest_dims(
		self,
		inp: SummaryInput,
	) -> tuple[tuple[str, float], tuple[str, float]]:
		"""Find the strongest and weakest dimension by score."""
		dims: list[tuple[str, float]] = [
			("Skills", inp.skill_dim.score),
		]
		if inp.experience_dim is not None:
			dims.append(("Experience", inp.experience_dim.score))
		if inp.education_dim is not None:
			dims.append(("Education", inp.education_dim.score))
		if inp.mission_dim is not None:
			dims.append(("Mission", inp.mission_dim.score))
		if inp.culture_dim is not None:
			dims.append(("Culture", inp.culture_dim.score))
		return max(dims, key=lambda x: x[1]), min(dims, key=lambda x: x[1])

	def _generate_action_items(
		self,
		overall_score: float,
		gaps: list[SkillMatchDetail],
		resume_gaps: list[str],
		resume_unverified: list[str],
		company: str,
	) -> list[str]:
		"""Generate concrete next-step action items."""
		items: list[str] = []
		verdict = score_to_verdict(overall_score)
		self._add_verdict_actions(items, verdict, company)
		self._add_gap_actions(items, gaps, resume_gaps, resume_unverified)
		if not items:
			items.append("Review the detailed skill breakdown for more context")
		return items[:MAX_ACTION_ITEMS]

	def _add_verdict_actions(
		self,
		items: list[str],
		verdict: str,
		company: str,
	) -> None:
		"""Append action items driven by the overall verdict."""
		if verdict in ("strong_yes", "yes"):
			items.append("Generate full application package for this role")
		if verdict in ("maybe", "probably_not"):
			items.append(
				f"Research {company}'s engineering blog and recent projects before deciding"
			)

	def _add_gap_actions(
		self,
		items: list[str],
		gaps: list[SkillMatchDetail],
		resume_gaps: list[str],
		resume_unverified: list[str],
	) -> None:
		"""Append action items related to gaps and unverified claims."""
		if resume_gaps:
			names = ", ".join(resume_gaps[:MAX_RESUME_ITEMS])
			items.append(
				f"Update resume to include: {names} "
				f"(demonstrated in sessions but missing from resume)"
			)
		if gaps:
			gap_names = [g.requirement for g in gaps[:MAX_GAP_NAMES]]
			items.append(f"Key gaps to address: {', '.join(gap_names)}")
		if resume_unverified:
			names = ", ".join(resume_unverified[:MAX_RESUME_ITEMS])
			items.append(
				f"Resume claims without session evidence: {names} "
				f"— prepare to discuss these in interviews"
			)
