"""scan command: run all detectors, update persistent state, show diff."""

from __future__ import annotations

import argparse
import copy
from pathlib import Path

from desloppify.app.commands.helpers.by_language import detect_present_languages
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import query_file_path
from desloppify.app.commands.helpers.runtime_options import (
    LangRuntimeOptionsError,
    print_lang_runtime_options_error,
)
from desloppify.base.config import target_strict_score_from_config
from desloppify.app.commands.scan.artifacts import (
    build_scan_query_payload,
    emit_scorecard_badge,
)
from desloppify.app.commands.scan.orchestrator import ScanOrchestrator
from desloppify.app.commands.scan.plan_nudge import (
    print_plan_workflow_nudge as _print_plan_workflow_nudge_impl,
)
from desloppify.app.commands.scan.reporting.agent_context import (
    auto_update_skill,
    print_llm_summary,
)
from desloppify.app.commands.scan.reporting.dimensions import (
    show_dimension_deltas,
    show_score_model_breakdown,
    show_scorecard_subjective_measures,
)
from desloppify.app.commands.scan.reporting.integrity_report import (
    show_post_scan_analysis,
)
from desloppify.app.commands.scan.reporting.summary import (  # noqa: F401
    show_diff_summary,
    show_score_delta,
)
from desloppify.app.commands.scan.workflow import (
    ScanStateContractError,
    merge_scan_results,
    persist_reminder_history,
    prepare_scan_runtime,
    resolve_noise_snapshot,
    run_scan_generation,
)
from desloppify.base.exception_sets import CommandError
from desloppify.base.discovery.paths import get_project_root
from desloppify.base.output.terminal import colorize
from desloppify.base.search.query import write_query

from . import preflight as scan_preflight_mod


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
    """Print fast-scan and noise budget visibility hints.

    Side-effect only: conditionally prints scan-mode warnings to stdout.
    All branches may be skipped (full scan, no noise budget hit, no hidden
    issues), so the function can legitimately produce no output.
    """
    if not effective_include_slow:
        print(colorize("  * Fast scan — slow phases (duplicates) skipped", "yellow"))
    if noise.budget_warning:
        print(colorize(f"  * {noise.budget_warning}", "yellow"))
    if noise.hidden_total:
        print(
            colorize(
                f"  * {noise.hidden_total} issues hidden (showing {noise.noise_budget}/detector). "
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


def _print_plan_workflow_nudge(state: dict) -> None:
    _print_plan_workflow_nudge_impl(state)


def cmd_scan(args: argparse.Namespace) -> None:
    """Run all detectors, update persistent state, show diff."""
    if getattr(args, "by_language", False):
        _cmd_scan_by_language(args)
        return
    scan_preflight_mod.scan_queue_preflight(args)
    try:
        runtime = prepare_scan_runtime(args)
    except LangRuntimeOptionsError as exc:
        lang_cfg = resolve_lang(args)
        lang_name = lang_cfg.name if lang_cfg else "selected"
        print_lang_runtime_options_error(exc, lang_name=lang_name)
        raise CommandError(str(exc), exit_code=2) from exc
    except ScanStateContractError as exc:
        raise CommandError(str(exc), exit_code=2) from exc
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
    _show_coverage_preflight(runtime)

    issues, potentials, codebase_metrics = orchestrator.generate()
    merge = orchestrator.merge(issues, potentials, codebase_metrics)
    _print_scan_complete_banner()

    noise = orchestrator.noise_snapshot()

    target_value = target_strict_score_from_config(runtime.config)

    show_diff_summary(merge.diff)
    show_score_delta(
        runtime.state,
        merge.prev_overall,
        merge.prev_objective,
        merge.prev_strict,
        merge.prev_verified,
        target_strict=target_value,
    )
    # Nudge: if plan_start_scores was just seeded, tell the agent about the lifecycle.
    _print_plan_workflow_nudge(runtime.state)
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

    badge_path, _badge_result = emit_scorecard_badge(args, runtime.config, runtime.state)
    print_llm_summary(runtime.state, badge_path, narrative, merge.diff)
    auto_update_skill()


def _cmd_scan_by_language(args: argparse.Namespace) -> None:
    path = Path(getattr(args, "path", None) or get_project_root())
    languages = detect_present_languages(path)
    if not languages:
        raise CommandError("No languages detected under scan path.", exit_code=2)
    print(colorize("\nDesloppify Scan by Language\n", "bold"))
    print(
        colorize(
            "  Aggregate policy: states stay independent; status averages scanned languages equally.",
            "dim",
        )
    )
    for lang_name in languages:
        print(colorize(f"\nLanguage: {lang_name}", "bold"))
        lang_args = copy.copy(args)
        lang_args.by_language = False
        lang_args.lang = lang_name
        lang_args.state = None
        # The CLI builds a runtime before dispatch. Rebuild it for each language.
        lang_args.runtime = None
        cmd_scan(lang_args)


__all__ = [
    "cmd_scan",
]
