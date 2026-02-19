"""C# detect-subcommand wrappers + command registry."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from desloppify.engine.detectors.dupes import detect_duplicates
from desloppify.engine.detectors.orphaned import (
    OrphanedDetectionOptions,
    detect_orphaned_files,
)
from desloppify.languages.csharp.detectors.deps import (
    build_dep_graph,
    resolve_roslyn_cmd_from_args,
)
from desloppify.languages.csharp.detectors.deps import cmd_cycles as cmd_cycles_deps
from desloppify.languages.csharp.detectors.deps import cmd_deps as cmd_deps_direct
from desloppify.languages.csharp.extractors import (
    extract_csharp_functions,
    find_csharp_files,
)
from desloppify.languages.csharp.phases import CSHARP_COMPLEXITY_SIGNALS
from desloppify.languages.framework.commands_base import (
    make_cmd_complexity,
    make_cmd_large,
    make_get_detect_commands,
)
from desloppify.utils import c, print_table, rel

_cmd_large_impl = make_cmd_large(find_csharp_files, default_threshold=500)
_cmd_complexity_impl = make_cmd_complexity(
    find_csharp_files, CSHARP_COMPLEXITY_SIGNALS, default_threshold=20
)


def cmd_large(args: argparse.Namespace) -> None:
    _cmd_large_impl(args)


def cmd_complexity(args: argparse.Namespace) -> None:
    _cmd_complexity_impl(args)


def cmd_deps(args: argparse.Namespace) -> None:
    cmd_deps_direct(args)


def cmd_cycles(args: argparse.Namespace) -> None:
    cmd_cycles_deps(args)


def cmd_orphaned(args: argparse.Namespace) -> None:
    graph = build_dep_graph(
        Path(args.path), roslyn_cmd=resolve_roslyn_cmd_from_args(args)
    )
    entries, _ = detect_orphaned_files(
        Path(args.path),
        graph,
        extensions=[".cs"],
        options=OrphanedDetectionOptions(
            extra_entry_patterns=[
                "/Program.cs",
                "/Startup.cs",
                "/Main.cs",
                "/Properties/",
            ],
            extra_barrel_names={"Program.cs"},
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


def cmd_dupes(args: argparse.Namespace) -> None:
    functions = []
    for filepath in find_csharp_files(Path(args.path)):
        functions.extend(extract_csharp_functions(filepath))

    entries, _ = detect_duplicates(
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


get_detect_commands = make_get_detect_commands(
    cmd_deps=cmd_deps,
    cmd_cycles=cmd_cycles,
    cmd_orphaned=cmd_orphaned,
    cmd_dupes=cmd_dupes,
    cmd_large=cmd_large,
    cmd_complexity=cmd_complexity,
)
