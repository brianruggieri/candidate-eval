"""
Heuristic pre-filter for commit evidence extraction.

Fetches the commit log, drops noise (merge commits, version bumps, WIP),
classifies commits into tiers by conventional-commit prefix, and ranks
by a structural score that combines diff size with file breadth.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum


class CommitTier(IntEnum):
	"""Commit importance tiers — lower is better."""

	TIER1 = 1  # feat, refactor, perf, implement, add, introduce
	TIER2 = 2  # fix, test (and unclassified)
	TIER3 = 3  # chore, bump, docs, style, revert, ci, build


@dataclass
class RawCommit:
	"""A single parsed commit from git log."""

	hash: str
	message: str
	timestamp: datetime
	additions: int = 0
	deletions: int = 0
	files_changed: int = 0
	pr_number: int | None = None
	body: str = ""


# ---------------------------------------------------------------------------
# Noise detection
# ---------------------------------------------------------------------------

_MERGE_RE = re.compile(r"^Merge\s+(branch|pull\s+request|remote)", re.IGNORECASE)
_VERSION_RE = re.compile(r"^(bump|release|v?\d+\.\d+)", re.IGNORECASE)
_WIP_RE = re.compile(r"^(wip|wip:|fixup!|squash!)", re.IGNORECASE)


def _is_noise(message: str) -> bool:
	"""Return True if the commit message is low-signal noise."""
	msg = message.strip()
	if len(msg) < 20:
		return True
	if _MERGE_RE.match(msg):
		return True
	if _VERSION_RE.match(msg):
		return True
	if _WIP_RE.match(msg):
		return True
	return False


# ---------------------------------------------------------------------------
# Tier classification
# ---------------------------------------------------------------------------

_TIER1_RE = re.compile(
	r"^(feat|refactor|perf|implement|add|introduce)[\s:(]",
	re.IGNORECASE,
)
_TIER3_RE = re.compile(
	r"^(chore|bump|docs|style|revert|ci|build)[\s:(]",
	re.IGNORECASE,
)
_TIER2_RE = re.compile(
	r"^(fix|test)[\s:(]",
	re.IGNORECASE,
)


def _classify_tier(message: str) -> CommitTier:
	"""Classify a commit message into a tier by conventional-commit prefix."""
	msg = message.strip()
	if _TIER1_RE.match(msg):
		return CommitTier.TIER1
	if _TIER3_RE.match(msg):
		return CommitTier.TIER3
	if _TIER2_RE.match(msg):
		return CommitTier.TIER2
	# Unclassified defaults to tier 2
	return CommitTier.TIER2


# ---------------------------------------------------------------------------
# Structural score
# ---------------------------------------------------------------------------


def _structural_score(*, additions: int, deletions: int, files_changed: int) -> float:
	"""Score a commit by diff size and breadth.

	Formula: log1p(additions + deletions) * 0.6 + log1p(files_changed) * 0.4
	"""
	return math.log1p(additions + deletions) * 0.6 + math.log1p(files_changed) * 0.4


# ---------------------------------------------------------------------------
# Filter pipeline
# ---------------------------------------------------------------------------


def filter_commits(
	commits: list[RawCommit],
	*,
	max_candidates: int = 50,
) -> list[RawCommit]:
	"""Drop noise, drop tier 3, sort by (tier asc, score desc), cap at max_candidates."""
	# Step 1: drop noise
	kept = [c for c in commits if not _is_noise(c.message)]

	# Step 2: classify and drop tier 3
	scored: list[tuple[RawCommit, CommitTier, float]] = []
	for c in kept:
		tier = _classify_tier(c.message)
		if tier == CommitTier.TIER3:
			continue
		score = _structural_score(
			additions=c.additions,
			deletions=c.deletions,
			files_changed=c.files_changed,
		)
		scored.append((c, tier, score))

	# Step 3: sort by tier ascending, then score descending
	scored.sort(key=lambda x: (x[1], -x[2]))

	# Step 4: cap at max_candidates
	return [c for c, _, _ in scored[:max_candidates]]


# ---------------------------------------------------------------------------
# Slot budget allocation
# ---------------------------------------------------------------------------


def slot_budget_for_repo(
	commit_count: int,
	*,
	total_commits: int,
	total_budget: int,
	min_slots: int = 1,
) -> int:
	"""Allocate highlight slots proportionally to a repo's commit count.

	Args:
		commit_count: Number of commits in this repo.
		total_commits: Total commits across all repos.
		total_budget: Total highlight slots to distribute.
		min_slots: Minimum slots any repo receives.

	Returns:
		Number of highlight slots for this repo.
	"""
	if total_commits <= 0:
		return min_slots
	fraction = commit_count / total_commits
	return max(min_slots, round(fraction * total_budget))
