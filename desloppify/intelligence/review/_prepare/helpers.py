"""Helpers used by holistic review preparation."""

from __future__ import annotations

from typing import Any

HOLISTIC_WORKFLOW = [
    "Read .desloppify/query.json for context, excerpts, and investigation batches",
    "For each batch: explore the codebase freely from this dimension's perspective; evaluate the batch's dimension (each batch covers exactly one dimension; batches are independent — parallelize)",
    "Cross-reference issues with the sibling_behavior and convention data",
    "IMPORTANT: issues must be defects only — never positive observations. High scores capture quality; issues capture problems.",
    "Write ALL issues to issues.json — do NOT fix code before importing. Import creates tracked state entries that let desloppify correlate fixes to issues.",
    "Codex: desloppify review --run-batches --runner codex --parallel --scan-after-import",
    "OpenCode: desloppify review --run-batches --runner opencode --parallel --scan-after-import",
    "Claude / other agent: desloppify review --run-batches --dry-run → launch one subagent per prompt file (all in parallel) → desloppify review --import-run <run-dir> --scan-after-import",
    "Cloud/external: run `desloppify review --external-start --external-runner claude`, follow the session template, then run the printed `--external-submit` command",
    "Fallback path: `desloppify review --import issues.json` (issues only). Use manual override only for emergency/provisional imports.",
    "AFTER importing: run `desloppify show review --status open` to see the work queue, then fix each issue in code and `desloppify plan resolve <id>`",
]


def append_full_sweep_batch(
    *,
    batches: list[dict[str, Any]],
    dims: list[str],
    all_files: list[str],
    lang: Any,
    max_files: int | None = None,
) -> None:
    """Append an optional cross-cutting full-codebase batch."""
    del all_files, lang, max_files
    if not dims:
        return
    batches.append(
        {
            "name": "Full Codebase Sweep",
            "dimensions": list(dims),
            "why": "thorough default: evaluate cross-cutting quality across all production files",
        }
    )
