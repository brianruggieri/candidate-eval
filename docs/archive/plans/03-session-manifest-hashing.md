# Plan 03: Session Manifest & Hashing

## Purpose

This plan defines the trust and verification layer of claude-candidate. It is the answer to the question: "How do I prove that this evaluation is genuinely derived from my real development work, without exposing that work?"

The manifest module creates a cryptographic chain of custody from raw session files through sanitization, extraction, and evaluation. It enables three things:

1. **Self-verification**: The user can confirm that a generated evaluation corresponds to specific sessions.
2. **Third-party auditability**: A hiring company can, with the user's cooperation, verify that claimed sessions existed and were processed by the pipeline.
3. **Tamper detection**: Any modification to session files after manifest creation is detectable.

This module operates independently of the agent pipeline. It runs in parallel, consumes raw files and pipeline artifacts, and produces verification documents that accompany (but are not required by) the deliverables.

## Threat Model

Understanding what we're defending against clarifies design choices.

### What we are proving
- Specific session files existed at specific times with specific content.
- The evaluation was generated from those specific sessions (not fabricated or cherry-picked post-hoc).
- The sanitization process removed specific categories of content (documented transparently).
- Public repo activity correlates with session activity (independent corroboration).

### What we are NOT proving
- That the sessions represent all of the user's work (they may have selected a subset).
- That the user wrote every prompt (Claude Code is interactive; the AI also contributed).
- That the user didn't have help (pair programming sessions would appear in logs).
- That the sessions are from a specific person (session files aren't identity-bound).

### Honest limitations to communicate
- Session selection is voluntary. The user chose which sessions to include.
- Session logs capture the user's interaction with Claude Code, which includes AI-generated responses. The *prompts, decisions, and direction* are the human signal; the *code output* is collaborative.
- The manifest proves data integrity, not identity. It's like a git commit — it proves the content existed at a point in time, not who authored it.

These limitations should be stated clearly in the proof package. Trying to claim more than the cryptography supports undermines the trust model.

## Data Structures

### SessionManifest

The top-level manifest for a pipeline run.

```python
class SessionFileRecord(BaseModel):
    """Record for a single session file in the manifest."""

    session_id: str
    # Unique identifier matching SessionReference.session_id in the CandidateProfile.
    # Format: YYYY-MM-DD_HH-MM-SS_{project_hash_prefix}

    original_path: str
    # Relative path from the user's home directory (not absolute — no PII).
    # Example: ".claude/projects/abc123/sessions/session_001.jsonl"
    # The absolute path prefix is stripped during manifest creation.

    file_size_bytes: int
    # Size of the raw session file.

    line_count: int
    # Number of lines (JSONL entries) in the raw file.

    token_count_estimate: int
    # Approximate token count (word_count * 1.3). Used for corpus statistics.

    created_at: datetime
    # File creation timestamp from filesystem metadata.

    modified_at: datetime
    # Last modification timestamp. If created_at != modified_at, note in flags.

    # === Hashes ===

    hash_raw: str
    # SHA-256 of the complete raw file content (bytes).
    # This is the primary integrity anchor.

    hash_sanitized: str | None = None
    # SHA-256 of the file after sanitization. Populated after Stage 1.
    # If hash_raw == hash_sanitized, no redactions were needed.

    hash_algorithm: str = "sha256"
    # Always SHA-256. Recorded explicitly for future-proofing.

    # === Content Metadata (non-revealing) ===

    project_hint: str | None = None
    # A non-sensitive project identifier, if detectable.
    # Example: "open-source/blog-a-claude" or "[PRIVATE_PROJECT]"

    technologies_detected: list[str] = []
    # Technologies mentioned in the session (from filename or first few lines).
    # Lightweight pre-extraction hint. Not authoritative — the extractor does real analysis.

    # === Flags ===

    flags: list[str] = []
    # Notable conditions. Examples:
    # "modified_after_creation" — file was edited after initial write
    # "large_file" — over 100KB (unusual for a session)
    # "no_user_messages" — session appears to have no human prompts
    # "contains_images" — session includes image data (base64 blocks)


class RedactionSummary(BaseModel):
    """Aggregate redaction statistics for the proof package."""

    total_redactions: int
    redactions_by_type: dict[str, int]
    # Keys: "api_key", "file_path", "email", "code_block", "company_name",
    #        "internal_url", "pii", "other"
    # Values: count of each type

    sessions_with_redactions: int
    sessions_without_redactions: int

    heaviest_redaction_session: str
    # session_id of the session with the most redactions.

    redaction_density: float
    # Average redactions per session.

    sample_redaction_types: list[str]
    # 3-5 example redaction descriptions (type only, no content).
    # Example: ["AWS API key in SDK initialization", "Absolute macOS home directory path",
    #           "Client company name in error log context"]


class PublicRepoCorrelation(BaseModel):
    """Evidence linking session activity to public git history."""

    repo_url: str
    repo_name: str

    session_ids: list[str]
    # Sessions that appear to relate to this repo.

    commit_hashes: list[str]
    # Public commits that correlate with session dates/content.

    correlation_type: Literal[
        "filename_match",       # Session touches files matching repo structure
        "temporal",             # Session timestamp close to commit timestamp
        "content_reference",    # Session discusses repo by name
        "combined"              # Multiple correlation types
    ]

    correlation_strength: Literal["strong", "moderate", "weak"]
    # strong: multiple signals align (filename + temporal + content)
    # moderate: two signals or one very clear signal
    # weak: single indirect signal

    notes: str
    # Brief explanation of the correlation evidence.


class PipelineArtifactRecord(BaseModel):
    """Hash record for a pipeline-generated artifact."""

    artifact_name: str
    # Example: "candidate_profile.json", "match_evaluation.json"

    artifact_path: str
    # Relative path within pipeline_output/{run_id}/

    hash: str
    # SHA-256 of the artifact content.

    generated_at: datetime
    generated_by: str
    # Agent name that produced this artifact.

    schema_version: str
    # Version of the schema the artifact conforms to.


class SessionManifest(BaseModel):
    """
    The complete trust document for a pipeline run.

    This manifest provides a cryptographic chain of custody from raw session
    files through the pipeline to final deliverables. It proves:
    - Which sessions were processed (by hash, not content)
    - What was redacted (by category, not content)
    - How public repos correlate with session activity
    - What the pipeline produced (by hash)

    The manifest itself is hashed and the hash is included in deliverables.
    """

    # === Manifest Metadata ===

    manifest_version: str = "0.1.0"
    manifest_id: str
    # UUID for this specific manifest instance.

    generated_at: datetime
    pipeline_version: str
    # Version of claude-candidate that created this manifest.

    run_id: str
    # The pipeline run this manifest belongs to.

    # === Session Records ===

    sessions: list[SessionFileRecord]
    # One record per session file included in the pipeline.

    corpus_statistics: CorpusStatistics
    # Aggregate stats for the proof package (see below).

    # === Redaction Summary ===

    redaction_summary: RedactionSummary

    # === Public Correlations ===

    public_repo_correlations: list[PublicRepoCorrelation]
    # Cross-references between sessions and public git activity.
    # Empty list is valid — not all work results in public commits.

    # === Pipeline Artifacts ===

    pipeline_artifacts: list[PipelineArtifactRecord]
    # Hash records for all pipeline-generated files.
    # Enables verification that deliverables came from this specific run.

    # === Manifest Integrity ===

    manifest_hash: str | None = None
    # SHA-256 of this manifest excluding this field.
    # Set as the final step after all other fields are populated.
    # Verification: remove this field, serialize, hash, compare.


class CorpusStatistics(BaseModel):
    """Non-revealing aggregate statistics about the session corpus."""

    total_sessions: int
    total_lines: int
    total_tokens_estimate: int

    date_range_start: datetime
    date_range_end: datetime
    date_span_days: int

    sessions_per_month: dict[str, int]
    # Keys: "YYYY-MM", Values: session count. Shows activity distribution.

    unique_projects: int
    # Number of distinct projects detected across sessions.

    technologies_overview: dict[str, int]
    # Top technologies by session count. Shows breadth.
    # Example: {"python": 45, "typescript": 12, "bash": 38, "react": 8}

    average_session_length_tokens: int
    median_session_length_tokens: int
    longest_session_tokens: int
```

## Implementation Modules

### Module 1: Hasher (`src/claude_candidate/manifest.py`)

The core hashing engine.

```python
"""
Session manifest creation and verification.

All hashing uses SHA-256 via Python's hashlib (standard library, no dependencies).
Files are read in binary mode and hashed in 8KB chunks for memory efficiency.
"""

import hashlib
from pathlib import Path

CHUNK_SIZE = 8192  # 8KB chunks for streaming hash

def hash_file(path: Path) -> str:
    """SHA-256 hash of a file's contents, read in streaming chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()

def hash_string(content: str) -> str:
    """SHA-256 hash of a string (UTF-8 encoded)."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()

def hash_json_stable(data: dict) -> str:
    """
    SHA-256 hash of a JSON-serializable dict with stable key ordering.

    Uses json.dumps with sort_keys=True and no extra whitespace to ensure
    the same logical content always produces the same hash, regardless of
    insertion order or formatting.
    """
    import json
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str)
    return hash_string(canonical)
```

### Module 2: Session Scanner (`src/claude_candidate/selector.py`)

Discovers and catalogs session files.

```python
def scan_sessions(paths: list[Path]) -> list[SessionFileRecord]:
    """
    Scan session files and create initial manifest records.

    For each file:
    1. Compute SHA-256 hash
    2. Count lines and estimate tokens
    3. Read filesystem timestamps
    4. Detect project context from path structure
    5. Quick-scan first 20 lines for technology hints

    Returns SessionFileRecord instances with hash_sanitized=None
    (populated later by the sanitizer).
    """
    ...

def generate_session_id(path: Path) -> str:
    """
    Generate a stable session ID from file metadata.

    Format: YYYY-MM-DD_HH-MM-SS_{path_hash_prefix}
    The path_hash_prefix is the first 8 chars of SHA-256(relative_path),
    ensuring uniqueness even for sessions at the same timestamp.
    """
    ...

def detect_project_from_path(path: Path) -> str | None:
    """
    Infer project context from Claude Code's directory structure.

    Claude Code stores sessions under ~/.claude/projects/{project_hash}/sessions/
    The project_hash can be mapped to a project name via ~/.claude/projects/*/config.json
    Returns the project name if detectable, "[PRIVATE_PROJECT]" if config exists
    but name is sensitive, or None if undetectable.
    """
    ...
```

### Module 3: Manifest Builder (`src/claude_candidate/manifest.py`)

Assembles the complete manifest.

```python
def create_manifest(
    session_records: list[SessionFileRecord],
    redaction_summary: RedactionSummary,
    pipeline_artifacts: list[PipelineArtifactRecord],
    public_correlations: list[PublicRepoCorrelation],
    run_id: str,
    pipeline_version: str,
) -> SessionManifest:
    """
    Assemble a complete SessionManifest.

    1. Compute corpus statistics from session records
    2. Assemble all components
    3. Serialize the manifest (excluding manifest_hash)
    4. Hash the serialized form
    5. Set manifest_hash
    6. Return the complete manifest

    The manifest_hash enables self-verification:
    to verify, set manifest_hash=None, serialize, hash, compare.
    """
    ...

def verify_manifest(manifest: SessionManifest) -> ManifestVerification:
    """
    Verify a manifest's internal consistency.

    Checks:
    1. manifest_hash matches recomputed hash of manifest-without-hash
    2. All session_ids are unique
    3. Corpus statistics are consistent with session records
    4. Pipeline artifact hashes are present for expected artifacts
    5. Date ranges are internally consistent

    Returns a ManifestVerification with pass/fail and details.
    """
    ...

def verify_sessions_against_manifest(
    manifest: SessionManifest,
    session_dir: Path,
) -> list[SessionVerificationResult]:
    """
    Verify that session files on disk match their manifest records.

    For each session in the manifest:
    1. Locate the file (by session_id or path)
    2. Recompute SHA-256
    3. Compare against hash_raw
    4. Report: match, mismatch, or missing

    This is the core proof mechanism: "these files were the input."
    """
    ...
```

### Module 4: Public Repo Correlator (`src/claude_candidate/correlator.py`)

Discovers links between sessions and public git history.

```python
def correlate_with_public_repos(
    session_records: list[SessionFileRecord],
    candidate_profile: CandidateProfile,
    repo_urls: list[str] | None = None,
) -> list[PublicRepoCorrelation]:
    """
    Find correlations between session activity and public git repos.

    Strategy:
    1. Identify public repos from CandidateProfile.projects[].public_repo_url
       and/or user-provided repo_urls
    2. For each repo, fetch recent commit history (git log via API or local clone)
    3. For each session, check:
       a. Filename match: do files touched in the session appear in the repo?
       b. Temporal match: is there a commit within 24h of the session?
       c. Content match: does the session mention the repo name?
    4. Score and classify each correlation

    Note: This module makes network requests to GitHub API (public repos only).
    It respects rate limits and caches responses.
    """
    ...

def fetch_commit_history(repo_url: str, since: datetime, until: datetime) -> list[CommitRecord]:
    """
    Fetch public commit history from GitHub API.

    Uses the unauthenticated API (60 requests/hour) or authenticated if
    a GITHUB_TOKEN is available. Only fetches commits within the session
    corpus date range to minimize API usage.
    """
    ...


class CommitRecord(BaseModel):
    """Lightweight commit record for correlation."""
    hash: str
    message: str
    author_date: datetime
    files_changed: list[str]
```

### Module 5: Proof Package Generator (`src/claude_candidate/proof_generator.py`)

Transforms the manifest into human-readable documentation.

```python
def generate_proof_package(
    manifest: SessionManifest,
    candidate_profile: CandidateProfile,
    match_evaluation: MatchEvaluation,
    pipeline_source_url: str,
) -> str:
    """
    Generate the proof_package.md deliverable.

    Sections:
    1. What This Is — brief explanation of the pipeline and its purpose
    2. Corpus Overview — statistics from CorpusStatistics (non-revealing)
    3. Verification — how the hashes work, what they prove, what they don't
    4. Public Corroboration — cross-references to public repos with links
    5. Redaction Transparency — what categories were redacted and aggregate counts
    6. Limitations — honest statement of what the proof does not establish
    7. Pipeline Source — link to the open-source repo
    8. Manifest Reference — instructions for requesting the full manifest

    The output is markdown formatted for inclusion as a document appendix
    or standalone page.
    """
    ...
```

## Hashing Protocol

### What Gets Hashed and When

```
Timeline:
─────────────────────────────────────────────────────────────────

T0: User selects sessions
    → hash_raw computed for each session file
    → SessionFileRecords created

T1: Sanitizer completes
    → hash_sanitized computed for each cleaned file
    → Redaction log written

T2: Extractor completes
    → candidate_profile.json hashed → PipelineArtifactRecord

T3: Job Parser completes
    → job_requirements.json hashed → PipelineArtifactRecord
    → job posting text hashed → JobRequirements.posting_text_hash

T4: Matcher completes
    → match_evaluation.json hashed → PipelineArtifactRecord
    → CandidateProfile hash recorded in MatchEvaluation.profile_hash
    → JobRequirements hash recorded in MatchEvaluation.job_hash

T5: Writer completes
    → Each deliverable hashed → PipelineArtifactRecord

T6: Manifest assembled
    → All records and artifacts collected
    → CorpusStatistics computed
    → PublicRepoCorrelations resolved
    → Manifest serialized (sans manifest_hash)
    → manifest_hash computed
    → Final manifest written

T7: Manifest self-verification
    → Automated verification pass confirms internal consistency
```

### Hash Chain Integrity

The hash chain ensures that each stage's output is cryptographically linked to its inputs:

```
hash_raw (session files)
    ↓ [sanitization]
hash_sanitized (cleaned files)
    ↓ [extraction]
candidate_profile hash
    ↓ [matching]                job_requirements hash
    ↓                              ↓
match_evaluation hash ← profile_hash + job_hash
    ↓ [generation]
deliverable hashes
    ↓
manifest_hash (covers everything above)
```

To verify the chain: start from manifest_hash, verify the manifest, then verify each artifact hash, then verify session hashes against files on disk. If every link holds, the deliverables are provably derived from the claimed sessions.

## CLI Commands

### Create Manifest

```bash
claude-candidate manifest create \
  --sessions ~/.claude/projects/*/sessions/*.jsonl \
  --output ./manifest.json
```

Scans all matching session files, computes hashes, generates session IDs, and writes an initial manifest (pre-sanitization, no pipeline artifacts).

### Verify Manifest

```bash
claude-candidate manifest verify \
  --manifest ./pipeline_output/run_123/manifest/session_manifest.json \
  --sessions ~/.claude/projects/*/sessions/
```

Recomputes hashes for all session files referenced in the manifest and reports matches, mismatches, and missing files.

### Verify Pipeline Run

```bash
claude-candidate manifest verify-run \
  --run-dir ./pipeline_output/run_123/
```

Verifies the complete chain: manifest self-hash, all pipeline artifact hashes, and optionally session file hashes if the original files are accessible.

### Export Proof Package

```bash
claude-candidate manifest proof-package \
  --run-dir ./pipeline_output/run_123/ \
  --output ./proof_package.md \
  --pipeline-url https://github.com/brianruggieri/claude-candidate
```

Generates the human-readable proof package document from the manifest.

## Security Considerations

### What the manifest does NOT protect against

1. **Fabricated sessions**: A user could create fake session files, hash them, and run the pipeline. The manifest proves integrity, not authenticity. Mitigation: public repo correlations provide independent corroboration; fabricating both session logs and matching git history is significantly harder.

2. **Selective omission**: The user chooses which sessions to include. They could omit sessions that show weaknesses. Mitigation: the manifest records session count and date range; large gaps in the date range or unexpectedly low session counts relative to public commit frequency could be notable.

3. **Post-hoc modification**: If the user modifies a session file and re-hashes it, the new manifest would be consistent but different from any earlier manifest. Mitigation: if manifests are shared (e.g., embedded in a git commit), the timestamp provides a reference point.

### What the manifest DOES protect against

1. **Pipeline fabrication**: Someone can't claim "the pipeline analyzed 500 sessions" without having 500 hashable files. The manifest links specific file hashes to specific claims.

2. **Deliverable tampering**: If someone modifies the resume after generation, the hash chain breaks. The deliverable hashes in the manifest won't match.

3. **Invisible redaction**: The redaction summary makes the sanitization process transparent. A reviewer can see that 47 API keys and 12 code blocks were redacted, rather than wondering what was hidden.

### Recommendations for advanced trust (v2+)

- **Timestamping service**: Hash the manifest and submit to a timestamping authority (RFC 3161) or a blockchain for irrefutable proof of existence at a specific time. Overkill for v1 but architecturally supported.
- **GPG signing**: Sign the manifest with the user's GPG key, linking it to a verifiable identity.
- **Git-anchored manifests**: Commit the manifest hash to a public repo. The git commit provides a timestamp and links the manifest to a public identity.

## Implementation Tasks

### Task 1: Core Hasher
**File**: `src/claude_candidate/manifest.py` (hash functions)
- Implement `hash_file()`, `hash_string()`, `hash_json_stable()`
- Unit tests for each function
- Test with known test vectors (SHA-256 of "hello world", etc.)
- Test `hash_json_stable()` produces same hash regardless of key order

### Task 2: Session Scanner
**File**: `src/claude_candidate/selector.py`
- Implement `scan_sessions()`, `generate_session_id()`, `detect_project_from_path()`
- Handle edge cases: empty files, binary content, non-UTF-8 encoding
- Test with sample JSONL files (create fixtures)

### Task 3: Manifest Builder
**File**: `src/claude_candidate/manifest.py` (builder functions)
- Implement `create_manifest()`, `verify_manifest()`, `verify_sessions_against_manifest()`
- Implement `CorpusStatistics` computation
- Test round-trip: create → serialize → deserialize → verify
- Test tamper detection: modify one hash, verify should fail

### Task 4: Public Repo Correlator
**File**: `src/claude_candidate/correlator.py`
- Implement GitHub API integration (unauthenticated + token-based)
- Implement correlation detection (filename, temporal, content)
- Implement correlation scoring and classification
- Test with known public repos (the candidate's actual repos)
- Handle API rate limits gracefully

### Task 5: Proof Package Generator
**File**: `src/claude_candidate/proof_generator.py`
- Implement markdown generation from manifest data
- Include all sections as specified
- Test with sample manifest data
- Review output for accidental information leakage

### Task 6: CLI Commands
**File**: `src/claude_candidate/cli.py` (manifest subcommands)
- Implement `manifest create`, `manifest verify`, `manifest verify-run`, `manifest proof-package`
- Integration tests for each command
- Test with real session files if available, fixtures otherwise

### Task 7: Integration with Pipeline
- Hook manifest creation into the orchestrator's parallel execution
- Ensure sanitizer updates `hash_sanitized` fields
- Ensure each agent writes PipelineArtifactRecords
- Verify the complete hash chain in end-to-end tests

## Acceptance Criteria

1. `hash_file()` produces correct SHA-256 for known test vectors.
2. `hash_json_stable()` produces identical hashes for logically equivalent dicts with different key orders.
3. Manifest creation processes 100 session files in under 10 seconds (hashing is I/O-bound, not CPU-bound).
4. Manifest self-verification detects any single-field modification.
5. Session verification correctly identifies matching, mismatched, and missing files.
6. Public repo correlator finds at least one correlation for the candidate's known public repos.
7. Proof package markdown contains no raw session content, file paths, or secrets.
8. All CLI commands work end-to-end with sample data.
9. The tamper detection tests cover: modified session file, modified manifest field, removed session record, added fabricated session record.

## Dependencies

- Python 3.11+ (hashlib is standard library)
- pydantic >= 2.0 (schema models)
- httpx (GitHub API requests — async capable)
- click (CLI commands)
- No cryptographic libraries beyond hashlib (SHA-256 is sufficient for integrity; we're not doing encryption)

## Notes for Agent Team Lead

The manifest module is the foundation of the trust argument. Every shortcut here undermines the entire proof model. Specific areas that need extra care:

1. **Stable serialization**: `hash_json_stable()` must be deterministic. Test with edge cases: Unicode strings, floating-point numbers, nested structures, None values. If any of these serialize differently across Python versions or platforms, the hashes won't match.

2. **Path handling**: Absolute paths must never appear in the manifest. Use `os.path.relpath()` anchored to the user's home directory, and verify by grepping the serialized manifest for common path prefixes (/Users/, /home/, C:\).

3. **The proof package is the public face**. It will be read by non-technical people (recruiters, hiring managers). It must be clear, professional, and honest about what it proves and what it doesn't. Don't over-claim. The limitations section is as important as the verification section.

4. **Public repo correlation is the highest-value trust signal.** It's independently verifiable, requires no cooperation from the candidate beyond sharing the manifest, and is difficult to fabricate. Invest extra effort here — a strong correlator makes the entire proof model significantly more convincing.

5. **Hash chain verification should be one command.** `claude-candidate manifest verify-run --run-dir ./output/` should check everything and produce a clear pass/fail report. Make the UX of verification as simple as the UX of generation.
