"""C# detect-subcommand wrappers + command registry."""

from __future__ import annotations

from pathlib import Path

from ...utils import c, print_table, rel
from ..commands_base import make_cmd_complexity, make_cmd_large
from .extractors import extract_csharp_functions, find_csharp_files
from .phases import CSHARP_COMPLEXITY_SIGNALS


_cmd_large_impl = make_cmd_large(find_csharp_files, default_threshold=500)
_cmd_complexity_impl = make_cmd_complexity(
    find_csharp_files, CSHARP_COMPLEXITY_SIGNALS, default_threshold=20
)


def cmd_large(args):
    _cmd_large_impl(args)


def cmd_complexity(args):
    _cmd_complexity_impl(args)


def cmd_deps(args):
    from .detectors.deps import cmd_deps as _cmd
    _cmd(args)


def cmd_cycles(args):
    from .detectors.deps import cmd_cycles as _cmd
    _cmd(args)


def cmd_orphaned(args):
    import json
    from .detectors.deps import build_dep_graph, resolve_roslyn_cmd_from_args
    from ...detectors.orphaned import detect_orphaned_files

    graph = build_dep_graph(Path(args.path), roslyn_cmd=resolve_roslyn_cmd_from_args(args))
    entries, _ = detect_orphaned_files(
        Path(args.path),
        graph,
        extensions=[".cs"],
        extra_entry_patterns=["/Program.cs", "/Startup.cs", "/Main.cs", "/Properties/"],
        extra_barrel_names={"Program.cs"},
    )
    if getattr(args, "json", False):
        print(
            json.dumps(
                {
                    "count": len(entries),
                    "entries": [{"file": rel(e["file"]), "loc": e["loc"]} for e in entries],
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


def cmd_dupes(args):
    import json
    from ...detectors.dupes import detect_duplicates

    functions = []
    for filepath in find_csharp_files(Path(args.path)):
        functions.extend(extract_csharp_functions(filepath))

    entries, _ = detect_duplicates(functions, threshold=getattr(args, "threshold", None) or 0.8)
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


def get_detect_commands() -> dict[str, callable]:
    """Build the C# detector command registry."""
    return {
        "deps": cmd_deps,
        "cycles": cmd_cycles,
        "orphaned": cmd_orphaned,
        "dupes": cmd_dupes,
        "large": cmd_large,
        "complexity": cmd_complexity,
    }
