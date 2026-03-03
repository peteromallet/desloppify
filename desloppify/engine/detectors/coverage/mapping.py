"""Test coverage mapping — import resolution, naming conventions, quality analysis."""

from __future__ import annotations

import logging
import os
import re
from collections import deque
from pathlib import Path

from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.hook_registry import get_lang_hook
from desloppify.engine.detectors.test_coverage.io import read_coverage_file

logger = logging.getLogger(__name__)


def _load_lang_test_coverage_module(lang_name: str | None):
    """Load language-specific test coverage helpers from ``lang/<name>/test_coverage.py``."""
    return get_lang_hook(lang_name, "test_coverage") or object()


def _infer_lang_name(test_files: set[str], production_files: set[str]) -> str | None:
    """Infer language from known file extensions when explicit lang is unavailable."""
    paths = list(test_files) + list(production_files)
    ext_to_lang = {
        ".py": "python",
        ".pyi": "python",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".js": "typescript",
        ".jsx": "typescript",
        ".cs": "csharp",
        ".php": "php",
        ".go": "go",
    }
    counts: dict[str, int] = {}
    for file_path in paths:
        suffix = Path(file_path).suffix.lower()
        lang_name = ext_to_lang.get(suffix)
        if not lang_name:
            continue
        counts[lang_name] = counts.get(lang_name, 0) + 1
    if counts:
        return max(counts.items(), key=lambda item: item[1])[0]
    return None


def _import_based_mapping(
    graph: dict,
    test_files: set[str],
    production_files: set[str],
    lang_name: str | None = None,
) -> set[str]:
    """Map test files to production files via import edges."""
    lang_name = lang_name or _infer_lang_name(test_files, production_files)
    mod = _load_lang_test_coverage_module(lang_name)

    tested = set()

    # Build module-name->path index for resolving test imports.
    prod_by_module: dict[str, str] = {}
    root_str = str(PROJECT_ROOT) + os.sep
    for pf in production_files:
        rel_pf = pf[len(root_str) :] if pf.startswith(root_str) else pf
        module_name = rel_pf.replace("/", ".").replace("\\", ".")
        if "." in module_name:
            module_name = module_name.rsplit(".", 1)[0]
        prod_by_module[module_name] = pf

        # __init__.py: also map package path (e.g. "foo.bar" -> __init__.py).
        if module_name.endswith(".__init__"):
            prod_by_module[module_name[: -len(".__init__")]] = pf

        parts = module_name.split(".")
        if parts:
            prod_by_module[parts[-1]] = pf

    for tf in test_files:
        entry = graph.get(tf)
        graph_mapped = set()
        if entry is not None:
            for imp in entry.get("imports", set()):
                if imp in production_files:
                    graph_mapped.add(imp)
            tested |= graph_mapped

        # Parse source imports as a supplement when graph imports are absent,
        # or always for TypeScript where dynamic import('...') is common in
        # coverage smoke tests and may be missed by static graph building.
        if not graph_mapped or lang_name == "typescript":
            tested |= _parse_test_imports(
                tf, production_files, prod_by_module, lang_name
            )

    barrel_basenames = getattr(mod, "BARREL_BASENAMES", set())
    if barrel_basenames:
        barrel_files = [f for f in tested if os.path.basename(f) in barrel_basenames]
        for bf in barrel_files:
            tested |= _resolve_barrel_reexports(bf, production_files, lang_name)

    # Facade expansion: if a directly-tested file has no testable logic (pure
    # re-export facade), promote its imports to directly tested.  This prevents
    # false "transitive_only" findings for internal modules behind facades like
    # scoring.py -> _scoring/policy/core.py.
    has_logic = getattr(mod, "has_testable_logic", None)
    if callable(has_logic):
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
        tested |= facade_targets

    return tested


