"""Entry points a file-based framework loads by path rather than by import.

Nuxt/Nitro, Next.js, SvelteKit, Remix and Astro all route by filesystem
location: an API handler, a page, a layout or a plugin is picked up because of
where it sits, not because something imports it.  An import-graph orphan check
sees zero importers on every one of those files and reports the application's
own entry points as dead code.

This module answers one question — does a detected framework already own this
path? — so the orphan detector can stay a pure graph check.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

# Extensions a framework convention can apply to. A convention rule never fires
# on, say, a .py file even when the rule's directory matches.
FRAMEWORK_EXTENSIONS: frozenset[str] = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".vue", ".svelte", ".astro"}
)

_CONFIG_EXTENSIONS: frozenset[str] = frozenset(
    {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".cts"}
)

# How far above the scan path to look for a framework config. A scan pointed at
# ``src/`` or a workspace package still belongs to the project above it.
_ROOT_SEARCH_DEPTH = 4


@dataclass(frozen=True)
class FrameworkEntryPoints:
    """Entry-point rules contributed by one detected framework.

    All paths are POSIX and relative to :attr:`root`, the directory holding the
    framework's config file.
    """

    name: str
    root: Path
    dir_prefixes: tuple[str, ...] = ()
    exact_files: tuple[str, ...] = ()
    # (directory segment, stems): a file whose stem is in the set and which sits
    # anywhere under a directory with that name. Next.js App Router shape.
    stems_under_segment: tuple[tuple[str, frozenset[str]], ...] = ()
    # (directory prefix, filename prefix): SvelteKit's ``+page``/``+server`` shape.
    name_prefixes: tuple[tuple[str, str], ...] = ()

    def covers(self, rel_path: str) -> bool:
        """Return True if *rel_path* (relative to :attr:`root`) is an entry point."""
        p = Path(rel_path)
        if p.suffix not in FRAMEWORK_EXTENSIONS:
            return False

        posix = p.as_posix()
        if posix in self.exact_files:
            return True

        for prefix in self.dir_prefixes:
            if posix.startswith(prefix + "/"):
                return True

        parts = p.parts
        for segment, stems in self.stems_under_segment:
            if segment in parts and p.stem in stems:
                return True

        for dir_prefix, name_prefix in self.name_prefixes:
            if posix.startswith(dir_prefix + "/") and p.name.startswith(name_prefix):
                return True

        return False

    def covers_file(self, filepath: str | Path) -> bool:
        """Return True if the absolute *filepath* is one of this framework's entries."""
        try:
            rel_path = Path(filepath).resolve().relative_to(self.root)
        except ValueError:
            return False
        return self.covers(rel_path.as_posix())


@dataclass
class FrameworkContext:
    """Everything the orphan detector needs to skip framework-owned files."""

    frameworks: list[FrameworkEntryPoints] = field(default_factory=list)
    # Root-relative POSIX paths named by package.json scripts. A file a script
    # invokes is reachable by definition, whatever the import graph says.
    script_entries: frozenset[str] = frozenset()
    root: Path | None = None

    def __bool__(self) -> bool:
        return bool(self.frameworks or self.script_entries)

    def covers_file(self, filepath: str | Path) -> bool:
        """Return True if a framework, a package script or tooling owns *filepath*."""
        if any(fw.covers_file(filepath) for fw in self.frameworks):
            return True
        if self.root is None:
            return False
        try:
            rel_path = Path(filepath).resolve().relative_to(self.root).as_posix()
        except ValueError:
            return False
        return rel_path in self.script_entries or is_tooling_config(rel_path)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _iter_roots(path: Path) -> list[Path]:
    """Yield the scan path and its parents, nearest first, up to a sane depth."""
    resolved = path.resolve()
    roots = [resolved]
    current = resolved
    for _ in range(_ROOT_SEARCH_DEPTH):
        if current.parent == current:
            break
        current = current.parent
        roots.append(current)
    return roots


def _find_root_with(path: Path, names: tuple[str, ...]) -> Path | None:
    """Return the nearest root (scan path or ancestor) holding one of *names*."""
    for root in _iter_roots(path):
        if any((root / name).is_file() for name in names):
            return root
    return None


