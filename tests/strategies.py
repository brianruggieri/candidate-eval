"""Reusable Hypothesis strategies for claude-candidate Pydantic models."""

from __future__ import annotations

from datetime import datetime, timezone

from hypothesis import strategies as st

from claude_candidate.schemas.candidate_profile import (
	DepthLevel,
	SessionReference,
	SkillEntry,
)
from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority

# ---------------------------------------------------------------------------
# Evidence type literals
# ---------------------------------------------------------------------------

EVIDENCE_TYPES = [
	"direct_usage",
	"architecture_decision",
	"debugging",
	"teaching",
	"evaluation",
	"integration",
	"refactor",
	"testing",
	"review",
	"planning",
]

SKILL_CATEGORIES = [
	"language",
	"framework",
	"tool",
	"platform",
	"concept",
	"practice",
	"domain",
	"soft_skill",
]

# ---------------------------------------------------------------------------
# Primitive building blocks
# ---------------------------------------------------------------------------

# Non-empty text that is still non-empty after .strip()
_nonempty_text = st.text(
	alphabet=st.characters(blacklist_categories=("Cs",)),
	min_size=1,
	max_size=100,
).filter(lambda s: s.strip() != "")

# Datetime that is timezone-aware (UTC) and within a reasonable range.
# Pydantic v2 round-trips datetime as ISO-8601; we keep it UTC to avoid
# ambiguity during JSON deserialization.
_datetime_strategy = st.datetimes(
	min_value=datetime(2020, 1, 1),
	max_value=datetime(2030, 12, 31),
	timezones=st.just(timezone.utc),
)

# ---------------------------------------------------------------------------
# SessionReference strategy
# ---------------------------------------------------------------------------

session_reference_strategy: st.SearchStrategy[SessionReference] = st.builds(
	SessionReference,
	session_id=_nonempty_text,
	session_date=_datetime_strategy,
	project_context=_nonempty_text,
	evidence_snippet=st.text(
		alphabet=st.characters(blacklist_categories=("Cs",)),
		min_size=1,
		max_size=500,
	).filter(lambda s: s.strip() != ""),
	evidence_type=st.sampled_from(EVIDENCE_TYPES),
	confidence=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
)

# ---------------------------------------------------------------------------
# SkillEntry strategy
# ---------------------------------------------------------------------------

# SkillEntry.name goes through normalize_name (lower + strip), so we need
# text that is non-empty after that transformation.
_skill_name = st.text(
	alphabet=st.characters(blacklist_categories=("Cs",)),
	min_size=1,
	max_size=80,
).filter(lambda s: s.strip() != "")

skill_entry_strategy: st.SearchStrategy[SkillEntry] = st.builds(
	SkillEntry,
	name=_skill_name,
	category=st.sampled_from(SKILL_CATEGORIES),
	depth=st.sampled_from(list(DepthLevel)),
	frequency=st.integers(min_value=1, max_value=500),
	recency=_datetime_strategy,
	first_seen=_datetime_strategy,
	evidence=st.lists(session_reference_strategy, min_size=1, max_size=5),
	context_notes=st.one_of(st.none(), _nonempty_text),
)

# ---------------------------------------------------------------------------
# QuickRequirement strategy
# ---------------------------------------------------------------------------

quick_requirement_strategy: st.SearchStrategy[QuickRequirement] = st.builds(
	QuickRequirement,
	description=_nonempty_text,
	skill_mapping=st.lists(_nonempty_text, min_size=1, max_size=10),
	priority=st.sampled_from(list(RequirementPriority)),
	source_text=st.text(max_size=200),
)
