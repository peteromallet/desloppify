"""Triage stage pipeline — Codex subprocess runner and Claude orchestrator."""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

from desloppify.app.commands.review._runner_parallel_types import BatchExecutionOptions
from desloppify.app.commands.review.batches_runtime import make_run_log_writer
from desloppify.app.commands.review.runner_parallel import execute_batches
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.discovery.paths import get_project_root
from desloppify.base.output.terminal import colorize

from ..helpers import (
    group_issues_into_observe_batches,
    has_triage_in_queue,
    inject_triage_stages,
)
from ..services import TriageServices, default_triage_services
from .stage_prompts import build_observe_batch_prompt, build_stage_prompt
from .stage_validation import build_auto_attestation, validate_stage

_STAGES = ("observe", "reflect", "organize", "enrich")


def _run_stamp() -> str:
    return datetime.now(UTC).strftime("%Y%m%d_%H%M%S")


def _parse_only_stages(raw: str | None) -> list[str]:
    """Parse --only-stages comma-separated string into validated stage list."""
    if not raw:
        return list(_STAGES)
    stages = [s.strip().lower() for s in raw.split(",") if s.strip()]
    for s in stages:
        if s not in _STAGES:
            raise ValueError(f"Unknown stage: {s!r}. Valid: {', '.join(_STAGES)}")
    return stages


def _ensure_triage_started(
    plan: dict,
    services: TriageServices,
) -> dict:
    """Auto-start triage if not started. Returns updated plan."""
    if not has_triage_in_queue(plan):
        inject_triage_stages(plan)
        meta = plan.setdefault("epic_triage_meta", {})
        meta.setdefault("triage_stages", {})
        services.save_plan(plan)
        print(colorize("  Planning mode auto-started.", "cyan"))
    return plan


