"""Sense-check parallel codex execution helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from pathlib import Path

from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan_state import (
    load_policy_result,
    render_policy_block,
)

from ..stages.helpers import scoped_manual_clusters_with_issues, triage_scoped_plan
from .codex_runner import (
    TriageStageRunResult,
    _output_file_has_text,
    run_triage_stage,
)
from .orchestrator_codex_parallel import run_parallel_batches
from .stage_prompts import (
    build_sense_check_content_prompt,
    build_sense_check_structure_prompt,
)
from .stage_prompts_sense import build_sense_check_value_prompt


def _noop_log(_msg: str) -> None:
    """Default run-log sink when the caller doesn't provide one."""


@dataclass(frozen=True)
class SenseBatchConfig:
    label: str
    prompt_file: Path
    output_file: Path
    log_file: Path
    prompt: str


def _print_sense_header(total_content: int, *, apply_updates: bool, log: Callable[[str], None]) -> None:
    if apply_updates:
        print(
            colorize(
                f"\n  Sense-check: {total_content} content batches, then 1 structure batch, then 1 value batch.",
                "bold",
            )
        )
        log(f"sense-check-sequenced content_batches={total_content} apply_updates=1")
        return
    print(colorize(f"\n  Sense-check: {total_content} content batches + 1 structure batch + 1 value batch.", "bold"))
    log(f"sense-check-parallel content_batches={total_content}")


def _sense_modes(*, apply_updates: bool) -> tuple[str, str]:
    mode = "self_record" if apply_updates else "output_only"
    return mode, mode


def _content_batch_config(
    *,
    cluster_name: str,
    batch_index: int,
    plan: dict,
    repo_root: Path,
    prompts_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    policy_text: str,
    mode: str,
    cli_command: str,
) -> SenseBatchConfig:
    prompt = build_sense_check_content_prompt(
        cluster_name=cluster_name,
        plan=plan,
        repo_root=repo_root,
        policy_block=policy_text,
        mode=mode,
        cli_command=cli_command,
    )
    return SenseBatchConfig(
        label=f"content:{cluster_name}",
        prompt_file=prompts_dir / f"sense_check_content_{batch_index}.md",
        output_file=output_dir / f"sense_check_content_{batch_index}.raw.txt",
        log_file=logs_dir / f"sense_check_content_{batch_index}.log",
        prompt=prompt,
    )


def _structure_batch_config(
    *,
    plan: dict,
    repo_root: Path,
    prompts_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    mode: str,
    cli_command: str,
) -> SenseBatchConfig:
    prompt = build_sense_check_structure_prompt(
        plan=dict(plan),
        repo_root=repo_root,
        mode=mode,
        cli_command=cli_command,
    )
    return SenseBatchConfig(
        label="structure",
        prompt_file=prompts_dir / "sense_check_structure.md",
        output_file=output_dir / "sense_check_structure.raw.txt",
        log_file=logs_dir / "sense_check_structure.log",
        prompt=prompt,
    )


def _write_batch_prompt(config: SenseBatchConfig) -> None:
    safe_write_text(config.prompt_file, config.prompt)


def _content_tasks_and_meta(
    *,
    clusters: list[str],
    plan: dict,
    repo_root: Path,
    prompts_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    timeout_seconds: int,
    dry_run: bool,
    policy_text: str,
    content_mode: str,
    cli_command: str,
    log: Callable[[str], None],
) -> tuple[dict[int, Callable[[], TriageStageRunResult]], list[tuple[str, Path]]]:
    tasks: dict[int, Callable[[], TriageStageRunResult]] = {}
    batch_meta: list[tuple[str, Path]] = []
    for i, cluster_name in enumerate(clusters):
        config = _content_batch_config(
            cluster_name=cluster_name,
            batch_index=i,
            plan=plan,
            repo_root=repo_root,
            prompts_dir=prompts_dir,
            output_dir=output_dir,
            logs_dir=logs_dir,
            policy_text=policy_text,
            mode=content_mode,
            cli_command=cli_command,
        )
        _write_batch_prompt(config)
        batch_meta.append((config.label, config.output_file))
        if not dry_run:
            tasks[i] = partial(
                run_triage_stage,
                prompt=config.prompt,
                repo_root=repo_root,
                output_file=config.output_file,
                log_file=config.log_file,
                timeout_seconds=timeout_seconds,
                validate_output_fn=_output_file_has_text,
            )
        print(colorize(f"    Content batch {i + 1}: {cluster_name}", "dim"))
        log(f"sense-check-content batch={i + 1} cluster={cluster_name}")
    return tasks, batch_meta


