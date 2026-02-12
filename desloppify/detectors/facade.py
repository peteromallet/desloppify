"""Re-export facade detection: files/directories that only re-export from elsewhere.

Common after file decomposition refactors — the old file is left behind with
just `from new_location import *` statements. With few importers, these are
unnecessary indirection that should be cleaned up.
"""

import ast
import re
from pathlib import Path

from ..utils import rel


def _is_py_facade(filepath: str) -> dict | None:
    """Check if a Python file is a pure re-export facade.

    Returns {"imports_from": list[str], "loc": int} or None.
    """
    try:
        content = Path(filepath).read_text()
        tree = ast.parse(content)
    except (OSError, SyntaxError, UnicodeDecodeError):
        return None

    if not tree.body:
        return None

    imports_from: list[str] = []
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                imports_from.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    imports_from.append(alias.name)
        elif isinstance(node, ast.Expr) and isinstance(node.value, (ast.Constant, ast.JoinedStr)):
            continue  # docstring
        elif isinstance(node, ast.Assign):
            # Allow __all__ = [...] assignments
            if (len(node.targets) == 1
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == "__all__"):
                continue
            return None  # has real code
        else:
            return None  # has non-import code

    if not imports_from:
        return None

    loc = len(content.splitlines())
    return {"imports_from": imports_from, "loc": loc}


def _is_ts_facade(filepath: str) -> dict | None:
    """Check if a TypeScript file is a pure re-export facade.

    Returns {"imports_from": list[str], "loc": int} or None.
    """
    try:
        content = Path(filepath).read_text()
        lines = content.splitlines()
    except (OSError, UnicodeDecodeError):
        return None

    if not lines:
        return None

    imports_from: list[str] = []
    export_re = re.compile(r"""^export\s+(?:\{[^}]*\}|\*)\s+from\s+['"]([^'"]+)['"]""")
    reexport_re = re.compile(r"""^export\s+(?:type\s+)?\{[^}]*\}\s+from\s+['"]([^'"]+)['"]""")

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*"):
            continue

        m = export_re.match(stripped) or reexport_re.match(stripped)
        if m:
            imports_from.append(m.group(1))
            continue

        # Not a re-export line
        return None

    if not imports_from:
        return None

    return {"imports_from": imports_from, "loc": len(lines)}


def detect_reexport_facades(
    graph: dict,
    *,
    lang: str,
    max_importers: int = 2,
    file_finder=None,
    path=None,
) -> tuple[list[dict], int]:
    """Detect re-export facade files and directories.

    Args:
        graph: Dependency graph from build_dep_graph.
        lang: "python" or "typescript".
        max_importers: Max importers for a file to be flagged (default: 2).
        file_finder: Function to find source files (for total count).
        path: Root path for scanning.

    Returns:
        (entries, total_files_checked). Each entry:
        {"file": str, "loc": int, "importers": int, "imports_from": list[str],
         "kind": "file"|"directory"}
    """
    is_facade = _is_py_facade if lang == "python" else _is_ts_facade
    entries: list[dict] = []
    total_checked = 0

    for filepath in graph:
        total_checked += 1
        importer_count = graph[filepath].get("importer_count", 0)

        if importer_count > max_importers:
            continue

        result = is_facade(filepath)
        if result:
            entries.append({
                "file": filepath,
                "loc": result["loc"],
                "importers": importer_count,
                "imports_from": result["imports_from"],
                "kind": "file",
            })

    # Phase 2: Detect facade directories (packages where __init__.py is a facade
    # and all sub-modules are also facades or don't exist)
    if lang == "python":
        facade_files = {e["file"] for e in entries}
        _detect_facade_directories(graph, facade_files, entries, max_importers)

    return sorted(entries, key=lambda e: (e["kind"], e["importers"], -e["loc"])), total_checked


def _detect_facade_directories(
    graph: dict, facade_files: set[str], entries: list[dict],
    max_importers: int,
):
    """Detect Python package directories where all modules are facades."""
    # Group files by directory
    by_dir: dict[str, list[str]] = {}
    for filepath in graph:
        parent = str(Path(filepath).parent)
        by_dir.setdefault(parent, []).append(filepath)

    for dirpath, files in by_dir.items():
        init_file = str(Path(dirpath) / "__init__.py")
        if init_file not in graph:
            continue

        # Check if __init__.py is a facade
        if init_file not in facade_files:
            continue

        # Check if ALL files in this directory are facades
        non_init_files = [f for f in files if not f.endswith("__init__.py")]
        if not non_init_files:
            continue  # just __init__.py — that's a normal barrel file, not a facade dir

        all_facades = all(f in facade_files for f in non_init_files)
        if not all_facades:
            continue

        # Count importers of the directory (importers of __init__.py)
        dir_importers = graph[init_file].get("importer_count", 0)
        if dir_importers > max_importers:
            continue

        total_loc = sum(
            len(Path(f).read_text().splitlines())
            for f in files
            if Path(f).exists()
        )

        entries.append({
            "file": dirpath,
            "loc": total_loc,
            "importers": dir_importers,
            "imports_from": [],  # aggregated from sub-modules
            "kind": "directory",
            "file_count": len(files),
        })
