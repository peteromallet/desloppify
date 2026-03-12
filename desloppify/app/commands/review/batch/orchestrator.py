"""Batch runner helpers and orchestration for review command."""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys
from functools import partial
from pathlib import Path
from typing import cast

from desloppify.app.commands.helpers.query import write_query_best_effort
from desloppify.base.coercions import coerce_positive_int
from desloppify.base.discovery.file_paths import safe_write_text
from desloppify.base.exception_sets import CommandError, PacketValidationError
from desloppify.base.output.terminal import colorize, log
from desloppify.base.search.query_paths import query_file_path
import desloppify.intelligence.narrative.core as narrative_mod
from desloppify.intelligence.review.feedback_contract import (
    max_batch_issues_for_dimension_count,
)
from desloppify.intelligence.review.prepare import (
    HolisticReviewPrepareOptions,
    prepare_holistic_review,
)

from ..helpers import parse_dimensions
from ..importing.cmd import do_import as _do_import
from ..importing.flags import ReviewImportConfig
from ..packet.build import (
    build_holistic_packet,
    build_run_batches_next_command,
    prepared_packet_contract,
    resolve_review_packet_context,
)
from ..packet.policy import coerce_review_batch_file_limit, redacted_review_config
from ..prompt_sections import explode_to_single_dimension
from ..runner_failures import print_failures, print_failures_and_raise
from ..runner_packets import (
    build_batch_import_provenance,
    build_blind_packet,
    prepare_run_artifacts,
    run_stamp,
    selected_batch_indexes,
    write_packet_snapshot,
)
from ..runner_parallel import BatchExecutionOptions, collect_batch_results, execute_batches
from desloppify.app.commands.runner.codex_batch import (
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
    review_packet_dir as _review_packet_dir,
)
from ..runtime_paths import (
    runtime_project_root as _runtime_project_root,
)
from ..runtime_paths import (
    subagent_runs_dir as _subagent_runs_dir,
)
from .core_merge_support import assessment_weight  # noqa: F401 — re-exported
from .core_models import BatchResultPayload
from .scope import (
    normalize_dimension_list,
    scored_dimensions_for_lang,
)
from .core_normalize import normalize_batch_result
from .core_parse import extract_json_payload, parse_batch_selection
from . import execution_phases as review_batch_phases_mod
from .merge import merge_batch_results
from .prompt_template import render_batch_prompt
from . import execution as review_batches_mod
from .execution_results import (
    enforce_import_coverage as _enforce_import_coverage,
    merge_and_write_results as _merge_and_write_results,
)

FOLLOWUP_SCAN_TIMEOUT_SECONDS = 45 * 60
_PREPARED_PACKET_CONTRACT_KEY = "prepared_packet_contract"
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


def _batch_live_log_interval_seconds(heartbeat_seconds: float) -> float:
    """Clamp the live log polling interval derived from the heartbeat."""
    if heartbeat_seconds <= 0:
        return 5.0
    return max(1.0, min(heartbeat_seconds, 10.0))


