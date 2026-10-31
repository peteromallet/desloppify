"""Orphaned file detection: files with zero importers that aren't entry points."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from desloppify.base.discovery.file_paths import count_lines, rel, resolve_path

_DUNDER_ALL_RE = re.compile(r"^__all__\s*[:=]", re.MULTILINE)

# ---------------------------------------------------------------------------
# Next.js App Router convention files
# ---------------------------------------------------------------------------

# Files that are entry points when inside an app/ directory
_NEXTJS_APP_DIR_CONVENTIONS: set[str] = {
    "page",
    "layout",
    "loading",
    "error",
    "not-found",
    "global-error",
    "route",
    "template",
    "default",
    "opengraph-image",
    "twitter-image",
    "sitemap",
    "robots",
    "icon",
    "apple-icon",
}

# Files that are entry points at the project root (or src/)
_NEXTJS_ROOT_CONVENTIONS: set[str] = {
    "middleware",
    "proxy",
    "instrumentation",
    "instrumentation-client",
}

_NEXTJS_EXTENSIONS: set[str] = {".ts", ".tsx", ".js", ".jsx"}


def _detect_nextjs_project(path: Path) -> bool:
    """Return True if this directory declares a Next.js project."""
    for name in ("next.config.js", "next.config.mjs", "next.config.ts"):
        if (path / name).is_file():
            return True
    return False


def _nextjs_project_root(directory: Path, cache: dict[Path, Path | None]) -> Path | None:
    """Find the nearest Next config without crossing another package boundary."""
    visited = []
    current = directory
    while current not in cache:
        visited.append(current)
        if _detect_nextjs_project(current):
            root = current
            break
        if (current / "package.json").is_file() or current.parent == current:
            root = None
            break
        current = current.parent
    else:
        root = cache[current]
    for parent in visited:
        cache[parent] = root
    return root


def _is_nextjs_convention_entry(rel_path: str) -> bool:
    """Return True if *rel_path* is a Next.js App Router convention file.

    Checks:
    - Files with convention names inside ``app/`` or ``src/app/``
    - Root-level convention files (middleware, proxy, instrumentation)
    """
    p = Path(rel_path)
    ext = p.suffix
    if ext not in _NEXTJS_EXTENSIONS:
        return False

    stem = p.stem
    parts = p.parts

    # Root-level conventions: middleware.ts, instrumentation.ts, etc.
    # These can live at the project root or inside src/
    if stem in _NEXTJS_ROOT_CONVENTIONS and (
        len(parts) == 1 or (len(parts) == 2 and parts[0] == "src")
    ):
        return True

    app_depth = 1 if parts[:1] == ("app",) else 2 if parts[:2] == ("src", "app") else 0
    # Next excludes private folders from routing, including their convention files.
    return bool(
        stem in _NEXTJS_APP_DIR_CONVENTIONS
        and app_depth
        and not any(part.startswith("_") for part in parts[app_depth:-1])
    )


@dataclass
class OrphanedDetectionOptions:
    """Optional behavior flags for orphaned-file detection."""

    extra_entry_patterns: list[str] | None = None
    extra_barrel_names: set[str] | None = None
    dynamic_import_finder: Callable[[Path, list[str]], set[str]] | None = None
    alias_resolver: Callable[[str], str] | None = None
    detect_frameworks: bool = True


def _has_dunder_all(filepath: str) -> bool:
    """Return True if the file defines ``__all__``, signaling a public API surface."""
    try:
        text = Path(filepath).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return _DUNDER_ALL_RE.search(text) is not None


def _is_dynamically_imported(
    filepath: str,
    dynamic_targets: set[str],
    alias_resolver: Callable[[str], str] | None = None,
) -> bool:
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
    options: OrphanedDetectionOptions | None = None,
) -> tuple[list[dict], int]:
    """Find files with zero importers that aren't known entry points."""
    resolved_options = options or OrphanedDetectionOptions()
    all_entry_patterns = resolved_options.extra_entry_patterns or []
    all_barrel_names = resolved_options.extra_barrel_names or set()
    dynamic_import_finder = resolved_options.dynamic_import_finder
    alias_resolver = resolved_options.alias_resolver

    # Resolve framework ownership per file for monorepos and subtree scans.
    nextjs_roots: dict[Path, Path | None] = {}

    dynamic_targets = (
        dynamic_import_finder(path, extensions) if dynamic_import_finder else set()
    )

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

        if resolved_options.detect_frameworks:
            source = Path(resolve_path(filepath))
            project_root = _nextjs_project_root(source.parent, nextjs_roots)
            if project_root and _is_nextjs_convention_entry(str(source.relative_to(project_root))):
                continue

        if dynamic_targets and _is_dynamically_imported(
            filepath, dynamic_targets, alias_resolver
        ):
            continue

        if _has_dunder_all(filepath):
            continue

        try:
            loc = count_lines(Path(filepath))
        except (OSError, UnicodeDecodeError):
            loc = 0

        if loc < 10:
            continue

        entries.append(
            {
                "file": filepath,
                "loc": loc,
                "import_count": entry.get("import_count", 0),
            }
        )

    return sorted(entries, key=lambda e: -e["loc"]), total_files