def _run_parallel_or_fail(
    *,
    tasks: dict[int, Callable[[], TriageStageRunResult]],
    stage_label: str,
    batch_label_fn: Callable[[int], str],
    log: Callable[[str], None],
) -> list[int]:
    return run_parallel_batches(
        tasks=tasks,
        stage_label=stage_label,
        batch_label_fn=batch_label_fn,
        append_run_log=log,
        heartbeat_seconds=15.0,
    )


def _content_failures(
    *,
    tasks: dict[int, Callable[[], TriageStageRunResult]],
    clusters: list[str],
    log: Callable[[str], None],
) -> list[int]:
    def _content_label(idx: int) -> str:
        if idx < len(clusters):
            return f"content:{clusters[idx]}"
        return f"content:{idx}"

    return _run_parallel_or_fail(
        tasks=tasks,
        stage_label="Sense-check",
        batch_label_fn=_content_label,
        log=log,
    )


def _parallel_failure_result(
    failures: list[int],
    *,
    log: Callable[[str], None],
) -> TriageStageRunResult:
    print(colorize(f"  Sense-check: {len(failures)} batch(es) failed: {failures}", "red"))
    log(f"sense-check-parallel-failed failures={failures}")
    return TriageStageRunResult(
        exit_code=1,
        reason="parallel_execution_failed",
    )


def _reload_structure_plan(
    *,
    reload_plan: Callable[[], dict] | None,
    log: Callable[[str], None],
) -> dict | None:
    if reload_plan is None:
        return None
    try:
        reloaded = dict(reload_plan())
        log("sense-check-plan-reloaded phase=structure")
        return reloaded
    except PLAN_LOAD_EXCEPTIONS as exc:  # pragma: no cover - defensive fallback
        print(colorize("  Sense-check: failed to reload plan after content updates.", "red"))
        log(f"sense-check-plan-reload-failed error={exc}")
        return None


def _merge_batch_outputs(batch_meta: list[tuple[str, Path]]) -> str:
    parts: list[str] = []
    for label, output_file in batch_meta:
        content = ""
        if output_file.exists():
            try:
                content = output_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError:
                content = "(output missing)"
        if not content:
            content = "(no output)"
        parts.append(f"## {label}\n\n{content}")
    return "\n\n---\n\n".join(parts)


def _value_batch_config(
    *,
    plan: dict,
    state: dict | None,
    repo_root: Path,
    prompts_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    mode: str,
    cli_command: str,
) -> SenseBatchConfig:
    prompt = build_sense_check_value_prompt(
        plan=dict(plan),
        state=state,
        repo_root=repo_root,
        strategist_briefing=(
            plan.get("epic_triage_meta", {}).get("strategist_briefing", {})
            if isinstance(plan.get("epic_triage_meta", {}), dict)
            else {}
        ),
        mode=mode,
        cli_command=cli_command,
    )
    return SenseBatchConfig(
        label="value",
        prompt_file=prompts_dir / "sense_check_value.md",
        output_file=output_dir / "sense_check_value.raw.txt",
        log_file=logs_dir / "sense_check_value.log",
        prompt=prompt,
    )


