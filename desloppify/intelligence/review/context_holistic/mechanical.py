"""Aggregate mechanical detector findings into structured evidence clusters.

Reads ALL state findings and produces signal clusters organized for holistic
review context enrichment.  The LLM reviewer gets hotspots and patterns —
not raw finding dumps — so it can investigate root causes.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


def _normalize_allowed_files(
    allowed_files: set[str] | list[str] | tuple[str, ...] | None,
) -> set[str] | None:
    """Normalize optional allowed-file scope to slash-normalized relative paths."""
    if allowed_files is None:
        return None
    out: set[str] = set()
    for raw in allowed_files:
        if not isinstance(raw, str):
            continue
        file_path = raw.strip().replace("\\", "/")
        if file_path:
            out.add(file_path)
    return out


def gather_mechanical_evidence(
    state: dict[str, Any],
    *,
    allowed_files: set[str] | list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Aggregate open findings into evidence clusters for holistic review.

    Returns a dict of named clusters.  Empty dict when no findings exist.
    """
    findings = state.get("findings", {})
    if not findings:
        return {}
    allowed_scope = _normalize_allowed_files(allowed_files)

    # ── Single-pass bucketing ────────────────────────────────────────
    by_detector: dict[str, list[dict]] = defaultdict(list)
    by_file: dict[str, list[dict]] = defaultdict(list)
    smell_counter: Counter[str] = Counter()
    smell_files: dict[str, list[str]] = defaultdict(list)  # smell_id -> [files]

    for finding in findings.values():
        if not isinstance(finding, dict):
            continue
        if finding.get("status") != "open":
            continue
        filepath = finding.get("file", "")
        normalized_file = (
            filepath.strip().replace("\\", "/")
            if isinstance(filepath, str)
            else ""
        )
        if allowed_scope is not None and normalized_file not in allowed_scope:
            continue
        det = finding.get("detector", "")
        if det:
            by_detector[det].append(finding)
        if normalized_file and normalized_file != ".":
            by_file[normalized_file].append(finding)
        # Track smell subtypes for systemic pattern detection
        if det == "smells":
            detail = finding.get("detail", {})
            smell_id = detail.get("smell_id", "") if isinstance(detail, dict) else ""
            if smell_id:
                smell_counter[smell_id] += 1
                smell_files[smell_id].append(normalized_file)

    if not by_detector:
        return {}

    evidence: dict[str, Any] = {}

    # ── Cluster A: Structural Complexity ─────────────────────────────
    complexity_hotspots = _build_complexity_hotspots(by_detector, by_file)
    if complexity_hotspots:
        evidence["complexity_hotspots"] = complexity_hotspots

    # ── Cluster B: Error & State Hygiene ─────────────────────────────
    error_hotspots = _build_error_hotspots(by_detector)
    if error_hotspots:
        evidence["error_hotspots"] = error_hotspots

    mutable_globals = _build_mutable_globals(by_detector)
    if mutable_globals:
        evidence["mutable_globals"] = mutable_globals

    # ── Cluster C: Dependency Architecture ───────────────────────────
    boundary_violations = _build_boundary_violations(by_detector)
    if boundary_violations:
        evidence["boundary_violations"] = boundary_violations

    dead_code = _build_dead_code(by_detector)
    if dead_code:
        evidence["dead_code"] = dead_code

    private_crossings = _build_private_crossings(by_detector)
    if private_crossings:
        evidence["private_crossings"] = private_crossings

    deferred = _build_deferred_import_density(by_file)
    if deferred:
        evidence["deferred_import_density"] = deferred

    # ── Cluster D: Consistency & Duplication ─────────────────────────
    duplicate_clusters = _build_duplicate_clusters(by_detector)
    if duplicate_clusters:
        evidence["duplicate_clusters"] = duplicate_clusters

    naming_drift = _build_naming_drift(by_detector)
    if naming_drift:
        evidence["naming_drift"] = naming_drift

    # ── Cluster E: Organization ──────────────────────────────────────
    flat_dir_findings = _build_flat_dir_findings(by_detector)
    if flat_dir_findings:
        evidence["flat_dir_findings"] = flat_dir_findings

    large_dist = _build_large_file_distribution(by_detector)
    if large_dist:
        evidence["large_file_distribution"] = large_dist

    # ── Cluster F: Security Density ──────────────────────────────────
    security_hotspots = _build_security_hotspots(by_detector)
    if security_hotspots:
        evidence["security_hotspots"] = security_hotspots

    # ── Cross-cutting: Signal density ────────────────────────────────
    signal_density = _build_signal_density(by_file)
    if signal_density:
        evidence["signal_density"] = signal_density

    # ── Systemic patterns ────────────────────────────────────────────
    systemic = _build_systemic_patterns(smell_counter, smell_files)
    if systemic:
        evidence["systemic_patterns"] = systemic

    return evidence


