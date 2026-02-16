"""Python detect-subcommand wrappers + command registry."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ...utils import c, display_entries, find_py_files, print_table, rel

if TYPE_CHECKING:
    import argparse

from .phases import PY_COMPLEXITY_SIGNALS, PY_GOD_RULES, PY_SKIP_NAMES, PY_ENTRY_PATTERNS
from ..commands_base import (make_cmd_large, make_cmd_complexity, make_cmd_single_use,
                             make_cmd_passthrough, make_cmd_naming, make_cmd_smells,
                             make_cmd_facade)



def _build_dep_graph(path):
    from .detectors.deps import build_dep_graph
    return build_dep_graph(path)


def _detect_passthrough(path):
    from .extractors import detect_passthrough_functions
    return detect_passthrough_functions(path)

def _detect_facades(graph):
    from .detectors.facade import detect_reexport_facades
    return detect_reexport_facades(graph)


_cmd_large_impl = make_cmd_large(find_py_files, default_threshold=300)
_cmd_complexity_impl = make_cmd_complexity(find_py_files, PY_COMPLEXITY_SIGNALS, default_threshold=25)
_cmd_single_use_impl = make_cmd_single_use(_build_dep_graph, barrel_names={"__init__.py"})
_cmd_passthrough_impl = make_cmd_passthrough(
    _detect_passthrough, noun="function", name_key="function", total_key="total_params")
_cmd_naming_impl = make_cmd_naming(find_py_files, skip_names=PY_SKIP_NAMES)


def cmd_large(args: argparse.Namespace) -> None:
    _cmd_large_impl(args)


def cmd_complexity(args: argparse.Namespace) -> None:
    _cmd_complexity_impl(args)


def cmd_single_use(args: argparse.Namespace) -> None:
    _cmd_single_use_impl(args)


def cmd_passthrough(args: argparse.Namespace) -> None:
    _cmd_passthrough_impl(args)


def cmd_naming(args: argparse.Namespace) -> None:
    _cmd_naming_impl(args)


def cmd_gods(args: argparse.Namespace) -> None:
    from ...detectors.gods import detect_gods
    from .extractors import extract_py_classes
    entries, _ = detect_gods(extract_py_classes(Path(args.path)), PY_GOD_RULES)
    display_entries(args, entries,
        label="God classes",
        empty_msg="No god classes found.",
        columns=["File", "Class", "LOC", "Why"], widths=[50, 20, 5, 40],
        row_fn=lambda e: [rel(e["file"]), e["name"], str(e["loc"]),
                          ", ".join(e["reasons"])])


def cmd_orphaned(args: argparse.Namespace) -> None:
    import json
    from .detectors.deps import build_dep_graph
    from ...detectors.orphaned import detect_orphaned_files
    graph = build_dep_graph(Path(args.path))
    entries, _ = detect_orphaned_files(
        Path(args.path), graph, extensions=[".py"],
        extra_entry_patterns=PY_ENTRY_PATTERNS,
        extra_barrel_names={"__init__.py"})
    if getattr(args, "json", False):
        print(json.dumps({"count": len(entries), "entries": [
            {"file": rel(e["file"]), "loc": e["loc"]} for e in entries
        ]}, indent=2))
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
    import json
    from .detectors.unused import detect_unused
    entries, _ = detect_unused(Path(args.path))
    if getattr(args, "json", False):
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return
    if not entries:
        print(c("No unused symbols found.", "green"))
        return
    print(c(f"\nUnused symbols: {len(entries)}\n", "bold"))
    for e in entries[:getattr(args, "top", 20)]:
        print(f"  {rel(e['file'])}:{e['line']}  {e['category']}: {e['name']}")


def cmd_deps(args: argparse.Namespace) -> None:
    import json
    from .detectors.deps import build_dep_graph
    graph = build_dep_graph(Path(args.path))
    if getattr(args, "json", False):
        print(json.dumps({"files": len(graph)}, indent=2))
        return
    print(c(f"\nPython dependency graph: {len(graph)} files\n", "bold"))
    by_importers = sorted(graph.items(), key=lambda x: -x[1]["importer_count"])
    print(c("Most imported:", "bold"))
    for filepath, entry in by_importers[:15]:
        print(f"  {rel(filepath):60s}  {entry['importer_count']:3d} importers  {len(entry['imports']):3d} imports")


def cmd_cycles(args: argparse.Namespace) -> None:
    import json
    from .detectors.deps import build_dep_graph
    from ...detectors.graph import detect_cycles
    graph = build_dep_graph(Path(args.path))
    cycles, _ = detect_cycles(graph)
    if getattr(args, "json", False):
        print(json.dumps({"count": len(cycles), "cycles": cycles}, indent=2))
        return
    if not cycles:
        print(c("No import cycles found.", "green"))
        return
    print(c(f"\nImport cycles: {len(cycles)}\n", "bold"))
    for cy in cycles[:getattr(args, "top", 20)]:
        files = [rel(f) for f in cy["files"]]
        print(f"  [{cy['length']} files] {' -> '.join(files[:6])}"
              + (f" -> +{len(files) - 6}" if len(files) > 6 else ""))


def _detect_py_smells(path):
    from .detectors.smells import detect_smells
    return detect_smells(path)

_cmd_smells_impl = make_cmd_smells(_detect_py_smells)


def cmd_smells(args: argparse.Namespace) -> None:
    _cmd_smells_impl(args)


_cmd_facade_impl = make_cmd_facade(_build_dep_graph, detect_facades_fn=_detect_facades)


def cmd_facade(args: argparse.Namespace) -> None:
    _cmd_facade_impl(args)


def cmd_dupes(args: argparse.Namespace) -> None:
    import json
    from ...detectors.dupes import detect_duplicates
    from .extractors import extract_py_functions
    functions = []
    for filepath in find_py_files(Path(args.path)):
        functions.extend(extract_py_functions(filepath))
    entries, _ = detect_duplicates(functions, threshold=getattr(args, "threshold", None) or 0.8)
    if getattr(args, "json", False):
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return
    if not entries:
        print(c("No duplicate functions found.", "green"))
        return
    print(c(f"\nDuplicate functions: {len(entries)} pairs\n", "bold"))
    rows = []
    for e in entries[:getattr(args, "top", 20)]:
        a, b = e["fn_a"], e["fn_b"]
        rows.append([
            f"{a['name']} ({rel(a['file'])}:{a['line']})",
            f"{b['name']} ({rel(b['file'])}:{b['line']})",
            f"{e['similarity']:.0%}", e["kind"],
        ])
    print_table(["Function A", "Function B", "Sim", "Kind"], rows, [40, 40, 5, 14])


# ── Command registry ──────────────────────────────────────


def get_detect_commands() -> dict[str, Callable[..., None]]:
    """Build the Python detector command registry."""
    return {
        "unused":      cmd_unused,
        "large":       cmd_large,
        "complexity":  cmd_complexity,
        "gods":        cmd_gods,
        "props":       cmd_passthrough,
        "smells":      cmd_smells,
        "dupes":       cmd_dupes,
        "deps":        cmd_deps,
        "cycles":      cmd_cycles,
        "orphaned":    cmd_orphaned,
        "single_use":  cmd_single_use,
        "naming":      cmd_naming,
        "facade":      cmd_facade,
    }
