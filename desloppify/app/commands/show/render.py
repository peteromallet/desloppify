"""Rendering and output helpers for show command."""

from __future__ import annotations

import json
from collections import defaultdict

from desloppify.app.commands.helpers.rendering import (
    print_agent_plan as render_plan_with_living_plan,
    print_ranked_actions,
)
from desloppify.app.commands.helpers.subjective import print_subjective_followup
from desloppify.app.commands.scan import (
    scan_reporting_dimensions as reporting_dimensions_mod,
)
from desloppify.core.output_api import colorize
from desloppify.core.paths_api import read_code_snippet
from desloppify.core.fallbacks import print_write_error
from desloppify.core.enums import canonical_finding_status
from desloppify.engine.planning import CONFIDENCE_ORDER
from desloppify.core.discovery_api import safe_write_text

from .formatting import format_detail


def write_show_output_file(output_file: str, payload: dict, surfaced_count: int) -> bool:
    """Write serialized show payload to file."""
    try:
        safe_write_text(output_file, json.dumps(payload, indent=2) + "\n")
        print(colorize(f"Wrote {surfaced_count} findings to {output_file}", "green"))
    except OSError as exc:
        payload["output_error"] = str(exc)
        print_write_error(output_file, exc, label="show output")
        return False
    return True


def group_matches_by_file(matches: list[dict]) -> list[tuple[str, list]]:
    """Group findings by file and sort by descending count."""
    by_file: dict[str, list] = defaultdict(list)
    for finding in matches:
        by_file[finding["file"]].append(finding)
    return sorted(by_file.items(), key=lambda item: -len(item[1]))


def _print_single_finding(finding: dict, *, show_code: bool) -> None:
    """Render a single finding to terminal."""
    normalized_status = canonical_finding_status(finding.get("status"))
    status_icon = {
        "open": "○",
        "fixed": "✓",
        "wontfix": "—",
        "false_positive": "✗",
        "auto_resolved": "◌",
    }.get(normalized_status, "?")
    zone = finding.get("zone", "production")
    zone_tag = colorize(f" [{zone}]", "dim") if zone != "production" else ""
    print(
        f"    {status_icon} T{finding['tier']} [{finding['confidence']}] {finding['summary']}{zone_tag}"
    )

    detail_parts = format_detail(finding.get("detail", {}))
    if detail_parts:
        print(colorize(f"      {' · '.join(detail_parts)}", "dim"))
    if show_code:
        detail = finding.get("detail", {})
        target_line = (
            detail.get("line") or (detail.get("lines", [None]) or [None])[0]
        )
        if target_line and finding["file"] not in (".", ""):
            snippet = read_code_snippet(finding["file"], target_line)
            if snippet:
                print(snippet)
    if finding.get("reopen_count", 0) >= 2:
        print(
            colorize(
                f"      ⟳ reopened {finding['reopen_count']} times — fix properly or wontfix",
                "red",
            )
        )
    if finding.get("note"):
        print(colorize(f"      note: {finding['note']}", "dim"))
    print(colorize(f"      {finding['id']}", "dim"))


