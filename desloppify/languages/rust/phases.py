"""Rust detector phase runners and external tool definitions."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from desloppify.base.output.terminal import log
from desloppify.engine.detectors.base import ComplexitySignal
from desloppify.engine.detectors.graph import detect_cycles
from desloppify.engine.detectors.orphaned import (
    OrphanedDetectionOptions,
    detect_orphaned_files,
)
from desloppify.engine.detectors.signature import detect_signature_variance
from desloppify.engine.detectors.single_use import detect_single_use_abstractions
from desloppify.engine.policy.zones import adjust_potential, filter_entries
from desloppify.languages._framework.base.shared_phases import (
    run_structural_phase,
)
from desloppify.languages._framework.base.types import DetectorPhase, LangRuntimeContract
from desloppify.languages._framework.issue_factories import (
    make_cycle_issues,
    make_orphaned_issues,
    make_single_use_issues,
)
from desloppify.languages._framework.generic_parts.tool_factories import (
    _record_tool_failure_coverage,
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
    detect_thread_safety_contracts,
    detect_unsafe_api_usage,
)
from desloppify.languages.rust.detectors.deps import build_dep_graph
from desloppify.languages.rust.tools import (
    CARGO_ERROR_CMD as RUST_CHECK_CMD,
    CLIPPY_WARNING_CMD as RUST_CLIPPY_CMD,
    RUSTDOC_WARNING_CMD as RUST_RUSTDOC_CMD,
    parse_cargo_errors,
    parse_clippy_messages,
    run_rustdoc_result,
)
from desloppify.state import Issue
from desloppify.state import make_issue

RUST_CLIPPY_LABEL = "cargo clippy"
RUST_CHECK_LABEL = "cargo check"
RUST_RUSTDOC_LABEL = "cargo rustdoc"
RUST_POLICY_LABEL = "Rust API + cargo policy"
RUST_SIGNATURE_LABEL = "Signature analysis"

RUST_SIGNATURE_ALLOWLIST = {
    "new",
    "default",
    "from",
    "try_from",
    "from_str",
    "fmt",
    "clone",
    "eq",
    "cmp",
    "partial_cmp",
    "hash",
    "serialize",
    "deserialize",
    "visit_str",
    "visit_seq",
    "visit_map",
    "visit_enum",
    "visit_i64",
    "visit_u64",
    "visit_bool",
    "visit_string",
    "get_value",
}

RUST_COMPLEXITY_SIGNALS = [
    ComplexitySignal(
        "control flow",
        r"\b(?:if|else\s+if|match|for|while|loop)\b",
        weight=1,
        threshold=25,
    ),
    ComplexitySignal(
        "error branching",
        r"\b(?:unwrap|expect|panic!|todo!|unimplemented!)",
        weight=2,
        threshold=4,
    ),
    ComplexitySignal(
        "trait/impl blocks",
        r"(?m)^\s*(?:impl|trait)\b",
        weight=2,
        threshold=8,
    ),
    ComplexitySignal(
        "async/concurrency",
        r"\b(?:async|await|spawn|join!|select!)\b",
        weight=1,
        threshold=10,
    ),
    ComplexitySignal(
        "TODOs",
        r"(?m)//\s*(?:TODO|FIXME|HACK|XXX)",
        weight=2,
        threshold=0,
    ),
]


def phase_structural(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    """Run structural detectors (large/complexity/flat directories)."""
    return run_structural_phase(
        path,
        lang,
        complexity_signals=RUST_COMPLEXITY_SIGNALS,
        log_fn=log,
    )


def phase_coupling(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    """Run coupling-oriented detectors against the Rust import graph."""
    graph = build_dep_graph(path)
    cycle_graph = build_dep_graph(path, include_mod_declarations=False)
    lang.dep_graph = graph
    zone_map = lang.zone_map
    results: list[Issue] = []

    single_entries, single_candidates = detect_single_use_abstractions(
        path,
        graph,
        barrel_names=lang.barrel_names,
    )
    single_entries = filter_entries(zone_map, single_entries, "single_use")
    results.extend(make_single_use_issues(single_entries, lang.get_area, stderr_fn=log))

    cycle_entries, total_cycle_files = detect_cycles(cycle_graph)
    cycle_entries = filter_entries(zone_map, cycle_entries, "cycles", file_key="files")
    results.extend(make_cycle_issues(cycle_entries, log))

    orphan_entries, total_graph_files = detect_orphaned_files(
        path,
        graph,
        extensions=lang.extensions,
        options=OrphanedDetectionOptions(
            extra_entry_patterns=lang.entry_patterns,
            extra_barrel_names=lang.barrel_names,
        ),
    )
    orphan_entries = filter_entries(zone_map, orphan_entries, "orphaned")
    results.extend(make_orphaned_issues(orphan_entries, log))

    log(f"         -> {len(results)} coupling/structural issues total")
    return results, {
        "single_use": adjust_potential(zone_map, single_candidates),
        "cycles": adjust_potential(zone_map, total_cycle_files),
        "orphaned": adjust_potential(zone_map, total_graph_files),
    }


def phase_custom_policy(
    path: Path,
    lang: LangRuntimeContract,
) -> tuple[list[Issue], dict[str, int]]:
    """Run Rust-specific API, manifest, and docs policy detectors."""
    detector_fns = (
        ("rust_import_hygiene", detect_import_hygiene),
        ("rust_feature_hygiene", detect_feature_hygiene),
        ("rust_doctest", detect_doctest_hygiene),
        ("rust_api_convention", detect_public_api_conventions),
        ("rust_error_boundary", detect_error_boundaries),
        ("rust_future_proofing", detect_future_proofing),
        ("rust_thread_safety", detect_thread_safety_contracts),
        ("rust_async_locking", detect_async_locking),
        ("rust_drop_safety", detect_drop_safety),
        ("rust_unsafe_api", detect_unsafe_api_usage),
    )
    results: list[Issue] = []
    counts: dict[str, int] = {}
    for detector, fn in detector_fns:
        entries, total = fn(path)
        entries = filter_entries(lang.zone_map, entries, detector)
        counts[detector] = adjust_potential(lang.zone_map, total)
        if entries:
            log(f"         {detector}: {len(entries)} issues")
        for entry in entries:
            results.append(
                make_issue(
                    detector,
                    entry["file"],
                    entry["name"],
                    tier=entry["tier"],
                    confidence=entry["confidence"],
                    summary=entry["summary"],
                    detail=entry.get("detail"),
                )
            )
    return results, counts


def phase_signature(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    """Run Rust-specific signature analysis with an idiomatic-name allowlist."""
    functions = [
        function
        for function in lang.extract_functions(path)
        if function.name not in RUST_SIGNATURE_ALLOWLIST
    ]
    if not functions:
        return [], {}

    entries, _ = detect_signature_variance(functions, min_occurrences=4)
    issues = [
        make_issue(
            "signature",
            entry["files"][0],
            f"signature_variance::{entry['name']}",
            tier=3,
            confidence="medium",
            summary=(
                f"'{entry['name']}' has {entry['signature_count']} different signatures "
                f"across {entry['file_count']} files"
            ),
        )
        for entry in entries
    ]
    if entries:
        log(f"         signature variance: {len(entries)}")
    return issues, {"signature": len(entries)} if entries else {}


ToolResultRunner = Callable[[Path], ToolRunResult]


def _make_rust_tool_phase(label: str, runner: ToolResultRunner, detector: str, tier: int):
    def run(path: Path, lang) -> tuple[list[dict], dict[str, int]]:
        result = runner(path)
        if result.status == "error":
            _record_tool_failure_coverage(
                lang,
                detector=detector,
                label=label,
                result=result,
            )
            return [], {}
        if not result.entries:
            return [], {}
        issues = [
            make_issue(
                detector,
                entry["file"],
                f"{detector}::{entry['line']}",
                tier=tier,
                confidence="medium",
                summary=entry["message"],
            )
            for entry in result.entries
        ]
        return issues, {detector: len(result.entries)}

    return DetectorPhase(label, run)


def tool_phase_clippy():
    return _make_rust_tool_phase(
        RUST_CLIPPY_LABEL,
        lambda path: run_tool_result(RUST_CLIPPY_CMD, path, parse_clippy_messages),
        "clippy_warning",
        tier=2,
    )


def tool_phase_check():
    return _make_rust_tool_phase(
        RUST_CHECK_LABEL,
        lambda path: run_tool_result(RUST_CHECK_CMD, path, parse_cargo_errors),
        "cargo_error",
        tier=3,
    )


def tool_phase_rustdoc():
    return _make_rust_tool_phase(
        RUST_RUSTDOC_LABEL,
        run_rustdoc_result,
        "rustdoc_warning",
        tier=2,
    )


__all__ = [
    "RUST_CHECK_CMD",
    "RUST_CHECK_LABEL",
    "RUST_CLIPPY_CMD",
    "RUST_CLIPPY_LABEL",
    "RUST_COMPLEXITY_SIGNALS",
    "RUST_POLICY_LABEL",
    "RUST_RUSTDOC_CMD",
    "RUST_RUSTDOC_LABEL",
    "RUST_SIGNATURE_LABEL",
    "phase_coupling",
    "phase_custom_policy",
    "phase_signature",
    "phase_structural",
    "tool_phase_check",
    "tool_phase_clippy",
    "tool_phase_rustdoc",
]
