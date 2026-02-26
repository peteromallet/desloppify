"""Batch execution flow helpers for review command."""

from __future__ import annotations

import json
import math
import shlex
import sys
from datetime import UTC, datetime
from pathlib import Path

from desloppify.intelligence.review.feedback_contract import (
    LEGACY_REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY,
    REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY,
)
from desloppify.intelligence.review.dimensions.data import load_dimensions_for_lang


def _validate_runner(runner: str, *, colorize_fn) -> None:
    """Validate review batch runner."""
    if runner == "codex":
        return
    print(
        colorize_fn(
            f"  Error: unsupported runner '{runner}' (supported: codex)", "red"
        ),
        file=sys.stderr,
    )
    sys.exit(2)


def _require_batches(
    packet: dict,
    *,
    colorize_fn,
    suggested_prepare_cmd: str | None = None,
) -> list[dict]:
    """Return investigation batches or exit with a clear error."""
    batches = packet.get("investigation_batches", [])
    if isinstance(batches, list) and batches:
        return batches
    print(
        colorize_fn("  Error: packet has no investigation_batches.", "red"),
        file=sys.stderr,
    )
    if isinstance(suggested_prepare_cmd, str) and suggested_prepare_cmd.strip():
        print(
            colorize_fn(
                f"  Regenerate review context first: `{suggested_prepare_cmd}`",
                "yellow",
            ),
            file=sys.stderr,
        )
    print(
        colorize_fn(
            "  Happy path: `desloppify review --run-batches --runner codex --parallel --scan-after-import`.",
            "dim",
        ),
        file=sys.stderr,
    )
    sys.exit(1)


def _print_review_quality(quality: object, *, colorize_fn) -> None:
    """Render merged review quality summary when present."""
    if not isinstance(quality, dict):
        return
    coverage = quality.get("dimension_coverage")
    density = quality.get("evidence_density")
    high_missing_issue_note = quality.get(
        REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY
    )
    if not isinstance(high_missing_issue_note, int | float):
        high_missing_issue_note = quality.get(
            LEGACY_REVIEW_QUALITY_HIGH_SCORE_MISSING_ISSUES_KEY
        )
    finding_pressure = quality.get("finding_pressure")
    dims_with_findings = quality.get("dimensions_with_findings")
    if not isinstance(coverage, int | float) or not isinstance(density, int | float):
        return

    pressure_segment = ""
    if isinstance(finding_pressure, int | float) and isinstance(dims_with_findings, int):
        pressure_segment = (
            f", finding-pressure {float(finding_pressure):.2f} "
            f"across {dims_with_findings} dims"
        )
    print(
        colorize_fn(
            "  Review quality: "
            f"dimension coverage {float(coverage):.2f}, "
            f"evidence density {float(density):.2f}, "
            f"high-score-missing-issue-note {int(high_missing_issue_note or 0)}"
            f"{pressure_segment}",
            "dim",
        )
    )


def _collect_reviewed_files_from_batches(
    *,
    batches: list[dict[str, object]],
    selected_indexes: list[int],
) -> list[str]:
    """Collect normalized file paths reviewed in the selected batch set."""
    reviewed: list[str] = []
    seen: set[str] = set()
    for idx in selected_indexes:
        if idx < 0 or idx >= len(batches):
            continue
        batch = batches[idx]
        files = batch.get("files_to_read", [])
        if not isinstance(files, list):
            continue
        for raw in files:
            if not isinstance(raw, str):
                continue
            path = raw.strip().strip(",'\"")
            if not path or path in {".", ".."}:
                continue
            if path.endswith("/"):
                continue
            if path in seen:
                continue
            seen.add(path)
            reviewed.append(path)
    return reviewed


def _coerce_positive_int(value: object, *, default: int, minimum: int = 1) -> int:
    """Parse positive integer CLI/config inputs with a safe default."""
    if value is None:
        return default
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _coerce_positive_float(value: object, *, default: float, minimum: float = 0.1) -> float:
    """Parse positive float CLI/config inputs with a safe default."""
    if value is None:
        return default
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= minimum else default


def _coerce_non_negative_float(value: object, *, default: float) -> float:
    """Parse non-negative float CLI/config inputs with a safe default."""
    if value is None:
        return default
    if not isinstance(value, int | float | str):
        return default
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0.0 else default


def _normalize_dimension_list(raw: object) -> list[str]:
    """Normalize dimension collections to a stable, de-duplicated list."""
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, str):
            continue
        dim = item.strip()
        if not dim or dim in seen:
            continue
        seen.add(dim)
        out.append(dim)
    return out


