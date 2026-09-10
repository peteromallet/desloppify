"""Cache primitives for tree-sitter import resolution."""

from __future__ import annotations

import logging
import os
from functools import lru_cache

from desloppify.base.output.fallbacks import log_best_effort_failure

def reset_import_cache() -> None:
    """Reset cached resolver state used by import helpers."""
    read_go_module_path.cache_clear()
    discover_jvm_source_roots.cache_clear()


@lru_cache(maxsize=512)
def read_go_module_path(go_mod_path: str) -> str:
    """Read module path from go.mod with memoization by absolute path."""
    logger = logging.getLogger(__name__)
    module_path = ""
    try:
        with open(go_mod_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("module "):
                    module_path = line.split(None, 1)[1].strip()
                    break
    except OSError as exc:
        log_best_effort_failure(logger, f"read go.mod at {go_mod_path}", exc)
    return module_path


_JVM_PRUNE_DIRS = {"build", "node_modules", "target", "dist", "out", "bin"}
_JVM_SOURCE_DIR_NAMES = {"java", "kotlin"}
_JVM_MAX_WALK_DEPTH = 8


@lru_cache(maxsize=32)
def discover_jvm_source_roots(scan_path: str) -> tuple[str, ...]:
    """Find ``<module>/src/main/java`` and ``<module>/src/main/kotlin`` roots.

    Multi-module Gradle/Maven projects keep each module's sources under a
    module directory (``android/src/main/java``, ``feature/x/src/main/kotlin``),
    so package-to-path resolution must try those roots, not just the scan
    root. Directories that only hold build output are pruned; results are
    memoized per scan root because resolvers run once per import statement.
    """
    roots: list[str] = []
    scan_abs = os.path.abspath(scan_path)
    for dirpath, dirnames, _filenames in os.walk(scan_abs):
        rel_parts = os.path.relpath(dirpath, scan_abs).split(os.sep)
        if len(rel_parts) > _JVM_MAX_WALK_DEPTH:
            dirnames[:] = []
            continue
        dirnames[:] = sorted(
            d
            for d in dirnames
            if d not in _JVM_PRUNE_DIRS and not d.startswith(".")
        )
        if (
            len(rel_parts) >= 3
            and rel_parts[-3] == "src"
            and rel_parts[-2] == "main"
            and rel_parts[-1] in _JVM_SOURCE_DIR_NAMES
        ):
            roots.append(dirpath)
            dirnames[:] = []
    return tuple(roots)


__all__ = [
    "discover_jvm_source_roots",
    "read_go_module_path",
    "reset_import_cache",
]
