# Tutorial Walkthrough Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a live end-to-end walkthrough of the claude-candidate pipeline that produces a shareable Markdown tutorial doc for hiring managers.

**Architecture:** Output-first narrative — Phase 0 produces the hero assessment output, Phases 1–2 establish trust, Phase 3 annotates the result, Phase 4 generates deliverables. Everything is captured inline and compiled into a tutorial doc at the end.

**Tech Stack:** Python 3.13 venv, click CLI (`claude_candidate.cli`), aiosqlite, pydantic v2, Claude API (for deliverable generation)

---

## File Map

| File | Created/Modified | Purpose |
|------|-----------------|---------|
| `posting.txt` | Created by user | Raw job description text from a real posting |
| `assessment.json` | Created in Task 2 | Phase 0 assess output (hero of the doc) |
| `/tmp/anthropic-posting.txt` | Created in Task 4 | Golden set description extracted to text |
| `/tmp/anthropic-posting.requirements.json` | Created in Task 4 | Golden set requirements sidecar |
| `/tmp/anthropic-assessment.json` | Created in Task 4 | Phase 2 validation assessment |
| `resume-bullets.md` | Created in Task 6 | Deliverable A |
| `cover-letter.md` | Created in Task 6 | Deliverable B |
| `.claude/tutorial/2026-03-23-walkthrough.md` | Created in Task 7 | Draft tutorial (gitignored) |
| `docs/tutorial/2026-03-23-walkthrough.md` | Created in Task 8 | Final committed tutorial |

---

## Task 1: Environment Check

**Files:** None created.

- [ ] **Step 1: Verify venv and CLI are working**

```bash
.venv/bin/python -m claude_candidate.cli --help
```

Expected: Usage line listing all commands (sessions, resume, assess, generate-deliverable, etc.)

- [ ] **Step 2: Confirm local data files exist**

```bash
ls -lh ~/.claude-candidate/{candidate_profile.json,curated_resume.json,whitelist.json}
```

Expected: All three files present. Note sizes. If `candidate_profile.json` is missing, stop — the profile must exist before running.

- [ ] **Step 3: Get a real job posting**

Find a LinkedIn job posting you're genuinely interested in. Copy the full job description text (title, company, requirements, about section — everything). Save it:

```bash
# Paste the job description into posting.txt using your editor
# Then confirm it's not empty
wc -l posting.txt
```

Expected: At least 20 lines of job description text.

Note the `--company`, `--title`, and `--seniority` values you'll use from the posting header.

---

## Task 2: Phase 0 — Real Posting Assessment (The Hero Output)

**Files:** Creates `assessment.json`

- [ ] **Step 1: Run the assessment**

```bash
.venv/bin/python -m claude_candidate.cli assess \
  --profile ~/.claude-candidate/candidate_profile.json \
  --resume ~/.claude-candidate/curated_resume.json \
  --job posting.txt \
  --company "COMPANY_NAME" \
  --title "JOB_TITLE" \
  --seniority mid \
  --output assessment.json
```

Replace `COMPANY_NAME`, `JOB_TITLE`, and `--seniority` with values from your posting. Seniority options: `junior|mid|senior|staff|principal|director|unknown`.

Expected: Progress output showing skill matching, then a fit summary printed to stdout. `assessment.json` written to disk.

- [ ] **Step 2: Confirm assessment.json was created**

```bash
ls -lh assessment.json && .venv/bin/python -c "import json; d=json.load(open('assessment.json')); print('Grade:', d.get('overall_grade'), '| Score:', round(d.get('overall_score',0)*100,1), '%')"
```

Expected: File exists, grade letter (A–F) and numeric score printed.

- [ ] **Step 3: Note the hero output for the doc**

Read and note the following from stdout or `assessment.json`:
- Overall grade and score
- Top 3 skill matches (skill name + evidence citation)
- Top 3 gaps (missing or low-confidence skills)
- Any `CONFLICTING` or `sessions_only` skills that appear

This is the data that goes into the "The Result" section of the tutorial doc.

---

## Task 3: Phase 1 — Profile Audit

**Files:** None created. Read-only inspection of `~/.claude-candidate/`.

- [ ] **Step 1: Check session coverage (recency)**

```bash
.venv/bin/python -c "
import json, pathlib
cp = json.loads(pathlib.Path('~/.claude-candidate/candidate_profile.json').expanduser().read_text())
print('Generated at:', cp.get('generated_at', 'not found'))
print('Session count:', len(cp.get('sessions', [])))
print('Skill count:', len(cp.get('skills', {})))
"
```

Expected: `generated_at` timestamp and counts. If `generated_at` is more than a week old and you've been actively coding since, note it — there may be unscanned sessions.

- [ ] **Step 2: Check for new unscanned sessions (optional)**

```bash
# Find the newest JSONL file in Claude's session directory
ls -lt ~/.claude/projects/ | head -5
```

