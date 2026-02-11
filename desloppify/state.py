"""Persistent state management for desloppify findings.

State lives in .desloppify/state.json. Each finding has a stable ID,
a status (open/fixed/wontfix/false_positive/auto_resolved), and optional notes.
Re-scanning diffs current findings against state without losing manual edits.
"""

import fnmatch
import json
from datetime import datetime, timezone
from pathlib import Path

from .utils import PROJECT_ROOT, rel

STATE_DIR = PROJECT_ROOT / ".desloppify"
STATE_FILE = STATE_DIR / "state.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state(path: Path | None = None) -> dict:
    """Load state from disk, or return empty state."""
    p = path or STATE_FILE
    if p.exists():
        return json.loads(p.read_text())
    return {
        "version": 1,
        "created": _now(),
        "last_scan": None,
        "scan_count": 0,
        "config": {"ignore": []},
        "score": 0,
        "stats": {},
        "findings": {},
    }


def save_state(state: dict, path: Path | None = None):
    """Recompute stats/score and save to disk."""
    _recompute_stats(state)
    p = path or STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, default=str) + "\n")


# Inverted weighting: structural/architectural issues (T3/T4) matter more
# than mechanical single-line fixes (T1/T2). This prevents volume of
# auto-fixable items from drowning out real architectural debt.
TIER_WEIGHTS = {1: 1, 2: 2, 3: 3, 4: 4}


def _recompute_stats(state: dict):
    """Recompute stats and score from findings.

    Score uses tier weighting: T4 architectural fixes are weighted 4x a T1
    mechanical fix. This ensures structural debt matters more per-finding
    than volume of auto-fixable items.
    """
    findings = state["findings"]
    counters = {"open": 0, "fixed": 0, "auto_resolved": 0, "wontfix": 0, "false_positive": 0}
    tier_stats: dict[int, dict[str, int]] = {}

    for f in findings.values():
        s = f["status"]
        counters[s] = counters.get(s, 0) + 1
        tier = f.get("tier", 3)
        if tier not in tier_stats:
            tier_stats[tier] = {"open": 0, "fixed": 0, "auto_resolved": 0, "wontfix": 0, "false_positive": 0}
        tier_stats[tier][s] = tier_stats[tier].get(s, 0) + 1

    total = sum(counters.values())

    # Weighted score: structural/architectural issues (T3/T4) have more impact
    total_weight = 0
    addressed_weight = 0
    fixed_weight = 0  # strict: actual fixes + false positives (not real issues)
    for f in findings.values():
        w = TIER_WEIGHTS.get(f.get("tier", 3), 2)
        total_weight += w
        if f["status"] != "open":
            addressed_weight += w
        if f["status"] in ("fixed", "auto_resolved", "false_positive"):
            fixed_weight += w

    state["stats"] = {
        "total": total,
        **counters,
        "by_tier": {str(t): ts for t, ts in sorted(tier_stats.items())},
    }
    state["score"] = round((addressed_weight / total_weight) * 100, 1) if total_weight > 0 else 100
    state["strict_score"] = round((fixed_weight / total_weight) * 100, 1) if total_weight > 0 else 100


def is_ignored(finding_id: str, file: str, ignore_patterns: list[str]) -> bool:
    """Check if a finding should be ignored.

    Pattern types:
    - Contains '*'  → fnmatch against finding ID (if '::' present) or file path
    - Contains '::' → prefix match on finding ID
    - Otherwise     → exact file path match
    """
    for pattern in ignore_patterns:
        if "*" in pattern:
            # Glob: match against ID if it looks like an ID pattern, else file path
            if "::" in pattern:
                if fnmatch.fnmatch(finding_id, pattern):
                    return True
            else:
                if fnmatch.fnmatch(file, pattern):
                    return True
        elif "::" in pattern:
            if finding_id.startswith(pattern):
                return True
        else:
            if file == pattern or file == rel(pattern):
                return True
    return False


