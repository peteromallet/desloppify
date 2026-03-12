"""Rust detect-subcommand registry and tool-backed command wrappers."""

from __future__ import annotations

import argparse
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from desloppify.base.discovery.file_paths import rel
from desloppify.base.output.terminal import colorize, display_entries
from desloppify.languages._framework.commands_base import (
    make_cmd_complexity,
    make_cmd_large,
    make_cmd_smells,
)
from desloppify.languages._framework.commands_base_registry import (
    build_standard_detect_registry,
    compose_detect_registry,
    make_cmd_cycles,
    make_cmd_deps,
    make_cmd_dupes,
    make_cmd_orphaned,
)
from desloppify.languages._framework.generic_parts.tool_runner import ToolRunResult
from desloppify.languages._framework.generic_parts.tool_runner import run_tool_result
from desloppify.languages.rust.detectors import (
    detect_async_locking,
    detect_doctest_hygiene,
    detect_drop_safety,
    detect_error_boundaries,
    detect_feature_hygiene,
    detect_future_proofing,
    detect_import_hygiene,
    detect_public_api_conventions,
    detect_smells,
    detect_thread_safety_contracts,
    detect_unsafe_api_usage,
)
from desloppify.languages.rust.detectors.deps import build_dep_graph
from desloppify.languages.rust.extractors import extract_functions, find_rust_files
from desloppify.languages.rust.phases import (
    RUST_CHECK_LABEL,
    RUST_CLIPPY_LABEL,
    RUST_COMPLEXITY_SIGNALS,
    RUST_RUSTDOC_LABEL,
)
from desloppify.languages.rust.tools import (
    CARGO_ERROR_CMD as RUST_CHECK_CMD,
    CLIPPY_WARNING_CMD as RUST_CLIPPY_CMD,
    parse_cargo_errors,
    parse_clippy_messages,
    parse_rustdoc_messages,
    run_rustdoc_result,
)

DetectCommand = Callable[[argparse.Namespace], None]
EntryDetector = Callable[[Path], tuple[list[dict[str, Any]], int]]
ToolResultRunner = Callable[[Path], ToolRunResult]

cmd_large = make_cmd_large(
    find_rust_files,
    default_threshold=500,
    module_name=__name__,
)
cmd_complexity = make_cmd_complexity(
    find_rust_files,
    RUST_COMPLEXITY_SIGNALS,
    default_threshold=15,
    module_name=__name__,
)
cmd_deps = make_cmd_deps(
    build_dep_graph_fn=build_dep_graph,
    empty_message="No Rust dependencies detected.",
    import_count_label="Imports",
    top_imports_label="Top imports",
    module_name=__name__,
)
cmd_cycles = make_cmd_cycles(
    build_dep_graph_fn=lambda path: build_dep_graph(path, include_mod_declarations=False),
    module_name=__name__,
)
cmd_orphaned = make_cmd_orphaned(
    build_dep_graph_fn=build_dep_graph,
    extensions=[".rs"],
    extra_entry_patterns=[
        "src/lib.rs",
        "src/main.rs",
        "src/bin/",
        "tests/",
        "examples/",
        "benches/",
        "fuzz/",
        "build.rs",
    ],
    extra_barrel_names={"lib.rs"},
    module_name=__name__,
)
cmd_dupes = make_cmd_dupes(extract_functions_fn=extract_functions, module_name=__name__)
cmd_smells = make_cmd_smells(detect_smells, module_name=__name__)


def _make_tool_detect_command(
    label: str,
    runner: ToolResultRunner,
) -> DetectCommand:
    def command(args: argparse.Namespace) -> None:
        result = runner(Path(args.path))
        if result.status == "error":
            payload = {
                "count": 0,
                "entries": [],
                "status": result.status,
                "error_kind": result.error_kind,
                "message": result.message,
            }
            if getattr(args, "json", False):
                print(json.dumps(payload, indent=2))
                return
            print(colorize(f"\n{label} unavailable", "yellow"))
            if result.message:
                print(colorize(result.message, "dim"))
            return

        entries = [
            {
                "file": rel(entry["file"]),
                "line": entry["line"],
                "message": entry["message"],
            }
            for entry in result.entries
        ]
        display_entries(
            args,
            entries,
            label=label,
            empty_msg=f"No {label} findings.",
            columns=["File", "Line", "Message"],
            widths=[60, 6, 80],
            row_fn=lambda entry: [
                entry["file"],
                str(entry["line"]),
                entry["message"],
            ],
            json_payload={"count": len(entries), "entries": entries},
        )

    command.__module__ = __name__
    return command
