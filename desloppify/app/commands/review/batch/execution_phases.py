"""Batch execution phase helpers for review command."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..batches_runtime import (
    BatchRunSummaryConfig,
    build_batch_tasks,
    make_run_log_writer,
    resolve_run_log_path,
)
from ..prompt_sections import explode_to_single_dimension
from ..runner_parallel import BatchExecutionOptions
from ..runtime.policy import resolve_batch_run_policy
from .execution_dry_run import maybe_handle_dry_run
from .execution_progress import (
    build_initial_batch_status,
    build_progress_reporter,
    mark_interrupted_batches,
    record_execution_issue,
)
from .execution_results import (
    collect_and_reconcile_results,
    enforce_import_coverage,
    import_and_finalize,
    log_run_start,
    merge_and_write_results,
)
from .execution_summary import build_run_summary_writer
from .execution import (
    CollectBatchResultsRequest,
    LoadOrPreparePacketRequest,
    PrepareRunArtifactsRequest,
)
from .scope import (
    normalize_dimension_list,
    print_preflight_dimension_scope_notice,
    require_batches,
    scored_dimensions_for_lang,
    validate_runner,
)

if TYPE_CHECKING:
    from ..runtime.policy import BatchRunPolicy
    from .execution import BatchRunDeps


@dataclass(frozen=True)
class PreparedBatchRunContext:
    """Typed handoff from prepare phase into execution/import phases."""

    stamp: str
    args: Any
    config: dict[str, Any]
    runner: str
    allow_partial: bool
    run_parallel: bool
    max_parallel_batches: int
    heartbeat_seconds: float
    batch_timeout_seconds: float
    batch_max_retries: int
    batch_retry_backoff_seconds: float
    stall_warning_seconds: float
    stall_kill_seconds: float
    state: dict[str, Any]
    lang: Any
    packet: dict[str, Any]
    immutable_packet_path: Path
    prompt_packet_path: Path
    scan_path: str
    packet_dimensions: list[str]
    scored_dimensions: list[str]
    batches: list[dict[str, Any]]
    selected_indexes: list[int]
    project_root: Path
    run_dir: Path
    logs_dir: Path
    prompt_files: dict[int, Path]
    output_files: dict[int, Path]
    log_files: dict[int, Path]
    run_log_path: Path
    append_run_log: Any
    batch_positions: dict[int, int]
    batch_status: dict[str, dict[str, object]]
    report_progress: Any
    record_issue: Any
    write_run_summary: Any


@dataclass(frozen=True)
class ExecutedBatchRunContext:
    """Typed handoff from execution phase into merge/import phase."""

    batch_results: list[dict[str, Any]]
    successful_indexes: list[int]
    failure_set: set[int]


@dataclass(frozen=True)
class PreparedPacketScope:
    """Packet and selection state shared from prepare into execution."""

    packet: dict[str, Any]
    immutable_packet_path: Path
    prompt_packet_path: Path
    scan_path: str
    packet_dimensions: list[str]
    scored_dimensions: list[str]
    batches: list[dict[str, Any]]
    selected_indexes: list[int]


@dataclass(frozen=True)
class PreparedRunArtifacts:
    """Runtime artifacts and callbacks created for one batch run."""

    run_dir: Path
    logs_dir: Path
    prompt_files: dict[int, Path]
    output_files: dict[int, Path]
    log_files: dict[int, Path]
    run_log_path: Path
    append_run_log: Any
    batch_positions: dict[int, int]
    batch_status: dict[str, dict[str, object]]
    report_progress: Any
    record_issue: Any
    write_run_summary: Any


def _resolve_runtime_policy(args) -> BatchRunPolicy:
    return resolve_batch_run_policy(args)


def _prepare_packet_scope(
    *,
    args,
    state,
    lang,
    config: dict[str, Any],
    deps: BatchRunDeps,
    stamp: str,
) -> PreparedPacketScope:
    packet, immutable_packet_path, prompt_packet_path = deps.load_or_prepare_packet_fn(
        LoadOrPreparePacketRequest(
            args=args,
            state=state,
            lang=lang,
            config=config,
            stamp=stamp,
        )
    )
    scan_path = str(getattr(args, "path", ".") or ".")
    packet_dimensions = normalize_dimension_list(packet.get("dimensions", []))
    scored_dimensions = scored_dimensions_for_lang(lang.name)
    print_preflight_dimension_scope_notice(
        selected_dims=packet_dimensions,
        scored_dims=scored_dimensions,
        explicit_selection=bool(getattr(args, "dimensions", None)),
        scan_path=scan_path,
        colorize_fn=deps.colorize_fn,
    )
    suggested_prepare_cmd = f"desloppify review --prepare --path {scan_path}"
    raw_dim_prompts = packet.get("dimension_prompts")
    batches = explode_to_single_dimension(
        require_batches(
            packet,
            colorize_fn=deps.colorize_fn,
            suggested_prepare_cmd=suggested_prepare_cmd,
        ),
        dimension_prompts=raw_dim_prompts if isinstance(raw_dim_prompts, dict) else None,
    )
    selected_indexes = deps.selected_batch_indexes_fn(args, batch_count=len(batches))
    return PreparedPacketScope(
        packet=packet,
        immutable_packet_path=immutable_packet_path,
        prompt_packet_path=prompt_packet_path,
        scan_path=scan_path,
        packet_dimensions=packet_dimensions,
        scored_dimensions=scored_dimensions,
        batches=batches,
        selected_indexes=selected_indexes,
    )


def _print_runtime_expectation(
    *,
    deps: BatchRunDeps,
    total_batches: int,
    run_parallel: bool,
    max_parallel_batches: int,
    batch_timeout_seconds: float,
) -> None:
    effective_workers = min(total_batches, max_parallel_batches) if run_parallel else 1
    waves = max(1, math.ceil(total_batches / max(1, effective_workers)))
    worst_case_minutes = max(1, math.ceil((waves * batch_timeout_seconds) / 60))
    print(
        deps.colorize_fn(
            "  Runtime expectation: "
            f"{total_batches} batch(es), workers={effective_workers}, "
            f"timeout-per-batch={int(batch_timeout_seconds / 60)}m, "
            f"worst-case upper bound ~{worst_case_minutes}m.",
            "dim",
        )
    )


def _prepare_run_runtime(
    *,
    args,
    deps: BatchRunDeps,
    stamp: str,
    selected_indexes: list[int],
    batches: list[dict[str, Any]],
    prompt_packet_path: Path,
    immutable_packet_path: Path,
    project_root: Path,
    subagent_runs_dir: Path,
    runner: str,
    allow_partial: bool,
    run_parallel: bool,
    max_parallel_batches: int,
    heartbeat_seconds: float,
    batch_timeout_seconds: float,
    batch_max_retries: int,
    batch_retry_backoff_seconds: float,
    stall_warning_seconds: float,
    stall_kill_seconds: float,
) -> PreparedRunArtifacts:
    run_dir, logs_dir, prompt_files, output_files, log_files = deps.prepare_run_artifacts_fn(
        PrepareRunArtifactsRequest(
            stamp=stamp,
            selected_indexes=selected_indexes,
            batches=batches,
            packet_path=prompt_packet_path,
            run_root=subagent_runs_dir,
            repo_root=project_root,
        )
    )
    run_log_path = resolve_run_log_path(
        getattr(args, "run_log_file", None),
        project_root=project_root,
        run_dir=run_dir,
    )
    append_run_log = make_run_log_writer(run_log_path)
    total_batches = len(selected_indexes)
    effective_workers = min(total_batches, max_parallel_batches) if run_parallel else 1
    waves = max(1, math.ceil(total_batches / max(1, effective_workers)))
    worst_case_minutes = max(1, math.ceil((waves * batch_timeout_seconds) / 60))
    log_run_start(
        append_run_log=append_run_log,
        colorize_fn=deps.colorize_fn,
        run_log_path=run_log_path,
        run_dir=run_dir,
        immutable_packet_path=immutable_packet_path,
        prompt_packet_path=prompt_packet_path,
        runner=runner,
        run_parallel=run_parallel,
        max_parallel_batches=max_parallel_batches,
        batch_timeout_seconds=batch_timeout_seconds,
        heartbeat_seconds=heartbeat_seconds,
        stall_warning_seconds=stall_warning_seconds,
        stall_kill_seconds=stall_kill_seconds,
        batch_max_retries=batch_max_retries,
        batch_retry_backoff_seconds=batch_retry_backoff_seconds,
        worst_case_minutes=worst_case_minutes,
        selected_indexes=selected_indexes,
    )
    batch_positions = {batch_idx: pos + 1 for pos, batch_idx in enumerate(selected_indexes)}
    batch_status = build_initial_batch_status(
        selected_indexes=selected_indexes,
        batch_positions=batch_positions,
        prompt_files=prompt_files,
        output_files=output_files,
        log_files=log_files,
    )
    stall_warned_batches: set[int] = set()
    report_progress = build_progress_reporter(
        batch_positions=batch_positions,
        batch_status=batch_status,
        stall_warned_batches=stall_warned_batches,
        total_batches=total_batches,
        stall_warning_seconds=stall_warning_seconds,
        prompt_files=prompt_files,
        output_files=output_files,
        log_files=log_files,
        append_run_log=append_run_log,
        colorize_fn=deps.colorize_fn,
    )
    record_issue = partial(record_execution_issue, append_run_log)
    write_run_summary = build_run_summary_writer(
        run_dir=run_dir,
        summary_config=BatchRunSummaryConfig(
            created_at=datetime.now(UTC).isoformat(timespec="seconds"),
            run_stamp=stamp,
            runner=runner,
            run_parallel=run_parallel,
            selected_indexes=selected_indexes,
            allow_partial=allow_partial,
            max_parallel_batches=max_parallel_batches,
            batch_timeout_seconds=batch_timeout_seconds,
            batch_max_retries=batch_max_retries,
            batch_retry_backoff_seconds=batch_retry_backoff_seconds,
            heartbeat_seconds=heartbeat_seconds,
            stall_warning_seconds=stall_warning_seconds,
            stall_kill_seconds=stall_kill_seconds,
            immutable_packet_path=immutable_packet_path,
            prompt_packet_path=prompt_packet_path,
            run_dir=run_dir,
            logs_dir=logs_dir,
            run_log_path=run_log_path,
        ),
        batch_status=batch_status,
        safe_write_text_fn=deps.safe_write_text_fn,
        colorize_fn=deps.colorize_fn,
        append_run_log=append_run_log,
    )
    return PreparedRunArtifacts(
        run_dir=run_dir,
        logs_dir=logs_dir,
        prompt_files=prompt_files,
        output_files=output_files,
        log_files=log_files,
        run_log_path=run_log_path,
        append_run_log=append_run_log,
        batch_positions=batch_positions,
        batch_status=batch_status,
        report_progress=report_progress,
        record_issue=record_issue,
        write_run_summary=write_run_summary,
    )


def prepare_batch_run(
    *,
    args,
    state,
    lang,
    config: dict[str, Any],
    deps: BatchRunDeps,
    project_root: Path,
    subagent_runs_dir: Path,
) -> PreparedBatchRunContext | None:
    """Prepare packet/artifacts and return execution context; None for dry-run."""
    runner = getattr(args, "runner", "codex")
    validate_runner(runner, colorize_fn=deps.colorize_fn)
    allow_partial = bool(getattr(args, "allow_partial", False))

    policy = _resolve_runtime_policy(args)

    stamp = deps.run_stamp_fn()
    packet_scope = _prepare_packet_scope(
        args=args,
        state=state,
        lang=lang,
        config=config,
        deps=deps,
        stamp=stamp,
    )
    total_batches = len(packet_scope.selected_indexes)
    _print_runtime_expectation(
        deps=deps,
        total_batches=total_batches,
        run_parallel=policy.run_parallel,
        max_parallel_batches=policy.max_parallel_batches,
        batch_timeout_seconds=policy.batch_timeout_seconds,
    )
    runtime_artifacts = _prepare_run_runtime(
        args=args,
        deps=deps,
        stamp=stamp,
        selected_indexes=packet_scope.selected_indexes,
        batches=packet_scope.batches,
        prompt_packet_path=packet_scope.prompt_packet_path,
        immutable_packet_path=packet_scope.immutable_packet_path,
        project_root=project_root,
        subagent_runs_dir=subagent_runs_dir,
        runner=runner,
        allow_partial=allow_partial,
        run_parallel=policy.run_parallel,
        max_parallel_batches=policy.max_parallel_batches,
        heartbeat_seconds=policy.heartbeat_seconds,
        batch_timeout_seconds=policy.batch_timeout_seconds,
        batch_max_retries=policy.batch_max_retries,
        batch_retry_backoff_seconds=policy.batch_retry_backoff_seconds,
        stall_warning_seconds=policy.stall_warning_seconds,
        stall_kill_seconds=policy.stall_kill_seconds,
    )
    if maybe_handle_dry_run(
        args=args,
        stamp=stamp,
        selected_indexes=packet_scope.selected_indexes,
        run_dir=runtime_artifacts.run_dir,
        logs_dir=runtime_artifacts.logs_dir,
        immutable_packet_path=packet_scope.immutable_packet_path,
        prompt_packet_path=packet_scope.prompt_packet_path,
        prompt_files=runtime_artifacts.prompt_files,
        output_files=runtime_artifacts.output_files,
        safe_write_text_fn=deps.safe_write_text_fn,
        colorize_fn=deps.colorize_fn,
        append_run_log=runtime_artifacts.append_run_log,
    ):
        return None

    if policy.run_parallel:
        print(
            deps.colorize_fn(
                "  Parallel runner config: "
                f"max-workers={min(total_batches, policy.max_parallel_batches)}, "
                f"heartbeat={policy.heartbeat_seconds:.1f}s",
                "dim",
            )
        )

    return PreparedBatchRunContext(
        stamp=stamp,
        args=args,
        config=config,
        runner=runner,
        allow_partial=allow_partial,
        run_parallel=policy.run_parallel,
        max_parallel_batches=policy.max_parallel_batches,
        heartbeat_seconds=policy.heartbeat_seconds,
        batch_timeout_seconds=policy.batch_timeout_seconds,
        batch_max_retries=policy.batch_max_retries,
        batch_retry_backoff_seconds=policy.batch_retry_backoff_seconds,
        stall_warning_seconds=policy.stall_warning_seconds,
        stall_kill_seconds=policy.stall_kill_seconds,
        state=state,
        lang=lang,
        packet=packet_scope.packet,
        immutable_packet_path=packet_scope.immutable_packet_path,
        prompt_packet_path=packet_scope.prompt_packet_path,
        scan_path=packet_scope.scan_path,
        packet_dimensions=packet_scope.packet_dimensions,
        scored_dimensions=packet_scope.scored_dimensions,
        batches=packet_scope.batches,
        selected_indexes=packet_scope.selected_indexes,
        project_root=project_root,
        run_dir=runtime_artifacts.run_dir,
        logs_dir=runtime_artifacts.logs_dir,
        prompt_files=runtime_artifacts.prompt_files,
        output_files=runtime_artifacts.output_files,
        log_files=runtime_artifacts.log_files,
        run_log_path=runtime_artifacts.run_log_path,
        append_run_log=runtime_artifacts.append_run_log,
        batch_positions=runtime_artifacts.batch_positions,
        batch_status=runtime_artifacts.batch_status,
        report_progress=runtime_artifacts.report_progress,
        record_issue=runtime_artifacts.record_issue,
        write_run_summary=runtime_artifacts.write_run_summary,
    )


def execute_batch_run(*, prepared: PreparedBatchRunContext, deps: BatchRunDeps) -> ExecutedBatchRunContext:
    """Execute prepared tasks and return reconciliation outputs."""
    selected_indexes = prepared.selected_indexes
    tasks = build_batch_tasks(
        selected_indexes=selected_indexes,
        prompt_files=prepared.prompt_files,
        output_files=prepared.output_files,
        log_files=prepared.log_files,
        project_root=prepared.project_root,
        run_codex_batch_fn=deps.run_codex_batch_fn,
    )
    try:
        execution_failures = deps.execute_batches_fn(
            tasks=tasks,
            options=BatchExecutionOptions(
                run_parallel=prepared.run_parallel,
                max_parallel_workers=prepared.max_parallel_batches,
                heartbeat_seconds=prepared.heartbeat_seconds,
            ),
            progress_fn=prepared.report_progress,
            error_log_fn=prepared.record_issue,
        )
    except KeyboardInterrupt:
        mark_interrupted_batches(
            selected_indexes=selected_indexes,
            batch_status=prepared.batch_status,
            batch_positions=prepared.batch_positions,
        )
        prepared.write_run_summary(
            successful_batches=[],
            failed_batches=[],
            interrupted=True,
            interruption_reason="keyboard_interrupt",
        )
        prepared.append_run_log("run-interrupted reason=keyboard_interrupt")
        raise SystemExit(130) from None

    batch_results, successful_indexes, failures, failure_set = collect_and_reconcile_results(
        collect_batch_results_fn=deps.collect_batch_results_fn,
        request=CollectBatchResultsRequest(
            selected_indexes=selected_indexes,
            failures=execution_failures,
            output_files=prepared.output_files,
            allowed_dims={
                str(dim)
                for dim in prepared.packet.get("dimensions", [])
                if isinstance(dim, str)
            },
        ),
        execution_failures=execution_failures,
        batch_positions=prepared.batch_positions,
        batch_status=prepared.batch_status,
        colorize_fn=deps.colorize_fn,
    )
    prepared.write_run_summary(
        successful_batches=[idx + 1 for idx in successful_indexes],
        failed_batches=[idx + 1 for idx in sorted(failure_set)],
    )

    if failures and (not prepared.allow_partial or not batch_results):
        prepared.append_run_log(
            f"run-finished failures={[idx + 1 for idx in sorted(failure_set)]} mode=exit"
        )
        deps.print_failures_and_raise_fn(
            failures=failures,
            packet_path=prepared.immutable_packet_path,
            logs_dir=prepared.logs_dir,
            colorize_fn=deps.colorize_fn,
        )
    elif failures:
        print(
            deps.colorize_fn(
                "  Partial completion enabled: importing successful batches and keeping failed batches open.",
                "yellow",
            )
        )
        deps.print_failures_fn(
            failures=failures,
            packet_path=prepared.immutable_packet_path,
            logs_dir=prepared.logs_dir,
            colorize_fn=deps.colorize_fn,
        )
        prepared.append_run_log(
            "run-partial "
            f"successful={[idx + 1 for idx in successful_indexes]} "
            f"failed={[idx + 1 for idx in sorted(failure_set)]}"
        )

    return ExecutedBatchRunContext(
        batch_results=batch_results,
        successful_indexes=successful_indexes,
        failure_set=failure_set,
    )


def _is_partial_batch_retry(prepared: PreparedBatchRunContext) -> bool:
    """Return True when the current run targets a subset of the packet's batches."""
    all_indexes = set(range(len(prepared.batches)))
    return set(prepared.selected_indexes) != all_indexes


