"""Dependency graph + coupling analysis (fan-in/fan-out) + dynamic imports."""

from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.engine.detectors.graph import (
    detect_cycles,
    finalize_graph,
    get_coupling_score,
)
from desloppify.languages.typescript.detectors.deps_runtime import (
    build_dynamic_import_targets as _build_dynamic_import_targets,
)
from desloppify.languages.typescript.detectors.deps_runtime import (
    ts_alias_resolver as _ts_alias_resolver,
)
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import rel, resolve_path
from desloppify.utils import (
    colorize,
    find_source_files,
    find_ts_files,
    grep_files,
    print_table,
)

_FRAMEWORK_EXTENSIONS = (".svelte", ".vue", ".astro")
_RESOLVE_EXTENSIONS = ("", ".ts", ".tsx", "/index.ts", "/index.tsx")
_JS_SPECIFIER_EXTENSIONS = {".js", ".mjs", ".cjs"}
_IMPORT_SPEC_RE = re.compile(
    r"""(?:from\s+|import\s+)(?:type\s+)?['"]([^'"]+)['"]"""
)
_DENO_EXTERNAL_PREFIXES = ("http://", "https://", "npm:", "jsr:")
logger = logging.getLogger(__name__)

# ── tsconfig paths resolution ──────────────────────────────


@lru_cache(maxsize=32)
def _load_tsconfig_paths_cached(project_root_str: str) -> dict[str, str]:
    """Return cached tsconfig path mappings for a project root."""
    return _parse_tsconfig_paths(Path(project_root_str))


def _load_tsconfig_paths(project_root: Path) -> dict[str, str]:
    """Parse tsconfig.json compilerOptions.paths into {prefix: directory}.

    Returns e.g. {"@/": "src/", "@components/": "src/components/"}.
    Falls back to {"@/": "src/"} if no tsconfig found or no paths configured.
    """
    return _load_tsconfig_paths_cached(str(project_root.resolve()))


def _parse_tsconfig_paths(project_root: Path) -> dict[str, str]:
    """Parse tsconfig paths from disk. Internal — use _load_tsconfig_paths()."""
    fallback = {"@/": "src/"}

    # Try config files in priority order
    for name in ("tsconfig.json", "tsconfig.app.json", "jsconfig.json"):
        config_path = project_root / name
        if config_path.is_file():
            try:
                data = json.loads(config_path.read_text(errors="replace"))
            except (json.JSONDecodeError, OSError) as exc:
                log_best_effort_failure(
                    logger, f"parse TypeScript config file {config_path}", exc
                )
                continue
            result = _extract_paths(data, project_root)
            if result is not None:
                return result
            # Config exists but no paths — check if it extends another
            extends = data.get("extends")
            if isinstance(extends, str) and not extends.startswith("@"):
                parent_path = (config_path.parent / extends).resolve()
                if parent_path.is_file():
                    try:
                        parent_data = json.loads(
                            parent_path.read_text(errors="replace")
                        )
                    except (json.JSONDecodeError, OSError) as exc:
                        log_best_effort_failure(
                            logger, f"parse extended config {parent_path}", exc
                        )
                        return fallback
                    parent_result = _extract_paths(parent_data, parent_path.parent)
                    if parent_result is not None:
                        # Child overrides parent — merge (child wins, but here child has none)
                        return parent_result
            return fallback

    return fallback


def _extract_paths(data: dict, base_dir: Path) -> dict[str, str] | None:
    """Extract paths mapping from a parsed tsconfig. Returns None if no paths field."""
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
        # Use first target (matches TS resolution behavior)
        target = targets[0]
        if not isinstance(target, str):
            continue
        # Strip wildcard: "@/*" → "@/", "./src/*" → "./src/"
        alias_prefix = alias.removesuffix("*")
        target_prefix = target.removesuffix("*")
        # Compose with baseUrl: resolve target relative to baseUrl
        target_dir = target_prefix.removeprefix("./")
        if base_url != ".":
            base = base_url.rstrip("/")
            if target_dir:
                target_dir = base + "/" + target_dir
            else:
                target_dir = base + "/"
        result[alias_prefix] = target_dir

    return result if result else None


