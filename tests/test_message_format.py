"""Tests for the message normalization module."""

from __future__ import annotations

import pytest

from claude_candidate.message_format import (
    NormalizedMessage,
    normalize_messages,
)


# ---------------------------------------------------------------------------
# normalize_messages: top-level tool_use events
# ---------------------------------------------------------------------------


class TestNormalizeToolUseEvents:
    def test_role_is_tool_use(self) -> None:
        raw = [{"type": "tool_use", "toolUse": {"name": "Read", "input": {"file_path": "foo.py"}}}]
        msgs = normalize_messages(raw)
        assert msgs[0]["role"] == "tool_use"

    def test_content_has_one_tool_use_block(self) -> None:
        raw = [{"type": "tool_use", "toolUse": {"name": "Write", "input": {"file_path": "x.py"}}}]
        msgs = normalize_messages(raw)
        assert len(msgs[0]["content"]) == 1
        assert msgs[0]["content"][0]["type"] == "tool_use"

    def test_tool_use_block_has_name_and_input(self) -> None:
        raw = [{"type": "tool_use", "toolUse": {"name": "Bash", "input": {"command": "ls"}}}]
        msgs = normalize_messages(raw)
        block = msgs[0]["content"][0]
        assert block["name"] == "Bash"
        assert block["input"] == {"command": "ls"}

    def test_raw_field_preserved(self) -> None:
        event = {"type": "tool_use", "toolUse": {"name": "Grep", "input": {}}, "sessionId": "s1"}
        msgs = normalize_messages([event])
        assert msgs[0]["raw"]["sessionId"] == "s1"

    def test_missing_tooluse_key_gives_empty_block(self) -> None:
        raw = [{"type": "tool_use"}]
        msgs = normalize_messages(raw)
        assert msgs[0]["role"] == "tool_use"
        block = msgs[0]["content"][0]
        assert block["name"] == ""
        assert block["input"] == {}


# ---------------------------------------------------------------------------
# normalize_messages: assistant events
# ---------------------------------------------------------------------------


class TestNormalizeAssistantEvents:
    def test_role_is_assistant(self) -> None:
        raw = [{"type": "assistant", "message": {"content": []}}]
        msgs = normalize_messages(raw)
        assert msgs[0]["role"] == "assistant"

    def test_text_block_preserved(self) -> None:
        raw = [
            {
                "type": "assistant",
                "message": {
                    "content": [{"type": "text", "text": "I'll read the file."}]
                },
            }
        ]
        msgs = normalize_messages(raw)
        assert len(msgs[0]["content"]) == 1
        assert msgs[0]["content"][0]["type"] == "text"
        assert msgs[0]["content"][0]["text"] == "I'll read the file."

    def test_nested_tool_use_block_preserved(self) -> None:
        raw = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "app.py"}}
                    ]
                },
            }
        ]
        msgs = normalize_messages(raw)
        block = msgs[0]["content"][0]
        assert block["type"] == "tool_use"
        assert block["name"] == "Read"

    def test_mixed_content_blocks(self) -> None:
        raw = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "text", "text": "Let me check"},
                        {"type": "tool_use", "name": "Read", "input": {"file_path": "x.py"}},
                    ]
                },
            }
        ]
        msgs = normalize_messages(raw)
        assert len(msgs[0]["content"]) == 2
        assert msgs[0]["content"][0]["type"] == "text"
        assert msgs[0]["content"][1]["type"] == "tool_use"

    def test_string_content_becomes_text_block(self) -> None:
        raw = [
            {
                "type": "assistant",
                "message": {"content": "Plain string content"},
            }
        ]
        msgs = normalize_messages(raw)
        assert len(msgs[0]["content"]) == 1
        assert msgs[0]["content"][0]["type"] == "text"
        assert msgs[0]["content"][0]["text"] == "Plain string content"

    def test_empty_content_gives_empty_list(self) -> None:
        raw = [{"type": "assistant", "message": {"content": []}}]
        msgs = normalize_messages(raw)
        assert msgs[0]["content"] == []


# ---------------------------------------------------------------------------
# normalize_messages: user events
# ---------------------------------------------------------------------------


class TestNormalizeUserEvents:
    def test_role_is_user(self) -> None:
        raw = [{"type": "user", "message": {"content": "hello"}}]
        msgs = normalize_messages(raw)
        assert msgs[0]["role"] == "user"

    def test_string_content_becomes_text_block(self) -> None:
        raw = [{"type": "user", "message": {"content": "fix this bug"}}]
        msgs = normalize_messages(raw)
        assert len(msgs[0]["content"]) == 1
        assert msgs[0]["content"][0]["type"] == "text"
        assert msgs[0]["content"][0]["text"] == "fix this bug"

    def test_list_content_with_text_block(self) -> None:
        raw = [
            {
                "type": "user",
                "message": {"content": [{"type": "text", "text": "fix this bug"}]},
            }
        ]
        msgs = normalize_messages(raw)
        assert msgs[0]["content"][0]["text"] == "fix this bug"

    def test_list_content_with_tool_result_block(self) -> None:
        raw = [
            {
                "type": "user",
                "message": {
                    "content": [{"type": "tool_result", "content": "file contents", "is_error": False}]
                },
            }
        ]
        msgs = normalize_messages(raw)
        block = msgs[0]["content"][0]
        assert block["type"] == "tool_result"
        assert block["content"] == "file contents"
        assert block["is_error"] is False

    def test_empty_string_content_gives_empty_list(self) -> None:
        raw = [{"type": "user", "message": {"content": ""}}]
        msgs = normalize_messages(raw)
        assert msgs[0]["content"] == []


