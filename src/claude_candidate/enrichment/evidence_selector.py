"""Embedding-based evidence snippet relevance scoring."""
from __future__ import annotations


class EvidenceSelector:
	"""Select the most relevant evidence snippet for a skill."""

	def __init__(self):
		from sentence_transformers import SentenceTransformer
		self._model = SentenceTransformer("all-MiniLM-L6-v2")

	def select_best_snippet(
		self,
		skill_label: str,
		candidates: list[str],
	) -> str | None:
		"""Pick the most relevant snippet for a skill from candidates.

		Pre-filters: drops snippets < 100 chars and pure questions.
		Scores by cosine similarity to skill label embedding.
		"""
		import numpy as np
		from sklearn.metrics.pairwise import cosine_similarity

		# Pre-filter
		filtered = [
			s for s in candidates
			if len(s) >= 100 and not s.strip().endswith("?")
		]
		if not filtered:
			return candidates[0] if candidates else None

		# Embed and score
		skill_emb = self._model.encode([skill_label], convert_to_numpy=True)
		candidate_embs = self._model.encode(filtered, convert_to_numpy=True)
		similarities = cosine_similarity(skill_emb, candidate_embs)[0]
		best_idx = int(np.argmax(similarities))
		return filtered[best_idx]
