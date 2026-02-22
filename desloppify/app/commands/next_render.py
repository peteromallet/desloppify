"""Terminal rendering helpers for the `next` command."""

from __future__ import annotations

from desloppify import scoring as scoring_mod
from desloppify import utils as utils_mod
from desloppify.app.commands.helpers.subjective import print_subjective_followup
from desloppify.app.commands.scan.scan_reporting_subjective import (
    build_subjective_followup,
)
from desloppify.app.output.scorecard_parts.projection import (
    scorecard_subjective_entries,
)
from desloppify.engine.work_queue import ATTEST_EXAMPLE, group_queue_items
from desloppify.intelligence.integrity import (
    is_holistic_subjective_finding,
    subjective_review_open_breakdown,
    unassessed_subjective_dimensions,
)
from desloppify.utils import colorize


def scorecard_subjective(
    state: dict,
    dim_scores: dict,
) -> list[dict]:
    """Return scorecard-aligned subjective entries for current dimension scores."""
    if not dim_scores:
        return []
    return scorecard_subjective_entries(
        state,
        dim_scores=dim_scores,
    )


def subjective_coverage_breakdown(
    findings_scoped: dict,
) -> tuple[int, dict[str, int], dict[str, int]]:
    """Return open subjective-review count plus reason and holistic-reason breakdowns."""
    return subjective_review_open_breakdown(findings_scoped)


def _tier_label(tier: int) -> str:
    return f"T{tier}"


def _render_tier_navigator(queue: dict) -> None:
    counts = queue.get("tier_counts", {})
    print(colorize("\n  Tier Navigator", "bold"))
    print(
        colorize(
            f"    Open: T1:{counts.get(1, 0)} T2:{counts.get(2, 0)} "
            f"T3:{counts.get(3, 0)} T4:{counts.get(4, 0)}",
            "dim",
        )
    )
    print(
        colorize(
            "    Switch: `desloppify next --tier 1` | `desloppify next --tier 2` | "
            "`desloppify next --tier 3` | `desloppify next --tier 4`",
            "dim",
        )
    )


def _render_grouped(items: list[dict], group: str) -> None:
    grouped = group_queue_items(items, group)
    for key, grouped_items in grouped.items():
        print(colorize(f"\n  {key} ({len(grouped_items)})", "cyan"))
        for item in grouped_items:
            tier = int(item.get("effective_tier", item.get("tier", 3)))
            print(
                f"    {_tier_label(tier)} [{item.get('confidence', 'medium')}] {item.get('summary', '')}"
            )


def is_auto_fix_command(command: str | None) -> bool:
    cmd = (command or "").strip()
    return cmd.startswith("desloppify fix ") and "--dry-run" in cmd


