"""scan command: run all detectors, update persistent state, show diff."""

from __future__ import annotations

from desloppify.app.commands.helpers.query import QUERY_FILE
from desloppify.app.commands.helpers.score import target_strict_score_from_config
from desloppify.app.commands.scan.scan_artifacts import (
    build_scan_query_payload,
    emit_scorecard_badge,
)
from desloppify.app.commands.scan.scan_helpers import (
    _audit_excluded_dirs,
    _collect_codebase_metrics,
    _effective_include_slow,
    _format_delta,
    _format_hidden_by_detector,
    _resolve_scan_profile,
    _warn_explicit_lang_with_no_files,
)
from desloppify.app.commands.scan.scan_reporting_analysis import (
    _show_post_scan_analysis,
    _show_score_integrity,
)
from desloppify.app.commands.scan.scan_reporting_dimensions import (
    _show_dimension_deltas,
    _show_low_dimension_hints,
    _show_score_model_breakdown,
    _show_scorecard_subjective_measures,
    _show_subjective_paths,
)
from desloppify.app.commands.scan.scan_reporting_llm import _print_llm_summary
from desloppify.app.commands.scan.scan_reporting_summary import (
    _show_diff_summary,
    _show_score_delta,
    _show_strict_target_progress,
)
from desloppify.app.commands.scan.scan_workflow import (
    merge_scan_results,
    persist_reminder_history,
    prepare_scan_runtime,
    resolve_noise_snapshot,
    run_scan_generation,
)
from desloppify.core.query import write_query
from desloppify.utils import colorize


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
        global_label = (
            f", {noise.global_noise_budget} global"
            if noise.global_noise_budget > 0
            else ""
        )
        print(
            colorize(
                f"  * Noise budget: {noise.noise_budget}/detector{global_label} "
                f"({noise.hidden_total} findings hidden in show output: "
                f"{_format_hidden_by_detector(noise.hidden_by_detector)})",
                "dim",
            )
        )


def cmd_scan(args) -> None:
    """Run all detectors, update persistent state, show diff."""
    runtime = prepare_scan_runtime(args)
    _print_scan_header(runtime.lang_label)
    if runtime.reset_subjective_count > 0:
        print(
            colorize(
                "  * Subjective reset "
                f"{runtime.reset_subjective_count} subjective dimensions to 0",
                "yellow",
            )
        )

    findings, potentials, codebase_metrics = run_scan_generation(runtime)
    merge = merge_scan_results(runtime, findings, potentials, codebase_metrics)
    _print_scan_complete_banner()

    noise = resolve_noise_snapshot(runtime.state, runtime.config)

    _show_diff_summary(merge.diff)
    _show_score_delta(
        runtime.state,
        merge.prev_overall,
        merge.prev_objective,
        merge.prev_strict,
        merge.prev_verified,
    )
    _show_scan_visibility(noise, runtime.effective_include_slow)
    _show_scorecard_subjective_measures(runtime.state)
    _show_score_model_breakdown(runtime.state)

    target_value = target_strict_score_from_config(runtime.config, fallback=95.0)

    new_dim_scores = runtime.state.get("dimension_scores", {})
    if new_dim_scores and merge.prev_dim_scores:
        _show_dimension_deltas(merge.prev_dim_scores, new_dim_scores)
    if new_dim_scores:
        _show_low_dimension_hints(new_dim_scores)
        _show_subjective_paths(
            runtime.state,
            new_dim_scores,
            threshold=target_value,
            target_strict_score=target_value,
        )

    _show_score_integrity(runtime.state, merge.diff)
    warnings, narrative = _show_post_scan_analysis(
        merge.diff,
        runtime.state,
        runtime.lang,
        target_strict_score=target_value,
    )
    persist_reminder_history(runtime, narrative)

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
        query_file=QUERY_FILE,
    )

    badge_path = emit_scorecard_badge(args, runtime.config, runtime.state)
    _print_llm_summary(runtime.state, badge_path, narrative, merge.diff)


__all__ = [
    "_audit_excluded_dirs",
    "_collect_codebase_metrics",
    "_effective_include_slow",
    "_format_delta",
    "_resolve_scan_profile",
    "_show_diff_summary",
    "_show_dimension_deltas",
    "_show_post_scan_analysis",
    "_show_score_delta",
    "_show_strict_target_progress",
    "_warn_explicit_lang_with_no_files",
    "cmd_scan",
]