def _build_batch_run_deps(*, policy, project_root: Path) -> review_batches_mod.BatchRunDeps:
    """Build the dependency bundle used by prepare/execute/import phases."""
    from desloppify.engine.plan_state import load_policy_result, render_policy_block

    policy_result = load_policy_result()
    policy_block = render_policy_block(policy_result.policy)
    if not policy_result.ok:
        print(
            colorize(
                f"  Warning: ignoring malformed project policy ({policy_result.message or 'unknown error'}).",
                "yellow",
            )
        )
    codex_batch_deps = CodexBatchRunnerDeps(
        timeout_seconds=policy.batch_timeout_seconds,
        subprocess_run=subprocess.run,
        timeout_error=subprocess.TimeoutExpired,
        safe_write_text_fn=safe_write_text,
        use_popen_runner=(getattr(subprocess.run, "__module__", "") == "subprocess"),
        subprocess_popen=subprocess.Popen,
        live_log_interval_seconds=_batch_live_log_interval_seconds(
            policy.heartbeat_seconds
        ),
        stall_after_output_seconds=policy.stall_kill_seconds,
        max_retries=policy.batch_max_retries,
        retry_backoff_seconds=policy.batch_retry_backoff_seconds,
    )
    followup_scan_deps = FollowupScanDeps(
        project_root=project_root,
        timeout_seconds=FOLLOWUP_SCAN_TIMEOUT_SECONDS,
        python_executable=sys.executable,
        subprocess_run=subprocess.run,
        timeout_error=subprocess.TimeoutExpired,
        colorize_fn=colorize,
    )
    return review_batches_mod.BatchRunDeps(
        run_stamp_fn=run_stamp,
        load_or_prepare_packet_fn=_load_or_prepare_packet,
        selected_batch_indexes_fn=lambda args, batch_count: selected_batch_indexes(
            raw_selection=getattr(args, "only_batches", None),
            batch_count=batch_count,
            parse_fn=parse_batch_selection,
            colorize_fn=colorize,
        ),
        prepare_run_artifacts_fn=partial(
            prepare_run_artifacts,
            build_prompt_fn=partial(render_batch_prompt, policy_block=policy_block),
            safe_write_text_fn=safe_write_text,
            colorize_fn=colorize,
        ),
        run_codex_batch_fn=partial(
            run_codex_batch,
            deps=codex_batch_deps,
        ),
        execute_batches_fn=lambda **kwargs: execute_batches(
            tasks=kwargs["tasks"],
            options=BatchExecutionOptions(
                run_parallel=kwargs["options"].run_parallel,
                max_parallel_workers=kwargs["options"].max_parallel_workers,
                heartbeat_seconds=kwargs["options"].heartbeat_seconds,
            ),
            progress_fn=kwargs.get("progress_fn"),
            error_log_fn=kwargs.get("error_log_fn"),
        ),
        collect_batch_results_fn=lambda **kwargs: collect_batch_results(
            selected_indexes=kwargs["selected_indexes"],
            failures=kwargs["failures"],
            output_files=kwargs["output_files"],
            allowed_dims=kwargs["allowed_dims"],
            extract_payload_fn=lambda raw: extract_json_payload(raw, log_fn=log),
            normalize_result_fn=lambda payload, dims: normalize_batch_result(
                payload,
                dims,
                max_batch_issues=max_batch_issues_for_dimension_count(len(dims)),
                abstraction_sub_axes=ABSTRACTION_SUB_AXES,
            ),
        ),
        print_failures_fn=print_failures,
        print_failures_and_raise_fn=print_failures_and_raise,
        merge_batch_results_fn=_merge_batch_results,
        build_import_provenance_fn=build_batch_import_provenance,
        do_import_fn=_do_import,
        run_followup_scan_fn=partial(
            run_followup_scan,
            deps=followup_scan_deps,
        ),
        safe_write_text_fn=safe_write_text,
        colorize_fn=colorize,
    )


def _build_prepared_packet_contract(args, *, config: dict | None) -> dict[str, object]:
    """Build normalized invocation contract for prepared packet reuse."""
    return prepared_packet_contract(resolve_review_packet_context(args), config=config)


def _prepared_packet_contract_mismatch_reason(
    packet: dict[str, object],
    expected_contract: dict[str, object],
) -> str | None:
    """Return mismatch reason for prepared packet reuse, else ``None``."""
    raw_contract = packet.get(_PREPARED_PACKET_CONTRACT_KEY)
    if not isinstance(raw_contract, dict):
        return "missing prepared packet contract metadata"

    for key in (
        "path",
        "dimensions",
        "retrospective",
        "retrospective_max_issues",
        "retrospective_max_batch_items",
        "config_hash",
    ):
        if raw_contract.get(key) != expected_contract.get(key):
            return f"contract field '{key}' differs"
    return None


def _try_load_prepared_packet(
    *,
    expected_contract: dict[str, object],
) -> tuple[dict | None, str | None]:
    """Load prepared packet from query.json when shape and contract match."""
    try:
        qf = query_file_path()
        if not qf.exists():
            return None, None
        data = json.loads(qf.read_text())
    except (OSError, json.JSONDecodeError, RuntimeError):
        return None, "query.json is missing or invalid JSON"
    if not isinstance(data, dict):
        return None, "prepared packet payload is not an object"
    if "investigation_batches" not in data:
        return None, "prepared packet is missing investigation batches"
    batches = data["investigation_batches"]
    if not isinstance(batches, list) or not batches:
        return None, "prepared packet has no investigation batches"

    mismatch_reason = _prepared_packet_contract_mismatch_reason(
        data,
        expected_contract,
    )
    if mismatch_reason is not None:
        return None, mismatch_reason
    return data, None


