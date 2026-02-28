"""scan command: run all detectors, update persistent state, show diff."""

from __future__ import annotations

import argparse
import copy

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
from desloppify.app.commands.scan.scan_reporting_by_language import (
    show_per_language_score_blocks,
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
    ScanRuntime,
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


def _compute_per_language_dimension_scores(
    runtime: ScanRuntime,
    lang_names: list[str],
    *,
    target_score: float,
) -> dict[str, dict]:
    """Run scan generation per language and compute per-language dimension scores.

    Returns a dict ``{lang_name: dim_scores}`` where *dim_scores* is the
    ``dimension_scores`` dict produced by a temporary single-language merge.
    The temporary state used for scoring is discarded; only the
    ``dimension_scores`` are returned.
    """
    from desloppify import state as state_mod
    from desloppify.languages._framework.resolution import get_lang
    from desloppify.languages._framework.runtime import LangRunOverrides, make_lang_run
    from desloppify.app.commands.helpers.lang import resolve_lang_settings

    results: dict[str, dict] = {}

    for lang_name in lang_names:
        try:
            lang_cfg = get_lang(lang_name)
        except (ValueError, ImportError):
            continue

        lang_settings = resolve_lang_settings(runtime.config, lang_cfg)
        try:
            lang_run = make_lang_run(
                lang_cfg,
                overrides=LangRunOverrides(
                    review_cache=runtime.state.get("review_cache", {}),
                    review_max_age_days=runtime.config.get("review_max_age_days", 30),
                    runtime_settings=lang_settings,
                    runtime_options={},
                    large_threshold_override=runtime.config.get("large_files_threshold", 0),
                    props_threshold_override=runtime.config.get("props_threshold", 0),
                ),
            )
        except Exception:
            continue

        lang_runtime = ScanRuntime(
            args=runtime.args,
            state_path=runtime.state_path,
            state=runtime.state,
            path=runtime.path,
            config=runtime.config,
            lang=lang_run,
            lang_label=f" ({lang_name})",
            profile=runtime.profile,
            effective_include_slow=runtime.effective_include_slow,
            zone_overrides=runtime.zone_overrides,
        )

        try:
            lang_findings, lang_potentials, _ = run_scan_generation(lang_runtime)
        except Exception:
            continue

        # Build a lightweight temporary state to compute dimension scores without
        # touching the real persisted state.
        temp_state: dict = {
            "version": 1,
            "created": state_mod.utc_now(),
            "last_scan": None,
            "scan_count": 0,
            "overall_score": 0,
            "objective_score": 0,
            "strict_score": 0,
            "verified_strict_score": 0,
            "stats": {},
            "findings": {},
            "scan_coverage": {},
            "score_confidence": {},
            "subjective_integrity": {},
            "subjective_assessments": {},
            "scan_history": [{"lang": lang_name}],
        }
        state_mod.ensure_state_defaults(temp_state)

        try:
            state_mod.merge_scan(
                temp_state,
                lang_findings,
                options=state_mod.MergeScanOptions(
                    lang=lang_name,
                    scan_path=None,
                    force_resolve=False,
                    exclude=[],
                    potentials=lang_potentials,
                    codebase_metrics=None,
                    include_slow=runtime.effective_include_slow,
                    ignore=runtime.config.get("ignore", []),
                    subjective_integrity_target=target_score,
                ),
            )
        except Exception:
            continue

        lang_dim_scores = dict(temp_state.get("dimension_scores", {}))
        if lang_dim_scores:
            # Attach aggregate scores for display
            lang_dim_scores["_aggregate_scores"] = {
                "overall_score": temp_state.get("overall_score"),
                "objective_score": temp_state.get("objective_score"),
                "strict_score": temp_state.get("strict_score"),
                "verified_strict_score": temp_state.get("verified_strict_score"),
            }
            results[lang_name] = lang_dim_scores

    return results


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

    by_language = getattr(args, "by_language", False)
    if by_language:
        _run_by_language_phase(runtime, args, target_value)

    badge_emit = emit_scorecard_badge(args, runtime.config, runtime.state)
    if isinstance(badge_emit, tuple):
        badge_path, _badge_result = badge_emit
    else:  # Backward-compatible shape for monkeypatched tests.
        badge_path = badge_emit
    _print_llm_summary(runtime.state, badge_path, narrative, merge.diff)
    auto_update_skill()


def _run_by_language_phase(
    runtime: ScanRuntime,
    args: argparse.Namespace,
    target_value: float,
) -> None:
    """Compute + store per-language dimension scores, print output, emit per-lang badges."""
    from desloppify.languages._framework.resolution import discover_repo_languages
    from desloppify import state as state_mod

    detected = discover_repo_languages(runtime.path)
    if len(detected) < 2:
        print(
            colorize(
                "  --by-language: fewer than 2 languages detected — showing aggregate only.",
                "yellow",
            )
        )
        return

    lang_names = list(detected.keys())
    print(
        colorize(
            f"  --by-language: {len(lang_names)} languages detected: "
            + ", ".join(lang_names),
            "dim",
        )
    )

    per_lang_scores = _compute_per_language_dimension_scores(
        runtime,
        lang_names,
        target_score=target_value,
    )

    if per_lang_scores:
        runtime.state["dimension_scores_by_language"] = per_lang_scores
        # Persist updated state with per-language data
        state_mod.save_state(
            runtime.state,
            runtime.state_path,
            subjective_integrity_target=target_value,
        )
        print()
        show_per_language_score_blocks(runtime.state, show_aggregate=True)

    # Generate per-language scorecard images
    _emit_per_language_badges(args, runtime.config, runtime.state, per_lang_scores)


def _emit_per_language_badges(
    args: argparse.Namespace,
    config: dict,
    state: dict,
    per_lang_scores: dict[str, dict],
) -> None:
    """Generate one scorecard PNG per language when badge generation is enabled."""
    import importlib
    import os
    from pathlib import Path
    from desloppify.core._internal.text_utils import PROJECT_ROOT

    if getattr(args, "no_badge", False):
        return
    if not config.get("generate_scorecard", True):
        return
    if os.environ.get("DESLOPPIFY_NO_BADGE", "").lower() in ("1", "true", "yes"):
        return

    try:
        scorecard_module = importlib.import_module("desloppify.app.output.scorecard")
    except ImportError:
        return

    generate_scorecard = getattr(scorecard_module, "generate_scorecard", None)
    if not callable(generate_scorecard):
        return

    badge_path_template = (
        getattr(args, "badge_path", None)
        or config.get("badge_path")
        or os.environ.get("DESLOPPIFY_BADGE_PATH", "scorecard.png")
    )

    for lang_name, lang_dim_scores in per_lang_scores.items():
        # Expand {lang} placeholder or insert language suffix before extension
        template = str(badge_path_template)
        if "{lang}" in template:
            lang_badge_path_str = template.replace("{lang}", lang_name)
        else:
            stem, _, ext = template.rpartition(".")
            lang_badge_path_str = f"{stem}-{lang_name}.{ext}" if stem else f"{template}-{lang_name}"

        lang_badge_path = Path(lang_badge_path_str)
        if not lang_badge_path.is_absolute() and not lang_badge_path.root:
            lang_badge_path = PROJECT_ROOT / lang_badge_path

        try:
            generate_scorecard(state, lang_badge_path, language=lang_name)
            try:
                rel_path = str(lang_badge_path.relative_to(PROJECT_ROOT))
            except ValueError:
                rel_path = str(lang_badge_path)
            print(colorize(f"  Scorecard ({lang_name}) → {rel_path}", "dim"))
        except Exception as exc:
            print(colorize(f"  ⚠ Could not generate {lang_name} scorecard: {exc}", "yellow"))


__all__ = [
    "cmd_scan",
]
