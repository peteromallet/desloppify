"""Orphaned file detection: files with zero importers that aren't entry points."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..utils import rel


def _is_dynamically_imported(filepath: str, dynamic_targets: set[str],
                              alias_resolver: Callable[[str], str] | None = None) -> bool:
    """Check if a file is referenced by any dynamic/side-effect import."""
    r = rel(filepath)
    stem = Path(filepath).stem
    name_no_ext = str(Path(r).with_suffix(""))

    for target in dynamic_targets:
        resolved = alias_resolver(target) if alias_resolver else target
        resolved = resolved.lstrip("./")
        if resolved == name_no_ext or resolved == r:
            return True
        if name_no_ext.endswith("/" + resolved) or name_no_ext.endswith(resolved):
            return True
        if resolved.endswith("/" + stem) or resolved == stem:
            return True
        if resolved.endswith("/" + Path(filepath).name):
            return True

    return False


def detect_orphaned_files(
    path: Path,
    graph: dict,
    extensions: list[str],
    extra_entry_patterns: list[str] | None = None,
    extra_barrel_names: set[str] | None = None,
    dynamic_import_finder: Callable[[Path, list[str]], set[str]] | None = None,
    alias_resolver: Callable[[str], str] | None = None,
) -> tuple[list[dict], int]:
    """Find files with zero importers that aren't known entry points.

    Args:
        extensions: File extensions to consider.
        extra_entry_patterns: Entry-point patterns (substring-matched against relative paths).
        extra_barrel_names: Barrel file names to skip.
        dynamic_import_finder: Language-specific function to find dynamic import targets.
            Signature: (path, extensions) -> set of import specifiers.
            If None, dynamic import checking is skipped.
        alias_resolver: Resolves import aliases (e.g. @/ -> src/).
            Signature: (target) -> resolved_target.
    """
    all_entry_patterns = extra_entry_patterns or []
    all_barrel_names = extra_barrel_names or set()

    dynamic_targets = dynamic_import_finder(path, extensions) if dynamic_import_finder else set()

    total_files = len(graph)
    entries = []
    for filepath, entry in graph.items():
        if entry["importer_count"] > 0:
            continue

        r = rel(filepath)

        if any(p in r for p in all_entry_patterns):
            continue

        basename = Path(filepath).name
        if basename in all_barrel_names:
            continue

        if dynamic_targets and _is_dynamically_imported(filepath, dynamic_targets, alias_resolver):
            continue

        try:
            loc = len(Path(filepath).read_text().splitlines())
        except (OSError, UnicodeDecodeError):
            loc = 0

        if loc < 10:
            continue

        entries.append({
            "file": filepath,
            "loc": loc,
            "import_count": entry.get("import_count", 0),
        })

    return sorted(entries, key=lambda e: -e["loc"]), total_files