# ── Import resolution helpers ──────────────────────────────


def _iter_resolve_candidates(target: Path):
    """Yield filesystem candidates for a module specifier target."""
    seen: set[str] = set()

    def _emit(candidate: Path):
        key = str(candidate)
        if key in seen:
            return
        seen.add(key)
        yield candidate

    if target.suffix in {".ts", ".tsx"}:
        yield from _emit(target)
        return

    if target.suffix in _JS_SPECIFIER_EXTENSIONS:
        # In ESM/NodeNext codebases, source imports often use `.js` while files are `.ts/.tsx`.
        stem = target.with_suffix("")
        yield from _emit(Path(str(stem) + ".ts"))
        yield from _emit(Path(str(stem) + ".tsx"))
        yield from _emit(Path(str(stem) + "/index.ts"))
        yield from _emit(Path(str(stem) + "/index.tsx"))
        yield from _emit(target)
        return

    for ext in _RESOLVE_EXTENSIONS:
        yield from _emit(Path(str(target) + ext))


def _resolve_alias(
    module_path: str, tsconfig_paths: dict[str, str], project_root: Path
) -> Path | None:
    """Resolve a tsconfig path alias to absolute path, or None if not an alias."""
    for prefix, target_dir in tsconfig_paths.items():
        if module_path.startswith(prefix):
            relative = module_path[len(prefix) :]
            return (project_root / target_dir / relative).resolve()
    return None


def _resolve_module(
    module_path: str,
    filepath: str,
    tsconfig_paths: dict[str, str],
    project_root: Path,
    graph: dict[str, dict[str, Any]],
    source_resolved: str,
) -> None:
    """Resolve an import specifier and add edges to the graph.

    Handles relative imports and tsconfig alias imports. External packages
    (bare specifiers like 'react') are silently ignored.
    """
    target: Path | None = None

    if module_path.startswith("."):
        source_dir = (
            Path(filepath).parent
            if Path(filepath).is_absolute()
            else (project_root / filepath).parent
        )
        target = (source_dir / module_path).resolve()
    else:
        target = _resolve_alias(module_path, tsconfig_paths, project_root)

    if target is None:
        return  # External package — not in our graph

    for candidate in _iter_resolve_candidates(target):
        if candidate.is_file():
            target_resolved = str(candidate)
            graph[source_resolved]["imports"].add(target_resolved)
            graph[target_resolved]["importers"].add(source_resolved)
            break


def _extract_module_specifiers(line: str) -> list[str]:
    """Extract static import/export module specifiers from one source line."""
    return [match.group(1) for match in _IMPORT_SPEC_RE.finditer(line)]


