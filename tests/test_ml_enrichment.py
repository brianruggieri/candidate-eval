"""Tests for ML enrichment layer."""

import pytest

from claude_candidate.enrichment import enrichment_available


class TestEnrichmentGate:
	def test_returns_bool(self):
		result = enrichment_available()
		assert isinstance(result, bool)


@pytest.mark.skipif(
	not enrichment_available(),
	reason="ML dependencies not installed",
)
class TestEmbeddingMatcher:
	def test_loads(self):
		from claude_candidate.enrichment.embedding_matcher import EmbeddingMatcher

		matcher = EmbeddingMatcher()
		assert matcher is not None

	def test_match_known_skill(self):
		from claude_candidate.enrichment.embedding_matcher import EmbeddingMatcher

		matcher = EmbeddingMatcher()
		result = matcher.match_skill("containerization with Docker")
		assert result is not None
		name, score = result
		assert name == "docker"
		assert score > 0.4

	def test_match_returns_none_for_nonsense(self):
		from claude_candidate.enrichment.embedding_matcher import EmbeddingMatcher

		matcher = EmbeddingMatcher()
		result = matcher.match_skill("xyzzy plugh", threshold=0.8)
		assert result is None


@pytest.mark.skipif(
	not enrichment_available(),
	reason="ML dependencies not installed",
)
class TestEvidenceSelector:
	def test_loads(self):
		from claude_candidate.enrichment.evidence_selector import EvidenceSelector

		selector = EvidenceSelector()
		assert selector is not None

	def test_selects_relevant_snippet(self):
		from claude_candidate.enrichment.evidence_selector import EvidenceSelector

		selector = EvidenceSelector()
		candidates = [
			"Hello, I'd like to help you today.",
			"We configured the Docker container with multi-stage builds and optimized the image size from 1.2GB to 340MB using Alpine base.",
			"Let me know if you need anything else.",
		]
		best = selector.select_best_snippet("docker containerization", candidates)
		assert best is not None
		assert "Docker" in best


@pytest.mark.skipif(
	not enrichment_available(),
	reason="ML dependencies not installed",
)
class TestSophisticationClassifier:
	def test_loads(self):
		from claude_candidate.enrichment.learning_velocity import SophisticationClassifier

		classifier = SophisticationClassifier()
		assert classifier is not None

	def test_classifies_simple_prompt(self):
		from claude_candidate.enrichment.learning_velocity import SophisticationClassifier

		classifier = SophisticationClassifier()
		score = classifier.classify_agent_prompt("fix the bug")
		assert score in (0, 1)

	def test_classifies_complex_prompt(self):
		from claude_candidate.enrichment.learning_velocity import SophisticationClassifier

		classifier = SophisticationClassifier()
		score = classifier.classify_agent_prompt(
			"Orchestrate three parallel agents in worktrees, each executing "
			"a phase from the plan at .claude/plans/feature.md with TDD"
		)
		assert score >= 2