def _read_package_json(root: Path) -> dict:
    """Return the parsed package.json for *root*, or an empty dict."""
    manifest = root / "package.json"
    if not manifest.is_file():
        return {}
    try:
        data = json.loads(manifest.read_text(encoding="utf-8", errors="replace"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _declared_dependencies(root: Path) -> set[str]:
    """Return every dependency name declared in *root*'s package.json."""
    data = _read_package_json(root)
    names: set[str] = set()
    for key in ("dependencies", "devDependencies", "peerDependencies"):
        section = data.get(key)
        if isinstance(section, dict):
            names.update(section)
    return names


def _find_root_with_dependency(path: Path, packages: tuple[str, ...]) -> Path | None:
    """Return the nearest root whose package.json declares one of *packages*."""
    for root in _iter_roots(path):
        if _declared_dependencies(root) & set(packages):
            return root
    return None


def _read_config_text(root: Path, names: tuple[str, ...]) -> str:
    """Return the text of the first config in *names* that exists under *root*."""
    for name in names:
        candidate = root / name
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
    return ""


# ---------------------------------------------------------------------------
# Nuxt / Nitro
# ---------------------------------------------------------------------------

_NUXT_CONFIG_NAMES = (
    "nuxt.config.ts",
    "nuxt.config.mts",
    "nuxt.config.js",
    "nuxt.config.mjs",
    "nuxt.config.cjs",
)

# Nitro reads these from ``serverDir``; every file under them is loaded by path.
_NITRO_DIRS = ("api", "routes", "plugins", "middleware", "tasks", "utils")

# Nuxt reads these from ``srcDir``: pages, layouts and middleware are routed,
# plugins and modules are registered, components/composables/utils are
# auto-imported by directory convention.
_NUXT_SRC_DIRS = (
    "pages",
    "layouts",
    "middleware",
    "plugins",
    "modules",
    "components",
    "composables",
    "utils",
)

_NUXT_SRC_FILES = ("app.vue", "error.vue", "app.config.ts", "app.config.js")

_SRC_DIR_RE = re.compile(r"""\bsrcDir\s*:\s*['"]([^'"]+)['"]""")
_SERVER_DIR_RE = re.compile(r"""\bserverDir\s*:\s*['"]([^'"]+)['"]""")
_IMPORTS_BLOCK_RE = re.compile(r"\bimports\s*:\s*\{(.*?)\}", re.DOTALL)
_DIRS_ARRAY_RE = re.compile(r"\bdirs\s*:\s*\[(.*?)\]", re.DOTALL)
_QUOTED_RE = re.compile(r"""['"]([^'"]+)['"]""")


def _clean_dir(raw: str, src_dir: str) -> str | None:
    """Normalise one configured directory into a root-relative POSIX prefix."""
    value = raw.strip().split("*", 1)[0].strip()
    for alias, base in (("~~/", ""), ("@@/", ""), ("~/", src_dir), ("@/", src_dir)):
        if value.startswith(alias):
            value = f"{base}/{value[len(alias) :]}" if base else value[len(alias) :]
            break
    else:
        value = value.removeprefix("./")
        if src_dir and not value.startswith(f"{src_dir}/") and value != src_dir:
            value = f"{src_dir}/{value}"
    value = value.strip("/")
    return value or None


def _nuxt_auto_import_dirs(config_text: str, src_dir: str) -> tuple[str, ...]:
    """Return directories named by ``imports.dirs`` in a nuxt.config."""
    block = _IMPORTS_BLOCK_RE.search(config_text)
    if not block:
        return ()
    dirs = _DIRS_ARRAY_RE.search(block.group(1))
    if not dirs:
        return ()
    cleaned = (_clean_dir(raw, src_dir) for raw in _QUOTED_RE.findall(dirs.group(1)))
    return tuple(sorted({d for d in cleaned if d}))


def detect_nuxt(path: Path) -> FrameworkEntryPoints | None:
    """Return Nuxt/Nitro entry-point rules when *path* sits in a Nuxt project."""
    root = _find_root_with(path, _NUXT_CONFIG_NAMES)
    if root is None:
        root = _find_root_with_dependency(path, ("nuxt", "nuxt3", "nuxt-edge"))
    if root is None:
        return None

    config_text = _read_config_text(root, _NUXT_CONFIG_NAMES)

    src_match = _SRC_DIR_RE.search(config_text)
    if src_match:
        src_dir = src_match.group(1).strip("./").rstrip("/")
    elif (root / "app").is_dir():
        # Nuxt 4 default. Nuxt 3 keeps the app directories at the project root.
        src_dir = "app"
    elif (root / "src").is_dir() and not (root / "pages").is_dir():
        src_dir = "src"
    else:
        src_dir = ""

    server_match = _SERVER_DIR_RE.search(config_text)
    server_dir = (
        server_match.group(1).strip("./").rstrip("/") if server_match else "server"
    )

    def under_src(name: str) -> str:
        return f"{src_dir}/{name}" if src_dir else name

    dir_prefixes = {under_src(name) for name in _NUXT_SRC_DIRS}
    dir_prefixes.update(f"{server_dir}/{name}" for name in _NITRO_DIRS)
    dir_prefixes.update(_nuxt_auto_import_dirs(config_text, src_dir))

    exact_files = {under_src(name) for name in _NUXT_SRC_FILES}
    exact_files.update(_NUXT_CONFIG_NAMES)

    return FrameworkEntryPoints(
        name="nuxt",
        root=root,
        dir_prefixes=tuple(sorted(dir_prefixes)),
        exact_files=tuple(sorted(exact_files)),
    )


# ---------------------------------------------------------------------------
# Next.js
# ---------------------------------------------------------------------------

_NEXTJS_CONFIG_NAMES = (
    "next.config.js",
    "next.config.mjs",
    "next.config.cjs",
    "next.config.ts",
)

# Files that are entry points when inside an app/ directory
_NEXTJS_APP_DIR_CONVENTIONS: frozenset[str] = frozenset(
    {
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
)

# Files that are entry points at the project root (or src/)
_NEXTJS_ROOT_CONVENTIONS: frozenset[str] = frozenset(
    {"middleware", "instrumentation", "instrumentation-client"}
)


def detect_nextjs(path: Path) -> FrameworkEntryPoints | None:
    """Return Next.js entry-point rules when *path* sits in a Next.js project."""
    root = _find_root_with(path, _NEXTJS_CONFIG_NAMES)
    if root is None:
        root = _find_root_with_dependency(path, ("next",))
    if root is None:
        return None

    exact_files: set[str] = set(_NEXTJS_CONFIG_NAMES)
    for stem in _NEXTJS_ROOT_CONVENTIONS:
        for ext in (".ts", ".tsx", ".js", ".jsx"):
            exact_files.add(f"{stem}{ext}")
            exact_files.add(f"src/{stem}{ext}")

    return FrameworkEntryPoints(
        name="nextjs",
        root=root,
        dir_prefixes=("pages", "src/pages", "app/api", "src/app/api"),
        exact_files=tuple(sorted(exact_files)),
        stems_under_segment=(("app", _NEXTJS_APP_DIR_CONVENTIONS),),
    )


# ---------------------------------------------------------------------------
# SvelteKit
# ---------------------------------------------------------------------------

_SVELTE_CONFIG_NAMES = ("svelte.config.js", "svelte.config.ts", "svelte.config.mjs")


def detect_sveltekit(path: Path) -> FrameworkEntryPoints | None:
    """Return SvelteKit entry-point rules when *path* sits in a SvelteKit project."""
    root = _find_root_with_dependency(path, ("@sveltejs/kit",))
    if root is None:
        candidate = _find_root_with(path, _SVELTE_CONFIG_NAMES)
        if candidate is None or not (candidate / "src" / "routes").is_dir():
            return None
        root = candidate

    exact_files: set[str] = set()
    for stem in ("hooks.server", "hooks.client", "hooks", "service-worker"):
        for ext in (".ts", ".js"):
            exact_files.add(f"src/{stem}{ext}")

    return FrameworkEntryPoints(
        name="sveltekit",
        root=root,
        dir_prefixes=("src/params",),
        exact_files=tuple(sorted(exact_files)),
        # Only ``+page``/``+layout``/``+server`` files are routed; a plain
        # component colocated in src/routes still has to be imported.
        name_prefixes=(("src/routes", "+"),),
    )


# ---------------------------------------------------------------------------
# Remix / React Router framework mode
# ---------------------------------------------------------------------------


def detect_remix(path: Path) -> FrameworkEntryPoints | None:
    """Return Remix entry-point rules when *path* sits in a Remix project."""
    root = _find_root_with_dependency(
        path, ("@remix-run/react", "@remix-run/node", "@remix-run/dev")
    )
    if root is None:
        root = _find_root_with(
            path, ("remix.config.js", "remix.config.ts", "remix.config.mjs")
        )
    if root is None:
        return None

    exact_files: set[str] = set()
    for stem in ("root", "entry.client", "entry.server", "routes"):
        for ext in (".ts", ".tsx", ".js", ".jsx"):
            exact_files.add(f"app/{stem}{ext}")

    return FrameworkEntryPoints(
        name="remix",
        root=root,
        dir_prefixes=("app/routes",),
        exact_files=tuple(sorted(exact_files)),
    )


# ---------------------------------------------------------------------------
# Astro
# ---------------------------------------------------------------------------

_ASTRO_CONFIG_NAMES = (
    "astro.config.mjs",
    "astro.config.ts",
    "astro.config.js",
    "astro.config.cjs",
)


def detect_astro(path: Path) -> FrameworkEntryPoints | None:
    """Return Astro entry-point rules when *path* sits in an Astro project."""
    root = _find_root_with(path, _ASTRO_CONFIG_NAMES)
    if root is None:
        root = _find_root_with_dependency(path, ("astro",))
    if root is None:
        return None

    exact_files: set[str] = set(_ASTRO_CONFIG_NAMES)
    for stem in ("middleware", "content/config"):
        for ext in (".ts", ".js"):
            exact_files.add(f"src/{stem}{ext}")

    return FrameworkEntryPoints(
        name="astro",
        root=root,
        dir_prefixes=("src/pages",),
        exact_files=tuple(sorted(exact_files)),
    )


# ---------------------------------------------------------------------------
# react-email
# ---------------------------------------------------------------------------


def detect_react_email(path: Path) -> FrameworkEntryPoints | None:
    """Return react-email entry-point rules: templates are discovered by folder."""
    root = _find_root_with_dependency(path, ("react-email",))
    if root is None:
        return None
    return FrameworkEntryPoints(
        name="react-email",
        root=root,
        dir_prefixes=("emails", "src/emails", "app/emails"),
    )


_DETECTORS = (
    detect_nuxt,
    detect_nextjs,
    detect_sveltekit,
    detect_remix,
    detect_astro,
    detect_react_email,
)


# ---------------------------------------------------------------------------
# package.json scripts
# ---------------------------------------------------------------------------

_SCRIPT_PATH_RE = re.compile(
    r"""(?<![\w/.-])([\w.-]+(?:/[\w.@-]+)*\.(?:ts|tsx|js|jsx|mjs|cjs|mts))"""
)


def package_script_entries(root: Path) -> frozenset[str]:
    """Return root-relative files invoked by package.json ``scripts``.

    ``tsx server/db/seed.ts`` makes that file reachable however empty its
    importer list is.
    """
    scripts = _read_package_json(root).get("scripts")
    if not isinstance(scripts, dict):
        return frozenset()

    found: set[str] = set()
    for command in scripts.values():
        if not isinstance(command, str):
            continue
        for match in _SCRIPT_PATH_RE.findall(command):
            candidate = match.removeprefix("./")
            if (root / candidate).is_file():
                found.add(candidate)
    return frozenset(found)


# ---------------------------------------------------------------------------
# Entry points that belong to no single framework
# ---------------------------------------------------------------------------


def is_tooling_config(rel_path: str) -> bool:
    """Return True for a top-level ``*.config.*`` file.

    Vitest, Playwright, Drizzle, ESLint and friends are loaded by their own CLI,
    never imported.
    """
    p = Path(rel_path)
    if len(p.parts) != 1 or p.suffix not in _CONFIG_EXTENSIONS:
        return False
    return p.stem.endswith(".config") or p.stem == "config"


def build_framework_context(path: Path) -> FrameworkContext:
    """Detect every framework covering *path* and collect its entry-point rules."""
    frameworks = [found for detect in _DETECTORS if (found := detect(path))]
    root = frameworks[0].root if frameworks else None
    if root is None:
        for candidate in _iter_roots(path):
            if (candidate / "package.json").is_file():
                root = candidate
                break
    script_entries = package_script_entries(root) if root is not None else frozenset()
    return FrameworkContext(
        frameworks=frameworks, script_entries=script_entries, root=root
    )


__all__ = [
    "FrameworkContext",
    "FrameworkEntryPoints",
    "build_framework_context",
    "detect_astro",
    "detect_nextjs",
    "detect_nuxt",
    "detect_react_email",
    "detect_remix",
    "detect_sveltekit",
    "is_tooling_config",
    "package_script_entries",
]
