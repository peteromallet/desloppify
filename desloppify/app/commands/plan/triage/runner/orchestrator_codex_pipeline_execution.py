"""Stage execution collaborators for the Codex triage pipeline."""

from __future__ import annotations

import argparse
import inspect
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan_triage import compute_triage_progress

from ..services import TriageServices
from ..validation.organize_policy import validate_organize_against_reflect_ledger
from ..validation.reflect_accounting import (
    analyze_reflect_issue_accounting,
    validate_reflect_accounting,
)
from .codex_runner import TriageStageRunResult, run_triage_stage
from .orchestrator_codex_observe import run_observe
from .orchestrator_codex_pipeline_context import StageRunContext
from .orchestrator_codex_sense import run_sense_check
from .stage_prompts import build_stage_prompt
from .stage_prompts_instruction_shared import PromptMode


def read_stage_output(output_file: Path) -> str:
    """Return stripped stage output text, or an empty string when unreadable."""
    try:
        return output_file.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


@dataclass(frozen=True)
class StageHandler:
    """Per-stage execution/record hooks for the codex triage pipeline."""

    run_parallel: Callable[[StageRunContext], TriageStageRunResult] | None = None
    record_report: Callable[[str, argparse.Namespace, TriageServices], None] | None = None
    prompt_mode: PromptMode = "output_only"


def _record_observe_report(
    report: str,
    args: argparse.Namespace,
    services: TriageServices,
) -> None:
    from ..stages.commands import cmd_stage_observe

    record_args = argparse.Namespace(
        stage="observe",
        report=report,
        state=getattr(args, "state", None),
    )
    cmd_stage_observe(record_args, services=services)


def _record_strategize_report(
    report: str,
    args: argparse.Namespace,
    services: TriageServices,
) -> None:
    from ..stages.commands import cmd_stage_strategize

    record_args = argparse.Namespace(
        stage="strategize",
        report=report,
        state=getattr(args, "state", None),
    )
    cmd_stage_strategize(record_args, services=services)


def _record_reflect_report(
    report: str,
    args: argparse.Namespace,
    services: TriageServices,
) -> None:
    from ..stages.commands import cmd_stage_reflect

    record_args = argparse.Namespace(
        stage="reflect",
        report=report,
        state=getattr(args, "state", None),
    )
    cmd_stage_reflect(record_args, services=services)


def _record_sense_check_report(
    report: str,
    args: argparse.Namespace,
    services: TriageServices,
) -> None:
    from ..stages.commands import cmd_stage_sense_check

    record_args = argparse.Namespace(
        stage="sense-check",
        report=report,
        state=getattr(args, "state", None),
        value_targets=getattr(args, "sense_check_value_targets", None),
    )
    cmd_stage_sense_check(record_args, services=services)


DEFAULT_STAGE_HANDLERS: dict[str, StageHandler] = {
    "strategize": StageHandler(
        record_report=_record_strategize_report,
        prompt_mode="output_only",
    ),
    "observe": StageHandler(
        run_parallel=lambda context: run_observe(
            si=context.triage_input,
            repo_root=context.repo_root,
            prompts_dir=context.prompts_dir,
            output_dir=context.output_dir,
            logs_dir=context.logs_dir,
            timeout_seconds=context.timeout_seconds,
            dry_run=context.dry_run,
            append_run_log=context.append_run_log,
            strategist_briefing=(
                context.plan.get("epic_triage_meta", {}).get("strategist_briefing", {})
                if isinstance(context.plan.get("epic_triage_meta", {}), dict)
                else {}
            ),
        ),
        record_report=_record_observe_report,
    ),
    "reflect": StageHandler(
        record_report=_record_reflect_report,
    ),
    "organize": StageHandler(
        prompt_mode="self_record",
    ),
    "enrich": StageHandler(
        prompt_mode="self_record",
    ),
    "sense-check": StageHandler(
        run_parallel=lambda context: run_sense_check(
            plan=dict(context.plan),
            repo_root=context.repo_root,
            prompts_dir=context.prompts_dir,
            output_dir=context.output_dir,
            logs_dir=context.logs_dir,
            timeout_seconds=context.timeout_seconds,
            dry_run=context.dry_run,
            cli_command=context.cli_command,
            apply_updates=True,
            reload_plan=context.services.load_plan,
            append_run_log=context.append_run_log,
            state=context.state,
        ),
        record_report=_record_sense_check_report,
    ),
}


