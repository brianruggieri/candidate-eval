# Blog Post Brief: claude-candidate

## Pipeline Metadata
- **Source conversation**: claude-candidate design, spec, and PoC implementation session
- **Session date**: 2026-03-16
- **Conversation turns**: ~12 (extended, multi-hour design + implementation session)
- **Artifacts produced**: 4 plan documents (21,794 words), 3,778 lines of Python, 91 passing tests, 4 fixture files, full project repo
- **Blog tone target**: Technical builder narrative, personal but precise, honest about limitations

---

## Narrative Skeleton

### Hook
What if your AI coding sessions were a better resume than your resume?

Every developer who uses Claude Code has a hidden asset: JSONL session logs that capture not just what they built, but *how they think*. Architecture decisions. Debugging strategies. The moment they chose NOT to build something. The moment they pivoted when an approach failed. These logs are a richer hiring signal than any bullet point on a resume — but until now, there was no way to make that signal legible to a hiring process.

claude-candidate changes that.

### The Problem (Why This Exists)

Resumes are lossy compressions of actual ability. They reward self-promotion over demonstrated skill. Tailoring one per application is tedious and rarely grounded in specific evidence.

Meanwhile, developers who build with AI assistants generate hundreds of session logs that capture exactly the behavior hiring managers care about — but those logs sit in `~/.claude/` gathering dust.

The gap: no tool starts from *observed development behavior*, extracts structured skill evidence, and maps it against specific job requirements with a verifiable chain of custody.

### The Spark (How the Idea Formed)

The idea emerged from a question about form factor. Should this be an ML model? A CLI tool? A website? The answer evolved through conversation:

- First: "an app that ingests prompt logs and evaluates the person as a job candidate"
- Then: "but the output needs to fit existing hiring workflows — resumes and cover letters"
- Then: "build the evaluation as an intermediate representation, generate deliverables from it"
- Then: "but how do you prove it's real without exposing private session data?"
- Then: "cryptographic manifests, public repo correlation, open-source method"
- Then: "what if I could just click a button while browsing LinkedIn and see my fit score?"
- Finally: "browser extension + local backend + dual evidence from resume AND sessions"

Each question refined the architecture. The final design didn't come from a spec — it came from following the implications of each answer to the next question.

### The Trust Innovation (The Hard Part)

Anyone can claim "AI analyzed my logs and says I'm great." The credibility problem is existential for this tool. The solution has three layers:

**Structural privacy**: Raw data never leaves the user's machine. The architecture makes exposure impossible, not merely prohibited.

**Cryptographic anchoring**: SHA-256 hashes of every session file, recorded before and after sanitization, chained through extraction and evaluation to final deliverables. Any modification to any file at any stage breaks the chain.

**Honest limitations**: The manifest proves integrity, not identity. Session selection is voluntary. The user might omit sessions that show weaknesses. The tool says all of this explicitly in the proof package. Trying to claim more than the cryptography supports would undermine the trust model.

The deepest insight: honesty about limitations *is* the trust signal. A tool that says "here's what I can and can't prove" is more credible than one that says "trust me."

### The Dual Evidence Model (The Key Insight)

The most important architectural decision: use both resume AND session logs, with provenance tracking for every skill.

Every skill gets classified:
- **Corroborated**: Both resume and sessions demonstrate it. Strongest signal.
- **Sessions-only**: Demonstrated in logs, missing from resume. *Discovery* — the resume is underselling this.
- **Resume-only**: Claimed on resume, no session evidence. *Unverified* — prepare to discuss this.
- **Conflicting**: Resume says expert, sessions show basic usage. Sessions win — observed behavior over self-report.

The discovery feature is the killer app within the app. The first assessment run found 9 skills the resume didn't mention but sessions demonstrated extensively. That's not just job matching — that's resume improvement driven by evidence.

### The Build (From Spec to Working Software)

Four plan documents were written first — ~22,000 words covering schemas, agent orchestration, cryptographic trust, and the browser extension. Then the proof-of-concept was built:

- 8 Pydantic schema files defining every data structure
- A manifest module with SHA-256 hashing, session scanning, and tamper detection
- A profile merger that combines resume + session evidence with provenance tracking
- A quick match engine scoring three dimensions equally: skills, mission, culture
- A CLI that produces rich terminal output with assessment cards
- 91 tests validating every module, every schema, and the full pipeline end-to-end

