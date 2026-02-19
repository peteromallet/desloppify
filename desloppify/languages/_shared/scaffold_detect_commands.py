"""Shared detect command factories for scaffold language plugins."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path

from desloppify.engine.detectors.dupes import detect_duplicates
from desloppify.engine.detectors.graph import detect_cycles
from desloppify.engine.detectors.orphaned import (
    OrphanedDetectionOptions,
    detect_orphaned_files,
)
from desloppify.utils import c, print_table, rel


def make_cmd_deps(
    *,
    build_dep_graph_fn,
    empty_message: str,
    import_count_label: str,
    top_imports_label: str,
) -> Callable[[argparse.Namespace], None]:
    """Build a deps command for lightweight graph-backed languages."""

    def cmd_deps(args: argparse.Namespace) -> None:
        graph = build_dep_graph_fn(Path(args.path))
        rows = [
            {
                "file": rel(filepath),
                "import_count": entry.get("import_count", 0),
                "importer_count": entry.get("importer_count", 0),
                "imports": [rel(imp) for imp in sorted(entry.get("imports", set()))],
            }
            for filepath, entry in graph.items()
        ]
        rows.sort(key=lambda row: (-row["import_count"], row["file"]))

        if getattr(args, "json", False):
            print(json.dumps({"count": len(rows), "entries": rows}, indent=2))
            return

        if not rows:
            print(c(f"\n{empty_message}", "green"))
            return

        print(c(f"\nDependency graph: {len(rows)} files\n", "bold"))
        top = getattr(args, "top", 20)
        table_rows = [
            [
                row["file"],
                str(row["import_count"]),
                str(row["importer_count"]),
                ", ".join(row["imports"][:3]) + (" ..." if len(row["imports"]) > 3 else ""),
            ]
            for row in rows[:top]
        ]
        print_table(
            ["File", import_count_label, "Importers", top_imports_label],
            table_rows,
            [56, 8, 9, 45],
        )

    return cmd_deps


def make_cmd_cycles(*, build_dep_graph_fn) -> Callable[[argparse.Namespace], None]:
    """Build a cycles command using a dependency graph builder."""

    def cmd_cycles(args: argparse.Namespace) -> None:
        graph = build_dep_graph_fn(Path(args.path))
        entries, _ = detect_cycles(graph)

        if getattr(args, "json", False):
            print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
            return

        if not entries:
            print(c("\nNo dependency cycles found.", "green"))
            return

        print(c(f"\nCycles: {len(entries)}\n", "bold"))
        top = getattr(args, "top", 20)
        rows = [
            [str(entry["length"]), ", ".join(rel(path) for path in entry["files"][:4])]
            for entry in entries[:top]
        ]
        print_table(["Length", "Files"], rows, [8, 95])

    return cmd_cycles


def make_cmd_orphaned(
    *,
    build_dep_graph_fn,
    extensions: list[str],
    extra_entry_patterns: list[str],
    extra_barrel_names: set[str],
) -> Callable[[argparse.Namespace], None]:
    """Build an orphaned-file command for language-specific roots/barrels."""

    def cmd_orphaned(args: argparse.Namespace) -> None:
        graph = build_dep_graph_fn(Path(args.path))
        entries, _ = detect_orphaned_files(
            Path(args.path),
            graph,
            extensions=extensions,
            options=OrphanedDetectionOptions(
                extra_entry_patterns=extra_entry_patterns,
                extra_barrel_names=extra_barrel_names,
            ),
        )

        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "count": len(entries),
                        "entries": [
                            {"file": rel(entry["file"]), "loc": entry["loc"]}
                            for entry in entries
                        ],
                    },
                    indent=2,
                )
            )
            return

        if not entries:
            print(c("\nNo orphaned files found.", "green"))
            return

        total_loc = sum(entry["loc"] for entry in entries)
        print(c(f"\nOrphaned files: {len(entries)} files, {total_loc} LOC\n", "bold"))
        top = getattr(args, "top", 20)
        rows = [[rel(entry["file"]), str(entry["loc"])] for entry in entries[:top]]
        print_table(["File", "LOC"], rows, [85, 6])

    return cmd_orphaned


def make_cmd_dupes(*, extract_functions_fn) -> Callable[[argparse.Namespace], None]:
    """Build a duplicate-function command from an extractor."""

    def cmd_dupes(args: argparse.Namespace) -> None:
        functions = extract_functions_fn(Path(args.path))
        entries, _ = detect_duplicates(
            functions,
            threshold=getattr(args, "threshold", None) or 0.8,
        )

        if getattr(args, "json", False):
            print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
            return

        if not entries:
            print(c("No duplicate functions found.", "green"))
            return

        print(c(f"\nDuplicate functions: {len(entries)} pairs\n", "bold"))
        top = getattr(args, "top", 20)
        rows = []
        for entry in entries[:top]:
            fn_a, fn_b = entry["fn_a"], entry["fn_b"]
            rows.append(
                [
                    f"{fn_a['name']} ({rel(fn_a['file'])}:{fn_a['line']})",
                    f"{fn_b['name']} ({rel(fn_b['file'])}:{fn_b['line']})",
                    f"{entry['similarity']:.0%}",
                    entry["kind"],
                ]
            )
        print_table(["Function A", "Function B", "Sim", "Kind"], rows, [40, 40, 5, 14])

    return cmd_dupes


__all__ = [
    "make_cmd_cycles",
    "make_cmd_deps",
    "make_cmd_dupes",
    "make_cmd_orphaned",
]