# ---------------------------------------------------------------------------
# normalize_messages: tool_result events
# ---------------------------------------------------------------------------


class TestNormalizeToolResultEvents:
    def test_role_is_tool_result(self) -> None:
        raw = [{"type": "tool_result", "content": "output"}]
        msgs = normalize_messages(raw)
        assert msgs[0]["role"] == "tool_result"

    def test_content_has_one_tool_result_block(self) -> None:
        raw = [{"type": "tool_result", "content": "file contents"}]
        msgs = normalize_messages(raw)
        assert len(msgs[0]["content"]) == 1
        block = msgs[0]["content"][0]
        assert block["type"] == "tool_result"
        assert block["content"] == "file contents"

    def test_is_error_defaults_false(self) -> None:
        raw = [{"type": "tool_result", "content": "ok"}]
        msgs = normalize_messages(raw)
        assert msgs[0]["content"][0]["is_error"] is False

    def test_is_error_propagated(self) -> None:
        raw = [{"type": "tool_result", "content": "error text", "is_error": True}]
        msgs = normalize_messages(raw)
        assert msgs[0]["content"][0]["is_error"] is True


# ---------------------------------------------------------------------------
# normalize_messages: system events
# ---------------------------------------------------------------------------


class TestNormalizeSystemEvents:
    def test_role_is_system(self) -> None:
        raw = [{"type": "system", "content": "some system content"}]
        msgs = normalize_messages(raw)
        assert msgs[0]["role"] == "system"

    def test_content_is_empty_list(self) -> None:
        raw = [{"type": "system", "content": "some system content"}]
        msgs = normalize_messages(raw)
        assert msgs[0]["content"] == []

    def test_raw_preserved(self) -> None:
        raw = [{"type": "system", "summary": "session started"}]
        msgs = normalize_messages(raw)
        assert msgs[0]["raw"]["summary"] == "session started"


# ---------------------------------------------------------------------------
# normalize_messages: unknown event types
# ---------------------------------------------------------------------------


class TestNormalizeUnknownEvents:
    def test_unknown_type_becomes_system_role(self) -> None:
        raw = [{"type": "summary", "data": "some data"}]
        msgs = normalize_messages(raw)
        assert msgs[0]["role"] == "system"

    def test_unknown_type_has_empty_content(self) -> None:
        raw = [{"type": "summary", "data": "some data"}]
        msgs = normalize_messages(raw)
        assert msgs[0]["content"] == []


# ---------------------------------------------------------------------------
# normalize_messages: multi-event batches and edge cases
# ---------------------------------------------------------------------------


class TestNormalizeMessagesBatch:
    def test_empty_list_returns_empty(self) -> None:
        assert normalize_messages([]) == []

    def test_multiple_events_produce_one_message_each(self) -> None:
        raw = [
            {"type": "user", "message": {"content": "hello"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "hi"}]}},
            {"type": "tool_use", "toolUse": {"name": "Read", "input": {}}},
        ]
        msgs = normalize_messages(raw)
        assert len(msgs) == 3
        assert msgs[0]["role"] == "user"
        assert msgs[1]["role"] == "assistant"
        assert msgs[2]["role"] == "tool_use"

    def test_unknown_content_block_types_are_skipped(self) -> None:
        raw = [
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {"type": "thinking", "thinking": "some thought"},
                        {"type": "text", "text": "result"},
                    ]
                },
            }
        ]
        msgs = normalize_messages(raw)
        # thinking block is unknown, skipped; only text block remains
        assert len(msgs[0]["content"]) == 1
        assert msgs[0]["content"][0]["type"] == "text"

    @pytest.mark.parametrize(
        "event_type,expected_role",
        [
            ("user", "user"),
            ("assistant", "assistant"),
            ("tool_use", "tool_use"),
            ("tool_result", "tool_result"),
            ("system", "system"),
        ],
    )
    def test_role_mapping(self, event_type: str, expected_role: str) -> None:
        if event_type == "tool_use":
            raw = [{"type": event_type, "toolUse": {"name": "x", "input": {}}}]
        elif event_type == "tool_result":
            raw = [{"type": event_type, "content": ""}]
        else:
            raw = [{"type": event_type, "message": {"content": []}}]
        msgs = normalize_messages(raw)
        assert msgs[0]["role"] == expected_role
