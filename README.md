# claude-candidate

> Everyone uses AI to polish their resume. I built AI agents that understand what I actually do — and prove it with evidence.

A privacy-first pipeline that turns real development session logs and resume credentials into evidence-backed job fit assessments. The sessions from *building this tool* are input to the tool evaluating its builder — every design decision and test in this repo is also data it has scored against real job postings.

**22/24 exact grade match on real LinkedIn postings. All processing on localhost.**

---

## What It Does

- **Extracts skills from real work** — Scans Claude Code development sessions, identifies skills and behavioral patterns, and links every claim to specific session evidence. Not self-reported; observed.
- **Matches against real job postings** — Parses job requirements, scores fit across skills, domain, and culture signals, and produces a letter grade. 22/24 exact match (24/24 within one grade) on a golden set of LinkedIn postings.
- **Runs as a browser extension** — Chrome extension assesses LinkedIn postings in real-time via a local FastAPI server. No data leaves localhost.

---

## The Self-Referential Property

The session logs from *building this tool* are part of the profile it uses to evaluate its builder. The pipeline's quality is its own resume.

This isn't a parlor trick — it means the architectural decisions, debugging strategies, and test coverage visible in this repo are also data the tool has scored against real job postings. The repo is the deliverable.

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
- **Provenance tracking** — Every skill claim is tagged: `corroborated`, `session-only`, or `resume-only`. No unattributed assertions.
- **Privacy by structure** — Raw session logs and resume data never leave your machine. PII scrubbed via regex + DataFog NER before any output.

---

## By the Numbers

| Metric | Value |
|--------|-------|
| Tests passing | 1,120+ |
| Benchmark accuracy | 22/24 exact grade match (24/24 within one grade) |
| Canonical skills in taxonomy | 49 |
| Sessions scanned (author) | 2,300+ |
| Must-have skill coverage | 93% across 24 real postings |

---

## Tech Stack

Python 3.11+ · Pydantic v2 · FastAPI · Click · aiosqlite · rapidfuzz · pytest + Hypothesis
Chrome Extension (Manifest V3) · DataFog NER for PII scrubbing

---

## Quick Start

```bash
pip install -e .

# Onboard from a resume
claude-candidate resume onboard --resume path/to/resume.pdf

# Extract skills from Claude Code session logs
claude-candidate sessions scan

# Score against a job posting
claude-candidate assess --job posting.txt --company "Acme Corp" --title "Senior AI Engineer"
```

For the daily-driver workflow: start the local server (`claude-candidate server`) and use the Chrome extension to assess LinkedIn postings in-browser.

---

## Design Principles

- **Privacy is structural, not policy** — raw data never persists outside your machine
- **Evidence over assertion** — every skill claim traces to a specific session or document
- **Dogfooding as proof** — the tool demonstrates exactly the skills it evaluates

Full architecture, trust model, and roadmap: [PROJECT.md](PROJECT.md)

---

## Project Status

**v0.5** — Active development. Core pipeline stable. v0.5 adds eligibility filters, adoption velocity scoring, and session compaction. Browser extension functional for daily use.

---

## License

MIT
