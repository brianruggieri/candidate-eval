"""
claude-candidate schemas.

All inter-stage data contracts are defined here as Pydantic v2 models.
These schemas are the single source of truth for the pipeline's data flow.
"""

from claude_candidate.schemas.candidate_profile import (
    CandidateProfile,
    DepthLevel,
    PatternType,
    ProblemSolvingPattern,
    ProjectComplexity,
    ProjectSummary,
    SessionReference,
    SkillEntry,
)
from claude_candidate.schemas.job_requirements import (
    JobRequirement,
    JobRequirements,
    RequirementPriority,
)
from claude_candidate.schemas.match_evaluation import (
    MatchEvaluation,
    SkillMatch,
)
from claude_candidate.schemas.session_manifest import (
    CorpusStatistics,
    PipelineArtifactRecord,
    PublicRepoCorrelation,
    RedactionSummary,
    SessionFileRecord,
    SessionManifest,
)
from claude_candidate.schemas.resume_profile import (
    ResumeProfile,
    ResumeRole,
    ResumeSkill,
)
from claude_candidate.schemas.merged_profile import (
    EvidenceSource,
    MergedEvidenceProfile,
    MergedSkillEvidence,
)
from claude_candidate.schemas.company_profile import CompanyProfile
from claude_candidate.schemas.fit_assessment import (
    DimensionScore,
    FitAssessment,
    SkillMatchDetail,
)

__all__ = [
    # candidate_profile
    "CandidateProfile",
    "DepthLevel",
    "PatternType",
    "ProblemSolvingPattern",
    "ProjectComplexity",
    "ProjectSummary",
    "SessionReference",
    "SkillEntry",
    # job_requirements
    "JobRequirement",
    "JobRequirements",
    "RequirementPriority",
    # match_evaluation
    "MatchEvaluation",
    "SkillMatch",
    # session_manifest
    "CorpusStatistics",
    "PipelineArtifactRecord",
    "PublicRepoCorrelation",
    "RedactionSummary",
    "SessionFileRecord",
    "SessionManifest",
    # resume_profile
    "ResumeProfile",
    "ResumeRole",
    "ResumeSkill",
    # merged_profile
    "EvidenceSource",
    "MergedEvidenceProfile",
    "MergedSkillEvidence",
    # company_profile
    "CompanyProfile",
    # fit_assessment
    "DimensionScore",
    "FitAssessment",
    "SkillMatchDetail",
]
