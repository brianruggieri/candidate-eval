"""CLI commands for regression corpus management.

Registered on the main CLI group via: main.add_command(corpus)
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import click

# Canonical grade ordering — 11 grades, matches benchmark_accuracy.py
GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]

# Paths relative to the repo root (where the CLI is run from)
_REGRESSION_DIR = Path("tests/regression_corpus")
_GOLDEN_DIR = Path("tests/golden_set")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_slug(company: str, title: str, date: datetime) -> str:
	"""Generate a filesystem-safe slug: {company}-{title}-{YYYY-MM-DD}."""
	def _slugify(s: str, max_len: int) -> str:
		s = s.lower()
		s = re.sub(r"[^a-z0-9]+", "-", s)
		s = re.sub(r"-+", "-", s).strip("-")
		return s[:max_len].rstrip("-")

	company_slug = _slugify(company, 20)
	title_slug = _slugify(title, 40)
	date_str = date.strftime("%Y-%m-%d")
	return f"{company_slug}-{title_slug}-{date_str}"


def load_regression_grades(corpus_dir: Path) -> dict[str, Any]:
	"""Load regression_corpus/expected_grades.json, returning {} if absent."""
	grades_path = corpus_dir / "expected_grades.json"
	if not grades_path.exists():
		return {}
	return json.loads(grades_path.read_text())


def save_regression_grades(corpus_dir: Path, grades: dict[str, Any]) -> None:
	"""Write regression_corpus/expected_grades.json."""
	(corpus_dir / "expected_grades.json").write_text(
		json.dumps(grades, indent=2, ensure_ascii=False)
	)


# ---------------------------------------------------------------------------
# Click group
# ---------------------------------------------------------------------------


@click.group()
def corpus() -> None:
	"""Manage the regression corpus of auto-graded job postings."""


@corpus.command("export")
@click.option("--db", "db_path", default=None, help="Path to assessments.db")
@click.option("--since", "since_days", type=int, default=None, help="Only export postings from last N days")
@click.option("--limit", "limit", type=int, default=None, help="Max postings to export")
@click.option("--corpus-dir", "corpus_dir_override", default=None, help="Override regression corpus directory (for tests)")
def export_cmd(db_path: str | None, since_days: int | None, limit: int | None, corpus_dir_override: str | None) -> None:
	"""Export cached job postings from assessments.db into the regression corpus."""
	import asyncio
	from claude_candidate.storage import AssessmentStore

	corpus_dir = Path(corpus_dir_override) if corpus_dir_override else _REGRESSION_DIR
	postings_dir = corpus_dir / "postings"
	postings_dir.mkdir(parents=True, exist_ok=True)

	data_dir = Path(db_path).parent if db_path else Path.home() / ".claude-candidate"
	db = Path(db_path) if db_path else data_dir / "assessments.db"

	loop = asyncio.new_event_loop()
	try:
		store = AssessmentStore(db)
		loop.run_until_complete(store.initialize())

		since_dt = None
		if since_days is not None:
			from datetime import timedelta
			since_dt = datetime.now() - timedelta(days=since_days)

		postings = loop.run_until_complete(store.list_cached_postings(since=since_dt, limit=limit))
		assessments = loop.run_until_complete(store.list_assessments(limit=10000))
	finally:
		loop.run_until_complete(store.close())
		loop.close()

	# Build url → latest assessment map
	url_to_assessment: dict[str, Any] = {}
	for a in assessments:
		url = a.get("posting_url")
		if not url:
			continue
		if url not in url_to_assessment or a.get("assessed_at", "") > url_to_assessment[url].get("assessed_at", ""):
			url_to_assessment[url] = a

	# Load existing grades for dedup
	grades = load_regression_grades(corpus_dir)
	existing_url_hashes = {v["url_hash"] for v in grades.values()}

	exported = 0
	skipped = 0
	for posting_row in postings:
		url_hash = posting_row["url_hash"]
		url = posting_row["url"]
		posting_data = posting_row["data"]

		if url_hash in existing_url_hashes:
			click.echo(f"  skip (already exported): {url}")
			skipped += 1
			continue

		assessment = url_to_assessment.get(url)
		if not assessment:
			continue

		# Enrich posting_data with url if missing
		posting_data = dict(posting_data)
		posting_data.setdefault("url", url)

		company = posting_data.get("company") or assessment.get("company_name") or "unknown"
		title = posting_data.get("title") or assessment.get("job_title") or "unknown"
		slug = make_slug(company, title, datetime.now())

		# Resolve slug collisions
		base_slug = slug
		if slug in grades:
			# Different URL — append hash prefix
			slug = f"{base_slug}-{url_hash[:6]}"
			counter = 2
			while slug in grades:
				slug = f"{base_slug}-{url_hash[:6]}-{counter}"
				counter += 1

		# Write posting JSON
		posting_path = postings_dir / f"{slug}.json"
		posting_path.write_text(json.dumps(posting_data, indent=2, ensure_ascii=False))

		# Append to grades
		overall_grade = None
		if isinstance(assessment.get("data"), dict):
			overall_grade = assessment["data"].get("overall_grade")
		overall_grade = overall_grade or assessment.get("overall_grade") or "?"

		grades[slug] = {
			"grade": overall_grade,
			"source": "auto",
			"assessment_id": assessment.get("assessment_id", ""),
			"url_hash": url_hash,
			"exported_at": datetime.now().isoformat(),
		}
		existing_url_hashes.add(url_hash)
		click.echo(f"  exported: {slug}  grade={overall_grade}")
		exported += 1

	save_regression_grades(corpus_dir, grades)
	click.echo(f"\nExported {exported} posting(s). Skipped {skipped} duplicate(s).")


@corpus.command("list")
@click.option("--corpus-dir", "corpus_dir_override", default=None)
def list_cmd(corpus_dir_override: str | None) -> None:
	"""List all postings in the regression corpus."""
	corpus_dir = Path(corpus_dir_override) if corpus_dir_override else _REGRESSION_DIR
	grades = load_regression_grades(corpus_dir)

	if not grades:
		click.echo("No postings in regression corpus.")
		return

	header = f"{'posting_id':<55} {'company':<20} {'title':<30} {'grade':<6} {'exported_at'}"
	click.echo(header)
	click.echo("-" * len(header))

	for posting_id, entry in sorted(grades.items()):
		posting_path = corpus_dir / "postings" / f"{posting_id}.json"
		if posting_path.exists():
			data = json.loads(posting_path.read_text())
			company = (data.get("company") or "")[:20]
			title = (data.get("title") or "")[:30]
		else:
			company = "[file missing]"
			title = "[file missing]"

		grade = entry.get("grade", "?")
		exported_at = entry.get("exported_at", "")[:16].replace("T", " ")
		click.echo(f"{posting_id:<55} {company:<20} {title:<30} {grade:<6} {exported_at}")


@corpus.command("remove")
@click.argument("posting_id")
@click.option("--corpus-dir", "corpus_dir_override", default=None)
def remove_cmd(posting_id: str, corpus_dir_override: str | None) -> None:
	"""Remove a posting from the regression corpus."""
	corpus_dir = Path(corpus_dir_override) if corpus_dir_override else _REGRESSION_DIR
	grades = load_regression_grades(corpus_dir)
	posting_path = corpus_dir / "postings" / f"{posting_id}.json"

	has_file = posting_path.exists()
	has_grade = posting_id in grades

	if not has_file and not has_grade:
		click.echo(f"Not found in regression corpus: {posting_id}")
		return

	if has_file:
		posting_path.unlink()
	else:
		click.echo(f"Warning: posting file missing for {posting_id} (grades entry still removed)")

	if has_grade:
		del grades[posting_id]
		save_regression_grades(corpus_dir, grades)
	else:
		click.echo(f"Warning: grades entry missing for {posting_id} (file still deleted)")

	click.echo(f"Removed: {posting_id}")


@corpus.command("promote")
@click.argument("posting_id")
@click.option("--corpus-dir", "corpus_dir_override", default=None)
@click.option("--golden-dir", "golden_dir_override", default=None)
def promote_cmd(posting_id: str, corpus_dir_override: str | None, golden_dir_override: str | None) -> None:
	"""Promote a regression corpus posting to the golden set with a human grade."""
	corpus_dir = Path(corpus_dir_override) if corpus_dir_override else _REGRESSION_DIR
	golden_dir = Path(golden_dir_override) if golden_dir_override else _GOLDEN_DIR

	# Step 1: read posting file
	posting_path = corpus_dir / "postings" / f"{posting_id}.json"
	if not posting_path.exists():
		raise click.ClickException(f"Posting file not found: {posting_path}")

	# Step 2: read grades entry
	grades = load_regression_grades(corpus_dir)
	if posting_id not in grades:
		raise click.ClickException(
			f"Grades entry not found for {posting_id}. "
			f"Run `corpus remove {posting_id}` to clean up the orphaned file."
		)

	posting_data = json.loads(posting_path.read_text())
	auto_grade = grades[posting_id]["grade"]

	# Step 3: show summary
	click.echo(f"\nPosting:    {posting_data.get('company', '?')} — {posting_data.get('title', '?')}")
	click.echo(f"Auto grade: {auto_grade}")
	click.echo(f"Preview:    {posting_data.get('description', '')[:300]}")
	click.echo()

	# Step 4: prompt for human grade
	valid_grades = set(GRADE_ORDER)
	human_grade = None
	while human_grade is None:
		raw = click.prompt(
			"Enter human grade (A+/A/A-/B+/B/B-/C+/C/C-/D/F)",
			default="",
			show_default=False,
		)
		if raw.strip().upper() in valid_grades:
			human_grade = raw.strip().upper()
		elif raw == "":
			raise click.Abort()
		else:
			click.echo(f"Invalid grade '{raw}'. Valid: {'/'.join(GRADE_ORDER)}")

	# Step 5: check golden set for conflicts
	golden_grades_path = golden_dir / "expected_grades.json"
	golden_grades: dict[str, Any] = {}
	if golden_grades_path.exists():
		golden_grades = json.loads(golden_grades_path.read_text())
	if posting_id in golden_grades:
		raise click.ClickException(
			f"{posting_id} already exists in golden set. "
			"Remove it from golden_set/expected_grades.json first if you want to replace it."
		)

	# Step 6: copy posting JSON to golden set
	golden_postings_dir = golden_dir / "postings"
	golden_postings_dir.mkdir(parents=True, exist_ok=True)
	shutil.copy2(posting_path, golden_postings_dir / f"{posting_id}.json")

	# Step 7: append to golden set expected_grades.json (existing nested format)
	golden_grades[posting_id] = {"expected": human_grade, "rationale": "human-promoted"}
	golden_grades_path.write_text(json.dumps(golden_grades, indent=2, ensure_ascii=False))

	# Step 8-9: remove from regression corpus
	del grades[posting_id]
	save_regression_grades(corpus_dir, grades)
	posting_path.unlink()

	click.echo(f"\nPromoted {posting_id} → golden set with grade {human_grade}")
