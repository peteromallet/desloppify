"""Test coverage gap detection — static analysis of test mapping and quality."""

from __future__ import annotations

import os

from desloppify.engine.detectors.coverage.mapping import (
    _analyze_test_quality,
    _get_test_files_for_prod,
    _import_based_mapping,
    _naming_based_mapping,
    _transitive_coverage,
)
from desloppify.engine.policy.zones import FileZoneMap

from .discovery import (
    _discover_scorable_and_tests,
    _no_tests_findings,
    _normalize_graph_paths,
)
from .metrics import _COMPLEXITY_TIER_UPGRADE, _file_loc, _loc_weight


def detect_test_coverage(
    graph: dict,
    zone_map: FileZoneMap,
    lang_name: str,
    extra_test_files: set[str] | None = None,
    complexity_map: dict[str, float] | None = None,
) -> tuple[list[dict], int]:
    graph = _normalize_graph_paths(graph)

    production_files, test_files, scorable, potential = _discover_scorable_and_tests(
        graph=graph,
        zone_map=zone_map,
        lang_name=lang_name,
        extra_test_files=extra_test_files,
    )
    if not scorable:
        return [], 0

    if not test_files:
        entries = _no_tests_findings(scorable, graph, lang_name, complexity_map)
        return entries, potential

    directly_tested = _import_based_mapping(
        graph,
        test_files,
        production_files,
        lang_name,
    )

    name_tested = _naming_based_mapping(test_files, production_files, lang_name)
    directly_tested |= name_tested

    transitively_tested = _transitive_coverage(directly_tested, graph, production_files)

    test_quality = _analyze_test_quality(test_files, lang_name)

    entries = _generate_findings(
        scorable,
        directly_tested,
        transitively_tested,
        test_quality,
        graph,
        lang_name,
        complexity_map=complexity_map,
    )

    return entries, potential
def _generate_findings(
    scorable: set[str],
    directly_tested: set[str],
    transitively_tested: set[str],
    test_quality: dict[str, dict],
    graph: dict,
    lang_name: str,
    complexity_map: dict[str, float] | None = None,
) -> list[dict]:
    entries: list[dict] = []
    cmap = complexity_map or {}
    test_files = set(test_quality.keys())

    for filepath in scorable:
        loc = _file_loc(filepath)
        importer_count = graph.get(filepath, {}).get("importer_count", 0)
        loc_weight = _loc_weight(loc)

        if filepath in directly_tested:
            related_tests = _get_test_files_for_prod(
                filepath, test_files, graph, lang_name
            )
            for test_file in related_tests:
                quality = test_quality.get(test_file)
                if quality is None:
                    continue
                finding = _quality_issue_finding(
                    prod_file=filepath,
                    test_file=test_file,
                    quality=quality,
                    loc_weight=loc_weight,
                )
                if finding:
                    entries.append(finding)
            continue

        complexity = cmap.get(filepath, 0)
        if filepath in transitively_tested:
            entries.append(
                _transitive_coverage_gap_finding(
                    file_path=filepath,
                    loc=loc,
                    importer_count=importer_count,
                    loc_weight=loc_weight,
                    complexity=complexity,
                )
            )
            continue

        entries.append(
            _untested_module_finding(
                file_path=filepath,
                loc=loc,
                importer_count=importer_count,
                loc_weight=loc_weight,
                complexity=complexity,
            )
        )

    return entries
