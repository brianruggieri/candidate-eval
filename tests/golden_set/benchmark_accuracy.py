#!/usr/bin/env python3
"""Benchmark skill matching accuracy and regression against corpus tiers.

Usage:
  python tests/golden_set/benchmark_accuracy.py                  # golden tier (default)
  python tests/golden_set/benchmark_accuracy.py --tier regression --corpus-dir tests/regression_corpus
  python tests/golden_set/benchmark_accuracy.py --tier all
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from claude_candidate.quick_match import QuickMatchEngine
from claude_candidate.schemas.job_requirements import QuickRequirement
from claude_candidate.schemas.merged_profile import MergedEvidenceProfile

GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]


def grade_distance(actual: str, expected: str) -> int:
	try:
		return GRADE_ORDER.index(actual) - GRADE_ORDER.index(expected)
	except ValueError:
		return 99


def load_profile(data_dir: Path) -> MergedEvidenceProfile:
	from claude_candidate.schemas.candidate_profile import CandidateProfile
	from claude_candidate.merger import merge_candidate_only, merge_with_curated
	from claude_candidate.schemas.curated_resume import CuratedResume
	cp = CandidateProfile.from_json((data_dir / "candidate_profile.json").read_text())
	curated_path = data_dir / "curated_resume.json"
	if curated_path.exists():
		curated = CuratedResume.model_validate(json.loads(curated_path.read_text()))
		return merge_with_curated(cp, curated)
	return merge_candidate_only(cp)


def _grade_to_midpoint(grade: str) -> float:
	midpoints = {"A+": 97, "A": 92, "A-": 87, "B+": 82, "B": 77, "B-": 72,
	             "C+": 67, "C": 62, "C-": 57, "D": 50, "F": 25}
	return midpoints.get(grade, 50)


def run_golden(golden_dir: Path, profile: MergedEvidenceProfile) -> dict:
	"""Run accuracy benchmark on the golden set. Returns result dict."""
	postings_dir = golden_dir / "postings"
	expected_path = golden_dir / "expected_grades.json"
	history_path = golden_dir / "benchmark_history.jsonl"

	expected = json.loads(expected_path.read_text())
	engine = QuickMatchEngine(profile)

	results = {}
	taxonomy_gaps = 0
	total_must_haves = 0
	met_must_haves = 0

	for posting_file in sorted(postings_dir.glob("*.json")):
		slug = posting_file.stem
		if slug not in expected:
			continue
		data = json.loads(posting_file.read_text())
		reqs = [QuickRequirement(**r) for r in data.get("requirements", []) if r.get("skill_mapping")]
		assessment = engine.assess(
			requirements=reqs,
			company=data.get("company", "Unknown"),
			title=data.get("title", "Unknown"),
			posting_url=data.get("url"),
			source="golden_set",
			seniority=data.get("seniority", "unknown"),
		)
		exp_grade = expected[slug]["expected"]
		actual_grade = assessment.overall_grade
		delta = grade_distance(actual_grade, exp_grade)
		score_pct = round(assessment.overall_score * 100, 1)
		for detail in assessment.skill_matches:
			if detail.priority == "must_have":
				total_must_haves += 1
				if detail.match_status in ("strong_match", "exceeds"):
					met_must_haves += 1
				elif detail.match_status == "no_evidence":
					taxonomy_gaps += 1
		results[slug] = {"actual": actual_grade, "expected": exp_grade, "delta": delta, "score": score_pct,
		                  "skill_score": round(assessment.skill_match.score * 100, 1)}

	graded = {k: v for k, v in results.items() if v["expected"] != "?"}
	exact = sum(1 for r in graded.values() if r["delta"] == 0)
	within_1 = sum(1 for r in graded.values() if abs(r["delta"]) <= 1)
	off_by_2 = len(graded) - within_1
	avg_delta = sum(r["delta"] for r in graded.values()) / max(len(graded), 1)
	must_have_pct = round(met_must_haves / max(total_must_haves, 1) * 100)

	print(f"=== ACCURACY BENCHMARK ({len(results)} postings, {len(graded)} graded) ===")
	if graded:
		print(f"Exact match: {exact}/{len(graded)} | Within 1: {within_1}/{len(graded)} | Off by 2+: {off_by_2}/{len(graded)}")
		print(f"Avg grade delta: {avg_delta:+.1f}")
	print(f"Must-have coverage: {must_have_pct}% ({met_must_haves}/{total_must_haves})")
	print()
	if taxonomy_gaps > len(results) * 0.1:
		print(f"  >>> FOCUS: Stage 1 (Taxonomy) — {taxonomy_gaps} must-have no_evidence gaps")
	elif must_have_pct < 70:
		print(f"  >>> FOCUS: Stage 2 (Requirement handling) — must-have coverage {must_have_pct}%")
	else:
		print("  >>> FOCUS: Stage 3 (Calibration) — fine-tune weights and thresholds")
	print()
	print("ALL POSTINGS:")
	for slug, r in sorted(results.items(), key=lambda x: x[1]["score"], reverse=True):
		exp_str = r["expected"] if r["expected"] != "?" else "?"
		delta_str = f"delta={r['delta']:+d}" if r["expected"] != "?" else "ungraded"
		print(f"  {slug:.<55} actual={r['actual']:>3} expected={exp_str:>3} {delta_str} score={r['score']}%")

	if graded:
		print()
		worst = sorted(graded.items(), key=lambda x: abs(x[1]["delta"]), reverse=True)[:5]
		print("WORST MISMATCHES:")
		for slug, r in worst:
			if abs(r["delta"]) > 1:
				print(f"  {slug:.<55} actual={r['actual']:>3} expected={r['expected']:>3} delta={r['delta']:+d} score={r['score']}%")

	entry = {"timestamp": datetime.now().isoformat(), "tier": "golden", "exact_match": exact,
	          "within_1": within_1, "off_by_2_plus": off_by_2, "avg_delta": round(avg_delta, 2),
	          "must_have_pct": must_have_pct, "postings": results}
	with open(history_path, "a") as f:
		f.write(json.dumps(entry) + "\n")

	return {"tier": "golden", "exact_match": exact, "within_1": within_1,
	         "off_by_2_plus": off_by_2, "postings": len(results), "graded": len(graded)}


def run_regression(corpus_dir: Path, profile: MergedEvidenceProfile) -> dict:
	"""Run regression benchmark on the regression corpus. Returns stability result dict."""
	postings_dir = corpus_dir / "postings"
	grades_path = corpus_dir / "expected_grades.json"
	history_path = corpus_dir / "benchmark_history.jsonl"

	corpus_dir.mkdir(parents=True, exist_ok=True)

	if not grades_path.exists():
		print("=== REGRESSION BENCHMARK (0 postings) ===")
		print("No regression_corpus/expected_grades.json found.")
		result = {"tier": "regression", "total": 0, "stable": 0, "regressions": 0,
		           "improvements": 0, "stability_pct": 100.0, "changed": []}
		with open(history_path, "a") as f:
			f.write(json.dumps({"timestamp": datetime.now().isoformat(), **result}) + "\n")
		return result

	expected = json.loads(grades_path.read_text())
	if not expected:
		result = {"tier": "regression", "total": 0, "stable": 0, "regressions": 0,
		           "improvements": 0, "stability_pct": 100.0, "changed": []}
		with open(history_path, "a") as f:
			f.write(json.dumps({"timestamp": datetime.now().isoformat(), **result}) + "\n")
		return result

	engine = QuickMatchEngine(profile)
	changed = []
	total = 0

	for posting_file in sorted(postings_dir.glob("*.json")):
		slug = posting_file.stem
		if slug not in expected:
			continue
		total += 1
		data = json.loads(posting_file.read_text())
		reqs = [QuickRequirement(**r) for r in data.get("requirements", []) if r.get("skill_mapping")]
		assessment = engine.assess(
			requirements=reqs,
			company=data.get("company", "Unknown"),
			title=data.get("title", "Unknown"),
			posting_url=data.get("url"),
			source="regression",
			seniority=data.get("seniority", "unknown"),
		)
		stored_grade = expected[slug]["grade"]
		current_grade = assessment.overall_grade
		try:
			current_idx = GRADE_ORDER.index(current_grade)
			stored_idx = GRADE_ORDER.index(stored_grade)
			dist = abs(current_idx - stored_idx)
		except ValueError:
			current_idx = None
			stored_idx = None
			dist = 99
		if dist >= 1 and current_idx is not None and stored_idx is not None:
			direction = "improvement" if current_idx < stored_idx else "regression"
			changed.append({"posting_id": slug, "stored_grade": stored_grade, "current_grade": current_grade, "direction": direction})

	stable = total - len(changed)
	regressions = sum(1 for c in changed if c["direction"] == "regression")
	improvements = sum(1 for c in changed if c["direction"] == "improvement")
	stability_pct = round(stable / max(total, 1) * 100, 1)

	print(f"=== REGRESSION BENCHMARK ({total} postings) ===")
	print(f"Stable: {stable}/{total} ({stability_pct}%)")
	if regressions:
		print(f"Regressions: {regressions}")
	if improvements:
		print(f"Improvements: {improvements}")
	if changed:
		print("\nCHANGED:")
		for c in changed:
			arrow = "↑" if c["direction"] == "improvement" else "↓"
			print(f"  {c['posting_id']:<55} {c['stored_grade']} → {c['current_grade']} {arrow}")

	result = {"tier": "regression", "total": total, "stable": stable, "regressions": regressions,
	           "improvements": improvements, "stability_pct": stability_pct, "changed": changed}
	with open(history_path, "a") as f:
		f.write(json.dumps({"timestamp": datetime.now().isoformat(), **result}) + "\n")
	return result


def main():
	parser = argparse.ArgumentParser()
	parser.add_argument("--tier", choices=["golden", "regression", "all"], default="golden")
	parser.add_argument("--data-dir", default=None, help="Override ~/.claude-candidate/ for profile loading")
	parser.add_argument("--corpus-dir", default="tests/regression_corpus", help="Path to regression corpus (for --tier regression)")
	args = parser.parse_args()

	data_dir = Path(args.data_dir) if args.data_dir else Path.home() / ".claude-candidate"
	corpus_dir = Path(args.corpus_dir)
	golden_dir = Path("tests/golden_set")

	profile = load_profile(data_dir)

	if args.tier == "golden":
		result = run_golden(golden_dir, profile)
		graded = result.get("graded", 0)
		within_1 = result.get("within_1", 0)
		if graded and within_1 == graded:
			print("\n*** ALL GRADED POSTINGS WITHIN TOLERANCE ***")
			sys.exit(0)
		elif not graded:
			print("\n*** No graded postings. Fill in expected_grades.json. ***")
			sys.exit(0)
		else:
			sys.exit(1)

	elif args.tier == "regression":
		result = run_regression(corpus_dir, profile)
		print(json.dumps(result, indent=2))
		sys.exit(0)

	elif args.tier == "all":
		golden_result = run_golden(golden_dir, profile)
		print()
		regression_result = run_regression(corpus_dir, profile)
		combined = {"golden": golden_result, "regression": regression_result}
		print(json.dumps(combined, indent=2))
		graded = golden_result.get("graded", 0)
		within_1 = golden_result.get("within_1", 0)
		sys.exit(0 if (not graded or within_1 == graded) else 1)


if __name__ == "__main__":
	main()
