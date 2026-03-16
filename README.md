# claude-candidate

Privacy-first pipeline that transforms Claude Code session logs and resume credentials into honest, evidence-backed job fit assessments.

## Quick Start

```bash
pip install -e .
claude-candidate assess \
  --profile candidate_profile.json \
  --resume resume_profile.json \
  --job posting.txt \
  --company "Acme Corp" \
  --title "Senior AI Engineer"
```

See [PROJECT.md](PROJECT.md) for full documentation.
