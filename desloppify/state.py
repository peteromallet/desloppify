"""Persistent state management for desloppify findings (.desloppify/state.json)."""

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


# Structural issues (T3/T4) weigh more than mechanical fixes (T1/T2)
TIER_WEIGHTS = {1: 1, 2: 2, 3: 3, 4: 4}


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


def _weighted_progress(findings: dict) -> tuple[float, float]:
    """Compute weighted addressed% and strict-fixed%. Returns (score, strict_score)."""
    total_w = addressed_w = fixed_w = 0
    for f in findings.values():
        w = TIER_WEIGHTS.get(f.get("tier", 3), 2)
        total_w += w
        if f["status"] != "open":
            addressed_w += w
        if f["status"] in ("fixed", "auto_resolved", "false_positive"):
            fixed_w += w
    if total_w == 0:
        return 100.0, 100.0
    return round((addressed_w / total_w) * 100, 1), round((fixed_w / total_w) * 100, 1)


def _update_objective_health(state: dict, findings: dict):
    """Compute dimension-based objective health scores from potentials."""
    pots = state.get("potentials", {})
    if not pots:
        return
    from .scoring import merge_potentials, compute_dimension_scores, compute_objective_score
    merged = merge_potentials(pots)
    if not merged:
        return
    ds = compute_dimension_scores(findings, merged, strict=False)
    ss = compute_dimension_scores(findings, merged, strict=True)
    state["dimension_scores"] = {
        n: {"score": ds[n]["score"], "strict": ss[n]["score"], "checks": ds[n]["checks"],
            "issues": ds[n]["issues"], "tier": ds[n]["tier"], "detectors": ds[n].get("detectors", {})}
        for n in ds}
    state["objective_score"] = round(compute_objective_score(ds), 1)
    state["objective_strict"] = round(compute_objective_score(ss), 1)


def _recompute_stats(state: dict):
    """Recompute stats, progress scores, and objective health scores from findings."""
    findings = state["findings"]
    counters, tier_stats = _count_findings(findings)
    score, strict_score = _weighted_progress(findings)
    state["stats"] = {
        "total": sum(counters.values()),
        **counters,
        "by_tier": {str(t): ts for t, ts in sorted(tier_stats.items())},
    }
    state["score"] = score
    state["strict_score"] = strict_score
    _update_objective_health(state, findings)


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
    now = _now()
    return {"id": fid, "detector": detector, "file": rfile, "tier": tier,
            "confidence": confidence, "summary": summary, "detail": detail or {},
            "status": "open", "note": None, "first_seen": now, "last_seen": now,
            "resolved_at": None, "reopen_count": 0}


def _find_suspect_detectors(
    existing: dict, current_by_detector: dict[str, int], force_resolve: bool,
) -> set[str]:
    """Detectors that had >=5 open findings but now returned zero (likely transient failure)."""
    if force_resolve:
        return set()
    prev: dict[str, int] = {}
    for f in existing.values():
        if f["status"] == "open":
            det = f.get("detector", "unknown")
            prev[det] = prev.get(det, 0) + 1
    return {d for d, n in prev.items() if n >= 5 and current_by_detector.get(d, 0) == 0}


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
            skip_lang += 1; continue
        if scan_path and not old["file"].startswith(scan_path.rstrip("/") + "/") and old["file"] != scan_path:
            skip_path += 1; continue
        if exclude and any(ex in old["file"] for ex in exclude):
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
) -> tuple[set[str], int, int, dict[str, int]]:
    """Insert new findings and update existing ones. Returns (ids, new, reopened, by_detector)."""
    current_ids: set[str] = set()
    new_count = reopened = 0
    by_detector: dict[str, int] = {}
    for f in current_findings:
        fid = f["id"]
        if is_ignored(fid, f["file"], ignore):
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
    return current_ids, new_count, reopened, by_detector


def merge_scan(state: dict, current_findings: list[dict], *,
               lang: str | None = None, scan_path: str | None = None,
               force_resolve: bool = False, exclude: tuple[str, ...] = (),
               potentials: dict[str, int] | None = None,
               codebase_metrics: dict | None = None,
               include_slow: bool = True) -> dict:
    """Merge a fresh scan into existing state. Returns diff summary."""
    from .utils import compute_tool_hash
    now = _now()
    state["last_scan"] = now
    state["scan_count"] = state.get("scan_count", 0) + 1
    state["tool_hash"] = compute_tool_hash()
    if potentials is not None and lang:
        state.setdefault("potentials", {})[lang] = potentials
    if codebase_metrics is not None and lang:
        state.setdefault("codebase_metrics", {})[lang] = codebase_metrics
    if lang:
        state.setdefault("scan_completeness", {})[lang] = "full" if include_slow else "fast"

    existing = state["findings"]
    ignore = state.get("config", {}).get("ignore", [])
    current_ids, new_count, reopened_count, current_by_detector = _upsert_findings(
        existing, current_findings, ignore, now, lang=lang)
    suspect_detectors = _find_suspect_detectors(
        existing, current_by_detector, force_resolve)
    auto_resolved, skipped_lang, skipped_path = _auto_resolve_disappeared(
        existing, current_ids, suspect_detectors, now,
        lang=lang, scan_path=scan_path, exclude=exclude)
    _recompute_stats(state)

    chronic = sum(1 for f in existing.values()
                  if f.get("reopen_count", 0) >= 2 and f["status"] == "open")
    return {
        "new": new_count, "auto_resolved": auto_resolved,
        "reopened": reopened_count, "total_current": len(current_ids),
        "suspect_detectors": sorted(suspect_detectors) if suspect_detectors else [],
        "chronic_reopeners": chronic,
        "skipped_other_lang": skipped_lang, "skipped_out_of_scope": skipped_path,
    }


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
    now = _now()
    resolved = []
    for f in match_findings(state, pattern, status_filter="open"):
        f.update(status=status, note=note, resolved_at=now)
        resolved.append(f["id"])
    _recompute_stats(state)
    return resolved
