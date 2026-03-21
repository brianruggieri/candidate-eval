#!/usr/bin/env python3
"""Export cached postings from assessments.db into golden set fixtures."""

import hashlib
import json
import re
import sqlite3
from pathlib import Path

from claude_candidate.skill_taxonomy import SkillTaxonomy
from claude_candidate.requirement_parser import normalize_skill_mappings


def slugify(company: str, title: str, url: str = "") -> str:
    """Generate a filename slug from company and title.

    Appends a short URL hash to avoid collisions when titles share a long prefix.
    """
    combined = f"{company}-{title}".lower()
    combined = re.sub(r'[^a-z0-9]+', '-', combined).strip('-')[:60]
    if url:
        url_hash = hashlib.sha256(url.encode()).hexdigest()[:6]
        combined = f"{combined}-{url_hash}"
    return combined


def export():
    db_path = Path.home() / ".claude-candidate" / "assessments.db"
    output_dir = Path("tests/golden_set/postings")
    output_dir.mkdir(parents=True, exist_ok=True)

    taxonomy = SkillTaxonomy.load_default()
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    cur = conn.execute("SELECT url, data FROM posting_cache ORDER BY extracted_at")
    rows = cur.fetchall()

    expected_grades = {}
    stats = {"total": 0, "normalized": 0, "unmatched": 0}

    for row in rows:
        data = json.loads(row["data"])
        company = data.get("company", "Unknown")
        title = data.get("title", "Unknown")
        slug = slugify(company, title, row["url"])

        # Skip postings with 0 requirements
        reqs = data.get("requirements", [])
        if not reqs:
            print(f"  SKIP (no requirements): {company} — {title}")
            continue

        # Capture originals before normalization
        originals_per_req = []
        for req in reqs:
            originals_per_req.append(list(req.get("skill_mapping", [])))

        # Normalize requirements
        normalize_skill_mappings(reqs, taxonomy)

        # Track normalization stats
        for original_skills, req in zip(originals_per_req, reqs):
            normalized_skills = req.get("skill_mapping", [])
            for orig in original_skills:
                canonical = taxonomy.match(orig)
                if canonical and canonical != orig:
                    stats["normalized"] += 1
                elif not canonical:
                    stats["unmatched"] += 1

        # Write posting file
        posting_path = output_dir / f"{slug}.json"
        posting_path.write_text(json.dumps(data, indent=2))
        stats["total"] += 1

        # Stub expected grade
        expected_grades[slug] = {
            "expected": "?",
            "rationale": f"{company} — {title}",
        }

        print(f"  Exported: {slug}.json ({len(reqs)} reqs)")

    # Write expected grades stub
    grades_path = Path("tests/golden_set/expected_grades.json")
    grades_path.write_text(json.dumps(expected_grades, indent=2))

    conn.close()
    print(f"\n=== Export Complete ===")
    print(f"Postings: {stats['total']}")
    print(f"Skill mappings normalized: {stats['normalized']}")
    print(f"Skill mappings unmatched: {stats['unmatched']}")
    print(f"\nExpected grades stub: {grades_path}")
    print(f">>> Fill in expected grades before launching ralph-loop <<<")


if __name__ == "__main__":
    export()
