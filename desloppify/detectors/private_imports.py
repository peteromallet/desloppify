"""Cross-module private import detection.

Detects _private symbols imported across module boundaries — a sign of
leaky abstractions that bypass the public API.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

from ..utils import rel, read_file_text


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


def detect_private_imports(
    dep_graph: dict,
    zone_map=None,
    file_finder=None,
    path: Path | None = None,
) -> tuple[list[dict], int]:
    """Find _private symbols imported across module boundaries.

    Uses AST to parse import statements and check for leading-underscore names
    imported from files in other packages.

    Returns (entries, total_files_checked).
    """
    entries: list[dict] = []
    files_checked = 0

    # Build a mapping of module paths in the project for resolution
    project_files: set[str] = set()
    if dep_graph:
        project_files = set(dep_graph.keys())

    for filepath, node in dep_graph.items():
        # Only check Python files
        if not filepath.endswith(".py"):
            continue

        # Skip test files importing from conftest
        basename = os.path.basename(filepath)
        is_test = basename.startswith("test_") or basename.endswith("_test.py")

        # Skip generated/vendor zones
        if zone_map is not None:
            from ..zones import EXCLUDED_ZONES
            zone = zone_map.get(filepath)
            if zone in EXCLUDED_ZONES:
                continue

        content = read_file_text(filepath)
        if content is None:
            continue

        files_checked += 1

        try:
            tree = ast.parse(content, filename=filepath)
        except SyntaxError:
            continue

        for ast_node in ast.walk(tree):
            if isinstance(ast_node, ast.ImportFrom):
                if ast_node.module is None or ast_node.names is None:
                    continue

                # Find which project file this import resolves to
                target_files = _resolve_import_target(
                    filepath, ast_node.module, project_files, dep_graph
                )

                for alias in ast_node.names:
                    name = alias.name
                    # Skip non-private and dunder names
                    if not name.startswith("_") or _is_dunder(name):
                        continue

                    for target in target_files:
                        # Skip same-package imports (intra-module access is fine)
                        if _same_package(filepath, target):
                            continue

                        # Skip test→conftest imports
                        if is_test and _is_conftest_import(filepath, target):
                            continue

                        rfile = rel(filepath)
                        rtarget = rel(target)
                        entries.append({
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
                        })

    return entries, files_checked


def _resolve_import_target(
    source_file: str,
    module_path: str,
    project_files: set[str],
    dep_graph: dict,
) -> list[str]:
    """Resolve a dotted import path to project file(s).

    Uses the dep graph's import edges to find which files the source imports,
    then filters to those matching the module path.
    """
    source_imports = dep_graph.get(source_file, {}).get("imports", set())
    if not source_imports:
        return []

    # Convert module path to possible file path fragments
    # e.g. "desloppify.narrative" → ["desloppify/narrative", "narrative"]
    parts = module_path.split(".")
    candidates = []
    for i in range(len(parts)):
        fragment = "/".join(parts[i:])
        candidates.append(fragment)

    matches = []
    for imp_file in source_imports:
        for frag in candidates:
            if frag in imp_file:
                matches.append(imp_file)
                break

    return matches