def render_findings(
    matches: list[dict],
    *,
    pattern: str,
    status_filter: str,
    show_code: bool,
    top: int,
    hidden_by_detector: dict[str, int],
    hidden_total: int,
    noise_budget: int,
    global_noise_budget: int,
    budget_warning: str | None,
) -> None:
    """Render grouped findings and rollup summary to terminal."""
    sorted_files = group_matches_by_file(matches)
    print(
        colorize(
            f"\n  {len(matches)} {status_filter} findings matching '{pattern}'\n",
            "bold",
        )
    )
    if budget_warning:
        print(colorize(f"  {budget_warning}\n", "yellow"))
    if hidden_total:
        global_label = (
            f", {global_noise_budget} global" if global_noise_budget > 0 else ""
        )
        hidden_parts = ", ".join(
            f"{det}: +{count}" for det, count in hidden_by_detector.items()
        )
        print(
            colorize(
                (
                    "  Noise budget: "
                    f"{noise_budget}/detector{global_label} "
                    f"({hidden_total} hidden: {hidden_parts})\n"
                ),
                "dim",
            )
        )

    shown_files = sorted_files[:top]
    remaining_files = sorted_files[top:]
    remaining_findings = sum(len(files) for _, files in remaining_files)

    for filepath, findings in shown_files:
        findings.sort(
            key=lambda finding: (
                finding["tier"],
                CONFIDENCE_ORDER.get(finding["confidence"], 9),
            )
        )
        display_path = "Codebase-wide" if filepath == "." else filepath
        print(
            colorize(f"  {display_path}", "cyan")
            + colorize(f"  ({len(findings)} findings)", "dim")
        )

        for finding in findings:
            _print_single_finding(finding, show_code=show_code)
        print()

    if remaining_findings:
        print(
            colorize(
                (
                    f"  ... and {len(remaining_files)} more files "
                    f"({remaining_findings} findings). "
                    f"Use --top {top + 20} to see more.\n"
                ),
                "dim",
            )
        )

    by_detector: dict[str, int] = defaultdict(int)
    by_tier: dict[int, int] = defaultdict(int)
    for finding in matches:
        by_detector[finding["detector"]] += 1
        by_tier[finding["tier"]] += 1

    print(colorize("  Summary:", "bold"))
    print(
        colorize(
            (
                "    By tier:     "
                + ", ".join(
                    f"T{tier}:{count}" for tier, count in sorted(by_tier.items())
                )
            ),
            "dim",
        )
    )
    print(
        colorize(
            (
                "    By detector: "
                + ", ".join(
                    f"{detector}:{count}"
                    for detector, count in sorted(
                        by_detector.items(), key=lambda item: -item[1]
                    )
                )
            ),
            "dim",
        )
    )
    if hidden_total:
        print(
            colorize(
                (
                    "    Hidden:      "
                    + ", ".join(
                        f"{detector}:+{count}"
                        for detector, count in hidden_by_detector.items()
                    )
                ),
                "dim",
            )
        )
    print()


def show_agent_plan(
    narrative: dict, matches: list[dict], *, plan: dict | None = None
) -> None:
    """Render a compact plan from current findings and narrative actions.

    When a living *plan* is active, renders plan focus/progress instead.
    """
    if plan and (plan.get("queue_order") or plan.get("clusters")):
        render_plan_with_living_plan(
            [],
            plan=plan,
            header="  AGENT PLAN (use `desloppify next` to see your next task):",
        )
        return

    actions = narrative.get("actions", [])
    if not actions and not matches:
        return

    print(
        colorize(
            "  AGENT PLAN (use `desloppify next --count 20` to inspect more items):",
            "yellow",
        )
    )
    if actions:
        top = actions[0]
        print(
            colorize(
                f"  Agent focus: `{top['command']}` — {top['description']}",
                "cyan",
            )
        )
    elif matches:
        first = matches[0]
        print(
            colorize(
                "  Agent focus: `desloppify next --count 20` — "
                f"inspect and resolve `{first.get('id', '')}`",
                "cyan",
            )
        )

    if print_ranked_actions(actions):
        print()


def show_subjective_followup(state: dict, target_strict_score: float) -> None:
    """Show subjective follow-up guidance for the current state."""
    dim_scores = state.get("dimension_scores", {}) or {}
    if not dim_scores:
        return

    subjective = reporting_dimensions_mod.scorecard_subjective_entries(
        state,
        dim_scores=dim_scores,
    )
    if not subjective:
        return

    followup = reporting_dimensions_mod.build_subjective_followup(
        state,
        subjective,
        threshold=target_strict_score,
        max_quality_items=3,
        max_integrity_items=5,
    )
    if print_subjective_followup(followup):
        print()


__all__ = [
    "group_matches_by_file",
    "render_findings",
    "show_agent_plan",
    "show_subjective_followup",
    "write_show_output_file",
]
