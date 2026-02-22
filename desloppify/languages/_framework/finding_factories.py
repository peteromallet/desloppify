"""Finding factory functions — normalize raw detector output into Finding dicts."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from desloppify.core.enums import Tier
from desloppify.state import Finding, make_finding
from desloppify.file_discovery import rel


def make_unused_findings(entries: list[dict], stderr_fn) -> list[Finding]:
    """Transform raw unused-detector entries into normalized findings.

    Shared by both Python and TypeScript unused phases.
    """
    results = []
    for e in entries:
        tier = 1 if e["category"] == "imports" else 2
        results.append(
            make_finding(
                "unused",
                e["file"],
                e["name"],
                tier=tier,
                confidence="high",
                summary=f"Unused {e['category']}: {e['name']}",
                detail={"line": e["line"], "category": e["category"]},
            )
        )
    stderr_fn(f"         {len(entries)} instances -> {len(results)} findings")
    return results


def make_dupe_findings(entries: list[dict], stderr_fn) -> list[Finding]:
    """Transform clustered duplicate entries into normalized findings.

    Each entry represents a cluster of similar functions. One finding per cluster.
    """
    results = []
    for e in entries:
        a, b = e["fn_a"], e["fn_b"]
        if a["loc"] < 10 and b["loc"] < 10:
            continue
        cluster_size = e.get("cluster_size", 2)
        pair = sorted([(a["file"], a["name"]), (b["file"], b["name"])])
        name = f"{pair[0][1]}::{rel(pair[1][0])}::{pair[1][1]}"
        tier = 2 if e["kind"] == "exact" else 3
        conf = "high" if e["kind"] == "exact" else "low"
        kind_label = "Exact" if e["kind"] == "exact" else "Near"
        if cluster_size > 2:
            summary = (
                f"{kind_label} dupe cluster ({cluster_size} functions, "
                f"{e['similarity']:.0%} similar): "
                f"{a['name']} ({rel(a['file'])}:{a['line']}), "
                f"{b['name']} ({rel(b['file'])}:{b['line']}), ..."
            )
        else:
            summary = (
                f"{kind_label} dupe: "
                f"{a['name']} ({rel(a['file'])}:{a['line']}) <-> "
                f"{b['name']} ({rel(b['file'])}:{b['line']}) [{e['similarity']:.0%}]"
            )
        results.append(
            make_finding(
                "dupes",
                pair[0][0],
                name,
                tier=tier,
                confidence=conf,
                summary=summary,
                detail={
                    "fn_a": a,
                    "fn_b": b,
                    "similarity": e["similarity"],
                    "kind": e["kind"],
                    "cluster_size": cluster_size,
                    "cluster": e.get("cluster", [a, b]),
                },
            )
        )
    suppressed = sum(
        1 for e in entries if e["fn_a"]["loc"] < 10 and e["fn_b"]["loc"] < 10
    )
    stderr_fn(f"         {len(entries)} clusters, {suppressed} suppressed (<10 LOC)")
    return results


def make_single_use_findings(
    entries: list[dict],
    get_area,
    *,
    loc_range: tuple[int, int] = (50, 200),
    suppress_colocated: bool = True,
    skip_dir_names: set[str] | None = None,
    stderr_fn,
) -> list[Finding]:
    """Filter and normalize single-use entries into findings.

    Suppresses entries within the LOC range (they're appropriately-sized abstractions),
    entries co-located with their sole importer, and entries in skip_dir_names
    directories (e.g., commands/ -- CLI modules are single-use by design).
    """
    results = []
    colocated_suppressed = 0
    lo, hi = loc_range
    for e in entries:
        if lo <= e["loc"] <= hi:
            continue
        # Skip files in directories that are single-use by design (e.g., commands/)
        if skip_dir_names:
            parts = Path(e["file"]).parts
            if any(p in skip_dir_names for p in parts):
                continue
        if suppress_colocated and get_area:
            src_area = get_area(rel(e["file"]))
            imp_area = get_area(e["sole_importer"])
            if src_area == imp_area:
                colocated_suppressed += 1
                continue
        results.append(
            make_finding(
                "single_use",
                e["file"],
                "",
                tier=3,
                confidence="medium",
                summary=f"Single-use ({e['loc']} LOC): only imported by {e['sole_importer']}",
                detail={"loc": e["loc"], "sole_importer": e["sole_importer"]},
            )
        )
    suppressed = len(entries) - len(results)
    coloc_note = f", {colocated_suppressed} co-located" if colocated_suppressed else ""
    stderr_fn(
        f"         single-use: {len(entries)} found, {suppressed} suppressed "
        f"({lo}-{hi} LOC{coloc_note})"
    )
    return results


def make_cycle_findings(entries: list[dict], stderr_fn) -> list[Finding]:
    """Normalize import cycles into findings."""
    results = []
    for cy in entries:
        cycle_files = [rel(f) for f in cy["files"]]
        name = "::".join(cycle_files[:4])
        if len(cycle_files) > 4:
            name += f"::+{len(cycle_files) - 4}"
        tier = 3 if cy["length"] <= 3 else 4
        results.append(
            make_finding(
                "cycles",
                cy["files"][0],
                name,
                tier=tier,
                confidence="high",
                summary=f"Import cycle ({cy['length']} files): "
                + " -> ".join(cycle_files[:5])
                + (f" -> +{len(cycle_files) - 5}" if len(cycle_files) > 5 else ""),
                detail={"files": cycle_files, "length": cy["length"]},
            )
        )
    if entries:
        stderr_fn(f"         cycles: {len(entries)} import cycles")
    return results


def make_orphaned_findings(entries: list[dict], stderr_fn) -> list[Finding]:
    """Normalize orphaned file entries into findings."""
    results = []
    for e in entries:
        results.append(
            make_finding(
                "orphaned",
                e["file"],
                "",
                tier=3,
                confidence="medium",
                summary=f"Orphaned file ({e['loc']} LOC): zero importers, not an entry point",
                detail={"loc": e["loc"]},
            )
        )
    if entries:
        stderr_fn(f"         orphaned: {len(entries)} files with zero importers")
    return results


SMELL_TIER_MAP = {"high": Tier.QUICK_FIX, "medium": Tier.JUDGMENT, "low": Tier.JUDGMENT}


def make_smell_findings(entries: list[dict], stderr_fn) -> list[Finding]:
    """Group smell entries by file and assign tiers from severity.

    Input: list of smell dicts from detect_smells, each with id/label/severity/matches.
    Output: findings grouped per (file, smell_id).
    """
    results = []
    for e in entries:
        by_file: dict[str, list] = defaultdict(list)
        for m in e["matches"]:
            by_file[m["file"]].append(m)
        for file, matches in by_file.items():
            conf = "medium" if e["severity"] != "low" else "low"
            tier = SMELL_TIER_MAP.get(e["severity"], 3)
            results.append(
                make_finding(
                    "smells",
                    file,
                    e["id"],
                    tier=tier,
                    confidence=conf,
                    summary=f"{len(matches)}x {e['label']}",
                    detail={
                        "smell_id": e["id"],
                        "severity": e["severity"],
                        "count": len(matches),
                        "lines": [m["line"] for m in matches[:10]],
                    },
                )
            )
    stderr_fn(f"         -> {len(results)} smell findings")
    return results


def make_passthrough_findings(
    entries: list[dict],
    name_key: str,
    total_key: str,
    stderr_fn,
) -> list[Finding]:
    """Normalize passthrough detection results into findings."""
    results = []
    for e in entries:
        label = e[name_key]
        results.append(
            make_finding(
                "props",
                e["file"],
                f"passthrough::{label}",
                tier=e["tier"],
                confidence=e["confidence"],
                summary=f"Passthrough: {label} "
                f"({e['passthrough']}/{e[total_key]} forwarded, {e['ratio']:.0%})",
                detail={k: v for k, v in e.items() if k != "file"},
            )
        )
    if entries:
        stderr_fn(f"         passthrough: {len(entries)} findings")
    return results


def make_facade_findings(entries: list[dict], stderr_fn) -> list[Finding]:
    """Normalize re-export facade entries into findings."""
    results = []
    for e in entries:
        kind = e["kind"]
        if kind == "directory":
            summary = (
                f"Facade directory ({e['loc']} LOC, {e.get('file_count', '?')} files): "
                f"all modules are re-exports ({e['importers']} importers)"
            )
        else:
            from_str = ", ".join(e["imports_from"][:3])
            if len(e["imports_from"]) > 3:
                from_str += f", +{len(e['imports_from']) - 3}"
            summary = (
                f"Re-export facade ({e['loc']} LOC): "
                f"imports from {from_str} ({e['importers']} importers)"
            )
        results.append(
            make_finding(
                "facade",
                e["file"],
                "",
                tier=2,
                confidence="high" if e["importers"] == 0 else "medium",
                summary=summary,
                detail={
                    "loc": e["loc"],
                    "importers": e["importers"],
                    "imports_from": e["imports_from"],
                    "kind": kind,
                },
            )
        )
    if entries:
        stderr_fn(f"         facades: {len(entries)} re-export facade findings")
    return results
