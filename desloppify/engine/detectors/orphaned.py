"""Orphaned file detection: files with zero importers that aren't entry points."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from desloppify.base.discovery.file_paths import rel
from desloppify.base.discovery.file_paths import count_lines

from ._orphaned.nuxt import (
    NuxtUsageIndex,
    build_nuxt_usage_index,
    detect_nuxt_project,
    is_nuxt_convention_entry,
    nuxt_auto_import_names,
    path_within_root,
)

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
    "instrumentation",
    "instrumentation-client",
}

_NEXTJS_EXTENSIONS: set[str] = {".ts", ".tsx", ".js", ".jsx"}


def _detect_nextjs_project(path: Path) -> bool:
    """Return True if the scan root looks like a Next.js project."""
    for name in ("next.config.js", "next.config.mjs", "next.config.ts"):
        if (path / name).exists():
            return True
    return False


def _is_nextjs_convention_entry(rel_path: str) -> bool:
    """Return True if *rel_path* is a Next.js App Router convention file.

    Checks:
    - Files with convention names inside any ``app/`` directory segment
    - Root-level convention files (middleware, instrumentation)
    """
    p = Path(rel_path)
    ext = p.suffix
    if ext not in _NEXTJS_EXTENSIONS:
        return False

    stem = p.stem
    parts = p.parts

    # Root-level conventions: middleware.ts, instrumentation.ts, etc.
    # These can live at the project root or inside src/
    if stem in _NEXTJS_ROOT_CONVENTIONS and len(parts) <= 2:
        return True

    # App directory conventions: any file inside an app/ segment
    if stem in _NEXTJS_APP_DIR_CONVENTIONS:
        if "app" in parts:
            return True

    return False


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

    # Framework convention detection
    detect_frameworks = resolved_options.detect_frameworks
    is_nextjs = detect_frameworks and _detect_nextjs_project(path)
    is_nuxt = detect_frameworks and detect_nuxt_project(path)
    nuxt_usage: NuxtUsageIndex | None = None
    scan_root = path.resolve()

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

        if is_nextjs and _is_nextjs_convention_entry(r):
            continue

        if is_nuxt:
            nuxt_rel = path_within_root(filepath, scan_root, r)
            if is_nuxt_convention_entry(nuxt_rel):
                continue
            auto_import_names = nuxt_auto_import_names(nuxt_rel, filepath)
            if auto_import_names is not None:
                if nuxt_usage is None:
                    nuxt_usage = build_nuxt_usage_index(path)
                resolved_path = str(Path(filepath).resolve())
                if nuxt_usage.is_used_outside(auto_import_names, resolved_path):
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
