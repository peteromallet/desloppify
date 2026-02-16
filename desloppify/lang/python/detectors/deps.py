"""Python import graph builder — parses import/from statements, resolves to files."""

from __future__ import annotations

import ast
from collections import defaultdict
from pathlib import Path
from typing import Any

from ....utils import PROJECT_ROOT, resolve_path
from ....detectors.graph import finalize_graph


def build_dep_graph(path: Path) -> dict[str, dict[str, Any]]:
    """Build a dependency graph for Python files.

    Uses ast.parse for reliable import extraction (handles multi-line imports,
    parenthesized imports, aliases, etc.).

    Returns {resolved_path: {"imports": set, "importers": set, "import_count", "importer_count"}}
    """
    from ....utils import find_py_files
    py_files = find_py_files(path)

    graph: dict[str, dict] = defaultdict(lambda: {
        "imports": set(), "importers": set(), "deferred_imports": set(),
    })

    for filepath in py_files:
        abs_path = filepath if Path(filepath).is_absolute() else str(PROJECT_ROOT / filepath)
        try:
            content = Path(abs_path).read_text()
            tree = ast.parse(content)
        except (OSError, UnicodeDecodeError, SyntaxError):
            continue

        source_resolved = resolve_path(filepath)
        graph[source_resolved]  # ensure entry

        # Collect top-level function/class line ranges to detect deferred imports
        top_level_scopes: list[tuple[int, int]] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                end = getattr(node, "end_lineno", node.lineno)
                top_level_scopes.append((node.lineno, end))

        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue

            is_deferred = any(start <= node.lineno <= end
                              for start, end in top_level_scopes)

            if isinstance(node, ast.ImportFrom):
                # Build module_path from level (dots) + module name
                dots = "." * (node.level or 0)
                module = node.module or ""
                module_path = dots + module

                # Resolve each imported name for dots-only imports (from . import X)
                if not module and node.level:
                    import_names = ", ".join(a.name for a in node.names)
                    targets = _resolve_python_from_import(module_path, import_names, filepath, path)
                else:
                    targets = _resolve_python_from_import(module_path, "", filepath, path)

                for target in targets:
                    graph[source_resolved]["imports"].add(target)
                    graph[target]["importers"].add(source_resolved)
                    if is_deferred:
                        graph[source_resolved]["deferred_imports"].add(target)

            elif isinstance(node, ast.Import):
                for alias in node.names:
                    target = _resolve_python_import(alias.name, filepath, path)
                    if target:
                        graph[source_resolved]["imports"].add(target)
                        graph[target]["importers"].add(source_resolved)
                        if is_deferred:
                            graph[source_resolved]["deferred_imports"].add(target)

    return finalize_graph(dict(graph))


def _resolve_python_from_import(module_path: str, import_names: str, source_file: str, scan_root: Path) -> list[str]:
    """Resolve a 'from X import Y' statement to file paths.

    When module_path is dots-only (e.g. 'from . import X, Y'), each imported
    name might be a submodule, so we resolve each name individually.
    Otherwise, resolve the module_path as before.
    """
    source = Path(source_file) if Path(source_file).is_absolute() else PROJECT_ROOT / source_file
    source_dir = source.parent
    scan_root_path = Path(scan_root) if not isinstance(scan_root, Path) else scan_root

    # Check if module_path is dots-only (no remainder after the dots)
    dots_only = all(ch == "." for ch in module_path)

    if dots_only:
        # from . import X, Y  or  from .. import X, Y
        # Each imported name could be a submodule in the base directory
        dots = len(module_path)
        base = source_dir
        for _ in range(dots - 1):
            base = base.parent

        results = []
        # Parse the import names (handle "X, Y" and "X as Z, Y as W")
        names = [n.strip().split()[0] for n in import_names.split(",")]
        for name in names:
            if not name or name.startswith("(") or name.startswith("#"):
                continue
            name = name.strip("()")
            if not name:
                continue
            # Try resolving as a submodule: base/name.py or base/name/__init__.py
            target = _try_resolve_path(base / name)
            if target:
                results.append(target)

        # Also resolve the package __init__.py itself (from . import X can pull from __init__)
        if not results:
            target = _try_resolve_path(base)
            if target:
                results.append(target)
        return results
    else:
        # Normal case: from .foo import bar, from ..foo.bar import baz
        target = _resolve_python_import(module_path, source_file, scan_root_path)
        return [target] if target else []


def _resolve_python_import(module_path: str, source_file: str, scan_root: Path) -> str | None:
    """Resolve a Python import to a file path.

    Handles:
      - Relative imports (starting with .)
      - Absolute imports within the project
    """
    source = Path(source_file) if Path(source_file).is_absolute() else PROJECT_ROOT / source_file
    source_dir = source.parent
    scan_root_path = Path(scan_root) if not isinstance(scan_root, Path) else scan_root

    if module_path.startswith("."):
        return _resolve_relative_import(module_path, source_dir)
    else:
        return _resolve_absolute_import(module_path, scan_root_path)


def _resolve_relative_import(module_path: str, source_dir: Path) -> str | None:
    """Resolve a relative Python import (from . import X, from .foo import X)."""
    # Count leading dots
    dots = 0
    for ch in module_path:
        if ch == ".":
            dots += 1
        else:
            break

    remainder = module_path[dots:]

    # Go up (dots - 1) directories from source_dir
    base = source_dir
    for _ in range(dots - 1):
        base = base.parent

    if remainder:
        parts = remainder.split(".")
        target_base = base
        for part in parts:
            target_base = target_base / part
    else:
        target_base = base

    return _try_resolve_path(target_base)


def _resolve_absolute_import(module_path: str, scan_root: Path) -> str | None:
    """Resolve an absolute Python import within the project."""
    parts = module_path.split(".")
    # Try from scan root
    target_base = scan_root.resolve()
    for part in parts:
        target_base = target_base / part

    resolved = _try_resolve_path(target_base)
    if resolved:
        return resolved

    # Try from project root
    target_base = PROJECT_ROOT
    for part in parts:
        target_base = target_base / part

    return _try_resolve_path(target_base)


def _try_resolve_path(target_base: Path) -> str | None:
    """Try to resolve a module base path to an actual file."""
    # foo.py
    candidate = Path(str(target_base) + ".py")
    if candidate.is_file():
        return str(candidate.resolve())

    # foo/__init__.py
    candidate = target_base / "__init__.py"
    if candidate.is_file():
        return str(candidate.resolve())

    # foo/ (directory with __init__.py)
    if target_base.is_dir():
        init = target_base / "__init__.py"
        if init.is_file():
            return str(init.resolve())

    return None
