"""Quality-focused Python detector phase runners."""

from __future__ import annotations

from pathlib import Path

from desloppify.base.output.terminal import log
from desloppify.engine._state.filtering import make_issue
from desloppify.engine.policy.zones import adjust_potential, filter_entries
from desloppify.languages._framework.issue_factories import make_smell_issues
from desloppify.languages._framework.base.types import LangRuntimeContract
from desloppify.languages.python.detectors import dict_keys as dict_keys_detector_mod
from desloppify.languages.python.detectors.dict_keys.schema import (
    detect_schema_drift_with_semantic_corrections,
)
from desloppify.languages.python.detectors import (
    import_linter_adapter as import_linter_adapter_mod,
)
from desloppify.languages.python.detectors import (
    mutable_state_scan as mutable_state_detector_mod,
)
from desloppify.languages.python.detectors import smells as smells_detector_mod
from desloppify.languages.python.detectors.ruff_smells import detect_with_ruff_smells
from desloppify.state_io import Issue


def phase_smells(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    """Run file/code smell detectors plus cross-file signature variance."""
    entries, total_files = smells_detector_mod.detect_smells(path)
    # Supplement with ruff B/E/W rules not covered by the regex smells above.
    ruff_entries = detect_with_ruff_smells(path)
    if ruff_entries:
        entries = entries + ruff_entries
    results = make_smell_issues(entries, log)

    return results, {
        "smells": adjust_potential(lang.zone_map, total_files),
    }


def phase_mutable_state(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    """Find global mutable config patterns."""
    entries, total_files = mutable_state_detector_mod.detect_global_mutable_config(path)
    results = []
    for entry in entries:
        results.append(
            make_issue(
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
        log(f"         global mutable config: {len(results)} issues")
    return results, {
        "global_mutable_config": adjust_potential(lang.zone_map, total_files),
    }


def phase_layer_violation(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    """Find package/layer boundary violations via import-linter."""
    entries = import_linter_adapter_mod.detect_with_import_linter(path)
    if entries is None:
        return [], {}

    total_files = len(lang.file_finder(path)) if lang.file_finder else 0
    results = []
    for entry in entries:
        results.append(
            make_issue(
                "layer_violation",
                entry["file"],
                f"{entry['source_pkg']}::{entry['target_pkg']}",
                tier=2,
                confidence=entry["confidence"],
                summary=entry["summary"],
                detail={
                    "source_pkg": entry["source_pkg"],
                    "target_pkg": entry["target_pkg"],
                    "line": entry.get("line", 0),
                    "description": entry.get("summary", ""),
                },
            )
        )
    if results:
        log(f"         layer violations: {len(results)} issues")
    return results, {"layer_violation": total_files}


def phase_dict_keys(path: Path, lang: LangRuntimeContract) -> tuple[list[Issue], dict[str, int]]:
    """Run dict-key flow and schema-drift analysis."""
    flow_entries, files_checked = dict_keys_detector_mod.detect_dict_key_flow(path)
    flow_entries = filter_entries(lang.zone_map, flow_entries, "dict_keys")

    results = []
    for entry in flow_entries:
        results.append(
            make_issue(
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

    drift_entries, _, semantic_correction_entries = (
        detect_schema_drift_with_semantic_corrections(path)
    )
    drift_entries = filter_entries(lang.zone_map, drift_entries, "dict_keys")
    for entry in drift_entries:
        results.append(
            make_issue(
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

    semantic_correction_entries = filter_entries(
        lang.zone_map,
        semantic_correction_entries,
        "dict_keys",
    )
    semantic_corrections = getattr(lang, "semantic_corrections", None)
    if isinstance(semantic_corrections, dict):
        for entry in semantic_correction_entries:
            correction_issue = make_issue(
                "dict_keys",
                entry["file"],
                f"schema_drift::{entry['key']}::{entry['line']}",
                tier=entry["tier"],
                confidence=entry["confidence"],
                summary=entry["summary"],
            )
            semantic_corrections[correction_issue["id"]] = {
                "detector": "dict_keys",
                "kind": "schema_drift",
                "file": correction_issue["file"],
                "key": entry["key"],
                "line": str(entry["line"]),
                "rule": entry["rule"],
                "evidence": (
                    f"{entry['file']}:{entry['line']} is "
                    f"{entry['comparison_scope']} and is absent from "
                    "the scoped schema-drift output"
                ),
            }

    log(f"         -> {len(results)} dict key issues")
    return results, {
        "dict_keys": adjust_potential(lang.zone_map, files_checked),
    }


__all__ = [
    "phase_dict_keys",
    "phase_layer_violation",
    "phase_mutable_state",
    "phase_smells",
]
