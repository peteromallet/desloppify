"""Handler for ``plan synthesize`` subcommand.

Implements a staged workflow: OBSERVE → REFLECT → ORGANIZE → COMMIT
with a fast-track CONFIRM-EXISTING skip path.

Stage gates validate **plan data enrichment**, not text reports:
- OBSERVE: lightweight — write an analysis of themes/root causes (100 char min)
- REFLECT: compare current findings against completed work (recurring patterns)
- ORGANIZE: structural — each manual cluster must have description + action_steps
- COMMIT: strategy must be substantive (200 char min) or "same"
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.state import require_completed_scan
from desloppify.app.commands.plan.synthesis_playbook import (
    SYNTHESIS_STAGE_DEPENDENCIES,
    SYNTHESIS_STAGE_LABELS,
    SYNTH_CMD_CLUSTER_ADD,
    SYNTH_CMD_CLUSTER_CREATE,
    SYNTH_CMD_CLUSTER_ENRICH_COMPACT,
    SYNTH_CMD_CLUSTER_STEPS,
    SYNTH_CMD_COMPLETE_VERBOSE,
    SYNTH_CMD_CONFIRM_EXISTING,
    SYNTH_CMD_OBSERVE,
    SYNTH_CMD_ORGANIZE,
    SYNTH_CMD_REFLECT,
)
from desloppify.core.io.api import colorize
from desloppify.engine._plan.epic_synthesis import (
    build_synthesis_prompt,
    collect_synthesis_input,
    detect_recurring_patterns,
    extract_finding_citations,
)
from desloppify.engine._plan.stale_dimensions import review_finding_snapshot_hash
from desloppify.engine._state.schema import utc_now
from desloppify.engine.plan import SYNTHESIS_ID, load_plan, save_plan


def _short_id(fid: str) -> str:
    """Extract the 8-char hash suffix from a finding ID for compact display.

    Finding IDs look like ``review::.::holistic::dim::identifier::abcdef12``.
    Commands accept the hash suffix as a shorthand for the full ID.
    """
    if "::" in fid:
        suffix = fid.rsplit("::", 1)[-1]
        if len(suffix) >= 8:
            return suffix[:8]
    return fid


def _synthesis_coverage(plan: dict) -> tuple[int, int, dict]:
    """Return (organized, total, clusters) for synthesis progress."""
    clusters = plan.get("clusters", {})
    all_cluster_ids: set[str] = set()
    for c in clusters.values():
        all_cluster_ids.update(c.get("finding_ids", []))
    queue_ids = [fid for fid in plan.get("queue_order", []) if fid != SYNTHESIS_ID]
    organized = sum(1 for fid in queue_ids if fid in all_cluster_ids)
    return organized, len(queue_ids), clusters


def _unenriched_clusters(plan: dict) -> list[tuple[str, list[str]]]:
    """Return clusters with findings that are missing required enrichment.

    Returns list of (cluster_name, list_of_missing_fields).
    Only checks non-auto clusters (manual clusters the agent creates).
    """
    gaps: list[tuple[str, list[str]]] = []
    for name, cluster in plan.get("clusters", {}).items():
        if not cluster.get("finding_ids"):
            continue
        if cluster.get("auto"):
            continue
        missing: list[str] = []
        if not cluster.get("description"):
            missing.append("description")
        if not cluster.get("action_steps"):
            missing.append("action_steps")
        if missing:
            gaps.append((name, missing))
    return gaps


def _manual_clusters_with_findings(plan: dict) -> list[str]:
    """Return names of non-auto clusters that have findings."""
    return [
        name for name, c in plan.get("clusters", {}).items()
        if c.get("finding_ids") and not c.get("auto")
    ]


def _print_stage_progress(stages: dict, plan: dict | None = None) -> None:
    """Print the 4-stage progress indicator."""
    print(colorize("  Stages:", "dim"))
    for stage_name, label in SYNTHESIS_STAGE_LABELS:
        if stage_name in stages:
            print(colorize(f"    \u2713 {label}", "green"))
        elif SYNTHESIS_STAGE_DEPENDENCIES[stage_name].issubset(stages):
            print(colorize(f"    \u2192 {label} (current)", "yellow"))
        else:
            print(colorize(f"    \u25cb {label}", "dim"))

    # Show enrichment gaps when in the organize stage
    if plan and "reflect" in stages and "organize" not in stages:
        gaps = _unenriched_clusters(plan)
        manual = _manual_clusters_with_findings(plan)
        if not manual:
            print(colorize("\n    No manual clusters yet. Create clusters and enrich them.", "yellow"))
        elif gaps:
            print(colorize(f"\n    {len(gaps)} cluster(s) need enrichment:", "yellow"))
            for name, missing in gaps:
                print(colorize(f"      {name}: missing {', '.join(missing)}", "yellow"))
            print(colorize(
                f"      Fix: {SYNTH_CMD_CLUSTER_ENRICH_COMPACT}",
                "dim",
            ))
        else:
            print(colorize(f"\n    All {len(manual)} manual cluster(s) enriched.", "green"))


def _print_progress(plan: dict, open_findings: dict) -> None:
    """Show cluster state and unclustered findings."""
    clusters = plan.get("clusters", {})
    # Only show clusters that actually have findings (hide empty/stale ones)
    active_clusters = {
        name: c for name, c in clusters.items()
        if c.get("finding_ids")
    }
    if active_clusters:
        print(colorize("\n  Current clusters:", "cyan"))
        for name, cluster in active_clusters.items():
            count = len(cluster.get("finding_ids", []))
            desc = cluster.get("description") or ""
            steps = cluster.get("action_steps", [])
            auto = cluster.get("auto", False)
            tags: list[str] = []
            if auto:
                tags.append("auto")
            if desc:
                tags.append("desc")
            else:
                tags.append("no desc")
            if steps:
                tags.append(f"{len(steps)} steps")
            else:
                if not auto:
                    tags.append("no steps")
            tag_str = f" [{', '.join(tags)}]"
            desc_str = f" \u2014 {desc}" if desc else ""
            print(f"    {name}: {count} items{tag_str}{desc_str}")

    all_clustered: set[str] = set()
    for c in clusters.values():
        all_clustered.update(c.get("finding_ids", []))
    unclustered = [fid for fid in open_findings if fid not in all_clustered]
    if unclustered:
        print(colorize(f"\n  {len(unclustered)} findings not yet in a cluster:", "yellow"))
        for fid in unclustered[:10]:
            f = open_findings[fid]
            dim = (f.get("detail", {}) or {}).get("dimension", "") if isinstance(f.get("detail"), dict) else ""
            short = _short_id(fid)
            print(f"    [{short}] [{dim}] {f.get('summary', '')}")
        if len(unclustered) > 10:
            print(colorize(f"    ... and {len(unclustered) - 10} more", "dim"))
    elif open_findings:
        organized, total, _ = _synthesis_coverage(plan)
        print(colorize(f"\n  All {organized}/{total} findings are in clusters.", "green"))


def _apply_completion(args: argparse.Namespace, plan: dict, strategy: str) -> None:
    """Shared completion logic: update meta, remove synthesis::pending, save."""
    organized, total, clusters = _synthesis_coverage(plan)

    order: list[str] = plan.get("queue_order", [])
    if SYNTHESIS_ID in order:
        order.remove(SYNTHESIS_ID)

    runtime = command_runtime(args)
    state = runtime.state
    current_hash = review_finding_snapshot_hash(state)

    meta = plan.setdefault("epic_synthesis_meta", {})
    meta["finding_snapshot_hash"] = current_hash
    if strategy.strip().lower() != "same":
        meta["strategy_summary"] = strategy
    meta["trigger"] = "manual_synthesis"
    meta["last_completed_at"] = utc_now()
    meta["synthesis_stages"] = {}  # clear stages on completion
    meta.pop("stage_refresh_required", None)
    meta.pop("stage_snapshot_hash", None)

    save_plan(plan)

    cluster_count = len([c for c in clusters.values() if c.get("finding_ids")])
    print(colorize(f"  Synthesis complete: {organized}/{total} findings in {cluster_count} cluster(s).", "green"))
    effective_strategy = strategy if strategy.strip().lower() != "same" else meta.get("strategy_summary", "")
    if effective_strategy:
        print(colorize(f"  Strategy: {effective_strategy}", "cyan"))
    print(colorize("  Run `desloppify next` to start implementation.", "green"))


# ---------------------------------------------------------------------------
# Stage handlers
# ---------------------------------------------------------------------------

def _cmd_stage_observe(args: argparse.Namespace) -> None:
    """Record the OBSERVE stage: agent analyses themes and root causes.

    No citation gate — the point is genuine analysis, not ID-stuffing.
    Just requires a 100-char report describing what the agent observed.
    """
    report: str | None = getattr(args, "report", None)
    if not report:
        print(colorize("  --report is required for --stage observe.", "red"))
        print(colorize("  Write an analysis of the findings: themes, root causes, contradictions.", "dim"))
        print(colorize("  Identify findings that contradict each other (opposite recommendations).", "dim"))
        print(colorize("  Do NOT just list finding IDs — describe what you actually observe.", "dim"))
        return

    runtime = command_runtime(args)
    state = runtime.state
    plan = load_plan()

    if SYNTHESIS_ID not in plan.get("queue_order", []):
        print(colorize("  synthesis::pending is not in the queue \u2014 nothing to observe.", "yellow"))
        return

    si = collect_synthesis_input(plan, state)
    finding_count = len(si.open_findings)

    # Edge case: 0 findings
    if finding_count == 0:
        meta = plan.setdefault("epic_synthesis_meta", {})
        stages = meta.setdefault("synthesis_stages", {})
        stages["observe"] = {
            "stage": "observe",
            "report": report,
            "cited_ids": [],
            "timestamp": utc_now(),
            "finding_count": 0,
        }
        save_plan(plan)
        print(colorize("  Observe stage recorded (no findings to analyse).", "green"))
        return

    # Validation: report length (no citation counting)
    min_chars = 50 if finding_count <= 3 else 100
    if len(report) < min_chars:
        print(colorize(f"  Report too short: {len(report)} chars (minimum {min_chars}).", "red"))
        print(colorize("  Describe themes, root causes, contradictions, and how findings relate.", "dim"))
        return

    # Save stage (still extract citations for analytics, but don't gate on them)
    valid_ids = set(si.open_findings.keys())
    cited = extract_finding_citations(report, valid_ids)

    meta = plan.setdefault("epic_synthesis_meta", {})
    stages = meta.setdefault("synthesis_stages", {})
    stages["observe"] = {
        "stage": "observe",
        "report": report,
        "cited_ids": sorted(cited),
        "timestamp": utc_now(),
        "finding_count": finding_count,
    }
    save_plan(plan)

    print(colorize(
        f"  Observe stage recorded: {finding_count} findings analysed.",
        "green",
    ))
    print(colorize(
        "  Next: run `desloppify plan synthesize` to see completed work, resolved findings,",
        "dim",
    ))
    print(colorize(
        "  and recurring patterns. Then record your reflect stage:",
        "dim",
    ))
    print(colorize(
        '    desloppify plan synthesize --stage reflect --report "..."',
        "dim",
    ))


def _cmd_stage_reflect(args: argparse.Namespace) -> None:
    """Record the REFLECT stage: compare current findings against completed work.

    Forces the agent to consider what was previously resolved and whether
    similar issues are recurring. Requires a 100-char report (50 if ≤3 findings).
    If recurring patterns are detected, the report must mention at least one
    recurring dimension name.
    """
    report: str | None = getattr(args, "report", None)
    if not report:
        print(colorize("  --report is required for --stage reflect.", "red"))
        print(colorize("  Compare current findings against completed work and form a holistic strategy:", "dim"))
        print(colorize("  - What clusters were previously completed? Did fixes hold?", "dim"))
        print(colorize("  - Are any dimensions recurring (resolved before, open again)?", "dim"))
        print(colorize("  - What contradictions did you find? Which direction will you take?", "dim"))
        print(colorize("  - Big picture: what to prioritize, what to defer, what to skip?", "dim"))
        return

    runtime = command_runtime(args)
    state = runtime.state
    plan = load_plan()

    if SYNTHESIS_ID not in plan.get("queue_order", []):
        print(colorize("  synthesis::pending is not in the queue — nothing to reflect on.", "yellow"))
        return

    meta = plan.get("epic_synthesis_meta", {})
    stages = meta.get("synthesis_stages", {})
    if "observe" not in stages:
        print(colorize("  Cannot reflect: observe stage not complete.", "red"))
        print(colorize('  Run: desloppify plan synthesize --stage observe --report "..."', "dim"))
        return

    si = collect_synthesis_input(plan, state)
    finding_count = len(si.open_findings)

    # Validation: report length
    min_chars = 50 if finding_count <= 3 else 100
    if len(report) < min_chars:
        print(colorize(f"  Report too short: {len(report)} chars (minimum {min_chars}).", "red"))
        print(colorize("  Describe how current findings relate to previously completed work.", "dim"))
        return

    # Detect recurring patterns
    recurring = detect_recurring_patterns(si.open_findings, si.resolved_findings)
    recurring_dims = sorted(recurring.keys())

    # If recurring patterns exist, report must mention at least one dimension
    if recurring_dims:
        report_lower = report.lower()
        mentioned = [dim for dim in recurring_dims if dim.lower() in report_lower]
        if not mentioned:
            print(colorize("  Recurring patterns detected but not addressed in report:", "red"))
            for dim in recurring_dims:
                info = recurring[dim]
                print(colorize(
                    f"    {dim}: {len(info['resolved'])} resolved, "
                    f"{len(info['open'])} still open — potential loop",
                    "yellow",
                ))
            print(colorize(
                "  Your report must mention at least one recurring dimension name.",
                "dim",
            ))
            return

    # Save stage
    stages = meta.setdefault("synthesis_stages", {})
    stages["reflect"] = {
        "stage": "reflect",
        "report": report,
        "cited_ids": [],
        "timestamp": utc_now(),
        "finding_count": finding_count,
        "recurring_dimensions": recurring_dims,
    }
    save_plan(plan)

    print(colorize(
        f"  Reflect stage recorded: {finding_count} findings, "
        f"{len(recurring_dims)} recurring dimension(s).",
        "green",
    ))
    if recurring_dims:
        for dim in recurring_dims:
            info = recurring[dim]
            print(colorize(
                f"    {dim}: {len(info['resolved'])} resolved, {len(info['open'])} still open",
                "dim",
            ))

    # Print the reflect report prominently — this is the agent's briefing to the user
    print()
    print(colorize("  ┌─ Strategic briefing (share with user before organizing) ─┐", "cyan"))
    for line in report.strip().splitlines():
        print(colorize(f"  │ {line}", "cyan"))
    print(colorize("  └" + "─" * 57 + "┘", "cyan"))
    print()
    print(colorize(
        "  IMPORTANT: Present your holistic strategy to the user. Explain:",
        "yellow",
    ))
    print(colorize(
        "  - What themes and root causes you see",
        "yellow",
    ))
    print(colorize(
        "  - What contradictions you found and which direction you'll take",
        "yellow",
    ))
    print(colorize(
        "  - What you'll prioritize, what you'll defer, the overall arc of work",
        "yellow",
    ))
    print(colorize(
        "  Wait for their input before creating clusters.",
        "yellow",
    ))
    print()
    print(colorize(
        "  Then create clusters and enrich each with action steps:",
        "dim",
    ))
    print(colorize(
        '    desloppify plan cluster create <name> --description "..."',
        "dim",
    ))
    print(colorize(
        "    desloppify plan cluster add <name> <finding-patterns>",
        "dim",
    ))
    print(colorize(
        '    desloppify plan cluster update <name> --steps "step 1" "step 2" ...',
        "dim",
    ))
    print(colorize(
        "    desloppify plan synthesize --stage organize --report \"summary of what was organized...\"",
        "dim",
    ))


def _cmd_stage_organize(args: argparse.Namespace) -> None:
    """Record the ORGANIZE stage: validates cluster enrichment.

    Instead of gating on a text report, validates that the plan data
    itself has been enriched: each manual cluster needs description +
    action_steps. This forces the agent to actually think about each
    cluster's execution plan.
    """
    plan = load_plan()

    if SYNTHESIS_ID not in plan.get("queue_order", []):
        print(colorize("  synthesis::pending is not in the queue \u2014 nothing to organize.", "yellow"))
        return

    meta = plan.get("epic_synthesis_meta", {})
    stages = meta.get("synthesis_stages", {})
    if "reflect" not in stages:
        if "observe" not in stages:
            print(colorize("  Cannot organize: observe stage not complete.", "red"))
            print(colorize('  Run: desloppify plan synthesize --stage observe --report "..."', "dim"))
        else:
            print(colorize("  Cannot organize: reflect stage not complete.", "red"))
            print(colorize('  Run: desloppify plan synthesize --stage reflect --report "..."', "dim"))
        return

    # Validate: at least 1 manual cluster with findings
    manual_clusters = _manual_clusters_with_findings(plan)
    if not manual_clusters:
        # Check if there are ANY clusters with findings (including auto)
        any_clusters = [
            name for name, c in plan.get("clusters", {}).items()
            if c.get("finding_ids")
        ]
        if any_clusters:
            print(colorize("  Cannot organize: only auto-clusters exist.", "red"))
            print(colorize("  Create manual clusters that group findings by root cause:", "dim"))
        else:
            print(colorize("  Cannot organize: no clusters with findings exist.", "red"))
        print(colorize('    desloppify plan cluster create <name> --description "..."', "dim"))
        print(colorize("    desloppify plan cluster add <name> <finding-patterns>", "dim"))
        return

    # Validate: all manual clusters are enriched
    gaps = _unenriched_clusters(plan)
    if gaps:
        print(colorize(f"  Cannot organize: {len(gaps)} cluster(s) need enrichment.", "red"))
        for name, missing in gaps:
            print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
        print()
        print(colorize("  Each cluster needs a description and action steps:", "dim"))
        print(colorize(
            '    desloppify plan cluster update <name> --description "what this cluster addresses" '
            '--steps "step 1" "step 2"',
            "dim",
        ))
        return

    # Require report — the agent must summarize what they organized and why
    report: str | None = getattr(args, "report", None)
    if not report:
        print(colorize("  --report is required for --stage organize.", "red"))
        print(colorize("  Summarize your prioritized organization:", "dim"))
        print(colorize("  - Did you defer contradictory findings before clustering?", "dim"))
        print(colorize("  - What clusters did you create and why?", "dim"))
        print(colorize("  - Explicit priority ordering: which cluster 1st, 2nd, 3rd and why?", "dim"))
        print(colorize("  - What depends on what? What unblocks the most?", "dim"))
        return
    if len(report) < 100:
        print(colorize(f"  Report too short: {len(report)} chars (minimum 100).", "red"))
        print(colorize("  Explain what you organized, your priorities, and focus order.", "dim"))
        return

    stages = meta.setdefault("synthesis_stages", {})
    stages["organize"] = {
        "stage": "organize",
        "report": report,
        "cited_ids": [],
        "timestamp": utc_now(),
        "finding_count": len(manual_clusters),
    }
    save_plan(plan)

    print(colorize(
        f"  Organize stage recorded: {len(manual_clusters)} enriched cluster(s).",
        "green",
    ))
    # Show cluster summary
    for name in manual_clusters:
        cluster = plan.get("clusters", {}).get(name, {})
        steps = cluster.get("action_steps", [])
        desc = cluster.get("description", "")
        desc_str = f" — {desc}" if desc else ""
        print(colorize(f"    {name}: {len(cluster.get('finding_ids', []))} findings, {len(steps)} steps{desc_str}", "dim"))

    # Print the organize report prominently — this is the debrief
    print()
    print(colorize("  ┌─ Prioritized organization (share with user) ───────────┐", "cyan"))
    for line in report.strip().splitlines():
        print(colorize(f"  │ {line}", "cyan"))
    print(colorize("  └" + "─" * 57 + "┘", "cyan"))
    print()
    print(colorize(
        "  IMPORTANT: Present your prioritized organization to the user. Explain",
        "yellow",
    ))
    print(colorize(
        "  each cluster, why it exists, and your explicit priority ordering —",
        "yellow",
    ))
    print(colorize(
        "  which cluster comes first, second, third, what depends on what,",
        "yellow",
    ))
    print(colorize(
        "  and why that ordering matters.",
        "yellow",
    ))
    print()
    print(colorize(
        '  Next: desloppify plan synthesize --complete --strategy "plan summary..."',
        "dim",
    ))


# ---------------------------------------------------------------------------
# Completion
# ---------------------------------------------------------------------------

def _cmd_synthesize_complete(args: argparse.Namespace) -> None:
    """Complete synthesis \u2014 requires organize stage (or confirm-existing path)."""
    strategy: str | None = getattr(args, "strategy", None)
    plan = load_plan()

    if SYNTHESIS_ID not in plan.get("queue_order", []):
        print(colorize("  synthesis::pending is not in the queue \u2014 nothing to complete.", "yellow"))
        return

    meta = plan.get("epic_synthesis_meta", {})
    stages = meta.get("synthesis_stages", {})

    # Require organize stage (or confirmed-existing)
    if "organize" not in stages:
        if "observe" not in stages:
            print(colorize("  Cannot complete: no stages done yet.", "red"))
            print(colorize('  Start with: desloppify plan synthesize --stage observe --report "..."', "dim"))
        else:
            print(colorize("  Cannot complete: organize stage not done.", "red"))
            gaps = _unenriched_clusters(plan)
            if gaps:
                print(colorize(f"  {len(gaps)} cluster(s) still need enrichment:", "yellow"))
                for name, missing in gaps:
                    print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
                print(colorize(
                    '  Fix: desloppify plan cluster update <name> --description "..." --steps "step1" "step2"',
                    "dim",
                ))
                print(colorize(
                    f"  Then: {SYNTH_CMD_ORGANIZE}",
                    "dim",
                ))
            else:
                manual = _manual_clusters_with_findings(plan)
                if manual:
                    print(colorize("  Clusters are enriched. Record the organize stage first:", "dim"))
                    print(colorize(f"    {SYNTH_CMD_ORGANIZE}", "dim"))
                else:
                    print(colorize("  Create enriched clusters first, then record organize:", "dim"))
                    print(colorize(f"    {SYNTH_CMD_ORGANIZE}", "dim"))
            if meta.get("strategy_summary"):
                print(colorize('  Or fast-track: --confirm-existing --note "why plan is still valid" --strategy "..."', "dim"))
        return

    # Re-validate cluster enrichment at completion time (prevents bypassing
    # organize gate by editing plan.json directly)
    manual_clusters = _manual_clusters_with_findings(plan)
    if not manual_clusters:
        any_clusters = [
            name for name, c in plan.get("clusters", {}).items()
            if c.get("finding_ids")
        ]
        if not any_clusters:
            print(colorize("  Cannot complete: no clusters with findings exist.", "red"))
            print(colorize('  Create clusters: desloppify plan cluster create <name> --description "..."', "dim"))
            return

    gaps = _unenriched_clusters(plan)
    if gaps:
        print(colorize(f"  Cannot complete: {len(gaps)} cluster(s) still need enrichment.", "red"))
        for name, missing in gaps:
            print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
        print(colorize(
            '  Fix: desloppify plan cluster update <name> --description "..." --steps "step1" "step2"',
            "dim",
        ))
        return

    # Verify cluster coverage
    organized, total, clusters = _synthesis_coverage(plan)

    if total > 0 and organized == 0:
        print(colorize("  Cannot complete: no findings have been organized into clusters.", "red"))
        print(colorize(f"  {total} findings are waiting.", "dim"))
        return

    if total > 0 and organized < total:
        remaining = total - organized
        print(colorize(
            f"  Warning: {remaining}/{total} findings are not yet in any cluster.",
            "yellow",
        ))

    # Strategy required
    if not strategy:
        print(colorize("  --strategy is required.", "red"))
        existing = meta.get("strategy_summary", "")
        if existing:
            print(colorize(f"  Current strategy: {existing}", "dim"))
            print(colorize('  Use --strategy "same" to keep it, or provide a new summary.', "dim"))
        else:
            print(colorize('  Provide --strategy "execution plan describing priorities, ordering, and verification approach"', "dim"))
        return

    # Strategy length check (unless "same") — 200 chars forces substantive content
    if strategy.strip().lower() != "same" and len(strategy.strip()) < 200:
        print(colorize(f"  Strategy too short: {len(strategy.strip())} chars (minimum 200).", "red"))
        print(colorize("  The strategy should describe:", "dim"))
        print(colorize("    - Execution order and priorities", "dim"))
        print(colorize("    - What each cluster accomplishes", "dim"))
        print(colorize("    - How to verify the work is correct", "dim"))
        return

    # Show summary
    print(colorize("  Synthesis summary:", "bold"))
    if "observe" in stages:
        obs = stages["observe"]
        print(colorize(f"    Observe: {obs.get('finding_count', '?')} findings analysed", "dim"))
    if "reflect" in stages:
        ref = stages["reflect"]
        recurring = ref.get("recurring_dimensions", [])
        if recurring:
            print(colorize(f"    Reflect: {len(recurring)} recurring dimension(s)", "dim"))
        else:
            print(colorize("    Reflect: no recurring patterns", "dim"))
    if "organize" in stages:
        manual = _manual_clusters_with_findings(plan)
        print(colorize(f"    Organize: {len(manual)} enriched cluster(s)", "dim"))
        for name in manual:
            cluster = plan.get("clusters", {}).get(name, {})
            steps = cluster.get("action_steps", [])
            print(colorize(f"      {name}: {len(steps)} steps", "dim"))

    _apply_completion(args, plan, strategy)


# ---------------------------------------------------------------------------
# Confirm-existing (skip path)
# ---------------------------------------------------------------------------

def _cmd_confirm_existing(args: argparse.Namespace) -> None:
    """Fast-track: confirm existing plan structure is still valid."""
    note: str | None = getattr(args, "note", None)
    strategy: str | None = getattr(args, "strategy", None)
    plan = load_plan()

    if SYNTHESIS_ID not in plan.get("queue_order", []):
        print(colorize("  synthesis::pending is not in the queue \u2014 nothing to confirm.", "yellow"))
        return

    meta = plan.get("epic_synthesis_meta", {})
    stages = meta.get("synthesis_stages", {})

    # Require observe + reflect stages
    if "observe" not in stages:
        print(colorize("  Cannot confirm existing: observe stage not complete.", "red"))
        print(colorize("  You must read findings first.", "dim"))
        print(colorize('  Run: desloppify plan synthesize --stage observe --report "..."', "dim"))
        return
    if "reflect" not in stages:
        print(colorize("  Cannot confirm existing: reflect stage not complete.", "red"))
        print(colorize("  You must compare against completed work first.", "dim"))
        print(colorize('  Run: desloppify plan synthesize --stage reflect --report "..."', "dim"))
        return

    # Require a prior completed synthesis — can't skip the full flow on first run
    prior_strategy = meta.get("strategy_summary", "")
    if not prior_strategy:
        print(colorize("  Cannot confirm existing: no prior synthesis has been completed.", "red"))
        print(colorize("  The full OBSERVE \u2192 REFLECT \u2192 ORGANIZE \u2192 COMMIT flow is required the first time.", "dim"))
        print(colorize(f"  Create and enrich clusters, then: {SYNTH_CMD_ORGANIZE}", "dim"))
        return

    # Require existing enriched clusters
    clusters_with_findings = _manual_clusters_with_findings(plan)
    if not clusters_with_findings:
        print(colorize("  Cannot confirm existing: no clusters with findings exist.", "red"))
        print(colorize("  Use the full organize flow instead.", "dim"))
        return

    # Require note
    if not note:
        print(colorize("  --note is required for confirm-existing.", "red"))
        print(colorize('  Explain why the existing plan is still valid (min 100 chars).', "dim"))
        return
    if len(note) < 100:
        print(colorize(f"  Note too short: {len(note)} chars (minimum 100).", "red"))
        return

    # Require strategy
    if not strategy:
        print(colorize("  --strategy is required.", "red"))
        existing = meta.get("strategy_summary", "")
        if existing:
            print(colorize('  Use --strategy "same" to keep it, or provide a new summary.', "dim"))
        return

    # Strategy length check (unless "same")
    if strategy.strip().lower() != "same" and len(strategy.strip()) < 200:
        print(colorize(f"  Strategy too short: {len(strategy.strip())} chars (minimum 200).", "red"))
        return

    # Validate: note cites at least 1 new/changed finding (if there are any)
    runtime = command_runtime(args)
    state = runtime.state
    si = collect_synthesis_input(plan, state)
    new_ids = si.new_since_last
    if new_ids:
        valid_ids = set(si.open_findings.keys())
        cited = extract_finding_citations(note, valid_ids)
        new_cited = cited & new_ids
        if not new_cited:
            print(colorize("  Note must cite at least 1 new/changed finding.", "red"))
            print(colorize(f"  {len(new_ids)} new finding(s) since last synthesis:", "dim"))
            for fid in sorted(new_ids)[:5]:
                print(colorize(f"    {fid}", "dim"))
            if len(new_ids) > 5:
                print(colorize(f"    ... and {len(new_ids) - 5} more", "dim"))
            return

    # Record organize as confirmed-existing and complete
    stages = meta.setdefault("synthesis_stages", {})
    stages["organize"] = {
        "stage": "organize",
        "report": f"[confirmed-existing] {note}",
        "cited_ids": [],
        "timestamp": utc_now(),
        "finding_count": len(clusters_with_findings),
    }

    _apply_completion(args, plan, strategy)
    print(colorize("  Confirmed existing plan \u2014 synthesis complete.", "green"))


# ---------------------------------------------------------------------------
# Reflect dashboard
# ---------------------------------------------------------------------------

def _print_reflect_dashboard(si: object, plan: dict) -> None:
    """Show completed clusters, resolved findings, and recurring patterns."""
    # si is a SynthesisInput
    completed = getattr(si, "completed_clusters", [])
    resolved = getattr(si, "resolved_findings", {})
    open_findings = getattr(si, "open_findings", {})

    if completed:
        print(colorize("\n  Previously completed clusters:", "cyan"))
        for c in completed[:10]:
            name = c.get("name", "?")
            count = len(c.get("finding_ids", []))
            thesis = c.get("thesis", "")
            print(f"    {name}: {count} findings")
            if thesis:
                print(colorize(f"      {thesis}", "dim"))
            for step in c.get("action_steps", [])[:3]:
                print(colorize(f"      - {step}", "dim"))
        if len(completed) > 10:
            print(colorize(f"    ... and {len(completed) - 10} more", "dim"))

    if resolved:
        print(colorize(f"\n  Resolved findings since last synthesis: {len(resolved)}", "cyan"))
        for fid, f in sorted(resolved.items())[:10]:
            status = f.get("status", "")
            summary = f.get("summary", "")
            detail = f.get("detail", {}) if isinstance(f.get("detail"), dict) else {}
            dim = detail.get("dimension", "")
            print(f"    [{status}] [{dim}] {summary}")
            print(colorize(f"      {fid}", "dim"))
        if len(resolved) > 10:
            print(colorize(f"    ... and {len(resolved) - 10} more", "dim"))

    recurring = detect_recurring_patterns(open_findings, resolved)
    if recurring:
        print(colorize("\n  Recurring patterns detected:", "yellow"))
        for dim, info in sorted(recurring.items()):
            resolved_count = len(info["resolved"])
            open_count = len(info["open"])
            label = "potential loop" if open_count >= resolved_count else "root cause unaddressed"
            print(colorize(
                f"    {dim}: {resolved_count} resolved, {open_count} still open — {label}",
                "yellow",
            ))
    elif not completed and not resolved:
        print(colorize("\n  First synthesis — no prior work to compare against.", "dim"))
        print(colorize("  Focus your reflect report on your strategy:", "yellow"))
        print(colorize("  - How will you resolve contradictions you identified in observe?", "dim"))
        print(colorize("  - Which findings will you cluster together vs defer?", "dim"))
        print(colorize("  - What's the overall arc of work and why?", "dim"))


# ---------------------------------------------------------------------------
# Dashboard (default view)
# ---------------------------------------------------------------------------

def _cmd_synthesize_dashboard(args: argparse.Namespace) -> None:
    """Default view: show findings, stage progress, and next command."""
    runtime = command_runtime(args)
    state = runtime.state
    plan = load_plan()
    si = collect_synthesis_input(plan, state)
    meta = plan.get("epic_synthesis_meta", {})
    stages = meta.get("synthesis_stages", {})

    print(colorize("  Epic synthesis \u2014 manual", "bold"))
    print(colorize("  " + "\u2500" * 60, "dim"))
    print(f"  Open review findings: {len(si.open_findings)}")
    print(colorize("  Goal: identify contradictions, resolve them, then group the coherent", "cyan"))
    print(colorize("  remainder into clusters by root cause with action steps and priorities.", "cyan"))
    if si.existing_epics:
        print(f"  Existing epics: {len(si.existing_epics)}")
    if si.new_since_last:
        print(f"  New since last synthesis: {len(si.new_since_last)}")
    if si.resolved_since_last:
        print(f"  Resolved since last synthesis: {len(si.resolved_since_last)}")

    # Stage progress (with enrichment gaps)
    print()
    _print_stage_progress(stages, plan)
    if meta.get("stage_refresh_required"):
        print(
            colorize(
                "  Note: review findings changed since stage progress started; "
                "refresh stage reports before completion.",
                "yellow",
            )
        )

    # --- Action guidance (shown early so agents see what to do first) ---
    print()
    if "observe" not in stages:
        print(colorize("  Next step:", "yellow"))
        print(f"    {SYNTH_CMD_OBSERVE}")
        print(colorize("    (themes, root causes, contradictions between findings — NOT a list of IDs)", "dim"))
    elif "reflect" not in stages:
        print(colorize("  Next step: use the completed work and patterns below to write your reflect report.", "yellow"))
        print(f"    {SYNTH_CMD_REFLECT}")
        print(colorize("    (Contradictions, recurring patterns, which direction to take, what to defer)", "dim"))
    elif "organize" not in stages:
        gaps = _unenriched_clusters(plan)
        manual = _manual_clusters_with_findings(plan)

        if not manual:
            print(colorize("  Next steps:", "yellow"))
            print("    0. Defer contradictory findings: `desloppify plan skip <hash>`")
            print(f"    1. Create clusters:  {SYNTH_CMD_CLUSTER_CREATE}")
            print(f"    2. Add findings:     {SYNTH_CMD_CLUSTER_ADD}")
            print(f"    3. Enrich clusters:  {SYNTH_CMD_CLUSTER_STEPS}")
            print(f"    4. Record stage:     {SYNTH_CMD_ORGANIZE}")
        elif gaps:
            print(colorize("  Enrich these clusters before recording organize:", "yellow"))
            for name, missing in gaps:
                print(colorize(f"    {name}: missing {', '.join(missing)}", "yellow"))
            print(colorize(
                f"    Fix: {SYNTH_CMD_CLUSTER_ENRICH_COMPACT}",
                "dim",
            ))
            print(colorize(f"    Then: {SYNTH_CMD_ORGANIZE}", "dim"))
        else:
            print(colorize("  All clusters enriched! Record the organize stage:", "green"))
            print(f"    {SYNTH_CMD_ORGANIZE}")

        if meta.get("strategy_summary"):
            print()
            print(colorize("  Or fast-track (if existing plan is still valid):", "dim"))
            print(f"    {SYNTH_CMD_CONFIRM_EXISTING}")
    else:
        print(colorize("  Ready to complete:", "green"))
        print(f"    {SYNTH_CMD_COMPLETE_VERBOSE}")
        print(colorize('    (use --strategy "same" to keep existing strategy)', "dim"))

    # --- Prior stage reports (context for current action) ---
    if "observe" in stages:
        obs_report = stages["observe"].get("report", "")
        if obs_report:
            print(colorize("\n  Your observe analysis:", "dim"))
            for line in obs_report.strip().splitlines()[:8]:
                print(colorize(f"    {line}", "dim"))
            if len(obs_report.strip().splitlines()) > 8:
                print(colorize("    ...", "dim"))
    if "reflect" in stages:
        ref_report = stages["reflect"].get("report", "")
        if ref_report:
            print(colorize("\n  Your reflect strategy:", "dim"))
            for line in ref_report.strip().splitlines()[:8]:
                print(colorize(f"    {line}", "dim"))
            if len(ref_report.strip().splitlines()) > 8:
                print(colorize("    ...", "dim"))

    # --- Findings data ---
    # Group findings by dimension with suggestions to surface contradictions
    by_dim: dict[str, list[tuple[str, dict]]] = defaultdict(list)
    for fid, f in si.open_findings.items():
        detail = f.get("detail", {}) if isinstance(f.get("detail"), dict) else {}
        dim = detail.get("dimension", "unknown")
        by_dim[dim].append((fid, f))

    print(colorize("\n  Review findings by dimension:", "cyan"))
    print(colorize("  (Look for contradictions: findings in the same dimension that", "dim"))
    print(colorize("  recommend opposite changes. These must be resolved before clustering.)", "dim"))
    max_per_dim = 5
    for dim in sorted(by_dim, key=lambda d: (-len(by_dim[d]), d)):
        items = by_dim[dim]
        print(colorize(f"\n    {dim} ({len(items)}):", "bold"))
        for fid, f in items[:max_per_dim]:
            summary = f.get("summary", "")
            short = _short_id(fid)
            detail = f.get("detail", {}) if isinstance(f.get("detail"), dict) else {}
            suggestion = (detail.get("suggestion") or "")[:120]
            print(f"      [{short}] {summary}")
            if suggestion:
                print(colorize(f"        \u2192 {suggestion}", "dim"))
        if len(items) > max_per_dim:
            print(colorize(f"      ... and {len(items) - max_per_dim} more", "dim"))
    print(colorize("\n  Use hash in commands: desloppify plan skip <hash>  |  desloppify show <hash>", "dim"))

    # Show reflect dashboard when observe done, reflect not done
    if "observe" in stages and "reflect" not in stages:
        _print_reflect_dashboard(si, plan)

    # Show current cluster progress
    _print_progress(plan, si.open_findings)


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def cmd_plan_synthesize(args: argparse.Namespace) -> None:
    """Run epic synthesis: staged workflow OBSERVE → REFLECT → ORGANIZE → COMMIT."""
    runtime = command_runtime(args)
    state = runtime.state
    if not require_completed_scan(state):
        return

    # Route: --complete
    if getattr(args, "complete", False):
        _cmd_synthesize_complete(args)
        return

    # Route: --confirm-existing
    if getattr(args, "confirm_existing", False):
        _cmd_confirm_existing(args)
        return

    # Route: --stage observe/reflect/organize
    stage = getattr(args, "stage", None)
    if stage == "observe":
        _cmd_stage_observe(args)
        return
    if stage == "reflect":
        _cmd_stage_reflect(args)
        return
    if stage == "organize":
        _cmd_stage_organize(args)
        return

    # Dry-run mode
    if getattr(args, "dry_run", False):
        plan = load_plan()
        si = collect_synthesis_input(plan, state)
        prompt = build_synthesis_prompt(si)
        print(colorize("  Epic synthesis \u2014 dry run", "bold"))
        print(colorize("  " + "\u2500" * 60, "dim"))
        print(f"  Open review findings: {len(si.open_findings)}")
        print(f"  Existing epics: {len(si.existing_epics)}")
        print(f"  New since last: {len(si.new_since_last)}")
        print(f"  Resolved since last: {len(si.resolved_since_last)}")
        print(colorize("\n  Prompt that would be sent to LLM:", "dim"))
        print()
        print(prompt)
        return

    # Default: dashboard
    _cmd_synthesize_dashboard(args)


__all__ = ["cmd_plan_synthesize"]