def run_sense_check(
    *,
    plan: dict,
    repo_root: Path,
    prompts_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    timeout_seconds: int,
    dry_run: bool = False,
    cli_command: str = "desloppify",
    apply_updates: bool = False,
    reload_plan: Callable[[], dict] | None = None,
    append_run_log=None,
    state: dict | None = None,
) -> TriageStageRunResult:
    """Run sense-check via parallel codex subprocess batches (content → structure → value)."""
    _log = append_run_log or _noop_log

    scoped_plan = triage_scoped_plan(plan, state)
    clusters = scoped_manual_clusters_with_issues(plan, state)
    total_content = len(clusters)
    total = total_content + 2  # +1 structure +1 value
    _print_sense_header(total_content, apply_updates=apply_updates, log=_log)

    policy_result = load_policy_result()
    policy_text = render_policy_block(policy_result.policy)
    if not policy_result.ok:
        print(
            colorize(
                f"  Warning: ignoring malformed project policy ({policy_result.message or 'unknown error'}).",
                "yellow",
            )
        )
    content_mode, structure_mode = _sense_modes(apply_updates=apply_updates)
    content_tasks, batch_meta = _content_tasks_and_meta(
        clusters=clusters,
        plan=scoped_plan,
        repo_root=repo_root,
        prompts_dir=prompts_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        timeout_seconds=timeout_seconds,
        dry_run=dry_run,
        policy_text=policy_text,
        content_mode=content_mode,
        cli_command=cli_command,
        log=_log,
    )
    structure_plan = dict(scoped_plan)
    structure_config = _structure_batch_config(
        plan=structure_plan,
        repo_root=repo_root,
        prompts_dir=prompts_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        mode=structure_mode,
        cli_command=cli_command,
    )
    _write_batch_prompt(structure_config)
    batch_meta.append((structure_config.label, structure_config.output_file))
    print(colorize("    Structure batch: global dependency check", "dim"))
    _log("sense-check-structure batch=global")

    if dry_run:
        if apply_updates:
            print(colorize("  [dry-run] Would execute sequenced sense-check batches.", "dim"))
        else:
            print(colorize("  [dry-run] Would execute parallel sense-check batches.", "dim"))
        return TriageStageRunResult(exit_code=0, reason="dry_run", dry_run=True)

    if content_tasks:
        content_failures = _content_failures(tasks=content_tasks, clusters=clusters, log=_log)
        if content_failures:
            return _parallel_failure_result(content_failures, log=_log)

    if apply_updates and reload_plan is not None:
        reloaded_plan = _reload_structure_plan(reload_plan=reload_plan, log=_log)
        if reloaded_plan is None:
            return TriageStageRunResult(exit_code=1, reason="plan_reload_failed")
        structure_plan = reloaded_plan
        structure_config = _structure_batch_config(
            plan=structure_plan,
            repo_root=repo_root,
            prompts_dir=prompts_dir,
            output_dir=output_dir,
            logs_dir=logs_dir,
            mode=structure_mode,
            cli_command=cli_command,
        )
        _write_batch_prompt(structure_config)

    structure_tasks: dict[int, Callable[[], TriageStageRunResult]] = {
        0: partial(
            run_triage_stage,
            prompt=structure_config.prompt,
            repo_root=repo_root,
            output_file=structure_config.output_file,
            log_file=structure_config.log_file,
            timeout_seconds=timeout_seconds,
            validate_output_fn=_output_file_has_text,
        )
    }
    structure_failures = _run_parallel_or_fail(
        tasks=structure_tasks,
        stage_label="Sense-check",
        batch_label_fn=lambda _idx: "structure",
        log=_log,
    )
    if structure_failures:
        return _parallel_failure_result(structure_failures, log=_log)

    # Value batch — runs after structure (needs corrected plan state)
    value_plan = dict(plan)
    if apply_updates and reload_plan is not None:
        reloaded = _reload_structure_plan(reload_plan=reload_plan, log=_log)
        if reloaded is not None:
            value_plan = reloaded
            _log("sense-check-plan-reloaded phase=value")

    value_mode = "self_record" if apply_updates else "output_only"
    value_config = _value_batch_config(
        plan=value_plan,
        state=state,
        repo_root=repo_root,
        prompts_dir=prompts_dir,
        output_dir=output_dir,
        logs_dir=logs_dir,
        mode=value_mode,
        cli_command=cli_command,
    )
    _write_batch_prompt(value_config)
    batch_meta.append((value_config.label, value_config.output_file))
    print(colorize("    Value batch: YAGNI/KISS pass", "dim"))
    _log("sense-check-value batch=global")

    if not dry_run:
        value_tasks: dict[int, Callable[[], TriageStageRunResult]] = {
            0: partial(
                run_triage_stage,
                prompt=value_config.prompt,
                repo_root=repo_root,
                output_file=value_config.output_file,
                log_file=value_config.log_file,
                timeout_seconds=timeout_seconds,
                validate_output_fn=_output_file_has_text,
            )
        }
        value_failures = _run_parallel_or_fail(
            tasks=value_tasks,
            stage_label="Sense-check",
            batch_label_fn=lambda _idx: "value",
            log=_log,
        )
        if value_failures:
            return _parallel_failure_result(value_failures, log=_log)

    merged = _merge_batch_outputs(batch_meta)
    print(colorize(f"  Sense-check: merged {total} batch outputs ({len(merged)} chars).", "green"))
    _log(f"sense-check-parallel-done merged_chars={len(merged)}")
    return TriageStageRunResult(
        exit_code=0,
        merged_output=merged,
    )


__all__ = ["run_sense_check"]
