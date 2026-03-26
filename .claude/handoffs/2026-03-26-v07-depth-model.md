---
name: v0.7 Depth Model — Implementation + Live Testing
slug: v07-depth-model
date: 2026-03-26
branch: feat/golden-set-expansion-calibration
pr: 32
---

# Handoff: v0.7 Depth Model

## Summary

Replaced session-count-based depth inference with a resume-anchored, repo-evidenced model. Then spent 18 patch iterations (0.7.0 → 0.7.18) live-testing against real LinkedIn postings (Khan Academy, Arcade, Pingo AI, Ello, Eightfold AI) and fixing scoring, display, and matching issues found during use.

## What Shipped

### Core v0.7 (Tasks 2-14 from plan)
- **repo_scanner.py** — Local filesystem + GitHub API scanning. Detects languages, deps, tests, CI, AI maturity signals, git commit span.
- **build_repo_profile()** — Aggregates per-skill evidence across repos with timeline scaling
- **merge_triad()** — Resume (anchor) + repos (receipts) merge. Sessions parked for v0.8.
- **compute_match_confidence()** — Match-time confidence scoring, wired into skill detail display
- **CLI:** `repos scan`, `repos list`, `profile rebuild` commands
- **Schema:** RESUME_AND_REPO, REPO_ONLY sources, repo evidence fields, optional scale property
- **Dead code:** ~690 lines removed from extractor.py, candidate_profile.py
- **Band-aids removed:** Concentration penalty, weak must-have ratio, session depth caps

### Live Testing Patches (0.7.1 → 0.7.18)
- **0.7.1** — Wire compute_match_confidence into _build_skill_detail display
- **0.7.2** — Mission alignment: scan role companies/descriptions, substring domain matching
- **0.7.3** — Soft skill morphological variants (adaptability↔adaptable), edtech taxonomy expansion
- **0.7.4** — Hide culture fit when no behavioral data, auto-open skills section
- **0.7.5** — Color-coded stat cards (HSL gradient by match quality)
- **0.7.6** — Years shortfall penalty (ratio-based: <50% required → cap at partial)
- **0.7.7** — Ratio refinement for years check
- **0.7.8** — Redefine "direct evidence" (resume_only counts as direct), skill text variants
- **0.7.9** — Added testing, machine-learning, react to curated resume
- **0.7.10** — Skill scale property (personal/team/startup/enterprise/consumer)
- **0.7.11** — Fix sessions_only leak in virtual skills, systems-thinking taxonomy
- **0.7.12** — Extension URL sandboxing for fullAssessmentReady
- **0.7.13** — AI-qualified scale penalty + AI-context penalty for generic skills
- **0.7.14** — java≠javascript fuzzy match fix, PM tool variants
- **0.7.15** — project-management taxonomy entry with Jira/ClickUp/Linear aliases
- **0.7.16** — Aggressive cache clear on URL mismatch (reverted in 0.7.17)
- **0.7.17** — Preserve cached assessments across tab switches
- **0.7.18** — Flask/Django/Airflow/Spark as distinct taxonomy entries

## Key Decisions

1. **Resume is the anchor** — never overridden by repo or session evidence
2. **Sessions parked for v0.8** — culture fit dimension disabled, no behavioral patterns
3. **Confidence = match quality** — computed at match time, not merge time
4. **Scale is per-skill** — curated by human, inferred from career history
5. **Domain gap: single B+ cap** — removed tiered system from ralph loop
6. **Direct evidence = human-attested** — resume_only + resume_and_repo both count
7. **Generic skills penalized in confidence** — software-engineering matching domain-specific reqs gets 0.10
8. **AI-qualified scale check** — when requirement asks for AI at scale, use candidate's AI skill scale, not matched skill's scale
9. **Language requirements can't cross-match tools** — Go doesn't match Docker via related skills

## Do Not Retry

