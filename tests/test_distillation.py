"""Tests for requirement distillation: compound splitting and weight preservation."""

import pytest
from claude_candidate.schemas.job_requirements import QuickRequirement, RequirementPriority, PRIORITY_WEIGHT


class TestQuickRequirementDistillationFields:
	"""Verify new schema fields for distillation."""

	def test_parent_id_defaults_to_none(self):
		req = QuickRequirement(
			description="Python experience",
			skill_mapping=["python"],
			priority=RequirementPriority.MUST_HAVE,
		)
		assert req.parent_id is None

	def test_weight_override_defaults_to_none(self):
		req = QuickRequirement(
			description="Python experience",
			skill_mapping=["python"],
			priority=RequirementPriority.MUST_HAVE,
		)
		assert req.weight_override is None

	def test_parent_id_set(self):
		req = QuickRequirement(
			description="Python experience",
			skill_mapping=["python"],
			priority=RequirementPriority.MUST_HAVE,
			parent_id="compound-1",
		)
		assert req.parent_id == "compound-1"

	def test_weight_override_set(self):
		req = QuickRequirement(
			description="Python experience",
			skill_mapping=["python"],
			priority=RequirementPriority.MUST_HAVE,
			weight_override=1.5,
		)
		assert req.weight_override == 1.5

	def test_serialization_roundtrip(self):
		req = QuickRequirement(
			description="Python",
			skill_mapping=["python"],
			priority=RequirementPriority.MUST_HAVE,
			parent_id="compound-1",
			weight_override=1.5,
		)
		data = req.model_dump()
		restored = QuickRequirement(**data)
		assert restored.parent_id == "compound-1"
		assert restored.weight_override == 1.5


from claude_candidate.requirement_parser import compute_distillation_weights


class TestComputeDistillationWeights:
	"""Weight invariant: total weight before == total weight after distillation."""

	def test_non_distilled_requirements_unchanged(self):
		reqs = [
			QuickRequirement(description="Python", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE),
			QuickRequirement(description="React", skill_mapping=["react"], priority=RequirementPriority.NICE_TO_HAVE),
		]
		compute_distillation_weights(reqs)
		assert reqs[0].weight_override is None
		assert reqs[1].weight_override is None

	def test_distilled_pair_splits_weight(self):
		reqs = [
			QuickRequirement(description="Python", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
			QuickRequirement(description="React", skill_mapping=["react"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
		]
		compute_distillation_weights(reqs)
		assert reqs[0].weight_override == pytest.approx(1.5)
		assert reqs[1].weight_override == pytest.approx(1.5)

	def test_distilled_triple_splits_weight(self):
		reqs = [
			QuickRequirement(description="A", skill_mapping=["python"], priority=RequirementPriority.STRONG_PREFERENCE, parent_id="c2"),
			QuickRequirement(description="B", skill_mapping=["react"], priority=RequirementPriority.STRONG_PREFERENCE, parent_id="c2"),
			QuickRequirement(description="C", skill_mapping=["docker"], priority=RequirementPriority.STRONG_PREFERENCE, parent_id="c2"),
		]
		compute_distillation_weights(reqs)
		expected = 2.0 / 3
		for req in reqs:
			assert req.weight_override == pytest.approx(expected)

	def test_weight_invariant(self):
		reqs = [
			QuickRequirement(description="Python", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
			QuickRequirement(description="React", skill_mapping=["react"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
			QuickRequirement(description="Docker", skill_mapping=["docker"], priority=RequirementPriority.NICE_TO_HAVE),
		]
		compute_distillation_weights(reqs)
		total = 0.0
		for req in reqs:
			w = req.weight_override if req.weight_override is not None else PRIORITY_WEIGHT[req.priority]
			total += w
		assert total == pytest.approx(4.0)

	def test_mixed_groups(self):
		reqs = [
			QuickRequirement(description="A", skill_mapping=["python"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
			QuickRequirement(description="B", skill_mapping=["react"], priority=RequirementPriority.MUST_HAVE, parent_id="c1"),
			QuickRequirement(description="C", skill_mapping=["docker"], priority=RequirementPriority.NICE_TO_HAVE, parent_id="c2"),
			QuickRequirement(description="D", skill_mapping=["k8s"], priority=RequirementPriority.NICE_TO_HAVE, parent_id="c2"),
		]
		compute_distillation_weights(reqs)
		assert reqs[0].weight_override == pytest.approx(1.5)
		assert reqs[1].weight_override == pytest.approx(1.5)
		assert reqs[2].weight_override == pytest.approx(0.5)
		assert reqs[3].weight_override == pytest.approx(0.5)
