"""Shared command factories for detect subcommands.

Commands that are structurally identical across languages (same detect call +
display_entries pattern, differing only in parameters) are generated here.
Language-specific commands with unique display logic stay in their own modules.
"""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from desloppify.engine.detectors import complexity as complexity_detector
from desloppify.engine.detectors import large as large_detector
from desloppify.engine.detectors import naming as naming_detector
from desloppify.engine.detectors import single_use as single_use_detector
from desloppify.engine.detectors.dupes import detect_duplicates
from desloppify.engine.detectors.graph import detect_cycles
from desloppify.engine.detectors.orphaned import (
    OrphanedDetectionOptions,
    detect_orphaned_files,
)
from desloppify.file_discovery import rel
from desloppify.utils import colorize, display_entries, print_table

if TYPE_CHECKING:
    import argparse

    from desloppify.engine.detectors.base import ComplexitySignal


def _bind_callsite_module(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Attribute generated command functions to the language commands module."""
    frame = inspect.currentframe()
    caller = frame.f_back.f_back if frame and frame.f_back else None
    module_name = caller.f_globals.get("__name__") if caller else None
    if isinstance(module_name, str):
        fn.__module__ = module_name
    del frame
    return fn


def make_cmd_large(
    file_finder: Callable[..., Any], default_threshold: int
) -> Callable[[argparse.Namespace], None]:
    """Factory: detect large files."""

    def cmd_large(args: argparse.Namespace) -> None:
        threshold = getattr(args, "threshold", default_threshold)
        entries, _ = large_detector.detect_large_files(
            Path(args.path),
            file_finder=file_finder,
            threshold=threshold,
        )
        display_entries(
            args,
            entries,
            label=f"Large files (>{threshold} LOC)",
            empty_msg=f"No files over {threshold} lines.",
            columns=["File", "LOC"],
            widths=[70, 6],
            row_fn=lambda e: [rel(e["file"]), str(e["loc"])],
        )

    return _bind_callsite_module(cmd_large)


def make_cmd_complexity(
    file_finder: Callable[..., Any],
    signals: list[ComplexitySignal],
    default_threshold: int = 15,
) -> Callable[[argparse.Namespace], None]:
    """Factory: detect complexity signals."""

    def cmd_complexity(args: argparse.Namespace) -> None:
        entries, _ = complexity_detector.detect_complexity(
            Path(args.path),
            signals=signals,
            file_finder=file_finder,
            threshold=default_threshold,
        )
        display_entries(
            args,
            entries,
            label="Complexity signals",
            empty_msg="No significant complexity signals found.",
            columns=["File", "LOC", "Score", "Signals"],
            widths=[55, 5, 6, 45],
            row_fn=lambda e: [
                rel(e["file"]),
                str(e["loc"]),
                str(e["score"]),
                ", ".join(e["signals"][:4]),
            ],
        )

    return _bind_callsite_module(cmd_complexity)


def make_cmd_single_use(
    build_dep_graph: Callable[..., Any], barrel_names: set[str]
) -> Callable[[argparse.Namespace], None]:
    """Factory: detect single-use abstractions."""

    def cmd_single_use(args: argparse.Namespace) -> None:
        graph = build_dep_graph(Path(args.path))
        entries, _ = single_use_detector.detect_single_use_abstractions(
            Path(args.path), graph, barrel_names=barrel_names
        )
        display_entries(
            args,
            entries,
            label="Single-use abstractions",
            empty_msg="No single-use abstractions found.",
            columns=["File", "LOC", "Only Imported By"],
            widths=[45, 5, 60],
            row_fn=lambda e: [rel(e["file"]), str(e["loc"]), e["sole_importer"]],
        )

    return _bind_callsite_module(cmd_single_use)


def make_cmd_passthrough(
    detect_fn: Callable[..., Any],
    noun: str,
    name_key: str,
    total_key: str,
) -> Callable[[argparse.Namespace], None]:
    """Factory: detect passthrough components/functions."""

    def cmd_passthrough(args: argparse.Namespace) -> None:
        entries = detect_fn(Path(args.path))
        display_entries(
            args,
            entries,
            label=f"Passthrough {noun}s",
            empty_msg=f"No passthrough {noun}s found.",
            columns=["Name", "File", "PT/Total", "Ratio", "Tier", "Line"],
            widths=[30, 55, 10, 7, 5, 6],
            row_fn=lambda e: [
                e[name_key],
                rel(e["file"]),
                f"{e['passthrough']}/{e[total_key]}",
                f"{e['ratio']:.0%}",
                f"T{e['tier']}",
                str(e["line"]),
            ],
        )

    return _bind_callsite_module(cmd_passthrough)


def make_cmd_naming(
    file_finder: Callable[..., Any],
    skip_names: set[str],
    skip_dirs: set[str] | None = None,
) -> Callable[[argparse.Namespace], None]:
    """Factory: detect naming inconsistencies."""

    def cmd_naming(args: argparse.Namespace) -> None:
        kwargs = dict(file_finder=file_finder, skip_names=skip_names)
        if skip_dirs:
            kwargs["skip_dirs"] = skip_dirs
        entries, _ = naming_detector.detect_naming_inconsistencies(
            Path(args.path), **kwargs
        )
        display_entries(
            args,
            entries,
            label="Naming inconsistencies",
            empty_msg="\nNo naming inconsistencies found.",
            columns=["Directory", "Majority", "Minority", "Outliers"],
            widths=[45, 20, 20, 40],
            row_fn=lambda e: [
                e["directory"],
                f"{e['majority']} ({e['majority_count']})",
                f"{e['minority']} ({e['minority_count']})",
                ", ".join(e["outliers"][:5])
                + (f" (+{len(e['outliers']) - 5})" if len(e["outliers"]) > 5 else ""),
            ],
        )

    return _bind_callsite_module(cmd_naming)


def make_cmd_facade(
    build_dep_graph_fn: Callable[..., Any],
    detect_facades_fn: Callable[..., tuple[list[dict], int]],
) -> Callable[[argparse.Namespace], None]:
    """Factory: detect re-export facades."""

    def cmd_facade(args: argparse.Namespace) -> None:
        graph = build_dep_graph_fn(Path(args.path))
        entries, _ = detect_facades_fn(graph)
        if getattr(args, "json", False):
            print(
                json.dumps(
                    {
                        "count": len(entries),
                        "entries": [{**e, "file": rel(e["file"])} for e in entries],
                    },
                    indent=2,
                )
            )
            return
        if not entries:
            print(colorize("\nNo re-export facades found.", "green"))
            return
        file_facades = [e for e in entries if e["kind"] == "file"]
        dir_facades = [e for e in entries if e["kind"] == "directory"]
        if file_facades:
            print(colorize(f"\nRe-export facade files: {len(file_facades)}\n", "bold"))
            rows = [
                [
                    rel(e["file"]),
                    str(e["loc"]),
                    str(e["importers"]),
                    ", ".join(e["imports_from"][:3]),
                ]
                for e in file_facades
            ]
            print_table(
                ["File", "LOC", "Importers", "Re-exports From"], rows, [50, 5, 9, 40]
            )
        if dir_facades:
            print(colorize(f"\nFacade directories: {len(dir_facades)}\n", "bold"))
            rows = [
                [rel(e["file"]), str(e.get("file_count", "?")), str(e["importers"])]
                for e in dir_facades
            ]
            print_table(["Directory", "Files", "Importers"], rows, [50, 6, 9])

    return _bind_callsite_module(cmd_facade)


def make_cmd_smells(
    detect_smells_fn: Callable[..., Any],
) -> Callable[[argparse.Namespace], None]:
    """Factory: detect code smells."""

    def cmd_smells(args: argparse.Namespace) -> None:
        entries, _ = detect_smells_fn(Path(args.path))
        if getattr(args, "json", False):
            print(json.dumps({"entries": entries}, indent=2))
            return
        if not entries:
            print(colorize("No code smells detected.", "green"))
            return
        total = sum(e["count"] for e in entries)
        print(
            colorize(
                f"\nCode smells: {total} instances across {len(entries)} patterns\n",
                "bold",
            )
        )
        rows = []
        for e in entries[: getattr(args, "top", 20)]:
            sev_color = {"high": "red", "medium": "yellow", "low": "dim"}.get(
                e["severity"], "dim"
            )
            rows.append(
                [
                    colorize(e["severity"].upper(), sev_color),
                    e["label"],
                    str(e["count"]),
                    str(e["files"]),
                ]
            )
        print_table(["Sev", "Pattern", "Count", "Files"], rows, [8, 40, 6, 6])
        high = [e for e in entries if e["severity"] == "high"]
        for e in high:
            print(colorize(f"\n  {e['label']} ({e['count']} instances):", "red"))
            for m in e["matches"][:10]:
                print(f"    {rel(m['file'])}:{m['line']}  {m['content'][:60]}")

    return _bind_callsite_module(cmd_smells)


def build_standard_detect_registry(
    *,
    cmd_deps: Callable[[argparse.Namespace], None],
    cmd_cycles: Callable[[argparse.Namespace], None],
    cmd_orphaned: Callable[[argparse.Namespace], None],
    cmd_dupes: Callable[[argparse.Namespace], None],
    cmd_large: Callable[[argparse.Namespace], None],
    cmd_complexity: Callable[[argparse.Namespace], None],
) -> dict[str, Callable[[argparse.Namespace], None]]:
    """Build the shared detect command mapping used by language plugins."""
    return {
        "deps": cmd_deps,
        "cycles": cmd_cycles,
        "orphaned": cmd_orphaned,
        "dupes": cmd_dupes,
        "large": cmd_large,
        "complexity": cmd_complexity,
    }


# ── Scaffold defaults ─────────────────────────────────────

SCAFFOLD_VERIFY_HINT = "desloppify detect deps"
SCAFFOLD_HOLISTIC_REVIEW_DIMENSIONS = [
    "cross_module_architecture",
    "error_consistency",
    "abstraction_fitness",
    "test_strategy",
]


def scaffold_find_replacements(
    source_abs: str, dest_abs: str, graph: dict
) -> dict[str, list[tuple[str, str]]]:
    """Default scaffold move behavior until language-specific move support exists."""
    del source_abs, dest_abs, graph
    return {}


def scaffold_find_self_replacements(
    source_abs: str, dest_abs: str, graph: dict
) -> list[tuple[str, str]]:
    """Default scaffold self-replacement behavior until move support exists."""
    del source_abs, dest_abs, graph
    return []


def scaffold_verify_hint() -> str:
    """Return the default verification command for scaffolded move adapters."""
    return SCAFFOLD_VERIFY_HINT


# ── Scaffold detect command factories ─────────────────────


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
            print(colorize(f"\n{empty_message}", "green"))
            return

        print(colorize(f"\nDependency graph: {len(rows)} files\n", "bold"))
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
            print(colorize("\nNo dependency cycles found.", "green"))
            return

        print(colorize(f"\nCycles: {len(entries)}\n", "bold"))
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
            print(colorize("\nNo orphaned files found.", "green"))
            return

        total_loc = sum(entry["loc"] for entry in entries)
        print(colorize(f"\nOrphaned files: {len(entries)} files, {total_loc} LOC\n", "bold"))
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
            print(colorize("No duplicate functions found.", "green"))
            return

        print(colorize(f"\nDuplicate functions: {len(entries)} pairs\n", "bold"))
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