def _resolve_import(
    spec: str,
    test_path: str,
    production_files: set[str],
    lang_name: str | None,
) -> str | None:
    mod = _load_lang_test_coverage_module(lang_name)
    resolver = getattr(mod, "resolve_import_spec", None)
    if callable(resolver):
        return resolver(spec, test_path, production_files)
    return None


def _resolve_barrel_reexports(
    filepath: str,
    production_files: set[str],
    lang_name: str | None = None,
) -> set[str]:
    """Resolve one-hop re-exports using language-specific helpers."""
    if lang_name is None:
        lang_name = _infer_lang_name({filepath}, production_files)
    mod = _load_lang_test_coverage_module(lang_name)
    resolver = getattr(mod, "resolve_barrel_reexports", None)
    if callable(resolver):
        return resolver(filepath, production_files)
    return set()


def _parse_test_imports(
    test_path: str,
    production_files: set[str],
    prod_by_module: dict[str, str],
    lang_name: str | None = None,
) -> set[str]:
    """Parse import statements from a test file and resolve production files."""
    tested = set()
    read_result = read_coverage_file(test_path, context="coverage_import_mapping_parse")
    if not read_result.ok:
        return tested
    content = read_result.content

    if lang_name is None:
        lang_name = _infer_lang_name({test_path}, production_files)

    mod = _load_lang_test_coverage_module(lang_name)
    parse_specs = getattr(mod, "parse_test_import_specs", None)
    if not callable(parse_specs):
        return tested

    for spec in parse_specs(content):
        if not spec:
            continue

        resolved = _resolve_import(spec, test_path, production_files, lang_name)
        if resolved:
            tested.add(resolved)
            continue

        # Fallback: module-name lookup with progressively shorter prefixes.
        cleaned = spec.lstrip("./").replace("/", ".")
        parts = cleaned.split(".")
        for i in range(len(parts), 0, -1):
            candidate = ".".join(parts[:i])
            if candidate in prod_by_module:
                tested.add(prod_by_module[candidate])
                break

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


