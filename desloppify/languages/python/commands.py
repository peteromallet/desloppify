"""Python detect-subcommand wrappers + command registry."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from desloppify.engine.detectors import dupes as dupes_detector_mod
from desloppify.engine.detectors import gods as gods_detector_mod
from desloppify.engine.detectors import graph as graph_detector_mod
from desloppify.engine.detectors import orphaned as orphaned_detector_mod
from desloppify.languages.python.detectors import deps as deps_detector_mod
from desloppify.languages.python.detectors import facade as facade_detector_mod
from desloppify.languages.python.detectors import smells as smells_detector_mod
from desloppify.languages.python.detectors import unused as unused_detector_mod
from desloppify.languages.python.extractors import (
    detect_passthrough_functions,
    extract_py_functions,
)
from desloppify.languages.python.extractors_classes import extract_py_classes
from desloppify.utils import c, display_entries, find_py_files, print_table, rel

if TYPE_CHECKING:
    import argparse

from desloppify.languages.framework.commands_base import (
    make_cmd_complexity,
    make_cmd_facade,
    make_cmd_large,
    make_cmd_naming,
    make_cmd_passthrough,
    make_cmd_single_use,
    make_cmd_smells,
)
from desloppify.languages.python.phases import (
    PY_COMPLEXITY_SIGNALS,
    PY_ENTRY_PATTERNS,
    PY_GOD_RULES,
    PY_SKIP_NAMES,
)

cmd_large = make_cmd_large(find_py_files, default_threshold=300)
cmd_complexity = make_cmd_complexity(
    find_py_files, PY_COMPLEXITY_SIGNALS, default_threshold=25
)
cmd_single_use = make_cmd_single_use(
    deps_detector_mod.build_dep_graph, barrel_names={"__init__.py"}
)
cmd_passthrough = make_cmd_passthrough(
    detect_passthrough_functions,
    noun="function",
    name_key="function",
    total_key="total_params",
)
cmd_naming = make_cmd_naming(find_py_files, skip_names=PY_SKIP_NAMES)


def cmd_gods(args: argparse.Namespace) -> None:
    entries, _ = gods_detector_mod.detect_gods(
        extract_py_classes(Path(args.path)), PY_GOD_RULES
    )
    display_entries(
        args,
        entries,
        label="God classes",
        empty_msg="No god classes found.",
        columns=["File", "Class", "LOC", "Why"],
        widths=[50, 20, 5, 40],
        row_fn=lambda e: [
            rel(e["file"]),
            e["name"],
            str(e["loc"]),
            ", ".join(e["reasons"]),
        ],
    )


def cmd_orphaned(args: argparse.Namespace) -> None:
    graph = deps_detector_mod.build_dep_graph(Path(args.path))
    entries, _ = orphaned_detector_mod.detect_orphaned_files(
        Path(args.path),
        graph,
        extensions=[".py"],
        options=orphaned_detector_mod.OrphanedDetectionOptions(
            extra_entry_patterns=PY_ENTRY_PATTERNS,
            extra_barrel_names={"__init__.py"},
        ),
    )
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "count": len(entries),
                    "entries": [
                        {"file": rel(e["file"]), "loc": e["loc"]} for e in entries
                    ],
                },
                indent=2,
            )
        )
        return
    if not entries:
        print(c("\nNo orphaned files found.", "green"))
        return
    total_loc = sum(e["loc"] for e in entries)
    print(c(f"\nOrphaned files: {len(entries)} files, {total_loc} LOC\n", "bold"))
    top = getattr(args, "top", 20)
    rows = [[rel(e["file"]), str(e["loc"])] for e in entries[:top]]
    print_table(["File", "LOC"], rows, [80, 6])


def cmd_unused(args: argparse.Namespace) -> None:
    entries, _ = unused_detector_mod.detect_unused(Path(args.path))
    if getattr(args, "json", False):
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return
    if not entries:
        print(c("No unused symbols found.", "green"))
        return
    print(c(f"\nUnused symbols: {len(entries)}\n", "bold"))
    for e in entries[: getattr(args, "top", 20)]:
        print(f"  {rel(e['file'])}:{e['line']}  {e['category']}: {e['name']}")


def cmd_deps(args: argparse.Namespace) -> None:
    graph = deps_detector_mod.build_dep_graph(Path(args.path))
    if getattr(args, "json", False):
        print(json.dumps({"files": len(graph)}, indent=2))
        return
    print(c(f"\nPython dependency graph: {len(graph)} files\n", "bold"))
    by_importers = sorted(graph.items(), key=lambda x: -x[1]["importer_count"])
    print(c("Most imported:", "bold"))
    for filepath, entry in by_importers[:15]:
        print(
            f"  {rel(filepath):60s}  {entry['importer_count']:3d} importers  {len(entry['imports']):3d} imports"
        )


def cmd_cycles(args: argparse.Namespace) -> None:
    graph = deps_detector_mod.build_dep_graph(Path(args.path))
    cycles, _ = graph_detector_mod.detect_cycles(graph)
    if getattr(args, "json", False):
        print(json.dumps({"count": len(cycles), "cycles": cycles}, indent=2))
        return
    if not cycles:
        print(c("No import cycles found.", "green"))
        return
    print(c(f"\nImport cycles: {len(cycles)}\n", "bold"))
    for cy in cycles[: getattr(args, "top", 20)]:
        files = [rel(f) for f in cy["files"]]
        print(
            f"  [{cy['length']} files] {' -> '.join(files[:6])}"
            + (f" -> +{len(files) - 6}" if len(files) > 6 else "")
        )


cmd_smells = make_cmd_smells(smells_detector_mod.detect_smells)
cmd_facade = make_cmd_facade(
    deps_detector_mod.build_dep_graph,
    detect_facades_fn=facade_detector_mod.detect_reexport_facades,
)


def cmd_dupes(args: argparse.Namespace) -> None:
    functions = []
    for filepath in find_py_files(Path(args.path)):
        functions.extend(extract_py_functions(filepath))
    entries, _ = dupes_detector_mod.detect_duplicates(
        functions, threshold=getattr(args, "threshold", None) or 0.8
    )
    if getattr(args, "json", False):
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return
    if not entries:
        print(c("No duplicate functions found.", "green"))
        return
    print(c(f"\nDuplicate functions: {len(entries)} pairs\n", "bold"))
    rows = []
    for e in entries[: getattr(args, "top", 20)]:
        a, b = e["fn_a"], e["fn_b"]
        rows.append(
            [
                f"{a['name']} ({rel(a['file'])}:{a['line']})",
                f"{b['name']} ({rel(b['file'])}:{b['line']})",
                f"{e['similarity']:.0%}",
                e["kind"],
            ]
        )
    print_table(["Function A", "Function B", "Sim", "Kind"], rows, [40, 40, 5, 14])


# ── Command registry ──────────────────────────────────────


def get_detect_commands() -> dict[str, Callable[..., None]]:
    """Build the Python detector command registry."""
    return {
        "unused": cmd_unused,
        "large": cmd_large,
        "complexity": cmd_complexity,
        "gods": cmd_gods,
        "props": cmd_passthrough,
        "smells": cmd_smells,
        "dupes": cmd_dupes,
        "deps": cmd_deps,
        "cycles": cmd_cycles,
        "orphaned": cmd_orphaned,
        "single_use": cmd_single_use,
        "naming": cmd_naming,
        "facade": cmd_facade,
    }