def do_run_triage_stages(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Run triage stages via the selected runner."""
    runner = str(getattr(args, "runner", "codex")).strip().lower()
    if runner == "claude":
        _run_claude_orchestrator(args, services=services)
    elif runner == "codex":
        _run_codex_pipeline(args, services=services)
    else:
        print(colorize(f"  Unknown runner: {runner}. Use 'codex' or 'claude'.", "red"))


def _run_claude_orchestrator(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Print orchestrator instructions for Claude Code agent."""
    resolved_services = services or default_triage_services()
    repo_root = get_project_root()
    plan = resolved_services.load_plan()
    _ensure_triage_started(plan, resolved_services)

    print(colorize("\n  Claude triage orchestrator mode.", "bold"))
    print(colorize("  " + "─" * 60, "dim"))
    print(colorize(
        "  You are the orchestrator. For each stage, launch a subagent.\n",
        "cyan",
    ))
    print("  For each stage (observe → reflect → organize → enrich):\n")
    print("    1. Get the prompt:")
    print("       desloppify plan triage --stage-prompt <stage>\n")
    print("    2. Launch a subagent (Agent tool) with that prompt.\n")
    print("    3. Verify the stage was recorded:")
    print("       desloppify plan triage\n")
    print("    4. Confirm:")
    print('       desloppify plan triage --confirm <stage> --attestation "..."\n')
    print("    5. Proceed to the next stage.\n")
    print("  After all 4 stages:")
    print('    desloppify plan triage --complete --strategy "..." --attestation "..."\n')
    print(colorize("  Key rules:", "yellow"))
    print("    - ONE subagent per stage. Don't combine stages.")
    print("    - Check the dashboard between stages.")
    print("    - Observe subagent should use sub-subagents (one per dimension group).")
    print("    - Enrich subagent should use sub-subagents (one per cluster).")
    print("    - If a stage fails validation, fix and re-record.")


def _merge_observe_outputs(
    batch_outputs: list[tuple[list[str], Path]],
) -> str:
    """Concatenate batch outputs with dimension headers into single observe report."""
    parts: list[str] = []
    for dims, output_file in batch_outputs:
        header = f"## Dimensions: {', '.join(dims)}"
        content = ""
        if output_file.exists():
            try:
                content = output_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                content = "(batch output missing)"
        if not content:
            content = "(batch produced no output)"
        parts.append(f"{header}\n\n{content}")
    return "\n\n---\n\n".join(parts)


def _run_observe(
    *,
    si,
    repo_root: Path,
    prompts_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    timeout_seconds: int,
    dry_run: bool = False,
    append_run_log=None,
) -> tuple[bool, str]:
    """Run observe stage via codex subprocess batches.

    Returns (ok, merged_report) where ok is True on success, False on failure.
    """
    from functools import partial

    from desloppify.app.commands.review._runner_parallel_types import BatchProgressEvent

    from .codex_runner import _output_file_has_text, run_triage_stage

    _log = append_run_log or (lambda _msg: None)

    batches = group_issues_into_observe_batches(si)
    total = len(batches)
    print(colorize(f"\n  Observe: splitting into {total} parallel batches.", "bold"))
    _log(f"observe-parallel batches={total}")

    # Build prompts and tasks
    tasks: dict[int, object] = {}
    batch_meta: list[tuple[list[str], Path]] = []

    for i, (dims, issues_subset) in enumerate(batches):
        prompt = build_observe_batch_prompt(
            batch_index=i + 1,
            total_batches=total,
            dimension_group=dims,
            issues_subset=issues_subset,
            repo_root=repo_root,
        )
        prompt_file = prompts_dir / f"observe_batch_{i}.md"
        safe_write_text(prompt_file, prompt)

        output_file = output_dir / f"observe_batch_{i}.raw.txt"
        log_file = logs_dir / f"observe_batch_{i}.log"
        batch_meta.append((dims, output_file))

        if not dry_run:
            tasks[i] = partial(
                run_triage_stage,
                prompt=prompt,
                repo_root=repo_root,
                output_file=output_file,
                log_file=log_file,
                timeout_seconds=timeout_seconds,
                validate_output_fn=_output_file_has_text,
            )

        dim_list = ", ".join(dims)
        print(colorize(f"    Batch {i + 1}: {len(issues_subset)} issues ({dim_list})", "dim"))
        _log(f"observe-batch batch={i + 1} issues={len(issues_subset)} dims={dim_list}")

    if dry_run:
        print(colorize("  [dry-run] Would execute parallel observe batches.", "dim"))
        return True, ""

    # Progress callback — same pattern as review batch execution
    def _progress(event: BatchProgressEvent) -> None:
        idx = event.batch_index
        if event.event == "start":
            print(colorize(f"    Observe batch {idx + 1}/{total} started", "dim"))
            _log(f"observe-batch-start batch={idx + 1}")
        elif event.event == "done":
            elapsed = event.details.get("elapsed_seconds", 0) if event.details else 0
            status = "done" if event.code == 0 else f"failed ({event.code})"
            tone = "dim" if event.code == 0 else "yellow"
            print(colorize(f"    Observe batch {idx + 1}/{total} {status} in {int(elapsed)}s", tone))
            _log(f"observe-batch-done batch={idx + 1} code={event.code} elapsed={int(elapsed)}s")
        elif event.event == "heartbeat":
            details = event.details or {}
            active = details.get("active_batches", [])
            elapsed_map = details.get("elapsed_seconds", {})
            if active:
                parts = [f"#{i + 1}:{int(elapsed_map.get(i, 0))}s" for i in active[:6]]
                print(colorize(f"    Observe heartbeat: {len(active)}/{total} active ({', '.join(parts)})", "dim"))

    def _error_log(batch_index: int, exc: Exception) -> None:
        _log(f"observe-batch-error batch={batch_index + 1} error={exc}")

    # Execute in parallel
    failures = execute_batches(
        tasks=tasks,
        options=BatchExecutionOptions(run_parallel=True, heartbeat_seconds=15.0),
        progress_fn=_progress,
        error_log_fn=_error_log,
    )

    if failures:
        print(colorize(
            f"  Observe: {len(failures)} batch(es) failed: {failures}",
            "red",
        ))
        for idx in failures:
            log_file = logs_dir / f"observe_batch_{idx}.log"
            print(colorize(f"    Check log: {log_file}", "dim"))
        _log(f"observe-parallel-failed failures={failures}")
        return False, ""

    merged = _merge_observe_outputs(batch_meta)
    print(colorize(f"  Observe: merged {total} batch outputs ({len(merged)} chars).", "green"))
    _log(f"observe-parallel-done merged_chars={len(merged)}")
    return True, merged


def _run_codex_pipeline(
    args: argparse.Namespace,
    *,
    services: TriageServices | None = None,
) -> None:
    """Run triage stages via Codex subprocesses (automated pipeline)."""
    from .codex_runner import run_triage_stage

    resolved_services = services or default_triage_services()
    timeout_seconds = int(getattr(args, "stage_timeout_seconds", 1800) or 1800)
    dry_run = bool(getattr(args, "dry_run", False))

    try:
        stages_to_run = _parse_only_stages(getattr(args, "only_stages", None))
    except ValueError as exc:
        print(colorize(f"  {exc}", "red"))
        return

    repo_root = get_project_root()
    plan = resolved_services.load_plan()
    _ensure_triage_started(plan, resolved_services)

    # Create run directory
    stamp = _run_stamp()
    desloppify_dir = repo_root / ".desloppify"
    run_dir = desloppify_dir / "triage_runs" / stamp
    prompts_dir = run_dir / "prompts"
    output_dir = run_dir / "output"
    logs_dir = run_dir / "logs"
    for d in (prompts_dir, output_dir, logs_dir):
        d.mkdir(parents=True, exist_ok=True)

    # Run log — same pattern as review batch execution
    run_log_path = run_dir / "run.log"
    append_run_log = make_run_log_writer(run_log_path)
    append_run_log(
        f"run-start runner=codex stages={','.join(stages_to_run)} "
        f"timeout={timeout_seconds}s dry_run={dry_run}"
    )

    print(colorize(f"  Run artifacts: {run_dir}", "dim"))
    print(colorize(f"  Live run log:  {run_log_path}", "dim"))

    # Collect triage input
    runtime = resolved_services.command_runtime(args)
    state = runtime.state

    prior_reports: dict[str, str] = {}
    stage_results: dict[str, dict] = {}
    pipeline_start = time.monotonic()

    for stage in stages_to_run:
        plan = resolved_services.load_plan()
        meta = plan.get("epic_triage_meta", {})
        stages = meta.get("triage_stages", {})

        # Skip if already confirmed (resume support)
        if stage in stages and stages[stage].get("confirmed_at"):
            print(colorize(f"  Stage {stage}: already confirmed, skipping.", "green"))
            append_run_log(f"stage-skip stage={stage} reason=already_confirmed")
            stage_results[stage] = {"status": "skipped"}
            report = stages[stage].get("report", "")
            if report:
                prior_reports[stage] = report
            continue

        stage_start = time.monotonic()
        append_run_log(f"stage-start stage={stage}")

        # Collect fresh triage input each stage
        si = resolved_services.collect_triage_input(plan, state)

        # Parallel observe path
        used_parallel = False
        if stage == "observe":
            parallel_ok, merged_report = _run_observe(
                si=si,
                repo_root=repo_root,
                prompts_dir=prompts_dir,
                output_dir=output_dir,
                logs_dir=logs_dir,
                timeout_seconds=timeout_seconds,
                dry_run=dry_run,
                append_run_log=append_run_log,
            )
            if parallel_ok is True and dry_run:
                stage_results[stage] = {"status": "dry_run"}
                continue
            if parallel_ok is True and merged_report:
                # Record observe via the stage command with merged report
                from ..stage_flow_commands import cmd_stage_observe
                record_args = argparse.Namespace(
                    stage="observe",
                    report=merged_report,
                    state=getattr(args, "state", None),
                )
                cmd_stage_observe(record_args, services=resolved_services)
                used_parallel = True
            elif parallel_ok is False:
                # Parallel execution failed — abort pipeline
                elapsed = int(time.monotonic() - stage_start)
                print(colorize("  Observe: parallel execution failed. Aborting.", "red"))
                append_run_log(f"stage-failed stage=observe elapsed={elapsed}s reason=parallel_execution_failed")
                stage_results[stage] = {"status": "failed", "elapsed_seconds": elapsed}
                _write_triage_run_summary(run_dir, stamp, stages_to_run, stage_results, append_run_log)
                return
            # parallel_ok is None → not applicable, fall through to single path

        # Single-subprocess path (non-observe stages, or observe with too few issues)
        if not used_parallel:
            prompt = build_stage_prompt(
                stage, si, prior_reports, repo_root=repo_root,
            )

            prompt_file = prompts_dir / f"{stage}.md"
            safe_write_text(prompt_file, prompt)

            if dry_run:
                print(colorize(f"  Stage {stage}: prompt written to {prompt_file}", "cyan"))
                print(colorize("  [dry-run] Would execute codex subprocess.", "dim"))
                stage_results[stage] = {"status": "dry_run"}
                continue

            print(colorize(f"\n  Stage {stage}: launching codex subprocess...", "bold"))
            append_run_log(f"stage-subprocess-start stage={stage}")

            output_file = output_dir / f"{stage}.raw.txt"
            log_file = logs_dir / f"{stage}.log"

            exit_code = run_triage_stage(
                prompt=prompt,
                repo_root=repo_root,
                output_file=output_file,
                log_file=log_file,
                timeout_seconds=timeout_seconds,
            )

            elapsed = int(time.monotonic() - stage_start)
            append_run_log(f"stage-subprocess-done stage={stage} code={exit_code} elapsed={elapsed}s")

            if exit_code != 0:
                print(colorize(f"  Stage {stage}: codex subprocess failed (exit {exit_code}).", "red"))
                print(colorize(f"  Check log: {log_file}", "dim"))
                print(colorize("  Re-run to resume (confirmed stages are skipped).", "dim"))
                append_run_log(f"stage-failed stage={stage} elapsed={elapsed}s code={exit_code}")
                stage_results[stage] = {"status": "failed", "exit_code": exit_code, "elapsed_seconds": elapsed}
                _write_triage_run_summary(run_dir, stamp, stages_to_run, stage_results, append_run_log)
                return

        # Common path: reload for validation
        plan = resolved_services.load_plan()
        meta = plan.get("epic_triage_meta", {})
        stages_data = meta.get("triage_stages", {})

        # Validate stage
        ok, error_msg = validate_stage(stage, plan, state, repo_root, triage_input=si)
        if not ok:
            elapsed = int(time.monotonic() - stage_start)
            print(colorize(f"  Stage {stage}: validation failed: {error_msg}", "red"))
            print(colorize("  Re-run to resume.", "dim"))
            append_run_log(f"stage-validation-failed stage={stage} elapsed={elapsed}s error={error_msg}")
            stage_results[stage] = {"status": "validation_failed", "elapsed_seconds": elapsed, "error": error_msg}
            _write_triage_run_summary(run_dir, stamp, stages_to_run, stage_results, append_run_log)
            return

        # Auto-confirm via confirmation functions with generated attestation
        attestation = build_auto_attestation(stage, plan, si)

        # Build a synthetic args namespace for confirm functions
        confirm_args = argparse.Namespace(
            confirm=stage,
            attestation=attestation,
            state=getattr(args, "state", None),
        )

        from ..confirmations import _cmd_confirm_stage
        _cmd_confirm_stage(confirm_args, services=resolved_services)

        # Re-load and check confirmation took effect
        plan = resolved_services.load_plan()
        meta = plan.get("epic_triage_meta", {})
        stages_data = meta.get("triage_stages", {})
        elapsed = int(time.monotonic() - stage_start)
        if stage in stages_data and stages_data[stage].get("confirmed_at"):
            print(colorize(f"  Stage {stage}: confirmed ({elapsed}s).", "green"))
            append_run_log(f"stage-confirmed stage={stage} elapsed={elapsed}s")
            stage_results[stage] = {"status": "confirmed", "elapsed_seconds": elapsed}
        else:
            print(colorize(f"  Stage {stage}: auto-confirmation did not take effect.", "red"))
            print(colorize("  Re-run to resume.", "dim"))
            append_run_log(f"stage-confirm-failed stage={stage} elapsed={elapsed}s")
            stage_results[stage] = {"status": "confirm_failed", "elapsed_seconds": elapsed}
            _write_triage_run_summary(run_dir, stamp, stages_to_run, stage_results, append_run_log)
            return

        # Accumulate report for next stage's prompt
        report = stages_data.get(stage, {}).get("report", "")
        if report:
            prior_reports[stage] = report

    if dry_run:
        print(colorize("\n  [dry-run] All prompts generated. No stages executed.", "cyan"))
        _write_triage_run_summary(run_dir, stamp, stages_to_run, stage_results, append_run_log)
        return

    # Auto-complete triage
    plan = resolved_services.load_plan()
    meta = plan.get("epic_triage_meta", {})
    stages_data = meta.get("triage_stages", {})

    # Derive strategy from all stage reports
    strategy_parts: list[str] = []
    for s in _STAGES:
        report = stages_data.get(s, {}).get("report", "")
        if report:
            strategy_parts.append(f"[{s}] {report[:200]}")
    strategy = " ".join(strategy_parts)
    if len(strategy) < 200:
        strategy = strategy + " " + "Automated triage via codex subagent pipeline. " * 3

    print(colorize("\n  Completing triage...", "bold"))

    # Build attestation for completion
    attestation = build_auto_attestation("enrich", plan, si)
    complete_args = argparse.Namespace(
        complete=True,
        strategy=strategy[:2000],
        attestation=attestation,
        state=getattr(args, "state", None),
    )

    from ..stage_completion_commands import _cmd_triage_complete
    _cmd_triage_complete(complete_args, services=resolved_services)

    total_elapsed = int(time.monotonic() - pipeline_start)
    print(colorize(f"\n  Triage pipeline complete ({total_elapsed}s).", "green"))
    append_run_log(f"run-finished elapsed={total_elapsed}s")
    _write_triage_run_summary(run_dir, stamp, stages_to_run, stage_results, append_run_log)


def _write_triage_run_summary(
    run_dir: Path,
    stamp: str,
    stages: list[str],
    stage_results: dict[str, dict],
    append_run_log,
) -> None:
    """Write a run_summary.json with per-stage results."""
    summary = {
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "run_stamp": stamp,
        "runner": "codex",
        "stages_requested": stages,
        "stage_results": stage_results,
        "run_dir": str(run_dir),
    }
    summary_path = run_dir / "run_summary.json"
    safe_write_text(summary_path, json.dumps(summary, indent=2) + "\n")
    print(colorize(f"  Run summary: {summary_path}", "dim"))
    append_run_log(f"run-summary {summary_path}")


__all__ = ["do_run_triage_stages"]
