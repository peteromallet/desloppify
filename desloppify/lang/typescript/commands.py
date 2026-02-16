"""TypeScript detect-subcommand wrappers + command registry."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ...utils import c, display_entries, find_ts_files, print_table, rel, SRC_PATH

if TYPE_CHECKING:
    import argparse

from .phases import TS_COMPLEXITY_SIGNALS, TS_GOD_RULES, TS_SKIP_NAMES, TS_SKIP_DIRS
from ..commands_base import (make_cmd_large, make_cmd_complexity, make_cmd_single_use,
                             make_cmd_passthrough, make_cmd_naming, make_cmd_smells,
                             make_cmd_facade)



def _build_dep_graph(path):
    from .detectors.deps import build_dep_graph
    return build_dep_graph(path)


def _detect_passthrough(path):
    from .extractors import detect_passthrough_components
    return detect_passthrough_components(path)

def _detect_facades(graph):
    from .detectors.facade import detect_reexport_facades
    return detect_reexport_facades(graph)


_cmd_large_impl = make_cmd_large(find_ts_files, default_threshold=500)
_cmd_complexity_impl = make_cmd_complexity(find_ts_files, TS_COMPLEXITY_SIGNALS)
_cmd_single_use_impl = make_cmd_single_use(_build_dep_graph, barrel_names={"index.ts", "index.tsx"})
_cmd_passthrough_impl = make_cmd_passthrough(
    _detect_passthrough, noun="component", name_key="component", total_key="total_props")
_cmd_naming_impl = make_cmd_naming(find_ts_files, skip_names=TS_SKIP_NAMES, skip_dirs=TS_SKIP_DIRS)


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
    from .extractors import extract_ts_components
    entries, _ = detect_gods(extract_ts_components(Path(args.path)), TS_GOD_RULES)
    display_entries(args, entries,
        label="God components",
        empty_msg="No god components found.",
        columns=["File", "LOC", "Hooks", "Why"], widths=[55, 5, 6, 45],
        row_fn=lambda e: [rel(e["file"]), str(e["loc"]),
                          str(e["detail"].get("hook_total", 0)),
                          ", ".join(e["reasons"])])


def cmd_orphaned(args: argparse.Namespace) -> None:
    import json
    from .detectors.deps import build_dep_graph, build_dynamic_import_targets, ts_alias_resolver
    from ...detectors.orphaned import detect_orphaned_files
    graph = build_dep_graph(Path(args.path))
    entries, _ = detect_orphaned_files(
        Path(args.path), graph, extensions=[".ts", ".tsx"],
        dynamic_import_finder=build_dynamic_import_targets,
        alias_resolver=ts_alias_resolver)
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
    if len(entries) > top:
        print(f"\n  ... and {len(entries) - top} more")


# ── Complex wrappers (unique display logic) ───────────────


def cmd_dupes(args: argparse.Namespace) -> None:
    import json
    from ...detectors.dupes import detect_duplicates
    from .extractors import extract_ts_functions
    functions = []
    for filepath in find_ts_files(Path(args.path)):
        if "node_modules" in filepath or ".d.ts" in filepath:
            continue
        functions.extend(extract_ts_functions(filepath))
    entries, _ = detect_duplicates(functions, threshold=getattr(args, "threshold", None) or 0.8)
    if getattr(args, "json", False):
        print(json.dumps({"count": len(entries), "entries": entries}, indent=2))
        return
    if not entries:
        print(c("No duplicate functions found.", "green"))
        return
    exact = [e for e in entries if e["kind"] == "exact"]
    near = [e for e in entries if e["kind"] == "near-duplicate"]
    if exact:
        print(c(f"\nExact duplicates: {len(exact)} pairs\n", "bold"))
        rows = []
        for e in exact[:getattr(args, "top", 20)]:
            a, b = e["fn_a"], e["fn_b"]
            rows.append([
                f"{a['name']} ({rel(a['file'])}:{a['line']})",
                f"{b['name']} ({rel(b['file'])}:{b['line']})",
                str(a["loc"]),
            ])
        print_table(["Function A", "Function B", "LOC"], rows, [50, 50, 5])
    if near:
        print(c(f"\nNear-duplicates (>={getattr(args, 'threshold', 0.8):.0%} similar): {len(near)} pairs\n", "bold"))
        rows = []
        for e in near[:getattr(args, "top", 20)]:
            a, b = e["fn_a"], e["fn_b"]
            rows.append([
                f"{a['name']} ({rel(a['file'])}:{a['line']})",
                f"{b['name']} ({rel(b['file'])}:{b['line']})",
                f"{e['similarity']:.0%}",
            ])
        print_table(["Function A", "Function B", "Sim"], rows, [50, 50, 5])


def _detect_ts_smells(path):
    from .detectors.smells import detect_smells
    return detect_smells(path)

_cmd_smells_impl = make_cmd_smells(_detect_ts_smells)


def cmd_smells(args: argparse.Namespace) -> None:
    _cmd_smells_impl(args)


_cmd_facade_impl = make_cmd_facade(_build_dep_graph, detect_facades_fn=_detect_facades)


def cmd_facade(args: argparse.Namespace) -> None:
    _cmd_facade_impl(args)


def _run_detector_cmd(args, module_path: str, fn_name: str) -> None:
    """Dispatch to a detector module command while keeping registry ownership here."""
    mod = importlib.import_module(module_path, package=__package__)
    fn = getattr(mod, fn_name)
    fn(args)


def cmd_logs(args: argparse.Namespace) -> None:
    _run_detector_cmd(args, ".detectors.logs", "cmd_logs")


def cmd_unused(args: argparse.Namespace) -> None:
    _run_detector_cmd(args, ".detectors.unused", "cmd_unused")


def cmd_exports(args: argparse.Namespace) -> None:
    _run_detector_cmd(args, ".detectors.exports", "cmd_exports")


def cmd_deprecated(args: argparse.Namespace) -> None:
    _run_detector_cmd(args, ".detectors.deprecated", "cmd_deprecated")


def cmd_props(args: argparse.Namespace) -> None:
    _run_detector_cmd(args, ".detectors.props", "cmd_props")


def cmd_concerns(args: argparse.Namespace) -> None:
    _run_detector_cmd(args, ".detectors.concerns", "cmd_concerns")


def cmd_deps(args: argparse.Namespace) -> None:
    _run_detector_cmd(args, ".detectors.deps", "cmd_deps")


def cmd_cycles(args: argparse.Namespace) -> None:
    _run_detector_cmd(args, ".detectors.deps", "cmd_cycles")


def cmd_patterns(args: argparse.Namespace) -> None:
    _run_detector_cmd(args, ".detectors.patterns", "cmd_patterns")


def cmd_react(args: argparse.Namespace) -> None:
    _run_detector_cmd(args, ".detectors.react", "cmd_react")


def cmd_coupling(args: argparse.Namespace) -> None:
    import json
    from .detectors.deps import build_dep_graph
    from ...detectors.coupling import (detect_coupling_violations, detect_boundary_candidates,
                                        detect_cross_tool_imports)
    graph = build_dep_graph(Path(args.path))
    shared_prefix = f"{SRC_PATH}/shared/"
    tools_prefix = f"{SRC_PATH}/tools/"
    violations, _ = detect_coupling_violations(Path(args.path), graph,
                                             shared_prefix=shared_prefix, tools_prefix=tools_prefix)
    candidates, _ = detect_boundary_candidates(Path(args.path), graph,
                                             shared_prefix=shared_prefix, tools_prefix=tools_prefix,
                                             skip_basenames={"index.ts", "index.tsx"})
    if getattr(args, "json", False):
        print(json.dumps({
            "violations": len(violations),
            "boundary_candidates": len(candidates),
            "coupling_violations": violations,
            "boundary_candidates_detail": [{**e, "file": rel(e["file"])} for e in candidates],
        }, indent=2))
        return
    if violations:
        print(c(f"\nCoupling violations (shared → tools): {len(violations)}\n", "bold"))
        rows = []
        for e in violations[:getattr(args, "top", 20)]:
            rows.append([rel(e["file"]), e["target"], e["tool"]])
        print_table(["Shared File", "Imports From", "Tool"], rows, [50, 50, 20])
    else:
        print(c("\nNo coupling violations (shared → tools).", "green"))
    cross_tool, _ = detect_cross_tool_imports(Path(args.path), graph, tools_prefix=tools_prefix)
    print()
    if cross_tool:
        print(c(f"Cross-tool imports (tools → tools): {len(cross_tool)}\n", "bold"))
        rows = []
        for e in cross_tool[:getattr(args, "top", 20)]:
            rows.append([rel(e["file"]), e["target"], f"{e['source_tool']}→{e['target_tool']}"])
        print_table(["Source File", "Imports From", "Direction"], rows, [50, 50, 20])
    else:
        print(c("No cross-tool imports.", "green"))
    print()
    if candidates:
        print(c(f"Boundary candidates (shared files used by 1 tool): {len(candidates)}\n", "bold"))
        rows = []
        for e in candidates[:getattr(args, "top", 20)]:
            rows.append([rel(e["file"]), str(e["loc"]), e["sole_tool"],
                         str(e["importer_count"])])
        print_table(["Shared File", "LOC", "Only Used By", "Importers"], rows,
                    [50, 5, 30, 9])
    else:
        print(c("No boundary candidates found.", "green"))
    print()


# ── Command registry ──────────────────────────────────────


def get_detect_commands() -> dict[str, Callable[..., None]]:
    """Build the TypeScript detector command registry."""
    return {
        "logs":        cmd_logs,
        "unused":      cmd_unused,
        "exports":     cmd_exports,
        "deprecated":  cmd_deprecated,
        "large":       cmd_large,
        "complexity":  cmd_complexity,
        "gods":        cmd_gods,
        "single_use":  cmd_single_use,
        "props":       cmd_props,
        "passthrough": cmd_passthrough,
        "concerns":    cmd_concerns,
        "deps":        cmd_deps,
        "dupes":       cmd_dupes,
        "smells":      cmd_smells,
        "coupling":    cmd_coupling,
        "patterns":    cmd_patterns,
        "naming":      cmd_naming,
        "cycles":      cmd_cycles,
        "orphaned":    cmd_orphaned,
        "react":       cmd_react,
        "facade":      cmd_facade,
    }
