"""
Manifest: Cryptographic hashing and manifest creation.

All hashing uses SHA-256 via Python's hashlib (standard library).
Files are read in binary mode and hashed in 8KB chunks for memory efficiency.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from pathlib import Path
from statistics import median

from claude_candidate.schemas.session_manifest import (
	CorpusStatistics,
	PipelineArtifactRecord,
	PublicRepoCorrelation,
	RedactionSummary,
	SessionFileRecord,
	SessionManifest,
)

CHUNK_SIZE = 8192


def hash_file(path: Path) -> str:
	"""SHA-256 hash of a file's contents, read in streaming chunks."""
	h = hashlib.sha256()
	with open(path, "rb") as f:
		while chunk := f.read(CHUNK_SIZE):
			h.update(chunk)
	return h.hexdigest()


def hash_string(content: str) -> str:
	"""SHA-256 hash of a string (UTF-8 encoded)."""
	return hashlib.sha256(content.encode("utf-8")).hexdigest()


def hash_json_stable(data: dict) -> str:
	"""
	SHA-256 hash of a JSON-serializable dict with stable key ordering.

	Uses json.dumps with sort_keys=True and no extra whitespace to ensure
	the same logical content always produces the same hash regardless of
	insertion order or formatting.
	"""
	canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
	return hash_string(canonical)


def generate_session_id(path: Path) -> str:
	"""
	Generate a stable session ID from file metadata.

	Format: YYYY-MM-DD_HH-MM-SS_{path_hash_prefix}
	"""
	stat = path.stat()
	created = datetime.fromtimestamp(stat.st_ctime)
	path_hash = hashlib.sha256(str(path).encode()).hexdigest()[:8]
	return f"{created.strftime('%Y-%m-%d_%H-%M-%S')}_{path_hash}"


def make_path_relative(path: Path) -> str:
	"""Strip absolute path prefix for privacy. Keep only from .claude/ onward."""
	parts = path.parts
	for i, part in enumerate(parts):
		if part == ".claude":
			return str(Path(*parts[i:]))
	# Fallback: relative to home
	try:
		return str(path.relative_to(Path.home()))
	except ValueError:
		return path.name


def scan_session_file(path: Path) -> SessionFileRecord:
	"""Create a SessionFileRecord for a single JSONL session file."""
	stat = path.stat()
	content = path.read_text(encoding="utf-8", errors="replace")
	lines = content.splitlines()
	word_count = len(content.split())
	token_estimate = int(word_count * 1.3)

	# Quick technology detection from first 50 lines
	techs_detected: list[str] = []
	tech_keywords = {
		"python": ["python", ".py", "pip ", "import "],
		"typescript": ["typescript", ".ts", ".tsx", "npm "],
		"javascript": ["javascript", ".js", "node "],
		"react": ["react", "jsx", "tsx", "useState"],
		"bash": ["bash", "#!/bin", "sh ", ".sh"],
		"git": ["git ", "commit", "branch", "merge"],
		"docker": ["docker", "dockerfile", "container"],
	}
	sample = "\n".join(lines[:50]).lower()
	for tech, keywords in tech_keywords.items():
		if any(kw in sample for kw in keywords):
			techs_detected.append(tech)

	# Detect project from path
	project_hint = None
	for i, part in enumerate(path.parts):
		if part == "projects" and i + 1 < len(path.parts):
			project_hint = path.parts[i + 1][:12]  # Truncated hash
			break

	flags: list[str] = []
	if stat.st_ctime != stat.st_mtime:
		flags.append("modified_after_creation")
	if stat.st_size > 100_000:
		flags.append("large_file")

	return SessionFileRecord(
		session_id=generate_session_id(path),
		original_path=make_path_relative(path),
		file_size_bytes=stat.st_size,
		line_count=len(lines),
		token_count_estimate=token_estimate,
		created_at=datetime.fromtimestamp(stat.st_ctime),
		modified_at=datetime.fromtimestamp(stat.st_mtime),
		hash_raw=hash_file(path),
		hash_sanitized=None,
		project_hint=project_hint,
		technologies_detected=techs_detected,
		flags=flags,
	)


def scan_sessions(paths: list[Path]) -> list[SessionFileRecord]:
	"""Scan multiple session files and create manifest records."""
	records = []
	for path in paths:
		if path.is_file():
			try:
				records.append(scan_session_file(path))
			except Exception as e:
				print(f"Warning: Could not scan {path}: {e}")
	return records


