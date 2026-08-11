"""Resolution helpers for TypeScript dependency graph extraction."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

from desloppify.base.output.fallbacks import log_best_effort_failure
from desloppify.languages.typescript.detectors.deps.framework_aliases import (
    framework_alias_paths,
)

_RESOLVE_EXTENSIONS = ("", ".ts", ".tsx", "/index.ts", "/index.tsx")
_JS_SPECIFIER_EXTENSIONS = {".js", ".mjs", ".cjs"}
logger = logging.getLogger(__name__)


@lru_cache(maxsize=32)
def load_tsconfig_paths_cached(project_root_str: str) -> dict[str, str]:
    """Return cached tsconfig path mappings for a project root."""
    return parse_tsconfig_paths(Path(project_root_str))


def load_tsconfig_paths(project_root: Path) -> dict[str, str]:
    """Parse tsconfig.json compilerOptions.paths into alias-to-directory mappings."""
    return load_tsconfig_paths_cached(str(project_root.resolve()))


def find_tsconfig_root(scan_path: Path, project_root: Path) -> Path:
    """Find the directory containing tsconfig.json, searching scan_path then project_root.

    When the scan path differs from the project root (e.g. monorepos or
    ``--path`` pointing at a subdirectory), the tsconfig may live alongside
    the scanned code rather than at the workspace root.  We check the scan
    path first, then walk up to (and including) the project root.
    """
    resolved_root = project_root.resolve()
    candidate = scan_path.resolve()

    # Walk from scan_path up to project_root looking for tsconfig.json
    while True:
        for name in ("tsconfig.json", "tsconfig.app.json", "jsconfig.json"):
            if (candidate / name).is_file():
                return candidate
        if candidate == resolved_root or candidate == candidate.parent:
            break
        candidate = candidate.parent

    # Fall back to project_root (load_tsconfig_paths will use its own fallback)
    return resolved_root


def parse_tsconfig_paths(project_root: Path) -> dict[str, str]:
    """Parse tsconfig paths from disk. Internal — use ``load_tsconfig_paths``."""
    framework_paths = framework_alias_paths(project_root)
    fallback = framework_paths or {"@/": "src/"}

    def merged(explicit: dict[str, str]) -> dict[str, str]:
        """Explicit tsconfig mappings win; framework defaults fill the gaps."""
        return {**framework_paths, **explicit}

    for name in ("tsconfig.json", "tsconfig.app.json", "jsconfig.json"):
        config_path = project_root / name
        if not config_path.is_file():
            continue
        try:
            data = json.loads(config_path.read_text(errors="replace"))
        except (json.JSONDecodeError, OSError) as exc:
            log_best_effort_failure(
                logger,
                f"parse TypeScript config file {config_path}",
                exc,
            )
            continue
        result = extract_paths(data, project_root)
        if result is not None:
            return merged(result)
        extends = data.get("extends")
        if isinstance(extends, str) and not extends.startswith("@"):
            parent_path = (config_path.parent / extends).resolve()
            if parent_path.is_file():
                try:
                    parent_data = json.loads(parent_path.read_text(errors="replace"))
                except (json.JSONDecodeError, OSError):
                    return fallback
                parent_result = extract_paths(parent_data, parent_path.parent)
                if parent_result is not None:
                    return merged(parent_result)
        return fallback

    return fallback


def extract_paths(data: dict[str, Any], base_dir: Path) -> dict[str, str] | None:
    """Extract paths mapping from a parsed tsconfig."""
    del base_dir
    compiler_options = data.get("compilerOptions")
    if not isinstance(compiler_options, dict):
        return None
    paths = compiler_options.get("paths")
    if not isinstance(paths, dict):
        return None

    base_url = compiler_options.get("baseUrl", ".")
    if not isinstance(base_url, str):
        base_url = "."

    result: dict[str, str] = {}
    for alias, targets in paths.items():
        if not isinstance(targets, list) or not targets:
            continue
        target = targets[0]
        if not isinstance(target, str):
            continue
        alias_prefix = alias.removesuffix("*")
        target_prefix = target.removesuffix("*")
        target_dir = target_prefix.removeprefix("./")
        if base_url != ".":
            base = base_url.rstrip("/")
            target_dir = base + "/" + target_dir if target_dir else base + "/"
        result[alias_prefix] = target_dir
    return result if result else None


def iter_resolve_candidates(target: Path) -> Iterator[Path]:
    """Yield filesystem candidates for a module specifier target."""
    seen: set[str] = set()

    def _emit(candidate: Path) -> Iterator[Path]:
        key = str(candidate)
        if key in seen:
            return
        seen.add(key)
        yield candidate

    if target.suffix in {".ts", ".tsx"}:
        yield from _emit(target)
        return

    if target.suffix in _JS_SPECIFIER_EXTENSIONS:
        stem = target.with_suffix("")
        yield from _emit(Path(str(stem) + ".ts"))
        yield from _emit(Path(str(stem) + ".tsx"))
        yield from _emit(Path(str(stem) + "/index.ts"))
        yield from _emit(Path(str(stem) + "/index.tsx"))
        yield from _emit(target)
        return

    for ext in _RESOLVE_EXTENSIONS:
        yield from _emit(Path(str(target) + ext))


def resolve_alias(
    module_path: str,
    tsconfig_paths: dict[str, str],
    project_root: Path,
) -> Path | None:
    """Resolve a tsconfig path alias to an absolute path.

    Prefixes are checked longest-first so that ``@components/*`` is preferred
    over ``@/*`` when both could match.
    """
    for prefix in sorted(tsconfig_paths, key=len, reverse=True):
        if module_path.startswith(prefix):
            target_dir = tsconfig_paths[prefix]
            relative = module_path[len(prefix) :]
            return (project_root / target_dir / relative).resolve()
    return None


def resolve_module(
    module_path: str,
    filepath: str,
    tsconfig_paths: dict[str, str],
    project_root: Path,
    graph: dict[str, dict[str, Any]],
    source_resolved: str,
    *,
    source_root: Path | None = None,
) -> None:
    """Resolve an import specifier and add edges to the graph."""
    target: Path | None = None
    if module_path.startswith("."):
        relative_root = source_root or project_root
        source_dir = (
            Path(filepath).parent
            if Path(filepath).is_absolute()
            else (relative_root / filepath).parent
        )
        target = (source_dir / module_path).resolve()
    else:
        target = resolve_alias(module_path, tsconfig_paths, project_root)

    if target is None:
        return

    for candidate in iter_resolve_candidates(target):
        if candidate.is_file():
            target_resolved = str(candidate)
            graph[source_resolved]["imports"].add(target_resolved)
            graph[target_resolved]["importers"].add(source_resolved)
            break
