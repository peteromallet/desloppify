"""Organize stage handler for plan triage."""

from __future__ import annotations

import argparse

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.base.output.terminal import colorize
from desloppify.engine.plan import load_plan, plan_path_for_state

from .stage_helpers import (
    _manual_clusters_with_issues,
    _require_triage_pending,
    _unenriched_clusters,
    _validate_stage_report,
)
from .stage_persistence import record_triage_stage


def cmd_stage_organize(args: argparse.Namespace) -> None:
    """Record the ORGANIZE stage: validates cluster enrichment."""
    runtime = command_runtime(args)
    plan_file = plan_path_for_state(runtime.state_path) if runtime.state_path else None
    plan = load_plan(plan_file)
    state = runtime.state

    if not _require_triage_pending(plan, action="organize"):
        return

    meta = plan.get("epic_triage_meta", {})
    stages = meta.get("triage_stages", {})
    if "reflect" not in stages:
        if "observe" not in stages:
            print(colorize("  Cannot organize: observe stage not complete.", "red"))
            print(colorize('  Run: desloppify plan triage --stage observe --report "..."', "dim"))
        else:
            print(colorize("  Cannot organize: reflect stage not complete.", "red"))
            print(colorize('  Run: desloppify plan triage --stage reflect --report "..."', "dim"))
        return

    manual_clusters = _manual_clusters_with_issues(plan)
    if not manual_clusters:
        any_clusters = [
            name for name, cluster in plan.get("clusters", {}).items() if cluster.get("issue_ids")
        ]
        if any_clusters:
            print(colorize("  Cannot organize: only auto-clusters exist.", "red"))
            print(colorize("  Create manual clusters that group issues by root cause:", "dim"))
        else:
            print(colorize("  Cannot organize: no clusters with issues exist.", "red"))
        print(colorize('    desloppify plan cluster create <name> --description "..."', "dim"))
        print(colorize("    desloppify plan cluster add <name> <issue-patterns>", "dim"))
        return

    gaps = _unenriched_clusters(plan)
    if gaps:
        print(colorize(f"  Cannot organize: {len(gaps)} cluster(s) need enrichment.", "red"))
        for name, missing in gaps:
            print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
        print()
        print(colorize("  Each cluster needs a description and action steps:", "dim"))
        print(
            colorize(
                '    desloppify plan cluster update <name> --description "what this cluster addresses" '
                '--steps "step 1" "step 2"',
                "dim",
            )
        )
        return

    report: str | None = getattr(args, "report", None)
    validated_report = _validate_stage_report(
        report,
        stage="organize",
        min_chars=100,
        missing_guidance=[
            "Summarize your prioritized organization:",
            "- Did you defer contradictory issues before clustering?",
            "- What clusters did you create and why?",
            "- Explicit priority ordering: which cluster 1st, 2nd, 3rd and why?",
            "- What depends on what? What unblocks the most?",
        ],
        short_guidance=[
            "Explain what you organized, your priorities, and focus order.",
        ],
    )
    if validated_report is None:
        return

    record_triage_stage(
        plan,
        state,
        stage="organize",
        report=validated_report,
        cited_ids=[],
        issue_count=len(manual_clusters),
        plan_path=plan_file,
    )

    print(
        colorize(
            f"  Organize stage recorded: {len(manual_clusters)} enriched cluster(s).",
            "green",
        )
    )
    for name in manual_clusters:
        cluster = plan.get("clusters", {}).get(name, {})
        steps = cluster.get("action_steps", [])
        desc = cluster.get("description", "")
        desc_str = f" \u2014 {desc}" if desc else ""
        print(
            colorize(
                f"    {name}: {len(cluster.get('issue_ids', []))} issues, {len(steps)} steps{desc_str}",
                "dim",
            )
        )

    print()
    print(colorize("  \u250c\u2500 Prioritized organization (share with user) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2510", "cyan"))
    for line in validated_report.strip().splitlines():
        print(colorize(f"  \u2502 {line}", "cyan"))
    print(colorize("  \u2514" + "\u2500" * 57 + "\u2518", "cyan"))
    print()
    print(
        colorize(
            "  IMPORTANT: Present your prioritized organization to the user. Explain",
            "yellow",
        )
    )
    print(
        colorize(
            "  each cluster, why it exists, and your explicit priority ordering \u2014",
            "yellow",
        )
    )
    print(
        colorize(
            "  which cluster comes first, second, third, what depends on what,",
            "yellow",
        )
    )
    print(colorize("  and why that ordering matters.", "yellow"))
    print()
    print(
        colorize(
            '  Next: desloppify plan triage --complete --strategy "plan summary..."',
            "dim",
        )
    )
