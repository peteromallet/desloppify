"""Quality-focused Python detector phase runners."""

from __future__ import annotations

from pathlib import Path

from desloppify import state as state_mod
from desloppify.engine.detectors import signature as signature_detector_mod
from desloppify.engine.policy.zones import adjust_potential, filter_entries
from desloppify.languages.framework.finding_factories import make_smell_findings
from desloppify.languages.python.detectors import dict_keys as dict_keys_detector_mod
from desloppify.languages.python.detectors import (
    layer_violation as layer_violation_detector_mod,
)
from desloppify.languages.python.detectors import (
    mutable_state as mutable_state_detector_mod,
)
from desloppify.languages.python.detectors import smells as smells_detector_mod
from desloppify.utils import log


def phase_smells(path: Path, lang) -> tuple[list[dict], dict[str, int]]:
    """Run file/code smell detectors plus cross-file signature variance."""
    entries, total_files = smells_detector_mod.detect_smells(path)
    results = make_smell_findings(entries, log)

    functions = lang.extract_functions(path) if lang.extract_functions else []
    sig_entries, _ = signature_detector_mod.detect_signature_variance(functions)
    for entry in sig_entries:
        results.append(
            state_mod.make_finding(
                "smells",
                entry["files"][0],
                f"sig_variance::{entry['name']}",
                tier=3,
                confidence="medium",
                summary=(
                    f"Signature variance: {entry['name']}() has {entry['signature_count']} "
                    f"different signatures across {entry['file_count']} files"
                ),
                detail={
                    "function": entry["name"],
                    "file_count": entry["file_count"],
                    "signature_count": entry["signature_count"],
                    "variants": entry["variants"][:5],
                },
            )
        )
    if sig_entries:
        log(
            f"         signature variance: {len(sig_entries)} functions with inconsistent signatures"
        )

    return results, {
        "smells": adjust_potential(lang.zone_map, total_files),
    }


def phase_mutable_state(path: Path, lang) -> tuple[list[dict], dict[str, int]]:
    """Find global mutable config patterns."""
    entries, total_files = mutable_state_detector_mod.detect_global_mutable_config(path)
    results = []
    for entry in entries:
        results.append(
            state_mod.make_finding(
                "global_mutable_config",
                entry["file"],
                entry["name"],
                tier=3,
                confidence=entry["confidence"],
                summary=entry["summary"],
                detail={
                    "mutation_count": entry["mutation_count"],
                    "mutation_lines": entry["mutation_lines"],
                },
            )
        )
    if results:
        log(f"         global mutable config: {len(results)} findings")
    return results, {
        "global_mutable_config": adjust_potential(lang.zone_map, total_files),
    }


def phase_layer_violation(path: Path, lang) -> tuple[list[dict], dict[str, int]]:
    """Find package/layer boundary violations."""
    entries, total_files = layer_violation_detector_mod.detect_layer_violations(
        path, lang.file_finder
    )
    results = []
    for entry in entries:
        results.append(
            state_mod.make_finding(
                "layer_violation",
                entry["file"],
                f"{entry['source_pkg']}::{entry['target_pkg']}",
                tier=2,
                confidence=entry["confidence"],
                summary=entry["summary"],
                detail={
                    "source_pkg": entry["source_pkg"],
                    "target_pkg": entry["target_pkg"],
                    "line": entry["line"],
                    "description": entry["description"],
                },
            )
        )
    if results:
        log(f"         layer violations: {len(results)} findings")
    return results, {"layer_violation": total_files}


def phase_dict_keys(path: Path, lang) -> tuple[list[dict], dict[str, int]]:
    """Run dict-key flow and schema-drift analysis."""
    flow_entries, files_checked = dict_keys_detector_mod.detect_dict_key_flow(path)
    flow_entries = filter_entries(lang.zone_map, flow_entries, "dict_keys")

    results = []
    for entry in flow_entries:
        results.append(
            state_mod.make_finding(
                "dict_keys",
                entry["file"],
                f"{entry['kind']}::{entry['variable']}::{entry['key']}"
                if "variable" in entry
                else f"{entry['kind']}::{entry['key']}::{entry['line']}",
                tier=entry["tier"],
                confidence=entry["confidence"],
                summary=entry["summary"],
                detail={
                    "kind": entry["kind"],
                    "key": entry.get("key", ""),
                    "line": entry.get("line"),
                    "info": entry.get("detail", ""),
                },
            )
        )

    drift_entries, _ = dict_keys_detector_mod.detect_schema_drift(path)
    drift_entries = filter_entries(lang.zone_map, drift_entries, "dict_keys")
    for entry in drift_entries:
        results.append(
            state_mod.make_finding(
                "dict_keys",
                entry["file"],
                f"schema_drift::{entry['key']}::{entry['line']}",
                tier=entry["tier"],
                confidence=entry["confidence"],
                summary=entry["summary"],
                detail={
                    "kind": "schema_drift",
                    "key": entry["key"],
                    "line": entry["line"],
                    "info": entry.get("detail", ""),
                },
            )
        )

    log(f"         -> {len(results)} dict key findings")
    return results, {
        "dict_keys": adjust_potential(lang.zone_map, files_checked),
    }


__all__ = [
    "phase_dict_keys",
    "phase_layer_violation",
    "phase_mutable_state",
    "phase_smells",
]
