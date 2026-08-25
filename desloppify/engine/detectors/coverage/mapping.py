"""Test coverage mapping — import resolution, naming conventions, quality analysis."""

from __future__ import annotations

import logging
import os

from desloppify.base.discovery.paths import get_project_root
from desloppify.engine.detectors.coverage.mapping_analysis import (
    _build_prod_by_module,
    transitive_coverage,
)
from desloppify.engine.detectors.coverage.mapping_analysis import (
    analyze_test_quality as _analyze_test_quality,
)
from desloppify.engine.detectors.coverage.mapping_analysis import (
    build_production_test_index as _build_production_test_index,
)
from desloppify.engine.detectors.coverage.mapping_analysis import (
    build_test_import_index as _build_test_import_index,
)
from desloppify.engine.detectors.coverage.mapping_analysis import (
    get_test_files_for_prod as _get_test_files_for_prod,
)
from desloppify.engine.detectors.coverage.mapping_imports import (
    _infer_lang_name,
    _load_lang_test_coverage_module,
    _parse_test_imports,
    _resolve_barrel_reexports,
)
from desloppify.engine.detectors.test_coverage.io import read_coverage_file

logger = logging.getLogger(__name__)


def _build_prod_module_index(production_files: set[str]) -> dict[str, str]:
    """Build a mapping from module basename/dotted-path to full file path."""
    return _build_prod_by_module(
        production_files,
        project_root=str(get_project_root()),
    )


def _graph_tested_imports(
    graph: dict,
    test_files: set[str],
    production_files: set[str],
    prod_by_module: dict[str, str],
    lang_name: str | None,
) -> set[str]:
    """Follow import graph edges from test files to find directly-tested production files."""
    tested: set[str] = set()
    for tf in test_files:
        entry = graph.get(tf)
        graph_mapped: set[str] = set()
        if entry is not None:
            for imp in entry.get("imports", set()):
                if imp in production_files:
                    graph_mapped.add(imp)
            tested |= graph_mapped

        # Always supplement graph-based detection with source parsing.
        # The import graph often resolves submodule imports (e.g.,
        # `from megaplan.evaluation import X`) to the package __init__.py
        # rather than the actual submodule file, causing false
        # "transitive_only" reports for modules with dedicated test files.
        tested |= _parse_test_imports(
            tf, production_files, prod_by_module, lang_name
        )
    return tested


def _expand_barrel_targets(
    *,
    tested: set[str],
    barrel_basenames: set[str],
    production_files: set[str],
    lang_name: str | None,
) -> set[str]:
    """Expand barrel/index file imports to the actual modules they re-export."""
    extra: set[str] = set()
    barrel_files = [f for f in tested if os.path.basename(f) in barrel_basenames]
    for bf in barrel_files:
        extra |= _resolve_barrel_reexports(bf, production_files, lang_name)
    return extra


def _expand_facade_targets(
    *,
    tested: set[str],
    graph: dict,
    production_files: set[str],
    has_logic,
) -> set[str]:
    """Expand facade imports to their underlying implementation files.

    If a directly-tested file has no testable logic (pure re-export facade),
    promote its imports to directly tested.  This prevents false
    "transitive_only" issues for internal modules behind facades like
    scoring.py -> _scoring/policy/core.py.
    """
    facade_targets: set[str] = set()
    for f in list(tested):
        entry = graph.get(f)
        if entry is None:
            continue
        read_result = read_coverage_file(
            f, context="coverage_import_mapping_facade_logic"
        )
        if not read_result.ok:
            continue
        content = read_result.content
        if not has_logic(f, content):
            for imp in entry.get("imports", set()):
                if imp in production_files:
                    facade_targets.add(imp)
    return facade_targets


def import_based_mapping(
    graph: dict,
    test_files: set[str],
    production_files: set[str],
    lang_name: str | None = None,
) -> set[str]:
    """Map test files to production files via import edges."""
    lang_name = lang_name or _infer_lang_name(test_files, production_files)
    mod = _load_lang_test_coverage_module(lang_name)

    prod_by_module = _build_prod_module_index(production_files)
    tested = _graph_tested_imports(
        graph, test_files, production_files, prod_by_module, lang_name
    )

    barrel_basenames = getattr(mod, "BARREL_BASENAMES", set())
    if barrel_basenames:
        tested |= _expand_barrel_targets(
            tested=tested,
            barrel_basenames=barrel_basenames,
            production_files=production_files,
            lang_name=lang_name,
        )

    has_logic = getattr(mod, "has_testable_logic", None)
    if callable(has_logic):
        tested |= _expand_facade_targets(
            tested=tested,
            graph=graph,
            production_files=production_files,
            has_logic=has_logic,
        )

    return tested


