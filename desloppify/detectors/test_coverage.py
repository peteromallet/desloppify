"""Test coverage gap detection — static analysis of test file mapping and quality.

Measures test *need* (what's dangerous without tests) not just test existence,
weighting by blast radius (importer count) so that testing one critical file
moves the score more than testing ten trivial ones.
"""

from __future__ import annotations

import math
import os
from pathlib import Path

from .lang_hooks import load_lang_hook_module
from ..utils import PROJECT_ROOT
from ..zones import FileZoneMap, Zone

# Minimum LOC threshold — tiny files don't need dedicated tests
_MIN_LOC = 10

# Max untested modules to report when there are zero tests
_MAX_NO_TESTS_ENTRIES = 50

def detect_test_coverage(
    graph: dict,
    zone_map: FileZoneMap,
    lang_name: str,
    extra_test_files: set[str] | None = None,
    complexity_map: dict[str, float] | None = None,
) -> tuple[list[dict], int]:
    """Detect test coverage gaps.

    Args:
        graph: dep graph from lang.build_dep_graph — {filepath: {"imports": set, "importer_count": int, ...}}
        zone_map: FileZoneMap from lang._zone_map
        lang_name: language plugin name (for loading language-specific coverage hooks)
        extra_test_files: test files outside the scanned path (e.g. PROJECT_ROOT/tests/)
        complexity_map: {filepath: complexity_score} from structural phase — files above
            _COMPLEXITY_TIER_UPGRADE threshold get their tier upgraded to 2

    Returns:
        (entries, potential) where entries are finding-like dicts and potential
        is LOC-weighted (sqrt(loc) capped at 50 per file).
    """
    # Normalize graph paths to relative (zone_map uses relative paths, graph may use absolute)
    root_prefix = str(PROJECT_ROOT) + os.sep
    def _to_rel(p: str) -> str:
        return p[len(root_prefix):] if p.startswith(root_prefix) else p

    needs_norm = any(k.startswith(root_prefix) for k in list(graph)[:3])
    if needs_norm:
        norm_graph: dict = {}
        for k, v in graph.items():
            rk = _to_rel(k)
            norm_graph[rk] = {
                **v,
                "imports": {_to_rel(imp) for imp in v.get("imports", set())},
            }
        graph = norm_graph

    all_files = zone_map.all_files()
    production_files = set(zone_map.include_only(all_files, Zone.PRODUCTION, Zone.SCRIPT))
    test_files = set(zone_map.include_only(all_files, Zone.TEST))

    # Include test files from outside the scanned path (normalize to relative)
    if extra_test_files:
        test_files |= {_to_rel(f) for f in extra_test_files}

    # Only score production files that are substantial and have testable logic.
    # Excludes type-only files, barrel re-exports, and declaration-only files.
    scorable = {f for f in production_files
                if _file_loc(f) >= _MIN_LOC and _has_testable_logic(f, lang_name)}

    if not scorable:
        return [], 0

    # LOC-weighted potential: sqrt(loc) capped at 50 per file.
    # This weights large untested files more heavily — a 500-LOC untested file
    # contributes ~22x more to score impact than a 15-LOC file.
    potential = round(sum(min(math.sqrt(_file_loc(f)), 50) for f in scorable))

    # If zero test files, emit findings for top modules by LOC
    if not test_files:
        entries = _no_tests_findings(scorable, graph, complexity_map)
        return entries, potential

    # Step 1: Import-based mapping (precise)
    directly_tested = _import_based_mapping(graph, test_files, production_files, lang_name)

    # Step 2: Naming convention fallback
    name_tested = _naming_based_mapping(test_files, production_files, lang_name)
    directly_tested |= name_tested

    # Step 3: Transitive coverage via BFS
    transitively_tested = _transitive_coverage(directly_tested, graph, production_files)

    # Step 4: Test quality analysis
    test_quality = _analyze_test_quality(test_files, lang_name)

    # Step 5: Generate findings
    entries = _generate_findings(
        scorable, directly_tested, transitively_tested,
        test_quality, graph, lang_name,
        complexity_map=complexity_map,
    )

    return entries, potential


