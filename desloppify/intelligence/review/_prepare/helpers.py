"""Helpers used by holistic review preparation."""

from __future__ import annotations

from typing import Any

from desloppify.file_discovery import rel

HOLISTIC_WORKFLOW = [
    "Read .desloppify/query.json for context, excerpts, and investigation batches",
    "For each batch: read the listed files, evaluate the batch's dimensions (batches are independent — parallelize)",
    "Cross-reference findings with the sibling_behavior and convention data",
    "IMPORTANT: findings must be defects only — never positive observations. High scores capture quality; findings capture problems.",
    "For simple issues (missing import, wrong name): fix directly in code, then note as resolved",
    "For cross-cutting issues: write to findings.json (format described in system_prompt)",
    "Import: desloppify review --import findings.json",
    "Run `desloppify issues` to see the work queue, then fix each finding and resolve",
]


def append_full_sweep_batch(
    *,
    batches: list[dict[str, Any]],
    dims: list[str],
    all_files: list[str],
    lang: Any,
) -> None:
    """Append an optional cross-cutting full-codebase batch."""
    if not dims:
        return
    all_rel_files: list[str] = []
    for filepath in all_files:
        if lang.zone_map is not None:
            zone = lang.zone_map.get(filepath)
            if zone.value in ("test", "generated", "vendor"):
                continue
        all_rel_files.append(rel(filepath))
    if not all_rel_files:
        return
    batches.append(
        {
            "name": "Full Codebase Sweep",
            "dimensions": list(dims),
            "files_to_read": all_rel_files,
            "why": "thorough default: evaluate cross-cutting quality across all production files",
        }
    )
