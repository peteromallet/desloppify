"""Nuxt / Nitro convention entry points and auto-import usage resolution.

Nuxt registers whole directory trees by convention: ``pages/`` is the router,
``server/api/`` is the HTTP surface, ``plugins/`` boot on their own. Nothing
imports those files, so an import-graph orphan check reports every one of them.

Nuxt also auto-imports ``components/``, ``composables/``, ``utils/`` and
``shared/``: consumers write ``<GameOutcomeDrawer />`` in a template or a bare
``useUser()`` call with no import statement, which the graph cannot see either.
Those are resolved by name rather than exempted wholesale, so a component that
genuinely nobody references is still reported.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from desloppify.base.discovery.paths import get_project_root
from desloppify.base.discovery.source import find_source_files, read_file_text

# ---------------------------------------------------------------------------
# Project detection
# ---------------------------------------------------------------------------

_NUXT_CONFIG_NAMES: frozenset[str] = frozenset(
    {
        "nuxt.config.ts",
        "nuxt.config.js",
        "nuxt.config.mjs",
        "nuxt.config.cjs",
        "nuxt.config.mts",
    }
)

# ---------------------------------------------------------------------------
# Convention directories and files
# ---------------------------------------------------------------------------

# Auto-registered directories under the Nuxt srcDir (``app/`` in Nuxt 4,
# the project root in Nuxt 3).
_NUXT_APP_DIRS: frozenset[str] = frozenset(
    {
        "pages",
        "layouts",
        "middleware",
        "plugins",
        "modules",
    }
)

# File-routed or auto-registered directories under the Nitro ``server/`` dir.
_NUXT_SERVER_DIRS: frozenset[str] = frozenset(
    {
        "api",
        "routes",
        "middleware",
        "plugins",
        "tasks",
    }
)

# Root-level convention files, by stem.
_NUXT_ROOT_CONVENTIONS: frozenset[str] = frozenset(
    {
        "nuxt.config",
        "capacitor.config",
        "app.config",
        "app",
        "error",
    }
)

# Segments a source path may start with before the conventions begin.
_NUXT_SRC_DIRS: frozenset[str] = frozenset({"app", "src"})

# ---------------------------------------------------------------------------
# Auto-import surfaces
# ---------------------------------------------------------------------------

# Directories whose files are registered globally by name. Values say how the
# registered name is derived: component naming, or the module's exports.
_COMPONENT_SURFACE = "component"
_EXPORT_SURFACE = "export"

_NUXT_APP_AUTO_IMPORTS: dict[str, str] = {
    "components": _COMPONENT_SURFACE,
    "composables": _EXPORT_SURFACE,
    "utils": _EXPORT_SURFACE,
}

_NUXT_SERVER_AUTO_IMPORTS: dict[str, str] = {
    "utils": _EXPORT_SURFACE,
}

_NUXT_SHARED_DIR = "shared"

_NUXT_SOURCE_EXTENSIONS: tuple[str, ...] = (
    ".vue",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".mjs",
    ".mts",
)

_MODE_SUFFIX_RE = re.compile(r"\.(?:client|server|global)$")
_WORD_SPLIT_RE = re.compile(r"[^A-Za-z0-9]+")
_CASE_SPLIT_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z][a-z0-9]*|[a-z0-9]+")

_IDENTIFIER_RE = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
_TAG_RE = re.compile(r"<\s*/?\s*([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)+)")

_EXPORT_DECL_RE = re.compile(
    r"\bexport\s+(?:declare\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:abstract\s+)?(?:function\s*\*?|const|let|var|class|interface|enum|type)\s+"
    r"([A-Za-z_$][A-Za-z0-9_$]*)"
)
_EXPORT_LIST_RE = re.compile(r"\bexport\s*\{([^}]*)\}")


def detect_nuxt_project(path: Path) -> bool:
    """Return True if the scan root looks like a Nuxt project."""
    for name in _NUXT_CONFIG_NAMES:
        if (path / name).exists():
            return True
    return _package_json_declares_nuxt(path / "package.json")


def _package_json_declares_nuxt(manifest: Path) -> bool:
    """Return True if *manifest* lists ``nuxt`` as a dependency."""
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return False
    if not isinstance(payload, dict):
        return False
    for key in ("dependencies", "devDependencies"):
        section = payload.get(key)
        if isinstance(section, dict) and "nuxt" in section:
            return True
    return False


def _strip_src_prefix(parts: tuple[str, ...]) -> tuple[str, ...]:
    """Drop a leading ``app/`` or ``src/`` srcDir segment."""
    if len(parts) > 1 and parts[0] in _NUXT_SRC_DIRS:
        return parts[1:]
    return parts


def is_nuxt_convention_entry(rel_path: str) -> bool:
    """Return True if *rel_path* is a Nuxt or Nitro convention entry point.

    Covers file-routed and auto-registered trees (``pages/``, ``layouts/``,
    ``server/api/``, ``server/plugins/`` and friends) plus the root config
    files, under both the Nuxt 3 root layout and the Nuxt 4 ``app/`` srcDir.
    """
    parts = Path(rel_path).parts
    if not parts:
        return False

    inner = _strip_src_prefix(parts)

    # ``nuxt.config.ts`` at the root, ``app.vue`` at the root or in the srcDir.
    if len(inner) == 1:
        return _MODE_SUFFIX_RE.sub("", Path(inner[0]).stem) in _NUXT_ROOT_CONVENTIONS

    if inner[0] == "server":
        return len(inner) > 2 and inner[1] in _NUXT_SERVER_DIRS

    return inner[0] in _NUXT_APP_DIRS


def _auto_import_surface(rel_path: str) -> tuple[str, tuple[str, ...]] | None:
    """Return ``(surface, dir_parts)`` when *rel_path* is auto-imported."""
    parts = Path(rel_path).parts
    if len(parts) < 2:
        return None

    if parts[0] == _NUXT_SHARED_DIR:
        return _EXPORT_SURFACE, parts[1:-1]

    inner = _strip_src_prefix(parts)
    if len(inner) < 2:
        return None

    if inner[0] == "server":
        if len(inner) < 3:
            return None
        surface = _NUXT_SERVER_AUTO_IMPORTS.get(inner[1])
        return (surface, inner[2:-1]) if surface else None

    surface = _NUXT_APP_AUTO_IMPORTS.get(inner[0])
    return (surface, inner[1:-1]) if surface else None


def path_within_root(filepath: str, root: Path, fallback: str) -> str:
    """Return *filepath* relative to the scan *root*.

    Convention matching is anchored on the scan root, not on the working
    directory: ``rel()`` resolves against the project root, which yields a
    ``../..`` prefix when the tool is invoked from outside the project.
    """
    try:
        return str(Path(filepath).resolve().relative_to(root))
    except ValueError:
        return fallback


def _absolute(filepath: str) -> str:
    """Resolve a discovery-relative path against the project root."""
    if os.path.isabs(filepath):
        return filepath
    return str(get_project_root() / filepath)


def _split_by_case(value: str) -> list[str]:
    """Split an identifier into its case/separator-delimited words."""
    words: list[str] = []
    for chunk in _WORD_SPLIT_RE.split(value):
        words.extend(_CASE_SPLIT_RE.findall(chunk))
    return words


def _pascal(words: list[str]) -> str:
    return "".join(word[:1].upper() + word[1:] for word in words)


def _component_names(dir_parts: tuple[str, ...], stem: str) -> set[str]:
    """Return the names a Nuxt component file can be referenced by.

    Nuxt joins the directory path to the filename and drops the directory
    segments the filename already repeats, so ``game/GameOutcomeDrawer.vue``
    registers as ``GameOutcomeDrawer`` while ``account/ThemeSwitcher.vue``
    registers as ``AccountThemeSwitcher``. The undeduplicated join comes back
    alongside it, and so does the bare filename: ``components.dirs`` with
    ``pathPrefix: false`` registers under that, and it is also the local name a
    consumer that imports the file by path writes in its template.
    """
    prefix_words: list[str] = []
    for segment in dir_parts:
        prefix_words.extend(_split_by_case(segment))

    file_words = [] if stem.lower() == "index" else _split_by_case(stem)

    remaining = list(prefix_words)
    leading: list[str] = []
    while remaining and (not file_words or remaining[0].lower() != file_words[0].lower()):
        leading.append(remaining.pop(0))

    names = {
        _pascal(leading + file_words),
        _pascal(prefix_words + file_words),
        _pascal(file_words),
    }
    return {name for name in names if name}


def _exported_names(filepath: str, stem: str) -> set[str]:
    """Return the identifiers a composable/util module publishes."""
    names = {stem}
    text = read_file_text(_absolute(filepath))
    if text is None:
        return names
    names.update(_EXPORT_DECL_RE.findall(text))
    for group in _EXPORT_LIST_RE.findall(text):
        for item in group.split(","):
            token = item.strip().split(" as ")[-1].strip()
            if token and _IDENTIFIER_RE.fullmatch(token):
                names.add(token)
    return names


def nuxt_auto_import_names(rel_path: str, filepath: str) -> set[str] | None:
    """Return the names *rel_path* is auto-imported under, or None.

    None means the file is not on an auto-import surface, so the ordinary
    import-graph verdict stands.
    """
    surface = _auto_import_surface(rel_path)
    if surface is None:
        return None

    kind, dir_parts = surface
    stem = _MODE_SUFFIX_RE.sub("", Path(rel_path).stem)
    if kind == _COMPONENT_SURFACE:
        return _component_names(dir_parts, stem)
    return _exported_names(filepath, stem)


@dataclass
class NuxtUsageIndex:
    """Where each referenced identifier was seen, across the project."""

    hits: dict[str, tuple[int, str]] = field(default_factory=dict)

    def record(self, name: str, filepath: str) -> None:
        seen = self.hits.get(name)
        if seen is None:
            self.hits[name] = (1, filepath)
        elif seen[1] != filepath:
            self.hits[name] = (seen[0] + 1, seen[1])

    def is_used_outside(self, names: set[str], filepath: str) -> bool:
        """Return True if any of *names* is referenced by another file."""
        for name in names:
            seen = self.hits.get(name)
            if seen is None:
                continue
            if seen[0] > 1 or seen[1] != filepath:
                return True
        return False


def build_nuxt_usage_index(path: Path) -> NuxtUsageIndex:
    """Index every identifier and component tag referenced under *path*.

    Template tags are normalized to PascalCase so ``<game-outcome-drawer />``
    and ``<GameOutcomeDrawer />`` resolve to the one registered name.
    """
    index = NuxtUsageIndex()
    for filepath in find_source_files(path, list(_NUXT_SOURCE_EXTENSIONS)):
        abs_path = _absolute(filepath)
        text = read_file_text(abs_path)
        if text is None:
            continue
        resolved = str(Path(abs_path).resolve())
        for name in _IDENTIFIER_RE.findall(text):
            index.record(name, resolved)
        for tag in _TAG_RE.findall(text):
            index.record(_pascal(_split_by_case(tag)), resolved)
    return index


__all__ = [
    "NuxtUsageIndex",
    "build_nuxt_usage_index",
    "detect_nuxt_project",
    "is_nuxt_convention_entry",
    "nuxt_auto_import_names",
    "path_within_root",
]
