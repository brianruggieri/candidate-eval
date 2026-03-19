"""Tests for the `profile review` CLI command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from claude_candidate.cli import main


FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestProfileReviewCommand:
    """Integration tests for `profile review`."""

    def test_review_accept_defaults_skip_gaps(self, tmp_path):
        """With no prompts answered and --skip-gaps, command succeeds and writes output."""
        output = tmp_path / "curated_profile.json"

        runner = CliRunner()
        # Supply Enter for each confirm prompt (accept defaults), skip gap-fill
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(FIXTURES_DIR / "sample_candidate_profile.json"),
                "--output", str(output),
                "--skip-gaps",
            ],
            input="\n" * 20,  # Enter for every confirm prompt
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert output.exists(), "Output file should have been written"

    def test_review_output_structure(self, tmp_path):
        """Output JSON has the expected top-level structure."""
        output = tmp_path / "curated_profile.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(FIXTURES_DIR / "sample_candidate_profile.json"),
                "--output", str(output),
                "--skip-gaps",
            ],
            input="\n" * 20,
        )

        assert result.exit_code == 0, f"CLI failed: {result.output}"

        data = json.loads(output.read_text())
        assert data["curated"] is True
        assert "curated_at" in data
        assert isinstance(data["patterns"], list)
        assert "resume_integration" in data
        assert "curated_resume_path" in data["resume_integration"]
        assert "curated_resume_exists" in data["resume_integration"]

    def test_review_session_evidence_patterns(self, tmp_path):
        """Session-evidence patterns appear in output with correct source."""
        output = tmp_path / "curated_profile.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(FIXTURES_DIR / "sample_candidate_profile.json"),
                "--output", str(output),
                "--skip-gaps",
            ],
            input="\n" * 20,
        )

        assert result.exit_code == 0

        data = json.loads(output.read_text())
        session_patterns = [p for p in data["patterns"] if p["source"] == "session_evidence"]

        # The sample profile has 7 observed patterns
        assert len(session_patterns) == 7

        for p in session_patterns:
            assert p["observed_strength"] is not None
            assert p["self_reported_strength"] is not None
            assert isinstance(p["delta"], int)
            assert p["session_count"] >= 1

    def test_review_no_gap_fill_when_skip_gaps(self, tmp_path):
        """Gap-fill patterns absent when --skip-gaps is set."""
        output = tmp_path / "curated_profile.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(FIXTURES_DIR / "sample_candidate_profile.json"),
                "--output", str(output),
                "--skip-gaps",
            ],
            input="\n" * 20,
        )

        assert result.exit_code == 0

        data = json.loads(output.read_text())
        gap_patterns = [p for p in data["patterns"] if p["source"] == "scenario_gap_fill"]
        assert len(gap_patterns) == 0

    def test_review_gap_fill_produces_self_reported_patterns(self, tmp_path):
        """Gap-fill answers produce scenario_gap_fill patterns."""
        output = tmp_path / "curated_profile.json"

        # Sample profile has 7 observed → 5 gaps.
        # Each scenario has 3 options (a/b/c); we answer 'a' (strong match) for all.
        gap_answers = "a\n" * 5

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(FIXTURES_DIR / "sample_candidate_profile.json"),
                "--output", str(output),
                # No --skip-gaps
            ],
            input=("\n" * 7) + gap_answers,  # 7 confirms + 5 scenario answers
        )

        assert result.exit_code == 0, f"CLI failed:\n{result.output}"

        data = json.loads(output.read_text())
        gap_patterns = [p for p in data["patterns"] if p["source"] == "scenario_gap_fill"]
        assert len(gap_patterns) == 5

        for p in gap_patterns:
            assert p["observed_strength"] is None
            assert p["self_reported_strength"] in ("emerging", "established")
            assert p["delta"] is None
            assert p["session_count"] == 0

    def test_review_adjust_pattern_strength(self, tmp_path):
        """Adjusting a pattern strength records a non-zero delta."""
        output = tmp_path / "curated_profile.json"

        # The first pattern in the sample profile is architecture_first (exceptional).
        # We'll adjust it to 'strong' (rank 3 vs 4 → delta -1), then confirm the rest.
        # 'x' maps to exceptional (no change for the first would be just Enter).
        # 's' maps to strong → delta = -1
        adjust_input = "s\n" + "\n" * 6  # adjust first, confirm remaining 6

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(FIXTURES_DIR / "sample_candidate_profile.json"),
                "--output", str(output),
                "--skip-gaps",
            ],
            input=adjust_input,
        )

        assert result.exit_code == 0, f"CLI failed:\n{result.output}"

        data = json.loads(output.read_text())
        session_patterns = [p for p in data["patterns"] if p["source"] == "session_evidence"]

        # First pattern should show the adjustment
        first = session_patterns[0]
        assert first["pattern_type"] == "architecture_first"
        assert first["observed_strength"] == "exceptional"
        assert first["self_reported_strength"] == "strong"
        assert first["delta"] == -1

    def test_review_default_output_path(self, tmp_path, monkeypatch):
        """Without --output, writes to ~/.claude-candidate/curated_profile.json."""
        fake_home = tmp_path / "home"
        fake_home.mkdir()

        # Patch Path.home() to return our temp dir
        monkeypatch.setattr(Path, "home", staticmethod(lambda: fake_home))

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(FIXTURES_DIR / "sample_candidate_profile.json"),
                "--skip-gaps",
            ],
            input="\n" * 20,
        )

        assert result.exit_code == 0, f"CLI failed:\n{result.output}"
        expected = fake_home / ".claude-candidate" / "curated_profile.json"
        assert expected.exists(), f"Expected output at {expected}"

    def test_review_shows_strength_bars_in_output(self, tmp_path):
        """Terminal output includes Unicode strength bars."""
        output = tmp_path / "curated_profile.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(FIXTURES_DIR / "sample_candidate_profile.json"),
                "--output", str(output),
                "--skip-gaps",
            ],
            input="\n" * 20,
        )

        assert result.exit_code == 0
        # At least one strength bar character should appear
        assert "█" in result.output

    def test_review_shows_session_counts(self, tmp_path):
        """Terminal output shows session counts for observed patterns."""
        output = tmp_path / "curated_profile.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(FIXTURES_DIR / "sample_candidate_profile.json"),
                "--output", str(output),
                "--skip-gaps",
            ],
            input="\n" * 20,
        )

        assert result.exit_code == 0
        assert "session" in result.output.lower()

    def test_review_resume_integration_field_set_correctly(self, tmp_path):
        """resume_integration correctly reports whether curated_resume.json exists."""
        output = tmp_path / "curated_profile.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(FIXTURES_DIR / "sample_candidate_profile.json"),
                "--output", str(output),
                "--skip-gaps",
            ],
            input="\n" * 20,
        )

        assert result.exit_code == 0
        data = json.loads(output.read_text())

        # curated_resume.json does NOT exist in actual home in test env;
        # the field should be a boolean regardless
        assert isinstance(data["resume_integration"]["curated_resume_exists"], bool)

    def test_review_invalid_candidate_path_fails(self, tmp_path):
        """Non-existent candidate file causes non-zero exit."""
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(tmp_path / "nonexistent.json"),
                "--skip-gaps",
            ],
        )
        assert result.exit_code != 0

    def test_review_step1_skipped_gracefully_if_no_patterns(self, tmp_path):
        """Profile with no patterns proceeds without error."""
        # Create a minimal profile with zero patterns
        base = json.loads((FIXTURES_DIR / "sample_candidate_profile.json").read_text())
        base["problem_solving_patterns"] = []
        minimal_path = tmp_path / "minimal_profile.json"
        minimal_path.write_text(json.dumps(base))
        output = tmp_path / "curated.json"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "profile", "review",
                "--candidate", str(minimal_path),
                "--output", str(output),
                "--skip-gaps",
            ],
            input="\n" * 5,
        )

        assert result.exit_code == 0, f"CLI failed:\n{result.output}"
        data = json.loads(output.read_text())
        # No session-evidence patterns
        assert all(p["source"] != "session_evidence" for p in data["patterns"])
