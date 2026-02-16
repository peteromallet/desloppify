"""TypeScript detect-subcommand wrappers + command registry."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Callable

from ...utils import c, display_entries, find_ts_files, print_table, rel, SRC_PATH

if TYPE_CHECKING:
    import argparse

from . import TS_COMPLEXITY_SIGNALS, TS_GOD_RULES, TS_SKIP_NAMES, TS_SKIP_DIRS
from ..commands_base import (make_cmd_large, make_cmd_complexity, make_cmd_single_use,
                             make_cmd_passthrough, make_cmd_naming, make_cmd_smells,
                             make_cmd_facade)



def _build_dep_graph(path):
    from .detectors.deps import build_dep_graph
    return build_dep_graph(path)


def _detect_passthrough(path):
    from .extractors import detect_passthrough_components
    return detect_passthrough_components(path)


cmd_large = make_cmd_large(find_ts_files, default_threshold=500)
cmd_complexity = make_cmd_complexity(find_ts_files, TS_COMPLEXITY_SIGNALS)
cmd_single_use = make_cmd_single_use(_build_dep_graph, barrel_names={"index.ts", "index.tsx"})
cmd_passthrough = make_cmd_passthrough(
    _detect_passthrough, noun="component", name_key="component", total_key="total_props")
cmd_naming = make_cmd_naming(find_ts_files, skip_names=TS_SKIP_NAMES, skip_dirs=TS_SKIP_DIRS)


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

cmd_smells = make_cmd_smells(_detect_ts_smells)


cmd_facade = make_cmd_facade(_build_dep_graph, lang="typescript")


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
                                             shared_prefix=shared_prefix, tools_prefix=tools_prefix)
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
    from .detectors.logs import cmd_logs
    from .detectors.unused import cmd_unused
    from .detectors.exports import cmd_exports
    from .detectors.deprecated import cmd_deprecated
    from .detectors.props import cmd_props
    from .detectors.concerns import cmd_concerns
    from .detectors.deps import cmd_deps, cmd_cycles
    from .detectors.patterns import cmd_patterns
    from .detectors.react import cmd_react
    return {
        "logs":        cmd_logs,
        "unused":      cmd_unused,
        "exports":     cmd_exports,
        "deprecated":  cmd_deprecated,
        "large":       cmd_large,
        "complexity":  cmd_complexity,
        "gods":        cmd_gods,
        "single-use":  cmd_single_use,
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
