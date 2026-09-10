"""Shared import graph construction utilities for tree-sitter backends."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .cache import get_or_parse_tree
from ..analysis.extractors import _get_parser, _make_query, _run_query, _unwrap_node

if TYPE_CHECKING:
    from desloppify.languages._framework.treesitter import TreeSitterLangSpec


def _node_text(node) -> str:
    raw = node.text
    return raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)


def _top_level_declaration_names(tree, name_query, root_type: str) -> list[str]:
    """Collect names of declarations sitting directly under the file root."""
    names: list[str] = []
    for _pattern_idx, captures in _run_query(name_query, tree.root_node):
        decl_node = _unwrap_node(captures.get("decl"))
        name_node = _unwrap_node(captures.get("name"))
        if decl_node is None or name_node is None:
            continue
        parent = decl_node.parent
        if parent is None or parent.type != root_type:
            continue
        name = _node_text(name_node)
        if len(name) >= 3:
            names.append(name)
    return names


def _augment_same_package_importers(
    graph: dict[str, dict[str, Any]],
    parser,
    language,
    spec: TreeSitterLangSpec,
) -> None:
    """Register same-package references as importers of the declaring file.

    JVM-style languages let files in one package use each other's top-level
    declarations without an import statement, so a purely import-based graph
    reports heavily-used DTOs and helpers as orphaned. References found here
    are recorded only as *importers* of the declaring file — never as outgoing
    imports of the referencing file — so cycle detection stays import-based.
    """
    package_source = getattr(spec, "package_query", "")
    name_source = getattr(spec, "top_level_name_query", "")
    if not package_source or not name_source:
        return

    package_query = _make_query(language, package_source)
    name_query = _make_query(language, name_source)

    file_package: dict[str, str] = {}
    declared_names: dict[str, list[str]] = {}
    sources: dict[str, str] = {}

    for filepath in graph:
        cached = get_or_parse_tree(filepath, parser, spec.grammar)
        if cached is None:
            continue
        source, tree = cached
        sources[filepath] = (
            source.decode("utf-8", errors="replace")
            if isinstance(source, bytes)
            else str(source)
        )

        package = ""
        for _pattern_idx, captures in _run_query(package_query, tree.root_node):
            package_node = _unwrap_node(captures.get("package"))
            if package_node is not None:
                package = _node_text(package_node)
                break
        file_package[filepath] = package
        declared_names[filepath] = _top_level_declaration_names(
            tree, name_query, tree.root_node.type
        )

    # Group declaring files by package: package -> [(file, names)].
    by_package: dict[str, list[tuple[str, list[str]]]] = {}
    for filepath, package in file_package.items():
        if package:
            by_package.setdefault(package, []).append((filepath, declared_names[filepath]))

    for package_files in by_package.values():
        if len(package_files) < 2:
            continue
        for declarer, names in package_files:
            if not names:
                continue
            pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b")
            for referencer, _ in package_files:
                if referencer == declarer:
                    continue
                text = sources.get(referencer)
                if text and pattern.search(text):
                    graph[declarer]["importers"].add(referencer)


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

    scan_path = str(path.resolve())
    graph: dict[str, dict[str, Any]] = {}

    # Initialize all files in the graph.
    for f in file_list:
        graph[f] = {"imports": set(), "importers": set()}

    # Map normalized absolute paths back to their file_list key form.
    # File finders may return relative paths while resolvers typically return
    # absolute ones; without this mapping no edge would ever match and every
    # file would report zero importers. Relative entries are interpreted both
    # against the current working directory and against the scan root.
    abs_to_key: dict[str, str] = {}
    for f in file_list:
        if os.path.isabs(f):
            abs_to_key[os.path.normpath(f)] = f
        else:
            abs_to_key[os.path.normpath(os.path.abspath(f))] = f
            abs_to_key.setdefault(
                os.path.normpath(os.path.join(scan_path, f)), f
            )

    for filepath in file_list:
        cached = get_or_parse_tree(filepath, parser, spec.grammar)
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

            resolved = spec.resolve_import(import_text, filepath, scan_path)
            if resolved is None:
                continue

            # Normalize to absolute path, then back to the file_list key form.
            if not os.path.isabs(resolved):
                resolved = os.path.normpath(os.path.join(scan_path, resolved))
            target = abs_to_key.get(os.path.normpath(resolved))

            # Only track edges within the scanned file set.
            if target is None:
                continue

            graph[filepath]["imports"].add(target)
            graph[target]["importers"].add(filepath)

    _augment_same_package_importers(graph, parser, language, spec)

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
