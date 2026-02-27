"""State filtering, ignore rules, and finding pattern matching."""

from __future__ import annotations

import fnmatch

__all__ = [
    "finding_in_scan_scope",
    "open_scope_breakdown",
    "path_scoped_findings",
    "is_ignored",
    "matched_ignore_pattern",
    "remove_ignored_findings",
    "add_ignore",
    "make_finding",
]

from desloppify.engine._state.schema import (
    Finding,
    StateModel,
    ensure_state_defaults,
    utc_now,
    validate_state_invariants,
)
from desloppify.core.discovery_api import rel


def path_scoped_findings(
    findings: dict[str, Finding],
    scan_path: str | None,
) -> dict[str, Finding]:
    """Filter findings to those within the given scan path."""
    return {
        finding_id: finding
        for finding_id, finding in findings.items()
        if finding_in_scan_scope(str(finding.get("file", "")), scan_path)
    }


def finding_in_scan_scope(file_path: str, scan_path: str | None) -> bool:
    """Return True when a file path belongs to the active scan scope."""
    if not scan_path or scan_path == ".":
        return True
    prefix = scan_path.rstrip("/") + "/"
    return (
        file_path.startswith(prefix)
        or file_path == scan_path
        or file_path == "."
    )


def open_scope_breakdown(
    findings: dict[str, Finding],
    scan_path: str | None,
    *,
    detector: str | None = None,
) -> dict[str, int]:
    """Return open-finding counts split by in-scope vs out-of-scope carryover."""
    in_scope = 0
    out_of_scope = 0

    for finding in findings.values():
        if finding.get("suppressed"):
            continue
        if finding.get("status") != "open":
            continue
        if detector is not None and finding.get("detector") != detector:
            continue
        file_path = str(finding.get("file", ""))
        if finding_in_scan_scope(file_path, scan_path):
            in_scope += 1
        else:
            out_of_scope += 1

    return {
        "in_scope": in_scope,
        "out_of_scope": out_of_scope,
        "global": in_scope + out_of_scope,
    }


def is_ignored(finding_id: str, file: str, ignore_patterns: list[str]) -> bool:
    """Check if a finding matches any ignore pattern (glob, ID prefix, or file path)."""
    return matched_ignore_pattern(finding_id, file, ignore_patterns) is not None


def matched_ignore_pattern(
    finding_id: str, file: str, ignore_patterns: list[str]
) -> str | None:
    """Return the ignore pattern that matched, if any."""
    for pattern in ignore_patterns:
        if "*" in pattern:
            target = finding_id if "::" in pattern else file
            if fnmatch.fnmatch(target, pattern):
                return pattern
            continue

        if "::" in pattern:
            if finding_id.startswith(pattern):
                return pattern
            continue

        if file == pattern or file == rel(pattern):
            return pattern

    return None


def remove_ignored_findings(state: StateModel, pattern: str) -> int:
    """Suppress findings matching an ignore pattern. Returns count affected."""
    ensure_state_defaults(state)
    matched_ids = [
        finding_id
        for finding_id, finding in state["findings"].items()
        if is_ignored(finding_id, finding["file"], [pattern])
    ]
    now = utc_now()
    for finding_id in matched_ids:
        finding = state["findings"][finding_id]
        finding["suppressed"] = True
        finding["suppressed_at"] = now
        finding["suppression_pattern"] = pattern
    # Deferred import to avoid circular dependency with engine._state.scoring
    from desloppify.engine._state.scoring import _recompute_stats

    _recompute_stats(state, scan_path=state.get("scan_path"))
    validate_state_invariants(state)
    return len(matched_ids)


def add_ignore(state: StateModel, pattern: str) -> int:
    """Add an ignore pattern and remove existing matching findings."""
    ensure_state_defaults(state)
    config = state.setdefault("config", {})
    ignores = config.setdefault("ignore", [])
    if pattern not in ignores:
        ignores.append(pattern)
    return remove_ignored_findings(state, pattern)


def make_finding(
    detector: str,
    file: str,
    name: str,
    *,
    tier: int,
    confidence: str,
    summary: str,
    detail: dict | None = None,
) -> Finding:
    """Create a normalized finding dict with a stable ID."""
    rfile = rel(file)
    finding_id = f"{detector}::{rfile}::{name}" if name else f"{detector}::{rfile}"
    now = utc_now()
    return {
        "id": finding_id,
        "detector": detector,
        "file": rfile,
        "tier": tier,
        "confidence": confidence,
        "summary": summary,
        "detail": detail or {},
        "status": "open",
        "note": None,
        "first_seen": now,
        "last_seen": now,
        "resolved_at": None,
        "reopen_count": 0,
    }


def _matches_pattern(finding_id: str, finding: dict[str, str], pattern: str) -> bool:
    """Check if a finding matches by ID, glob, prefix, detector, or path."""
    return (
        finding_id == pattern
        or ("*" in pattern and fnmatch.fnmatch(finding_id, pattern))
        or ("::" in pattern and finding_id.startswith(pattern))
        or (
            finding.get("detector") == pattern
            or finding["file"] == pattern
            or finding["file"].startswith(pattern.rstrip("/") + "/")
        )
    )
