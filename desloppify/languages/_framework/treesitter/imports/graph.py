"""Shared import graph construction utilities for tree-sitter backends."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from desloppify.base.discovery.file_paths import resolve_scan_file

from ..analysis.extractors import _get_parser, _make_query, _run_query, _unwrap_node
from .cache import get_or_parse_tree

if TYPE_CHECKING:
    from desloppify.languages._framework.treesitter import TreeSitterLangSpec


def _source_path(filepath: str) -> Path:
    """Resolve discovery keys against the project root without changing case."""
    return resolve_scan_file(filepath)


def _import_path(filepath: str, scan_path: Path) -> Path:
    """Resolve a resolver result using its scan-root-relative contract."""
    path = Path(filepath)
    if path.is_absolute():
        return path.resolve()
    return (scan_path / path).resolve()


def _path_identity(path: Path) -> str:
    """Return a comparison identity without changing the path used for I/O."""
    return os.path.normcase(str(path))


def ts_build_dep_graph(
    path: Path,
    spec: TreeSitterLangSpec,
    file_list: list[str],
) -> dict[str, dict[str, Any]]:
    """Build a dependency graph by parsing imports with tree-sitter.

    Returns the same shape as Python/TS dep graphs:
    {file: {"imports": set[str], "importers": set[str], "import_count": int, "importer_count": int}}
    """
    if not spec.import_query or not spec.resolve_import:
        return {}

    parser, language = _get_parser(spec.grammar)
    query = _make_query(language, spec.import_query)

    scan_path = path.resolve()
    file_paths_by_key = {filepath: _source_path(filepath) for filepath in file_list}
    file_keys_by_path: dict[str, str] = {}
    for filepath, resolved_path in file_paths_by_key.items():
        identity = _path_identity(resolved_path)
        previous_key = file_keys_by_path.get(identity)
        if previous_key is not None and previous_key != filepath:
            raise ValueError(
                "Tree-sitter dependency graph received duplicate paths "
                f"{previous_key!r} and {filepath!r} for {resolved_path}"
            )
        file_keys_by_path[identity] = filepath
    graph: dict[str, dict[str, Any]] = {}

    # Initialize all files in the graph.
    for f in file_list:
        graph[f] = {"imports": set(), "importers": set()}

    for filepath in file_list:
        source_path = file_paths_by_key[filepath]
        cached = get_or_parse_tree(str(source_path), parser, spec.grammar)
        if cached is None:
            continue
        _source, tree = cached
        matches = _run_query(query, tree.root_node)

        for _pattern_idx, captures in matches:
            path_node = _unwrap_node(captures.get("path"))
            if not path_node:
                continue

            raw_text = path_node.text
            import_text = (
                raw_text.decode("utf-8", errors="replace")
                if isinstance(raw_text, bytes)
                else str(raw_text)
            )

            # Strip surrounding quotes if present.
            import_text = import_text.strip("\"'`")

            # Prepend group-use prefix when present (PHP ``use A\B\{C, D}``).
            prefix_node = _unwrap_node(captures.get("prefix"))
            if prefix_node is not None:
                prefix_raw = prefix_node.text
                prefix_text = (
                    prefix_raw.decode("utf-8", errors="replace")
                    if isinstance(prefix_raw, bytes)
                    else str(prefix_raw)
                ).strip("\"'`")
                import_text = f"{prefix_text}\\{import_text}"

            resolved = spec.resolve_import(
                import_text, str(source_path), str(scan_path)
            )
            if resolved is None:
                continue

            # Match by filesystem identity, then store the caller's original key.
            resolved_key = file_keys_by_path.get(
                _path_identity(_import_path(resolved, scan_path))
            )
            if resolved_key is None:
                continue

            graph[filepath]["imports"].add(resolved_key)
            graph[resolved_key]["importers"].add(filepath)

    # Finalize: add counts.
    for data in graph.values():
        data["import_count"] = len(data["imports"])
        data["importer_count"] = len(data["importers"])

    return graph


def make_ts_dep_builder(
    spec: TreeSitterLangSpec,
    file_finder: Callable[[Path], list[str]],
) -> Callable[[Path], dict[str, dict[str, Any]]]:
    """Create a dep graph builder bound to a TreeSitterLangSpec + file finder.

    Returns a callable with signature (path: Path) -> dict,
    matching the contract expected by LangConfig.build_dep_graph.
    """

    def build(path: Path) -> dict[str, dict[str, Any]]:
        file_list = file_finder(path)
        return ts_build_dep_graph(path, spec, file_list)

    return build


__all__ = ["make_ts_dep_builder", "ts_build_dep_graph"]