def _map_test_to_source(
    test_path: str,
    production_set: set[str],
    lang_name: str,
) -> str | None:
    """Match a test file to a production file using language conventions."""
    mod = _load_lang_test_coverage_module(lang_name)
    mapper = getattr(mod, "map_test_to_source", None)
    if callable(mapper):
        return mapper(test_path, production_set)
    return None


def naming_based_mapping(
    test_files: set[str],
    production_files: set[str],
    lang_name: str,
) -> set[str]:
    """Map test files to production files by naming conventions."""
    tested = set()

    prod_by_basename: dict[str, list[str]] = {}
    for p in production_files:
        bn = os.path.basename(p)
        prod_by_basename.setdefault(bn, []).append(p)

    for tf in test_files:
        matched = _map_test_to_source(tf, production_files, lang_name)
        if matched:
            tested.add(matched)
            continue

        basename = os.path.basename(tf)
        src_name = _strip_test_markers(basename, lang_name)
        if src_name and src_name in prod_by_basename:
            for p in prod_by_basename[src_name]:
                tested.add(p)

    return tested


def promote_owner_coverage(
    directly_tested: set[str],
    transitively_tested: set[str],
    production_files: set[str],
    lang_name: str,
) -> set[str]:
    """Promote language-specific child modules covered through an owner boundary."""
    mod = _load_lang_test_coverage_module(lang_name)
    promoter = getattr(mod, "promote_owner_covered_files", None)
    if not callable(promoter):
        return set()
    return set(promoter(directly_tested, transitively_tested, production_files))


def _strip_test_markers(basename: str, lang_name: str) -> str | None:
    """Strip test naming markers from a basename to derive source basename."""
    mod = _load_lang_test_coverage_module(lang_name)
    strip_markers = getattr(mod, "strip_test_markers", None)
    if callable(strip_markers):
        return strip_markers(basename)
    return None


def analyze_test_quality(
    test_files: set[str],
    lang_name: str,
) -> dict[str, dict]:
    """Analyze test quality per file."""
    return _analyze_test_quality(
        test_files,
        lang_name,
        load_lang_module=_load_lang_test_coverage_module,
        read_coverage_file_fn=read_coverage_file,
        logger=logger,
    )


def get_test_files_for_prod(
    prod_file: str,
    test_files: set[str],
    graph: dict,
    lang_name: str,
    parsed_imports_by_test: dict[str, set[str]] | None = None,
) -> list[str]:
    """Find which test files exercise a given production file."""
    return _get_test_files_for_prod(
        prod_file,
        test_files,
        graph,
        lang_name,
        parsed_imports_by_test,
        parse_test_imports_fn=_parse_test_imports,
        map_test_to_source_fn=_map_test_to_source,
        project_root=str(get_project_root()),
    )


def build_test_import_index(
    test_files: set[str],
    production_files: set[str],
    lang_name: str,
) -> dict[str, set[str]]:
    """Parse test import sources once, producing a test->production import index."""
    return _build_test_import_index(
        test_files,
        production_files,
        lang_name,
        parse_test_imports_fn=_parse_test_imports,
        project_root=str(get_project_root()),
    )


def build_production_test_index(
    test_files: set[str],
    production_files: set[str],
    graph: dict,
    lang_name: str,
    parsed_imports_by_test: dict[str, set[str]],
) -> dict[str, list[str]]:
    """Index direct tests by production file without quadratic resolution."""
    return _build_production_test_index(
        test_files,
        production_files,
        graph,
        lang_name,
        parsed_imports_by_test,
        map_test_to_source_fn=_map_test_to_source,
    )


__all__ = [
    "analyze_test_quality",
    "build_production_test_index",
    "build_test_import_index",
    "get_test_files_for_prod",
    "import_based_mapping",
    "naming_based_mapping",
    "promote_owner_coverage",
    "transitive_coverage",
    "_build_prod_module_index",
    "_map_test_to_source",
    "_strip_test_markers",
]