The first assessment run scored 65% on skills — lower than expected. The reason: job requirements like "modular system architecture" mapped to behavioral pattern types, but the matching engine only searched skill entries. A pattern-type resolution layer was added, and the score jumped to 78% with 8/8 must-haves met.

This bug-and-fix cycle is itself a demonstration of the tool's value. The session logs from debugging the matcher are evidence of systematic debugging ability. The architectural decision to add pattern resolution is evidence of systems thinking. The tool evaluated its own development process.

### The Assessment Card (Show, Don't Tell)

```
╭──────────────── claude-candidate ────────────────╮
│ AI Tools Corp                                     │
│ Senior AI Engineer                                │
│                                                   │
│ Overall: B (78%)                                  │
│ ███████████████░░░░░                              │
╰───────────────────────────────────────────────────╯
┌──────────────┬───────┬───────┬──────────────────┐
│ Dimension    │ Score │ Grade │ Bar              │
├──────────────┼───────┼───────┼──────────────────┤
│ Skill Match  │  78%  │   B   │ ███████████████░ │
│ Mission      │  50%  │   D   │ ██████████░░░░░░ │
│ Culture Fit  │  50%  │   D   │ ██████████░░░░░░ │
└──────────────┴───────┴───────┴──────────────────┘

  ✓ 8/8 must-haves met
  ★ Strongest: Multi-agent orchestration
  △ Gap: None — all requirements addressed

  💡 9 skills your resume doesn't mention
     → claude-api, cli-design, developer-tooling

  ⚠  1 resume claim without session evidence
     → docker

  Verdict: MAYBE → (mission/culture need enrichment data)
```

Note: Mission and Culture show D because the CLI path doesn't pass company enrichment data. The browser extension path (which auto-fetches company websites, engineering blogs, and GitHub orgs) would populate those dimensions. The tool is honest about what it knows and doesn't know.

### The Recursive Property (Why This Matters Beyond the Tool)

claude-candidate evaluates its own builder. The session logs from designing the schema, implementing the scoring engine, debugging the pattern matcher, and writing the agent CLAUDE.md files — all of that is valid input to the tool.

If you feed those sessions in and point the tool at an AI Engineering role, it should produce a strong match. The architecture-first patterns. The modular thinking. The prompt engineering. The multi-agent orchestration. The trust model design. All demonstrated, all evidenced, all traceable.

And this blog post? If it's generated by blog-a-claude (a pipeline that ingests session logs and produces blog posts), then the blog post about building claude-candidate was itself generated by a tool that processes the same kind of session data that claude-candidate evaluates.

The snake eats its tail. And that's the point. The tools observe their own creation. The quality of the observation is the proof of the skill.

### What's Next

The PoC works. The plans are written. The handoff to an agent team is ready. What remains:

1. FastAPI backend server to wire the scoring engine to HTTP
2. Resume parser to enable dual-source evidence
3. Company enrichment to populate mission and culture dimensions
4. Chrome extension to make job browsing feel like having a brutally honest advisor on your shoulder
5. Full pipeline for generating tailored resumes, cover letters, and proof packages
6. And then: run it against real job postings, eat the dogfood, and see if the tool is as honest as it claims to be

### Closing Line Options

- "The best way to prove you can build AI systems is to build an AI system that proves you can build AI systems."
- "Your resume says what you claim. Your session logs show what you did. claude-candidate tells the difference."
- "Every session you've had with Claude Code is evidence. claude-candidate makes it count."

---

## Blog-a-Claude Pipeline Notes

If this brief is being processed by the blog-a-claude pipeline:

1. **Target length**: 1,500-2,500 words. This is a narrative post, not a tutorial.
2. **Include the assessment card output** as a formatted code block. It's the hero visual.
3. **Do NOT reproduce the full schema definitions.** Reference them and link to the repo.
4. **The emotional arc**: curiosity → "wait, this could actually work" → trust problem → elegant solution → working code → recursive realization.
5. **Voice**: First person, builder's perspective. Not a product announcement. More like "here's what I built this weekend and why it surprised me."
6. **Link to repo**: github.com/brianruggieri/claude-candidate (once published)
7. **Cross-link**: Reference blog-a-claude, teamchat, and obsidian-daily-digest as the ecosystem context.