If any JSONL files are newer than the `generated_at` timestamp from Step 1, note "X new sessions not yet in profile" for the doc. No re-scan needed unless the delta is large (>50 sessions).

- [ ] **Step 3: Skill snapshot — count by category**

```bash
.venv/bin/python -c "
import json, pathlib
from collections import Counter
cp = json.loads(pathlib.Path('~/.claude-candidate/candidate_profile.json').expanduser().read_text())
skills = cp.get('skills', {})
# Count by depth
depths = Counter(v.get('depth','?') for v in skills.values())
print('Total skills:', len(skills))
print('By depth:', dict(depths))
print()
print('Top 10 by session_count:')
top = sorted(skills.items(), key=lambda x: x[1].get('session_count',0), reverse=True)[:10]
for name, s in top:
    print(f'  {name}: depth={s.get(\"depth\",\"?\")} sessions={s.get(\"session_count\",0)}')
"
```

Expected: Totals and top-10 skills printed. Note any conspicuously missing skills you'd expect to see (e.g. if `python` is absent, something is wrong).

- [ ] **Step 4: Merge provenance breakdown**

```bash
.venv/bin/python -c "
import json, pathlib
mp_path = pathlib.Path('~/.claude-candidate/merged_profile.json').expanduser()
if not mp_path.exists():
    print('merged_profile.json not found — will be created after Phase 0 assess completes')
else:
    mp = json.loads(mp_path.read_text())
    skills = mp.get('skills', {})
    from collections import Counter
    provenance = Counter(v.get('provenance','?') for v in skills.values())
    print('Merge provenance breakdown:')
    for k, v in sorted(provenance.items(), key=lambda x: -x[1]):
        print(f'  {k}: {v} skills')
    print()
    # Flag sessions_only (undersold on resume)
    sessions_only = [k for k,v in skills.items() if v.get('provenance')=='sessions_only']
    if sessions_only:
        print('Sessions-only (not on resume):', ', '.join(sessions_only[:10]))
"
```

Expected: Breakdown of corroborated / sessions_only / resume_only / conflicting counts. The `sessions_only` list is especially interesting — these are skills you demonstrate but haven't claimed.

Note the breakdown for the "Why you can trust it" section of the tutorial doc.

---

## Task 4: Phase 2 — Baseline Validation (Golden Set)

**Files:** Creates `/tmp/anthropic-posting.txt`, `/tmp/anthropic-posting.requirements.json`, `/tmp/anthropic-assessment.json`

- [ ] **Step 1: Extract golden set posting to text + sidecar**

```bash
.venv/bin/python -c "
import json, pathlib
d = json.loads(pathlib.Path('tests/golden_set/postings/anthropic-software-engineer-claude-code.json').read_text())
pathlib.Path('/tmp/anthropic-posting.txt').write_text(d['description'])
pathlib.Path('/tmp/anthropic-posting.requirements.json').write_text(json.dumps(d['requirements'], indent=2))
print('Company:', d['company'])
print('Title:', d['title'])
print('Seniority:', d['seniority'])
print('Requirements:', len(d['requirements']))
"
```

Expected: Extracted to `/tmp/`. Requirements count printed (should be ~10–20).

- [ ] **Step 2: Look up the expected grade**

```bash
.venv/bin/python -c "
import json, pathlib
grades = json.loads(pathlib.Path('tests/golden_set/expected_grades.json').read_text())
slug = 'anthropic-software-engineer-claude-code'
print('Expected grade:', grades.get(slug, 'NOT FOUND'))
"
```

Note the expected grade before running — avoids anchoring bias.

- [ ] **Step 3: Run validation assessment**

```bash
.venv/bin/python -m claude_candidate.cli assess \
  --profile ~/.claude-candidate/candidate_profile.json \
  --resume ~/.claude-candidate/curated_resume.json \
  --job /tmp/anthropic-posting.txt \
  --company "Anthropic" \
  --title "Software Engineer, Claude Code" \
  --seniority mid \
  --output /tmp/anthropic-assessment.json
```

Expected: Assessment runs (sidecar found — no Claude re-parse). Grade printed.

- [ ] **Step 4: Compare result to expected**

```bash
.venv/bin/python -c "
import json, pathlib
expected = json.loads(pathlib.Path('tests/golden_set/expected_grades.json').read_text()).get('anthropic-software-engineer-claude-code')
actual_d = json.loads(pathlib.Path('/tmp/anthropic-assessment.json').read_text())
actual = actual_d.get('overall_grade')
print(f'Expected: {expected}  |  Actual: {actual}  |  Match: {expected == actual}')
"
```

Expected: Match = True (or within one grade letter). If drift is observed, note the direction (higher or lower) and any obvious cause — this is interesting content for the doc either way.

---

## Task 5: Phase 3 — Annotate the Real Posting Assessment

