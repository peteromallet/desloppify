"""Persistent state management for desloppify findings (.desloppify/state.json)."""

from __future__ import annotations

import fnmatch
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import NotRequired, TypedDict

from .utils import PROJECT_ROOT, rel, matches_exclusion, safe_write_text


class Finding(TypedDict):
    """The central data structure — a normalized finding from any detector."""
    id: str
    detector: str
    file: str
    tier: int              # 1-4
    confidence: str        # "high" | "medium" | "low"
    summary: str
    detail: dict
    status: str            # "open" | "resolved" | "wontfix" | "false_positive"
    note: str | None
    first_seen: str
    last_seen: str
    resolved_at: str | None
    reopen_count: int
    # Stamped post-creation in plan.py:
    lang: NotRequired[str]
    zone: NotRequired[str]

STATE_DIR = PROJECT_ROOT / ".desloppify"
STATE_FILE = STATE_DIR / "state.json"

CURRENT_VERSION = 1


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _empty_state() -> dict:
    return {
        "version": CURRENT_VERSION,
        "created": utc_now(),
        "last_scan": None,
        "scan_count": 0,
        "overall_score": 0,
        "objective_score": 0,
        "strict_score": 0,
        "stats": {},
        "findings": {},
        "subjective_assessments": {},
    }


def load_state(path: Path | None = None) -> dict:
    """Load state from disk, or return empty state.

    Handles corruption gracefully: tries backup, then starts fresh.
    """
    p = path or STATE_FILE
    if not p.exists():
        return _empty_state()

    try:
        data = json.loads(p.read_text())
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as e:
        # Try backup
        backup = p.with_suffix(".json.bak")
        if backup.exists():
            try:
                data = json.loads(backup.read_text())
                print(f"  \u26a0 State file corrupted ({e}), loaded from backup.", file=sys.stderr)
                return data
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass
        print(f"  \u26a0 State file corrupted ({e}). Starting fresh.", file=sys.stderr)
        try:
            p.rename(p.with_suffix(".json.corrupted"))
        except OSError:
            pass
        return _empty_state()

    # Version check
    version = data.get("version", 1)
    if version > CURRENT_VERSION:
        print(f"  \u26a0 State file version {version} is newer than supported ({CURRENT_VERSION}). "
              f"Some features may not work correctly.", file=sys.stderr)
    return data


def json_default(obj):
    """JSON serializer that handles known types and rejects unknowns."""
    if isinstance(obj, set):
        return sorted(obj)
    if isinstance(obj, Path):
        return str(obj)
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable: {obj!r}")


def save_state(state: dict, path: Path | None = None):
    """Recompute stats/score and save to disk atomically."""
    _recompute_stats(state, scan_path=state.get("scan_path"))
    p = path or STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(state, indent=2, default=json_default) + "\n"

    # Keep a backup of the previous state
    if p.exists():
        backup = p.with_suffix(".json.bak")
        try:
            shutil.copy2(str(p), str(backup))
        except OSError:
            pass

    try:
        safe_write_text(p, content)
    except OSError as e:
        print(f"  Warning: Could not save state: {e}", file=sys.stderr)



_EMPTY_COUNTERS = ("open", "fixed", "auto_resolved", "wontfix", "false_positive")


def _count_findings(findings: dict) -> tuple[dict[str, int], dict[int, dict[str, int]]]:
    """Tally per-status counters and per-tier breakdowns."""
    counters = dict.fromkeys(_EMPTY_COUNTERS, 0)
    tier_stats: dict[int, dict[str, int]] = {}
    for f in findings.values():
        s, tier = f["status"], f.get("tier", 3)
        counters[s] = counters.get(s, 0) + 1
        ts = tier_stats.setdefault(tier, dict.fromkeys(_EMPTY_COUNTERS, 0))
        ts[s] = ts.get(s, 0) + 1
    return counters, tier_stats


def _is_subjective_dimension(data: dict) -> bool:
    """Whether a dimension entry is subjective-review driven."""
    return "subjective_assessment" in data.get("detectors", {})


