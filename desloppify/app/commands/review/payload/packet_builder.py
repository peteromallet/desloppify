"""Shared review packet preparation helpers used by prepare/batch flows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from desloppify.intelligence import review as review_mod

from .constants import DEFAULT_REVIEW_BATCH_MAX_FILES


def redacted_review_config(config: dict[str, object] | None) -> dict[str, object]:
    """Return review config payload with score-target hints removed."""
    if not isinstance(config, dict):
        return {}
    return {key: value for key, value in config.items() if key != "target_strict_score"}


def coerce_review_batch_file_limit(config: dict[str, object] | None) -> int | None:
    """Resolve per-batch review file cap from config (0/negative => unlimited)."""
    raw = (config or {}).get("review_batch_max_files", DEFAULT_REVIEW_BATCH_MAX_FILES)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_REVIEW_BATCH_MAX_FILES
    return value if value > 0 else None


def build_run_batches_next_command(
    *,
    include_scan_after_import: bool,
    retrospective: bool,
    retrospective_max_issues: int,
    retrospective_max_batch_items: int,
) -> str:
    """Build canonical follow-up command for batch execution."""
    command = "desloppify review --run-batches --runner codex --parallel"
    if include_scan_after_import:
        command += " --scan-after-import"
    if retrospective:
        command += (
            " --retrospective"
            f" --retrospective-max-issues {retrospective_max_issues}"
            f" --retrospective-max-batch-items {retrospective_max_batch_items}"
        )
    return command


def build_review_packet(
    *,
    path: Path,
    lang_run,
    state: dict[str, Any],
    config: dict[str, object] | None,
    dimensions: list[str] | None,
    files: list[str] | None,
    narrative: dict[str, Any],
    retrospective: bool,
    retrospective_max_issues: int,
    retrospective_max_batch_items: int,
    include_scan_after_import: bool,
    prepare_holistic_review_fn=None,
) -> dict[str, Any]:
    """Create the canonical holistic review packet payload."""
    prepare_fn = prepare_holistic_review_fn or review_mod.prepare_holistic_review
    packet = prepare_fn(
        path,
        lang_run,
        state,
        options=review_mod.HolisticReviewPrepareOptions(
            dimensions=dimensions,
            files=files or None,
            max_files_per_batch=coerce_review_batch_file_limit(config),
            include_issue_history=retrospective,
            issue_history_max_issues=retrospective_max_issues,
            issue_history_max_batch_items=retrospective_max_batch_items,
        ),
    )
    packet["config"] = redacted_review_config(config)
    packet["narrative"] = narrative
    packet["next_command"] = build_run_batches_next_command(
        include_scan_after_import=include_scan_after_import,
        retrospective=retrospective,
        retrospective_max_issues=retrospective_max_issues,
        retrospective_max_batch_items=retrospective_max_batch_items,
    )
    return packet


__all__ = [
    "build_review_packet",
    "build_run_batches_next_command",
    "coerce_review_batch_file_limit",
    "redacted_review_config",
]