@dataclass(frozen=True)
class StageExecutionDependencies:
    """Dependency container for stage execution to support focused patching in tests."""

    build_stage_prompt: Callable[..., str]
    run_triage_stage: Callable[..., TriageStageRunResult]
    read_stage_output: Callable[[Path], str]
    analyze_reflect_issue_accounting: Callable[..., tuple[set[str], list[str], list[str]]]
    validate_reflect_issue_accounting: Callable[
        ...,
        tuple[bool, set[str], list[str], list[str]],
    ]


@dataclass(frozen=True)
class StageExecutionResult:
    """Explicit outcome model for one stage-execution step."""

    status: str
    payload: dict[str, Any]
    used_parallel: bool = False
    output_file: Path | None = None
    elapsed_seconds: int | None = None


def default_stage_execution_dependencies() -> StageExecutionDependencies:
    """Construct the default stage execution dependency set."""
    return StageExecutionDependencies(
        build_stage_prompt=build_stage_prompt,
        run_triage_stage=run_triage_stage,
        read_stage_output=read_stage_output,
        analyze_reflect_issue_accounting=analyze_reflect_issue_accounting,
        validate_reflect_issue_accounting=validate_reflect_accounting,
    )


def stage_report_recorded(plan: Mapping[str, Any], stage: str) -> bool:
    """True when the plan contains a persisted report for the given stage."""
    return bool(
        plan.get("epic_triage_meta", {})
        .get("triage_stages", {})
        .get(stage, {})
        .get("report", "")
    )


def preflight_stage(
    *,
    stage: str,
    prompt_mode: PromptMode = "output_only",
    plan: Mapping[str, Any],
    triage_input: Any,
    dry_run: bool,
    append_run_log: Callable[[str], None],
    validate_reflect_issue_accounting: Callable[
        ...,
        tuple[bool, set[str], list[str], list[str]],
    ],
) -> tuple[bool, str | None]:
    """Fail fast when a requested stage has invalid upstream prerequisites."""
    # Dry-run previews do not persist upstream stage reports, so preflight checks that
    # require recorded reflect/enrich state would otherwise fail by construction.
    if dry_run and stage in {"organize", "sense-check"}:
        return True, None

    if stage == "sense-check":
        stages = plan.get("epic_triage_meta", {}).get("triage_stages", {})
        progress = compute_triage_progress(stages)
        if "sense-check" in stages or progress.current_stage == "sense-check":
            return True, None
        reason = "enrich_not_confirmed"
        append_run_log(f"stage-preflight-failed stage={stage} reason={reason}")
        return False, reason

    if stage != "organize":
        return True, None
    stages = plan.get("epic_triage_meta", {}).get("triage_stages", {})
    reflect_report = str(stages.get("reflect", {}).get("report", ""))
    accounting_ok, _cited, missing_ids, duplicate_ids = validate_reflect_issue_accounting(
        report=reflect_report,
        valid_ids=set(
            getattr(triage_input, "review_issues", getattr(triage_input, "open_issues", {})).keys()
        ),
    )
    if not accounting_ok:
        reason_parts: list[str] = []
        if missing_ids:
            reason_parts.append(f"missing={len(missing_ids)}")
        if duplicate_ids:
            reason_parts.append(f"duplicates={len(duplicate_ids)}")
        reason = "reflect_accounting_invalid"
        if reason_parts:
            reason = f"{reason}({' '.join(reason_parts)})"
        append_run_log(f"stage-preflight-failed stage={stage} reason={reason}")
        return False, reason

    # Self-record stages mutate plan state from within the subagent, so their
    # postconditions cannot be required before launch. The organize command
    # itself validates ledger/disposition alignment when it records the stage.
    if prompt_mode == "self_record":
        return True, None

    # Output-only organize paths may rely on pre-applied plan mutations.
    ledger_mismatches = validate_organize_against_reflect_ledger(
        plan=dict(plan), stages=stages,
    )
    if ledger_mismatches:
        mismatch_types = set()
        for m in ledger_mismatches:
            mismatch_types.add(m.expected_decision)
        reason = f"reflect_ledger_mismatch(count={len(ledger_mismatches)} types={','.join(sorted(mismatch_types))})"
        append_run_log(f"stage-preflight-failed stage={stage} reason={reason}")
        return False, reason

    return True, None