def compute_corpus_statistics(records: list[SessionFileRecord]) -> CorpusStatistics:
	"""Compute aggregate statistics from session records."""
	if not records:
		now = datetime.now()
		return CorpusStatistics(
			total_sessions=0,
			total_lines=0,
			total_tokens_estimate=0,
			date_range_start=now,
			date_range_end=now,
			date_span_days=0,
			sessions_per_month={},
			unique_projects=0,
			technologies_overview={},
			average_session_length_tokens=0,
			median_session_length_tokens=0,
			longest_session_tokens=0,
		)

	dates = [r.created_at for r in records]
	tokens = [r.token_count_estimate for r in records]

	# Sessions per month
	per_month: dict[str, int] = {}
	for r in records:
		key = r.created_at.strftime("%Y-%m")
		per_month[key] = per_month.get(key, 0) + 1

	# Technologies overview
	tech_counts: dict[str, int] = {}
	for r in records:
		for tech in r.technologies_detected:
			tech_counts[tech] = tech_counts.get(tech, 0) + 1

	# Unique projects
	projects = {r.project_hint for r in records if r.project_hint}

	return CorpusStatistics(
		total_sessions=len(records),
		total_lines=sum(r.line_count for r in records),
		total_tokens_estimate=sum(tokens),
		date_range_start=min(dates),
		date_range_end=max(dates),
		date_span_days=(max(dates) - min(dates)).days,
		sessions_per_month=per_month,
		unique_projects=len(projects),
		technologies_overview=tech_counts,
		average_session_length_tokens=sum(tokens) // len(tokens) if tokens else 0,
		median_session_length_tokens=int(median(tokens)) if tokens else 0,
		longest_session_tokens=max(tokens) if tokens else 0,
	)


def create_manifest(
	session_records: list[SessionFileRecord],
	redaction_summary: RedactionSummary | None = None,
	pipeline_artifacts: list[PipelineArtifactRecord] | None = None,
	public_correlations: list[PublicRepoCorrelation] | None = None,
	run_id: str | None = None,
	pipeline_version: str = "0.1.0",
) -> SessionManifest:
	"""
	Assemble a complete SessionManifest with self-integrity hash.
	"""
	if run_id is None:
		run_id = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

	if redaction_summary is None:
		redaction_summary = RedactionSummary(
			total_redactions=0,
			redactions_by_type={},
			sessions_with_redactions=0,
			sessions_without_redactions=len(session_records),
			heaviest_redaction_session=None,
			redaction_density=0.0,
			sample_redaction_types=[],
		)

	corpus_stats = compute_corpus_statistics(session_records)

	manifest = SessionManifest(
		manifest_id=str(uuid.uuid4()),
		generated_at=datetime.now(),
		pipeline_version=pipeline_version,
		run_id=run_id,
		sessions=session_records,
		corpus_statistics=corpus_stats,
		redaction_summary=redaction_summary,
		public_repo_correlations=public_correlations or [],
		pipeline_artifacts=pipeline_artifacts or [],
		manifest_hash=None,
	)

	# Compute self-integrity hash
	manifest_dict = manifest.model_dump()
	manifest_dict.pop("manifest_hash", None)
	manifest.manifest_hash = hash_json_stable(manifest_dict)

	return manifest


def verify_manifest(manifest: SessionManifest) -> dict:
	"""
	Verify a manifest's internal consistency.

	Returns dict with 'valid' bool and 'errors' list.
	"""
	errors: list[str] = []

	# Check self-hash
	stored_hash = manifest.manifest_hash
	manifest_dict = manifest.model_dump()
	manifest_dict.pop("manifest_hash", None)
	computed_hash = hash_json_stable(manifest_dict)

	if stored_hash and stored_hash != computed_hash:
		errors.append(
			f"Manifest hash mismatch: stored={stored_hash[:16]}... computed={computed_hash[:16]}..."
		)

	# Check unique session IDs
	ids = [s.session_id for s in manifest.sessions]
	if len(ids) != len(set(ids)):
		errors.append("Duplicate session IDs detected")

	# Check corpus stats consistency
	stats = manifest.corpus_statistics
	if stats.total_sessions != len(manifest.sessions):
		errors.append(
			f"Session count mismatch: stats={stats.total_sessions} actual={len(manifest.sessions)}"
		)

	return {"valid": len(errors) == 0, "errors": errors}


def verify_sessions_on_disk(
	manifest: SessionManifest,
	search_dirs: list[Path],
) -> list[dict]:
	"""
	Verify that session files on disk match their manifest records.

	Returns list of {session_id, status, detail} dicts.
	"""
	# Build lookup of all files in search dirs
	file_hashes: dict[str, str] = {}
	for d in search_dirs:
		if d.is_dir():
			for f in d.rglob("*.jsonl"):
				file_hashes[hash_file(f)] = str(f)

	results = []
	for record in manifest.sessions:
		if record.hash_raw in file_hashes:
			results.append(
				{
					"session_id": record.session_id,
					"status": "match",
					"detail": f"Found at {file_hashes[record.hash_raw]}",
				}
			)
		else:
			results.append(
				{
					"session_id": record.session_id,
					"status": "missing",
					"detail": "No matching file found on disk",
				}
			)

	return results
