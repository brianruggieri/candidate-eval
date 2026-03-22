"""Optional ML enrichment layer. No-op if torch/sentence-transformers not installed."""


def enrichment_available() -> bool:
	"""Check if ML dependencies are available."""
	try:
		import torch  # noqa: F401
		import sentence_transformers  # noqa: F401
		return True
	except ImportError:
		return False