def _update_objective_health(state: dict, findings: dict):
    """Compute canonical score trio from dimension scoring."""
    pots = state.get("potentials", {})
    if not pots:
        return
    from .scoring import merge_potentials, compute_dimension_scores, compute_objective_score
    merged = merge_potentials(pots)
    if not merged:
        return
    subjective_assessments = (state.get("subjective_assessments")
                              or state.get("review_assessments") or None)
    # If nothing was checked for this scan scope (all detector potentials are zero)
    # and there are no subjective assessments, objective health is effectively
    # "no active checks" — treat as neutral instead of 0%.
    has_active_checks = any((count or 0) > 0 for count in merged.values())
    if not has_active_checks and not subjective_assessments:
        state["dimension_scores"] = {}
        state["overall_score"] = 100.0
        state["objective_score"] = 100.0
        state["strict_score"] = 100.0
        return

    lenient_scores = compute_dimension_scores(
        findings,
        merged,
        strict=False,
        subjective_assessments=subjective_assessments,
    )
    strict_scores = compute_dimension_scores(
        findings,
        merged,
        strict=True,
        subjective_assessments=subjective_assessments,
    )
    state["dimension_scores"] = {
        name: {
            "score": lenient_scores[name]["score"],
            "strict": strict_scores[name]["score"],
            "checks": lenient_scores[name]["checks"],
            "issues": lenient_scores[name]["issues"],
            "tier": lenient_scores[name]["tier"],
            "detectors": lenient_scores[name].get("detectors", {}),
        }
        for name in lenient_scores
    }
    mechanical_lenient_scores = {
        name: data for name, data in lenient_scores.items()
        if not _is_subjective_dimension(data)
    }
    state["overall_score"] = round(compute_objective_score(lenient_scores), 1)
    state["objective_score"] = round(compute_objective_score(mechanical_lenient_scores), 1)
    state["strict_score"] = round(compute_objective_score(strict_scores), 1)
    # Remove deprecated score keys when recomputing from canonical dimensions.
    state.pop("score", None)
    state.pop("objective_strict", None)


def path_scoped_findings(findings: dict, scan_path: str | None) -> dict:
    """Filter findings to those within the given scan path.

    Always includes holistic findings (file=".") regardless of scan_path.
    """
    if not scan_path or scan_path == ".":
        return findings
    prefix = scan_path.rstrip("/") + "/"
    return {k: v for k, v in findings.items()
            if v.get("file", "").startswith(prefix) or v.get("file") == scan_path
            or v.get("file") == "."}


def _recompute_stats(state: dict, scan_path: str | None = None):
    """Recompute stats and canonical health scores from findings."""
    findings = path_scoped_findings(state["findings"], scan_path)
    counters, tier_stats = _count_findings(findings)
    state["stats"] = {
        "total": sum(counters.values()),
        **counters,
        "by_tier": {str(t): ts for t, ts in sorted(tier_stats.items())},
    }
    _update_objective_health(state, findings)


def suppression_metrics(state: dict, *, window: int = 5) -> dict:
    """Summarize ignore suppression from recent scan history."""
    history = state.get("scan_history", [])
    if not history:
        return {
            "last_ignored": 0,
            "last_raw_findings": 0,
            "last_suppressed_pct": 0.0,
            "last_ignore_patterns": 0,
            "recent_scans": 0,
            "recent_ignored": 0,
            "recent_raw_findings": 0,
            "recent_suppressed_pct": 0.0,
        }

    scans_with_suppression = [
        h for h in history
        if isinstance(h, dict) and (
            "ignored" in h
            or "raw_findings" in h
            or "suppressed_pct" in h
            or "ignore_patterns" in h
        )
    ]
    if not scans_with_suppression:
        return {
            "last_ignored": 0,
            "last_raw_findings": 0,
            "last_suppressed_pct": 0.0,
            "last_ignore_patterns": 0,
            "recent_scans": 0,
            "recent_ignored": 0,
            "recent_raw_findings": 0,
            "recent_suppressed_pct": 0.0,
        }

    recent = scans_with_suppression[-max(1, window):]
    last = recent[-1]

    recent_ignored = sum(int(h.get("ignored", 0) or 0) for h in recent)
    recent_raw = sum(int(h.get("raw_findings", 0) or 0) for h in recent)
    recent_pct = round(recent_ignored / recent_raw * 100, 1) if recent_raw else 0.0

    last_ignored = int(last.get("ignored", 0) or 0)
    last_raw = int(last.get("raw_findings", 0) or 0)
    if "suppressed_pct" in last:
        last_pct = round(float(last.get("suppressed_pct") or 0.0), 1)
    else:
        last_pct = round(last_ignored / last_raw * 100, 1) if last_raw else 0.0

    return {
        "last_ignored": last_ignored,
        "last_raw_findings": last_raw,
        "last_suppressed_pct": last_pct,
        "last_ignore_patterns": int(last.get("ignore_patterns", 0) or 0),
        "recent_scans": len(recent),
        "recent_ignored": recent_ignored,
        "recent_raw_findings": recent_raw,
        "recent_suppressed_pct": recent_pct,
    }


