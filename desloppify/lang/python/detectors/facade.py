"""Python facade detection helpers."""

from __future__ import annotations

import ast
from pathlib import Path


def is_py_facade(filepath: str) -> dict | None:
    """Check if a Python file is a pure re-export facade."""
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
            continue
        elif isinstance(node, ast.Assign):
            if (
                len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "__all__"
            ):
                continue
            return None
        else:
            return None

    if not imports_from:
        return None

    loc = len(content.splitlines())
    return {"imports_from": imports_from, "loc": loc}


def detect_reexport_facades(
    graph: dict,
    *,
    max_importers: int = 2,
) -> tuple[list[dict], int]:
    """Detect Python re-export facade files and directories."""
    entries: list[dict] = []
    total_checked = 0

    for filepath in graph:
        total_checked += 1
        importer_count = graph[filepath].get("importer_count", 0)
        if importer_count > max_importers:
            continue

        result = is_py_facade(filepath)
        if result:
            entries.append(
                {
                    "file": filepath,
                    "loc": result["loc"],
                    "importers": importer_count,
                    "imports_from": result["imports_from"],
                    "kind": "file",
                }
            )

    facade_files = {e["file"] for e in entries}
    _detect_facade_directories(graph, facade_files, entries, max_importers)
    return sorted(entries, key=lambda e: (e["kind"], e["importers"], -e["loc"])), total_checked


def _detect_facade_directories(
    graph: dict, facade_files: set[str], entries: list[dict],
    max_importers: int,
):
    """Detect Python package directories where all modules are facades."""
    by_dir: dict[str, list[str]] = {}
    for filepath in graph:
        parent = str(Path(filepath).parent)
        by_dir.setdefault(parent, []).append(filepath)

    for dirpath, files in by_dir.items():
        init_file = str(Path(dirpath) / "__init__.py")
        if init_file not in graph or init_file not in facade_files:
            continue

        non_init_files = [f for f in files if not f.endswith("__init__.py")]
        if not non_init_files:
            continue
        if not all(f in facade_files for f in non_init_files):
            continue

        dir_importers = graph[init_file].get("importer_count", 0)
        if dir_importers > max_importers:
            continue

        total_loc = sum(
            len(Path(f).read_text().splitlines())
            for f in files
            if Path(f).exists()
        )

        entries.append(
            {
                "file": dirpath,
                "loc": total_loc,
                "importers": dir_importers,
                "imports_from": [],
                "kind": "directory",
                "file_count": len(files),
            }
        )