def build_reflect_repair_prompt(
    *,
    triage_input: Any,
    prior_reports: Mapping[str, str],
    repo_root: Path,
    cli_command: str,
    original_report: str,
    missing_ids: list[str],
    duplicate_ids: list[str],
    build_stage_prompt_fn: Callable[..., str],
    stages_data: Mapping[str, Any] | None = None,
) -> str:
    """Build a targeted retry prompt for a reflect report that failed accounting."""
    missing_short = ", ".join(issue_id.rsplit("::", 1)[-1] for issue_id in missing_ids) or "none"
    duplicate_short = (
        ", ".join(issue_id.rsplit("::", 1)[-1] for issue_id in duplicate_ids) or "none"
    )
    base_prompt = build_stage_prompt_fn(
        "reflect",
        triage_input,
        dict(prior_reports),
        repo_root=repo_root,
        mode="output_only",
        cli_command=cli_command,
        stages_data=stages_data,
    )
    return "\n\n".join(
        [
            base_prompt,
            "## Repair Pass",
            "Your previous reflect report failed the exact-hash accounting check.",
            f"Missing hashes: {missing_short}",
            f"Duplicated hashes: {duplicate_short}",
            "Rewrite the FULL reflect report so it passes validation.",
            "Requirements for this repair:",
            "- Start with a `## Coverage Ledger` section.",
            '- Use one ledger line per issue hash: `- abcd1234 -> cluster "name"` or `- abcd1234 -> skip "reason"`.',
            "- Mention every required hash exactly once in that ledger.",
            "- Do not mention hashes anywhere else in the report.",
            "- Preserve the same strategy unless fixing the missing/duplicate hashes forces a small adjustment.",
            "- Output only the corrected reflect report.",
            "## Previous Reflect Report",
            original_report,
        ]
    )


def repair_reflect_report_if_needed(
    *,
    report: str,
    triage_input: Any,
    prior_reports: Mapping[str, str],
    repo_root: Path,
    prompts_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    cli_command: str,
    timeout_seconds: int,
    append_run_log: Callable[[str], None],
    dependencies: StageExecutionDependencies,
    stages_data: Mapping[str, Any] | None = None,
) -> tuple[str | None, str | None]:
    """Retry reflect once with a targeted repair prompt when accounting is invalid."""
    _cited, missing_ids, duplicate_ids = dependencies.analyze_reflect_issue_accounting(
        report=report,
        valid_ids=set(
            getattr(triage_input, "review_issues", getattr(triage_input, "open_issues", {})).keys()
        ),
    )
    if not missing_ids and not duplicate_ids:
        return report, None

    print(colorize("  Reflect: repairing missing/duplicate hash accounting...", "yellow"))
    append_run_log(
        "stage-reflect-repair-start "
        f"missing={len(missing_ids)} duplicates={len(duplicate_ids)}"
    )

    repair_prompt = build_reflect_repair_prompt(
        triage_input=triage_input,
        prior_reports=prior_reports,
        repo_root=repo_root,
        cli_command=cli_command,
        original_report=report,
        missing_ids=missing_ids,
        duplicate_ids=duplicate_ids,
        build_stage_prompt_fn=dependencies.build_stage_prompt,
        stages_data=stages_data,
    )
    repair_prompt_file = prompts_dir / "reflect.repair.md"
    repair_output_file = output_dir / "reflect.repair.raw.txt"
    repair_log_file = logs_dir / "reflect.repair.log"
    safe_write_text(repair_prompt_file, repair_prompt)
    stage_result = dependencies.run_triage_stage(
        prompt=repair_prompt,
        repo_root=repo_root,
        output_file=repair_output_file,
        log_file=repair_log_file,
        timeout_seconds=timeout_seconds,
    )
    append_run_log(f"stage-reflect-repair-done code={stage_result.exit_code}")
    if not stage_result.ok:
        return None, f"reflect_repair_failed_exit_{stage_result.exit_code}"

    repaired_report = dependencies.read_stage_output(repair_output_file)
    if not repaired_report:
        return None, "reflect_repair_empty_output"

    _cited, missing_after, duplicates_after = dependencies.analyze_reflect_issue_accounting(
        report=repaired_report,
        valid_ids=set(
            getattr(triage_input, "review_issues", getattr(triage_input, "open_issues", {})).keys()
        ),
    )
    if missing_after or duplicates_after:
        return None, "reflect_repair_invalid"

    print(colorize("  Reflect: repair pass fixed issue accounting.", "green"))
    append_run_log("stage-reflect-repair-success")
    return repaired_report, None