# ── Internal helpers ──────────────────────────────────────


def _file_loc(filepath: str) -> int:
    """Count lines in a file, returning 0 on error."""
    try:
        return len(Path(filepath).read_text().splitlines())
    except (OSError, UnicodeDecodeError):
        return 0


def _loc_weight(loc: int) -> float:
    """Compute LOC weight for a file: sqrt(loc) capped at 50."""
    return min(math.sqrt(loc), 50)


def _has_testable_logic(filepath: str, lang_name: str) -> bool:
    """Check whether a file contains runtime logic worth testing.

    Returns False for files that need no dedicated tests:
    - .d.ts type definition files (TypeScript)
    - Files containing only type/interface declarations and imports
    - Barrel files containing only re-exports
    - Python files with no function or method definitions
    """
    try:
        content = Path(filepath).read_text()
    except (OSError, UnicodeDecodeError):
        return True  # assume testable if unreadable

    mod = _load_lang_test_coverage_module(lang_name)
    has_logic = getattr(mod, "has_testable_logic", None)
    if callable(has_logic):
        return bool(has_logic(filepath, content))
    return True


def _load_lang_test_coverage_module(lang_name: str):
    """Load language-specific test coverage helpers from ``lang/<name>/test_coverage.py``."""
    return load_lang_hook_module(lang_name, "test_coverage") or object()


def _no_tests_findings(
    scorable: set[str], graph: dict,
    complexity_map: dict[str, float] | None = None,
) -> list[dict]:
    """Generate findings when there are zero test files."""
    cmap = complexity_map or {}
    # Sort by LOC descending, take top N
    by_loc = sorted(scorable, key=lambda f: -_file_loc(f))
    entries = []
    for f in by_loc[:_MAX_NO_TESTS_ENTRIES]:
        loc = _file_loc(f)
        ic = graph.get(f, {}).get("importer_count", 0)
        complexity = cmap.get(f, 0)
        is_complex = complexity >= _COMPLEXITY_TIER_UPGRADE
        is_critical = ic >= 10 or is_complex
        tier = 2 if is_critical else 3
        kind = "untested_critical" if is_critical else "untested_module"
        detail: dict = {"kind": kind, "loc": loc, "importer_count": ic,
                        "loc_weight": _loc_weight(loc)}
        if is_complex:
            detail["complexity_score"] = complexity
        entries.append({
            "file": f,
            "name": "",
            "tier": tier,
            "confidence": "high",
            "summary": f"Untested module ({loc} LOC, {ic} importers) — no test files found",
            "detail": detail,
        })
    return entries


from .test_coverage_mapping import (  # noqa: E402
    _import_based_mapping,
    _naming_based_mapping,
    _transitive_coverage,
    _analyze_test_quality,
    _get_test_files_for_prod,
)


# Complexity score threshold for upgrading test coverage tier.
# Files above this are risky enough without tests to warrant tier 2.
_COMPLEXITY_TIER_UPGRADE = 20