**Files:** No new files. Annotation-only — no commands.

- [ ] **Step 1: Read and annotate the assessment**

```bash
.venv/bin/python -c "
import json, pathlib
d = json.loads(pathlib.Path('assessment.json').read_text())
print(json.dumps(d, indent=2))
" | less
```

Walk through each top-level field. Note:
- `overall_grade`, `overall_score` — the headline
- `skill_matches` — each entry has skill name, score, provenance, evidence citations
- `gaps` — required skills that scored low or missing
- `confidence` — overall confidence tier

- [ ] **Step 2: Find the self-referential signal**

Look through `skill_matches` for skills with evidence pointing to sessions from this repo (`candidate-eval`). The sessions from *building* the tool are themselves evidence for the `ai-agents`, `python`, `fastapi`, `pydantic` skills being scored. Note any you find — this is the most compelling moment for a hiring manager.

- [ ] **Step 3: Note CONFLICTING-EXPERT behavior**

Check if any skills show `provenance: conflicting`. Per the confidence floor logic (CONFLICTING-EXPERT), these should not be penalized below expert floor. If present, note them — good explanation for the doc.

---

## Task 6: Phase 4 — Generate Deliverables

**Files:** Creates `resume-bullets.md`, `cover-letter.md`

- [ ] **Step 1: Generate resume bullets**

```bash
.venv/bin/python -m claude_candidate.cli generate-deliverable \
  --assessment assessment.json \
  --type resume-bullets \
  --output resume-bullets.md
```

Expected: `resume-bullets.md` written. Bullets reference specific skills matched to the posting.

- [ ] **Step 2: Review resume bullets**

```bash
cat resume-bullets.md
```

Note: Are the bullets specific and evidence-backed, or generic? Flag anything that reads like resume filler without session evidence — that's a quality signal for the doc.

- [ ] **Step 3: Generate cover letter**

```bash
.venv/bin/python -m claude_candidate.cli generate-deliverable \
  --assessment assessment.json \
  --type cover-letter \
  --output cover-letter.md
```

Expected: `cover-letter.md` written. Should reference the specific company and role.

- [ ] **Step 4: Review cover letter**

```bash
cat cover-letter.md
```

Note: Does it mention the self-referential angle (the tool is proof of the skill)? Does it feel tailored or generic? Quality of the output is worth commenting on in the doc.

---

## Task 7: Compile the Tutorial Doc

**Files:** Creates `.claude/tutorial/2026-03-23-walkthrough.md`

- [ ] **Step 1: Create the staging directory**

```bash
mkdir -p .claude/tutorial
```

- [ ] **Step 2: Write the tutorial doc**

Compile everything captured across Tasks 1–6 into `.claude/tutorial/2026-03-23-walkthrough.md` with this structure:

```markdown
# claude-candidate: Live Walkthrough
*Generated: 2026-03-23*

## What you're looking at
[One paragraph: what claude-candidate is, what this doc shows, who it's for]

## The Result
[Phase 0 hero output — grade, top skill matches with evidence, gaps. Annotated inline.]

## Why you can trust it
### Profile snapshot
[Phase 1 audit findings — skill count, depth distribution, session coverage, merge provenance breakdown]

### Baseline calibration
[Phase 2 result — expected vs actual grade on the Anthropic posting, whether it matched]

## The deliverables
### Resume bullets
[Full content of resume-bullets.md]

### Cover letter
[Full content of cover-letter.md]

## How it works
[2–3 paragraph technical explainer: sessions → extraction → merge → scoring → deliverable. Keep it accessible.]

## Appendix: Reproduce this walkthrough
[Full command sequence in order, with intermediate filenames. Exact copy-paste.]
```

- [ ] **Step 3: Verify the doc exists and is non-trivial**

```bash
wc -l .claude/tutorial/2026-03-23-walkthrough.md
```

Expected: At least 100 lines. If shorter, something is missing.

---

## Task 8: Review and Commit

**Files:** Moves `.claude/tutorial/2026-03-23-walkthrough.md` → `docs/tutorial/2026-03-23-walkthrough.md`

- [ ] **Step 1: Ask user to review the draft**

Point user to `.claude/tutorial/2026-03-23-walkthrough.md`. Wait for approval or change requests. Apply any edits before proceeding.

- [ ] **Step 2: Move to docs/tutorial/**

```bash
mkdir -p docs/tutorial
cp .claude/tutorial/2026-03-23-walkthrough.md docs/tutorial/2026-03-23-walkthrough.md
```

- [ ] **Step 3: Commit**

```bash
git add docs/tutorial/2026-03-23-walkthrough.md
git commit -m "Add tutorial walkthrough doc"
```

Expected: Clean commit on current branch.

- [ ] **Step 4: Verify committed**

```bash
git show --stat HEAD
```

Expected: `docs/tutorial/2026-03-23-walkthrough.md` listed with line count.