def _execute_parallel_stage(
    *,
    context: StageRunContext,
    stage: str,
    handler: StageHandler | None,
) -> StageExecutionResult:
    """Execute optional parallel stage path."""
    if handler is None or handler.run_parallel is None:
        return StageExecutionResult(status="ready", payload={})

    parallel_result = handler.run_parallel(context)
    if parallel_result.status == "dry_run":
        return StageExecutionResult(
            status="dry_run",
            payload={"status": "dry_run"},
            used_parallel=True,
        )

    if parallel_result.ok and parallel_result.merged_output:
        if handler.record_report is not None:
            handler.record_report(parallel_result.merged_output, context.args, context.services)
            return StageExecutionResult(status="ready", payload={}, used_parallel=True)
        return StageExecutionResult(status="ready", payload={})

    if parallel_result.ok:
        return StageExecutionResult(status="ready", payload={})

    elapsed = int(time.monotonic() - context.stage_start)
    error_reason = parallel_result.reason or "parallel_execution_failed"
    print(colorize(f"  {stage.capitalize()}: parallel execution failed. Aborting.", "red"))
    context.append_run_log(
        f"stage-failed stage={stage} elapsed={elapsed}s reason={error_reason}"
    )
    return StageExecutionResult(
        status="failed",
        payload={
            "status": "failed",
            "elapsed_seconds": elapsed,
            "error": error_reason,
        },
        used_parallel=True,
        elapsed_seconds=elapsed,
    )


def _failure_result(
    *,
    stage: str,
    elapsed: int | None,
    error: str,
    append_run_log: Callable[[str], None] | None = None,
    log_event: str = "stage-failed",
    log_reason: str | None = None,
    printed_message: str | None = None,
) -> StageExecutionResult:
    if printed_message is not None:
        print(colorize(printed_message, "red"))
    if append_run_log is not None:
        log_parts = [f"{log_event} stage={stage}"]
        if elapsed is not None:
            log_parts.append(f"elapsed={elapsed}s")
        log_parts.append(f"reason={log_reason or error}")
        append_run_log(" ".join(log_parts))
    payload: dict[str, Any] = {
        "status": "failed",
        "error": error,
    }
    if elapsed is not None:
        payload["elapsed_seconds"] = elapsed
    return StageExecutionResult(
        status="failed",
        payload=payload,
        elapsed_seconds=elapsed,
    )


def _build_subprocess_prompt(
    *,
    context: StageRunContext,
    stage: str,
    prompt_mode: PromptMode,
    dependencies: StageExecutionDependencies,
) -> tuple[str, Mapping[str, Any]]:
    """Build and persist one stage prompt for subprocess execution."""
    stages_data = context.plan.get("epic_triage_meta", {}).get("triage_stages", {})
    build_kwargs = {
        "repo_root": context.repo_root,
        "mode": prompt_mode,
        "cli_command": context.cli_command,
        "stages_data": stages_data,
    }
    try:
        signature = inspect.signature(dependencies.build_stage_prompt)
    except (TypeError, ValueError):
        signature = None
    if signature is None or "plan" in signature.parameters:
        build_kwargs["plan"] = context.plan
    if signature is None or "state" in signature.parameters:
        build_kwargs["state"] = context.state
    prompt = dependencies.build_stage_prompt(
        stage,
        context.triage_input,
        dict(context.prior_reports),
        **build_kwargs,
    )
    prompt_file = context.prompts_dir / f"{stage}.md"
    safe_write_text(prompt_file, prompt)
    return prompt, stages_data


