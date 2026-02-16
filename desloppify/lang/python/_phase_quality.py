"""Quality-related Python phase runners split from phases.py."""

from __future__ import annotations

from pathlib import Path

from ..base import LangConfig
from ...utils import log
from ...zones import adjust_potential, filter_entries


def _phase_mutable_state(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.mutable_state import detect_global_mutable_config
    from ...state import make_finding

    entries, total_files = detect_global_mutable_config(path)
    results = []
    for e in entries:
        results.append(
            make_finding(
                "global_mutable_config",
                e["file"],
                e["name"],
                tier=3,
                confidence=e["confidence"],
                summary=e["summary"],
                detail={"mutation_count": e["mutation_count"], "mutation_lines": e["mutation_lines"]},
            )
        )
    if results:
        log(f"         global mutable config: {len(results)} findings")
    return results, {
        "global_mutable_config": adjust_potential(lang._zone_map, total_files),
    }


def _phase_layer_violation(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.layer_violation import detect_layer_violations
    from ...state import make_finding

    entries, total_files = detect_layer_violations(path, lang.file_finder)
    results = []
    for e in entries:
        results.append(
            make_finding(
                "layer_violation",
                e["file"],
                f"{e['source_pkg']}::{e['target_pkg']}",
                tier=2,
                confidence=e["confidence"],
                summary=e["summary"],
                detail={
                    "source_pkg": e["source_pkg"],
                    "target_pkg": e["target_pkg"],
                    "line": e["line"],
                    "description": e["description"],
                },
            )
        )
    if results:
        log(f"         layer violations: {len(results)} findings")
    return results, {"layer_violation": total_files}


def _phase_dict_keys(path: Path, lang: LangConfig) -> tuple[list[dict], dict[str, int]]:
    from .detectors.dict_keys import detect_dict_key_flow, detect_schema_drift
    from ...state import make_finding

    flow_entries, files_checked = detect_dict_key_flow(path)
    flow_entries = filter_entries(lang._zone_map, flow_entries, "dict_keys")

    results = []
    for e in flow_entries:
        results.append(
            make_finding(
                "dict_keys",
                e["file"],
                f"{e['kind']}::{e['variable']}::{e['key']}"
                if "variable" in e
                else f"{e['kind']}::{e['key']}::{e['line']}",
                tier=e["tier"],
                confidence=e["confidence"],
                summary=e["summary"],
                detail={
                    "kind": e["kind"],
                    "key": e.get("key", ""),
                    "line": e.get("line"),
                    "info": e.get("detail", ""),
                },
            )
        )

    drift_entries, _ = detect_schema_drift(path)
    drift_entries = filter_entries(lang._zone_map, drift_entries, "dict_keys")

    for e in drift_entries:
        results.append(
            make_finding(
                "dict_keys",
                e["file"],
                f"schema_drift::{e['key']}::{e['line']}",
                tier=e["tier"],
                confidence=e["confidence"],
                summary=e["summary"],
                detail={
                    "kind": "schema_drift",
                    "key": e["key"],
                    "line": e["line"],
                    "info": e.get("detail", ""),
                },
            )
        )

    log(f"         -> {len(results)} dict key findings")
    return results, {
        "dict_keys": adjust_potential(lang._zone_map, files_checked),
    }
