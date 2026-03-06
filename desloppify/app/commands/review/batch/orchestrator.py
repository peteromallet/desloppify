"""Batch runner helpers and orchestration for review command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import cast

from desloppify.app.commands.helpers.query import write_query_best_effort
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.exception_sets import CommandError, PacketValidationError
from desloppify.base.output.terminal import colorize, log
from desloppify.intelligence import review as review_mod
from desloppify.intelligence.review.feedback_contract import (
    max_batch_issues_for_dimension_count,
)

from ..coordinator import build_review_packet_payload, write_review_packet_snapshot
from ..importing.cmd import do_import as _do_import
from ..packet.build import (
    build_run_batches_next_command,
    resolve_review_packet_context,
)
from ..runner_failures import print_failures, print_failures_and_raise
from ..runner_packets import (
    build_batch_import_provenance,
    build_blind_packet,
    prepare_run_artifacts,
    run_stamp,
    selected_batch_indexes,
)
from ..runner_parallel import collect_batch_results, execute_batches
from ..runner_process import (
    CodexBatchRunnerDeps,
    FollowupScanDeps,
    run_codex_batch,
    run_followup_scan,
)
from ..runtime.setup import setup_lang_concrete as _setup_lang
from ..runtime_paths import (
    blind_packet_path as _blind_packet_path,
)
from ..runtime_paths import (
    runtime_project_root as _runtime_project_root,
)
from ..runtime_paths import (
    subagent_runs_dir as _subagent_runs_dir,
)
from . import core as batch_core_mod
from . import execution as review_batches_mod

FOLLOWUP_SCAN_TIMEOUT_SECONDS = 45 * 60
ABSTRACTION_SUB_AXES = (
    "abstraction_leverage",
    "indirection_cost",
    "interface_honesty",
    "delegation_density",
    "definition_directness",
    "type_discipline",
)
ABSTRACTION_COMPONENT_NAMES = {
    "abstraction_leverage": "Abstraction Leverage",
    "indirection_cost": "Indirection Cost",
    "interface_honesty": "Interface Honesty",
    "delegation_density": "Delegation Density",
    "definition_directness": "Definition Directness",
    "type_discipline": "Type Discipline",
}



def _merge_batch_results(batch_results: list[object]) -> dict[str, object]:
    """Deterministically merge assessments/issues across batch outputs."""
    normalized_results: list[batch_core_mod.BatchResultPayload] = []
    for result in batch_results:
        if hasattr(result, "to_dict") and callable(result.to_dict):
            payload = result.to_dict()
            if isinstance(payload, dict):
                normalized_results.append(cast(batch_core_mod.BatchResultPayload, payload))
                continue
        if isinstance(result, dict):
            normalized_results.append(cast(batch_core_mod.BatchResultPayload, result))
    return batch_core_mod.merge_batch_results(
        normalized_results,
        abstraction_sub_axes=ABSTRACTION_SUB_AXES,
        abstraction_component_names=ABSTRACTION_COMPONENT_NAMES,
    )


def _load_or_prepare_packet(
    args,
    *,
    state: dict,
    lang,
    config: dict,
    stamp: str,
) -> tuple[dict, Path, Path]:
    """Load packet override or prepare a fresh packet snapshot."""
    packet_override = getattr(args, "packet", None)
    if packet_override:
        packet_path = Path(packet_override)
        if not packet_path.exists():
            raise PacketValidationError(f"packet not found: {packet_override}", exit_code=1)
        try:
            packet = json.loads(packet_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise PacketValidationError(f"reading packet: {exc}", exit_code=1) from exc
        blind_path = _blind_packet_path()
        blind_packet = build_blind_packet(packet)
        safe_write_text(blind_path, json.dumps(blind_packet, indent=2) + "\n")
        print(colorize(f"  Immutable packet: {packet_path}", "dim"))
        print(colorize(f"  Blind packet: {blind_path}", "dim"))
        return packet, packet_path, blind_path

    context = resolve_review_packet_context(args)
    next_command = build_run_batches_next_command(context)
    try:
        packet = build_review_packet_payload(
            state=state,
            lang=lang,
            config=config,
            context=context,
            next_command=next_command,
            setup_lang_fn=_setup_lang,
            prepare_holistic_review_fn=review_mod.prepare_holistic_review,
        )
    except ValueError as exc:
        raise PacketValidationError(str(exc), exit_code=1) from exc
    write_query_best_effort(
        packet,
        context="review packet query update",
    )
    packet_path, blind_saved = write_review_packet_snapshot(
        packet,
        stamp=stamp,
        blind_path_override=_blind_packet_path(),
        safe_write_text_fn=safe_write_text,
    )
    print(colorize(f"  Immutable packet: {packet_path}", "dim"))
    print(colorize(f"  Blind packet: {blind_saved}", "dim"))
    return packet, packet_path, blind_saved


def do_run_batches(args, state, lang, state_file, config: dict | None = None) -> None:
    """Run holistic investigation batches with a local subagent runner."""
    from ..runtime.policy import resolve_batch_run_policy

    runtime_project_root = _runtime_project_root()
    policy = resolve_batch_run_policy(args)
    batch_timeout_seconds = policy.batch_timeout_seconds
    batch_max_retries = policy.batch_max_retries
    batch_retry_backoff_seconds = policy.batch_retry_backoff_seconds
    batch_heartbeat_seconds = policy.heartbeat_seconds
    batch_live_log_interval_seconds = (
        max(1.0, min(batch_heartbeat_seconds, 10.0))
        if batch_heartbeat_seconds > 0
        else 5.0
    )
    batch_stall_kill_seconds = policy.stall_kill_seconds

    def _prepare_run_artifacts(*, stamp, selected_indexes, batches, packet_path, run_root, repo_root):
        return prepare_run_artifacts(
            stamp=stamp,
            selected_indexes=selected_indexes,
            batches=batches,
            packet_path=packet_path,
            run_root=run_root,
            repo_root=repo_root,
            build_prompt_fn=batch_core_mod.build_batch_prompt,
            safe_write_text_fn=safe_write_text,
            colorize_fn=colorize,
        )

    def _collect_batch_results(*, selected_indexes, failures, output_files, allowed_dims):
        return collect_batch_results(
            selected_indexes=selected_indexes,
            failures=failures,
            output_files=output_files,
            allowed_dims=allowed_dims,
            extract_payload_fn=lambda raw: batch_core_mod.extract_json_payload(raw, log_fn=log),
            normalize_result_fn=lambda payload, dims: batch_core_mod.normalize_batch_result(
                payload,
                dims,
                max_batch_issues=max_batch_issues_for_dimension_count(
                    len(dims)
                ),
                abstraction_sub_axes=ABSTRACTION_SUB_AXES,
            ),
        )

    return review_batches_mod.do_run_batches(
        args,
        state,
        lang,
        state_file,
        config=config,
        run_stamp_fn=run_stamp,
        load_or_prepare_packet_fn=_load_or_prepare_packet,
        selected_batch_indexes_fn=lambda args, *, batch_count: selected_batch_indexes(
            raw_selection=getattr(args, "only_batches", None),
            batch_count=batch_count,
            parse_fn=batch_core_mod.parse_batch_selection,
            colorize_fn=colorize,
        ),
        prepare_run_artifacts_fn=_prepare_run_artifacts,
        run_codex_batch_fn=lambda *, prompt, repo_root, output_file, log_file: run_codex_batch(
            prompt=prompt,
            repo_root=repo_root,
            output_file=output_file,
            log_file=log_file,
            deps=CodexBatchRunnerDeps(
                timeout_seconds=batch_timeout_seconds,
                subprocess_run=subprocess.run,
                timeout_error=subprocess.TimeoutExpired,
                safe_write_text_fn=safe_write_text,
                use_popen_runner=(getattr(subprocess.run, "__module__", "") == "subprocess"),
                subprocess_popen=subprocess.Popen,
                live_log_interval_seconds=batch_live_log_interval_seconds,
                stall_after_output_seconds=batch_stall_kill_seconds,
                max_retries=batch_max_retries,
                retry_backoff_seconds=batch_retry_backoff_seconds,
            ),
        ),
        execute_batches_fn=execute_batches,
        collect_batch_results_fn=_collect_batch_results,
        print_failures_fn=print_failures,
        print_failures_and_raise_fn=print_failures_and_raise,
        merge_batch_results_fn=_merge_batch_results,
        build_import_provenance_fn=build_batch_import_provenance,
        do_import_fn=_do_import,
        run_followup_scan_fn=lambda *, lang_name, scan_path: run_followup_scan(
            lang_name=lang_name,
            scan_path=scan_path,
            deps=FollowupScanDeps(
                project_root=runtime_project_root,
                timeout_seconds=FOLLOWUP_SCAN_TIMEOUT_SECONDS,
                python_executable=sys.executable,
                subprocess_run=subprocess.run,
                timeout_error=subprocess.TimeoutExpired,
                colorize_fn=colorize,
            ),
        ),
        safe_write_text_fn=safe_write_text,
        colorize_fn=colorize,
        project_root=runtime_project_root,
        subagent_runs_dir=_subagent_runs_dir(),
    )

def _validate_run_dir(run_dir: Path) -> tuple[dict, Path, str]:
    """Validate run directory, load summary, and return (summary, blind_packet_path, immutable_packet_path).

    Raises CommandError on any validation failure.
    """
    if not run_dir.is_dir():
        raise CommandError(f"run directory not found: {run_dir}", exit_code=1)

    summary_path = run_dir / "run_summary.json"
    if not summary_path.exists():
        raise CommandError(f"no run_summary.json in {run_dir}", exit_code=1)
    try:
        summary = json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandError(f"Error reading run summary: {exc}", exit_code=1) from exc

    successful = summary.get("successful_batches", [])
    blind_packet_path = Path(str(summary.get("blind_packet", "")))
    immutable_packet_path = str(summary.get("immutable_packet", ""))

    if not successful:
        raise CommandError("no successful batches in run summary.", exit_code=1)
    if not blind_packet_path.exists():
        raise PacketValidationError(f"blind packet not found: {blind_packet_path}", exit_code=1)

    try:
        packet = json.loads(Path(immutable_packet_path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise PacketValidationError(f"Error reading immutable packet: {exc}", exit_code=1) from exc

    summary["_packet"] = packet
    return summary, blind_packet_path, immutable_packet_path


def do_import_run(
    run_dir_path: str,
    state: dict,
    lang,
    state_file: str,
    *,
    config: dict | None = None,
    allow_partial: bool = False,
    scan_after_import: bool = False,
    scan_path: str = ".",
) -> None:
    """Re-import results from a completed run directory.

    Replays the merge+provenance+import step that normally runs at the end of
    ``--run-batches``.  Useful when the original pipeline was interrupted (e.g.
    broken pipe from background execution) but all batch results completed.
    """
    run_dir = Path(run_dir_path)
    summary, blind_packet_path, _immutable_path = _validate_run_dir(run_dir)

    runner = str(summary.get("runner", "codex"))
    stamp = str(summary.get("run_stamp", ""))
    successful = summary.get("successful_batches", [])
    packet = summary.pop("_packet", {})
    allowed_dims = {str(d) for d in packet.get("dimensions", []) if isinstance(d, str)}

    # -- locate and parse raw batch results --
    results_dir = run_dir / "results"
    selected_indexes = [idx - 1 for idx in successful]  # convert 1-based to 0-based
    output_files = {
        idx: results_dir / f"batch-{idx + 1}.raw.txt"
        for idx in selected_indexes
    }

    missing = [idx + 1 for idx in selected_indexes if not output_files[idx].exists()]
    if missing:
        raise CommandError(f"missing result files for batches: {missing}", exit_code=1)

    batch_results, failures = collect_batch_results(
        selected_indexes=selected_indexes,
        failures=[],
        output_files=output_files,
        allowed_dims=allowed_dims,
        extract_payload_fn=lambda raw: batch_core_mod.extract_json_payload(raw, log_fn=log),
        normalize_result_fn=lambda payload, dims: batch_core_mod.normalize_batch_result(
            payload,
            dims,
            max_batch_issues=max_batch_issues_for_dimension_count(len(dims)),
            abstraction_sub_axes=ABSTRACTION_SUB_AXES,
        ),
    )

    if not batch_results:
        raise CommandError("no valid batch results could be parsed.", exit_code=1)

    print(colorize(f"  Parsed {len(batch_results)} batch results from {run_dir}", "bold"))
    if failures:
        print(colorize(f"  Warning: {len(failures)} batches failed to parse: {[f + 1 for f in failures]}", "yellow"))

    # -- merge --
    merged = _merge_batch_results(batch_results)

    # -- build provenance --
    successful_indexes = [idx for idx in selected_indexes if idx not in set(failures)]
    merged["provenance"] = build_batch_import_provenance(
        runner=runner,
        blind_packet_path=blind_packet_path,
        run_stamp=stamp,
        batch_indexes=successful_indexes,
    )

    # -- write merged output --
    merged_path = run_dir / "holistic_issues_merged.json"
    safe_write_text(merged_path, json.dumps(merged, indent=2) + "\n")
    print(colorize(f"  Merged output: {merged_path}", "bold"))

    # -- import with trusted source --
    _do_import(
        str(merged_path),
        state,
        lang,
        state_file,
        config=config,
        allow_partial=allow_partial,
        trusted_assessment_source=True,
        trusted_assessment_label=f"trusted import-run replay from {run_dir.name}",
    )

    # -- optional follow-up scan --
    if scan_after_import:
        lang_name = getattr(lang, "name", None) or str(getattr(lang, "lang", ""))
        if lang_name:
            run_followup_scan(
                lang_name=lang_name,
                scan_path=scan_path,
                deps=FollowupScanDeps(
                    project_root=_runtime_project_root(),
                    timeout_seconds=FOLLOWUP_SCAN_TIMEOUT_SECONDS,
                    python_executable=sys.executable,
                    subprocess_run=subprocess.run,
                    timeout_error=subprocess.TimeoutExpired,
                    colorize_fn=colorize,
                ),
            )
