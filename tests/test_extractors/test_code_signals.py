"""Tests for CodeSignalExtractor — Tier 1 skill detection from code content."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from claude_candidate.extractors import NormalizedSession
from claude_candidate.extractors.code_signals import CodeSignalExtractor
from claude_candidate.message_format import normalize_messages

FIXTURES = Path(__file__).parent.parent / "fixtures" / "sessions"


def _load_session(filename: str) -> NormalizedSession:
	lines = (FIXTURES / filename).read_text().strip().splitlines()
	raw_events = [json.loads(line) for line in lines if line.strip()]
	messages = normalize_messages(raw_events)
	session_id = "test-session"
	for msg in messages:
		sid = msg["raw"].get("sessionId", "")
		if sid:
			session_id = sid
			break
	return NormalizedSession(
		session_id=session_id,
		timestamp=datetime.now(timezone.utc),
		cwd="/Users/test/git/myproject",
		project_context="myproject",
		messages=messages,
	)


class TestCodeSignalExtractorName:
	def test_name(self):
		extractor = CodeSignalExtractor()
		assert extractor.name() == "code_signals"


class TestFileExtensionDetection:
	def test_detects_python_from_py_extension(self):
		session = _load_session("simple_python_session.jsonl")
		extractor = CodeSignalExtractor()
		result = extractor.extract_session(session)

		assert "python" in result.skills
		py_signals = result.skills["python"]
		ext_signals = [s for s in py_signals if s.source == "file_extension"]
		assert len(ext_signals) > 0
		assert all(s.confidence == 0.9 for s in ext_signals)

	def test_detects_react_and_typescript_from_tsx(self):
		session = _load_session("import_heavy_session.jsonl")
		extractor = CodeSignalExtractor()
		result = extractor.extract_session(session)

		# .tsx maps to both typescript and react
		assert "typescript" in result.skills
		ts_ext = [
			s for s in result.skills["typescript"]
			if s.source == "file_extension"
		]
		assert len(ts_ext) > 0

		assert "react" in result.skills
		react_ext = [
			s for s in result.skills["react"]
			if s.source == "file_extension"
		]
		assert len(react_ext) > 0


class TestContentPatternDetection:
	def test_detects_fastapi_from_content(self):
		session = _load_session("simple_python_session.jsonl")
		extractor = CodeSignalExtractor()
		result = extractor.extract_session(session)

		assert "fastapi" in result.skills
		pattern_signals = [
			s for s in result.skills["fastapi"]
			if s.source == "content_pattern"
		]
		assert len(pattern_signals) > 0
		assert all(s.confidence == 0.75 for s in pattern_signals)


class TestImportStatementDetection:
	def test_detects_skills_from_imports(self):
		session = _load_session("import_heavy_session.jsonl")
		extractor = CodeSignalExtractor()
		result = extractor.extract_session(session)

		# Check that import-based signals exist with correct source/confidence
		all_import_signals = []
		for signals in result.skills.values():
			all_import_signals.extend(
				s for s in signals if s.source == "import_statement"
			)
		assert len(all_import_signals) > 0
		assert all(s.confidence == 0.85 for s in all_import_signals)

	def test_detects_aws_from_boto3_import(self):
		session = _load_session("import_heavy_session.jsonl")
		extractor = CodeSignalExtractor()
		result = extractor.extract_session(session)

		assert "aws" in result.skills
		aws_import = [
			s for s in result.skills["aws"]
			if s.source == "import_statement"
		]
		assert len(aws_import) > 0


class TestPackageCommandDetection:
	def test_detects_skills_from_package_commands(self):
		session = _load_session("import_heavy_session.jsonl")
		extractor = CodeSignalExtractor()
		result = extractor.extract_session(session)

		all_pkg_signals = []
		for signals in result.skills.values():
			all_pkg_signals.extend(
				s for s in signals if s.source == "package_command"
			)
		assert len(all_pkg_signals) > 0
		assert all(s.confidence == 0.7 for s in all_pkg_signals)

	def test_detects_anthropic_from_npm_install(self):
		session = _load_session("import_heavy_session.jsonl")
		extractor = CodeSignalExtractor()
		result = extractor.extract_session(session)

		assert "anthropic" in result.skills
		anthropic_pkg = [
			s for s in result.skills["anthropic"]
			if s.source == "package_command"
		]
		assert len(anthropic_pkg) > 0


class TestMultiTechSession:
	def test_handles_multi_tech_session(self):
		session = _load_session("multi_tech_session.jsonl")
		extractor = CodeSignalExtractor()
		result = extractor.extract_session(session)

		# Should detect multiple technologies
		assert len(result.skills) >= 3
		# Should include python (from .py files)
		assert "python" in result.skills


class TestEmptySession:
	def test_returns_empty_skills_for_empty_session(self):
		session = NormalizedSession(
			session_id="empty-session",
			timestamp=datetime.now(timezone.utc),
			cwd="/Users/test/git/myproject",
			project_context="myproject",
			messages=[],
		)
		extractor = CodeSignalExtractor()
		result = extractor.extract_session(session)

		assert result.skills == {}
		assert result.metrics["file_extension_count"] == 0
		assert result.metrics["content_pattern_count"] == 0
		assert result.metrics["import_count"] == 0
		assert result.metrics["package_command_count"] == 0


class TestMetrics:
	def test_metrics_populated(self):
		session = _load_session("import_heavy_session.jsonl")
		extractor = CodeSignalExtractor()
		result = extractor.extract_session(session)

		assert "file_extension_count" in result.metrics
		assert "content_pattern_count" in result.metrics
		assert "import_count" in result.metrics
		assert "package_command_count" in result.metrics
		assert result.metrics["file_extension_count"] > 0
		assert result.metrics["import_count"] > 0
		assert result.metrics["package_command_count"] > 0


class TestEvidenceSnippets:
	def test_evidence_snippets_not_empty(self):
		session = _load_session("import_heavy_session.jsonl")
		extractor = CodeSignalExtractor()
		result = extractor.extract_session(session)

		for skill_name, signals in result.skills.items():
			for signal in signals:
				assert signal.evidence_snippet, (
					f"Empty evidence for {skill_name} ({signal.source})"
				)
				assert len(signal.evidence_snippet) <= 500