def add_ignore(state: dict, pattern: str) -> int:
    """Add an ignore pattern. Removes matching findings from state. Returns count removed."""
    config = state.setdefault("config", {})
    ignores = config.setdefault("ignore", [])
    if pattern not in ignores:
        ignores.append(pattern)

    to_remove = [fid for fid, f in state["findings"].items()
                 if is_ignored(fid, f["file"], [pattern])]
    for fid in to_remove:
        del state["findings"][fid]
    return len(to_remove)


def make_finding(detector: str, file: str, name: str, *,
                 tier: int, confidence: str, summary: str,
                 detail: dict | None = None) -> dict:
    """Create a normalized finding dict with a stable ID."""
    rfile = rel(file)
    fid = f"{detector}::{rfile}::{name}" if name else f"{detector}::{rfile}"
    return {
        "id": fid,
        "detector": detector,
        "file": rfile,
        "tier": tier,
        "confidence": confidence,
        "summary": summary,
        "detail": detail or {},
        "status": "open",
        "note": None,
        "first_seen": _now(),
        "last_seen": _now(),
        "resolved_at": None,
        "reopen_count": 0,
    }


def _find_suspect_detectors(
    existing: dict, current_by_detector: dict[str, int], force_resolve: bool,
) -> set[str]:
    """Identify detectors that previously had findings but now returned zero.

    These are likely transient failures — their findings should not be auto-resolved.
    """
    if force_resolve:
        return set()
    suspect = set()
    prev_by_detector: dict[str, int] = {}
    for f in existing.values():
        if f["status"] == "open":
            det = f.get("detector", "unknown")
            prev_by_detector[det] = prev_by_detector.get(det, 0) + 1
    for det, prev_count in prev_by_detector.items():
        if prev_count >= 5 and current_by_detector.get(det, 0) == 0:
            suspect.add(det)
    return suspect


def _auto_resolve_disappeared(
    existing: dict, current_ids: set[str], suspect_detectors: set[str],
    now: str, *, lang: str | None, scan_path: str | None,
    exclude: tuple[str, ...] = (),
) -> tuple[int, int, int]:
    """Auto-resolve findings that disappeared from the scan.

    Wontfix findings that disappear are upgraded to auto_resolved so the strict
    score reflects the actual fix. Findings from excluded directories are skipped
    (they disappeared because they were excluded, not fixed).
    Returns (auto_resolved, skipped_lang, skipped_path).
    """
    auto_resolved = 0
    skipped_lang = 0
    skipped_path = 0
    for fid, old in existing.items():
        if fid not in current_ids and old["status"] in ("open", "wontfix"):
            if lang and old.get("lang") and old["lang"] != lang:
                skipped_lang += 1
                continue
            if scan_path and not old["file"].startswith(scan_path.rstrip("/") + "/") and old["file"] != scan_path:
                skipped_path += 1
                continue
            # Don't auto-resolve findings from excluded directories —
            # they disappeared because they were excluded, not fixed
            if exclude and any(ex in old["file"] for ex in exclude):
                continue
            if old.get("detector", "unknown") in suspect_detectors:
                continue
            prev_status = old["status"]
            old["status"] = "auto_resolved"
            old["resolved_at"] = now
            if prev_status == "wontfix":
                old["note"] = "Fixed despite wontfix — disappeared from scan (was wontfix)"
            else:
                old["note"] = "Disappeared from scan — likely fixed"
            auto_resolved += 1
    return auto_resolved, skipped_lang, skipped_path


