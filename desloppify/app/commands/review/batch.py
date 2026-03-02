"""Batch runner helpers and orchestration for review command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from desloppify.app.commands.helpers.query import write_query_best_effort
from . import batch_core as batch_core_mod
from . import batches as review_batches_mod
from . import runner_helpers as runner_helpers_mod
from desloppify.core._internal.coercions import coerce_positive_int
from desloppify.core._internal.text_utils import get_project_root
from desloppify.core.fallbacks import print_error
from desloppify.core.discovery_api import safe_write_text
from desloppify.intelligence import narrative as narrative_mod
from desloppify.intelligence import review as review_mod
from desloppify.intelligence.review.feedback_contract import (
    max_batch_findings_for_dimension_count,
)
from desloppify.core.output_api import colorize, log

from .helpers import parse_dimensions
from .import_cmd import do_import as _do_import
from .packet_policy import coerce_review_batch_file_limit, redacted_review_config
from .runtime import setup_lang_concrete as _setup_lang

# Backward-compatible override hooks for tests.
PROJECT_ROOT: Path | None = None
REVIEW_PACKET_DIR: Path | None = None
SUBAGENT_RUNS_DIR: Path | None = None
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


def _runtime_project_root() -> Path:
    if isinstance(PROJECT_ROOT, Path):
        return PROJECT_ROOT
    return get_project_root()


def _review_packet_dir() -> Path:
    if isinstance(REVIEW_PACKET_DIR, Path):
        return REVIEW_PACKET_DIR
    return _runtime_project_root() / ".desloppify" / "review_packets"


def _subagent_runs_dir() -> Path:
    if isinstance(SUBAGENT_RUNS_DIR, Path):
        return SUBAGENT_RUNS_DIR
    return _runtime_project_root() / ".desloppify" / "subagents" / "runs"


def _blind_packet_path() -> Path:
    return _runtime_project_root() / ".desloppify" / "review_packet_blind.json"


def _merge_batch_results(batch_results: list[object]) -> dict[str, object]:
    """Deterministically merge assessments/findings across batch outputs."""
    normalized_results: list[dict] = []
    for result in batch_results:
        if hasattr(result, "to_dict") and callable(result.to_dict):
            payload = result.to_dict()
            if isinstance(payload, dict):
                normalized_results.append(payload)
                continue
        if isinstance(result, dict):
            normalized_results.append(result)
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
            print_error(f"packet not found: {packet_override}")
            sys.exit(1)
        try:
            packet = json.loads(packet_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            print_error(f"reading packet: {exc}")
            sys.exit(1)
        blind_path = _blind_packet_path()
        blind_packet = runner_helpers_mod.build_blind_packet(packet)
        safe_write_text(blind_path, json.dumps(blind_packet, indent=2) + "\n")
        print(colorize(f"  Immutable packet: {packet_path}", "dim"))
        print(colorize(f"  Blind packet: {blind_path}", "dim"))
        return packet, packet_path, blind_path

    path = Path(args.path)
    dims = parse_dimensions(args)
    dimensions = list(dims) if dims else None
    retrospective = bool(getattr(args, "retrospective", False))
    retrospective_max_issues = coerce_positive_int(
        getattr(args, "retrospective_max_issues", None),
        default=30,
        minimum=1,
    )
    retrospective_max_batch_items = coerce_positive_int(
        getattr(args, "retrospective_max_batch_items", None),
        default=20,
        minimum=1,
    )
    lang_run, found_files = _setup_lang(lang, path, config)
    lang_name = lang_run.name
    narrative = narrative_mod.compute_narrative(
        state,
        context=narrative_mod.NarrativeContext(lang=lang_name, command="review"),
    )

    blind_path = _blind_packet_path()
    packet = review_mod.prepare_holistic_review(
        path,
        lang_run,
        state,
        options=review_mod.HolisticReviewPrepareOptions(
            dimensions=dimensions,
            files=found_files or None,
            max_files_per_batch=coerce_review_batch_file_limit(config),
            include_issue_history=retrospective,
            issue_history_max_issues=retrospective_max_issues,
            issue_history_max_batch_items=retrospective_max_batch_items,
        ),
    )
    packet["config"] = redacted_review_config(config)
    packet["narrative"] = narrative
    next_command = "desloppify review --run-batches --runner codex --parallel"
    if retrospective:
        next_command += (
            " --retrospective"
            f" --retrospective-max-issues {retrospective_max_issues}"
            f" --retrospective-max-batch-items {retrospective_max_batch_items}"
        )
    packet["next_command"] = next_command
    write_query_best_effort(
        packet,
        context="review packet query update",
    )
    packet_path, blind_saved = runner_helpers_mod.write_packet_snapshot(
        packet,
        stamp=stamp,
        review_packet_dir=_review_packet_dir(),
        blind_path=blind_path,
        safe_write_text_fn=safe_write_text,
    )
    print(colorize(f"  Immutable packet: {packet_path}", "dim"))
    print(colorize(f"  Blind packet: {blind_saved}", "dim"))
    return packet, packet_path, blind_saved


def _do_run_batches(args, state, lang, state_file, config: dict | None = None) -> None:
    """Run holistic investigation batches with a local subagent runner."""
    from .runtime.policy import resolve_batch_run_policy

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
        return runner_helpers_mod.prepare_run_artifacts(
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
        return runner_helpers_mod.collect_batch_results(
            selected_indexes=selected_indexes,
            failures=failures,
            output_files=output_files,
            allowed_dims=allowed_dims,
            extract_payload_fn=lambda raw: batch_core_mod.extract_json_payload(raw, log_fn=log),
            normalize_result_fn=lambda payload, dims: batch_core_mod.normalize_batch_result(
                payload,
                dims,
                max_batch_findings=max_batch_findings_for_dimension_count(
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
        run_stamp_fn=runner_helpers_mod.run_stamp,
        load_or_prepare_packet_fn=_load_or_prepare_packet,
        selected_batch_indexes_fn=lambda args, *, batch_count: runner_helpers_mod.selected_batch_indexes(
            raw_selection=getattr(args, "only_batches", None),
            batch_count=batch_count,
            parse_fn=batch_core_mod.parse_batch_selection,
            colorize_fn=colorize,
        ),
        prepare_run_artifacts_fn=_prepare_run_artifacts,
        run_codex_batch_fn=lambda *, prompt, repo_root, output_file, log_file: runner_helpers_mod.run_codex_batch(
            prompt=prompt,
            repo_root=repo_root,
            output_file=output_file,
            log_file=log_file,
            deps=runner_helpers_mod.CodexBatchRunnerDeps(
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
        execute_batches_fn=runner_helpers_mod.execute_batches,
        collect_batch_results_fn=_collect_batch_results,
        print_failures_fn=runner_helpers_mod.print_failures,
        print_failures_and_exit_fn=runner_helpers_mod.print_failures_and_exit,
        merge_batch_results_fn=_merge_batch_results,
        build_import_provenance_fn=runner_helpers_mod.build_batch_import_provenance,
        do_import_fn=_do_import,
        run_followup_scan_fn=lambda *, lang_name, scan_path: runner_helpers_mod.run_followup_scan(
            lang_name=lang_name,
            scan_path=scan_path,
            deps=runner_helpers_mod.FollowupScanDeps(
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

    Exits with error message on any validation failure.
    """
    if not run_dir.is_dir():
        print(colorize(f"  Error: run directory not found: {run_dir}", "red"), file=sys.stderr)
        sys.exit(1)

    summary_path = run_dir / "run_summary.json"
    if not summary_path.exists():
        print(colorize(f"  Error: no run_summary.json in {run_dir}", "red"), file=sys.stderr)
        sys.exit(1)
    try:
        summary = json.loads(summary_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(colorize(f"  Error reading run summary: {exc}", "red"), file=sys.stderr)
        sys.exit(1)

    successful = summary.get("successful_batches", [])
    blind_packet_path = Path(str(summary.get("blind_packet", "")))
    immutable_packet_path = str(summary.get("immutable_packet", ""))

    if not successful:
        print(colorize("  Error: no successful batches in run summary.", "red"), file=sys.stderr)
        sys.exit(1)
    if not blind_packet_path.exists():
        print(colorize(f"  Error: blind packet not found: {blind_packet_path}", "red"), file=sys.stderr)
        sys.exit(1)

    try:
        packet = json.loads(Path(immutable_packet_path).read_text())
    except (OSError, json.JSONDecodeError) as exc:
        print(colorize(f"  Error reading immutable packet: {exc}", "red"), file=sys.stderr)
        sys.exit(1)

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
        print(colorize(f"  Error: missing result files for batches: {missing}", "red"), file=sys.stderr)
        sys.exit(1)

    batch_results, failures = runner_helpers_mod.collect_batch_results(
        selected_indexes=selected_indexes,
        failures=[],
        output_files=output_files,
        allowed_dims=allowed_dims,
        extract_payload_fn=lambda raw: batch_core_mod.extract_json_payload(raw, log_fn=log),
        normalize_result_fn=lambda payload, dims: batch_core_mod.normalize_batch_result(
            payload,
            dims,
            max_batch_findings=max_batch_findings_for_dimension_count(len(dims)),
            abstraction_sub_axes=ABSTRACTION_SUB_AXES,
        ),
    )

    if not batch_results:
        print(colorize("  Error: no valid batch results could be parsed.", "red"), file=sys.stderr)
        sys.exit(1)

    print(colorize(f"  Parsed {len(batch_results)} batch results from {run_dir}", "bold"))
    if failures:
        print(colorize(f"  Warning: {len(failures)} batches failed to parse: {[f + 1 for f in failures]}", "yellow"))

    # -- merge --
    merged = _merge_batch_results(batch_results)

    # -- build provenance --
    successful_indexes = [idx for idx in selected_indexes if idx not in set(failures)]
    merged["provenance"] = runner_helpers_mod.build_batch_import_provenance(
        runner=runner,
        blind_packet_path=blind_packet_path,
        run_stamp=stamp,
        batch_indexes=successful_indexes,
    )

    # -- write merged output --
    merged_path = run_dir / "holistic_findings_merged.json"
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
            runner_helpers_mod.run_followup_scan(
                lang_name=lang_name,
                scan_path=scan_path,
                deps=runner_helpers_mod.FollowupScanDeps(
                    project_root=_runtime_project_root(),
                    timeout_seconds=FOLLOWUP_SCAN_TIMEOUT_SECONDS,
                    python_executable=sys.executable,
                    subprocess_run=subprocess.run,
                    timeout_error=subprocess.TimeoutExpired,
                    colorize_fn=colorize,
                ),
            )
