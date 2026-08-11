"""Path aliases a framework injects rather than committing to tsconfig.json.

Nuxt writes its ``compilerOptions.paths`` into ``.nuxt/tsconfig.*.json``, a
generated directory that is gitignored and absent until ``nuxt prepare`` runs.
The committed ``tsconfig.json`` is a bare list of project references, so every
``~/…``, ``~~/…`` and ``#shared/…`` import resolves to nothing and the files
behind those specifiers look like they have no importers at all.

Reconstruct the aliases from the project layout instead of depending on a build
artifact being present.
"""

from __future__ import annotations

import re
from pathlib import Path

_NUXT_CONFIG_NAMES = (
    "nuxt.config.ts",
    "nuxt.config.mts",
    "nuxt.config.js",
    "nuxt.config.mjs",
    "nuxt.config.cjs",
)

_SRC_DIR_RE = re.compile(r"""\bsrcDir\s*:\s*['"]([^'"]+)['"]""")


def _nuxt_config_text(project_root: Path) -> str | None:
    """Return the nuxt.config source for *project_root*, or None if there is none."""
    for name in _NUXT_CONFIG_NAMES:
        candidate = project_root / name
        if candidate.is_file():
            try:
                return candidate.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
    return None


def nuxt_alias_paths(project_root: Path) -> dict[str, str]:
    """Return Nuxt's built-in aliases as tsconfig-style prefix → directory pairs."""
    config_text = _nuxt_config_text(project_root)
    if config_text is None:
        return {}

    match = _SRC_DIR_RE.search(config_text)
    if match:
        src_dir = match.group(1).strip("./").rstrip("/")
    elif (project_root / "app").is_dir():
        # Nuxt 4 default. Nuxt 3 keeps the app sources at the project root.
        src_dir = "app"
    elif (project_root / "src").is_dir() and not (project_root / "pages").is_dir():
        src_dir = "src"
    else:
        src_dir = ""

    src_target = f"{src_dir}/" if src_dir else ""
    aliases = {
        # ~~ and @@ point at the project root, ~ and @ at srcDir. Longest prefix
        # wins in resolve_alias(), so the two-character forms cannot shadow them.
        "~~/": "",
        "@@/": "",
        "~/": src_target,
        "@/": src_target,
    }
    if (project_root / "shared").is_dir():
        aliases["#shared/"] = "shared/"
    return aliases


def framework_alias_paths(project_root: Path) -> dict[str, str]:
    """Return alias mappings contributed by any framework detected at the root."""
    return nuxt_alias_paths(project_root)


__all__ = ["framework_alias_paths", "nuxt_alias_paths"]