def _render_item(
    item: dict, dim_scores: dict, findings_scoped: dict, explain: bool
) -> None:
    tier = int(item.get("effective_tier", item.get("tier", 3)))
    confidence = item.get("confidence", "medium")
    print(colorize(f"  (Tier {tier}, {confidence} confidence)", "bold"))
    print(colorize("  " + "─" * 60, "dim"))
    print(f"  {colorize(item.get('summary', ''), 'yellow')}")

    kind = item.get("kind", "finding")
    if kind == "subjective_dimension":
        detail = item.get("detail", {})
        subjective_score = float(
            detail.get("strict_score", item.get("subjective_score", 100.0))
        )
        print(f"  Dimension: {detail.get('dimension_name', 'unknown')}")
        print(f"  Score: {subjective_score:.1f}% (always queued as T4)")
        print(
            colorize(
                f"  Action: {item.get('primary_command', 'desloppify review --prepare')}",
                "cyan",
            )
        )
        if explain:
            reason = item.get("explain", {}).get(
                "policy",
                "subjective items are fixed at T4 and do not outrank mechanical T1/T2/T3.",
            )
            print(colorize(f"  explain: {reason}", "dim"))
        return

    print(f"  File: {item.get('file', '')}")
    print(colorize(f"  ID:   {item.get('id', '')}", "dim"))

    detail = item.get("detail", {})
    if detail.get("lines"):
        print(f"  Lines: {', '.join(str(line_no) for line_no in detail['lines'][:8])}")
    if detail.get("category"):
        print(f"  Category: {detail['category']}")
    if detail.get("importers") is not None:
        print(f"  Active importers: {detail['importers']}")
    if detail.get("suggestion"):
        print(colorize(f"\n  Suggestion: {detail['suggestion']}", "dim"))

    target_line = detail.get("line") or (detail.get("lines", [None]) or [None])[0]
    if target_line and item.get("file") not in (".", ""):
        snippet = utils_mod.read_code_snippet(item["file"], target_line)
        if snippet:
            print(colorize("\n  Code:", "dim"))
            print(snippet)

    if dim_scores:
        detector = item.get("detector", "")
        dimension = scoring_mod.get_dimension_for_detector(detector)
        if dimension and dimension.name in dim_scores:
            dimension_score = dim_scores[dimension.name]
            strict_val = dimension_score.get("strict", dimension_score["score"])
            print(
                colorize(
                    f"\n  Dimension: {dimension.name} — {dimension_score['score']:.1f}% "
                    f"(strict: {strict_val:.1f}%) "
                    f"({dimension_score['issues']} of {dimension_score['checks']:,} checks failing)",
                    "dim",
                )
            )

    detector_name = item.get("detector", "")
    auto_fix_command = item.get("primary_command")
    if is_auto_fix_command(auto_fix_command):
        similar_count = sum(
            1
            for finding in findings_scoped.values()
            if finding.get("detector") == detector_name and finding["status"] == "open"
        )
        if similar_count > 1:
            print(
                colorize(
                    f"\n  Auto-fixable: {similar_count} similar findings. "
                    f"Run `{auto_fix_command}` to fix all at once.",
                    "cyan",
                )
            )
    if explain:
        explanation = item.get("explain", {})
        count_weight = explanation.get("count", int(detail.get("count", 0) or 0))
        base = (
            f"ranked by tier={tier}, confidence={confidence}, "
            f"count={count_weight}, id={item.get('id', '')}"
        )
        policy = explanation.get("policy")
        if policy:
            base = f"{base}. {policy}"
        print(colorize(f"  explain: {base}", "dim"))


def render_queue_header(queue: dict, explain: bool) -> None:
    _render_tier_navigator(queue)
    if not queue.get("fallback_reason"):
        return
    print(colorize(f"  {queue['fallback_reason']}", "yellow"))
    if not explain:
        return
    available = queue.get("available_tiers", [])
    if available:
        tiers = ", ".join(f"T{tier_num}" for tier_num in available)
        print(colorize(f"  explain: available tiers are {tiers}", "dim"))


def show_empty_queue(queue: dict, tier: int | None, strict: float | None) -> bool:
    if queue.get("items"):
        return False
    suffix = f" Strict score: {strict:.1f}/100" if strict is not None else ""
    print(colorize(f"\n  Nothing to do!{suffix}", "green"))
    if tier is not None:
        print(colorize(f"  Requested tier: T{tier}", "dim"))
        available = queue.get("available_tiers", [])
        if available:
            commands = " | ".join(
                f"desloppify next --tier {tier_num}" for tier_num in available
            )
            print(colorize(f"  Try: {commands}", "dim"))
    return True


def render_terminal_items(
    items: list[dict],
    dim_scores: dict,
    findings_scoped: dict,
    *,
    group: str,
    explain: bool,
) -> None:
    if group != "item":
        _render_grouped(items, group)
        return
    for idx, item in enumerate(items):
        if idx > 0:
            print()
        label = f"  [{idx + 1}/{len(items)}]" if len(items) > 1 else "  Next item"
        print(colorize(label, "bold"))
        _render_item(item, dim_scores, findings_scoped, explain=explain)


def render_single_item_resolution_hint(items: list[dict]) -> None:
    if len(items) != 1 or items[0].get("kind") != "finding":
        return
    item = items[0]
    detector_name = item.get("detector", "")
    if detector_name == "subjective_review":
        print(colorize("\n  Review with:", "dim"))
        primary = item.get(
            "primary_command", "desloppify show subjective_review --status open"
        )
        print(f"    {primary}")
        if is_holistic_subjective_finding(item):
            print("    desloppify review --prepare")
        return

    primary = item.get("primary_command", "")
    if is_auto_fix_command(primary):
        print(colorize("\n  Fix with:", "dim"))
        print(f"    {primary}")
        print(colorize("  Or resolve individually:", "dim"))
    else:
        print(colorize("\n  Resolve with:", "dim"))

    print(
        f'    desloppify resolve fixed "{item["id"]}" --note "<what you did>" '
        f'--attest "{ATTEST_EXAMPLE}"'
    )
    print(
        f'    desloppify resolve wontfix "{item["id"]}" --note "<why>" '
        f'--attest "{ATTEST_EXAMPLE}"'
    )