def _scored_dimensions_for_lang(lang_name: str) -> list[str]:
    """Return default scored subjective dimensions for one language."""
    try:
        default_dims, _, _ = load_dimensions_for_lang(lang_name)
    except (ValueError, RuntimeError):
        return []
    return _normalize_dimension_list(default_dims)


def _missing_scored_dimensions(
    *,
    selected_dims: list[str],
    scored_dims: list[str],
) -> list[str]:
    selected = set(selected_dims)
    return [dim for dim in scored_dims if dim not in selected]


def _missing_dimensions_command(*, missing_dims: list[str], scan_path: str) -> str:
    """Return rerun command for missing subjective dimensions."""
    base = "desloppify review --run-batches --runner codex --parallel --scan-after-import"
    if scan_path and scan_path != ".":
        base += f" --path {shlex.quote(scan_path)}"
    if missing_dims:
        base += f" --dimensions {','.join(missing_dims)}"
    return base


def _print_preflight_dimension_scope_notice(
    *,
    selected_dims: list[str],
    scored_dims: list[str],
    explicit_selection: bool,
    scan_path: str,
    colorize_fn,
) -> None:
    """Print trigger-time notice when run scope is a scored-dimension subset."""
    if not scored_dims:
        return
    missing_dims = _missing_scored_dimensions(
        selected_dims=selected_dims,
        scored_dims=scored_dims,
    )
    if not missing_dims:
        return

    covered_count = len([dim for dim in selected_dims if dim in set(scored_dims)])
    scope_reason = (
        "explicit --dimensions selection"
        if explicit_selection
        else "language default review dimension set"
    )
    tone = "yellow" if explicit_selection else "red"
    print(
        colorize_fn(
            "  WARNING: this run targets "
            f"{covered_count}/{len(scored_dims)} scored subjective dimensions "
            f"({scope_reason}).",
            tone,
        )
    )
    preview = ", ".join(missing_dims[:5])
    if len(missing_dims) > 5:
        preview = f"{preview}, +{len(missing_dims) - 5} more"
    print(colorize_fn(f"  Missing from this run: {preview}", "yellow"))
    print(
        colorize_fn(
            "  Rerun missing dimensions: "
            f"`{_missing_dimensions_command(missing_dims=missing_dims, scan_path=scan_path)}`",
            "dim",
        )
    )


def _print_import_dimension_coverage_notice(
    *,
    assessed_dims: list[str],
    scored_dims: list[str],
    scan_path: str,
    colorize_fn,
) -> list[str]:
    """Print result-time notice when merged import covers only a subset."""
    if not scored_dims:
        return []
    missing_dims = _missing_scored_dimensions(
        selected_dims=assessed_dims,
        scored_dims=scored_dims,
    )
    if not missing_dims:
        return []

    covered_count = len([dim for dim in assessed_dims if dim in set(scored_dims)])
    print(
        colorize_fn(
            "  Coverage gap: imported assessments for "
            f"{covered_count}/{len(scored_dims)} scored subjective dimensions.",
            "yellow",
        )
    )
    preview = ", ".join(missing_dims[:5])
    if len(missing_dims) > 5:
        preview = f"{preview}, +{len(missing_dims) - 5} more"
    print(colorize_fn(f"  Still missing: {preview}", "yellow"))
    print(
        colorize_fn(
            "  Run to cover missing dimensions: "
            f"`{_missing_dimensions_command(missing_dims=missing_dims, scan_path=scan_path)}`",
            "dim",
        )
    )
    return missing_dims