def _run_subprocess_stage(
    *,
    context: StageRunContext,
    stage: str,
    prompt: str,
    dependencies: StageExecutionDependencies,
) -> StageExecutionResult:
    """Run codex subprocess for one stage (or emit dry-run status)."""
    prompt_file = context.prompts_dir / f"{stage}.md"
    if context.dry_run:
        print(colorize(f"  Stage {stage}: prompt written to {prompt_file}", "cyan"))
        print(colorize("  [dry-run] Would execute codex subprocess.", "dim"))
        return StageExecutionResult(
            status="dry_run",
            payload={"status": "dry_run"},
        )

    print(colorize(f"\n  Stage {stage}: launching codex subprocess...", "bold"))
    context.append_run_log(f"stage-subprocess-start stage={stage}")

    output_file = context.output_dir / f"{stage}.raw.txt"
    log_file = context.logs_dir / f"{stage}.log"
    stage_result = dependencies.run_triage_stage(
        prompt=prompt,
        repo_root=context.repo_root,
        output_file=output_file,
        log_file=log_file,
        timeout_seconds=context.timeout_seconds,
    )

    elapsed = int(time.monotonic() - context.stage_start)
    context.append_run_log(
        "stage-subprocess-done "
        f"stage={stage} code={stage_result.exit_code} elapsed={elapsed}s"
    )

    if stage_result.ok:
        return StageExecutionResult(
            status="ready",
            payload={},
            output_file=output_file,
            elapsed_seconds=elapsed,
        )

    print(
        colorize(
            "  Stage "
            f"{stage}: codex subprocess failed (exit {stage_result.exit_code}).",
            "red",
        )
    )
    print(colorize(f"  Check log: {log_file}", "dim"))
    print(colorize("  Re-run to resume (confirmed stages are skipped).", "dim"))
    context.append_run_log(
        "stage-failed "
        f"stage={stage} elapsed={elapsed}s code={stage_result.exit_code}"
    )
    return StageExecutionResult(
        status="failed",
        payload={
            "status": "failed",
            "exit_code": stage_result.exit_code,
            "elapsed_seconds": elapsed,
        },
        elapsed_seconds=elapsed,
    )


def _resolve_subprocess_artifacts(
    subprocess_result: StageExecutionResult,
) -> tuple[Path, int] | None:
    output_file = subprocess_result.output_file
    elapsed = subprocess_result.elapsed_seconds
    if output_file is None or elapsed is None:
        return None
    return output_file, elapsed


def _record_stage_report_if_needed(
    *,
    context: StageRunContext,
    stage: str,
    handler: StageHandler | None,
    dependencies: StageExecutionDependencies,
    output_file: Path,
    elapsed: int,
    stages_data: Mapping[str, Any],
) -> StageExecutionResult:
    """Record subprocess output for stages that require orchestrator persistence."""
    if handler is None or handler.record_report is None:
        return StageExecutionResult(status="ready", payload={})

    report = dependencies.read_stage_output(output_file)
    if not report:
        return _failure_result(
            stage=stage,
            elapsed=elapsed,
            error="empty_stage_output",
            append_run_log=context.append_run_log,
            printed_message=f"  Stage {stage}: output file was empty after subprocess.",
        )

    if stage == "reflect":
        report, repair_error = repair_reflect_report_if_needed(
            report=report,
            triage_input=context.triage_input,
            prior_reports=context.prior_reports,
            repo_root=context.repo_root,
            prompts_dir=context.prompts_dir,
            output_dir=context.output_dir,
            logs_dir=context.logs_dir,
            cli_command=context.cli_command,
            timeout_seconds=context.timeout_seconds,
            append_run_log=context.append_run_log,
            dependencies=dependencies,
            stages_data=stages_data,
        )
        if repair_error:
            return _failure_result(
                stage=stage,
                elapsed=elapsed,
                error=repair_error,
                append_run_log=context.append_run_log,
                printed_message=f"  Stage {stage}: repair failed ({repair_error}).",
            )
        if not report:
            return _failure_result(
                stage=stage,
                elapsed=elapsed,
                error="reflect_repair_no_report",
                append_run_log=context.append_run_log,
            )

    handler.record_report(report, context.args, context.services)
    plan_after_record = context.services.load_plan()
    if not stage_report_recorded(plan_after_record, stage):
        return _failure_result(
            stage=stage,
            elapsed=elapsed,
            error="stage_not_recorded",
            append_run_log=context.append_run_log,
            log_event="stage-record-failed",
            printed_message=f"  Stage {stage}: handler completed but did not persist the stage.",
        )
    context.append_run_log(
        f"stage-recorded stage={stage} elapsed={elapsed}s mode=orchestrator"
    )
    return StageExecutionResult(status="ready", payload={})


