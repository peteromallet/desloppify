"""Result reconciliation, merge writing, and import-finalization helpers."""

from __future__ import annotations

import json
from pathlib import Path

from desloppify.base.exception_sets import CommandError

from ..importing.flags import ReviewImportConfig
from .execution import CollectBatchResultsRequest

from .scope import (
    collect_reviewed_files_from_batches,
    enforce_trusted_import_coverage_gate,
    normalize_dimension_list,
    print_import_dimension_coverage_notice,
    print_review_quality,
)


def find_prior_run_merged_results(
    *,
    subagent_runs_dir: Path,
    immutable_packet_path: Path,
    current_run_dir: Path,
) -> dict | None:
    """Find the most recent prior run's merged results for the same packet.

    Searches run directories under ``subagent_runs_dir`` for a prior run that
    used the same immutable packet and produced a ``holistic_issues_merged.json``.
    Skips the current run directory.  Returns the parsed merged results dict or
    ``None`` if no matching prior run is found.
    """
    if not subagent_runs_dir.is_dir():
        return None

    immutable_packet_str = str(immutable_packet_path)
    best_merged: dict | None = None
    best_stamp: str = ""

    for run_dir in sorted(subagent_runs_dir.iterdir(), reverse=True):
        if not run_dir.is_dir():
            continue
        if run_dir == current_run_dir:
            continue
        summary_path = run_dir / "run_summary.json"
        merged_path = run_dir / "holistic_issues_merged.json"
        if not summary_path.exists() or not merged_path.exists():
            continue
        try:
            summary = json.loads(summary_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if str(summary.get("immutable_packet", "")) != immutable_packet_str:
            continue
        stamp = str(summary.get("run_stamp", run_dir.name))
        if stamp <= best_stamp:
            continue
        try:
            merged = json.loads(merged_path.read_text())
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(merged, dict) and merged.get("assessments"):
            best_merged = merged
            best_stamp = stamp

    return best_merged


def overlay_retry_results_on_prior(
    *,
    prior_merged: dict,
    retry_merged: dict,
    retry_dims: set[str],
) -> dict:
    """Combine prior run results with retry results for retried dimensions.

    For dimensions in ``retry_dims``, the retry's assessments/issues/notes take
    precedence.  For all other dimensions, the prior run's data is preserved.
    The result is a new merged dict suitable for the standard coverage gate.
    """
    combined = dict(retry_merged)

    # --- assessments: prior non-retried dims + retry dims ---
    prior_assessments = prior_merged.get("assessments") or {}
    retry_assessments = retry_merged.get("assessments") or {}
    merged_assessments: dict[str, object] = {}
    for dim, value in prior_assessments.items():
        if dim not in retry_dims:
            merged_assessments[dim] = value
    for dim, value in retry_assessments.items():
        merged_assessments[dim] = value
    combined["assessments"] = merged_assessments

    # --- issues: prior non-retried dim issues + all retry issues ---
    prior_issues = prior_merged.get("issues") or []
    retry_issues = retry_merged.get("issues") or []
    kept_prior_issues = [
        issue for issue in prior_issues
        if isinstance(issue, dict) and str(issue.get("dimension", "")) not in retry_dims
    ]
    combined["issues"] = kept_prior_issues + list(retry_issues)

    # --- dimension_notes: merge similarly ---
    prior_notes = prior_merged.get("dimension_notes") or {}
    retry_notes = retry_merged.get("dimension_notes") or {}
    merged_notes: dict[str, object] = {}
    for dim, value in prior_notes.items():
        if dim not in retry_dims:
            merged_notes[dim] = value
    for dim, value in retry_notes.items():
        merged_notes[dim] = value
    combined["dimension_notes"] = merged_notes

    # --- dimension_judgment: merge similarly ---
    prior_judgment = prior_merged.get("dimension_judgment") or {}
    retry_judgment = retry_merged.get("dimension_judgment") or {}
    merged_judgment: dict[str, object] = {}
    for dim, value in prior_judgment.items():
        if dim not in retry_dims:
            merged_judgment[dim] = value
    for dim, value in retry_judgment.items():
        merged_judgment[dim] = value
    combined["dimension_judgment"] = merged_judgment

    # --- context_updates: merge similarly ---
    prior_ctx = prior_merged.get("context_updates") or {}
    retry_ctx = retry_merged.get("context_updates") or {}
    if prior_ctx or retry_ctx:
        merged_ctx: dict[str, object] = {}
        for dim, value in prior_ctx.items():
            if dim not in retry_dims:
                merged_ctx[dim] = value
        for dim, value in retry_ctx.items():
            merged_ctx[dim] = value
        combined["context_updates"] = merged_ctx

    return combined


def collect_and_reconcile_results(
    *,
    collect_batch_results_fn,
    request: CollectBatchResultsRequest,
    execution_failures: list[int],
    batch_positions: dict[int, int],
    batch_status: dict[str, dict[str, object]],
    colorize_fn=None,
) -> tuple[list[dict], list[int], list[int], set[int]]:
    """Collect batch results and reconcile per-batch status entries."""
    selected_indexes = request.selected_indexes
    output_files = request.output_files
    batch_results, failures = collect_batch_results_fn(request)

    execution_failure_set = set(execution_failures)
    failure_set = set(failures)
    successful_indexes = sorted(idx for idx in selected_indexes if idx not in failure_set)
    for idx in selected_indexes:
        key = str(idx + 1)
        state = batch_status.setdefault(
            key,
            {"position": batch_positions.get(idx, 0), "status": "pending"},
        )
        if idx not in failure_set:
            # Batch succeeded — distinguish recovered (execution failed but payload valid)
            # from clean success.
            if idx in execution_failure_set:
                state["status"] = "recovered"
            else:
                state["status"] = "succeeded"
            continue
        if idx in execution_failure_set:
            state["status"] = "failed"
            continue
        if not output_files[idx].exists():
            state["status"] = "missing_output"
            continue
        state["status"] = "parse_failed"

    recovered = sorted(
        idx + 1
        for idx in selected_indexes
        if idx in execution_failure_set and idx not in failure_set
    )
    if recovered and colorize_fn is not None:
        print(
            colorize_fn(
                f"  Recovered batches (execution exited non-zero but payload valid): {recovered}",
                "green",
            )
        )

    return batch_results, successful_indexes, failures, failure_set


def merge_and_write_results(
    *,
    merge_batch_results_fn,
    build_import_provenance_fn,
    batch_results: list[dict],
    batches: list,
    successful_indexes: list[int],
    packet: dict,
    packet_dimensions: list[str],
    scored_dimensions: list[str],
    scan_path: str,
    runner: str,
    prompt_packet_path: Path,
    stamp: str,
    run_dir: Path,
    safe_write_text_fn,
    colorize_fn,
) -> tuple[Path, list[str]]:
    """Merge batch results, enrich with metadata, and write to disk."""
    merged = merge_batch_results_fn(batch_results)
    quality = merged.get("review_quality", {})
    reviewed_files = collect_reviewed_files_from_batches(
        batches=batches,
        selected_indexes=successful_indexes,
    )
    full_sweep_included = any(
        str(batch.get("name", "")).strip().lower() == "full codebase sweep"
        for idx in successful_indexes
        if 0 <= idx < len(batches)
        for batch in [batches[idx]]
        if isinstance(batch, dict)
    )
    review_scope: dict[str, object] = {
        "reviewed_files_count": len(reviewed_files),
        "successful_batch_count": len(successful_indexes),
        "full_sweep_included": full_sweep_included,
    }
    total_files = packet.get("total_files")
    if isinstance(total_files, int) and not isinstance(total_files, bool) and total_files > 0:
        review_scope["total_files"] = total_files
    merged["review_scope"] = review_scope
    if reviewed_files:
        merged["reviewed_files"] = reviewed_files
        print(
            colorize_fn(
                f"  Reviewed files captured for cache refresh: {len(reviewed_files)}",
                "dim",
            )
        )
    merged["provenance"] = build_import_provenance_fn(
        runner=runner,
        blind_packet_path=prompt_packet_path,
        run_stamp=stamp,
        batch_indexes=successful_indexes,
    )
    merged_assessment_dims = normalize_dimension_list(
        list((merged.get("assessments") or {}).keys())
    )
    merged_issue_dims = normalize_dimension_list(
        [
            issue.get("dimension")
            for issue in (merged.get("issues") or [])
            if isinstance(issue, dict)
        ]
    )
    merged_imported_dims = normalize_dimension_list(
        merged_assessment_dims + merged_issue_dims
    )
    review_scope["imported_dimensions"] = merged_imported_dims
    missing_after_import = print_import_dimension_coverage_notice(
        assessed_dims=merged_assessment_dims,
        scored_dims=scored_dimensions,
        scan_path=scan_path,
        colorize_fn=colorize_fn,
    )
    merged["assessment_coverage"] = {
        "scored_dimensions": scored_dimensions,
        "selected_dimensions": packet_dimensions,
        "imported_dimensions": merged_assessment_dims,
        "missing_dimensions": missing_after_import,
    }
    merged_path = run_dir / "holistic_issues_merged.json"
    safe_write_text_fn(merged_path, json.dumps(merged, indent=2) + "\n")
    print(colorize_fn(f"\n  Merged outputs: {merged_path}", "bold"))
    print_review_quality(quality, colorize_fn=colorize_fn)
    return merged_path, missing_after_import


def import_and_finalize(
    *,
    do_import_fn,
    run_followup_scan_fn,
    merged_path: Path,
    state,
    lang,
    state_file,
    config: dict,
    allow_partial: bool,
    successful_indexes: list[int],
    failure_set: set[int],
    append_run_log,
    args,
) -> None:
    """Import merged results and optionally run a follow-up scan."""
    try:
        do_import_fn(
            str(merged_path),
            state,
            lang,
            state_file,
            import_config=ReviewImportConfig(
                config=config,
                allow_partial=allow_partial,
                trusted_assessment_source=True,
                trusted_assessment_label="trusted internal run-batches import",
            ),
        )
    except SystemExit as exc:
        append_run_log(f"run-finished import-failed code={exc.code}")
        raise
    except Exception as exc:
        append_run_log(f"run-finished import-error error={exc}")
        raise
    append_run_log(
        "run-finished "
        f"successful={[idx + 1 for idx in successful_indexes]} "
        f"failed={[idx + 1 for idx in sorted(failure_set)]} imported={str(merged_path)}"
    )

    if getattr(args, "scan_after_import", False):
        followup_code = run_followup_scan_fn(
            lang_name=lang.name,
            scan_path=str(args.path),
        )
        if followup_code != 0:
            raise CommandError(
                f"Error: follow-up scan failed with exit code {followup_code}.",
                exit_code=followup_code,
            )


def enforce_import_coverage(
    *,
    missing_after_import: list[str],
    packet_dimensions: list[str],
    allow_partial: bool,
    scan_path: str,
    colorize_fn,
) -> None:
    """Apply trusted import coverage gate after merge output is written."""
    enforce_trusted_import_coverage_gate(
        missing_dims=missing_after_import,
        selected_dims=packet_dimensions,
        allow_partial=allow_partial,
        scan_path=scan_path,
        colorize_fn=colorize_fn,
    )


def log_run_start(
    *,
    append_run_log,
    colorize_fn,
    run_log_path: Path,
    run_dir: Path,
    immutable_packet_path: Path,
    prompt_packet_path: Path,
    runner: str,
    run_parallel: bool,
    max_parallel_batches: int,
    batch_timeout_seconds: int,
    heartbeat_seconds: float,
    stall_warning_seconds: int,
    stall_kill_seconds: int,
    batch_max_retries: int,
    batch_retry_backoff_seconds: float,
    worst_case_minutes: int,
    selected_indexes: list[int],
) -> None:
    """Append initial run metadata and print live log path."""
    append_run_log(
        "run-start "
        f"runner={runner} parallel={run_parallel} max_parallel={max_parallel_batches} "
        f"timeout={batch_timeout_seconds}s heartbeat={heartbeat_seconds:.1f}s "
        f"stall_warning={stall_warning_seconds}s stall_kill={stall_kill_seconds}s "
        f"retries={batch_max_retries} "
        f"retry_backoff={batch_retry_backoff_seconds:.1f}s upper_bound={worst_case_minutes}m "
        f"selected={[idx + 1 for idx in selected_indexes]}"
    )
    append_run_log(f"run-path {run_dir}")
    append_run_log(f"packet {immutable_packet_path}")
    append_run_log(f"blind-packet {prompt_packet_path}")
    print(colorize_fn(f"  Live run log: {run_log_path}", "dim"))


__all__ = [
    "collect_and_reconcile_results",
    "enforce_import_coverage",
    "find_prior_run_merged_results",
    "log_run_start",
    "import_and_finalize",
    "merge_and_write_results",
    "overlay_retry_results_on_prior",
]
