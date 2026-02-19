"""next command: show next highest-priority queue items."""

from __future__ import annotations

from desloppify import state as state_mod
from desloppify import utils as utils_mod
from desloppify.app.commands import next_output as next_output_mod
from desloppify.app.commands import next_render as next_render_mod
from desloppify.app.commands.helpers.lang import resolve_lang
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.score import target_strict_score_from_config
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.app.output.scorecard_parts.projection import (
    scorecard_dimensions_payload,
)
from desloppify.engine.work_queue_internal.core import (
    QueueBuildOptions,
    build_work_queue,
)
from desloppify.intelligence.narrative import NarrativeContext, compute_narrative
from desloppify.utils import colorize


def _scorecard_subjective(
    state_or_dim_scores: dict,
    dim_scores: dict | None = None,
) -> list[dict]:
    """Return scorecard-aligned subjective entries for current dimension scores."""
    return next_render_mod.scorecard_subjective(state_or_dim_scores, dim_scores)


def _low_subjective_dimensions(
    state_or_dim_scores: dict,
    dim_scores: dict | None = None,
    *,
    threshold: float = 95.0,
) -> list[tuple[str, float, int]]:
    """Return assessed scorecard-subjective entries below the threshold."""
    if dim_scores is None:
        dim_scores = state_or_dim_scores
        state = {"dimension_scores": dim_scores}
    else:
        state = state_or_dim_scores
    low: list[tuple[str, float, int]] = []
    for entry in _scorecard_subjective(state, dim_scores):
        if entry.get("placeholder"):
            continue
        strict_val = float(entry.get("strict", entry.get("score", 100.0)))
        if strict_val < threshold:
            low.append(
                (
                    str(entry.get("name", "Subjective")),
                    strict_val,
                    int(entry.get("issues", 0)),
                )
            )
    low.sort(key=lambda item: item[1])
    return low


def cmd_next(args) -> None:
    """Show next highest-priority queue items."""
    runtime = command_runtime(args)
    state = runtime.state
    config = runtime.config
    if not require_completed_scan(state):
        return

    stale_warning = utils_mod.check_tool_staleness(state)
    if stale_warning:
        print(colorize(f"  {stale_warning}", "yellow"))

    _get_items(args, state, config)


def _get_items(args, state: dict, config: dict) -> None:
    tier = getattr(args, "tier", None)
    count = getattr(args, "count", 1) or 1
    scope = getattr(args, "scope", None)
    status = getattr(args, "status", "open")
    group = getattr(args, "group", "item")
    output_format = getattr(args, "format", "terminal")
    explain = bool(getattr(args, "explain", False))
    no_tier_fallback = bool(getattr(args, "no_tier_fallback", False))

    target_strict = target_strict_score_from_config(config, fallback=95.0)

    queue = build_work_queue(
        state,
        options=QueueBuildOptions(
            tier=tier,
            count=count,
            scan_path=state.get("scan_path"),
            scope=scope,
            status=status,
            include_subjective=True,
            subjective_threshold=target_strict,
            no_tier_fallback=no_tier_fallback,
            explain=explain,
        ),
    )
    items = queue.get("items", [])

    lang = resolve_lang(args)
    lang_name = lang.name if lang else None
    narrative = compute_narrative(
        state,
        context=NarrativeContext(lang=lang_name, command="next"),
    )

    payload = next_output_mod.build_query_payload(
        queue, items, command="next", narrative=narrative
    )
    payload["overall_score"] = state_mod.get_overall_score(state)
    payload["objective_score"] = state_mod.get_objective_score(state)
    payload["strict_score"] = state_mod.get_strict_score(state)
    payload["scorecard_dimensions"] = scorecard_dimensions_payload(
        state,
        dim_scores=state.get("dimension_scores", {}),
    )
    payload["subjective_measures"] = [
        row for row in payload["scorecard_dimensions"] if row.get("subjective")
    ]
    write_query(payload)

    output_file = getattr(args, "output", None)
    if output_file:
        if next_output_mod.write_output_file(
            output_file,
            payload,
            len(items),
            safe_write_text_fn=utils_mod.safe_write_text,
            colorize_fn=colorize,
        ):
            return
        raise SystemExit(1)

    if next_output_mod.emit_non_terminal_output(output_format, payload, items):
        return

    next_render_mod.render_queue_header(queue, explain)
    strict_score = state_mod.get_strict_score(state)
    if next_render_mod.show_empty_queue(queue, tier, strict_score):
        return

    dim_scores = state.get("dimension_scores", {})
    findings_scoped = state_mod.path_scoped_findings(
        state.get("findings", {}),
        state.get("scan_path"),
    )
    next_render_mod.render_terminal_items(
        items, dim_scores, findings_scoped, group=group, explain=explain
    )
    next_render_mod.render_single_item_resolution_hint(items)
    next_render_mod.render_followup_nudges(
        state,
        dim_scores,
        findings_scoped,
        strict_score=strict_score,
        target_strict_score=target_strict,
    )
    print()


__all__ = ["_low_subjective_dimensions", "cmd_next"]
