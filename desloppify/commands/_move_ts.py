"""TypeScript import specifier computation and replacement finding for move command."""

import os
from pathlib import Path

from ..utils import SRC_PATH
from .move import _dedup


# ── TypeScript import specifier computation ───────────────


def _strip_ts_ext(path: str) -> str:
    """Strip .ts/.tsx/.js/.jsx extension from an import path."""
    for ext in (".tsx", ".ts", ".jsx", ".js"):
        if path.endswith(ext):
            return path[:-len(ext)]
    return path


def _compute_ts_specifiers(from_file: str, to_file: str) -> tuple[str | None, str]:
    """Compute both @/ alias and relative import specifiers for a TS file.

    Returns (alias_specifier_or_None, relative_specifier).
    alias_specifier is None if the target is outside src/.
    """
    to_path = Path(to_file)

    # @/ alias: only works for files under SRC_PATH
    alias = None
    try:
        to_rel_src = to_path.relative_to(SRC_PATH)
        alias = "@/" + _strip_ts_ext(str(to_rel_src))
        if alias.endswith("/index"):
            alias = alias[:-6]
    except ValueError:
        pass  # target outside src/

    # Relative specifier
    from_dir = Path(from_file).parent
    relative = os.path.relpath(to_file, from_dir)
    relative = _strip_ts_ext(relative)
    if not relative.startswith("."):
        relative = "./" + relative
    if relative.endswith("/index"):
        relative = relative[:-6]

    return alias, relative


# ── Finding import lines and computing replacements ───────


def find_ts_replacements(
    source_abs: str, dest_abs: str, graph: dict,
) -> dict[str, list[tuple[str, str]]]:
    """Compute all import string replacements needed for a TS file move.

    Returns {filepath: [(old_str, new_str), ...]}
    """
    changes: dict[str, list[tuple[str, str]]] = {}
    entry = graph.get(source_abs)
    if not entry:
        return changes

    importers = entry.get("importers", set())

    for importer in importers:
        if importer == source_abs:
            continue  # skip self-imports, handled separately

        # Compute old specifiers (what the importer currently uses)
        old_alias, old_relative = _compute_ts_specifiers(importer, source_abs)
        # Compute new specifiers
        new_alias, new_relative = _compute_ts_specifiers(importer, dest_abs)

        replacements = []

        try:
            content = Path(importer).read_text()
        except (OSError, UnicodeDecodeError):
            continue

        # Check which form the importer actually uses
        for old_spec, new_spec in [(old_alias, new_alias), (old_relative, new_relative)]:
            if old_spec is None or new_spec is None:
                continue
            if old_spec == new_spec:
                continue
            # Look for the old specifier in quotes
            for quote in ("'", '"'):
                target = f"{quote}{old_spec}{quote}"
                if target in content:
                    replacement = f"{quote}{new_spec}{quote}"
                    replacements.append((target, replacement))

        if replacements:
            changes[importer] = _dedup(replacements)

    return changes


def find_ts_self_replacements(
    source_abs: str, dest_abs: str, graph: dict,
) -> list[tuple[str, str]]:
    """Compute replacements for the moved file's own relative imports.

    Only relative imports need updating — @/ imports are location-independent.
    """
    replacements = []
    entry = graph.get(source_abs)
    if not entry:
        return replacements

    try:
        content = Path(source_abs).read_text()
    except (OSError, UnicodeDecodeError):
        return replacements

    for imported_file in entry.get("imports", set()):
        # Compute old relative specifier (from source location)
        _, old_relative = _compute_ts_specifiers(source_abs, imported_file)
        # Compute new relative specifier (from dest location)
        _, new_relative = _compute_ts_specifiers(dest_abs, imported_file)

        if old_relative == new_relative:
            continue

        for quote in ("'", '"'):
            target = f"{quote}{old_relative}{quote}"
            if target in content:
                replacement = f"{quote}{new_relative}{quote}"
                replacements.append((target, replacement))

    return _dedup(replacements)
