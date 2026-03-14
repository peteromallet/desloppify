"""LLM-facing reporting helpers for scan command."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from desloppify import state as state_mod
from desloppify.base.output.user_message import print_user_message
from desloppify.app.commands.update_skill import (
    resolve_interface,
    update_installed_skill,
)
from desloppify.base import registry as registry_mod
from desloppify.app import skill_docs as skill_docs_mod
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.fallbacks import log_best_effort_failure
from desloppify.base.discovery.paths import get_project_root
from desloppify.engine._scoring.results.core import compute_health_breakdown
from desloppify.engine._scoring.subjective.core import DISPLAY_NAMES
from desloppify.engine._state.schema import StateModel
from desloppify.engine._work_queue.core import ATTEST_EXAMPLE
from desloppify.engine.plan_state import load_plan
from desloppify.engine.planning import scorecard_projection as scorecard_projection_mod

from .text import build_workflow_guide

logger = logging.getLogger(__name__)


def is_agent_environment() -> bool:
    return bool(
        os.environ.get("AGENT")
        or os.environ.get("CLAUDECODE")
        or os.environ.get("DESLOPPIFY_AGENT")
        or os.environ.get("GEMINI_CLI")
        or os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED")
        or os.environ.get("CODEX_SANDBOX")
        or os.environ.get("CURSOR_TRACE_ID")
    )


def _load_scores(state: StateModel) -> state_mod.ScoreSnapshot:
    """Load all four canonical scores from state."""
    return state_mod.score_snapshot(state)


def _print_score_lines(
    *,
    overall_score: float | None,
    objective_score: float | None,
    strict_score: float | None,
    verified_strict_score: float | None,
) -> None:
    lines: list[str] = []
    if overall_score is not None:
        lines.append(f"Overall score:   {overall_score:.1f}/100")
    if objective_score is not None:
        lines.append(f"Objective score: {objective_score:.1f}/100")
    if strict_score is not None:
        lines.append(f"Strict score:    {strict_score:.1f}/100")
    if verified_strict_score is not None:
        lines.append(f"Verified score:  {verified_strict_score:.1f}/100")
    if lines:
        print("\n".join(lines))
    # Score legend — always shown in LLM block so agents understand the scoring model
    print("Score guide:")
    print("  overall  = 25% mechanical + 75% subjective (lenient — ignores wontfix)")
    print("  objective = mechanical detectors only (no subjective review)")
    print("  strict   = like overall, but wontfix counts against you  <-- your north star")
    print("  verified = strict, but only credits scan-verified fixes")
    print()


def _split_dimension_scores(
    state: StateModel,
    dim_scores: dict[str, Any],
) -> tuple[list[tuple[str, dict[str, Any]]], list[tuple[str, dict[str, Any]]]]:
    # Build dimension table from canonical scorecard projection.
    rows = scorecard_projection_mod.scorecard_dimension_rows(
        state, dim_scores=dim_scores
    )
    subjective_name_set = {name.lower() for name in DISPLAY_NAMES.values()}
    subjective_name_set.update({"elegance", "elegance (combined)"})

    mechanical = [
        (name, data)
        for name, data in rows
        if (
            "subjective_assessment" not in data.get("detectors", {})
            and str(name).strip().lower() not in subjective_name_set
        )
    ]
    subjective = [
        (name, data)
        for name, data in rows
        if (
            "subjective_assessment" in data.get("detectors", {})
            or str(name).strip().lower() in subjective_name_set
        )
    ]
    return mechanical, subjective


def _print_dimension_table(state: StateModel, dim_scores: dict[str, Any]) -> None:
    mechanical, subjective = _split_dimension_scores(state, dim_scores)
    if not (mechanical or subjective):
        return

    print("| Dimension | Health | Strict | Issues | Tier | Action |")
    print("|-----------|--------|--------|--------|------|--------|")
    for name, data in sorted(mechanical, key=lambda item: item[0]):
        score = data.get("score", 100)
        strict = data.get("strict", score)
        issues = data.get("failing", 0)
        tier = data.get("tier", "")
        action = registry_mod.dimension_action_type(name)
        print(
            f"| {name} | {score:.1f}% | {strict:.1f}% | {issues} | T{tier} | {action} |"
        )
    if subjective:
        print("| **Subjective Dimensions** | | | | | |")
        for name, data in sorted(subjective, key=lambda item: item[0]):
            score = data.get("score", 100)
            strict = data.get("strict", score)
            issues = data.get("failing", 0)
            tier = data.get("tier", "")
            print(
                f"| {name} | {score:.1f}% | {strict:.1f}% | {issues} | T{tier} | review |"
            )
    print()


def _print_drag_summary(dim_scores: dict[str, Any]) -> None:
    """Print the biggest score-drag dimensions so agents know where to focus."""
    if not dim_scores:
        return
    try:
        breakdown = compute_health_breakdown(dim_scores)
        entries = breakdown.get("entries", [])
        drags = sorted(
            [e for e in entries if isinstance(e, dict) and float(e.get("overall_drag", 0) or 0) > 0.01],
            key=lambda e: -float(e.get("overall_drag", 0) or 0),
        )
        if drags:
            print("Biggest score drags (fixing these dimensions has the most impact):")
            for entry in drags[:5]:
                print(
                    f"  - {entry['name']}: -{float(entry['overall_drag']):.2f} pts "
                    f"(score {float(entry['score']):.1f}%, "
                    f"{float(entry['pool_share'])*100:.1f}% of {entry['pool']} pool)"
                )
            print()
    except (ImportError, TypeError, ValueError, KeyError) as exc:
        log_best_effort_failure(
            logger,
            "compute score drag summary for scan report",
            exc,
        )


def _print_stats_summary(
    state: StateModel,
    diff: dict[str, Any] | None,
    *,
    overall_score: float | None,
    strict_score: float | None,
) -> None:
    stats = state.get("stats", {})
    if not stats:
        return

    wontfix = stats.get("wontfix", 0)
    ignored = diff.get("ignored", 0) if diff else 0
    ignore_pats = diff.get("ignore_patterns", 0) if diff else 0
    strict_gap = (
        round((overall_score or 0) - (strict_score or 0), 1)
        if overall_score and strict_score
        else 0
    )
    print(
        f"Total issues: {stats.get('total', 0)} | "
        f"Open: {stats.get('open', 0)} | "
        f"Fixed: {stats.get('fixed', 0)} | "
        f"Wontfix: {wontfix}"
    )
    if wontfix or ignored or ignore_pats:
        print(
            f"Ignored: {ignored} (by {ignore_pats} patterns) | Strict gap: {strict_gap} pts"
        )
        print("Focus on strict score — wontfix and ignore inflate the lenient score.")
    print()


_WORKFLOW_GUIDE = build_workflow_guide(ATTEST_EXAMPLE)


def _print_workflow_guide() -> None:
    # Workflow guide — teach agents the full cycle
    print(_WORKFLOW_GUIDE)
    print()


def _print_narrative_status(narrative: dict[str, Any] | None) -> None:
    if not narrative:
        return

    headline = narrative.get("headline", "")
    strategy = narrative.get("strategy") or {}
    actions = narrative.get("actions", [])
    if headline:
        print(f"Current status: {headline}")
    hint = strategy.get("hint", "")
    if hint:
        print(f"Strategy: {hint}")
    if actions:
        top = actions[0]
        print(f"Top action: `{top['command']}` — {top['description']}")
    print()


def _detect_agent_interface() -> str | None:
    """Detect the current agent interface from environment variables."""
    # Check AGENT first — AMP sets both AGENT=amp and CLAUDECODE=1,
    # so we must identify it before falling through to the CLAUDECODE check.
    agent_var = os.environ.get("AGENT", "").lower()
    if agent_var == "amp":
        return "amp"
    if os.environ.get("CLAUDECODE"):
        return "claude"
    if os.environ.get("GEMINI_CLI"):
        return "gemini"
    if os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED") or os.environ.get("CODEX_SANDBOX"):
        return "codex"
    if os.environ.get("CURSOR_TRACE_ID"):
        return "cursor"
    return None


def _try_auto_update_skill() -> None:
    """Attempt to auto-install or auto-update the skill document.

    Best-effort: swallows all exceptions so a network failure or permission
    error never breaks the scan.
    """
    try:
        interface = _detect_agent_interface()
        installs = skill_docs_mod.find_installed_skills(interface=interface) if interface else skill_docs_mod.find_installed_skills()

        if interface is None:
            interface = resolve_interface(installs=installs)
        if interface is None:
            return

        active_install = skill_docs_mod.select_preferred_install(installs, interface=interface)
        if active_install and active_install.canonical and not active_install.stale:
            return
        if active_install and active_install.source_kind == "legacy_project":
            print("Migrating legacy project-scoped skill install to the native user location.")
        update_installed_skill(interface, "user" if interface in {"codex", "claude"} else "auto")
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        log_best_effort_failure(
            logger,
            "auto-update installed skill guidance",
            exc,
        )


def _print_badge_hint(badge_path: Path | None) -> None:
    if not (badge_path and badge_path.exists()):
        return

    rel_path = badge_path.name if badge_path.parent == get_project_root() else str(badge_path)
    print(f"A scorecard image was saved to `{rel_path}`.")
    print("Let the user know they can view it, and suggest adding it")
    print(f'to their README: `<img src="{rel_path}" width="100%">`')


def print_llm_summary(
    state: StateModel,
    badge_path: Path | None,
    narrative: dict[str, Any] | None = None,
    diff: dict[str, Any] | None = None,
) -> None:
    """Print a structured summary for LLM consumption.

    The LLM reads terminal output after running scans. This gives it
    clear instructions on how to present the results to the end user.
    Only shown when running inside an agent (CLAUDE_CODE or DESLOPPIFY_AGENT env).
    """
    if not is_agent_environment():
        return

    dim_scores = state.get("dimension_scores", {})
    scores = _load_scores(state)

    if _llm_summary_empty(scores, dim_scores):
        return

    _print_llm_header()
    plan_snapshot, has_plan = _load_living_plan_snapshot()

    if has_plan:
        _print_living_plan_notice(plan_snapshot)

    _print_score_lines(
        overall_score=scores.overall,
        objective_score=scores.objective,
        strict_score=scores.strict,
        verified_strict_score=scores.verified,
    )
    _print_dimension_table(state, dim_scores)
    _print_drag_summary(dim_scores)
    _print_stats_summary(
        state,
        diff,
        overall_score=scores.overall,
        strict_score=scores.strict,
    )
    if has_plan:
        print("\nFollow the living plan: `desloppify next` for your next execution task,")
        print("`desloppify backlog` for broader backlog discovery, and `desloppify plan` for plan details.")
    else:
        _print_workflow_guide()
    _print_narrative_status(narrative)
    _print_badge_hint(badge_path)
    print("─" * 60)

    if has_plan:
        print_user_message(
            "Hey — please follow the living plan. Run `desloppify"
            " next` for your next execution task. No need to reply, just"
            " continue."
        )


def _llm_summary_empty(scores: state_mod.ScoreSnapshot, dim_scores: dict[str, Any]) -> bool:
    return (
        scores.overall is None
        and scores.objective is None
        and scores.strict is None
        and scores.verified is None
        and not dim_scores
    )


def _print_llm_header() -> None:
    """Print the LLM instruction block header for agent-facing scan output.

    Side-effect only: prints framing text that tells LLM agents how to
    present scan results. Called from print_llm_summary.
    """
    print("─" * 60)
    print("INSTRUCTIONS FOR LLM")
    print("IMPORTANT: ALWAYS present ALL scores to the user after a scan.")
    print("Show overall health (lenient + strict), ALL dimension scores,")
    print("AND all subjective dimension scores in a markdown table.")
    print("The goal is to maximize strict scores. Never skip the scores.\n")


def _load_living_plan_snapshot() -> tuple[dict[str, object], bool]:
    fallback: dict[str, object] = {
        "queue_order": [],
        "clusters": {},
        "skipped": {},
        "active_cluster": None,
    }
    try:
        loaded_plan = load_plan()
    except PLAN_LOAD_EXCEPTIONS:
        return fallback, False
    if not isinstance(loaded_plan, dict):
        loaded_plan = {}
    loaded_plan.setdefault("queue_order", [])
    loaded_plan.setdefault("clusters", {})
    loaded_plan.setdefault("skipped", {})
    loaded_plan.setdefault("active_cluster", None)

    queue_order = loaded_plan.get("queue_order")
    clusters = loaded_plan.get("clusters")
    skipped = loaded_plan.get("skipped")
    active = loaded_plan.get("active_cluster")

    snapshot = {
        "queue_order": queue_order if isinstance(queue_order, list) else [],
        "clusters": clusters if isinstance(clusters, dict) else {},
        "skipped": skipped if isinstance(skipped, dict) else {},
        "active_cluster": active if isinstance(active, str) and active else None,
    }
    has_plan = bool(snapshot["queue_order"] or snapshot["clusters"] or snapshot["skipped"])
    return snapshot, has_plan


def _print_living_plan_notice(plan_snapshot: dict[str, object]) -> None:
    ordered = len(plan_snapshot.get("queue_order", []))
    skipped = len(plan_snapshot.get("skipped", {}))
    active = plan_snapshot.get("active_cluster")
    print(f"LIVING PLAN ACTIVE: {ordered} ordered, {skipped} skipped.")
    if isinstance(active, str) and active:
        cluster = plan_snapshot.get("clusters", {}).get(active)
        issue_ids = cluster.get("issue_ids", []) if isinstance(cluster, dict) else []
        remaining = len(issue_ids) if isinstance(issue_ids, list) else 0
        print(f"Focused on: {active} ({remaining} items remaining).")
    print("The plan is the single source of truth for work order.")
    print("Use `desloppify next` which respects the plan.")
    print("Use `desloppify plan` to view and update it.\n")


def auto_update_skill() -> None:
    """Auto-install or update the skill document if we detect an agent.

    Called unconditionally from the scan workflow — not gated on scores.
    """
    if not is_agent_environment():
        return

    active_interface = _detect_agent_interface()
    _try_auto_update_skill()

    # Single post-check: whatever happened above, is the doc current now?
    install = skill_docs_mod.find_installed_skill(active_interface)
    if not install:
        names = ", ".join(sorted(skill_docs_mod.SKILL_TARGETS))
        print(
            f"No skill document found. Install one for better workflow guidance: "
            f"desloppify update-skill <{names}>"
        )
    elif install.stale:
        update_hint = "desloppify update-skill"
        if install.interface:
            update_hint = f"desloppify update-skill {install.interface}"
        print(
            f"Skill document is outdated "
            f"(v{install.version}, current v{skill_docs_mod.SKILL_VERSION}). "
            f"Run: {update_hint}"
        )


__all__ = ["is_agent_environment", "print_llm_summary", "auto_update_skill"]