def render_followup_nudges(
    state: dict,
    dim_scores: dict,
    findings_scoped: dict,
    *,
    strict_score: float | None,
    target_strict_score: float,
) -> None:
    subjective_threshold = target_strict_score
    subjective_entries = scorecard_subjective(state, dim_scores)
    followup = build_subjective_followup(
        state,
        subjective_entries,
        threshold=subjective_threshold,
        max_quality_items=3,
        max_integrity_items=5,
    )
    low_assessed = followup.low_assessed
    unassessed_subjective = unassessed_subjective_dimensions(dim_scores)
    if strict_score is not None:
        gap = round(float(target_strict_score) - float(strict_score), 1)
        if gap > 0:
            print(
                colorize(
                    f"\n  North star: strict {strict_score:.1f}/100 → target {target_strict_score:.1f} (+{gap:.1f} needed)",
                    "cyan",
                )
            )
        else:
            print(
                colorize(
                    f"\n  North star: strict {strict_score:.1f}/100 meets target {target_strict_score:.1f}",
                    "green",
                )
            )
    print_subjective_followup(followup, leading_newline=True)

    coverage_open, coverage_reasons, holistic_reasons = subjective_coverage_breakdown(
        findings_scoped
    )
    holistic_open = sum(holistic_reasons.values())
    if unassessed_subjective or holistic_open > 0:
        bits: list[str] = []
        if unassessed_subjective:
            bits.append("unassessed subjective dimensions")
        if holistic_open > 0:
            bits.append("holistic review stale/missing")
        gap_label = " + ".join(bits)
        print(colorize(f"\n  Subjective integrity gap: {gap_label}", "yellow"))
        print(
            colorize(
                "  Priority: `desloppify review --prepare`", "dim"
            )
        )
        print(
            colorize(
                "  Then import and rerun `desloppify scan` to refresh strict score.",
                "dim",
            )
        )
        if unassessed_subjective:
            rendered = ", ".join(name for name in unassessed_subjective[:3])
            if len(unassessed_subjective) > 3:
                rendered = f"{rendered}, +{len(unassessed_subjective) - 3} more"
            print(colorize(f"  Unassessed (0% placeholder): {rendered}", "dim"))

    open_review = [
        finding
        for finding in findings_scoped.values()
        if finding.get("status") == "open" and finding.get("detector") == "review"
    ]
    if low_assessed and open_review:
        print(
            colorize(
                "  Subjective bottleneck: prioritize `desloppify issues` to move elegance scores.",
                "yellow",
            )
        )

    if coverage_open > 0:
        reason_parts = []
        if coverage_reasons.get("changed", 0) > 0:
            reason_parts.append(f"{coverage_reasons['changed']} changed")
        if coverage_reasons.get("unreviewed", 0) > 0:
            reason_parts.append(f"{coverage_reasons['unreviewed']} unreviewed")
        reason_text = ", ".join(reason_parts) if reason_parts else "stale/unreviewed"
        suffix = "file" if coverage_open == 1 else "files"
        print(
            colorize(
                f"  Subjective coverage debt: {coverage_open} {suffix} ({reason_text})",
                "cyan",
            )
        )
        if holistic_open > 0:
            print(
                colorize(
                    f"  Includes {holistic_open} holistic stale/missing signal(s).",
                    "yellow",
                )
            )
        print(
            colorize(
                "  Triage: `desloppify show subjective_review --status open`", "dim"
            )
        )

    if open_review:
        uninvestigated = sum(
            1
            for finding in open_review
            if not finding.get("detail", {}).get("investigation")
        )
        suffix = f" ({uninvestigated} uninvestigated)" if uninvestigated else ""
        print(
            colorize(
                f"  Also: {len(open_review)} review findings open{suffix}. Run `desloppify issues`.",
                "cyan",
            )
        )
    elif low_assessed or unassessed_subjective or coverage_open > 0:
        print(
            colorize(
                "  Then import review output and rerun `desloppify scan` to refresh subjective scores.",
                "dim",
            )
        )


__all__ = [
    "is_auto_fix_command",
    "render_followup_nudges",
    "render_queue_header",
    "render_single_item_resolution_hint",
    "render_terminal_items",
    "scorecard_subjective",
    "show_empty_queue",
    "subjective_coverage_breakdown",
]