def is_ignored(finding_id: str, file: str, ignore_patterns: list[str]) -> bool:
    """Check if a finding matches any ignore pattern (glob, ID prefix, or file path)."""
    for pat in ignore_patterns:
        if "*" in pat:
            target = finding_id if "::" in pat else file
            if fnmatch.fnmatch(target, pat):
                return True
        elif "::" in pat:
            if finding_id.startswith(pat):
                return True
        elif file == pat or file == rel(pat):
            return True
    return False


def remove_ignored_findings(state: dict, pattern: str) -> int:
    """Remove findings matching an ignore pattern. Returns count removed."""
    to_remove = [fid for fid, f in state["findings"].items()
                 if is_ignored(fid, f["file"], [pattern])]
    for fid in to_remove:
        del state["findings"][fid]
    return len(to_remove)


def add_ignore(state: dict, pattern: str) -> int:
    """Add an ignore pattern. Removes matching findings from state. Returns count removed.

    Deprecated: prefer config.add_ignore_pattern() + remove_ignored_findings().
    Kept for backward compatibility.
    """
    config = state.setdefault("config", {})
    ignores = config.setdefault("ignore", [])
    if pattern not in ignores:
        ignores.append(pattern)
    return remove_ignored_findings(state, pattern)


def make_finding(detector: str, file: str, name: str, *,
                 tier: int, confidence: str, summary: str,
                 detail: dict | None = None) -> Finding:
    """Create a normalized finding dict with a stable ID."""
    rfile = rel(file)
    fid = f"{detector}::{rfile}::{name}" if name else f"{detector}::{rfile}"
    now = utc_now()
    return {"id": fid, "detector": detector, "file": rfile, "tier": tier,
            "confidence": confidence, "summary": summary, "detail": detail or {},
            "status": "open", "note": None, "first_seen": now, "last_seen": now,
            "resolved_at": None, "reopen_count": 0}


def _find_suspect_detectors(
    existing: dict, current_by_detector: dict[str, int], force_resolve: bool,
    ran_detectors: set[str] | None = None,
) -> set[str]:
    """Detectors that had open findings but didn't actually run this scan.

    A detector is suspect only if:
    1. It had open findings before
    2. It returned 0 findings now
    3. It's NOT in ran_detectors (i.e., it didn't run — tool missing, skipped, errored)

    If ran_detectors is provided (from potentials), a 0-finding result from a
    detector that DID run is trusted — the user likely fixed everything.
    """
    if force_resolve:
        return set()
    prev: dict[str, int] = {}
    for f in existing.values():
        if f["status"] == "open":
            det = f.get("detector", "unknown")
            prev[det] = prev.get(det, 0) + 1

    # review is import-only (not a scan detector) — always protect from auto-resolve
    _IMPORT_ONLY_DETECTORS = {"review"}

    suspect = set()
    for det, n in prev.items():
        if det in _IMPORT_ONLY_DETECTORS:
            suspect.add(det)
        elif current_by_detector.get(det, 0) > 0:
            pass  # Detector produced findings — not suspect
        elif ran_detectors is not None:
            # We know what ran: trust detectors that ran, protect those that didn't
            if det not in ran_detectors:
                suspect.add(det)
        elif n >= 3:
            # ran_detectors unknown — heuristic: protect if meaningful count
            suspect.add(det)
    return suspect


