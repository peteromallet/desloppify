"""CLI handlers for ``plan commit-log`` subcommand family."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from desloppify import state as state_mod
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.base.config import load_config
from desloppify.base.git_context import detect_git_context, update_pr_body
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import (
    append_log_entry,
    commit_tracking_summary,
    filter_issue_ids_by_pattern,
    generate_pr_body,
    get_uncommitted_issues,
    load_plan,
    plan_path_for_state,
    record_commit,
    save_plan,
)


def _cmd_commit_log_status(plan: dict) -> None:
    """Show full commit-log status: uncommitted, committed, git context."""
    git = detect_git_context()
    summary = commit_tracking_summary(plan)

    print(colorize("  Commit Tracking Status", "bold"))
    print(colorize("  " + "─" * 40, "dim"))

    if git.available:
        print(f"  Branch:  {git.branch or '(detached)'}")
        print(f"  HEAD:    {git.head_sha or '?'}")
        if git.has_uncommitted:
            print(colorize("  Working tree has uncommitted changes", "yellow"))
    else:
        print(colorize("  Git: not available", "dim"))

    config = load_config()
    pr = config.get("commit_pr", 0)
    if pr:
        print(f"  PR:      #{pr}")

    uncommitted = get_uncommitted_issues(plan)
    print(f"\n  Uncommitted:  {summary['uncommitted']} issue(s)")
    for fid in uncommitted[:10]:
        print(f"    {fid}")
    if len(uncommitted) > 10:
        print(f"    ... and {len(uncommitted) - 10} more")

    commit_log = plan.get("commit_log", [])
    committed_count = sum(len(r.get("issue_ids", [])) for r in commit_log)
    print(f"  Committed:    {committed_count} issue(s) in {len(commit_log)} commit(s)")

    if not uncommitted and not commit_log:
        print(colorize("\n  No commit tracking data yet.", "dim"))
        print(colorize("  Resolve issues with `desloppify resolve` or `desloppify plan resolve` to start.", "dim"))


def _cmd_commit_log_record(args: argparse.Namespace, plan: dict, plan_file: Path | None = None) -> None:
    """Record a commit: capture HEAD, move uncommitted → committed, update PR."""
    sha = getattr(args, "sha", None)
    branch = getattr(args, "branch", None)
    note = getattr(args, "note", None)
    only_patterns: list[str] | None = getattr(args, "only", None)

    # Auto-detect from git if not overridden
    if not sha or not branch:
        git = detect_git_context()
        if git.available:
            sha = sha or git.head_sha
            branch = branch or git.branch
        elif not sha:
            print(colorize("  Cannot detect HEAD. Use --sha to specify.", "red"))
            return

    # Determine which issues to record
    uncommitted = get_uncommitted_issues(plan)
    if not uncommitted:
        print(colorize("  No uncommitted issues to record.", "yellow"))
        return

    if only_patterns:
        issue_ids = filter_issue_ids_by_pattern(uncommitted, only_patterns)
        if not issue_ids:
            print(colorize("  No uncommitted issues match --only patterns.", "yellow"))
            return
    else:
        issue_ids = None  # record all

    record = record_commit(
        plan,
        sha=sha,
        branch=branch,
        issue_ids=issue_ids,
        note=note,
    )
    append_log_entry(
        plan,
        "commit_record",
        issue_ids=record["issue_ids"],
        actor="user",
        note=note,
        detail={"sha": sha, "branch": branch},
    )
    save_plan(plan, plan_file)

    recorded = len(record["issue_ids"])
    print(colorize(f"  Recorded commit {sha} with {recorded} issue(s).", "green"))
    if note:
        print(colorize(f"  Note: {note}", "dim"))

    # Update PR if configured
    config = load_config()
    pr_number = config.get("commit_pr", 0)
    if pr_number:
        try:
            state = state_mod.load_state()
            body = generate_pr_body(plan, state)
            ok = update_pr_body(pr_number, body)
            if ok:
                print(colorize(f"  PR #{pr_number} description updated.", "green"))
            else:
                print(colorize(f"  Could not update PR #{pr_number} (gh may not be available).", "yellow"))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(
                colorize(f"  Warning: PR update skipped ({exc}).", "yellow"),
                file=sys.stderr,
            )


def _cmd_commit_log_history(args: argparse.Namespace, plan: dict) -> None:
    """Show commit records."""
    top = getattr(args, "top", 10)
    commit_log = plan.get("commit_log", [])

    if not commit_log:
        print(colorize("  No commits recorded yet.", "dim"))
        return

    print(colorize("  Commit History", "bold"))
    print(colorize("  " + "─" * 40, "dim"))

    shown = commit_log[-top:] if top else commit_log
    for record in reversed(shown):
        sha = record.get("sha", "?")[:7]
        branch = record.get("branch", "")
        issue_ids = record.get("issue_ids", [])
        note = record.get("note", "")
        recorded_at = record.get("recorded_at", "")

        header = f"  {sha}"
        if branch:
            header += f" ({branch})"
        header += f" — {len(issue_ids)} issue(s)"
        if recorded_at:
            header += f"  [{recorded_at[:16]}]"
        print(header)
        if note:
            print(colorize(f"    Note: {note}", "dim"))
        for fid in issue_ids[:5]:
            print(f"    - {fid}")
        if len(issue_ids) > 5:
            print(f"    ... and {len(issue_ids) - 5} more")


def _cmd_commit_log_pr(plan: dict) -> None:
    """Print PR body markdown to stdout (dry run)."""
    try:
        state = state_mod.load_state()
    except (OSError, ValueError, KeyError, TypeError):
        state = {"issues": {}}

    body = generate_pr_body(plan, state)
    print(body)


_COMMIT_LOG_HANDLERS = {
    "record": _cmd_commit_log_record,
    "history": _cmd_commit_log_history,
    "pr": lambda _args, plan: _cmd_commit_log_pr(plan),
}


def cmd_commit_log_dispatch(args: argparse.Namespace) -> None:
    """Route commit-log subcommands."""
    config = load_config()
    if not config.get("commit_tracking_enabled", True):
        print(colorize("  Commit tracking is disabled. Enable with: desloppify config set commit_tracking_enabled true", "yellow"))
        return

    runtime = command_runtime(args)
    plan_file = plan_path_for_state(runtime.state_path) if runtime.state_path else None
    plan = load_plan(plan_file)
    action = getattr(args, "commit_log_action", None)
    if action == "record":
        _cmd_commit_log_record(args, plan, plan_file)
        return
    handler = _COMMIT_LOG_HANDLERS.get(action)
    if handler is None:
        _cmd_commit_log_status(plan)
        return
    handler(args, plan)


__all__ = ["cmd_commit_log_dispatch"]
