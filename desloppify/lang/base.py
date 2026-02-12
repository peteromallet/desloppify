"""Base abstractions for multi-language support."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..state import make_finding
from ..utils import PROJECT_ROOT, rel, resolve_path


@dataclass
class DetectorPhase:
    """A single phase in the scan pipeline.

    Each phase runs one or more detectors and returns normalized findings.
    The `run` function handles both detection AND normalization (converting
    raw detector output to findings with tiers/confidence).
    """
    label: str
    run: Callable[[Path, LangConfig], list[dict]]
    slow: bool = False


@dataclass
class FixerConfig:
    """Configuration for an auto-fixer."""
    label: str
    detect: Callable
    fix: Callable
    detector: str           # finding detector name (for state resolution)
    verb: str = "Fixed"
    dry_verb: str = "Would fix"
    post_fix: Callable | None = None


@dataclass
class BoundaryRule:
    """A coupling boundary: `protected` dir should not be imported from `forbidden_from`."""
    protected: str          # e.g. "shared/"
    forbidden_from: str     # e.g. "tools/"
    label: str              # e.g. "shared→tools"


@dataclass
class LangConfig:
    """Language configuration — everything the pipeline needs to scan a codebase."""

    name: str
    extensions: list[str]
    exclusions: list[str]
    default_src: str                                    # relative to PROJECT_ROOT

    # Dep graph builder (language-specific import parsing)
    build_dep_graph: Callable[[Path], dict]

    # Entry points (not orphaned even with 0 importers)
    entry_patterns: list[str]
    barrel_names: set[str]

    # Detector phases (ordered)
    phases: list[DetectorPhase] = field(default_factory=list)

    # Fixer registry
    fixers: dict[str, FixerConfig] = field(default_factory=dict)

    # Area classification (project-specific grouping)
    get_area: Callable[[str], str] | None = None

    # Commands for `detect` subcommand (language-specific overrides)
    # Keys serve as the valid detector name list.
    detect_commands: dict[str, Callable] = field(default_factory=dict)

    # Function extractor (for duplicate detection)
    extract_functions: Callable[[str], list[dict]] | None = None

    # Coupling boundaries (optional, project-specific)
    boundaries: list[BoundaryRule] = field(default_factory=list)

    # Unused detection tool command (for post-fix checklist)
    typecheck_cmd: str = ""

    # File finder: (path) -> list[str]
    file_finder: Callable | None = None

    # Structural analysis thresholds
    large_threshold: int = 500
    complexity_threshold: int = 15

    # Zone classification
    zone_rules: list = field(default_factory=list)
    _zone_map: object = field(default=None, repr=False)  # FileZoneMap, set at scan time


def make_unused_findings(entries: list[dict], stderr_fn) -> list[dict]:
    """Transform raw unused-detector entries into normalized findings.

    Shared by both Python and TypeScript unused phases.
    """
    results = []
    for e in entries:
        tier = 1 if e["category"] == "imports" else 2
        results.append(make_finding(
            "unused", e["file"], e["name"],
            tier=tier, confidence="high",
            summary=f"Unused {e['category']}: {e['name']}",
            detail={"line": e["line"], "category": e["category"]},
        ))
    stderr_fn(f"         {len(entries)} instances -> {len(results)} findings")
    return results


def make_dupe_findings(entries: list[dict], stderr_fn) -> list[dict]:
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
            summary = (f"{kind_label} dupe cluster ({cluster_size} functions, "
                       f"{e['similarity']:.0%} similar): "
                       f"{a['name']} ({rel(a['file'])}:{a['line']}), "
                       f"{b['name']} ({rel(b['file'])}:{b['line']}), ...")
        else:
            summary = (f"{kind_label} dupe: "
                       f"{a['name']} ({rel(a['file'])}:{a['line']}) <-> "
                       f"{b['name']} ({rel(b['file'])}:{b['line']}) [{e['similarity']:.0%}]")
        results.append(make_finding(
            "dupes", pair[0][0], name,
            tier=tier, confidence=conf,
            summary=summary,
            detail={"fn_a": a, "fn_b": b,
                    "similarity": e["similarity"], "kind": e["kind"],
                    "cluster_size": cluster_size,
                    "cluster": e.get("cluster", [a, b])},
        ))
    suppressed = sum(1 for e in entries
                     if e["fn_a"]["loc"] < 10 and e["fn_b"]["loc"] < 10)
    stderr_fn(f"         {len(entries)} clusters, {suppressed} suppressed (<10 LOC)")
    return results


def add_structural_signal(structural: dict, file: str, signal: str, detail: dict):
    """Add a complexity signal to the per-file structural dict.

    Accumulates signals per file so they can be merged into tiered findings.
    """
    f = resolve_path(file)
    structural.setdefault(f, {"signals": [], "detail": {}})
    structural[f]["signals"].append(signal)
    structural[f]["detail"].update(detail)


def merge_structural_signals(structural: dict, stderr_fn,
                              *, complexity_only_min: int = 35) -> list[dict]:
    """Convert per-file structural signals into tiered findings.

    3+ signals -> T4/high (needs decomposition).
    1-2 signals -> T3/medium.
    Complexity-only files (no large/god signals) need score >= complexity_only_min
    to be flagged — lower complexity in small files is normal, not decomposition-worthy.
    """
    results = []
    suppressed = 0
    for filepath, data in structural.items():
        if "loc" not in data["detail"]:
            try:
                p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
                data["detail"]["loc"] = len(p.read_text().splitlines())
            except (OSError, UnicodeDecodeError):
                data["detail"]["loc"] = 0

        # Suppress complexity-only findings below the elevated threshold
        signals = data["signals"]
        is_complexity_only = all(s.startswith("complexity") for s in signals)
        if is_complexity_only:
            score = data["detail"].get("complexity_score", 0)
            if score < complexity_only_min:
                suppressed += 1
                continue

        signal_count = len(signals)
        tier = 4 if signal_count >= 3 else 3
        confidence = "high" if signal_count >= 3 else "medium"
        summary = "Needs decomposition: " + " / ".join(signals)
        results.append(make_finding(
            "structural", filepath, "",
            tier=tier, confidence=confidence,
            summary=summary,
            detail=data["detail"],
        ))
    if suppressed:
        stderr_fn(f"         {suppressed} complexity-only files below threshold (< {complexity_only_min})")
    stderr_fn(f"         -> {len(results)} structural findings")
    return results


def make_single_use_findings(
    entries: list[dict],
    get_area,
    *,
    loc_range: tuple[int, int] = (50, 200),
    suppress_colocated: bool = True,
    skip_dir_names: set[str] | None = None,
    stderr_fn,
) -> list[dict]:
    """Filter and normalize single-use entries into findings.

    Suppresses entries within the LOC range (they're appropriately-sized abstractions),
    entries co-located with their sole importer, and entries in skip_dir_names
    directories (e.g., commands/ — CLI modules are single-use by design).
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
        results.append(make_finding(
            "single_use", e["file"], "",
            tier=3, confidence="medium",
            summary=f"Single-use ({e['loc']} LOC): only imported by {e['sole_importer']}",
            detail={"loc": e["loc"], "sole_importer": e["sole_importer"]},
        ))
    suppressed = len(entries) - len(results)
    coloc_note = f", {colocated_suppressed} co-located" if colocated_suppressed else ""
    stderr_fn(f"         single-use: {len(entries)} found, {suppressed} suppressed "
              f"({lo}-{hi} LOC{coloc_note})")
    return results


def make_cycle_findings(entries: list[dict], stderr_fn) -> list[dict]:
    """Normalize import cycles into findings."""
    results = []
    for cy in entries:
        cycle_files = [rel(f) for f in cy["files"]]
        name = "::".join(cycle_files[:4])
        if len(cycle_files) > 4:
            name += f"::+{len(cycle_files) - 4}"
        tier = 3 if cy["length"] <= 3 else 4
        results.append(make_finding(
            "cycles", cy["files"][0], name,
            tier=tier, confidence="high",
            summary=f"Import cycle ({cy['length']} files): "
                    + " -> ".join(cycle_files[:5])
                    + (f" -> +{len(cycle_files) - 5}" if len(cycle_files) > 5 else ""),
            detail={"files": cycle_files, "length": cy["length"]},
        ))
    if entries:
        stderr_fn(f"         cycles: {len(entries)} import cycles")
    return results


def make_orphaned_findings(entries: list[dict], stderr_fn) -> list[dict]:
    """Normalize orphaned file entries into findings."""
    results = []
    for e in entries:
        results.append(make_finding(
            "orphaned", e["file"], "",
            tier=3, confidence="medium",
            summary=f"Orphaned file ({e['loc']} LOC): zero importers, not an entry point",
            detail={"loc": e["loc"]},
        ))
    if entries:
        stderr_fn(f"         orphaned: {len(entries)} files with zero importers")
    return results


SMELL_TIER_MAP = {"high": 2, "medium": 3, "low": 3}


def make_smell_findings(entries: list[dict], stderr_fn) -> list[dict]:
    """Group smell entries by file and assign tiers from severity.

    Input: list of smell dicts from detect_smells, each with id/label/severity/matches.
    Output: findings grouped per (file, smell_id).
    """
    from collections import defaultdict
    results = []
    for e in entries:
        by_file: dict[str, list] = defaultdict(list)
        for m in e["matches"]:
            by_file[m["file"]].append(m)
        for file, matches in by_file.items():
            conf = "medium" if e["severity"] != "low" else "low"
            tier = SMELL_TIER_MAP.get(e["severity"], 3)
            results.append(make_finding(
                "smells", file, e["id"],
                tier=tier, confidence=conf,
                summary=f"{len(matches)}x {e['label']}",
                detail={"smell_id": e["id"], "severity": e["severity"],
                        "count": len(matches),
                        "lines": [m["line"] for m in matches[:10]]},
            ))
    stderr_fn(f"         -> {len(results)} smell findings")
    return results


def phase_dupes(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    """Shared phase runner: detect duplicate functions via lang.extract_functions.

    When a zone map is available, filters out functions from zone-excluded files
    before the O(n^2) comparison to avoid test/config/generated false positives.
    """
    from ..detectors.dupes import detect_duplicates
    from ..utils import log
    functions = lang.extract_functions(path)

    # Filter out functions from zone-excluded files
    if lang._zone_map is not None:
        from ..zones import EXCLUDED_ZONES
        before = len(functions)
        functions = [f for f in functions
                     if lang._zone_map.get(getattr(f, "file", "")) not in EXCLUDED_ZONES]
        excluded = before - len(functions)
        if excluded:
            log(f"         zones: {excluded} functions excluded (non-production)")

    entries, total_functions = detect_duplicates(functions)
    findings = make_dupe_findings(entries, log)
    return findings, {"dupes": total_functions}


def make_passthrough_findings(
    entries: list[dict],
    name_key: str,
    total_key: str,
    stderr_fn,
) -> list[dict]:
    """Normalize passthrough detection results into findings."""
    results = []
    for e in entries:
        label = e[name_key]
        results.append(make_finding(
            "props", e["file"], f"passthrough::{label}",
            tier=e["tier"], confidence=e["confidence"],
            summary=f"Passthrough: {label} "
                    f"({e['passthrough']}/{e[total_key]} forwarded, {e['ratio']:.0%})",
            detail={k: v for k, v in e.items() if k != "file"},
        ))
    if entries:
        stderr_fn(f"         passthrough: {len(entries)} findings")
    return results


def make_facade_findings(entries: list[dict], stderr_fn) -> list[dict]:
    """Normalize re-export facade entries into findings."""
    results = []
    for e in entries:
        kind = e["kind"]
        if kind == "directory":
            summary = (f"Facade directory ({e['loc']} LOC, {e.get('file_count', '?')} files): "
                       f"all modules are re-exports ({e['importers']} importers)")
        else:
            from_str = ", ".join(e["imports_from"][:3])
            if len(e["imports_from"]) > 3:
                from_str += f", +{len(e['imports_from']) - 3}"
            summary = (f"Re-export facade ({e['loc']} LOC): "
                       f"imports from {from_str} ({e['importers']} importers)")
        results.append(make_finding(
            "facade", e["file"], "",
            tier=2, confidence="high" if e["importers"] == 0 else "medium",
            summary=summary,
            detail={"loc": e["loc"], "importers": e["importers"],
                    "imports_from": e["imports_from"], "kind": kind},
        ))
    if entries:
        stderr_fn(f"         facades: {len(entries)} re-export facade findings")
    return results
