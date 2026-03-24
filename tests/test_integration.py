"""Integration tests — full CLI flow with real fixtures."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from claude_candidate.cli import main


class TestAssessCommand:
    def test_assess_with_both_profiles(self, fixtures_dir, tmp_path):
        output = tmp_path / "assessment.json"

        runner = CliRunner()
        result = runner.invoke(main, [
            "assess",
            "--profile", str(fixtures_dir / "sample_candidate_profile.json"),
            "--resume", str(fixtures_dir / "sample_resume_profile.json"),
            "--job", str(fixtures_dir / "sample_job_posting.txt"),
            "--company", "AI Tools Corp",
            "--title", "Senior AI Engineer",
            "--seniority", "senior",
            "--output", str(output),
        ])

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert output.exists()

        # Validate output is valid JSON and a FitAssessment
        data = json.loads(output.read_text())
        assert data["company_name"] == "AI Tools Corp"
        assert data["job_title"] == "Senior AI Engineer"
        assert 0 <= data["overall_score"] <= 1
        assert data["should_apply"] in ("strong_yes", "yes", "maybe", "probably_not", "no")
        assert len(data["skill_matches"]) > 0

    def test_assess_without_resume(self, fixtures_dir, tmp_path):
        output = tmp_path / "assessment.json"

        runner = CliRunner()
        result = runner.invoke(main, [
            "assess",
            "--profile", str(fixtures_dir / "sample_candidate_profile.json"),
            "--job", str(fixtures_dir / "sample_job_posting.txt"),
            "--company", "Test Corp",
            "--title", "Engineer",
            "--output", str(output),
        ])

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert output.exists()

    def test_assess_output_to_stdout(self, fixtures_dir):
        runner = CliRunner()
        result = runner.invoke(main, [
            "assess",
            "--profile", str(fixtures_dir / "sample_candidate_profile.json"),
            "--resume", str(fixtures_dir / "sample_resume_profile.json"),
            "--job", str(fixtures_dir / "sample_job_posting.txt"),
            "--company", "Test Corp",
            "--title", "Test Role",
        ])

        assert result.exit_code == 0
        # Should print the assessment card
        assert "Test Corp" in result.output


class TestManifestCommands:
    def test_manifest_create(self, tmp_path):
        # Create a fake session file
        session = tmp_path / "session.jsonl"
        session.write_text('{"type":"user","message":"hello python"}\n')
        output = tmp_path / "manifest.json"

        runner = CliRunner()
        result = runner.invoke(main, [
            "manifest", "create",
            str(session),
            "--output", str(output),
        ])

        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert output.exists()

        data = json.loads(output.read_text())
        assert len(data["sessions"]) == 1
        assert data["manifest_hash"] is not None

    def test_manifest_verify(self, tmp_path):
        session = tmp_path / "session.jsonl"
        session.write_text('{"msg":"test"}\n')
        output = tmp_path / "manifest.json"

        runner = CliRunner()
        # Create first
        runner.invoke(main, ["manifest", "create", str(session), "--output", str(output)])

        # Then verify
        result = runner.invoke(main, ["manifest", "verify", str(output)])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    def test_manifest_create_directory(self, tmp_path):
        """Test scanning a directory of session files."""
        sessions_dir = tmp_path / "sessions"
        sessions_dir.mkdir()
        for i in range(3):
            (sessions_dir / f"s{i}.jsonl").write_text(f'{{"msg":"session {i}"}}\n')

        output = tmp_path / "manifest.json"
        runner = CliRunner()
        result = runner.invoke(main, [
            "manifest", "create",
            str(sessions_dir),
            "--output", str(output),
        ])

        assert result.exit_code == 0
        data = json.loads(output.read_text())
        assert len(data["sessions"]) == 3



class TestEndToEndFlow:
    """Full pipeline: load → merge → assess → validate output chain."""

    def test_complete_pipeline(self, fixtures_dir, tmp_path):
        """Run the entire v0.1 flow and validate the output chain."""
        from claude_candidate.schemas.candidate_profile import CandidateProfile
        from claude_candidate.schemas.resume_profile import ResumeProfile
        from claude_candidate.schemas.job_requirements import QuickRequirement
        from claude_candidate.schemas.fit_assessment import FitAssessment
        from claude_candidate.merger import merge_profiles
        from claude_candidate.quick_match import QuickMatchEngine

        # Step 1: Load profiles
        cp = CandidateProfile.from_json(
            (fixtures_dir / "sample_candidate_profile.json").read_text()
        )
        rp = ResumeProfile.from_json(
            (fixtures_dir / "sample_resume_profile.json").read_text()
        )

        # Step 2: Merge
        merged = merge_profiles(cp, rp)
        assert merged.profile_hash  # Provenance hash set
        assert merged.resume_hash == rp.source_file_hash
        assert merged.candidate_profile_hash == cp.manifest_hash

        # Step 3: Load requirements
        reqs = [
            QuickRequirement(**r)
            for r in json.loads(
                (fixtures_dir / "sample_job_posting.requirements.json").read_text()
            )
        ]

        # Step 4: Assess
        engine = QuickMatchEngine(merged)
        assessment = engine.assess(
            requirements=reqs,
            company="AI Tools Corp",
            title="Senior AI Engineer",
            seniority="senior",
            culture_signals=["open source", "documentation", "remote", "autonomous"],
            tech_stack=["python", "typescript", "react", "fastapi", "claude-api"],
        )

        # Step 5: Validate output
        assert assessment.overall_score > 0
        assert assessment.profile_hash == merged.profile_hash  # Chain intact

        # Step 6: Serialize and deserialize
        json_str = assessment.to_json()
        recovered = FitAssessment.from_json(json_str)
        assert recovered.overall_score == assessment.overall_score
        assert recovered.assessment_id == assessment.assessment_id

        # Step 7: Write to file and verify
        out_path = tmp_path / "final_assessment.json"
        out_path.write_text(json_str)
        reloaded = FitAssessment.from_json(out_path.read_text())
        assert reloaded.company_name == "AI Tools Corp"


@pytest.mark.slow
class TestJobParseCommand:
    def test_parse_job_posting(self, fixtures_dir, tmp_path):
        posting = fixtures_dir / "sample_job_posting.txt"
        output = tmp_path / "reqs.json"
        runner = CliRunner()
        result = runner.invoke(main, ["job", "parse", str(posting), "-o", str(output)])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert output.exists()
        reqs = json.loads(output.read_text())
        assert len(reqs) > 0

    def test_parse_to_stdout(self, fixtures_dir):
        posting = fixtures_dir / "sample_job_posting.txt"
        runner = CliRunner()
        result = runner.invoke(main, ["job", "parse", str(posting)])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert "description" in result.output


class TestMatchCorrelateCommand:
    def test_correlate_without_profile(self, tmp_path):
        """Correlate with no profile — should succeed with empty result (no signals to match)."""
        output = tmp_path / "correlations.json"
        runner = CliRunner()
        result = runner.invoke(main, [
            "match", "correlate",
            "--github-user", "nonexistent-user-zzz999abc",
            "-o", str(output),
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert output.exists()
        data = json.loads(output.read_text())
        assert isinstance(data, list)

    def test_correlate_with_profile(self, fixtures_dir, tmp_path):
        """Correlate with a real CandidateProfile — should produce valid JSON output."""
        output = tmp_path / "correlations.json"
        runner = CliRunner()
        result = runner.invoke(main, [
            "match", "correlate",
            "--github-user", "nonexistent-user-zzz999abc",
            "--profile", str(fixtures_dir / "sample_candidate_profile.json"),
            "-o", str(output),
        ])
        assert result.exit_code == 0, f"CLI failed: {result.output}"
        assert output.exists()
        data = json.loads(output.read_text())
        assert isinstance(data, list)


class TestProofCommand:
    def test_generates_proof_from_assessment(self, tmp_path, fixtures_dir):
        """Run assess first, then generate proof from the output file."""
        assessment_file = tmp_path / "assessment.json"
        proof_file = tmp_path / "proof.md"

        runner = CliRunner()
        # Step 1: create an assessment
        result = runner.invoke(main, [
            "assess",
            "--profile", str(fixtures_dir / "sample_candidate_profile.json"),
            "--resume", str(fixtures_dir / "sample_resume_profile.json"),
            "--job", str(fixtures_dir / "sample_job_posting.txt"),
            "--company", "Proof Corp",
            "--title", "Staff Engineer",
            "--output", str(assessment_file),
        ])
        assert result.exit_code == 0, f"assess failed: {result.output}"
        assert assessment_file.exists()

        # Step 2: generate proof
        result = runner.invoke(main, [
            "proof",
            "--assessment", str(assessment_file),
            "--output", str(proof_file),
        ])
        assert result.exit_code == 0, f"proof failed: {result.output}"
        assert proof_file.exists()

        content = proof_file.read_text()
        assert "# Proof Package" in content
        assert "Proof Corp" in content

    def test_proof_to_stdout(self, tmp_path, fixtures_dir):
        assessment_file = tmp_path / "assessment.json"

        runner = CliRunner()
        runner.invoke(main, [
            "assess",
            "--profile", str(fixtures_dir / "sample_candidate_profile.json"),
            "--job", str(fixtures_dir / "sample_job_posting.txt"),
            "--company", "Stdout Corp",
            "--title", "Engineer",
            "--output", str(assessment_file),
        ])

        result = runner.invoke(main, [
            "proof",
            "--assessment", str(assessment_file),
        ])
        assert result.exit_code == 0, f"proof failed: {result.output}"
        assert "# Proof Package" in result.output


class TestGenerateCommand:
    def _create_assessment(self, fixtures_dir, tmp_path, runner: CliRunner) -> str:
        """Helper: run assess and return path to assessment JSON."""
        out = str(tmp_path / "assessment.json")
        result = runner.invoke(main, [
            "assess",
            "--profile", str(fixtures_dir / "sample_candidate_profile.json"),
            "--resume", str(fixtures_dir / "sample_resume_profile.json"),
            "--job", str(fixtures_dir / "sample_job_posting.txt"),
            "--company", "Deliverable Corp",
            "--title", "Senior Engineer",
            "--output", out,
        ])
        assert result.exit_code == 0, f"assess failed: {result.output}"
        return out

    def test_generates_resume_bullets(self, tmp_path, fixtures_dir):
        runner = CliRunner()
        assessment_path = self._create_assessment(fixtures_dir, tmp_path, runner)
        output = tmp_path / "bullets.txt"

        with patch(
            "claude_candidate.generator.call_claude",
            return_value="- Led Python backend refactor\n- Built React dashboard",
        ):
            result = runner.invoke(main, [
                "generate-deliverable",
                "--assessment", assessment_path,
                "--type", "resume-bullets",
                "--output", str(output),
            ])
        assert result.exit_code == 0, f"generate-deliverable failed: {result.output}"
        assert output.exists()
        assert len(output.read_text()) > 0

    def test_generates_cover_letter(self, tmp_path, fixtures_dir):
        runner = CliRunner()
        assessment_path = self._create_assessment(fixtures_dir, tmp_path, runner)
        output = tmp_path / "cover_letter.txt"

        with patch(
            "claude_candidate.generator.call_claude",
            return_value="Dear Hiring Manager, I am excited to apply for this role...",
        ):
            result = runner.invoke(main, [
                "generate-deliverable",
                "--assessment", assessment_path,
                "--type", "cover-letter",
                "--output", str(output),
            ])
        assert result.exit_code == 0, f"generate-deliverable failed: {result.output}"
        assert output.exists()
        assert len(output.read_text()) > 0

    def test_generates_interview_prep(self, tmp_path, fixtures_dir):
        runner = CliRunner()
        assessment_path = self._create_assessment(fixtures_dir, tmp_path, runner)
        output = tmp_path / "interview.txt"

        with patch(
            "claude_candidate.generator.call_claude",
            return_value="## Technical Discussion Points\n- Python: strong\n## Questions to Ask\n- ?",
        ):
            result = runner.invoke(main, [
                "generate-deliverable",
                "--assessment", assessment_path,
                "--type", "interview-prep",
                "--output", str(output),
            ])
        assert result.exit_code == 0, f"generate-deliverable failed: {result.output}"
        assert output.exists()
        assert len(output.read_text()) > 0

    def test_generate_to_stdout(self, tmp_path, fixtures_dir):
        runner = CliRunner()
        assessment_path = self._create_assessment(fixtures_dir, tmp_path, runner)

        with patch(
            "claude_candidate.generator.call_claude",
            return_value="Dear Hiring Manager, I am excited to apply for this role...",
        ):
            result = runner.invoke(main, [
                "generate-deliverable",
                "--assessment", assessment_path,
                "--type", "cover-letter",
            ])
        assert result.exit_code == 0, f"generate-deliverable failed: {result.output}"
        assert len(result.output) > 0


class TestShortlistCommand:
    def test_shortlist_command_empty(self):
        """Shortlist with no entries shows message."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["shortlist", "--db", "test.db"])
            assert result.exit_code == 0, f"CLI failed: {result.output}"
            assert "No shortlisted jobs" in result.output

    def test_shortlist_command_with_data(self):
        """Shortlist with entries shows a formatted table."""
        import asyncio
        from claude_candidate.storage import AssessmentStore

        runner = CliRunner()
        with runner.isolated_filesystem():
            db_path = "test.db"

            # Pre-populate the database
            async def _seed():
                store = AssessmentStore(db_path)
                await store.initialize()
                await store.add_to_shortlist(
                    company_name="Acme Corp",
                    job_title="Senior Engineer",
                    salary="$150k",
                    location="Remote",
                    overall_grade="A-",
                )
                await store.add_to_shortlist(
                    company_name="Widget Inc",
                    job_title="Staff Developer",
                    overall_grade="B+",
                )
                await store.close()

            asyncio.run(_seed())

            result = runner.invoke(main, ["shortlist", "--db", db_path])
            assert result.exit_code == 0, f"CLI failed: {result.output}"
            assert "Acme Corp" in result.output
            assert "Senior Engineer" in result.output
            assert "$150k" in result.output
            assert "Remote" in result.output
            assert "A-" in result.output
            assert "Widget Inc" in result.output
            assert "B+" in result.output


