"""scan command: run all detectors, update persistent state, show diff."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import query_file_path
from desloppify.app.commands.helpers.runtime_options import (
    LangRuntimeOptionsError,
    print_lang_runtime_options_error,
)
from desloppify.app.commands.helpers.score import target_strict_score_from_config
from desloppify.app.commands.scan.scan_artifacts import (
    build_scan_query_payload,
    emit_scorecard_badge,
)
from desloppify.app.commands.scan.scan_helpers import (  # noqa: F401 (re-exports)
    _audit_excluded_dirs,
    _collect_codebase_metrics,
    _effective_include_slow,
    format_delta,
    _resolve_scan_profile,
    _warn_explicit_lang_with_no_files,
)
from desloppify.app.commands.scan.scan_reporting_analysis import (
    show_post_scan_analysis,
)
from desloppify.app.commands.scan.scan_reporting_dimensions import (
    show_dimension_deltas,
    show_score_model_breakdown,
    show_scorecard_subjective_measures,
)
from desloppify.app.commands.scan.scan_reporting_llm import (
    _print_llm_summary,
    auto_update_skill,
)
from desloppify.app.commands.scan.scan_reporting_summary import (  # noqa: F401
    show_diff_summary,
    show_score_delta,
    show_strict_target_progress,
)
from desloppify.app.commands.scan.scan_orchestrator import ScanOrchestrator
from desloppify.app.commands.scan.scan_workflow import (
    ScanStateContractError,
    merge_scan_results,
    persist_reminder_history,
    prepare_scan_runtime,
    resolve_noise_snapshot,
    run_scan_generation,
)
from desloppify.core.query import write_query
from desloppify.core.output_api import colorize


def _print_scan_header(lang_label: str) -> None:
    """Print the scan header line."""
    print(colorize(f"\nDesloppify Scan{lang_label}\n", "bold"))


def _print_scan_complete_banner() -> None:
    """Print scan completion hint banner."""
    lines = [
        colorize("  Scan complete", "bold"),
        colorize("  " + "─" * 50, "dim"),
    ]
    print("\n".join(lines))


def _show_scan_visibility(noise, effective_include_slow: bool) -> None:
    """Print fast-scan and noise budget visibility hints."""
    if not effective_include_slow:
        print(colorize("  * Fast scan — slow phases (duplicates) skipped", "yellow"))
    if noise.budget_warning:
        print(colorize(f"  * {noise.budget_warning}", "yellow"))
    if noise.hidden_total:
        print(
            colorize(
                f"  * {noise.hidden_total} findings hidden (showing {noise.noise_budget}/detector). "
                "Use `desloppify show <detector>` to see all.",
                "dim",
            )
        )


def _show_coverage_preflight(runtime) -> None:
    """Print preflight warnings when scan coverage confidence is reduced."""
    warnings = getattr(runtime, "coverage_warnings", []) or []
    if not isinstance(warnings, list) or not warnings:
        return

    for entry in warnings:
        if not isinstance(entry, dict):
            continue
        summary = str(entry.get("summary", "")).strip()
        impact = str(entry.get("impact", "")).strip()
        remediation = str(entry.get("remediation", "")).strip()
        detector = str(entry.get("detector", "")).strip() or "detector"

        headline = summary or f"Coverage reduced for `{detector}`."
        print(colorize(f"  * Coverage preflight: {headline}", "yellow"))
        if impact:
            print(colorize(f"    Repercussion: {impact}", "dim"))
        if remediation:
            print(colorize(f"    Fix: {remediation}", "dim"))


def cmd_scan(args: argparse.Namespace) -> None:
    """Run all detectors, update persistent state, show diff."""
    try:
        runtime = prepare_scan_runtime(args)
    except LangRuntimeOptionsError as exc:
        lang_cfg = resolve_lang(args)
        lang_name = lang_cfg.name if lang_cfg else "selected"
        print_lang_runtime_options_error(exc, lang_name=lang_name)
        raise SystemExit(2) from exc
    except ScanStateContractError as exc:
        print(colorize(f"  {exc}", "red"))
        raise SystemExit(2) from exc
    orchestrator = ScanOrchestrator(
        runtime,
        run_scan_generation_fn=run_scan_generation,
        merge_scan_results_fn=merge_scan_results,
        resolve_noise_snapshot_fn=resolve_noise_snapshot,
        persist_reminder_history_fn=persist_reminder_history,
    )
    _print_scan_header(runtime.lang_label)
    if runtime.reset_subjective_count > 0:
        print(
            colorize(
                "  * Subjective reset "
                f"{runtime.reset_subjective_count} subjective dimensions to 0",
                "yellow",
            )
        )
    if runtime.expired_manual_override_count > 0:
        print(
            colorize(
                "  * Expired provisional manual-override assessments: "
                f"{runtime.expired_manual_override_count} dimension(s) reset to 0. "
                "Use trusted `review --run-batches --runner codex --parallel --scan-after-import` to replace them.",
                "yellow",
            )
        )
    _show_coverage_preflight(runtime)

    findings, potentials, codebase_metrics = orchestrator.generate()
    merge = orchestrator.merge(findings, potentials, codebase_metrics)
    _print_scan_complete_banner()

    noise = orchestrator.noise_snapshot()

    target_value = target_strict_score_from_config(runtime.config, fallback=95.0)

    show_diff_summary(merge.diff)
    show_score_delta(
        runtime.state,
        merge.prev_overall,
        merge.prev_objective,
        merge.prev_strict,
        merge.prev_verified,
        target_strict=target_value,
    )
    _show_scan_visibility(noise, runtime.effective_include_slow)
    show_scorecard_subjective_measures(runtime.state)
    show_score_model_breakdown(runtime.state)

    new_dim_scores = runtime.state.get("dimension_scores", {})
    if new_dim_scores and merge.prev_dim_scores:
        show_dimension_deltas(merge.prev_dim_scores, new_dim_scores)

    warnings, narrative = show_post_scan_analysis(
        merge.diff,
        runtime.state,
        runtime.lang,
        target_strict_score=target_value,
    )
    orchestrator.persist_reminders(narrative)

    write_query(
        build_scan_query_payload(
            runtime.state,
            runtime.config,
            runtime.profile,
            merge.diff,
            warnings,
            narrative,
            merge,
            noise,
        ),
        query_file=query_file_path(),
    )

    badge_emit = emit_scorecard_badge(args, runtime.config, runtime.state)
    if isinstance(badge_emit, tuple):
        badge_path, _badge_result = badge_emit
    else:  # Backward-compatible shape for monkeypatched tests.
        badge_path = badge_emit
    _print_llm_summary(runtime.state, badge_path, narrative, merge.diff)
    auto_update_skill()


__all__ = [
    "cmd_scan",
]