def do_run_batches(
    args,
    state,
    lang,
    state_file,
    *,
    config: dict | None,
    run_stamp_fn,
    load_or_prepare_packet_fn,
    selected_batch_indexes_fn,
    prepare_run_artifacts_fn,
    run_codex_batch_fn,
    execute_batches_fn,
    collect_batch_results_fn,
    print_failures_fn,
    print_failures_and_exit_fn,
    merge_batch_results_fn,
    build_import_provenance_fn,
    do_import_fn,
    run_followup_scan_fn,
    safe_write_text_fn,
    colorize_fn,
    project_root: Path,
    subagent_runs_dir: Path,
) -> None:
    """Run holistic investigation batches with a local subagent runner."""
    config = config or {}
    runner = getattr(args, "runner", "codex")
    _validate_runner(runner, colorize_fn=colorize_fn)
    allow_partial = bool(getattr(args, "allow_partial", False))
    run_parallel = bool(getattr(args, "parallel", False))
    max_parallel_batches = _coerce_positive_int(
        getattr(args, "max_parallel_batches", None),
        default=3,
        minimum=1,
    )
    heartbeat_seconds = _coerce_positive_float(
        getattr(args, "batch_heartbeat_seconds", None),
        default=15.0,
        minimum=0.1,
    )
    batch_timeout_seconds = _coerce_positive_int(
        getattr(args, "batch_timeout_seconds", None),
        default=2 * 60 * 60,
        minimum=1,
    )
    batch_max_retries = _coerce_positive_int(
        getattr(args, "batch_max_retries", None),
        default=1,
        minimum=0,
    )
    batch_retry_backoff_seconds = _coerce_non_negative_float(
        getattr(args, "batch_retry_backoff_seconds", None),
        default=2.0,
    )
    raw_stall_warning = getattr(args, "batch_stall_warning_seconds", None)
    stall_warning_seconds = 0
    if isinstance(raw_stall_warning, int | float | str):
        try:
            parsed_stall_warning = int(raw_stall_warning)
        except (TypeError, ValueError):
            parsed_stall_warning = 0
        stall_warning_seconds = parsed_stall_warning if parsed_stall_warning > 0 else 0
    raw_stall_kill = getattr(args, "batch_stall_kill_seconds", None)
    stall_kill_seconds = 0
    if isinstance(raw_stall_kill, int | float | str):
        try:
            parsed_stall_kill = int(raw_stall_kill)
        except (TypeError, ValueError):
            parsed_stall_kill = 0
        stall_kill_seconds = parsed_stall_kill if parsed_stall_kill > 0 else 0

    stamp = run_stamp_fn()
    packet, immutable_packet_path, prompt_packet_path = load_or_prepare_packet_fn(
        args,
        state=state,
        lang=lang,
        config=config,
        stamp=stamp,
    )

    scan_path = str(getattr(args, "path", ".") or ".")
    packet_dimensions = _normalize_dimension_list(packet.get("dimensions", []))
    scored_dimensions = _scored_dimensions_for_lang(lang.name)
    _print_preflight_dimension_scope_notice(
        selected_dims=packet_dimensions,
        scored_dims=scored_dimensions,
        explicit_selection=bool(getattr(args, "dimensions", None)),
        scan_path=scan_path,
        colorize_fn=colorize_fn,
    )
    suggested_prepare_cmd = f"desloppify review --prepare --path {scan_path}"
    batches = _require_batches(
        packet,
        colorize_fn=colorize_fn,
        suggested_prepare_cmd=suggested_prepare_cmd,
    )

    selected_indexes = selected_batch_indexes_fn(args, batch_count=len(batches))
    total_batches = len(selected_indexes)
    effective_workers = min(total_batches, max_parallel_batches) if run_parallel else 1
    waves = max(1, math.ceil(total_batches / max(1, effective_workers)))
    worst_case_seconds = waves * batch_timeout_seconds
    worst_case_minutes = max(1, math.ceil(worst_case_seconds / 60))
    print(
        colorize_fn(
            "  Runtime expectation: "
            f"{total_batches} batch(es), workers={effective_workers}, "
            f"timeout-per-batch={int(batch_timeout_seconds / 60)}m, "
            f"worst-case upper bound ~{worst_case_minutes}m.",
            "dim",
        )
    )
    run_dir, logs_dir, prompt_files, output_files, log_files = prepare_run_artifacts_fn(
        stamp=stamp,
        selected_indexes=selected_indexes,
        batches=batches,
        packet_path=prompt_packet_path,
        run_root=subagent_runs_dir,
        repo_root=project_root,
    )
    raw_run_log_file = getattr(args, "run_log_file", None)
    run_log_file_value = (
        raw_run_log_file.strip()
        if isinstance(raw_run_log_file, str) and raw_run_log_file.strip()
        else None
    )
    if run_log_file_value is not None:
        candidate = Path(run_log_file_value).expanduser()
        run_log_path = candidate if candidate.is_absolute() else project_root / candidate
    else:
        run_log_path = run_dir / "run.log"
    run_log_path.parent.mkdir(parents=True, exist_ok=True)

    def _append_run_log(message: str) -> None:
        line = f"{datetime.now(UTC).isoformat(timespec='seconds')} {message}\n"
        try:
            with run_log_path.open("a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            return

    _append_run_log(
        "run-start "
        f"runner={runner} parallel={run_parallel} max_parallel={max_parallel_batches} "
        f"timeout={batch_timeout_seconds}s heartbeat={heartbeat_seconds:.1f}s "
        f"stall_warning={stall_warning_seconds}s stall_kill={stall_kill_seconds}s "
        f"retries={batch_max_retries} "
        f"retry_backoff={batch_retry_backoff_seconds:.1f}s upper_bound={worst_case_minutes}m "
        f"selected={[idx + 1 for idx in selected_indexes]}"
    )
    _append_run_log(f"run-path {run_dir}")
    _append_run_log(f"packet {immutable_packet_path}")
    _append_run_log(f"blind-packet {prompt_packet_path}")
    print(colorize_fn(f"  Live run log: {run_log_path}", "dim"))

    if getattr(args, "dry_run", False):
        print(
            colorize_fn(
                "  Dry run only: prompts generated, runner execution skipped.", "yellow"
            )
        )
        print(colorize_fn(f"  Immutable packet: {immutable_packet_path}", "dim"))
        print(colorize_fn(f"  Blind packet: {prompt_packet_path}", "dim"))
        print(colorize_fn(f"  Prompts: {run_dir / 'prompts'}", "dim"))
        _append_run_log("run-finished dry-run")
        return

    def _run_batch(*, prompt: str, output_file: Path, log_file: Path) -> int:
        return run_codex_batch_fn(
            prompt=prompt,
            repo_root=project_root,
            output_file=output_file,
            log_file=log_file,
        )

    def _make_task(batch_index: int):
        prompt_path = prompt_files[batch_index]
        output_path = output_files[batch_index]
        log_path = log_files[batch_index]

        def _task() -> int:
            try:
                prompt = prompt_path.read_text()
            except OSError as exc:
                raise RuntimeError(
                    f"unable to read prompt for batch #{batch_index + 1}: {prompt_path}"
                ) from exc
            return _run_batch(prompt=prompt, output_file=output_path, log_file=log_path)

        return _task

    tasks = {idx: _make_task(idx) for idx in selected_indexes}

    batch_positions = {batch_idx: pos + 1 for pos, batch_idx in enumerate(selected_indexes)}
    summary_created_at = datetime.now(UTC).isoformat(timespec="seconds")
    stall_warned_batches: set[int] = set()
    batch_status: dict[str, dict[str, object]] = {
        str(idx + 1): {
            "position": batch_positions.get(idx, 0),
            "status": "pending",
            "prompt_path": str(prompt_files[idx]),
            "result_path": str(output_files[idx]),
            "log_path": str(log_files[idx]),
        }
        for idx in selected_indexes
    }

    if run_parallel:
        print(
            colorize_fn(
                "  Parallel runner config: "
                f"max-workers={min(total_batches, max_parallel_batches)}, "
                f"heartbeat={heartbeat_seconds:.1f}s",
                "dim",
            )
        )

    def _report_progress(
        batch_index: int,
        event: str,
        code: int | None = None,
        **details,
    ) -> None:
        if event == "heartbeat":
            active = details.get("active_batches")
            queued = details.get("queued_batches", [])
            elapsed = details.get("elapsed_seconds", {})
            if not isinstance(active, list):
                active = []
            if not isinstance(queued, list):
                queued = []
            if not active and not queued:
                return
            segments: list[str] = []
            for idx in active[:6]:
                secs = 0
                if isinstance(elapsed, dict):
                    raw_secs = elapsed.get(idx, 0)
                    secs = int(raw_secs) if isinstance(raw_secs, int | float) else 0
                segments.append(f"#{idx + 1}:{secs}s")
            if len(active) > 6:
                segments.append(f"+{len(active) - 6} more")
            queued_segment = ""
            if queued:
                queued_segment = f", queued {len(queued)}"
            print(
                colorize_fn(
                    "  Batch heartbeat: "
                    f"{len(active)}/{total_batches} active{queued_segment} "
                    f"({', '.join(segments) if segments else 'running batches pending'})",
                    "dim",
                )
            )
            _append_run_log(
                "heartbeat "
                f"active={[idx + 1 for idx in active]} queued={[idx + 1 for idx in queued]} "
                f"elapsed={{{', '.join(f'{idx + 1}:{elapsed.get(idx, 0)}' for idx in active)}}}"
            )
            if stall_warning_seconds > 0 and isinstance(elapsed, dict):
                slow_active = [
                    idx
                    for idx in active
                    if isinstance(elapsed.get(idx), int | float)
                    and int(elapsed.get(idx) or 0) >= stall_warning_seconds
                ]
                newly_warned = [idx for idx in slow_active if idx not in stall_warned_batches]
                if newly_warned:
                    stall_warned_batches.update(newly_warned)
                    warning_message = (
                        "  Stall warning: batches "
                        f"{[idx + 1 for idx in sorted(newly_warned)]} exceeded "
                        f"{stall_warning_seconds}s elapsed. "
                        "This may be normal for long runs; review run.log and batch logs."
                    )
                    print(colorize_fn(warning_message, "yellow"))
                    _append_run_log(
                        "stall-warning "
                        f"threshold={stall_warning_seconds}s batches={[idx + 1 for idx in sorted(newly_warned)]}"
                    )
            return

        position = batch_positions.get(batch_index, 0)
        key = str(batch_index + 1)
        state = batch_status.setdefault(
            key,
            {
                "position": position,
                "status": "pending",
                "prompt_path": str(prompt_files.get(batch_index, "")),
                "result_path": str(output_files.get(batch_index, "")),
                "log_path": str(log_files.get(batch_index, "")),
            },
        )
        if event == "queued":
            state["status"] = "queued"
            print(
                colorize_fn(
                    f"  Batch {position}/{total_batches} queued (#{batch_index + 1})",
                    "dim",
                )
            )
            _append_run_log(f"batch-queued batch={batch_index + 1} position={position}/{total_batches}")
            return
        if event == "start":
            state["status"] = "running"
            state["started_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            print(
                colorize_fn(
                    f"  Batch {position}/{total_batches} started (#{batch_index + 1})",
                    "dim",
                )
            )
            _append_run_log(f"batch-start batch={batch_index + 1} position={position}/{total_batches}")
            return
        if event == "done":
            status = "done" if code == 0 else f"failed ({code})"
            tone = "dim" if code == 0 else "yellow"
            elapsed_seconds = details.get("elapsed_seconds")
            elapsed_suffix = ""
            if isinstance(elapsed_seconds, int | float):
                elapsed_suffix = f" in {int(max(0, elapsed_seconds))}s"
                state["elapsed_seconds"] = int(max(0, elapsed_seconds))
            state["status"] = "succeeded" if code == 0 else "failed"
            state["exit_code"] = int(code) if isinstance(code, int) else code
            state["completed_at"] = datetime.now(UTC).isoformat(timespec="seconds")
            if batch_index in stall_warned_batches:
                stall_warned_batches.discard(batch_index)
            print(
                colorize_fn(
                    f"  Batch {position}/{total_batches} {status}{elapsed_suffix} (#{batch_index + 1})",
                    tone,
                )
            )
            _append_run_log(
                f"batch-done batch={batch_index + 1} position={position}/{total_batches} "
                f"code={code} elapsed={state.get('elapsed_seconds', 0)}"
            )

    def _record_execution_issue(batch_index: int, exc: Exception) -> None:
        if batch_index < 0:
            _append_run_log(f"execution-error heartbeat error={exc}")
            return
        _append_run_log(f"execution-error batch={batch_index + 1} error={exc}")

    run_summary_path = run_dir / "run_summary.json"

    def _write_run_summary(
        *,
        successful_batches: list[int],
        failed_batches: list[int],
        interrupted: bool = False,
        interruption_reason: str | None = None,
    ) -> None:
        run_summary: dict[str, object] = {
            "created_at": summary_created_at,
            "run_stamp": stamp,
            "runner": runner,
            "parallel": run_parallel,
            "selected_batches": [idx + 1 for idx in selected_indexes],
            "successful_batches": successful_batches,
            "failed_batches": failed_batches,
            "allow_partial": allow_partial,
            "max_parallel_batches": max_parallel_batches if run_parallel else 1,
            "batch_timeout_seconds": batch_timeout_seconds,
            "batch_max_retries": batch_max_retries,
            "batch_retry_backoff_seconds": batch_retry_backoff_seconds,
            "batch_heartbeat_seconds": heartbeat_seconds if run_parallel else None,
            "batch_stall_warning_seconds": stall_warning_seconds if run_parallel else None,
            "batch_stall_kill_seconds": stall_kill_seconds,
            "immutable_packet": str(immutable_packet_path),
            "blind_packet": str(prompt_packet_path),
            "run_dir": str(run_dir),
            "logs_dir": str(logs_dir),
            "run_log": str(run_log_path),
            "batches": batch_status,
        }
        if interrupted:
            run_summary["interrupted"] = True
            if interruption_reason:
                run_summary["interruption_reason"] = interruption_reason
        safe_write_text_fn(run_summary_path, json.dumps(run_summary, indent=2) + "\n")
        print(colorize_fn(f"  Run summary: {run_summary_path}", "dim"))
        _append_run_log(f"run-summary {run_summary_path}")

    try:
        execution_failures = execute_batches_fn(
            tasks=tasks,
            run_parallel=run_parallel,
            progress_fn=_report_progress,
            error_log_fn=_record_execution_issue,
            max_parallel_workers=max_parallel_batches,
            heartbeat_seconds=heartbeat_seconds,
        )
    except KeyboardInterrupt:
        for idx in selected_indexes:
            key = str(idx + 1)
            state = batch_status.setdefault(
                key,
                {"position": batch_positions.get(idx, 0), "status": "pending"},
            )
            if state.get("status") in {"pending", "queued", "running"}:
                state["status"] = "interrupted"
        _write_run_summary(
            successful_batches=[],
            failed_batches=[],
            interrupted=True,
            interruption_reason="keyboard_interrupt",
        )
        _append_run_log("run-interrupted reason=keyboard_interrupt")
        raise SystemExit(130) from None

    allowed_dims = {
        str(dim) for dim in packet.get("dimensions", []) if isinstance(dim, str)
    }
    batch_results, failures = collect_batch_results_fn(
        selected_indexes=selected_indexes,
        failures=execution_failures,
        output_files=output_files,
        allowed_dims=allowed_dims,
    )

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
            state["status"] = "succeeded"
            continue
        if idx in execution_failure_set:
            state["status"] = "failed"
            continue
        if not output_files[idx].exists():
            state["status"] = "missing_output"
            continue
        state["status"] = "parse_failed"

    _write_run_summary(
        successful_batches=[idx + 1 for idx in successful_indexes],
        failed_batches=[idx + 1 for idx in sorted(failure_set)],
    )

    if failures and (not allow_partial or not batch_results):
        _append_run_log(
            f"run-finished failures={[idx + 1 for idx in sorted(failure_set)]} mode=exit"
        )
        print_failures_and_exit_fn(
            failures=failures,
            packet_path=immutable_packet_path,
            logs_dir=logs_dir,
            colorize_fn=colorize_fn,
        )
    elif failures:
        print(
            colorize_fn(
                "  Partial completion enabled: importing successful batches and keeping failed batches open.",
                "yellow",
            )
        )
        print_failures_fn(
            failures=failures,
            packet_path=immutable_packet_path,
            logs_dir=logs_dir,
            colorize_fn=colorize_fn,
        )
        _append_run_log(
            "run-partial "
            f"successful={[idx + 1 for idx in successful_indexes]} "
            f"failed={[idx + 1 for idx in sorted(failure_set)]}"
        )

    merged = merge_batch_results_fn(batch_results)
    reviewed_files = _collect_reviewed_files_from_batches(
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
    merged_assessment_dims = _normalize_dimension_list(
        list((merged.get("assessments") or {}).keys())
    )
    merged_finding_dims = _normalize_dimension_list(
        [
            finding.get("dimension")
            for finding in (merged.get("findings") or [])
            if isinstance(finding, dict)
        ]
    )
    merged_imported_dims = _normalize_dimension_list(
        merged_assessment_dims + merged_finding_dims
    )
    review_scope["imported_dimensions"] = merged_imported_dims
    missing_after_import = _print_import_dimension_coverage_notice(
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
    merged_path = run_dir / "holistic_findings_merged.json"
    safe_write_text_fn(merged_path, json.dumps(merged, indent=2) + "\n")
    print(colorize_fn(f"\n  Merged outputs: {merged_path}", "bold"))
    _print_review_quality(merged.get("review_quality", {}), colorize_fn=colorize_fn)

    try:
        do_import_fn(
            str(merged_path),
            state,
            lang,
            state_file,
            config=config,
            allow_partial=allow_partial,
            trusted_assessment_source=True,
            trusted_assessment_label="trusted internal run-batches import",
        )
    except SystemExit as exc:
        _append_run_log(f"run-finished import-failed code={exc.code}")
        raise
    except Exception as exc:
        _append_run_log(f"run-finished import-error error={exc}")
        raise
    _append_run_log(
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
            print(
                colorize_fn(
                    f"  Follow-up scan failed with exit code {followup_code}.",
                    "red",
                ),
                file=sys.stderr,
            )
            raise SystemExit(followup_code)


__all__ = ["do_run_batches"]
