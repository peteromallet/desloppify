"""Orphaned file detection: files with zero importers that aren't entry points."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from desloppify.base.discovery.file_paths import rel
from desloppify.base.discovery.file_paths import count_lines

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


# ---------------------------------------------------------------------------
# React Router / Remix convention files
# ---------------------------------------------------------------------------

# Everything under app/routes/ is a route module, loaded by the framework's
# file-based router and imported by nothing.
_REACT_ROUTER_ROUTE_DIRS: tuple[str, ...] = ("routes",)

# Framework entry points that sit beside the routes directory.
_REACT_ROUTER_CONVENTIONS: set[str] = {
    "root",
    "entry.client",
    "entry.server",
}

_REACT_ROUTER_CONFIGS: tuple[str, ...] = (
    "react-router.config.js",
    "react-router.config.mjs",
    "react-router.config.ts",
    "remix.config.js",
    "remix.config.mjs",
    "remix.config.ts",
)


def _detect_react_router_project(path: Path) -> bool:
    """Return True if the scan root looks like a React Router or Remix project.

    A config file is the cheap signal. Failing that, the dependency is checked,
    because the framework's own template ships a Vite config rather than a
    react-router.config file.
    """
    for name in _REACT_ROUTER_CONFIGS:
        if (path / name).exists():
            return True

    package_json = path / "package.json"
    if package_json.exists():
        try:
            text = package_json.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
        return '"@react-router/' in text or '"@remix-run/' in text
    return False


def _is_react_router_convention_entry(rel_path: str) -> bool:
    """Return True if *rel_path* is a React Router / Remix convention file.

    Route modules and the framework entry points have no importers by design —
    the router loads them from the filesystem — so reporting them as orphaned
    is a false positive on every project of this shape.
    """
    p = Path(rel_path)
    if p.suffix not in _NEXTJS_EXTENSIONS:
        return False

    parts = p.parts

    # Any file beneath an app/routes/ (or src/routes/) directory.
    for routes_dir in _REACT_ROUTER_ROUTE_DIRS:
        if routes_dir in parts[:-1]:
            return True

    # root.jsx, entry.client.jsx, entry.server.jsx beside the routes directory.
    # `.stem` only strips the last suffix, so entry.client.jsx stems to
    # "entry.client", which is exactly what is being matched.
    if p.stem in _REACT_ROUTER_CONVENTIONS and len(parts) <= 3:
        return True

    return False


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
    is_nextjs = (
        resolved_options.detect_frameworks and _detect_nextjs_project(path)
    )
    is_react_router = (
        resolved_options.detect_frameworks and _detect_react_router_project(path)
    )

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

        if is_react_router and _is_react_router_convention_entry(r):
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
