"""Tool metadata helpers (hashing, staleness checks)."""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from desloppify.core.fallbacks import log_best_effort_failure

TOOL_DIR = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)


def _compute_tool_hash_with_diagnostics(
    *,
    tool_dir: Path | None = None,
) -> tuple[str, int]:
    """Compute tool hash and unreadable-file count."""
    active_tool_dir = tool_dir or TOOL_DIR
    digest = hashlib.sha256()
    unreadable_files = 0
    for py_file in sorted(active_tool_dir.rglob("*.py")):
        rel_parts = py_file.relative_to(active_tool_dir).parts
        if "tests" in rel_parts:
            continue
        try:
            digest.update(str(py_file.relative_to(active_tool_dir)).encode())
            digest.update(py_file.read_bytes())
        except OSError as exc:
            unreadable_files += 1
            log_best_effort_failure(
                logger,
                f"read tool-hash source file {py_file}",
                exc,
            )
            digest.update(f"[unreadable:{py_file.name}]".encode())
            continue
    return digest.hexdigest()[:12], unreadable_files


def compute_tool_hash(*, tool_dir: Path | None = None) -> str:
    """Compute a content hash of all .py files in the desloppify package."""
    digest, _ = _compute_tool_hash_with_diagnostics(tool_dir=tool_dir)
    return digest


def check_tool_staleness(state: dict, *, tool_dir: Path | None = None) -> str | None:
    """Return warning if tool code has changed since last scan."""
    stored = state.get("tool_hash")
    if not stored:
        return None
    current, unreadable_files = _compute_tool_hash_with_diagnostics(tool_dir=tool_dir)
    if current != stored:
        suffix = (
            f" ({unreadable_files} unreadable file(s) encountered while hashing)"
            if unreadable_files > 0
            else ""
        )
        return (
            f"Tool code changed since last scan (was {stored}, now {current}){suffix}. "
            "Consider re-running: desloppify scan"
        )
    if unreadable_files > 0:
        return (
            f"Tool hash check completed with {unreadable_files} unreadable file(s); "
            "staleness verification may be incomplete."
        )
    return None


_NEEDS_RESCAN_WARNING = (
    "Config changed — scores may be stale. Run: desloppify scan"
)


def check_config_staleness(config: dict) -> str | None:
    """Return warning if config changes have invalidated cached scores."""
    if config.get("needs_rescan"):
        return _NEEDS_RESCAN_WARNING
    return None


__all__ = [
    "TOOL_DIR",
    "check_config_staleness",
    "check_tool_staleness",
    "compute_tool_hash",
]