def _make_entry_detect_command(
    label: str,
    detector_fn: EntryDetector,
) -> DetectCommand:
    def command(args: argparse.Namespace) -> None:
        entries, _ = detector_fn(Path(args.path))
        display_entries(
            args,
            entries,
            label=label,
            empty_msg=f"No {label} findings.",
            columns=["File", "Line", "Message"],
            widths=[60, 6, 80],
            row_fn=lambda entry: [
                entry["file"],
                str(entry["line"]),
                entry["summary"],
            ],
            json_payload={"count": len(entries), "entries": entries},
        )

    command.__module__ = __name__
    return command


cmd_clippy_warning = _make_tool_detect_command(
    RUST_CLIPPY_LABEL,
    lambda path: run_tool_result(RUST_CLIPPY_CMD, path, parse_clippy_messages),
)
cmd_cargo_error = _make_tool_detect_command(
    RUST_CHECK_LABEL,
    lambda path: run_tool_result(RUST_CHECK_CMD, path, parse_cargo_errors),
)
cmd_rustdoc_warning = _make_tool_detect_command(
    RUST_RUSTDOC_LABEL,
    run_rustdoc_result,
)
cmd_rust_import_hygiene = _make_entry_detect_command(
    "Rust import hygiene",
    detect_import_hygiene,
)
cmd_rust_feature_hygiene = _make_entry_detect_command(
    "Rust feature hygiene",
    detect_feature_hygiene,
)
cmd_rust_doctest = _make_entry_detect_command(
    "Rust doctest hygiene",
    detect_doctest_hygiene,
)
cmd_rust_api_convention = _make_entry_detect_command(
    "Rust API conventions",
    detect_public_api_conventions,
)
cmd_rust_error_boundary = _make_entry_detect_command(
    "Rust public error boundaries",
    detect_error_boundaries,
)
cmd_rust_future_proofing = _make_entry_detect_command(
    "Rust API future-proofing",
    detect_future_proofing,
)
cmd_rust_thread_safety = _make_entry_detect_command(
    "Rust thread-safety contracts",
    detect_thread_safety_contracts,
)
cmd_rust_async_locking = _make_entry_detect_command(
    "Rust async locking",
    detect_async_locking,
)
cmd_rust_drop_safety = _make_entry_detect_command(
    "Rust drop safety",
    detect_drop_safety,
)
cmd_rust_unsafe_api = _make_entry_detect_command(
    "Rust unsafe API usage",
    detect_unsafe_api_usage,
)


def get_detect_commands() -> dict[str, DetectCommand]:
    return compose_detect_registry(
        base_registry=build_standard_detect_registry(
            cmd_deps=cmd_deps,
            cmd_cycles=cmd_cycles,
            cmd_orphaned=cmd_orphaned,
            cmd_dupes=cmd_dupes,
            cmd_large=cmd_large,
            cmd_complexity=cmd_complexity,
        ),
        extra_registry={
            "smells": cmd_smells,
            "clippy_warning": cmd_clippy_warning,
            "cargo_error": cmd_cargo_error,
            "rustdoc_warning": cmd_rustdoc_warning,
            "rust_import_hygiene": cmd_rust_import_hygiene,
            "rust_feature_hygiene": cmd_rust_feature_hygiene,
            "rust_doctest": cmd_rust_doctest,
            "rust_api_convention": cmd_rust_api_convention,
            "rust_error_boundary": cmd_rust_error_boundary,
            "rust_future_proofing": cmd_rust_future_proofing,
            "rust_thread_safety": cmd_rust_thread_safety,
            "rust_async_locking": cmd_rust_async_locking,
            "rust_drop_safety": cmd_rust_drop_safety,
            "rust_unsafe_api": cmd_rust_unsafe_api,
        },
    )


__all__ = [
    "cmd_cargo_error",
    "cmd_clippy_warning",
    "cmd_complexity",
    "cmd_cycles",
    "cmd_deps",
    "cmd_dupes",
    "cmd_large",
    "cmd_orphaned",
    "cmd_smells",
    "cmd_rust_api_convention",
    "cmd_rust_async_locking",
    "cmd_rust_doctest",
    "cmd_rust_drop_safety",
    "cmd_rust_error_boundary",
    "cmd_rust_feature_hygiene",
    "cmd_rust_future_proofing",
    "cmd_rust_import_hygiene",
    "cmd_rust_thread_safety",
    "cmd_rust_unsafe_api",
    "cmd_rustdoc_warning",
    "get_detect_commands",
]