def _merge_batch_results(batch_results: list[object]) -> dict[str, object]:
    """Deterministically merge assessments/issues across batch outputs."""
    normalized_results: list[BatchResultPayload] = []
    for result in batch_results:
        if hasattr(result, "to_dict") and callable(result.to_dict):
            payload = result.to_dict()
            if isinstance(payload, dict):
                normalized_results.append(cast(BatchResultPayload, payload))
                continue
        if isinstance(result, dict):
            normalized_results.append(cast(BatchResultPayload, result))
    return merge_batch_results(
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

    # When no explicit --packet and no explicit --dimensions were given,
    # check whether a prior ``review --prepare`` left a valid query.json
    # packet we can reuse instead of rebuilding from scratch.
    dims = parse_dimensions(args)

    # Validate explicit dimensions against the language's scored dimensions.
    if dims:
        lang_obj = lang
        lang_name = getattr(lang_obj, "name", None) or str(getattr(lang_obj, "lang", ""))
        if lang_name:
            valid_dims = set(scored_dimensions_for_lang(lang_name))
            if valid_dims:
                invalid = sorted(dims - valid_dims)
                if invalid:
                    valid_list = ", ".join(sorted(valid_dims))
                    raise CommandError(
                        f"Invalid dimensions for language '{lang_name}': {', '.join(invalid)}. "
                        f"Valid dimensions: {valid_list}",
                        exit_code=1,
                    )

    expected_contract = _build_prepared_packet_contract(args, config=config)
    if not dims:
        prepared, mismatch_reason = _try_load_prepared_packet(
            expected_contract=expected_contract,
        )
        if prepared is not None:
            print(colorize("  Reusing prepared packet from query.json", "dim"))
            blind_path = _blind_packet_path()
            blind_packet = build_blind_packet(prepared)
            safe_write_text(blind_path, json.dumps(blind_packet, indent=2) + "\n")
            packet_path, blind_saved = write_packet_snapshot(
                prepared,
                stamp=stamp,
                review_packet_dir=_review_packet_dir(),
                blind_path=blind_path,
                safe_write_text_fn=safe_write_text,
            )
            print(colorize(f"  Immutable packet: {packet_path}", "dim"))
            print(colorize(f"  Blind packet: {blind_saved}", "dim"))
            return prepared, packet_path, blind_saved
        if mismatch_reason:
            print(
                colorize(
                    f"  Prepared packet reuse rejected: {mismatch_reason}; rebuilding.",
                    "dim",
                )
            )

    context = resolve_review_packet_context(args)
    blind_path = _blind_packet_path()
    packet, _lang_name = build_holistic_packet(
        state=state,
        lang=lang,
        config=config,
        context=context,
        setup_lang_fn=_setup_lang,
        prepare_holistic_review_fn=prepare_holistic_review,
    )
    packet["config"] = redacted_review_config(config)
    packet[_PREPARED_PACKET_CONTRACT_KEY] = expected_contract
    packet["next_command"] = build_run_batches_next_command(context)
    write_query_best_effort(
        packet,
        context="review packet query update",
    )
    packet_path, blind_saved = write_packet_snapshot(
        packet,
        stamp=stamp,
        review_packet_dir=_review_packet_dir(),
        blind_path=blind_path,
        safe_write_text_fn=safe_write_text,
    )
    print(colorize(f"  Immutable packet: {packet_path}", "dim"))
    print(colorize(f"  Blind packet: {blind_saved}", "dim"))
    return packet, packet_path, blind_saved


def do_run_batches(args, state, lang, state_file, config: dict | None = None) -> None:
    """Run holistic investigation batches with a local subagent runner."""
    from ..runtime.policy import resolve_batch_run_policy  # noqa: PLC0415

    project_root = _runtime_project_root()
    subagent_runs_dir = _subagent_runs_dir()
    policy = resolve_batch_run_policy(args)
    batch_deps = _build_batch_run_deps(
        policy=policy,
        project_root=project_root,
    )
    prepared = review_batch_phases_mod.prepare_batch_run(
        args=args,
        state=state,
        lang=lang,
        config=config or {},
        deps=batch_deps,
        project_root=project_root,
        subagent_runs_dir=subagent_runs_dir,
    )
    if prepared is None:
        return

    executed = review_batch_phases_mod.execute_batch_run(
        prepared=prepared,
        deps=batch_deps,
    )
    review_batch_phases_mod.merge_and_import_batch_run(
        prepared=prepared,
        executed=executed,
        state_file=state_file,
        deps=batch_deps,
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

    selected = summary.get("selected_batches", [])
    blind_packet_path = Path(str(summary.get("blind_packet", "")))
    immutable_packet_path = str(summary.get("immutable_packet", ""))

    if not selected:
        raise CommandError("no selected batches in run summary.", exit_code=1)
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
    dry_run: bool = False,
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
    selected = summary.get("selected_batches", [])
    packet = summary.pop("_packet", {})
    allowed_dims = {str(d) for d in packet.get("dimensions", []) if isinstance(d, str)}

    # -- locate and parse raw batch results --
    results_dir = run_dir / "results"
    selected_indexes = [idx - 1 for idx in selected]  # convert 1-based to 0-based
    output_files = {
        idx: results_dir / f"batch-{idx + 1}.raw.txt"
        for idx in selected_indexes
    }

    missing = [idx + 1 for idx in selected_indexes if not output_files[idx].exists()]
    if missing:
        if not results_dir.exists():
            hint = (
                f"Results directory does not exist: {results_dir}\n"
                "  Did you run --run-batches or launch subagents to produce results first?"
            )
        elif len(missing) == len(selected):
            hint = (
                f"No result files found in {results_dir}\n"
                "  Each subagent must write its output to results/batch-N.raw.txt.\n"
                "  Run --run-batches first, or launch subagents on the prompts/ files manually."
            )
        else:
            hint = (
                f"Missing result files in {results_dir}: batches {missing}\n"
                "  Re-run the failed batches or use --allow-partial to import what succeeded."
            )
        raise CommandError(hint, exit_code=1)

    batch_results, failures = collect_batch_results(
        selected_indexes=selected_indexes,
        failures=[],
        output_files=output_files,
        allowed_dims=allowed_dims,
        extract_payload_fn=lambda raw: extract_json_payload(raw, log_fn=log),
        normalize_result_fn=lambda payload, dims: normalize_batch_result(
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

    successful_indexes = [idx for idx in selected_indexes if idx not in set(failures)]

    # Reuse the canonical merge+metadata boundary from normal batch execution.
    raw_batches = packet.get("investigation_batches", [])
    raw_dim_prompts = packet.get("dimension_prompts")
    batches = explode_to_single_dimension(
        raw_batches if isinstance(raw_batches, list) else [],
        dimension_prompts=raw_dim_prompts if isinstance(raw_dim_prompts, dict) else None,
    )
    packet_dimensions = normalize_dimension_list(packet.get("dimensions", []))
    lang_name = getattr(lang, "name", None) or str(getattr(lang, "lang", ""))
    scored_dimensions = scored_dimensions_for_lang(lang_name) if lang_name else []
    merged_path, missing_after_import = _merge_and_write_results(
        merge_batch_results_fn=_merge_batch_results,
        build_import_provenance_fn=build_batch_import_provenance,
        batch_results=batch_results,
        batches=batches,
        successful_indexes=successful_indexes,
        packet=packet,
        packet_dimensions=packet_dimensions,
        scored_dimensions=scored_dimensions,
        scan_path=scan_path,
        runner=runner,
        prompt_packet_path=blind_packet_path,
        stamp=stamp,
        run_dir=run_dir,
        safe_write_text_fn=safe_write_text,
        colorize_fn=colorize,
    )
    _enforce_import_coverage(
        missing_after_import=missing_after_import,
        packet_dimensions=packet_dimensions,
        allow_partial=allow_partial,
        scan_path=scan_path,
        colorize_fn=colorize,
    )

    # -- import with trusted source --
    _do_import(
        str(merged_path),
        state,
        lang,
        state_file,
        import_config=ReviewImportConfig(
            config=config,
            allow_partial=allow_partial,
            trusted_assessment_source=True,
            trusted_assessment_label=f"trusted import-run replay from {run_dir.name}",
        ),
        dry_run=dry_run,
    )

    # -- optional follow-up scan --
    if scan_after_import and not dry_run:
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