def merge_and_import_batch_run(
    *,
    prepared: PreparedBatchRunContext,
    executed: ExecutedBatchRunContext,
    state_file,
    deps: BatchRunDeps,
) -> None:
    """Merge successful batch results and import final holistic output."""
    merged_path, missing_after_import = merge_and_write_results(
        merge_batch_results_fn=deps.merge_batch_results_fn,
        build_import_provenance_fn=deps.build_import_provenance_fn,
        batch_results=executed.batch_results,
        batches=prepared.batches,
        successful_indexes=executed.successful_indexes,
        packet=prepared.packet,
        packet_dimensions=prepared.packet_dimensions,
        scored_dimensions=prepared.scored_dimensions,
        scan_path=prepared.scan_path,
        runner=prepared.runner,
        prompt_packet_path=prepared.prompt_packet_path,
        stamp=prepared.stamp,
        run_dir=prepared.run_dir,
        safe_write_text_fn=deps.safe_write_text_fn,
        colorize_fn=deps.colorize_fn,
    )

    # When retrying a subset of batches (--only-batches), the merged output
    # only contains the retried dimensions.  Skip the coverage gate so the
    # partial result can be imported — the original run already covered the
    # remaining dimensions.
    allow_partial = prepared.allow_partial
    if _is_partial_batch_retry(prepared):
        allow_partial = True

    enforce_import_coverage(
        missing_after_import=missing_after_import,
        packet_dimensions=prepared.packet_dimensions,
        allow_partial=allow_partial,
        scan_path=prepared.scan_path,
        colorize_fn=deps.colorize_fn,
    )
    import_and_finalize(
        do_import_fn=deps.do_import_fn,
        run_followup_scan_fn=deps.run_followup_scan_fn,
        merged_path=merged_path,
        state=prepared.state,
        lang=prepared.lang,
        state_file=state_file,
        config=prepared.config,
        allow_partial=prepared.allow_partial,
        successful_indexes=executed.successful_indexes,
        failure_set=executed.failure_set,
        append_run_log=prepared.append_run_log,
        args=prepared.args,
    )


__all__ = [
    "ExecutedBatchRunContext",
    "PreparedPacketScope",
    "PreparedBatchRunContext",
    "PreparedRunArtifacts",
    "_is_partial_batch_retry",
    "_prepare_packet_scope",
    "_prepare_run_runtime",
    "_print_runtime_expectation",
    "_resolve_runtime_policy",
    "execute_batch_run",
    "merge_and_import_batch_run",
    "prepare_batch_run",
]
