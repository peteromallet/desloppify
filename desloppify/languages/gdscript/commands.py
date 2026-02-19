"""GDScript detect-subcommand wrappers + command registry."""

from __future__ import annotations

import argparse

from desloppify.languages._shared.scaffold_detect_commands import (
    make_cmd_cycles,
    make_cmd_deps,
    make_cmd_dupes,
    make_cmd_orphaned,
)
from desloppify.languages.framework.commands_base import (
    make_cmd_complexity,
    make_cmd_large,
    make_get_detect_commands,
)
from desloppify.languages.gdscript.detectors.deps import build_dep_graph
from desloppify.languages.gdscript.extractors import (
    extract_functions,
    find_gdscript_files,
)
from desloppify.languages.gdscript.phases import GDSCRIPT_COMPLEXITY_SIGNALS

_cmd_large_impl = make_cmd_large(find_gdscript_files, default_threshold=500)
_cmd_complexity_impl = make_cmd_complexity(
    find_gdscript_files, GDSCRIPT_COMPLEXITY_SIGNALS, default_threshold=16
)
_cmd_deps_impl = make_cmd_deps(
    build_dep_graph_fn=build_dep_graph,
    empty_message="No GDScript dependencies detected.",
    import_count_label="Refs",
    top_imports_label="Top refs",
)
_cmd_cycles_impl = make_cmd_cycles(build_dep_graph_fn=build_dep_graph)
_cmd_orphaned_impl = make_cmd_orphaned(
    build_dep_graph_fn=build_dep_graph,
    extensions=[".gd"],
    extra_entry_patterns=["/main.gd", "/autoload/", "/addons/", "/tests/", "/test/"],
    extra_barrel_names=set(),
)
_cmd_dupes_impl = make_cmd_dupes(extract_functions_fn=extract_functions)


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


get_detect_commands = make_get_detect_commands(
    cmd_deps=cmd_deps,
    cmd_cycles=cmd_cycles,
    cmd_orphaned=cmd_orphaned,
    cmd_dupes=cmd_dupes,
    cmd_large=cmd_large,
    cmd_complexity=cmd_complexity,
)
