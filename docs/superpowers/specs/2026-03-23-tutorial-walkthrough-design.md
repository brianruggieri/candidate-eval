# Tutorial Walkthrough Design

**Date:** 2026-03-23
**Status:** Approved

## Summary

A live session walkthrough of the claude-candidate tool that produces a shareable Markdown doc. Primary audience is the builder dog-fooding their own tool; secondary audience is hiring managers evaluating the project. Uses an output-first narrative: show the most impressive output first, then explain what produced it.

## Goals

- Run every major pipeline step against real data
- Audit the existing local profile for staleness or gaps
- Produce a shareable doc a hiring manager can read without any local setup
- Identify rough edges in the pipeline along the way

## Non-Goals

- Cold-start onboarding (user already has a populated local state)
- Automated regression testing (that's the benchmark script)
- Full re-scan of session logs (unless the audit reveals new sessions exist)

## Narrative Spine

Output-first: the tutorial opens with the most impressive thing the tool produces (a scored assessment against a real job posting), then works backwards to explain what generated that output and why it can be trusted.

Every earlier phase is framed as: *"this is why you can trust that output."*

---

## Phase Structure

### Phase 0 — The Payoff (shown first)

Run `assess` against a real job posting the user cares about. Show the output immediately — letter grade, per-skill scores, evidence citations, gap analysis — before any setup context. Annotate each field inline as we go. This output is the "hero" of the final doc.

**Input — sourcing posting.txt:**
Copy the raw job description text from a LinkedIn (or similar) job posting the user is genuinely interested in. Paste it into a local file: `posting.txt`. The user also supplies `--company`, `--title`, and `--seniority` from the posting header.

**Commands:**
```bash
# From a raw job description text file
.venv/bin/python -m claude_candidate.cli assess \
  --profile ~/.claude-candidate/candidate_profile.json \
  --resume ~/.claude-candidate/curated_resume.json \
  --job posting.txt \
  --company "Company Name" \
  --title "Role Title" \
  --seniority mid \
  --output assessment.json
```
The `--resume` flag provides the curated resume signal; `assess` handles merging internally. `--output assessment.json` is required — Phase 4 reads this file.

**What we look at:**
- Overall fit grade (A–F) and numeric score
- Top skill matches with evidence citations
- Gap analysis — required skills not demonstrated
- Confidence tier per skill (corroborated / resume-only / sessions-only)

---

### Phase 1 — Profile Audit

Inspect the existing local data to confirm it's current and complete. Three sub-checks:

**1. Session coverage check**
Manual inspection — there is no `--dry-run` flag. Read `candidate_profile.json` top-level metadata to find `generated_at` and session count. Compare `generated_at` against the most recent JSONL file in `~/.claude/projects/` to determine if new sessions have accumulated since the last scan. If the delta looks significant, note it; a re-scan is out of scope unless the audit reveals the profile is materially stale.

**2. Skill snapshot**
Read top skills from `~/.claude-candidate/candidate_profile.json`:
- Skill count by category (languages, frameworks, platforms, domains, practices)
- Depth distribution (beginner / proficient / expert)
- Evidence quality (session count, recency)
- Flag: any skills conspicuously absent that the user would expect to see

**3. Merge provenance breakdown**
Read `~/.claude-candidate/merged_profile.json` corroboration summary. Note: this file is written as a side effect of running `assess` with `--resume`. It may not exist if Phase 0 hasn't run yet or if the user has never run assess with resume data. If absent, skip this sub-check and note it in the doc.
- **Corroborated:** Both sessions and resume agree — strongest signal
- **Sessions-only:** Demonstrated in work but not on resume — undersold opportunity
- **Resume-only:** Claimed on resume, not shown in sessions — unverified
- **Conflicting:** Depth mismatch between sources — worth examining

---

### Phase 2 — Baseline Validation

Run the same assess pipeline against a known golden set posting to verify calibration before trusting the real-posting score.

**Posting:** `tests/golden_set/postings/anthropic-software-engineer-claude-code.json`
(Rationale: closest to the user's actual work domain; expected grade is known.)

**Setup:** The golden set files are structured JSON (not raw text). The CLI's `--job` flag reads files as raw text and checks for a `.requirements.json` sidecar. Extract the posting text and pre-built requirements before running:

```bash
# Extract description and requirements from the golden set JSON
python3 -c "
import json, pathlib
d = json.loads(pathlib.Path('tests/golden_set/postings/anthropic-software-engineer-claude-code.json').read_text())
pathlib.Path('/tmp/anthropic-posting.txt').write_text(d['description'])
pathlib.Path('/tmp/anthropic-posting.requirements.json').write_text(json.dumps(d['requirements']))
print('Extracted:', len(d['requirements']), 'requirements')
"

# Run assess — CLI finds the sidecar automatically, skips Claude re-parsing
.venv/bin/python -m claude_candidate.cli assess \
  --profile ~/.claude-candidate/candidate_profile.json \
  --resume ~/.claude-candidate/curated_resume.json \
  --job /tmp/anthropic-posting.txt \
  --company "Anthropic" \
  --title "Software Engineer, Claude Code" \
  --seniority mid \
  --output /tmp/anthropic-assessment.json
```

**Check:** Compare output grade against `tests/golden_set/expected_grades.json`.
- Match → pipeline is calibrated, proceed with confidence
- Drift → diagnose the gap (interesting finding for the doc either way)

---

### Phase 3 — Real Posting (Annotated Walkthrough)

**No new commands.** This phase is annotation-only — it revisits the Phase 0 output (`assessment.json`) with full context. Walk every output field with explanations of what each number means and why it's more credible than a self-reported resume.

**Highlights to annotate:**
- The self-referential signal: sessions from *building this tool* appear in the evidence
- Confidence floor behavior (CONFLICTING-EXPERT skills don't get penalized)
- How the merge provenance affects the final score

---

### Phase 4 — Deliverable Generation

Generate two deliverables from the real-posting assessment, showing the full evidence chain.

**Deliverable A: Resume bullets**
```bash
.venv/bin/python -m claude_candidate.cli generate-deliverable \
  --assessment assessment.json \
  --type resume-bullets \
  --output resume-bullets.md
```
Shows how session evidence maps to accomplishment statements. Technical proof layer.

**Deliverable B: Cover letter**
```bash
.venv/bin/python -m claude_candidate.cli generate-deliverable \
  --assessment assessment.json \
  --type cover-letter \
  --output cover-letter.md
```
Full narrative tailored to the company and role. Human-readable synthesis. Best hiring-manager showcase moment.

---

## Output Document

### Structure
1. **Header** — What this doc is, who it's for, why it exists (one paragraph)
2. **The Result** — Real-posting assessment with inline annotations (hero section)
3. **Why you can trust it** — Profile audit summary + baseline validation result
4. **The deliverables** — Resume bullets + cover letter in full
5. **The pipeline** — Technical explainer of what produced the above
6. **Appendix** — Full command sequence in order (all phases), including intermediate file names and the golden set prep script. Enough for a new user to reproduce the session end-to-end.

### Location
Draft: `.claude/tutorial/YYYY-MM-DD-walkthrough.md` (gitignored — stays local until reviewed).
Final: `docs/tutorial/YYYY-MM-DD-walkthrough.md` (committed to repo after user approval).

The `.claude/` directory is the staging area per project conventions. The final doc is moved to `docs/tutorial/` only after the user has reviewed and approved it.

### Format
Markdown — version-controlled, readable on GitHub, shareable as a direct link.

### What a hiring manager receives
A GitHub link. No local install required. They see: a grade on a real role, evidence from real work sessions, and a tool that produced a tailored cover letter. The repo itself is the proof layer.

---

## Live Session Protocol

As each phase runs:
1. Execute the commands together (user runs, I read and analyze output)
2. I annotate inline — what each output means, what's notable, what to flag
3. At the end of Phase 4, I compile the session into the output doc
4. User reviews the doc before it's committed

The doc reflects what actually happened — not hypothetical or pre-staged output.