def _auto_resolve_disappeared(
    existing: dict, current_ids: set[str], suspect_detectors: set[str],
    now: str, *, lang: str | None, scan_path: str | None,
    exclude: tuple[str, ...] = (),
) -> tuple[int, int, int]:
    """Auto-resolve open/wontfix findings absent from scan. Returns (resolved, skip_lang, skip_path)."""
    resolved = skip_lang = skip_path = 0
    for fid, old in existing.items():
        if fid in current_ids or old["status"] not in ("open", "wontfix"):
            continue
        if lang and old.get("lang") and old["lang"] != lang:
            skip_lang += 1
            continue
        # Skip findings outside the scanned path (when scanning a subdirectory)
        if scan_path and scan_path != ".":
            prefix = scan_path.rstrip("/") + "/"
            if not old["file"].startswith(prefix) and old["file"] != scan_path:
                skip_path += 1
                continue
        if exclude and any(matches_exclusion(old["file"], ex) for ex in exclude):
            continue
        if old.get("detector", "unknown") in suspect_detectors:
            continue
        prev = old["status"]
        old["status"] = "auto_resolved"
        old["resolved_at"] = now
        old["note"] = ("Fixed despite wontfix — disappeared from scan (was wontfix)"
                       if prev == "wontfix" else "Disappeared from scan — likely fixed")
        resolved += 1
    return resolved, skip_lang, skip_path


def _upsert_findings(
    existing: dict, current_findings: list[dict], ignore: list[str],
    now: str, *, lang: str | None,
) -> tuple[set[str], int, int, dict[str, int], int]:
    """Insert new findings and update existing ones. Returns (ids, new, reopened, by_detector, ignored)."""
    current_ids: set[str] = set()
    new_count = reopened = ignored_count = 0
    by_detector: dict[str, int] = {}
    for f in current_findings:
        fid = f["id"]
        if is_ignored(fid, f["file"], ignore):
            ignored_count += 1
            continue
        current_ids.add(fid)
        det = f.get("detector", "unknown")
        by_detector[det] = by_detector.get(det, 0) + 1
        if lang:
            f["lang"] = lang
        if fid in existing:
            old = existing[fid]
            old.update(last_seen=now, tier=f["tier"], confidence=f["confidence"],
                       summary=f["summary"], detail=f.get("detail", {}))
            if "zone" in f:
                old["zone"] = f["zone"]
            if lang and not old.get("lang"):
                old["lang"] = lang
            if old["status"] in ("fixed", "auto_resolved"):
                prev = old["status"]
                old["reopen_count"] = old.get("reopen_count", 0) + 1
                old.update(status="open", resolved_at=None,
                           note=f"Reopened (×{old['reopen_count']}) — reappeared in scan (was {prev})")
                reopened += 1
        else:
            existing[fid] = f
            new_count += 1
    return current_ids, new_count, reopened, by_detector, ignored_count


