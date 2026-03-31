"""Tests for the heuristic commit pre-filter."""

from __future__ import annotations

from datetime import datetime, timezone

from claude_candidate.commit_filter import (
	CommitTier,
	RawCommit,
	_classify_tier,
	_is_noise,
	_structural_score,
	filter_commits,
	slot_budget_for_repo,
)

_TS = datetime(2026, 3, 15, tzinfo=timezone.utc)


def _rc(message: str, **kw) -> RawCommit:
	"""Shorthand for building a RawCommit with a message."""
	defaults = dict(hash="abc1234", timestamp=_TS, additions=50, deletions=10, files_changed=3)
	defaults.update(kw)
	return RawCommit(message=message, **defaults)


# ---------------------------------------------------------------------------
# _is_noise
# ---------------------------------------------------------------------------


class TestIsNoise:
	def test_merge_branch_is_noise(self):
		assert _is_noise("Merge branch 'main' into feature") is True

	def test_merge_pull_request_is_noise(self):
		assert _is_noise("Merge pull request #42 from user/branch") is True

	def test_merge_remote_is_noise(self):
		assert _is_noise("Merge remote-tracking branch 'origin/main'") is True

	def test_version_bump_is_noise(self):
		assert _is_noise("Bump version to 0.9.1, update docs") is True

	def test_wip_is_noise(self):
		assert _is_noise("WIP: still working on this feature") is True

	def test_fixup_is_noise(self):
		assert _is_noise("fixup! Add scoring engine tests") is True

	def test_short_message_is_noise(self):
		assert _is_noise("fix typo") is True

	def test_real_commit_not_noise(self):
		assert _is_noise("Add gradient year scoring to replace binary thresholds") is False


# ---------------------------------------------------------------------------
# _classify_tier
# ---------------------------------------------------------------------------


class TestClassifyTier:
	def test_feat_is_tier1(self):
		assert _classify_tier("feat: add scoring engine") == CommitTier.TIER1

	def test_refactor_is_tier1(self):
		assert _classify_tier("refactor: simplify merger logic") == CommitTier.TIER1

	def test_perf_is_tier1(self):
		assert _classify_tier("perf: optimize taxonomy lookup") == CommitTier.TIER1

	def test_implement_is_tier1(self):
		assert _classify_tier("implement culture scoring pipeline") == CommitTier.TIER1

	def test_add_is_tier1(self):
		assert _classify_tier("Add CommitHighlight schema and repo_evidence field") == CommitTier.TIER1

	def test_introduce_is_tier1(self):
		assert _classify_tier("introduce gradient year model") == CommitTier.TIER1

	def test_fix_is_tier2(self):
		assert _classify_tier("fix: null check in parser") == CommitTier.TIER2

	def test_test_is_tier2(self):
		assert _classify_tier("test: add hypothesis cases for merger") == CommitTier.TIER2

	def test_chore_is_tier3(self):
		assert _classify_tier("chore: clean up unused imports") == CommitTier.TIER3

	def test_docs_is_tier3(self):
		assert _classify_tier("docs: update README for v0.9") == CommitTier.TIER3

	def test_ci_is_tier3(self):
		assert _classify_tier("ci: add linting step") == CommitTier.TIER3

	def test_unclassified_defaults_to_tier2(self):
		assert _classify_tier("Wire server reassess batch through prepare_assess_inputs()") == CommitTier.TIER2


# ---------------------------------------------------------------------------
# _structural_score
# ---------------------------------------------------------------------------


class TestStructuralScore:
	def test_zero_diff_scores_zero(self):
		assert _structural_score(additions=0, deletions=0, files_changed=0) == 0.0

	def test_larger_diff_scores_higher(self):
		small = _structural_score(additions=10, deletions=5, files_changed=2)
		large = _structural_score(additions=500, deletions=200, files_changed=20)
		assert large > small

	def test_score_is_positive_for_nonzero(self):
		score = _structural_score(additions=1, deletions=0, files_changed=1)
		assert score > 0.0


# ---------------------------------------------------------------------------
# filter_commits
# ---------------------------------------------------------------------------


class TestFilterCommits:
	def test_drops_noise(self):
		commits = [
			_rc("Merge branch 'main' into feat/x"),
			_rc("feat: add scoring engine with gradient years"),
		]
		result = filter_commits(commits)
		assert len(result) == 1
		assert result[0].message == "feat: add scoring engine with gradient years"

	def test_drops_tier3(self):
		commits = [
			_rc("feat: implement culture scoring"),
			_rc("chore: clean up imports across modules"),
			_rc("docs: update CLAUDE.md with new patterns"),
		]
		result = filter_commits(commits)
		assert len(result) == 1
		assert "feat" in result[0].message

	def test_sorts_tier1_before_tier2(self):
		commits = [
			_rc("fix: null check in parser module"),
			_rc("feat: add gradient year scoring model"),
		]
		result = filter_commits(commits)
		assert result[0].message.startswith("feat:")
		assert result[1].message.startswith("fix:")

	def test_caps_at_max_candidates(self):
		commits = [_rc(f"feat: feature number {i:03d} implemented") for i in range(100)]
		result = filter_commits(commits, max_candidates=10)
		assert len(result) == 10

	def test_empty_input_returns_empty(self):
		assert filter_commits([]) == []


# ---------------------------------------------------------------------------
# slot_budget_for_repo
# ---------------------------------------------------------------------------


class TestSlotBudget:
	def test_proportional_allocation(self):
		"""A repo with half the commits gets half the budget."""
		slots = slot_budget_for_repo(50, total_commits=100, total_budget=20)
		assert slots == 10

	def test_min_slots_enforced(self):
		"""Even a repo with 1 commit gets at least min_slots."""
		slots = slot_budget_for_repo(1, total_commits=1000, total_budget=20, min_slots=2)
		assert slots >= 2

	def test_zero_total_commits_returns_min(self):
		"""Edge case: total_commits=0 returns min_slots."""
		slots = slot_budget_for_repo(0, total_commits=0, total_budget=20)
		assert slots == 1

	def test_single_repo_gets_full_budget(self):
		"""A single repo gets the full budget."""
		slots = slot_budget_for_repo(200, total_commits=200, total_budget=20)
		assert slots == 20
