"""Observe-stage parallel codex execution helpers."""

from __future__ import annotations

from collections.abc import Callable
from functools import partial
from pathlib import Path

from desloppify.app.commands.review.runner_parallel import BatchProgressEvent
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.output.terminal import colorize

from ..observe_batches import group_issues_into_observe_batches
from .codex_runner import (
    TriageStageRunResult,
    _output_file_has_text,
    run_triage_stage,
)
from .orchestrator_codex_parallel import run_parallel_batches
from .stage_prompts import build_observe_batch_prompt


def _noop_log(_msg: str) -> None:
    """Default run-log sink when the caller doesn't provide one."""


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


def _strategist_guidance_for_batch(
    strategist_briefing: dict | None,
    dimension_group: list[str],
) -> str | None:
    if not isinstance(strategist_briefing, dict):
        return None
    parts: list[str] = []
    guidance = str(strategist_briefing.get("observe_guidance", "")).strip()
    if guidance:
        parts.append(guidance)
    dims = {dim.lower() for dim in dimension_group}
    for warning in strategist_briefing.get("rework_warnings", []) or []:
        if not isinstance(warning, dict):
            continue
        dimension = str(warning.get("dimension", "")).strip()
        if dimension.lower() not in dims:
            continue
        parts.append(
            f"Rework warning for {dimension}: "
            f"{warning.get('resolved', warning.get('resolved_count', 0))} resolved, "
            f"{warning.get('new_open', warning.get('new_open_count', 0))} new open."
        )
    return "\n".join(parts) if parts else None


def run_observe(
    *,
    si,
    repo_root: Path,
    prompts_dir: Path,
    output_dir: Path,
    logs_dir: Path,
    timeout_seconds: int,
    dry_run: bool = False,
    append_run_log=None,
    strategist_briefing: dict | None = None,
) -> TriageStageRunResult:
    """Run observe stage via codex subprocess batches."""
    _log = append_run_log or _noop_log

    batches = group_issues_into_observe_batches(si)
    total = len(batches)
    print(colorize(f"\n  Observe: splitting into {total} parallel batches.", "bold"))
    _log(f"observe-parallel batches={total}")

    tasks: dict[int, Callable[[], TriageStageRunResult]] = {}
    batch_meta: list[tuple[list[str], Path]] = []

    for i, (dims, issues_subset) in enumerate(batches):
        prompt = build_observe_batch_prompt(
            batch_index=i + 1,
            total_batches=total,
            dimension_group=dims,
            issues_subset=issues_subset,
            repo_root=repo_root,
            strategist_guidance=_strategist_guidance_for_batch(strategist_briefing, dims),
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
        return TriageStageRunResult(exit_code=0, reason="dry_run", dry_run=True)

    def _heartbeat(event: BatchProgressEvent) -> None:
        details = event.details or {}
        active = details.get("active_batches", [])
        elapsed_map = details.get("elapsed_seconds", {})
        if active:
            parts = [f"#{i + 1}:{int(elapsed_map.get(i, 0))}s" for i in active[:6]]
            print(colorize(f"    Observe heartbeat: {len(active)}/{total} active ({', '.join(parts)})", "dim"))

    def _batch_label(idx: int) -> str:
        return f"batch {idx + 1}/{total}"

    failures = run_parallel_batches(
        tasks=tasks,
        stage_label="Observe",
        batch_label_fn=_batch_label,
        append_run_log=_log,
        heartbeat_seconds=15.0,
        heartbeat_printer=_heartbeat,
    )

    if failures:
        print(colorize(f"  Observe: {len(failures)} batch(es) failed: {failures}", "red"))
        for idx in failures:
            log_file = logs_dir / f"observe_batch_{idx}.log"
            print(colorize(f"    Check log: {log_file}", "dim"))
        _log(f"observe-parallel-failed failures={failures}")
        return TriageStageRunResult(
            exit_code=1,
            reason="parallel_execution_failed",
        )

    merged = _merge_observe_outputs(batch_meta)
    print(colorize(f"  Observe: merged {total} batch outputs ({len(merged)} chars).", "green"))
    _log(f"observe-parallel-done merged_chars={len(merged)}")
    return TriageStageRunResult(
        exit_code=0,
        merged_output=merged,
    )


__all__ = ["run_observe"]
