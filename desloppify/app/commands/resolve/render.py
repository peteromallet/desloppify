"""Terminal rendering helpers for resolve command flows."""

from __future__ import annotations

import argparse
import logging

from desloppify.app.commands.helpers.score_update import print_strict_target_nudge
from desloppify.app.commands.resolve.render_support import (
    print_post_resolve_guidance,
    print_strict_gap_note,
    score_snapshot_or_error,
)
from desloppify.base.config import load_config
from desloppify.base.exception_sets import CommandError, PLAN_LOAD_EXCEPTIONS
from desloppify.base.git_context import detect_git_context
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan_state import get_uncommitted_issues, suggest_commit_message


def _print_resolve_summary(
    *, status: str, all_resolved: list[str], reattributed_count: int = 0
) -> None:
    if reattributed_count:
        print(
            colorize(
                f"\nRe-attributed {reattributed_count} auto-resolved issue(s) as fixed",
                "green",
            )
        )
    verb = "Reopened" if status == "open" else "Resolved"
    print(colorize(f"\n{verb} {len(all_resolved)} issue(s) as {status}:", "green"))
    for fid in all_resolved[:20]:
        print(f"  {fid}")
    if len(all_resolved) > 20:
        print(f"  ... and {len(all_resolved) - 20} more")


def _print_wontfix_batch_warning(
    state: dict,
    *,
    status: str,
    resolved_count: int,
) -> None:
    if status != "wontfix" or resolved_count <= 10:
        return
    work_items = state.get("work_items") or state.get("issues", {})
    wontfix_count = sum(
        1 for issue in work_items.values() if issue["status"] == "wontfix"
    )
    actionable = sum(
        1
        for issue in work_items.values()
        if issue["status"]
        in ("open", "wontfix", "fixed", "auto_resolved", "false_positive")
    )
    wontfix_pct = round(wontfix_count / actionable * 100) if actionable else 0
    print(
        colorize(
            f"\n  ⚠ Wontfix debt is now {wontfix_count} issues ({wontfix_pct}% of actionable).",
            "yellow",
        )
    )
    print(
        colorize(
            '    The strict score reflects this. Run `desloppify show "*" --status wontfix` to review.',
            "dim",
        )
    )


def _delta_suffix(delta: float) -> str:
    if abs(delta) < 0.05:
        return ""
    return f" ({'+' if delta > 0 else ''}{delta:.1f})"


def _print_score_movement(
    *,
    status: str,
    prev_overall: float | None,
    prev_objective: float | None,
    prev_strict: float | None,
    prev_verified: float | None,
    state: dict,
    has_review_issues: bool = False,
    target_strict: float | None = None,
) -> None:
    try:
        new = score_snapshot_or_error(state)
    except CommandError as exc:
        print(colorize(f"\n  {exc.message}", "yellow"))
        return

    overall_delta = new.overall - (prev_overall or 0)
    objective_delta = new.objective - (prev_objective or 0)
    strict_delta = new.strict - (prev_strict or 0)
    verified_delta = new.verified - (prev_verified or 0)
    print(
        f"\n  Scores: overall {new.overall:.1f}/100{_delta_suffix(overall_delta)}"
        + colorize(
            f"  objective {new.objective:.1f}/100{_delta_suffix(objective_delta)}",
            "dim",
        )
        + colorize(f"  strict {new.strict:.1f}/100{_delta_suffix(strict_delta)}", "dim")
        + colorize(
            f"  verified {new.verified:.1f}/100{_delta_suffix(verified_delta)}", "dim"
        )
    )
    if target_strict is not None:
        print_strict_target_nudge(new.strict, target_strict, show_next=False)
    print_strict_gap_note(status, overall=new.overall, strict=new.strict)
    print_post_resolve_guidance(
        status=status,
        has_review_issues=has_review_issues,
        overall_delta=overall_delta,
    )


