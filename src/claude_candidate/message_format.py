"""
Canonical message format for Claude Code session JSONL events.

JSONL sessions contain several event types with inconsistent shapes.
This module defines a single normalized representation and converts
raw parsed events into it before downstream processing.

Canonical shape:
    role: "user" | "assistant" | "tool_use" | "tool_result" | "system"
    content: list of content blocks, always a list (never a bare string)

Content block types:
    {"type": "text", "text": str}
    {"type": "tool_use", "name": str, "input": dict}
    {"type": "tool_result", "content": str, "is_error": bool}
"""

from __future__ import annotations

from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Canonical types
# ---------------------------------------------------------------------------


class ContentBlock(TypedDict, total=False):
    """A single block within a normalized message's content list."""

    type: str  # "text" | "tool_use" | "tool_result"
    # text blocks
    text: str
    # tool_use blocks
    name: str
    input: dict[str, Any]
    # tool_result blocks
    content: str
    is_error: bool


class NormalizedMessage(TypedDict):
    """Canonical representation of a single JSONL session event."""

    role: str  # "user" | "assistant" | "tool_use" | "tool_result" | "system"
    content: list[ContentBlock]
    # Passthrough metadata (optional, present when available in the source event)
    raw: dict[str, Any]


# ---------------------------------------------------------------------------
# Normalization helpers
# ---------------------------------------------------------------------------


def _normalize_tool_use_event(event: dict[str, Any]) -> NormalizedMessage:
    """Convert top-level tool_use event to canonical form.

    Input:  {"type": "tool_use", "toolUse": {"name": ..., "input": ...}}
    Output: role="tool_use", content=[{type: tool_use, name: ..., input: ...}]
    """
    tool_use = event.get("toolUse", {})
    block: ContentBlock = {
        "type": "tool_use",
        "name": tool_use.get("name", ""),
        "input": tool_use.get("input", {}),
    }
    return NormalizedMessage(role="tool_use", content=[block], raw=event)


def _normalize_assistant_event(event: dict[str, Any]) -> NormalizedMessage:
    """Convert assistant event to canonical form.

    Input:  {"type": "assistant", "message": {"content": [...]}}
    Output: role="assistant", content=[...normalized blocks...]
    """
    message = event.get("message", {})
    raw_content = message.get("content", [])
    blocks = _normalize_content(raw_content)
    return NormalizedMessage(role="assistant", content=blocks, raw=event)


def _normalize_user_event(event: dict[str, Any]) -> NormalizedMessage:
    """Convert user event to canonical form.

    Input:  {"type": "user", "message": {"content": "string" or [...]}}
    Output: role="user", content=[...normalized blocks...]
    """
    message = event.get("message", {})
    raw_content = message.get("content", [])
    blocks = _normalize_content(raw_content)
    return NormalizedMessage(role="user", content=blocks, raw=event)


def _normalize_tool_result_event(event: dict[str, Any]) -> NormalizedMessage:
    """Convert top-level tool_result event to canonical form.

    Input:  {"type": "tool_result", "content": "..."}
    Output: role="tool_result", content=[{type: tool_result, content: ...}]
    """
    raw_content = event.get("content", "")
    content_str = raw_content if isinstance(raw_content, str) else str(raw_content)
    block: ContentBlock = {
        "type": "tool_result",
        "content": content_str,
        "is_error": bool(event.get("is_error", False)),
    }
    return NormalizedMessage(role="tool_result", content=[block], raw=event)


def _normalize_system_event(event: dict[str, Any]) -> NormalizedMessage:
    """Pass system events through with empty content list."""
    return NormalizedMessage(role="system", content=[], raw=event)


def _normalize_content(raw_content: Any) -> list[ContentBlock]:
    """Normalize a raw content value (string or list) to a list of content blocks."""
    if isinstance(raw_content, str):
        if raw_content:
            return [ContentBlock(type="text", text=raw_content)]
        return []

    if not isinstance(raw_content, list):
        return []

    blocks: list[ContentBlock] = []
    for item in raw_content:
        if not isinstance(item, dict):
            continue
        block = _normalize_content_block(item)
        if block is not None:
            blocks.append(block)
    return blocks


def _normalize_content_block(item: dict[str, Any]) -> ContentBlock | None:
    """Normalize a single raw content block dict."""
    item_type = item.get("type", "")

    if item_type == "text":
        return ContentBlock(type="text", text=item.get("text", ""))

    if item_type == "tool_use":
        return ContentBlock(
            type="tool_use",
            name=item.get("name", ""),
            input=item.get("input", {}),
        )

    if item_type == "tool_result":
        raw = item.get("content", "")
        content_str = raw if isinstance(raw, str) else str(raw)
        return ContentBlock(
            type="tool_result",
            content=content_str,
            is_error=bool(item.get("is_error", False)),
        )

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def normalize_messages(raw_events: list[dict[str, Any]]) -> list[NormalizedMessage]:
    """Convert a list of raw JSONL events to the canonical NormalizedMessage format.

    Unknown event types are passed through with role="system" and empty content.
    """
    result: list[NormalizedMessage] = []
    for event in raw_events:
        event_type = event.get("type", "")
        if event_type == "tool_use":
            result.append(_normalize_tool_use_event(event))
        elif event_type == "assistant":
            result.append(_normalize_assistant_event(event))
        elif event_type == "user":
            result.append(_normalize_user_event(event))
        elif event_type == "tool_result":
            result.append(_normalize_tool_result_event(event))
        elif event_type == "system":
            result.append(_normalize_system_event(event))
        else:
            # Unknown types: pass through as system with empty content
            result.append(NormalizedMessage(role="system", content=[], raw=event))
    return result