# ── Cluster builders ─────────────────────────────────────────────────


def _get_detail(finding: dict, key: str, default: Any = None) -> Any:
    detail = finding.get("detail", {})
    if not isinstance(detail, dict):
        return default
    return detail.get(key, default)


def _get_signals(finding: dict) -> dict:
    detail = finding.get("detail", {})
    if not isinstance(detail, dict):
        return {}
    signals = detail.get("signals", {})
    return signals if isinstance(signals, dict) else {}


def _safe_num(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        return default
    if isinstance(value, int | float):
        return float(value)
    return default


def _build_complexity_hotspots(
    by_detector: dict[str, list[dict]],
    by_file: dict[str, list[dict]],
) -> list[dict]:
    """Top 20 files by composite complexity score."""
    # Gather per-file structural signals
    file_data: dict[str, dict[str, Any]] = {}

    for finding in by_detector.get("structural", []):
        filepath = finding.get("file", "")
        if not filepath:
            continue
        signals = _get_signals(finding)
        entry = file_data.setdefault(filepath, {
            "file": filepath, "loc": 0, "complexity_score": 0,
            "signals": [], "component_count": 0, "function_count": 0,
            "monster_functions": 0, "cyclomatic_hotspots": 0,
        })
        entry["loc"] = max(entry["loc"], _safe_num(signals.get("loc")))
        entry["function_count"] = max(
            entry["function_count"], _safe_num(signals.get("function_count"))
        )
        entry["component_count"] = max(
            entry["component_count"], _safe_num(signals.get("component_count"))
        )

        # Collect notable signals
        max_params = _safe_num(signals.get("max_params"))
        if max_params >= 5:
            entry["signals"].append(f"{int(max_params)} params")
        max_nesting = _safe_num(signals.get("max_nesting"))
        if max_nesting >= 4:
            entry["signals"].append(f"nesting depth {int(max_nesting)}")
        complexity = _safe_num(signals.get("complexity_score"))
        entry["complexity_score"] = max(entry["complexity_score"], complexity)

    # Enrich with smell findings for the same files
    for finding in by_detector.get("smells", []):
        filepath = finding.get("file", "")
        smell_id = _get_detail(finding, "smell_id", "")
        if filepath in file_data:
            if smell_id == "monster_function":
                file_data[filepath]["monster_functions"] += 1
            elif smell_id in ("cyclomatic_complexity", "high_cyclomatic"):
                file_data[filepath]["cyclomatic_hotspots"] += 1

    # Also count responsibility_cohesion findings
    for finding in by_detector.get("responsibility_cohesion", []):
        filepath = finding.get("file", "")
        if filepath in file_data:
            clusters = _safe_num(_get_detail(finding, "cluster_count"))
            file_data[filepath]["component_count"] = max(
                file_data[filepath]["component_count"], clusters
            )

    # Composite score: loc/100 + complexity_score + component_count*3 + monster*10
    for entry in file_data.values():
        entry["_score"] = (
            entry["loc"] / 100
            + entry["complexity_score"]
            + entry["component_count"] * 3
            + entry["monster_functions"] * 10
        )
        # Deduplicate signals
        entry["signals"] = list(dict.fromkeys(entry["signals"]))

    ranked = sorted(file_data.values(), key=lambda e: -e["_score"])[:20]
    for entry in ranked:
        del entry["_score"]
    return ranked


def _build_error_hotspots(by_detector: dict[str, list[dict]]) -> list[dict]:
    """Files with 3+ exception handling findings from smells detector."""
    error_smell_ids = frozenset({
        "broad_except", "silent_except", "empty_except",
        "swallowed_error", "bare_except",
    })
    file_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for finding in by_detector.get("smells", []):
        smell_id = _get_detail(finding, "smell_id", "")
        if smell_id not in error_smell_ids:
            continue
        filepath = finding.get("file", "")
        if filepath:
            file_counts[filepath][smell_id] += 1

    results = []
    for filepath, counts in file_counts.items():
        total = sum(counts.values())
        if total < 3:
            continue
        entry = {"file": filepath, "total": total}
        for sid in sorted(error_smell_ids):
            entry[sid] = counts.get(sid, 0)
        results.append(entry)
    results.sort(key=lambda e: -e["total"])
    return results[:20]


def _build_mutable_globals(by_detector: dict[str, list[dict]]) -> list[dict]:
    """All global_mutable_config findings."""
    results: list[dict] = []
    file_data: dict[str, dict] = {}

    for finding in by_detector.get("global_mutable_config", []):
        filepath = finding.get("file", "")
        if not filepath:
            continue
        entry = file_data.setdefault(filepath, {
            "file": filepath, "names": [], "total_mutations": 0,
        })
        name = _get_detail(finding, "name", "")
        if name and name not in entry["names"]:
            entry["names"].append(name)
        mutations = _safe_num(_get_detail(finding, "mutations"))
        entry["total_mutations"] += int(mutations) if mutations else 1

    results = sorted(file_data.values(), key=lambda e: -e["total_mutations"])
    return results[:20]


def _build_boundary_violations(by_detector: dict[str, list[dict]]) -> list[dict]:
    """From coupling and layer_violation detectors."""
    results: list[dict] = []
    for det_name in ("coupling", "layer_violation"):
        for finding in by_detector.get(det_name, []):
            filepath = finding.get("file", "")
            detail = finding.get("detail", {})
            if not isinstance(detail, dict):
                detail = {}
            results.append({
                "file": filepath,
                "target": detail.get("target", detail.get("imported_from", "")),
                "direction": detail.get("direction", detail.get("violation", "")),
            })
    return results[:30]


def _build_dead_code(by_detector: dict[str, list[dict]]) -> list[dict]:
    """Orphaned files + uncalled functions."""
    results: list[dict] = []
    for finding in by_detector.get("orphaned", []):
        filepath = finding.get("file", "")
        signals = _get_signals(finding)
        loc = _safe_num(signals.get("loc", _get_detail(finding, "loc")))
        results.append({"file": filepath, "kind": "orphaned", "loc": int(loc)})
    for finding in by_detector.get("uncalled_functions", []):
        filepath = finding.get("file", "")
        detail = finding.get("detail", {})
        loc = _safe_num(detail.get("loc", 0)) if isinstance(detail, dict) else 0
        results.append({"file": filepath, "kind": "uncalled", "loc": int(loc)})
    return results[:30]


def _build_private_crossings(by_detector: dict[str, list[dict]]) -> list[dict]:
    """From private_imports detector."""
    results: list[dict] = []
    for finding in by_detector.get("private_imports", []):
        filepath = finding.get("file", "")
        detail = finding.get("detail", {})
        if not isinstance(detail, dict):
            detail = {}
        results.append({
            "file": filepath,
            "symbol": detail.get("symbol", detail.get("name", "")),
            "source": detail.get("source", detail.get("imported_from", "")),
            "target": detail.get("target", filepath),
        })
    return results[:30]


def _build_deferred_import_density(by_file: dict[str, list[dict]]) -> list[dict]:
    """Files with 2+ deferred_import smells (proxy for cycle pressure)."""
    file_counts: dict[str, int] = defaultdict(int)
    for filepath, file_findings in by_file.items():
        for finding in file_findings:
            if finding.get("detector") != "smells":
                continue
            if _get_detail(finding, "smell_id") == "deferred_import":
                file_counts[filepath] += 1

    results = [
        {"file": filepath, "count": count}
        for filepath, count in file_counts.items()
        if count >= 2
    ]
    results.sort(key=lambda e: -e["count"])
    return results[:20]


def _build_duplicate_clusters(by_detector: dict[str, list[dict]]) -> list[dict]:
    """From dupes and boilerplate_duplication detectors."""
    results: list[dict] = []
    for det_name in ("dupes", "boilerplate_duplication"):
        for finding in by_detector.get(det_name, []):
            detail = finding.get("detail", {})
            if not isinstance(detail, dict):
                detail = {}
            kind = detail.get("kind", det_name)
            name = detail.get("name", detail.get("function", finding.get("summary", "")[:60]))
            files = detail.get("files", [])
            if not isinstance(files, list):
                files = [finding.get("file", "")]
            results.append({
                "kind": kind,
                "cluster_size": len(files) if files else 1,
                "name": name,
                "files": files[:10],
            })
    return results[:20]


def _build_naming_drift(by_detector: dict[str, list[dict]]) -> list[dict]:
    """From naming detector."""
    dir_data: dict[str, dict] = {}
    for finding in by_detector.get("naming", []):
        filepath = finding.get("file", "")
        detail = finding.get("detail", {})
        if not isinstance(detail, dict):
            detail = {}
        # Group by directory
        parts = filepath.rsplit("/", 1)
        directory = parts[0] + "/" if len(parts) > 1 else "./"
        entry = dir_data.setdefault(directory, {
            "directory": directory,
            "majority": detail.get("expected_convention", ""),
            "minority_count": 0,
            "outliers": [],
        })
        entry["minority_count"] += 1
        if filepath not in entry["outliers"]:
            entry["outliers"].append(filepath)
        if not entry["majority"] and detail.get("expected_convention"):
            entry["majority"] = detail["expected_convention"]

    results = sorted(dir_data.values(), key=lambda e: -e["minority_count"])
    return results[:20]


def _build_flat_dir_findings(by_detector: dict[str, list[dict]]) -> list[dict]:
    """From flat_dirs detector."""
    results: list[dict] = []
    for finding in by_detector.get("flat_dirs", []):
        filepath = finding.get("file", "")
        detail = finding.get("detail", {})
        if not isinstance(detail, dict):
            detail = {}
        results.append({
            "directory": filepath,
            "kind": detail.get("kind", detail.get("reason", "")),
            "file_count": int(_safe_num(detail.get("file_count"))),
            "combined_score": int(_safe_num(detail.get("score", detail.get("combined_score")))),
        })
    results.sort(key=lambda e: -e["combined_score"])
    return results[:20]


def _build_large_file_distribution(by_detector: dict[str, list[dict]]) -> dict | None:
    """Distribution stats from structural findings."""
    locs: list[float] = []
    for finding in by_detector.get("structural", []):
        signals = _get_signals(finding)
        loc = _safe_num(signals.get("loc"))
        if loc > 0:
            locs.append(loc)
    if not locs:
        return None
    locs.sort()
    n = len(locs)
    return {
        "count": n,
        "median_loc": int(locs[n // 2]),
        "p90_loc": int(locs[int(n * 0.9)]) if n >= 10 else int(locs[-1]),
        "p99_loc": int(locs[int(n * 0.99)]) if n >= 100 else int(locs[-1]),
    }


def _build_security_hotspots(by_detector: dict[str, list[dict]]) -> list[dict]:
    """Files with 3+ security findings grouped by severity."""
    file_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for finding in by_detector.get("security", []):
        filepath = finding.get("file", "")
        if not filepath:
            continue
        detail = finding.get("detail", {})
        severity = (
            detail.get("severity", "medium")
            if isinstance(detail, dict) else "medium"
        )
        file_counts[filepath][severity] += 1

    results = []
    for filepath, counts in file_counts.items():
        total = sum(counts.values())
        if total < 3:
            continue
        results.append({
            "file": filepath,
            "high_severity": counts.get("high", 0),
            "medium_severity": counts.get("medium", 0),
            "total": total,
        })
    results.sort(key=lambda e: (-e["high_severity"], -e["total"]))
    return results[:20]


def _build_signal_density(by_file: dict[str, list[dict]]) -> list[dict]:
    """Top 20 files by number of distinct detectors firing."""
    results: list[dict] = []
    for filepath, file_findings in by_file.items():
        detectors = set()
        for finding in file_findings:
            det = finding.get("detector", "")
            if det:
                detectors.add(det)
        if len(detectors) >= 2:
            results.append({
                "file": filepath,
                "detector_count": len(detectors),
                "finding_count": len(file_findings),
                "detectors": sorted(detectors),
            })
    results.sort(key=lambda e: (-e["detector_count"], -e["finding_count"]))
    return results[:20]


def _build_systemic_patterns(
    smell_counter: Counter[str],
    smell_files: dict[str, list[str]],
) -> list[dict]:
    """Smell subtypes appearing in 5+ files."""
    results: list[dict] = []
    for smell_id, count in smell_counter.most_common():
        unique_files = sorted(set(smell_files.get(smell_id, [])))
        if len(unique_files) < 5:
            continue
        # Find top hotspot files (most occurrences)
        file_counts = Counter(smell_files[smell_id])
        hotspots = [
            f"{f} ({c})" for f, c in file_counts.most_common(5)
        ]
        results.append({
            "pattern": smell_id,
            "file_count": len(unique_files),
            "hotspots": hotspots,
        })
    return results[:20]


__all__ = ["gather_mechanical_evidence"]
