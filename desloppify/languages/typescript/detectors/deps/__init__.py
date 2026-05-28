"""Dependency graph + coupling analysis (fan-in/fan-out) + dynamic imports."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from desloppify.base.discovery.file_paths import rel, resolve_path
from desloppify.base.search.grep import grep_files
from desloppify.base.output.terminal import colorize, print_table
from desloppify.base.discovery.source import (
    find_source_files,
    find_ts_and_tsx_files,
)
from desloppify.base.discovery.paths import get_project_root
from desloppify.engine.detectors.graph import (
    detect_cycles,
    finalize_graph,
    get_coupling_score,
)
from desloppify.languages.typescript.detectors.deps.resolve import (
    find_tsconfig_root as _find_tsconfig_root,
)
from desloppify.languages.typescript.detectors.deps.resolve import (
    load_tsconfig_paths as _load_tsconfig_paths,
)
from desloppify.languages.typescript.detectors.deps.resolve import (
    resolve_module as _resolve_module,
)
from desloppify.languages.typescript.detectors.deps.runtime import (
    build_dynamic_import_targets as _build_dynamic_import_targets,
)
from desloppify.languages.typescript.detectors.deps.runtime import (
    ts_alias_resolver as _ts_alias_resolver,
)
from desloppify.languages._framework.frameworks.registry import (
    framework_source_extensions,
)


def _framework_extensions() -> tuple[str, ...]:
    """Framework source extensions for the node ecosystem, registry-driven.

    Resolved at call time so newly-registered specs (e.g. by tests via
    ``register_framework_spec``) are picked up without module reload.
    """
    return framework_source_extensions(ecosystem="node")


_IMPORT_SPEC_RE = re.compile(
    r"""(?:from\s+|import\s+)(?:type\s+)?['"]([^'"]+)['"]"""
)
_DENO_EXTERNAL_PREFIXES = ("http://", "https://", "npm:", "jsr:")


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
    project_root = get_project_root()
    tsconfig_root = _find_tsconfig_root(path, project_root)
    tsconfig_paths = _load_tsconfig_paths(tsconfig_root)

    ts_files = find_ts_and_tsx_files(path)
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
                tsconfig_root,
                graph,
                source_resolved,
                source_root=project_root,
            )

    fw_files = find_source_files(path, list(_framework_extensions()))
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
                    tsconfig_root,
                    graph,
                    source_resolved,
                    source_root=project_root,
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
        framework_extensions=_framework_extensions(),
        grep_files_fn=grep_files,
        find_source_files_fn=find_source_files,
    )


def ts_alias_resolver(target: str) -> str:
    """Resolve TS path aliases using tsconfig.json paths."""
    return _ts_alias_resolver(
        target,
        load_paths_fn=_load_tsconfig_paths,
        project_root=get_project_root(),
    )