def merge_scan(state: dict, current_findings: list[dict], *,
               lang: str | None = None, scan_path: str | None = None,
               force_resolve: bool = False, exclude: tuple[str, ...] = (),
               potentials: dict[str, int] | None = None,
               merge_potentials: bool = False,
               codebase_metrics: dict | None = None,
               include_slow: bool = True,
               ignore: list[str] | None = None) -> dict:
    """Merge a fresh scan into existing state. Returns diff summary."""
    from .utils import compute_tool_hash
    now = utc_now()
    state["last_scan"] = now
    state["scan_count"] = state.get("scan_count", 0) + 1
    state["tool_hash"] = compute_tool_hash()
    if potentials is not None and lang:
        all_pots = state.setdefault("potentials", {})
        if merge_potentials and isinstance(all_pots.get(lang), dict):
            merged = dict(all_pots[lang])
            merged.update(potentials)
            all_pots[lang] = merged
        else:
            all_pots[lang] = potentials
    if codebase_metrics is not None and lang:
        state.setdefault("codebase_metrics", {})[lang] = codebase_metrics
    if lang:
        state.setdefault("scan_completeness", {})[lang] = "full" if include_slow else "fast"

    state["scan_path"] = scan_path
    existing = state["findings"]
    ignore = ignore if ignore is not None else state.get("config", {}).get("ignore", [])
    current_ids, new_count, reopened_count, current_by_detector, ignored_count = _upsert_findings(
        existing, current_findings, ignore, now, lang=lang)
    raw_findings = len(current_findings)
    suppressed_pct = round(ignored_count / raw_findings * 100, 1) if raw_findings else 0.0
    # Detectors that appear in potentials actually ran — trust their 0-finding results.
    # Use `is not None` (not truthiness) so an empty dict {} still means "potentials
    # were provided" — prevents marking all detectors as suspect on empty scans.
    ran_detectors = set(potentials.keys()) if potentials is not None else None
    suspect_detectors = _find_suspect_detectors(
        existing, current_by_detector, force_resolve, ran_detectors)
    auto_resolved, skipped_lang, skipped_path = _auto_resolve_disappeared(
        existing, current_ids, suspect_detectors, now,
        lang=lang, scan_path=scan_path, exclude=exclude)
    _recompute_stats(state, scan_path=scan_path)

    # Append scan history entry for trajectory tracking
    history = state.setdefault("scan_history", [])
    history.append({
        "timestamp": now,
        "lang": lang,
        "strict_score": state.get("strict_score"),
        "objective_score": state.get("objective_score"),
        "overall_score": state.get("overall_score"),
        "open": state["stats"]["open"],
        "diff_new": new_count,
        "diff_resolved": auto_resolved,
        "ignored": ignored_count,
        "raw_findings": raw_findings,
        "suppressed_pct": suppressed_pct,
        "ignore_patterns": len(ignore),
        "dimension_scores": {
            name: {"score": ds["score"], "strict": ds.get("strict", ds["score"])}
            for name, ds in state.get("dimension_scores", {}).items()
        } if state.get("dimension_scores") else None,
    })
    if len(history) > 20:
        state["scan_history"] = history[-20:]

    # Detect chronic reopeners (findings that keep bouncing between resolved and open)
    chronic = [f for f in existing.values()
               if f.get("reopen_count", 0) >= 2 and f["status"] == "open"]

    return {
        "new": new_count, "auto_resolved": auto_resolved,
        "reopened": reopened_count, "total_current": len(current_ids),
        "suspect_detectors": sorted(suspect_detectors) if suspect_detectors else [],
        "chronic_reopeners": chronic,
        "skipped_other_lang": skipped_lang, "skipped_out_of_scope": skipped_path,
        "ignored": ignored_count, "ignore_patterns": len(ignore),
        "raw_findings": raw_findings, "suppressed_pct": suppressed_pct,
    }


def get_overall_score(state: dict) -> float | None:
    """Canonical overall score (lenient, includes subjective dimensions)."""
    if state.get("overall_score") is not None:
        return state.get("overall_score")
    if state.get("objective_score") is not None and state.get("objective_strict") is not None:
        return state.get("objective_score")
    if state.get("score") is not None:
        return state.get("score")
    return None


def get_objective_score(state: dict) -> float | None:
    """Canonical objective score (lenient, mechanical dimensions only)."""
    if state.get("objective_score") is not None:
        return state.get("objective_score")
    if state.get("score") is not None:
        return state.get("score")
    return None


def get_strict_score(state: dict) -> float | None:
    """Canonical strict score (strict, includes subjective dimensions)."""
    if state.get("overall_score") is not None and state.get("strict_score") is not None:
        return state.get("strict_score")
    if state.get("objective_strict") is not None:
        return state.get("objective_strict")
    if state.get("strict_score") is not None:
        return state.get("strict_score")
    return None


def _matches_pattern(fid: str, f: dict, pattern: str) -> bool:
    """Check if a finding matches: exact ID, glob, ID prefix, detector name, or file path."""
    if fid == pattern:
        return True
    if "*" in pattern:
        return fnmatch.fnmatch(fid, pattern)
    if "::" in pattern:
        return fid.startswith(pattern)
    return f.get("detector") == pattern or f["file"] == pattern or f["file"].startswith(pattern.rstrip("/") + "/")


def match_findings(state: dict, pattern: str, status_filter: str = "open") -> list[dict]:
    """Return findings matching *pattern* with the given status."""
    return [f for fid, f in state["findings"].items()
            if (status_filter == "all" or f["status"] == status_filter)
            and _matches_pattern(fid, f, pattern)]


def resolve_findings(state: dict, pattern: str, status: str,
                     note: str | None = None) -> list[str]:
    """Resolve findings matching pattern. Returns list of resolved IDs."""
    now = utc_now()
    resolved = []
    for f in match_findings(state, pattern, status_filter="open"):
        f.update(status=status, note=note, resolved_at=now)
        resolved.append(f["id"])
    _recompute_stats(state, scan_path=state.get("scan_path"))
    return resolved
