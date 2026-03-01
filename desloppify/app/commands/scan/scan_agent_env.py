"""Agent-environment detection helpers for scan reporting."""

from __future__ import annotations

import os


def is_agent_environment() -> bool:
    """Return True when scan is running inside a supported AI agent runtime."""
    return bool(
        os.environ.get("CLAUDE_CODE")
        or os.environ.get("DESLOPPIFY_AGENT")
        or os.environ.get("GEMINI_CLI")
        or os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED")
        or os.environ.get("CODEX_SANDBOX")
        or os.environ.get("CURSOR_TRACE_ID")
    )


def detect_agent_interface() -> str | None:
    """Resolve current interface key used by `update-skill`."""
    if os.environ.get("CLAUDE_CODE"):
        return "claude"
    if os.environ.get("GEMINI_CLI"):
        return "gemini"
    if os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED") or os.environ.get("CODEX_SANDBOX"):
        return "codex"
    if os.environ.get("CURSOR_TRACE_ID"):
        return "cursor"
    return None


__all__ = ["detect_agent_interface", "is_agent_environment"]