def _generate_findings(
    scorable: set[str],
    directly_tested: set[str],
    transitively_tested: set[str],
    test_quality: dict[str, dict],
    graph: dict,
    lang_name: str,
    complexity_map: dict[str, float] | None = None,
) -> list[dict]:
    """Generate test coverage findings from the analysis results."""
    entries: list[dict] = []
    cmap = complexity_map or {}

    # Collect all test files for mapping
    test_files = set(test_quality.keys())

    for f in scorable:
        loc = _file_loc(f)
        ic = graph.get(f, {}).get("importer_count", 0)
        lw = _loc_weight(loc)

        if f in directly_tested:
            # Check quality of the test(s) for this file
            related_tests = _get_test_files_for_prod(f, test_files, graph, lang_name)
            for tf in related_tests:
                tq = test_quality.get(tf)
                if tq is None:
                    continue

                if tq["quality"] == "assertion_free":
                    entries.append({
                        "file": f,
                        "name": f"assertion_free::{os.path.basename(tf)}",
                        "tier": 3,
                        "confidence": "medium",
                        "summary": (f"Assertion-free test: {os.path.basename(tf)} "
                                    f"has {tq['test_functions']} test functions but 0 assertions"),
                        "detail": {"kind": "assertion_free_test", "test_file": tf,
                                   "test_functions": tq["test_functions"],
                                   "loc_weight": lw},
                    })
                elif tq["quality"] == "smoke":
                    entries.append({
                        "file": f,
                        "name": f"shallow::{os.path.basename(tf)}",
                        "tier": 3,
                        "confidence": "medium",
                        "summary": (f"Shallow tests: {os.path.basename(tf)} has "
                                    f"{tq['assertions']} assertions across "
                                    f"{tq['test_functions']} test functions"),
                        "detail": {"kind": "shallow_tests", "test_file": tf,
                                   "assertions": tq["assertions"],
                                   "test_functions": tq["test_functions"],
                                   "loc_weight": lw},
                    })
                elif tq["quality"] == "over_mocked":
                    entries.append({
                        "file": f,
                        "name": f"over_mocked::{os.path.basename(tf)}",
                        "tier": 3,
                        "confidence": "low",
                        "summary": (f"Over-mocked tests: {os.path.basename(tf)} has "
                                    f"{tq['mocks']} mocks vs {tq['assertions']} assertions"),
                        "detail": {"kind": "over_mocked", "test_file": tf,
                                   "mocks": tq["mocks"], "assertions": tq["assertions"],
                                   "loc_weight": lw},
                    })
                elif tq["quality"] == "snapshot_heavy":
                    entries.append({
                        "file": f,
                        "name": f"snapshot_heavy::{os.path.basename(tf)}",
                        "tier": 3,
                        "confidence": "low",
                        "summary": (f"Snapshot-heavy tests: {os.path.basename(tf)} has "
                                    f"{tq['snapshots']} snapshots vs {tq['assertions']} assertions"),
                        "detail": {"kind": "snapshot_heavy", "test_file": tf,
                                   "snapshots": tq["snapshots"],
                                   "assertions": tq["assertions"],
                                   "loc_weight": lw},
                    })

        elif f in transitively_tested:
            complexity = cmap.get(f, 0)
            is_complex = complexity >= _COMPLEXITY_TIER_UPGRADE
            tier = 2 if (ic >= 10 or is_complex) else 3
            detail: dict = {"kind": "transitive_only", "loc": loc, "importer_count": ic,
                            "loc_weight": lw}
            if is_complex:
                detail["complexity_score"] = complexity
            entries.append({
                "file": f,
                "name": "transitive_only",
                "tier": tier,
                "confidence": "medium",
                "summary": (f"No direct tests ({loc} LOC, {ic} importers) "
                            f"— covered only via imports from tested modules"),
                "detail": detail,
            })

        else:
            # Untested
            complexity = cmap.get(f, 0)
            is_complex = complexity >= _COMPLEXITY_TIER_UPGRADE
            if ic >= 10 or is_complex:
                detail = {"kind": "untested_critical", "loc": loc, "importer_count": ic,
                          "loc_weight": lw}
                if is_complex:
                    detail["complexity_score"] = complexity
                entries.append({
                    "file": f,
                    "name": "untested_critical",
                    "tier": 2,
                    "confidence": "high",
                    "summary": (f"Untested critical module ({loc} LOC, {ic} importers) "
                                f"— high blast radius"),
                    "detail": detail,
                })
            else:
                entries.append({
                    "file": f,
                    "name": "untested_module",
                    "tier": 3,
                    "confidence": "high",
                    "summary": f"Untested module ({loc} LOC, {ic} importers)",
                    "detail": {"kind": "untested_module", "loc": loc, "importer_count": ic,
                               "loc_weight": lw},
                })

    return entries
