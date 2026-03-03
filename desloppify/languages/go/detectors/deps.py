"""Go dependency graph builder — regex-based import parsing."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from desloppify.engine.detectors.graph import finalize_graph
from desloppify.languages._framework.treesitter._imports import resolve_go_import
from desloppify.languages.go.extractors import find_go_files

# Match single import: import "path" or import alias "path"
_SINGLE_IMPORT_RE = re.compile(
    r'^\s*import\s+(?:\w+\s+)?"([^"]+)"'
)

# Match start of grouped import block: import (
_GROUP_IMPORT_START_RE = re.compile(r'^\s*import\s*\(')

# Match import line inside group: "path" or alias "path" or . "path"
_GROUP_IMPORT_LINE_RE = re.compile(
    r'^\s*(?:\w+\s+|\.\s+)?"([^"]+)"'
)


def _extract_imports(content: str) -> list[str]:
    """Extract all import paths from Go source content."""
    imports: list[str] = []
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        # Check for grouped import
        if _GROUP_IMPORT_START_RE.match(line):
            i += 1
            while i < len(lines):
                group_line = lines[i].strip()
                if group_line == ')':
                    break
                m = _GROUP_IMPORT_LINE_RE.match(lines[i])
                if m:
                    imports.append(m.group(1))
                i += 1
            i += 1
            continue

        # Check for single import
        m = _SINGLE_IMPORT_RE.match(line)
        if m:
            imports.append(m.group(1))

        i += 1
    return imports


def build_dep_graph(
    path: Path,
    roslyn_cmd: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build Go dependency graph from import declarations.

    Parses Go import blocks (single and grouped), resolves local imports
    via go.mod module path, and returns the standard graph shape.
    """
    del roslyn_cmd  # Not used for Go

    scan_path = str(path.resolve())
    files = find_go_files(path)
    file_set = set(files)

    # Initialize graph with all files
    graph: dict[str, dict[str, Any]] = {}
    for f in files:
        graph[f] = {"imports": set(), "importers": set()}

    # Track package declarations per file for same-package edge linking
    dir_pkg: dict[tuple[str, str], list[str]] = defaultdict(list)

    for filepath in files:
        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError:
            continue

        # Collect package name for same-package linking (single read)
        pkg_match = _PACKAGE_RE.search(content)
        if pkg_match:
            key = (str(Path(filepath).parent), pkg_match.group(1))
            dir_pkg[key].append(filepath)

        import_paths = _extract_imports(content)
        for import_path in import_paths:
            resolved = resolve_go_import(import_path, filepath, scan_path)
            if resolved is None:
                continue

            # Normalize to absolute path
            if not os.path.isabs(resolved):
                resolved = os.path.normpath(os.path.join(scan_path, resolved))

            # Only track edges within the scanned file set
            if resolved not in file_set:
                continue

            graph[filepath]["imports"].add(resolved)
            if resolved in graph:
                graph[resolved]["importers"].add(filepath)

    # Add implicit same-package edges: Go files in the same directory
    # sharing the same `package` declaration are implicitly linked.
    # Without these edges, every file that isn't cross-package imported
    # would appear "orphaned."
    for pkg_files in dir_pkg.values():
        if len(pkg_files) < 2:
            continue
        rep = pkg_files[0]
        for other in pkg_files[1:]:
            graph[rep]["importers"].add(other)
            graph[other]["importers"].add(rep)

    return finalize_graph(graph)


_PACKAGE_RE = re.compile(r"^\s*package\s+(\w+)", re.MULTILINE)
