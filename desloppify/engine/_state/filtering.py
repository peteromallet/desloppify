"""State filtering, ignore rules, and finding pattern matching."""

from __future__ import annotations

import fnmatch
import importlib

from desloppify.engine._state.schema import (
    Finding,
    ensure_state_defaults,
    utc_now,
    validate_state_invariants,
)
from desloppify.file_discovery import rel


def path_scoped_findings(
    findings: dict[str, Finding],
    scan_path: str | None,
) -> dict[str, Finding]:
    """Filter findings to those within the given scan path."""
    if not scan_path or scan_path == ".":
        return findings

    prefix = scan_path.rstrip("/") + "/"
    return {
        finding_id: finding
        for finding_id, finding in findings.items()
        if finding.get("file", "").startswith(prefix)
        or finding.get("file") == scan_path
        or finding.get("file") == "."
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


def remove_ignored_findings(state: dict, pattern: str) -> int:
    """Suppress findings matching an ignore pattern. Returns count affected."""
    scoring_mod = importlib.import_module("desloppify.engine._state.scoring")
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
        if finding.get("status") in ("fixed", "auto_resolved", "false_positive"):
            finding["status"] = "open"
            finding["resolved_at"] = None
            finding["note"] = (
                "Suppressed by ignore pattern — remains unresolved for score integrity"
            )
    scoring_mod._recompute_stats(state, scan_path=state.get("scan_path"))
    validate_state_invariants(state)
    return len(matched_ids)


def add_ignore(state: dict, pattern: str) -> int:
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
