"""Tree-sitter based unused import detection.

Cross-references parsed import statements against file body to find
imports whose names don't appear elsewhere in the file.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from .. import PARSE_INIT_ERRORS
from ..imports.cache import get_or_parse_tree
from .extractors import _get_parser, _make_query, _node_text, _run_query, _unwrap_node

if TYPE_CHECKING:
    from desloppify.languages._framework.treesitter import TreeSitterLangSpec

logger = logging.getLogger(__name__)


def detect_unused_imports(
    file_list: list[str],
    spec: TreeSitterLangSpec,
) -> list[dict]:
    """Find imports whose names are not referenced elsewhere in the file.

    Returns list of {file, line, name} entries.
    """
    if not spec.import_query:
        return []

    try:
        parser, language = _get_parser(spec.grammar)
    except PARSE_INIT_ERRORS as exc:
        logger.debug("tree-sitter init failed: %s", exc)
        return []

    query = _make_query(language, spec.import_query)
    entries: list[dict] = []

    for filepath in file_list:
        cached = get_or_parse_tree(filepath, parser, spec.grammar)
        if cached is None:
            continue
        source, tree = cached
        source_text = source.decode("utf-8", errors="replace")

        matches = _run_query(query, tree.root_node)
        if not matches:
            continue

        for _pattern_idx, captures in matches:
            import_node = _unwrap_node(captures.get("import"))
            path_node = _unwrap_node(captures.get("path"))
            if not import_node or not path_node:
                continue

            raw_path = _node_text(path_node).strip("\"'`")
            if not raw_path:
                continue

            # Check for alias (e.g. PHP ``use Foo as Bar``, Python ``import X as Y``).
            # When an alias is present, search for the alias name instead.
            alias_name = _extract_alias(import_node)

            # Extract the imported name from the path.
            name = alias_name or _extract_import_name(raw_path)
            if not name:
                continue

            # Get the import statement's line range so we can exclude it
            # from the search.
            import_start = import_node.start_byte
            import_end = import_node.end_byte

            # Build text without the import statement itself.
            rest = source_text[:import_start] + source_text[import_end:]

            # Check if the name appears in the rest of the file.
            if not re.search(r'\b' + re.escape(name) + r'\b', rest):
                entries.append({
                    "file": filepath,
                    "line": import_node.start_point[0] + 1,
                    "name": name,
                })

    return entries


def _extract_alias(import_node) -> str | None:
    """Extract alias name from import nodes.

    Handles two styles:
    - Go-style named imports where a ``package_identifier`` child precedes
      the path with no ``as`` keyword (e.g. ``alias "pkg/path"``).
    - ``as``-style aliases (Python ``import X as Y``, PHP ``use Foo as Bar``).

    Returns the alias text or None.
    """
    # Go-style named imports: alias is a package_identifier child.
    for i in range(import_node.child_count):
        child = import_node.children[i]
        if child.type == "package_identifier":
            return _node_text(child)

    # "as"-style aliases (Python, PHP, etc.)
    found_as = False
    for child in _iter_children(import_node):
        text = _node_text(child)
        if text == "as":
            found_as = True
            continue
        # The node immediately after "as" is the alias name.
        if found_as and child.type in ("name", "identifier", "namespace_name"):
            return _node_text(child)
    return None


def _iter_children(node):
    """Recursively yield terminal-ish children relevant to alias extraction.

    Only descends into namespace_use_clause / import_clause nodes (the
    immediate import container) — avoids descending into unrelated subtrees.
    """
    for i in range(node.child_count):
        child = node.children[i]
        # Yield leaf-like nodes (keywords, identifiers).
        if child.child_count == 0:
            yield child
        elif child.type in (
            "namespace_use_clause", "import_clause",
            "namespace_alias", "as_pattern",
        ):
            yield from _iter_children(child)


def _extract_import_name(import_path: str) -> str:
    """Extract the usable name from an import path.

    Examples:
        "fmt" -> "fmt"
        "./utils" -> "utils"
        "crate::module::Foo" -> "Foo"
        "com.example.MyClass" -> "MyClass"
        "MyApp::Model::User" -> "User"
        "Data.List" -> "List"
    """
    candidate = import_path.strip()
    for sep in ("/", "\\"):
        if sep in candidate:
            parts = [p for p in candidate.split(sep) if p]
            if parts:
                candidate = parts[-1]

    for ext in (".go", ".rs", ".rb", ".py", ".js", ".jsx", ".ts",
                ".tsx", ".java", ".kt", ".cs", ".fs", ".ml",
                ".ex", ".erl", ".hs", ".lua", ".zig", ".pm",
                ".sh", ".pl", ".scala", ".swift", ".php",
                ".dart", ".mjs", ".cjs", ".h", ".hh", ".hpp"):
        if candidate.endswith(ext):
            return candidate[:-len(ext)]

    for sep in ("::", "."):
        if sep in candidate:
            parts = [p for p in candidate.split(sep) if p]
            if parts:
                return parts[-1]

    return candidate


__all__ = ["detect_unused_imports"]
