"""Responsibility cohesion detector for dumping-ground modules."""

from __future__ import annotations

import ast
from pathlib import Path

from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import find_py_files


def _extract_top_level_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    return [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _collect_import_alias_roots(tree: ast.Module) -> dict[str, str]:
    alias_roots: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                local = alias.asname or alias.name.split(".")[0]
                alias_roots[local] = alias.name.split(".")[0]
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            for alias in node.names:
                local = alias.asname or alias.name
                alias_roots[local] = module or alias.name.split(".")[0]
    return alias_roots


def _function_calls(fn: ast.FunctionDef | ast.AsyncFunctionDef, function_names: set[str]) -> set[str]:
    calls: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id in function_names and node.func.id != fn.name:
                calls.add(node.func.id)
    return calls


def _function_import_roots(
    fn: ast.FunctionDef | ast.AsyncFunctionDef, alias_roots: dict[str, str]
) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Name):
            root = alias_roots.get(node.id)
            if root:
                roots.add(root)
    return roots


def _connected_components(function_names: list[str], adjacency: dict[str, set[str]]) -> list[list[str]]:
    unvisited = set(function_names)
    comps: list[list[str]] = []
    while unvisited:
        seed = next(iter(unvisited))
        stack = [seed]
        comp: list[str] = []
        unvisited.remove(seed)
        while stack:
            name = stack.pop()
            comp.append(name)
            for neighbor in adjacency.get(name, set()):
                if neighbor not in unvisited:
                    continue
                unvisited.remove(neighbor)
                stack.append(neighbor)
        comps.append(sorted(comp))
    comps.sort(key=lambda c: (-len(c), c[0]))
    return comps


def _name_family(name: str) -> str:
    return name.split("_", 1)[0] if "_" in name else name


def detect_responsibility_cohesion(
    path: Path,
    *,
    min_loc: int = 200,
    min_functions: int = 8,
) -> tuple[list[dict], int]:
    """Detect large modules that split into disconnected responsibility clusters."""
    entries: list[dict] = []
    candidates = 0

    for filepath in find_py_files(path):
        full = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
        try:
            source = full.read_text()
            tree = ast.parse(source)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            # Preserve parse/read context while intentionally skipping broken files.
            _ = (full, exc)
            continue

        loc = len(source.splitlines())
        if loc < min_loc:
            continue

        functions = _extract_top_level_functions(tree)
        if len(functions) < min_functions:
            continue
        candidates += 1

        function_names = [fn.name for fn in functions]
        function_name_set = set(function_names)
        alias_roots = _collect_import_alias_roots(tree)

        adjacency: dict[str, set[str]] = {name: set() for name in function_names}
        import_clusters: dict[str, set[str]] = {}
        families: dict[str, set[str]] = {}

        for fn in functions:
            calls = _function_calls(fn, function_name_set)
            for callee in calls:
                adjacency[fn.name].add(callee)
                adjacency[callee].add(fn.name)
            import_roots = _function_import_roots(fn, alias_roots)
            import_clusters[fn.name] = import_roots
            families.setdefault(_name_family(fn.name), set()).add(fn.name)

        components = _connected_components(function_names, adjacency)
        comp_sizes = [len(comp) for comp in components]
        largest = max(comp_sizes) if comp_sizes else 0
        family_count = len(families)

        non_empty_import_sets = {
            tuple(sorted(roots)) for roots in import_clusters.values() if roots
        }
        import_cluster_count = len(non_empty_import_sets)

        has_disconnected_clusters = len(components) >= 3 and largest <= int(
            len(functions) * 0.65
        )
        has_mixed_families = family_count >= 4 and len(components) >= 2
        has_import_divergence = import_cluster_count >= 3 and len(components) >= 2
        if not (has_disconnected_clusters or has_mixed_families or has_import_divergence):
            continue

        entries.append(
            {
                "file": filepath,
                "loc": loc,
                "function_count": len(functions),
                "component_count": len(components),
                "component_sizes": comp_sizes,
                "family_count": family_count,
                "import_cluster_count": import_cluster_count,
                "families": sorted(families.keys())[:8],
            }
        )

    entries.sort(
        key=lambda item: (
            -item["component_count"],
            -item["family_count"],
            -item["function_count"],
            item["file"],
        )
    )
    return entries, candidates


__all__ = ["detect_responsibility_cohesion"]
