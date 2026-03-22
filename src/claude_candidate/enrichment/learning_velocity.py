"""Enhanced sophistication classification using embeddings."""
from __future__ import annotations


class SophisticationClassifier:
	"""Classify sophistication of agentic tool usage using embeddings."""

	def __init__(self):
		from sentence_transformers import SentenceTransformer
		self._model = SentenceTransformer("all-MiniLM-L6-v2")

	def classify_agent_prompt(self, prompt: str) -> int:
		"""Classify an agent dispatch prompt's sophistication 0-3.

		0: no clear intent
		1: basic single-purpose task
		2: multi-step or typed task
		3: complex orchestration with plan references
		"""
		import numpy as np
		from sklearn.metrics.pairwise import cosine_similarity

		# Define sophistication archetypes
		archetypes = [
			"simple task, do one thing",
			"explore the codebase and report findings",
			"implement this specific feature following the plan with tests",
			"orchestrate multiple agents with worktree isolation and plan-driven execution",
		]

		prompt_emb = self._model.encode([prompt[:500]], convert_to_numpy=True)
		arch_embs = self._model.encode(archetypes, convert_to_numpy=True)
		similarities = cosine_similarity(prompt_emb, arch_embs)[0]
		return int(np.argmax(similarities))

	def classify_task_description(self, description: str) -> int:
		"""Classify a task description's decomposition quality 0-3."""
		import numpy as np
		from sklearn.metrics.pairwise import cosine_similarity

		archetypes = [
			"do the thing",
			"update the file to fix the bug",
			"phase A: update schema, phase B: add migration",
			"task with dependency chain, file-level specificity, and phased execution",
		]

		desc_emb = self._model.encode([description[:500]], convert_to_numpy=True)
		arch_embs = self._model.encode(archetypes, convert_to_numpy=True)
		similarities = cosine_similarity(desc_emb, arch_embs)[0]
		return int(np.argmax(similarities))
