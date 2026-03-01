"""show command: dig into findings by file, directory, detector, or pattern."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.score import target_strict_score_from_config
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.core.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.intelligence.narrative import NarrativeContext, compute_narrative
from desloppify.core.output_api import colorize
from desloppify.core.skill_docs import check_skill_version
from desloppify.core.tooling import check_config_staleness, check_tool_staleness
from desloppify.engine.concerns import generate_concerns
from desloppify.engine.plan import load_plan

from .payload import ShowPayloadMeta, build_show_payload
from .render import (
    render_findings,
    show_agent_plan,
    show_subjective_followup,
    write_show_output_file,
)
from .scope import (
    _detector_names_hint,
    _lookup_dimension_score,
    load_matches,
    resolve_entity,
    resolve_noise,
    resolve_show_scope,
)


def _show_concerns(state: dict, lang_name: str | None) -> None:
    """Render current design concerns from mechanical signals."""
    concerns = generate_concerns(state, lang_name=lang_name)
    if not concerns:
        print(colorize("  No design concerns detected.", "green"))
        return

    print(colorize(f"\n  {len(concerns)} design concern(s):\n", "bold"))
    dismissals = state.get("concern_dismissals", {})

    for i, c in enumerate(concerns, 1):
        print(colorize(f"  {i}. [{c.type}] {c.file}", "cyan"))
        print(f"     {c.summary}")
        for ev in c.evidence:
            print(colorize(f"       - {ev}", "dim"))
        print(colorize(f"     ? {c.question}", "yellow"))

        # Check if previously dismissed (but resurface due to changed findings).
        prev = dismissals.get(c.fingerprint)
        if isinstance(prev, dict):
            reasoning = prev.get("reasoning", "")
            if reasoning:
                print(colorize(f"     (previously dismissed: {reasoning})", "dim"))
        print()


def _print_dimension_score(dim_data: dict, display_name: str) -> None:
    """Print the health/strict score line for a dimension if available."""
    score_val = dim_data.get("score") if isinstance(dim_data, dict) else None
    strict_val = (
        dim_data.get("strict", score_val) if isinstance(dim_data, dict) else None
    )
    if score_val is not None:
        print(
            colorize(
                f"  {display_name}: {score_val:.1f}% health (strict: {strict_val:.1f}%)",
                "bold",
            )
        )


def _render_subjective_dimension(
    state: dict,
    config: dict,
    entity,
    pattern_raw: str,
) -> None:
    """Show score + subjective explanation for a subjective dimension."""
    lowered = pattern_raw.strip().lower().replace(" ", "_") if pattern_raw else ""
    dim_data, display_name = _lookup_dimension_score(state, entity.display_name)
    _print_dimension_score(dim_data, display_name)
    print(
        colorize(
            f"  '{pattern_raw.strip()}' is a subjective dimension "
            "— its score comes from design reviews, not code findings.",
            "yellow",
        )
    )
    # Count open review findings tagged with this dimension
    dim_reviews = [
        f
        for f in (state.get("findings") or {}).values()
        if f.get("detector") == "review"
        and f.get("status") == "open"
        and lowered
        in str(f.get("detail", {}).get("dimension", "")).lower().replace(" ", "_")
    ]
    if dim_reviews:
        print(
            colorize(
                f"  {len(dim_reviews)} open review finding(s). "
                "Run `show review --status open`.",
                "dim",
            )
        )
    show_subjective_followup(
        state,
        target_strict_score_from_config(config, fallback=95.0),
    )


def _render_clean_mechanical_dimension(state: dict, entity) -> None:
    """Show score + 'no open findings' for a mechanical dimension with zero findings."""
    dim_data, display_name = _lookup_dimension_score(state, entity.display_name)
    _print_dimension_score(dim_data, display_name)
    det_list = ", ".join(entity.detectors) if entity.detectors else "none"
    print(
        colorize(
            f"  No open findings for {entity.display_name}. Detectors: {det_list}",
            "green",
        )
    )


def _load_dimension_findings(
    state: dict,
    entity,
    status_filter: str,
) -> list[dict]:
    """Load findings for all detectors in a mechanical dimension."""
    all_matches: list[dict] = []
    for detector in entity.detectors:
        matches = load_matches(
            state, scope=detector, status_filter=status_filter, chronic=False
        )
        all_matches.extend(matches)
    # Deduplicate by finding ID
    seen: set[str] = set()
    unique: list[dict] = []
    for item in all_matches:
        fid = item.get("id", "")
        if fid not in seen:
            seen.add(fid)
            unique.append(item)
    return unique


def _render_no_matches(entity, pattern, status_filter, narrative, state, config):
    """Handle the no-findings case: subjective views show dashboard, others show hint."""
    print(
        colorize(f"No {status_filter} findings matching: {pattern}", "yellow")
    )
    write_query(
        {
            "command": "show",
            "query": pattern,
            "status_filter": status_filter,
            "total": 0,
            "findings": [],
            "narrative": narrative,
        }
    )
    if entity.kind == "special_view":
        show_subjective_followup(
            state,
            target_strict_score_from_config(config, fallback=95.0),
        )
    else:
        hint = _detector_names_hint()
        print(
            colorize(
                f"  Try: show <detector>, show <file>, or show subjective. "
                f"Detectors: {hint}",
                "dim",
            )
        )


def _render_subjective_views_guide(entity) -> None:
    """Print 'Related views' hint after subjective/subjective_review output."""
    if entity.kind == "special_view" and entity.pattern.strip().lower() in (
        "subjective",
        "subjective_review",
    ):
        print(colorize("  Related views:", "dim"))
        print(colorize("    `show review --status open`            Per-file design review findings", "dim"))
        print(colorize("    `show subjective_review --status open`  Files needing re-review", "dim"))


def cmd_show(args: argparse.Namespace) -> None:
    """Show all findings for a file, directory, detector, or pattern."""
    runtime = command_runtime(args)
    state = runtime.state
    config = runtime.config

    if not require_completed_scan(state):
        return

    stale_warning = check_tool_staleness(state)
    if stale_warning:
        print(colorize(f"  {stale_warning}", "yellow"))
    skill_warning = check_skill_version()
    if skill_warning:
        print(colorize(f"  {skill_warning}", "yellow"))
    config_warning = check_config_staleness(config)
    if config_warning:
        print(colorize(f"  {config_warning}", "yellow"))

    pattern_raw = getattr(args, "pattern", "")
    show_code = getattr(args, "code", False)
    chronic = getattr(args, "chronic", False)
    ok, pattern, status_filter, scope = resolve_show_scope(args)
    if not ok or pattern is None:
        return

    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(
        state,
        context=NarrativeContext(lang=lang_name, command="show"),
    )

    # --- Entity resolution: classify what the user asked for ---
    entity = resolve_entity(pattern, state)

    # Dispatch: concerns special view
    if entity.kind == "special_view" and entity.pattern.strip().lower() == "concerns":
        _show_concerns(state, lang_name)
        return

    # Dispatch: subjective dimension
    if entity.kind == "dimension" and entity.is_subjective:
        _render_subjective_dimension(state, config, entity, pattern_raw)
        return

    # Dispatch: mechanical dimension
    if entity.kind == "dimension" and not entity.is_subjective:
        matches = _load_dimension_findings(state, entity, status_filter)
        if not matches:
            _render_clean_mechanical_dimension(state, entity)
            return
        pattern = entity.display_name
    else:
        # All other kinds: existing load_matches path
        matches = load_matches(
            state, scope=scope, status_filter=status_filter, chronic=chronic
        )

    if not matches:
        _render_no_matches(entity, pattern, status_filter, narrative, state, config)
        return

    (
        surfaced_matches,
        hidden_by_detector,
        noise_budget,
        global_noise_budget,
        budget_warning,
    ) = resolve_noise(
        config,
        matches,
    )
    hidden_total = sum(hidden_by_detector.values())

    payload = build_show_payload(
        surfaced_matches,
        pattern,
        status_filter,
        ShowPayloadMeta(
            total_matches=len(matches),
            hidden_by_detector=hidden_by_detector,
            noise_budget=noise_budget,
            global_noise_budget=global_noise_budget,
        ),
    )
    write_query({"command": "show", **payload, "narrative": narrative})

    output_file = getattr(args, "output", None)
    if output_file:
        if write_show_output_file(output_file, payload, len(surfaced_matches)):
            return
        raise SystemExit(1)

    top = getattr(args, "top", 20) or 20
    render_findings(
        surfaced_matches,
        pattern=pattern,
        status_filter=status_filter,
        show_code=show_code,
        top=top,
        hidden_by_detector=hidden_by_detector,
        hidden_total=hidden_total,
        noise_budget=noise_budget,
        global_noise_budget=global_noise_budget,
        budget_warning=budget_warning,
    )
    try:
        _plan = load_plan()
        _plan_active = _plan if (_plan.get("queue_order") or _plan.get("clusters")) else None
    except PLAN_LOAD_EXCEPTIONS:
        _plan_active = None
    show_agent_plan(narrative, surfaced_matches, plan=_plan_active)
    show_subjective_followup(
        state,
        target_strict_score_from_config(config, fallback=95.0),
    )

    _render_subjective_views_guide(entity)


__all__ = ["cmd_show"]
