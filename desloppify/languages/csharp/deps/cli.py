"""CLI formatting helpers for C# dependency graph commands."""

from __future__ import annotations

import json
from pathlib import Path

from desloppify.engine.detectors.graph import detect_cycles, get_coupling_score
from desloppify.file_discovery import rel
from desloppify.utils import colorize, print_table


def cmd_deps(args, *, build_dep_graph, resolve_roslyn_cmd) -> None:
    """Show dependency info for a specific C# file or top coupled files."""
    graph = build_dep_graph(Path(args.path), roslyn_cmd=resolve_roslyn_cmd(args))

    if getattr(args, "file", None):
        coupling = get_coupling_score(args.file, graph)
        if getattr(args, "json", False):
            print(json.dumps({"file": rel(args.file), **coupling}, indent=2))
            return
        print(colorize(f"\nDependency info: {rel(args.file)}\n", "bold"))
        print(f"  Fan-in (importers):  {coupling['fan_in']}")
        print(f"  Fan-out (imports):   {coupling['fan_out']}")
        print(f"  Instability:         {coupling['instability']}")
        return

    by_importers = sorted(graph.items(), key=lambda kv: (-kv[1].get("importer_count", 0), rel(kv[0])))
    if getattr(args, "json", False):
        top = by_importers[: getattr(args, "top", 20)]
        print(
            json.dumps(
                {
                    "files": len(graph),
                    "entries": [
                        {
                            "file": rel(filepath),
                            "importers": entry.get("importer_count", 0),
                            "imports": entry.get("import_count", 0),
                        }
                        for filepath, entry in top
                    ],
                },
                indent=2,
            )
        )
        return

    print(colorize(f"\nC# dependency graph: {len(graph)} files\n", "bold"))
    rows = []
    for filepath, entry in by_importers[: getattr(args, "top", 20)]:
        rows.append([rel(filepath), str(entry.get("importer_count", 0)), str(entry.get("import_count", 0))])
    if rows:
        print_table(["File", "Importers", "Imports"], rows, [70, 9, 7])


def cmd_cycles(args, *, build_dep_graph, resolve_roslyn_cmd) -> None:
    """Show import cycles in C# source files."""
    graph = build_dep_graph(Path(args.path), roslyn_cmd=resolve_roslyn_cmd(args))
    cycles, _ = detect_cycles(graph)

    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "count": len(cycles),
                    "cycles": [
                        {"length": cycle["length"], "files": [rel(filepath) for filepath in cycle["files"]]}
                        for cycle in cycles
                    ],
                },
                indent=2,
            )
        )
        return

    if not cycles:
        print(colorize("No import cycles found.", "green"))
        return

    print(colorize(f"\nImport cycles: {len(cycles)}\n", "bold"))
    for cycle in cycles[: getattr(args, "top", 20)]:
        files = [rel(filepath) for filepath in cycle["files"]]
        suffix = f" -> +{len(files) - 6}" if len(files) > 6 else ""
        print(f"  [{cycle['length']} files] {' -> '.join(files[:6])}{suffix}")