def _run_stage_subprocess_path(
    *,
    context: StageRunContext,
    stage: str,
    handler: StageHandler | None,
    prompt_mode: PromptMode,
    dependencies: StageExecutionDependencies,
) -> StageExecutionResult:
    prompt, stages_data = _build_subprocess_prompt(
        context=context,
        stage=stage,
        prompt_mode=prompt_mode,
        dependencies=dependencies,
    )
    subprocess_result = _run_subprocess_stage(
        context=context,
        stage=stage,
        prompt=prompt,
        dependencies=dependencies,
    )
    if subprocess_result.status != "ready":
        return subprocess_result

    subprocess_artifacts = _resolve_subprocess_artifacts(subprocess_result)
    if subprocess_artifacts is None:
        return _failure_result(
            stage=stage,
            elapsed=None,
            error="subprocess_output_missing",
        )
    output_file, elapsed = subprocess_artifacts

    return _record_stage_report_if_needed(
        context=context,
        stage=stage,
        handler=handler,
        dependencies=dependencies,
        output_file=output_file,
        elapsed=elapsed,
        stages_data=stages_data,
    )


def execute_stage(
    context: StageRunContext,
    *,
    handlers: Mapping[str, StageHandler],
    dependencies: StageExecutionDependencies,
) -> StageExecutionResult:
    """Execute one stage and return an explicit stage outcome."""
    stage = context.stage
    handler = handlers.get(stage)
    prompt_mode = handler.prompt_mode if handler is not None else "output_only"

    preflight_ok, preflight_reason = preflight_stage(
        stage=stage,
        prompt_mode=prompt_mode,
        plan=context.plan,
        triage_input=context.triage_input,
        dry_run=context.dry_run,
        append_run_log=context.append_run_log,
        validate_reflect_issue_accounting=dependencies.validate_reflect_issue_accounting,
    )
    if not preflight_ok:
        elapsed = int(time.monotonic() - context.stage_start)
        return _failure_result(
            stage=stage,
            elapsed=elapsed,
            error=preflight_reason or "stage_preflight_failed",
            printed_message=f"  Stage {stage}: blocked before launch ({preflight_reason}).",
        )

    parallel_result = _execute_parallel_stage(
        context=context,
        stage=stage,
        handler=handler,
    )
    if parallel_result.status != "ready":
        return parallel_result
    if parallel_result.used_parallel:
        return StageExecutionResult(status="ready", payload={})
    return _run_stage_subprocess_path(
        context=context,
        stage=stage,
        handler=handler,
        prompt_mode=prompt_mode,
        dependencies=dependencies,
    )


__all__ = [
    "DEFAULT_STAGE_HANDLERS",
    "StageExecutionResult",
    "StageExecutionDependencies",
    "StageHandler",
    "build_reflect_repair_prompt",
    "default_stage_execution_dependencies",
    "execute_stage",
    "preflight_stage",
    "read_stage_output",
    "repair_reflect_report_if_needed",
    "stage_report_recorded",
]
