"""Go dependency graph builder — regex-based import parsing."""

from __future__ import annotations

import os
import re
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

    for filepath in files:
        try:
            content = Path(filepath).read_text(errors="replace")
        except OSError:
            continue

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

    return finalize_graph(graph)
