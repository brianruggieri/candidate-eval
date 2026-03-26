"""
Backward-compatibility shim for claude_candidate.quick_match.

All scoring logic now lives in the claude_candidate.scoring subpackage.
This module re-exports the public API so existing import paths continue to work.

Scheduled for removal at end of Phase 3 (v0.8.2).
"""

# Re-export everything from the scoring subpackage.
# This allows `from claude_candidate.quick_match import X` to continue working.
from claude_candidate.scoring import *  # noqa: F401, F403
from claude_candidate.scoring import (  # explicit re-exports for type checkers
	AdoptionVelocityResult,
	AssessmentInput,
	QuickMatchEngine,
	SummaryInput,
	compute_adoption_velocity,
	compute_match_confidence,
)