def _print_subjective_reset_hint(
    *,
    args: argparse.Namespace,
    state: dict,
    all_resolved: list[str],
    prev_subjective_scores: dict[str, float],
) -> None:
    work_items = state.get("work_items") or state.get("issues", {})
    has_review = any(
        work_items.get(fid, {}).get("detector") == "review"
        for fid in all_resolved
    )
    if not has_review or not state.get("subjective_assessments"):
        return

    stale_dims = sorted(
        dim
        for dim in {
            str(
                work_items.get(fid, {}).get("detail", {}).get("dimension", "")
            ).strip()
            for fid in all_resolved
            if work_items.get(fid, {}).get("detector") == "review"
        }
        if dim and dim in (state.get("subjective_assessments") or {})
    )
    if not stale_dims:
        return

    shown = ", ".join(stale_dims[:3])
    if len(stale_dims) > 3:
        shown = f"{shown}, +{len(stale_dims) - 3} more"
    print(
        colorize(
            f"  Subjective scores unchanged — re-run review for updated scores: {shown}",
            "yellow",
        )
    )
    print(
        colorize(
            "  Next subjective step: "
            + (
                "`desloppify review --prepare --dimensions "
                f"{','.join(stale_dims)} --force-review-rerun`"
            ),
            "dim",
        )
    )


def _render_uncommitted_block(uncommitted: list[str], just_resolved: list[str]) -> None:
    """Print the uncommitted issues section."""
    count = len(uncommitted)
    just_set = set(just_resolved)
    print(f"\n  Uncommitted work ({count} resolved issue{'s' if count != 1 else ''}):")
    for fid in uncommitted[:5]:
        marker = colorize("●", "green") if fid in just_set else "○"
        tag = "  (just now)" if fid in just_set else ""
        print(f"    {marker} {fid}{tag}")
    if count > 5:
        print(f"    ... and {count - 5} more")


def _render_committed_block(commit_log: list[dict]) -> None:
    """Print the already-committed section (last 3 commits)."""
    if not commit_log:
        return
    committed_count = sum(len(r.get("issue_ids", [])) for r in commit_log)
    nc = len(commit_log)
    print(f"\n  Already committed ({nc} commit{'s' if nc != 1 else ''}, {committed_count} issue{'s' if committed_count != 1 else ''}):")
    for record in commit_log[-3:]:
        sha = record.get("sha", "?")[:7]
        note = record.get("note", "")
        fc = len(record.get("issue_ids", []))
        note_str = f' — "{note}"' if note else ""
        print(f"    {sha}{note_str} ({fc} issue{'s' if fc != 1 else ''})")


def render_commit_guidance(
    state: dict,
    plan: dict | None,
    just_resolved: list[str],
    status: str,
) -> None:
    """Show commit tracking guidance after a resolve."""
    if status != "fixed" or plan is None:
        return

    try:
        config = load_config()
        if not config.get("commit_tracking_enabled", True):
            return

        git = detect_git_context()
        if not git.available:
            return

        uncommitted = get_uncommitted_issues(plan)
        if not uncommitted:
            return

        pr_number = config.get("commit_pr", 0)

        print(colorize("\n  ── Commit Tracking ──────────────────────────", "dim"))
        print(f"  Branch: {git.branch or '?'}    HEAD: {git.head_sha or '?'}")
        if pr_number:
            print(f"  PR: #{pr_number}")

        _render_uncommitted_block(uncommitted, just_resolved)
        _render_committed_block(plan.get("commit_log", []))

        template = config.get(
            "commit_message_template",
            "desloppify: {status} {count} issue(s) — {summary}",
        )
        msg = suggest_commit_message(plan, template)
        if msg:
            print("\n  Suggested commit message:")
            print(colorize(f'    "{msg}"', "cyan"))

        print(colorize("\n  After committing → `desloppify plan commit-log record`", "dim"))
        print(colorize("  ─────────────────────────────────────────────", "dim"))

    except PLAN_LOAD_EXCEPTIONS:
        logging.getLogger(__name__).debug(
            "commit guidance rendering skipped", exc_info=True,
        )


def _print_next_command(state: dict) -> str:
    work_items = state.get("work_items") or state.get("issues", {})
    remaining = sum(
        1
        for issue in work_items.values()
        if issue["status"] == "open"
        and not issue.get("suppressed")
    )
    next_command = "desloppify scan"
    if remaining > 0:
        suffix = "s" if remaining != 1 else ""
        print(
            colorize(
                f"\n  {remaining} issue{suffix} remaining — run `desloppify next`",
                "dim",
            )
        )
        next_command = "desloppify next"
    print(colorize(f"  Next command: `{next_command}`", "dim"))
    print()
    return next_command
