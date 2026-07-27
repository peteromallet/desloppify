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


# ---------------------------------------------------------------------------
# Django convention files
# ---------------------------------------------------------------------------

# Modules Django and Celery load by dotted-string reference or autodiscovery
# rather than a source-level import, so they always show zero importers.
_DJANGO_AUTOLOADED_MODULES: set[str] = {
    "admin",  # django.contrib.admin autodiscover
    "apps",   # AppConfig named from INSTALLED_APPS
    "celery",  # Celery app module loaded at startup
    "checks",  # system check framework registration
    "context_processors",  # TEMPLATES OPTIONS strings
    "middleware",  # MIDDLEWARE strings
    "models",  # imported implicitly by the app registry
    "receivers",  # signal receivers wired in AppConfig.ready()
    "routers",  # DATABASE_ROUTERS strings
    "signals",  # signal handlers wired in AppConfig.ready()
    "tasks",  # celery autodiscover_tasks()
}

# Directories whose modules are resolved by name at runtime.
_DJANGO_AUTOLOADED_DIRS: set[str] = {
    "templatetags",  # {% load %}
    "management",  # manage.py subcommand discovery
    "migrations",  # migration executor
}


def _detect_django_project(path: Path) -> bool:
    """Return True if the scan root looks like a Django project."""
    if (path / "manage.py").exists():
        return True
    candidates = list(path.glob("*/settings.py")) + list(path.glob("*/settings/base.py"))
    for settings_path in candidates:
        try:
            text = settings_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "INSTALLED_APPS" in text:
            return True
    return False


def _is_django_convention_entry(rel_path: str) -> bool:
    """Return True if *rel_path* is a Django/Celery convention module.

    These are reached through dotted strings (``ROOT_URLCONF``, ``MIDDLEWARE``,
    ``include("app.urls")``) or autodiscovery, never through an import
    statement, so importer counts say nothing about whether they are live.
    """
    p = Path(rel_path)
    if p.suffix != ".py":
        return False

    if _DJANGO_AUTOLOADED_DIRS.intersection(p.parts[:-1]):
        return True

    stem = p.stem
    if stem in _DJANGO_AUTOLOADED_MODULES:
        return True

    # URLconfs: urls.py plus the common urls_staff.py / staff_urls.py splits,
    # each pulled in by include("app.<module>").
    return stem == "urls" or stem.startswith("urls_") or stem.endswith("_urls")


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
    is_django = detect_frameworks and _detect_django_project(path)

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

        if is_django and _is_django_convention_entry(r):
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
