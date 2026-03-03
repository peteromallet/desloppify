"""Go detect-subcommand wrappers + command registry.

Originally contributed by tinker495 (KyuSeok Jung) in PR #128.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from desloppify.engine.detectors import gods as gods_detector_mod
from desloppify.languages._framework.commands_base import (
    make_cmd_complexity,
    make_cmd_cycles,
    make_cmd_deps,
    make_cmd_dupes,
    make_cmd_large,
    make_cmd_naming,
    make_cmd_orphaned,
    make_cmd_single_use,
    make_cmd_smells,
)
from desloppify.core.discovery_api import rel
from desloppify.core.output_api import display_entries
from desloppify.languages.go.detectors.deps import build_dep_graph
from desloppify.languages.go.detectors.gods import GO_GOD_RULES, extract_go_structs
from desloppify.languages.go.detectors.smells import detect_smells
from desloppify.languages.go.detectors.unused import detect_unused
from desloppify.languages.go.extractors import extract_functions, find_go_files
from desloppify.languages.go.phases import GO_COMPLEXITY_SIGNALS

_cmd_large_impl = make_cmd_large(find_go_files, default_threshold=500)
_cmd_complexity_impl = make_cmd_complexity(
    find_go_files, GO_COMPLEXITY_SIGNALS, default_threshold=15
)
_cmd_deps_impl = make_cmd_deps(
    build_dep_graph_fn=build_dep_graph,
    empty_message="No Go dependencies detected.",
    import_count_label="Imports",
    top_imports_label="Top imports",
)
_cmd_cycles_impl = make_cmd_cycles(build_dep_graph_fn=build_dep_graph)
_cmd_orphaned_impl = make_cmd_orphaned(
    build_dep_graph_fn=build_dep_graph,
    extensions=[".go"],
    extra_entry_patterns=["/main.go", "/cmd/"],
    extra_barrel_names=set(),
)
_cmd_dupes_impl = make_cmd_dupes(extract_functions_fn=extract_functions)
_cmd_single_use_impl = make_cmd_single_use(
    build_dep_graph=build_dep_graph,
    barrel_names=set(),
)
_cmd_smells_impl = make_cmd_smells(detect_smells)
_cmd_naming_impl = make_cmd_naming(
    find_go_files,
    skip_names={"main.go", "doc.go"},
    skip_dirs={"vendor"},
)


def cmd_large(args: argparse.Namespace) -> None:
    _cmd_large_impl(args)


def cmd_complexity(args: argparse.Namespace) -> None:
    _cmd_complexity_impl(args)


def cmd_deps(args: argparse.Namespace) -> None:
    _cmd_deps_impl(args)


def cmd_cycles(args: argparse.Namespace) -> None:
    _cmd_cycles_impl(args)


def cmd_orphaned(args: argparse.Namespace) -> None:
    _cmd_orphaned_impl(args)


def cmd_dupes(args: argparse.Namespace) -> None:
    _cmd_dupes_impl(args)


def cmd_single_use(args: argparse.Namespace) -> None:
    _cmd_single_use_impl(args)


def cmd_smells(args: argparse.Namespace) -> None:
    _cmd_smells_impl(args)


def cmd_naming(args: argparse.Namespace) -> None:
    _cmd_naming_impl(args)


def cmd_unused(args: argparse.Namespace) -> None:
    entries, total, available = detect_unused(Path(args.path))
    if not available:
        empty = "staticcheck is not installed — install it for unused symbol detection."
    else:
        empty = "No unused symbols found."
    display_entries(
        args,
        entries,
        label=f"Unused symbols ({total} files checked)",
        empty_msg=empty,
        columns=["File", "Line", "Name", "Category"],
        widths=[55, 6, 30, 10],
        row_fn=lambda e: [rel(e["file"]), str(e["line"]), e["name"], e["category"]],
    )


def cmd_gods(args: argparse.Namespace) -> None:
    entries, _ = gods_detector_mod.detect_gods(
        extract_go_structs(Path(args.path)), GO_GOD_RULES
    )
    display_entries(
        args,
        entries,
        label="God structs",
        empty_msg="No god structs found.",
        columns=["File", "Struct", "LOC", "Why"],
        widths=[50, 20, 6, 45],
        row_fn=lambda e: [
            rel(e["file"]),
            e["name"],
            str(e["loc"]),
            ", ".join(e["reasons"]),
        ],
    )


def get_detect_commands() -> dict[str, object]:
    """Return the detect command registry for Go."""
    return {
        "deps": cmd_deps,
        "cycles": cmd_cycles,
        "orphaned": cmd_orphaned,
        "dupes": cmd_dupes,
        "large": cmd_large,
        "complexity": cmd_complexity,
        "single_use": cmd_single_use,
        "smells": cmd_smells,
        "naming": cmd_naming,
        "unused": cmd_unused,
        "gods": cmd_gods,
    }