def build_dep_graph(
    path: Path,
    roslyn_cmd: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build a dependency graph: for each file, who it imports and who imports it.

    Returns {resolved_path: {"imports": set[str], "importers": set[str], "import_count": int, "importer_count": int}}
    """
    del roslyn_cmd
    graph: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"imports": set(), "importers": set(), "external_imports": set()}
    )
    tsconfig_paths = _load_tsconfig_paths(PROJECT_ROOT)

    ts_files = find_ts_files(path)
    hits = grep_files(r"""(?:\bfrom\s+['"]|\bimport\s+['"])""", ts_files)

    for filepath, _lineno, content in hits:
        source_resolved = resolve_path(filepath)
        graph[source_resolved]  # ensure entry exists
        for module_path in _extract_module_specifiers(content):
            if module_path.startswith(_DENO_EXTERNAL_PREFIXES):
                graph[source_resolved]["external_imports"].add(module_path)
                continue
            _resolve_module(
                module_path,
                filepath,
                tsconfig_paths,
                PROJECT_ROOT,
                graph,
                source_resolved,
            )

    fw_files = find_source_files(path, list(_FRAMEWORK_EXTENSIONS))
    if fw_files:
        fw_hits = grep_files(r"""(?:\bfrom\s+['"]|\bimport\s+['"])""", fw_files)
        for filepath, _lineno, content in fw_hits:
            source_resolved = resolve_path(filepath)
            graph[source_resolved]  # ensure entry exists
            for module_path in _extract_module_specifiers(content):
                if module_path.startswith(_DENO_EXTERNAL_PREFIXES):
                    graph[source_resolved]["external_imports"].add(module_path)
                    continue
                _resolve_module(
                    module_path,
                    filepath,
                    tsconfig_paths,
                    PROJECT_ROOT,
                    graph,
                    source_resolved,
                )

    return finalize_graph(dict(graph))


def cmd_deps(args: Any) -> None:
    """Show dependency info for a specific file or top coupled files."""
    graph = build_dep_graph(Path(args.path))

    if hasattr(args, "file") and args.file:
        # Single file mode
        coupling = get_coupling_score(args.file, graph)
        if args.json:
            print(json.dumps({"file": rel(args.file), **coupling}, indent=2))
            return
        print(colorize(f"\nDependency info: {rel(args.file)}\n", "bold"))
        print(f"  Fan-in (importers):  {coupling['fan_in']}")
        print(f"  Fan-out (imports):   {coupling['fan_out']}")
        print(f"  Instability:         {coupling['instability']}")
        if coupling["importers"]:
            print(colorize(f"\n  Imported by ({coupling['fan_in']}):", "cyan"))
            for p in coupling["importers"][:20]:
                print(f"    {p}")
        if coupling["imports"]:
            print(colorize(f"\n  Imports ({coupling['fan_out']}):", "cyan"))
            for p in coupling["imports"][:20]:
                print(f"    {p}")
        return

    # Top coupled files mode
    scored = []
    for filepath, entry in graph.items():
        total = entry["import_count"] + entry["importer_count"]
        if total > 5:
            scored.append(
                {
                    "file": filepath,
                    "fan_in": entry["importer_count"],
                    "fan_out": entry["import_count"],
                    "total": total,
                }
            )
    scored.sort(key=lambda x: -x["total"])

    if args.json:
        print(
            json.dumps(
                {
                    "count": len(scored),
                    "entries": [
                        {**s, "file": rel(s["file"])} for s in scored[: args.top]
                    ],
                },
                indent=2,
            )
        )
        return

    print(colorize(f"\nMost coupled files: {len(scored)} with >5 connections\n", "bold"))
    rows = []
    for s in scored[: args.top]:
        rows.append(
            [rel(s["file"]), str(s["fan_in"]), str(s["fan_out"]), str(s["total"])]
        )
    print_table(["File", "In", "Out", "Total"], rows, [60, 5, 5, 6])


def cmd_cycles(args: Any) -> None:
    """Show import cycles in the codebase."""
    graph = build_dep_graph(Path(args.path))
    cycles, _ = detect_cycles(graph)

    if args.json:
        print(
            json.dumps(
                {
                    "count": len(cycles),
                    "cycles": [
                        {"length": cy["length"], "files": [rel(f) for f in cy["files"]]}
                        for cy in cycles
                    ],
                },
                indent=2,
            )
        )
        return

    if not cycles:
        print(colorize("\nNo import cycles found.", "green"))
        return

    print(colorize(f"\nImport cycles: {len(cycles)}\n", "bold"))
    for i, cy in enumerate(cycles[: args.top]):
        files = [rel(f) for f in cy["files"]]
        print(
            colorize(
                f"  Cycle {i + 1} ({cy['length']} files):",
                "red" if cy["length"] > 3 else "yellow",
            )
        )
        for f in files[:8]:
            print(f"    {f}")
        if len(files) > 8:
            print(f"    ... +{len(files) - 8} more")
        print()


def build_dynamic_import_targets(path: Path, extensions: list[str]) -> set[str]:
    """Find files referenced by dynamic imports (import('...')) and side-effect imports."""
    return _build_dynamic_import_targets(
        path,
        extensions,
        framework_extensions=_FRAMEWORK_EXTENSIONS,
        grep_files_fn=grep_files,
        find_source_files_fn=find_source_files,
    )


def ts_alias_resolver(target: str) -> str:
    """Resolve TS path aliases using tsconfig.json paths."""
    return _ts_alias_resolver(
        target,
        load_paths_fn=_load_tsconfig_paths,
        project_root=PROJECT_ROOT,
    )
