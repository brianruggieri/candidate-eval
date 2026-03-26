# v0.8 Feature List

> Accumulated from v0.7 live testing session (2026-03-26). Prioritized by impact on assessment accuracy.

## Scoring Engine

### 1. Requirement Distillation (HIGH)
Break compound requirements into individual skills before matching. Use Claude analysis for complex cases.
- "Flutter AND React" should be two separate requirements
- "AI systems at consumer scale" should check AI + scale independently
- "5+ years of transferrable technical experience (e.g., software engineering, ML engineering, data science)" should extract each example as a skill mapping
- This is the #1 remaining accuracy issue

### 2. Wire compute_match_confidence into Scoring (MEDIUM)
Currently standalone function used only for display. Should modulate `_score_requirement()` so low-confidence matches contribute less to the overall score, not just show a smaller bar.

### 3. Virtual Skill Concentration Limit (MEDIUM)
system-design matched 6/14 Pingo requirements. Cap how many times one virtual skill can be the "strongest match" — after N matches, subsequent uses get diminishing returns.

## Evidence Model

### 4. Sessions as Behavioral Metrics (HIGH)
Bring sessions back — not for depth (that's repos now) but for behavioral signals:
- Debugging patterns and systematic problem-solving
- Prompt sophistication and iteration quality
- Improvement velocity across sessions
- Agentic orchestration maturity (how well they direct AI tools)
- These feed into culture fit dimension (currently disabled)

### 5. Recursive Skill-Crafting Loop Detection (MEDIUM)
New scanner signals from ~/git/skills/ repo evidence:

| Signal | What to detect | Where |
|--------|---------------|-------|
| `skills_authored` | Count SKILL.md files | */SKILL.md |
| `eval_harnesses` | Count eval/ dirs within skills | */eval/SKILL.md |
| `prompt_iterations` | Git log revisions on prompt files | */prompts/*.md |
| `skill_test_corpus` | Fixture files for eval | */tests/fixtures/ |
| `ab_test_evidence` | A/B test results | */evidence/ |
| `meta_skill_count` | Skills that invoke/evaluate other skills | SKILL.md referencing other skills |
| `grading_rubrics` | Structured evaluation criteria | */prompts/grade*.md |

New taxonomy entry: `ai-process-engineering` (practice) — designs, implements, and iterates on AI-assisted development processes.

### 6. Repo Scanner → Skill Evidence for AI Signals (LOW)
Currently repo scanner detects llm_imports, prompt_templates, eval_frameworks as RepoEvidence signals but `build_repo_profile()` doesn't map them into `skill_evidence`. Fixes "llm" showing as resume-only when repos prove it.

## Extension

### 7. Per-URL Keyed Storage (HIGH)
Replace single global cache slots with URL-keyed storage:
```
posting:{urlHash} → posting data
assessment:{urlHash} → assessment data
full:{urlHash} → full assessment data
```
Each tab's assessment lives in its own slot. No cross-contamination, no data loss on tab switch. Current `cacheMatchesTab` guard works but is fragile.

### 8. Requirement Text Summarization (LOW)
Shorten long requirement descriptions in stat cards and skill match list. Either truncate intelligently or generate short summaries during requirement parsing.

## Profile

### 9. Scale Property on Repo-Only Skills (LOW)
Currently only curated resume skills have scale annotations. Repo-detected skills need scale too — infer from repo characteristics (stars, traffic, deployment signals, team size indicators).

## Dependencies
- #1 (Requirement Distillation) unblocks accuracy improvements across the board
- #4 (Sessions) unblocks culture fit dimension
- #5 (Skill Loop) depends on #6 (AI signal mapping)
- #7 (Extension Storage) is independent, can ship anytime