class TestSessionsScanCommand:
    @pytest.mark.slow
    def test_scan_with_fixtures(self, tmp_path, fixtures_dir):
        """Scan fixture session files and produce a CandidateProfile."""
        sessions_dir = fixtures_dir / "sessions"
        output_path = tmp_path / "profile.json"

        runner = CliRunner()
        result = runner.invoke(main, [
            "sessions", "scan",
            "--session-dir", str(sessions_dir),
            "--output", str(output_path),
        ])

        assert result.exit_code == 0, result.output
        assert output_path.exists()

        from claude_candidate.schemas.candidate_profile import CandidateProfile
        profile = CandidateProfile.from_json(output_path.read_text())
        assert profile.session_count > 0
        assert len(profile.skills) > 0

    def test_scan_empty_dir(self, tmp_path):
        """Scan an empty directory produces no output."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        runner = CliRunner()
        result = runner.invoke(main, [
            "sessions", "scan",
            "--session-dir", str(empty_dir),
        ])

        assert result.exit_code == 0
        assert "No sessions found" in result.output

    @pytest.mark.slow
    def test_scan_session_dir_skips_whitelist(self, tmp_path, fixtures_dir):
        """--session-dir bypasses whitelist entirely — no prompt, no whitelist required."""
        sessions_dir = fixtures_dir / "sessions"
        output_path = tmp_path / "profile.json"

        runner = CliRunner()
        result = runner.invoke(main, [
            "sessions", "scan",
            "--session-dir", str(sessions_dir),
            "--output", str(output_path),
        ])

        assert result.exit_code == 0, result.output
        # No whitelist-related output expected
        assert "whitelist" not in result.output.lower()


class TestSessionsScanWhitelist:
    """Integration tests for the sessions scan whitelist flow."""

    def _make_sessions_dir(self, root: Path, projects: dict[str, int]) -> Path:
        """Create a fake ~/.claude/projects/ style directory.

        Args:
            root: tmp_path root
            projects: mapping of dir_name -> number of .jsonl files
        """
        projects_dir = root / "projects"
        projects_dir.mkdir()
        for dir_name, count in projects.items():
            proj = projects_dir / dir_name
            proj.mkdir()
            for i in range(count):
                (proj / f"session-{i:04d}.jsonl").write_text('{"msg":"test"}\n')
        return projects_dir

    def test_scan_session_dir_skips_whitelist(self, tmp_path):
        """Using --session-dir bypasses whitelist entirely."""
        projects_dir = self._make_sessions_dir(tmp_path, {
            "-Users-u-git-proj-a": 2,
            "-Users-u-git-proj-b": 1,
        })
        output_path = tmp_path / "profile.json"

        runner = CliRunner()
        result = runner.invoke(main, [
            "sessions", "scan",
            "--session-dir", str(projects_dir / "-Users-u-git-proj-a"),
            "--output", str(output_path),
        ])
        # --session-dir skips whitelist, so this should succeed without prompts
        assert result.exit_code == 0, result.output

    def test_scan_accept_defaults_without_whitelist_errors(self, tmp_path, monkeypatch):
        """--accept-defaults with no whitelist should print an error and exit 1."""
        projects_dir = self._make_sessions_dir(tmp_path, {
            "-Users-u-git-proj-a": 1,
        })
        # Point default dirs to our tmp dirs
        monkeypatch.setattr("claude_candidate.cli._default_sessions_dir", lambda: projects_dir)
        monkeypatch.setattr(
            "claude_candidate.whitelist.get_default_whitelist_path",
            lambda: tmp_path / "no_whitelist.json",
        )

        runner = CliRunner()
        result = runner.invoke(main, ["sessions", "scan", "--accept-defaults"])

        assert result.exit_code != 0
        assert "No whitelist found" in result.output or "No whitelist found" in (result.exception and str(result.exception) or "")

    def test_scan_accept_defaults_with_existing_whitelist(self, tmp_path, monkeypatch):
        """--accept-defaults with an existing whitelist uses it without prompting."""
        from claude_candidate.whitelist import WhitelistConfig, save_whitelist

        projects_dir = self._make_sessions_dir(tmp_path, {
            "-Users-u-git-proj-a": 2,
            "-Users-u-git-proj-b": 1,
        })
        whitelist_path = tmp_path / "whitelist.json"
        output_path = tmp_path / "profile.json"

        # Create a whitelist that includes proj-a
        save_whitelist(WhitelistConfig(projects=["-Users-u-git-proj-a"]), whitelist_path)

        monkeypatch.setattr("claude_candidate.cli._default_sessions_dir", lambda: projects_dir)
        monkeypatch.setattr(
            "claude_candidate.whitelist.get_default_whitelist_path",
            lambda: whitelist_path,
        )

        runner = CliRunner()
        result = runner.invoke(main, [
            "sessions", "scan",
            "--accept-defaults",
            "--output", str(output_path),
        ])

        assert result.exit_code == 0, result.output
        # Should have filtered to only proj-a sessions (2 sessions)
        assert "2 sessions" in result.output or "After whitelist" in result.output

    def test_scan_reselect_forces_prompt(self, tmp_path, monkeypatch):
        """--reselect triggers interactive selection even when whitelist exists."""
        from claude_candidate.whitelist import WhitelistConfig, save_whitelist

        projects_dir = self._make_sessions_dir(tmp_path, {
            "-Users-u-git-proj-a": 1,
        })
        whitelist_path = tmp_path / "whitelist.json"
        output_path = tmp_path / "profile.json"

        # Create an existing whitelist
        save_whitelist(WhitelistConfig(projects=["-Users-u-git-proj-a"]), whitelist_path)

        monkeypatch.setattr("claude_candidate.cli._default_sessions_dir", lambda: projects_dir)
        monkeypatch.setattr(
            "claude_candidate.whitelist.get_default_whitelist_path",
            lambda: whitelist_path,
        )

        runner = CliRunner()
        # Select all (project 1) and confirm, then the scan runs
        result = runner.invoke(main, [
            "sessions", "scan",
            "--reselect",
            "--output", str(output_path),
        ], input="all\ny\n")

        assert result.exit_code == 0, result.output
        # The interactive table should have appeared
        assert "Found" in result.output and "projects" in result.output

    def test_scan_interactive_creates_whitelist_and_scans(self, tmp_path, monkeypatch):
        """No whitelist → interactive selection → whitelist saved → scan completes."""
        from claude_candidate.whitelist import load_whitelist

        projects_dir = self._make_sessions_dir(tmp_path, {
            "-Users-u-git-myapp": 2,
            "-Users-u-git-other": 1,
        })
        whitelist_path = tmp_path / "new_whitelist.json"
        output_path = tmp_path / "profile.json"

        monkeypatch.setattr("claude_candidate.cli._default_sessions_dir", lambda: projects_dir)
        monkeypatch.setattr(
            "claude_candidate.whitelist.get_default_whitelist_path",
            lambda: whitelist_path,
        )

        runner = CliRunner()
        # Select project 1 (myapp) and confirm
        result = runner.invoke(main, [
            "sessions", "scan",
            "--output", str(output_path),
        ], input="1\ny\n")

        assert result.exit_code == 0, result.output
        # Whitelist should have been saved
        assert whitelist_path.exists()
        saved = load_whitelist(whitelist_path)
        assert saved is not None
        assert len(saved.projects) == 1