1. **Nuclear cache clearing on URL mismatch** — breaks in-progress analysis on other tabs. Use URL validation guards instead.
2. **Session depth as a scoring signal** — sessions are parked, don't try to use them
3. **Global chrome.storage for assessments** — per-URL keying needed (v0.8)
4. **Worktree agents for feature branch work** — worktrees branch from main, not the feature branch. Cherry-pick or work directly.

## Negative Knowledge

1. **java fuzzy-matches javascript** via substring ("java" in "javascript"). Fixed with taxonomy-aware rejection in _find_fuzzy_match.
2. **Virtual skills (system-design, frontend-development, data-science) have no scale** — they're synthesized at match time. The AI-qualified scale check compensates but virtual skills need proper scale inheritance.
3. **Requirement parser puts parent language as fallback skill_mapping** — Flask requirement includes "python" as a mapping. When flask doesn't match, python does. Fixed by adding flask/django/airflow/spark as distinct taxonomy entries.
4. **merge_triad sets confidence=None** — required 3+ null guards in quick_match.py scoring paths. All found and fixed.
5. **Mission alignment only does shallow keyword matching** — 65% C+ for an edtech candidate at an edtech company. Needs full reanalysis in v0.8.
6. **Extension fullAssessmentReady doesn't scope by URL** — deep analysis for posting A shows on posting B. Partial fix in place, per-URL storage needed.

## Curated Resume State (49 skills)

Key additions during this session:
- software-engineering (expert, 13yr, consumer scale)
- computer-science (deep, 17yr, consumer scale)
- product-development (expert, 10yr, consumer scale)
- testing (expert, 10yr, consumer scale)
- edtech (deep, 6yr, consumer scale)
- project-management (deep, 8yr, enterprise scale)
- technology-research (deep, 13yr, enterprise scale)
- machine-learning (used, 4mo, personal scale)
- react (applied, 1yr, personal scale)

All 49 skills annotated with scale: 16 consumer, 14 enterprise, 3 startup, 8 personal, 3 team.

## Benchmark

| Metric | v0.6 baseline | v0.7 final |
|--------|--------------|------------|
| Tests | 1224 | 1260 |
| Exact match | ~22/47 | 37/47 |
| Within ±1 | ~35/47 | 47/47 |
| Off by 2+ | ~12/47 | 0/47 |
| Phantom languages | 5 | 0 |
| Profile skills | ~76 | 92 |

## v0.8 Feature List

Saved at: `docs/superpowers/specs/2026-03-26-v08-feature-list.md`

Priority order:
1. Requirement distillation (compound → individual skills)
2. Mission alignment reanalysis
3. Sessions as behavioral metrics (culture fit)
4. Skill-crafting loop detection
5. Per-URL extension storage
6. Wire confidence into scoring engine
7. Virtual skill concentration limit
8. Repo scanner → AI skill evidence mapping
9. Requirement text summarization
10. Scale on repo-only skills

## Files Modified (key)

| File | Changes |
|------|---------|
| src/claude_candidate/repo_scanner.py | NEW — full module |
| src/claude_candidate/merger.py | merge_triad() added |
| src/claude_candidate/quick_match.py | confidence, scale, fuzzy fixes, variants |
| src/claude_candidate/schemas/merged_profile.py | RESUME_AND_REPO, repo fields, scale |
| src/claude_candidate/schemas/curated_resume.py | scale field on CuratedSkill |
| src/claude_candidate/schemas/repo_profile.py | NEW (Task 1, pre-existing) |
| src/claude_candidate/data/taxonomy.json | 10+ entries/aliases added |
| src/claude_candidate/cli.py | repos scan/list, profile rebuild |
| src/claude_candidate/server.py | merge_triad integration |
| extension/popup.js | confidence display, URL sandboxing, stat colors |
| extension/popup.html | culture fit hide, skills auto-open |
| extension/background.js | URL-scoped fullAssessmentReady |

## PR

brianruggieri/candidate-eval#32 — 63 commits, 66 files changed, +12,531 / -934 lines.
Run `/fix-pr-reviews` on a fresh agent after Copilot reviews.
