#!/usr/bin/env python3
"""Benchmark skill matching accuracy against golden set."""

import json
import sys
from datetime import datetime
from pathlib import Path

from claude_candidate.quick_match import QuickMatchEngine
from claude_candidate.schemas.job_requirements import QuickRequirement
from claude_candidate.schemas.merged_profile import MergedEvidenceProfile


GRADE_ORDER = ["A+", "A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "F"]

def grade_distance(actual: str, expected: str) -> int:
    """Ordinal distance between two grades. Positive = actual is lower."""
    try:
        return GRADE_ORDER.index(actual) - GRADE_ORDER.index(expected)
    except ValueError:
        return 99


def load_profile() -> MergedEvidenceProfile:
    """Load merged profile from standard location."""
    profile_path = Path.home() / ".claude-candidate" / "merged_profile.json"
    if not profile_path.exists():
        # Fallback to generating on the fly
        from claude_candidate.schemas.candidate_profile import CandidateProfile
        cp_path = Path.home() / ".claude-candidate" / "candidate_profile.json"
        curated_path = Path.home() / ".claude-candidate" / "curated_resume.json"
        cp = CandidateProfile.from_json(cp_path.read_text())
        curated = json.loads(curated_path.read_text())
        from claude_candidate.merger import merge_with_curated
        return merge_with_curated(
            cp,
            curated.get("curated_skills", []),
            total_years=curated.get("total_years_experience"),
            education=curated.get("education", []),
        )
    return MergedEvidenceProfile.from_json(profile_path.read_text())


def _grade_to_midpoint(grade: str) -> float:
    """Approximate midpoint score for a grade."""
    midpoints = {"A+": 97, "A": 92, "A-": 87, "B+": 82, "B": 77, "B-": 72,
                 "C+": 67, "C": 62, "C-": 57, "D": 50, "F": 25}
    return midpoints.get(grade, 50)


def run_benchmark():
    golden_dir = Path("tests/golden_set")
    postings_dir = golden_dir / "postings"
    expected_path = golden_dir / "expected_grades.json"
    history_path = golden_dir / "benchmark_history.jsonl"

    expected = json.loads(expected_path.read_text())
    profile = load_profile()
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
        # Skip requirements with empty skill_mapping (e.g. education-only rows)
        reqs = []
        for r in data.get("requirements", []):
            if not r.get("skill_mapping"):
                continue
            reqs.append(QuickRequirement(**r))

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

        # Count must-have coverage
        for detail in assessment.skill_matches:
            if detail.priority == "must_have":
                total_must_haves += 1
                if detail.match_status in ("strong_match", "exceeds"):
                    met_must_haves += 1
                elif detail.match_status == "no_evidence":
                    taxonomy_gaps += 1

        results[slug] = {
            "actual": actual_grade,
            "expected": exp_grade,
            "delta": delta,
            "score": score_pct,
            "skill_score": round(assessment.skill_match.score * 100, 1),
        }

    # Compute summary stats
    graded = {k: v for k, v in results.items() if v["expected"] != "?"}
    exact = sum(1 for r in graded.values() if r["delta"] == 0)
    within_1 = sum(1 for r in graded.values() if abs(r["delta"]) <= 1)
    off_by_2 = len(graded) - within_1
    avg_delta = sum(r["delta"] for r in graded.values()) / max(len(graded), 1)

    # Must-have coverage
    must_have_pct = round(met_must_haves / max(total_must_haves, 1) * 100)

    # Print report
    print(f"=== ACCURACY BENCHMARK ({len(results)} postings, {len(graded)} graded) ===")
    if graded:
        print(f"Exact match: {exact}/{len(graded)} | Within 1 grade: {within_1}/{len(graded)} | Off by 2+: {off_by_2}/{len(graded)}")
        print(f"Avg grade delta: {avg_delta:+.1f}")
    print(f"Must-have coverage: {must_have_pct}% ({met_must_haves}/{total_must_haves})")
    print()

    # Stage diagnosis
    if taxonomy_gaps > len(results) * 0.1:
        print(f"  >>> FOCUS: Stage 1 (Taxonomy) — {taxonomy_gaps} must-have no_evidence gaps")
    elif must_have_pct < 70:
        print(f"  >>> FOCUS: Stage 2 (Requirement handling) — must-have coverage {must_have_pct}%")
    else:
        print(f"  >>> FOCUS: Stage 3 (Calibration) — fine-tune weights and thresholds")
    print()

    # All postings with scores
    print("ALL POSTINGS:")
    for slug, r in sorted(results.items(), key=lambda x: x[1]["score"], reverse=True):
        exp_str = r["expected"] if r["expected"] != "?" else "?"
        delta_str = f"delta={r['delta']:+d}" if r["expected"] != "?" else "ungraded"
        print(f"  {slug:.<55} actual={r['actual']:>3} expected={exp_str:>3} {delta_str} score={r['score']}%")

    if graded:
        print()
        # Worst mismatches
        worst = sorted(graded.items(), key=lambda x: abs(x[1]["delta"]), reverse=True)[:5]
        print("WORST MISMATCHES:")
        for slug, r in worst:
            if abs(r["delta"]) > 1:
                print(f"  {slug:.<55} actual={r['actual']:>3} expected={r['expected']:>3} delta={r['delta']:+d} score={r['score']}%")

    # Append to history
    entry = {
        "timestamp": datetime.now().isoformat(),
        "exact_match": exact,
        "within_1": within_1,
        "off_by_2_plus": off_by_2,
        "avg_delta": round(avg_delta, 2),
        "must_have_pct": must_have_pct,
        "postings": results,
    }
    with open(history_path, "a") as f:
        f.write(json.dumps(entry) + "\n")

    # Exit code for CI
    if graded and within_1 == len(graded):
        print("\n*** ALL GRADED POSTINGS WITHIN TOLERANCE ***")
        sys.exit(0)
    elif not graded:
        print("\n*** No graded postings (all expected='?'). Fill in expected_grades.json. ***")
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    run_benchmark()
