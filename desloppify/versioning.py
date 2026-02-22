"""Tool versioning: content hashing and scan staleness detection."""

from __future__ import annotations

import hashlib
from pathlib import Path

TOOL_DIR = Path(__file__).resolve().parent


def compute_tool_hash() -> str:
    """Compute a content hash of all .py files in the desloppify package.

    Changes to any tool source file produce a different hash, enabling
    staleness detection for scan results.
    """
    h = hashlib.sha256()
    for py_file in sorted(TOOL_DIR.rglob("*.py")):
        rel_parts = py_file.relative_to(TOOL_DIR).parts
        if "tests" in rel_parts:
            continue
        try:
            h.update(str(py_file.relative_to(TOOL_DIR)).encode())
            h.update(py_file.read_bytes())
        except OSError:
            h.update(f"[unreadable:{py_file.name}]".encode())
            continue
    return h.hexdigest()[:12]


def check_tool_staleness(state: dict) -> str | None:
    """Return a warning string if tool code has changed since last scan, else None."""
    stored = state.get("tool_hash")
    if not stored:
        return None
    current = compute_tool_hash()
    if current != stored:
        return (
            f"Tool code changed since last scan (was {stored}, now {current}). "
            f"Consider re-running: desloppify scan"
        )
    return None
