"""Semantic skill matching using sentence-transformers embeddings."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np


class EmbeddingMatcher:
	"""Matches skill mentions to canonical taxonomy entries using embeddings."""

	def __init__(self, cache_dir: Path | None = None):
		from sentence_transformers import SentenceTransformer

		self._model = SentenceTransformer("all-MiniLM-L6-v2")
		self._cache_dir = cache_dir or Path.home() / ".claude-candidate"
		self._cache_dir.mkdir(parents=True, exist_ok=True)
		self._taxonomy_embeddings: np.ndarray | None = None
		self._taxonomy_names: list[str] = []
		self._load_taxonomy()

	def _load_taxonomy(self) -> None:
		"""Load and embed taxonomy entries (cached)."""
		taxonomy_path = Path(__file__).parent.parent / "data" / "taxonomy.json"
		taxonomy = json.loads(taxonomy_path.read_text())

		# Build enriched text for each entry
		entries = []
		names = []
		for name, info in sorted(taxonomy.items()):
			aliases = " ".join(info.get("aliases", []))
			category = info.get("category", "")
			related = " ".join(info.get("related", []))
			patterns = " ".join(info.get("content_patterns", []))
			text = f"{name} {aliases} {category} {related} {patterns}"
			entries.append(text)
			names.append(name)

		self._taxonomy_names = names

		# Check cache
		taxonomy_hash = hashlib.md5(taxonomy_path.read_bytes()).hexdigest()
		cache_path = self._cache_dir / f"embeddings_cache_{taxonomy_hash}.npz"

		if cache_path.exists():
			data = np.load(cache_path)
			self._taxonomy_embeddings = data["embeddings"]
		else:
			self._taxonomy_embeddings = self._model.encode(entries, convert_to_numpy=True)
			np.savez(cache_path, embeddings=self._taxonomy_embeddings)

	def match_skill(self, text: str, threshold: float = 0.4) -> tuple[str, float] | None:
		"""Match a text mention to the best canonical skill.

		Returns (canonical_name, similarity) or None if below threshold.
		"""
		if self._taxonomy_embeddings is None:
			return None

		from sklearn.metrics.pairwise import cosine_similarity

		text_embedding = self._model.encode([text], convert_to_numpy=True)
		similarities = cosine_similarity(text_embedding, self._taxonomy_embeddings)[0]
		best_idx = int(np.argmax(similarities))
		best_score = float(similarities[best_idx])

		if best_score >= threshold:
			return self._taxonomy_names[best_idx], best_score
		return None

	def upgrade_matches(
		self,
		skills: dict[str, Any],
		threshold: float = 0.4,
	) -> dict[str, Any]:
		"""Re-score low-confidence skill matches using embeddings.

		For skills with confidence < 0.7, try semantic matching.
		Returns updated skills dict.
		"""
		# This is a placeholder for the upgrade logic
		# In practice, you'd iterate skills, re-match low-confidence ones
		return skills
