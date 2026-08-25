"""Top-level issue generation for the test-coverage detector."""

from __future__ import annotations

from desloppify.engine.detectors.coverage.mapping import (
    build_production_test_index,
    build_test_import_index,
)

from ._issue_gaps import transitive_coverage_gap_issue, untested_module_issue
from ._issue_quality import select_direct_test_quality_issue
from .metrics import _file_loc, _loc_weight


def generate_issues(
    scorable: set[str],
    directly_tested: set[str],
    transitively_tested: set[str],
    test_quality: dict[str, dict],
    graph: dict,
    lang_name: str,
    complexity_map: dict[str, float] | None = None,
) -> list[dict]:
    """Generate test-coverage issues for all scorable production files."""
    entries: list[dict] = []
    cmap = complexity_map or {}
    test_files = set(test_quality.keys())
    production_scope = set(scorable) | set(directly_tested) | set(transitively_tested)
    parsed_imports_by_test = build_test_import_index(
        test_files,
        production_scope,
        lang_name,
    )
    related_tests_by_production = build_production_test_index(
        test_files,
        production_scope,
        graph,
        lang_name,
        parsed_imports_by_test,
    )

    for filepath in scorable:
        loc = _file_loc(filepath)
        importer_count = graph.get(filepath, {}).get("importer_count", 0)
        loc_weight = _loc_weight(loc)

        if filepath in directly_tested:
            issue = select_direct_test_quality_issue(
                prod_file=filepath,
                related_tests=related_tests_by_production.get(filepath, []),
                test_quality=test_quality,
                loc_weight=loc_weight,
            )
            if issue:
                entries.append(issue)
            continue

        complexity = cmap.get(filepath, 0)
        if filepath in transitively_tested:
            entries.append(
                transitive_coverage_gap_issue(
                    file_path=filepath,
                    loc=loc,
                    importer_count=importer_count,
                    loc_weight=loc_weight,
                    complexity=complexity,
                )
            )
            continue

        entries.append(
            untested_module_issue(
                file_path=filepath,
                loc=loc,
                importer_count=importer_count,
                loc_weight=loc_weight,
                complexity=complexity,
            )
        )

    return entries


__all__ = ["generate_issues"]
