"""
CompanyProfile: Public information about a company.

Used for mission alignment and culture fit scoring in the
Quick Match engine. All data sourced from public URLs only.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class CompanyProfile(BaseModel):
    """Public information about a company."""

    company_name: str
    company_url: str | None = None

    # Mission & Product
    mission_statement: str | None = None
    product_description: str
    product_domain: list[str]  # "developer-tooling", "fintech", etc.

    # Engineering Culture
    engineering_blog_url: str | None = None
    recent_blog_topics: list[str] = Field(default_factory=list)
    tech_stack_public: list[str] = Field(default_factory=list)
    github_org_url: str | None = None
    public_repos_count: int | None = None
    primary_languages_github: list[str] = Field(default_factory=list)
    oss_activity_level: Literal[
        "very_active", "active", "minimal", "none", "unknown"
    ] = "unknown"

    # Work Style
    remote_policy: Literal["remote_first", "hybrid", "in_office", "unknown"] = "unknown"
    company_size: str | None = None
    funding_stage: str | None = None

    # Signals
    culture_keywords: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)

    # Metadata
    enriched_at: datetime
    sources: list[str] = Field(default_factory=list)
    enrichment_quality: Literal["rich", "moderate", "sparse"] = "sparse"

    def to_json(self) -> str:
        return self.model_dump_json(indent=2)

    @classmethod
    def from_json(cls, data: str) -> CompanyProfile:
        return cls.model_validate_json(data)
