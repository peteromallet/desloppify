"""Kotlin graph edges from discovered package/declaration ownership.

Kotlin does not require package-shaped directories or one declaration per file.
Explicit imports resolve through the parsed index, including aliases and member
imports. Inferred star/same-package edges cover unique type/constructor references
only; this is not compiler type resolution (extensions, overloads and Gradle
source-set visibility are deliberately not guessed).
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .cache import get_or_parse_tree
from .kotlin_syntax import KotlinFile, parse_kotlin_file


def _qualify(package: str, name: str) -> str:
    return f"{package}.{name}" if package else name


def build_kotlin_graph(file_list: list[str], parser) -> dict[str, dict[str, Any]]:
    files: dict[str, KotlinFile] = {}
    declarations: dict[str, dict[str, bool]] = defaultdict(dict)
    graph = {file: {"imports": set(), "importers": set()} for file in file_list}
    for file in file_list:
        cached = get_or_parse_tree(file, parser, "kotlin")
        if cached is None:
            continue
        facts = files[file] = parse_kotlin_file(cached[1].root_node)
        for name, is_type in facts.declarations.items():
            declarations[_qualify(facts.package, name)][file] = is_type

    def unique_owner(name: str, *, types_only: bool = False) -> str | None:
        candidates = declarations.get(name, {})
        if len(candidates) != 1:
            return None
        file, is_type = next(iter(candidates.items()))
        return file if is_type or not types_only else None

    for file, facts in files.items():
        edges = graph[file]["imports"]
        for path, _alias in facts.imports:
            # A nested type, object member or enum entry belongs to its outer
            # declaration's file. Never turn a package prefix into a candidate.
            owner = unique_owner(path)
            prefix = path
            while owner is None and "." in prefix:
                prefix = prefix.rsplit(".", 1)[0]
                owner = unique_owner(prefix, types_only=True)
            if owner is not None:
                edges.add(owner)
        for name in facts.references - facts.shadowed:
            local = _qualify(facts.package, name)
            if local in declarations:
                owner = unique_owner(local, types_only=True)
            else:
                owners = {
                    unique_owner(_qualify(star, name), types_only=True)
                    for star in facts.stars
                    if _qualify(star, name) in declarations
                }
                owner = next(iter(owners)) if len(owners) == 1 else None
            if owner is not None:
                edges.add(owner)
        edges.discard(file)
        for imported in edges:
            graph[imported]["importers"].add(file)

    for data in graph.values():
        data["import_count"] = len(data["imports"])
        data["importer_count"] = len(data["importers"])
    return graph
