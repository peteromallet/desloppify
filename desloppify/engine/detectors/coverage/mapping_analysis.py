"""Analysis helpers extracted from coverage mapping orchestration."""

from __future__ import annotations

import logging
import os
from collections import deque
from collections.abc import Callable
from typing import Any


def transitive_coverage(
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
        for imported in entry.get("imports", set()):
            if imported in production_files and imported not in visited:
                visited.add(imported)
                queue.append(imported)

    return visited - directly_tested


def analyze_test_quality(
    test_files: set[str],
    lang_name: str,
    *,
    load_lang_module: Callable[[str], object],
    read_coverage_file_fn: Callable[..., Any],
    logger: logging.Logger,
) -> dict[str, dict]:
    """Analyze test quality per file using language-specific heuristics."""
    mod = load_lang_module(lang_name)
    assert_pats = list(getattr(mod, "ASSERT_PATTERNS", []) or [])
    mock_pats = list(getattr(mod, "MOCK_PATTERNS", []) or [])
    snapshot_pats = list(getattr(mod, "SNAPSHOT_PATTERNS", []) or [])
    test_func_re = getattr(mod, "TEST_FUNCTION_RE", None)
    strip_comments = getattr(mod, "strip_comments", None)
    placeholder_classifier = getattr(mod, "is_placeholder_test", None)

    if test_func_re is None or not hasattr(test_func_re, "findall"):
        import re

        test_func_re = re.compile(r"$^")
    if not callable(strip_comments):

        def strip_comments(text: str) -> str:
            return text
    if not callable(placeholder_classifier):

        def placeholder_classifier(
            _content: str, *, assertions: int, test_functions: int
        ) -> bool:
            _ = assertions
            _ = test_functions
            return False

    quality_map: dict[str, dict] = {}

    for test_path in test_files:
        read_result = read_coverage_file_fn(
            test_path,
            context="coverage_quality_analysis",
        )
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
                    stripped,
                    assertions=assertions,
                    test_functions=test_functions,
                )
            )
        except TypeError as exc:
            logger.debug(
                "Best-effort fallback failed while trying to classify placeholder "
                "test quality for %s: %s",
                test_path,
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

        quality_map[test_path] = {
            "assertions": assertions,
            "mocks": mocks,
            "test_functions": test_functions,
            "snapshots": snapshots,
            "placeholder": is_placeholder,
            "quality": quality,
        }

    return quality_map


def _build_prod_by_module(
    production_files: set[str],
    *,
    project_root: str,
) -> dict[str, str]:
    """Build module lookup map for production files."""
    root_str = project_root + os.sep
    prod_by_module: dict[str, str] = {}
    ambiguous_aliases: set[str] = set()

    def assign_alias(alias: str, prod_file: str) -> None:
        if not alias or alias in ambiguous_aliases:
            return
        existing = prod_by_module.get(alias)
        if existing is None or existing == prod_file:
            prod_by_module[alias] = prod_file
            return
        ambiguous_aliases.add(alias)
        prod_by_module.pop(alias, None)

    for prod_file in production_files:
        rel_path = (
            prod_file[len(root_str) :]
            if prod_file.startswith(root_str)
            else prod_file
        )
        # Strip src/ prefix so src-layout projects map correctly
        # (e.g. 'src/argos_toolkit/foo.py' -> 'argos_toolkit.foo')
        if rel_path.startswith("src/") or rel_path.startswith("src\\"):
            rel_path = rel_path[4:]
        module_name = rel_path.replace("/", ".").replace("\\", ".")
        if "." in module_name:
            module_name = module_name.rsplit(".", 1)[0]
        assign_alias(module_name, prod_file)
        if module_name.endswith(".__init__"):
            assign_alias(module_name[: -len(".__init__")], prod_file)
        parts = module_name.split(".")
        if parts:
            assign_alias(parts[-1], prod_file)
    return prod_by_module


def get_test_files_for_prod(
    prod_file: str,
    test_files: set[str],
    graph: dict,
    lang_name: str,
    parsed_imports_by_test: dict[str, set[str]] | None,
    *,
    parse_test_imports_fn: Callable[[str, set[str], dict[str, str], str], set[str]],
    map_test_to_source_fn: Callable[[str, set[str], str], str | None],
    project_root: str,
) -> list[str]:
    """Find which test files exercise a given production file."""
    parsed_imports_by_test = parsed_imports_by_test or {}
    root_str = project_root + os.sep
    rel_prod = prod_file[len(root_str) :] if prod_file.startswith(root_str) else prod_file
    module_name = rel_prod.replace("/", ".").replace("\\", ".")
    if "." in module_name:
        module_name = module_name.rsplit(".", 1)[0]
    prod_by_module: dict[str, str] = {module_name: prod_file}
    parts = module_name.split(".")
    if parts:
        prod_by_module[parts[-1]] = prod_file

    result: list[str] = []
    for test_path in test_files:
        entry = graph.get(test_path)
        if entry and prod_file in entry.get("imports", set()):
            result.append(test_path)
            continue
        parsed = parsed_imports_by_test.get(test_path)
        if parsed is None:
            parsed = parse_test_imports_fn(
                test_path,
                {prod_file},
                prod_by_module,
                lang_name,
            )
        if prod_file in parsed:
            result.append(test_path)
            continue
        if map_test_to_source_fn(test_path, {prod_file}, lang_name) == prod_file:
            result.append(test_path)
    return result


def build_test_import_index(
    test_files: set[str],
    production_files: set[str],
    lang_name: str,
    *,
    parse_test_imports_fn: Callable[[str, set[str], dict[str, str], str], set[str]],
    project_root: str,
) -> dict[str, set[str]]:
    """Parse test import sources once, producing a test->production import index."""
    prod_by_module = _build_prod_by_module(
        production_files,
        project_root=project_root,
    )
    index: dict[str, set[str]] = {}
    for test_path in test_files:
        index[test_path] = parse_test_imports_fn(
            test_path,
            production_files,
            prod_by_module,
            lang_name,
        )
    return index



__all__ = [
    "analyze_test_quality",
    "build_test_import_index",
    "get_test_files_for_prod",
    "transitive_coverage",
]