def _naming_based_mapping(
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


def _strip_test_markers(basename: str, lang_name: str) -> str | None:
    """Strip test naming markers from a basename to derive source basename."""
    mod = _load_lang_test_coverage_module(lang_name)
    strip_markers = getattr(mod, "strip_test_markers", None)
    if callable(strip_markers):
        return strip_markers(basename)
    return None


def _transitive_coverage(
    directly_tested: set[str],
    graph: dict,
    production_files: set[str],
) -> set[str]:
    """BFS from directly-tested files through dep-graph imports."""
    visited = set(directly_tested)
    queue = deque(directly_tested)

    while queue:
        current = queue.popleft()
        entry = graph.get(current)
        if entry is None:
            continue
        for imp in entry.get("imports", set()):
            if imp in production_files and imp not in visited:
                visited.add(imp)
                queue.append(imp)

    return visited - directly_tested


def _analyze_test_quality(
    test_files: set[str],
    lang_name: str,
) -> dict[str, dict]:
    """Analyze test quality per file."""
    mod = _load_lang_test_coverage_module(lang_name)
    assert_pats = list(getattr(mod, "ASSERT_PATTERNS", []) or [])
    mock_pats = list(getattr(mod, "MOCK_PATTERNS", []) or [])
    snapshot_pats = list(getattr(mod, "SNAPSHOT_PATTERNS", []) or [])
    test_func_re = getattr(mod, "TEST_FUNCTION_RE", re.compile(r"$^"))
    strip_comments = getattr(mod, "strip_comments", None)
    placeholder_classifier = getattr(mod, "is_placeholder_test", None)

    if not hasattr(test_func_re, "findall"):
        test_func_re = re.compile(r"$^")
    if not callable(strip_comments):

        def strip_comments(text: str) -> str:
            return text
    if not callable(placeholder_classifier):

        def placeholder_classifier(
            _content: str, *, assertions: int, test_functions: int
        ) -> bool:
            return False

    quality_map: dict[str, dict] = {}

    for tf in test_files:
        read_result = read_coverage_file(tf, context="coverage_quality_analysis")
        if not read_result.ok:
            continue
        content = read_result.content

        stripped = strip_comments(content)
        lines = stripped.splitlines()

        assertions = sum(
            1 for line in lines if any(pat.search(line) for pat in assert_pats)
        )
        mocks = sum(1 for line in lines if any(pat.search(line) for pat in mock_pats))
        snapshots = sum(
            1 for line in lines if any(pat.search(line) for pat in snapshot_pats)
        )
        test_functions = len(test_func_re.findall(stripped))
        try:
            is_placeholder = bool(
                placeholder_classifier(
                    stripped, assertions=assertions, test_functions=test_functions
                )
            )
        except TypeError as exc:
            logger.debug(
                "Best-effort fallback failed while trying to classify placeholder "
                "test quality for %s: %s",
                tf,
                exc,
            )
            is_placeholder = False

        if test_functions == 0:
            quality = "no_tests"
        elif assertions == 0:
            quality = "assertion_free"
        elif is_placeholder:
            quality = "placeholder_smoke"
        elif mocks > assertions:
            quality = "over_mocked"
        elif snapshots > 0 and snapshots > assertions * 0.5:
            quality = "snapshot_heavy"
        elif test_functions > 0 and assertions / test_functions < 1:
            quality = "smoke"
        elif assertions / test_functions >= 3:
            quality = "thorough"
        else:
            quality = "adequate"

        quality_map[tf] = {
            "assertions": assertions,
            "mocks": mocks,
            "test_functions": test_functions,
            "snapshots": snapshots,
            "placeholder": is_placeholder,
            "quality": quality,
        }

    return quality_map


def _get_test_files_for_prod(
    prod_file: str,
    test_files: set[str],
    graph: dict,
    lang_name: str,
    parsed_imports_by_test: dict[str, set[str]] | None = None,
) -> list[str]:
    """Find which test files exercise a given production file."""
    parsed_imports_by_test = parsed_imports_by_test or {}
    root_str = str(PROJECT_ROOT) + os.sep
    rel_prod = prod_file[len(root_str):] if prod_file.startswith(root_str) else prod_file
    module_name = rel_prod.replace("/", ".").replace("\\", ".")
    if "." in module_name:
        module_name = module_name.rsplit(".", 1)[0]
    prod_by_module: dict[str, str] = {module_name: prod_file}
    parts = module_name.split(".")
    if parts:
        prod_by_module[parts[-1]] = prod_file

    result = []
    for tf in test_files:
        entry = graph.get(tf)
        if entry and prod_file in entry.get("imports", set()):
            result.append(tf)
            continue
        parsed = parsed_imports_by_test.get(tf)
        if parsed is None:
            parsed = _parse_test_imports(tf, {prod_file}, prod_by_module, lang_name)
        if prod_file in parsed:
            result.append(tf)
            continue
        if _map_test_to_source(tf, {prod_file}, lang_name) == prod_file:
            result.append(tf)
    return result


def _build_test_import_index(
    test_files: set[str],
    production_files: set[str],
    lang_name: str,
) -> dict[str, set[str]]:
    """Parse test import sources once, producing a test->production import index."""
    root_str = str(PROJECT_ROOT) + os.sep
    prod_by_module: dict[str, str] = {}
    for pf in production_files:
        rel_pf = pf[len(root_str):] if pf.startswith(root_str) else pf
        module_name = rel_pf.replace("/", ".").replace("\\", ".")
        if "." in module_name:
            module_name = module_name.rsplit(".", 1)[0]
        prod_by_module[module_name] = pf
        if module_name.endswith(".__init__"):
            prod_by_module[module_name[: -len(".__init__")]] = pf
        parts = module_name.split(".")
        if parts:
            prod_by_module[parts[-1]] = pf

    index: dict[str, set[str]] = {}
    for tf in test_files:
        index[tf] = _parse_test_imports(tf, production_files, prod_by_module, lang_name)
    return index