def merge_scan(state: dict, current_findings: list[dict], *,
               lang: str | None = None, scan_path: str | None = None,
               force_resolve: bool = False,
               exclude: tuple[str, ...] = ()) -> dict:
    """Merge a fresh scan into existing state. Returns diff summary.

    Args:
        lang: Language name — only auto-resolve findings matching this language.
        scan_path: Relative scan path — only auto-resolve findings under this path.
        force_resolve: Bypass suspect-detector protection (use when you know a
            detector legitimately went to 0).
        exclude: Directory exclusion patterns — findings from excluded dirs are
            not auto-resolved (they disappeared because of the filter, not a fix).

    Protections against detector instability:
    - If a detector previously had findings but now returns zero, its open
      findings are NOT auto-resolved (likely a transient detector failure).
    - The note for reopened findings correctly captures the previous status.
    """
    from .utils import compute_tool_hash
    now = _now()
    state["last_scan"] = now
    state["scan_count"] = state.get("scan_count", 0) + 1
    state["tool_hash"] = compute_tool_hash()
    ignore = state.get("config", {}).get("ignore", [])
    existing = state["findings"]

    current_ids = set()
    new_count = 0
    reopened_count = 0

    # Track current findings per detector to detect empty-detector anomalies
    current_by_detector: dict[str, int] = {}
    for f in current_findings:
        fid = f["id"]
        if is_ignored(fid, f["file"], ignore):
            continue
        current_ids.add(fid)
        det = f.get("detector", "unknown")
        current_by_detector[det] = current_by_detector.get(det, 0) + 1

        # Stamp language on findings so language-scoped auto-resolve works
        if lang:
            f["lang"] = lang

        if fid in existing:
            old = existing[fid]
            old["last_seen"] = now
            # Refresh metadata (tier/confidence/summary may update)
            old["tier"] = f["tier"]
            old["confidence"] = f["confidence"]
            old["summary"] = f["summary"]
            old["detail"] = f.get("detail", {})
            # Backfill lang on existing findings
            if lang and not old.get("lang"):
                old["lang"] = lang

            # Reopen if it was auto-resolved/fixed but reappeared
            if old["status"] in ("fixed", "auto_resolved"):
                prev_status = old["status"]
                old["status"] = "open"
                old["reopen_count"] = old.get("reopen_count", 0) + 1
                old["note"] = f"Reopened (×{old['reopen_count']}) — reappeared in scan (was {prev_status})"
                old["resolved_at"] = None
                reopened_count += 1
            # wontfix / false_positive stay as-is even if finding reappears
        else:
            existing[fid] = f
            new_count += 1

    suspect_detectors = _find_suspect_detectors(
        existing, current_by_detector, force_resolve)

    auto_resolved, skipped_lang, skipped_path = _auto_resolve_disappeared(
        existing, current_ids, suspect_detectors, now,
        lang=lang, scan_path=scan_path, exclude=exclude)

    _recompute_stats(state)

    # Detect chronic reopeners (findings that keep bouncing between resolved and open)
    chronic = [f for f in existing.values()
               if f.get("reopen_count", 0) >= 2 and f["status"] == "open"]

    return {
        "new": new_count,
        "auto_resolved": auto_resolved,
        "reopened": reopened_count,
        "total_current": len(current_ids),
        "suspect_detectors": sorted(suspect_detectors) if suspect_detectors else [],
        "chronic_reopeners": len(chronic),
        "skipped_other_lang": skipped_lang,
        "skipped_out_of_scope": skipped_path,
    }


def match_findings(state: dict, pattern: str, status_filter: str = "open") -> list[dict]:
    """Return findings matching *pattern* with the given status.

    Pattern matching (checked in order):
    - Exact finding ID
    - Glob (fnmatch) on finding ID when pattern contains ``*``
    - ID prefix when pattern contains ``::``
    - Detector name (no ``::`` in pattern)
    - Exact file path or directory prefix (``src/foo/`` matches children)
    """
    matches = []
    for fid, f in state["findings"].items():
        if status_filter != "all" and f["status"] != status_filter:
            continue

        matched = False
        if fid == pattern:
            matched = True
        elif "*" in pattern:
            matched = fnmatch.fnmatch(fid, pattern)
        elif "::" in pattern and fid.startswith(pattern):
            matched = True
        elif "::" not in pattern and f.get("detector") == pattern:
            matched = True
        elif "::" not in pattern and (f["file"] == pattern or f["file"].startswith(pattern.rstrip("/") + "/")):
            matched = True

        if matched:
            matches.append(f)
    return matches


def resolve_findings(state: dict, pattern: str, status: str,
                     note: str | None = None) -> list[str]:
    """Resolve findings matching pattern. Returns list of resolved IDs."""
    matches = match_findings(state, pattern, status_filter="open")
    now = _now()
    resolved = []
    for f in matches:
        f["status"] = status
        f["note"] = note
        f["resolved_at"] = now
        resolved.append(f["id"])
    _recompute_stats(state)
    return resolved
