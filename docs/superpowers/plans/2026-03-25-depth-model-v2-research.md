# Depth Model v2 — Research Synthesis

## The Problem
The current `_infer_depth` treats 8 Claude Code sessions as "expert." Rust (571 sessions) and TypeScript (572 sessions) are indistinguishable despite Brian having 0 years of Rust and 6+ years of TypeScript. Session count measures activity, not expertise.

## Core Insight (from Brian)
Claude Code sessions should be treated as a **current job position** on the resume — not individual project evidence. This position:
- **Extends** existing tech expertise (TypeScript gets recency confirmation)
- **Introduces** new AI-era skills (agentic orchestration, prompt engineering)
- **Does NOT create** expertise in incidentally-touched technologies (Rust, Go, C++)
- **Demonstrates** engineering patterns at high cognitive levels (Bloom's 4-6)

## Research Sources (6 agents)
1. **Expertise models** — Dreyfus, 10K hours, Bloom's, SFIA, portfolio assessment, competency frameworks
2. **Signal extraction** — 7 novel signal families from session data
3. **Time measurement** — Calendar metrics, industry benchmarks, real-world equivalence
4. **Project context** — Project diversity, open source, portfolio theory, T-shaped detection
5. **Agentic expertise** — AI-era engineering patterns, orchestrator skill, hiring trends
6. **Datasets** — ESCO (13.9K skills), O*NET, UK Skills Clustering, LinkedIn 1.3M jobs

## The Three-Category Skill Model

### Category 1: Direct Technical Skills
*"Can you write Rust?"*
- **Primary evidence:** Resume (years of professional use)
- **Sessions prove:** Recency and active use, NOT depth
- **Authorship gate:** Must have Write/Edit to files of that language's extension
- **Without resume:** Sessions-only language skills capped at APPLIED regardless of session count
- **With resume:** Resume depth is the anchor; sessions confirm it's current

### Category 2: Engineering Pattern Skills
*"Can you architect, test, debug, ship complex systems?"*
- **Primary evidence:** Sessions — the patterns ARE the demonstrated work
- **Resume proves:** Longevity of these patterns across years
- **Bloom's mapping:** Architecture decisions = Evaluate (level 5), System building = Create (level 6)
- **Measured by:** Evidence type diversity, project diversity, complexity ceiling
- **Key signals:** Spec-first sessions, multi-directory work, test-alongside-implementation, config/CI authorship

### Category 3: Agentic Orchestration Skills
*"Can you coordinate AI agents to build complex systems?"*
- **Primary evidence:** Sessions are the ONLY evidence (skill didn't exist before 2024)
- **Measured by:** Prompt sophistication, correction quality, task decomposition, review depth, verification discipline
- **Key insight:** 95% of professional developers use AI tools weekly (Anthropic 2026). Seniors ship 2.5x more AI code because they catch mistakes (Fastly 2025). The skill is orchestration quality, not AI usage volume.

## Signal Architecture

### Gate Signal: Code Authorship
Did you Write/Edit files in this language? No = MENTIONED, stop.
- This single check kills the "571 Rust sessions" problem
- Brian never wrote a .rs file — every detection was conversation text

### Primary Signals (easy to extract, high impact)
| Signal | Source | What it measures |
|--------|--------|-----------------|
| Active days/weeks/months | Timestamps | Sustained engagement over real time |
| Distinct projects | File paths (cwd) | Breadth of application |
| Files authored per language | Write/Edit + extension | Actual code production |
| Edit precision ratio | Edit/(Edit+Write) | Surgical vs wholesale (expertise proxy) |
| Time span (first→last) | Timestamps | Duration of engagement |
| Resume corroboration | Curated resume | Anchors depth to years of experience |

### Secondary Signals (medium effort, high discriminating power)
| Signal | Source | What it measures |
|--------|--------|-----------------|
| Prompt sophistication | User messages | Domain vocabulary, directive vs questioning |
| Debugging efficiency | Tool call sequences | Steps-to-fix, hypothesis quality |
| Learning trajectory | Temporal trends | Question→directive ratio over time |
| Architecture scope | File paths | Multi-directory, config files, module design |
| Write-to-test ratio | Write tool calls | Testing discipline per language |

### Tertiary Signals (hard to capture, future phase)
| Signal | Source | What it measures |
|--------|--------|-----------------|
| Error recovery intelligence | Error→resolution sequences | Pivot vs retry, diagnostic approach |
| Correction sophistication | User corrections to AI | Technical rationale in corrections |
| Cross-session complexity escalation | Temporal analysis | Deliberate practice detection |

## Proposed Depth Thresholds

### For Direct Technical Skills (Category 1)
| Level | Requirements | Real-world equivalent |
|-------|-------------|----------------------|
| MENTIONED | Appeared in sessions, no authorship | "I've heard of it" |
| USED | 3+ active days, some authored files | "Tried it in a tutorial" |
| APPLIED | 10+ active days, 2+ projects, 1+ month span | "Used it on a real project" |
| DEEP | 30+ active days, 3+ projects, 3+ months, OR resume says 1-3 years | "Regular professional use" |
| EXPERT | Resume says 3+ years AND sessions confirm active use, OR 60+ active days over 6+ months with high authorship | "Core professional skill" |

### For Engineering Patterns (Category 2)
| Level | Requirements |
|-------|-------------|
| MENTIONED | Pattern observed 1-2 times |
| USED | Pattern in 3+ sessions |
| APPLIED | Pattern consistent across 3+ projects |
| DEEP | Pattern at Bloom's Evaluate level across diverse projects |
| EXPERT | Pattern at Bloom's Create level, demonstrated across 5+ projects over months |

### For Agentic Orchestration (Category 3)
| Level | Requirements |
|-------|-------------|
| MENTIONED | Used AI tools casually |
| USED | Directed AI on simple tasks |
| APPLIED | Decomposed complex tasks for AI, reviewed output |
| DEEP | Multi-agent orchestration, spec-first workflow, systematic verification |
| EXPERT | Ships complex, tested systems primarily through AI orchestration |

## Year-Equivalent Estimation
- Sessions alone can claim at most the actual calendar span as experience
- 31 days of sessions = ~1 month maximum, regardless of session count
- Resume duration is the primary anchor for year claims
- Session evidence confirms recency: "still active as of March 2026"
- For AI-era skills (agentic orchestration): measured from first session date, no resume anchor possible

## Key Data Points from Research
- 10,000 hours: Explains only 18-26% of skill variation (meta-analysis)
- Bootcamp completion (480+ hrs, 12 weeks): Produces APPLIED-level developers
- Corporate onboarding: 3-6 months for productive team member (DEEP)
- Professional proficiency: 1-2 years (DEEP→EXPERT transition)
- Dreyfus Expert: 5-10+ years of deliberate practice
- Skill half-life: 2.5 years for tech skills (IBM), 5-7 for core languages
- AI era: Seniors ship 2.5x more AI code (Fastly), 78% of Claude sessions are multi-file (Anthropic)
- T-shaped engineers: Deep in 2-3 areas, broad across 8+ (industry consensus)

## Integration with Existing Taxonomy
Current taxonomy has 104 skills across categories: language, framework, domain, practice, tool, platform, soft_skill.

Proposed addition: each skill entry gets:
```json
{
  "name": "rust",
  "category": "language",
  "direct_depth": "mentioned",
  "orchestration_context": true,
  "evidence_type": "agentic_build",
  "active_days": 30,
  "active_weeks": 5,
  "projects": 3,
  "files_authored": 0,
  "resume_years": null,
  "estimated_years": 0.08
}
```

## External Dataset Integration (Phase 2)
- **ESCO** (13.9K skills → 3K occupations): Skill-to-occupation mapping for contextual matching
- **O*NET**: Skill importance ratings per occupation
- **UK Skills Clustering** (65M postings → 21 clusters): Data-driven domain groupings
- **Lightcast**: 33K skills, 3-tier hierarchy with job family mapping

## Implementation Priority
1. **Authorship gate** — Zero-effort, instant fix for language inflation
2. **Calendar metrics** — Active days/weeks/months computation in extractor
3. **Resume-as-anchor** — Resume depth is primary; sessions confirm recency
4. **Three-category split** — Separate scoring for direct/pattern/orchestration
5. **Project diversity** — Count distinct projects per skill
6. **ESCO integration** — Domain-weighted skill matching