def _quality_issue_finding(
    *,
    prod_file: str,
    test_file: str,
    quality: dict,
    loc_weight: float,
) -> dict | None:
    basename = os.path.basename(test_file)
    quality_kind = quality.get("quality")
    if quality_kind == "assertion_free":
        return {
            "file": prod_file,
            "name": f"assertion_free::{basename}",
            "tier": 3,
            "confidence": "medium",
            "summary": (
                f"Assertion-free test: {basename} has "
                f"{quality['test_functions']} test functions but 0 assertions"
            ),
            "detail": {
                "kind": "assertion_free_test",
                "test_file": test_file,
                "test_functions": quality["test_functions"],
                "loc_weight": loc_weight,
            },
        }
    if quality_kind == "placeholder_smoke":
        return {
            "file": prod_file,
            "name": f"placeholder::{basename}",
            "tier": 2,
            "confidence": "high",
            "summary": (
                f"Placeholder smoke test: {basename} relies on tautological assertions "
                "and likely inflates coverage confidence"
            ),
            "detail": {
                "kind": "placeholder_test",
                "test_file": test_file,
                "assertions": quality["assertions"],
                "test_functions": quality["test_functions"],
                "loc_weight": loc_weight,
            },
        }
    if quality_kind == "smoke":
        return {
            "file": prod_file,
            "name": f"shallow::{basename}",
            "tier": 3,
            "confidence": "medium",
            "summary": (
                f"Shallow tests: {basename} has {quality['assertions']} assertions across "
                f"{quality['test_functions']} test functions"
            ),
            "detail": {
                "kind": "shallow_tests",
                "test_file": test_file,
                "assertions": quality["assertions"],
                "test_functions": quality["test_functions"],
                "loc_weight": loc_weight,
            },
        }
    if quality_kind == "over_mocked":
        return {
            "file": prod_file,
            "name": f"over_mocked::{basename}",
            "tier": 3,
            "confidence": "low",
            "summary": (
                f"Over-mocked tests: {basename} has "
                f"{quality['mocks']} mocks vs {quality['assertions']} assertions"
            ),
            "detail": {
                "kind": "over_mocked",
                "test_file": test_file,
                "mocks": quality["mocks"],
                "assertions": quality["assertions"],
                "loc_weight": loc_weight,
            },
        }
    if quality_kind == "snapshot_heavy":
        return {
            "file": prod_file,
            "name": f"snapshot_heavy::{basename}",
            "tier": 3,
            "confidence": "low",
            "summary": (
                f"Snapshot-heavy tests: {basename} has {quality['snapshots']} snapshots vs "
                f"{quality['assertions']} assertions"
            ),
            "detail": {
                "kind": "snapshot_heavy",
                "test_file": test_file,
                "snapshots": quality["snapshots"],
                "assertions": quality["assertions"],
                "loc_weight": loc_weight,
            },
        }
    return None
def _transitive_coverage_gap_finding(
    *,
    file_path: str,
    loc: int,
    importer_count: int,
    loc_weight: float,
    complexity: float,
) -> dict:
    is_complex = complexity >= _COMPLEXITY_TIER_UPGRADE
    detail: dict = {
        "kind": "transitive_only",
        "loc": loc,
        "importer_count": importer_count,
        "loc_weight": loc_weight,
    }
    if is_complex:
        detail["complexity_score"] = complexity
    return {
        "file": file_path,
        "name": "transitive_only",
        "tier": 2 if (importer_count >= 10 or is_complex) else 3,
        "confidence": "medium",
        "summary": (
            f"No direct tests ({loc} LOC, {importer_count} importers) "
            "— covered only via imports from tested modules"
        ),
        "detail": detail,
    }
def _untested_module_finding(
    *,
    file_path: str,
    loc: int,
    importer_count: int,
    loc_weight: float,
    complexity: float,
) -> dict:
    is_complex = complexity >= _COMPLEXITY_TIER_UPGRADE
    if importer_count >= 10 or is_complex:
        detail: dict = {
            "kind": "untested_critical",
            "loc": loc,
            "importer_count": importer_count,
            "loc_weight": loc_weight,
        }
        if is_complex:
            detail["complexity_score"] = complexity
        return {
            "file": file_path,
            "name": "untested_critical",
            "tier": 2,
            "confidence": "high",
            "summary": (
                f"Untested critical module ({loc} LOC, {importer_count} importers) "
                "— high blast radius"
            ),
            "detail": detail,
        }
    return {
        "file": file_path,
        "name": "untested_module",
        "tier": 3,
        "confidence": "high",
        "summary": f"Untested module ({loc} LOC, {importer_count} importers)",
        "detail": {
            "kind": "untested_module",
            "loc": loc,
            "importer_count": importer_count,
            "loc_weight": loc_weight,
        },
    }
