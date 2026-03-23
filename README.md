# claude-candidate

> Everyone uses AI to polish their resume. I built one that watches me work — and scores the results against real job postings.

A pipeline that turns development session logs and resume data into evidence-backed job fit assessments.

**Privacy note:** Session logs and resume data are processed locally. Job posting extraction calls Claude CLI, which reaches Anthropic's API — posting text is sent as a prompt; your sessions and resume stay on your machine.

---

## What It Does

- **Extracts skills from real work** — Scans Claude Code development sessions, identifies skills and behavioral patterns, and links every claim to specific session evidence. Not self-reported; observed.
- **Matches against real job postings** — Parses job requirements, scores fit across skills, domain, and culture signals, and produces a letter grade with evidence-linked explanations.
- **Runs as a browser extension** — Chrome extension assesses LinkedIn postings in real-time via a local FastAPI server.

---

## The Self-Referential Property

The session logs from *building this tool* are part of the profile it uses to evaluate its builder. Every architectural decision, debugging strategy, and test you see in this repo is also data the tool has scored against real job postings.

---

## How It Works

```
Session Logs (JSONL) ──→ Sanitizer ──→ Extractor ──→ CandidateProfile ──┐
Resume (PDF/DOCX)    ──→ Resume Parser ──────────────→ ResumeProfile ────┤
                                                                          ↓
                                                           MergedEvidenceProfile
                                                                          ↓
Job Posting ──→ Requirement Parser ──→ QuickRequirements ──→ Scorer ──→ FitAssessment
```

- **Dual evidence model** — Skills sourced from sessions, resume, or both. Corroborated skills (both sources agree) rank higher.
- **Provenance tracking** — Every skill claim is tagged: `corroborated`, `sessions_only`, or `resume_only`. No unattributed assertions.
- **PII scrubbing** — Raw session and resume text is scrubbed via DataFog (phone, email, SSN, names) before any output is written to disk.

Full architecture, trust model, and roadmap: [PROJECT.md](PROJECT.md)

---

## By the Numbers

| Metric | Value |
|--------|-------|
| Tests passing | 1,117 |
| Canonical skills in taxonomy | 105 |
| Sessions scanned (author) | 2,300+ |

---

## Tech Stack

Python 3.11+ · Pydantic v2 · FastAPI · Click · aiosqlite · rapidfuzz · pytest + Hypothesis
Chrome Extension (Manifest V3) · DataFog for PII scrubbing

---

## Quick Start

```bash
pip install -e .  # requires Python 3.11+

# Onboard from a resume
claude-candidate resume onboard path/to/resume.pdf

# Extract skills from Claude Code session logs
claude-candidate sessions scan
# → saves profile to ~/.claude-candidate/candidate_profile.json

# Score against a job posting
claude-candidate assess \
  --profile ~/.claude-candidate/candidate_profile.json \
  --job posting.txt \
  --company "Acme Corp" \
  --title "Senior AI Engineer"
```

For the daily-driver workflow: run `claude-candidate server start` and use the Chrome extension to assess LinkedIn postings in-browser.

---

## Project Status

**v0.5** — Active development. Core pipeline stable. v0.5 adds eligibility filters, adoption velocity scoring, and session compaction.

The repo is the deliverable.

---

## License

MIT
