"""Cross-module private import detection for Python."""

from __future__ import annotations

import ast
import logging
import os
from pathlib import Path

from desloppify.engine.policy.zones import EXCLUDED_ZONES, Zone
from desloppify.file_discovery import rel
from desloppify.file_discovery import read_file_text

logger = logging.getLogger(__name__)


def _is_dunder(name: str) -> bool:
    """True for __dunder__ names (legitimate cross-module access)."""
    return name.startswith("__") and name.endswith("__")


def _module_of(filepath: str) -> str:
    """Return the immediate parent package (directory) of a file."""
    return os.path.dirname(filepath)


def _same_package(file_a: str, file_b: str) -> bool:
    """True if two files share the same immediate parent directory."""
    return _module_of(file_a) == _module_of(file_b)


def _is_conftest_import(source_file: str, target_file: str) -> bool:
    """True if a test file imports from conftest (legitimate)."""
    return os.path.basename(target_file) == "conftest.py"


def _is_test_file(filepath: str) -> bool:
    """True when a file path clearly points to test code."""
    normalized = filepath.replace("\\", "/")
    basename = os.path.basename(normalized)
    if basename.startswith("test_") or basename.endswith("_test.py"):
        return True
    markers = ("/tests/", "/test/", "/__tests__/", "/fixtures/")
    padded = f"/{normalized}/"
    return any(marker in padded for marker in markers)


def detect_private_imports(
    dep_graph: dict,
    zone_map=None,
    file_finder=None,
    path: Path | None = None,
) -> tuple[list[dict], int]:
    """Find _private symbols imported across module boundaries."""
    del file_finder, path
    entries: list[dict] = []
    files_checked = 0
    project_files = set(dep_graph.keys()) if dep_graph else set()

    for filepath in dep_graph:
        if not filepath.endswith(".py"):
            continue
        if _is_test_file(filepath):
            continue

        basename = os.path.basename(filepath)
        is_test = basename.startswith("test_") or basename.endswith("_test.py")

        if zone_map is not None:
            zone = zone_map.get(filepath)
            if zone == Zone.PRODUCTION:
                zone = zone_map.get(rel(filepath))
            if zone in EXCLUDED_ZONES:
                continue

        content = read_file_text(filepath)
        if content is None:
            continue

        files_checked += 1

        try:
            tree = ast.parse(content, filename=filepath)
        except SyntaxError as exc:
            logger.debug(
                "Skipping unparseable python file %s in private-import detector: %s",
                filepath,
                exc,
            )
            continue

        for ast_node in ast.walk(tree):
            if isinstance(ast_node, ast.ImportFrom):
                if ast_node.module is None or ast_node.names is None:
                    continue

                target_files = _resolve_import_target(
                    filepath,
                    ast_node.module,
                    project_files,
                    dep_graph,
                )

                for alias in ast_node.names:
                    name = alias.name
                    if not name.startswith("_") or _is_dunder(name):
                        continue

                    for target in target_files:
                        if _same_package(filepath, target):
                            continue
                        if is_test and _is_conftest_import(filepath, target):
                            continue

                        rfile = rel(filepath)
                        rtarget = rel(target)
                        entries.append(
                            {
                                "file": rfile,
                                "name": f"{name}::from::{rtarget}",
                                "tier": 3,
                                "confidence": "medium",
                                "summary": (
                                    f"Cross-module private import: `{name}` "
                                    f"from {rtarget}"
                                ),
                                "detail": {
                                    "symbol": name,
                                    "source_file": rfile,
                                    "target_file": rtarget,
                                    "source_module": ast_node.module,
                                },
                            }
                        )

    return entries, files_checked


def _resolve_import_target(
    source_file: str,
    module_path: str,
    project_files: set[str] | None,
    dep_graph: dict,
) -> list[str]:
    """Resolve a dotted import path to project file(s)."""
    source_imports = dep_graph.get(source_file, {}).get("imports", set())
    if not source_imports:
        return []

    parts = module_path.split(".")
    candidates = []
    for i in range(len(parts)):
        candidates.append("/".join(parts[i:]))

    matches = []
    for imp_file in source_imports:
        if project_files is not None and imp_file not in project_files:
            continue
        for frag in candidates:
            if frag in imp_file:
                matches.append(imp_file)
                break

    return matches
