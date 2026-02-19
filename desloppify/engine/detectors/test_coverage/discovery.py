"""File discovery and mapping helpers for test coverage detector."""

from __future__ import annotations

import math
import os

from desloppify.engine.policy.zones import FileZoneMap, Zone
from desloppify.utils import PROJECT_ROOT

from .heuristics import _has_testable_logic, _is_runtime_entrypoint
from .metrics import _COMPLEXITY_TIER_UPGRADE, _MIN_LOC, _file_loc, _loc_weight

# Max untested modules to report when there are zero tests
_MAX_NO_TESTS_ENTRIES = 50


def _normalize_graph_paths(graph: dict) -> dict:
    """Normalize graph paths to relative paths."""
    root_prefix = str(PROJECT_ROOT) + os.sep

    def _to_rel(path: str) -> str:
        return path[len(root_prefix) :] if path.startswith(root_prefix) else path

    needs_norm = any(k.startswith(root_prefix) for k in list(graph)[:3])
    if not needs_norm:
        return graph

    norm_graph: dict = {}
    for key, value in graph.items():
        rel_key = _to_rel(key)
        norm_graph[rel_key] = {
            **value,
            "imports": {_to_rel(imp) for imp in value.get("imports", set())},
        }
    return norm_graph


def _discover_scorable_and_tests(
    *,
    graph: dict,
    zone_map: FileZoneMap,
    lang_name: str,
    extra_test_files: set[str] | None,
) -> tuple[set[str], set[str], set[str], int]:
    """Return (production_files, test_files, scorable_files, potential)."""
    root_prefix = str(PROJECT_ROOT) + os.sep

    def _to_rel(path: str) -> str:
        return path[len(root_prefix) :] if path.startswith(root_prefix) else path

    all_files = zone_map.all_files()
    production_files = set(zone_map.include_only(all_files, Zone.PRODUCTION, Zone.SCRIPT))
    test_files = set(zone_map.include_only(all_files, Zone.TEST))

    if extra_test_files:
        test_files |= {_to_rel(f) for f in extra_test_files}

    scorable = {
        filepath
        for filepath in production_files
        if _file_loc(filepath) >= _MIN_LOC and _has_testable_logic(filepath, lang_name)
    }

    potential = round(sum(min(math.sqrt(_file_loc(f)), 50) for f in scorable))
    return production_files, test_files, scorable, potential


def _no_tests_findings(
    scorable: set[str],
    graph: dict,
    lang_name: str,
    complexity_map: dict[str, float] | None = None,
) -> list[dict]:
    """Generate findings when there are zero test files."""
    cmap = complexity_map or {}
    by_loc = sorted(scorable, key=lambda f: -_file_loc(f))
    entries = []
    for filepath in by_loc[:_MAX_NO_TESTS_ENTRIES]:
        loc = _file_loc(filepath)
        importer_count = graph.get(filepath, {}).get("importer_count", 0)
        is_runtime_entry = _is_runtime_entrypoint(filepath, lang_name)
        if is_runtime_entry:
            entries.append(
                {
                    "file": filepath,
                    "name": "runtime_entrypoint_no_direct_tests",
                    "tier": 3,
                    "confidence": "medium",
                    "summary": (
                        f"Runtime entrypoint ({loc} LOC, {importer_count} importers) — "
                        "externally invoked; no direct tests found"
                    ),
                    "detail": {
                        "kind": "runtime_entrypoint_no_direct_tests",
                        "loc": loc,
                        "importer_count": importer_count,
                        "loc_weight": 0.0,
                        "entrypoint": True,
                    },
                }
            )
            continue
        complexity = cmap.get(filepath, 0)
        is_complex = complexity >= _COMPLEXITY_TIER_UPGRADE
        is_critical = importer_count >= 10 or is_complex
        tier = 2 if is_critical else 3
        kind = "untested_critical" if is_critical else "untested_module"
        detail: dict = {
            "kind": kind,
            "loc": loc,
            "importer_count": importer_count,
            "loc_weight": _loc_weight(loc),
        }
        if is_complex:
            detail["complexity_score"] = complexity
        entries.append(
            {
                "file": filepath,
                "name": "",
                "tier": tier,
                "confidence": "high",
                "summary": f"Untested module ({loc} LOC, {importer_count} importers) — no test files found",
                "detail": detail,
            }
        )
    return entries
