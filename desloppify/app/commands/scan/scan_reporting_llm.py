"""LLM-facing reporting helpers for scan command."""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent

from desloppify import scoring as scoring_mod
from desloppify import state as state_mod
from desloppify import utils as utils_mod
from desloppify.app.output.scorecard_parts import projection as scorecard_projection_mod
from desloppify.core import registry as registry_mod
from desloppify.engine.work_queue import ATTEST_EXAMPLE
from desloppify.core._internal.text_utils import PROJECT_ROOT


def _is_agent_environment() -> bool:
    return bool(
        os.environ.get("CLAUDE_CODE")
        or os.environ.get("DESLOPPIFY_AGENT")
        or os.environ.get("GEMINI_CLI")
        or os.environ.get("CODEX_SANDBOX_NETWORK_DISABLED")
        or os.environ.get("CODEX_SANDBOX")
        or os.environ.get("CURSOR_TRACE_ID")
    )


def _load_scores(state: dict) -> state_mod.ScoreSnapshot:
    """Load all four canonical scores from state."""
    return state_mod.score_snapshot(state)


def _print_score_lines(
    *,
    overall_score: float | None,
    objective_score: float | None,
    strict_score: float | None,
    verified_score: float | None,
) -> None:
    lines: list[str] = []
    if overall_score is not None:
        lines.append(f"Overall score:   {overall_score:.1f}/100")
    if objective_score is not None:
        lines.append(f"Objective score: {objective_score:.1f}/100")
    if strict_score is not None:
        lines.append(f"Strict score:    {strict_score:.1f}/100")
    if verified_score is not None:
        lines.append(f"Verified score:  {verified_score:.1f}/100")
    if lines:
        print("\n".join(lines))
    print()


def _split_dimension_scores(
    state: dict,
    dim_scores: dict,
) -> tuple[list[tuple[str, dict]], list[tuple[str, dict]]]:
    # Build dimension table from canonical scorecard projection.
    rows = scorecard_projection_mod.scorecard_dimension_rows(
        state, dim_scores=dim_scores
    )
    subjective_name_set = {name.lower() for name in scoring_mod.DISPLAY_NAMES.values()}
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


def _print_dimension_table(state: dict, dim_scores: dict) -> None:
    mechanical, subjective = _split_dimension_scores(state, dim_scores)
    if not (mechanical or subjective):
        return

    print("| Dimension | Health | Strict | Issues | Tier | Action |")
    print("|-----------|--------|--------|--------|------|--------|")
    for name, data in sorted(mechanical, key=lambda item: item[0]):
        score = data.get("score", 100)
        strict = data.get("strict", score)
        issues = data.get("issues", 0)
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
            issues = data.get("issues", 0)
            tier = data.get("tier", "")
            print(
                f"| {name} | {score:.1f}% | {strict:.1f}% | {issues} | T{tier} | review |"
            )
    print()


def _print_stats_summary(
    state: dict,
    diff: dict | None,
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
        f"Total findings: {stats.get('total', 0)} | "
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


_WORKFLOW_GUIDE = dedent(
    f"""
    ## Workflow Guide

    1. **Review findings first** (if any): `desloppify issues` — high-value subjective findings
    2. **Run auto-fixers** (if available): `desloppify fix <fixer> --dry-run` to preview, then apply
    3. **Manual fixes**: `desloppify next` — highest-priority item. Fix it, then:
       `desloppify resolve fixed "<id>" --note "<what you did>" --attest "{ATTEST_EXAMPLE}"`
       Required attestation keywords: 'I have actually' and 'not gaming'.
    4. **Rescan**: `desloppify scan --path <path>` — verify improvements, catch cascading effects
    5. **Reset subjective baseline when needed**:
       `desloppify scan --path <path> --reset-subjective` (then run a fresh review/import cycle)
    6. **Check progress**: `desloppify status` — dimension scores dashboard

    ### Decision Guide
    - **Tackle**: T1/T2 (high impact), auto-fixable, security findings
    - **Consider skipping**: T4 low-confidence, test/config zone findings (lower impact)
    - **Wontfix**: Intentional patterns, false positives →
      `desloppify resolve wontfix "<id>" --note "<why>" --attest "{ATTEST_EXAMPLE}"`
    - **Batch wontfix**: Multiple intentional patterns →
      `desloppify resolve wontfix "<detector>::*::<category>" --note "<why>" --attest "{ATTEST_EXAMPLE}"`

    ### Understanding Dimensions
    - **Mechanical** (File health, Code quality, etc.): Fix code → rescan
    - **Subjective** (Naming Quality, Logic Clarity, etc.): Address review findings → re-review
    - **Health vs Strict**: Health ignores wontfix; Strict penalizes it. Focus on Strict.
    """
).strip()


def _print_workflow_guide() -> None:
    # Workflow guide — teach agents the full cycle
    print(_WORKFLOW_GUIDE)
    print()


def _print_narrative_status(narrative: dict | None) -> None:
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
    if os.environ.get("CLAUDE_CODE"):
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
    install = utils_mod.find_installed_skill()

    if install and not install.stale:
        return  # Up to date.

    try:
        from desloppify.app.commands.update_skill import (
            resolve_interface,
            update_installed_skill,
        )

        if install:
            interface = resolve_interface(install=install)
        else:
            interface = _detect_agent_interface()

        if interface:
            update_installed_skill(interface)
    except Exception:  # noqa: BLE001
        pass


def _print_badge_hint(badge_path: Path | None) -> None:
    if not (badge_path and badge_path.exists()):
        return

    rel_path = badge_path.name if badge_path.parent == PROJECT_ROOT else str(badge_path)
    print(f"A scorecard image was saved to `{rel_path}`.")
    print("Let the user know they can view it, and suggest adding it")
    print(f'to their README: `<img src="{rel_path}" width="100%">`')


def _print_llm_summary(
    state: dict,
    badge_path: Path | None,
    narrative: dict | None = None,
    diff: dict | None = None,
):
    """Print a structured summary for LLM consumption.

    The LLM reads terminal output after running scans. This gives it
    clear instructions on how to present the results to the end user.
    Only shown when running inside an agent (CLAUDE_CODE or DESLOPPIFY_AGENT env).
    """
    if not _is_agent_environment():
        return

    dim_scores = state.get("dimension_scores", {})
    scores = _load_scores(state)

    if (
        scores.overall is None
        and scores.objective is None
        and scores.strict is None
        and scores.verified is None
        and not dim_scores
    ):
        return

    print("─" * 60)
    print("INSTRUCTIONS FOR LLM")
    print("IMPORTANT: ALWAYS present ALL scores to the user after a scan.")
    print("Show overall health (lenient + strict), ALL dimension scores,")
    print("AND all subjective dimension scores in a markdown table.")
    print("The goal is to maximize strict scores. Never skip the scores.\n")

    _print_score_lines(
        overall_score=scores.overall,
        objective_score=scores.objective,
        strict_score=scores.strict,
        verified_score=scores.verified,
    )
    _print_dimension_table(state, dim_scores)
    _print_stats_summary(
        state,
        diff,
        overall_score=scores.overall,
        strict_score=scores.strict,
    )
    _print_workflow_guide()
    _print_narrative_status(narrative)
    _print_badge_hint(badge_path)
    print("─" * 60)


def auto_update_skill() -> None:
    """Auto-install or update the skill document if we detect an agent.

    Called unconditionally from the scan workflow — not gated on scores.
    """
    if not _is_agent_environment():
        return

    _try_auto_update_skill()

    # Single post-check: whatever happened above, is the doc current now?
    install = utils_mod.find_installed_skill()
    if not install:
        names = ", ".join(sorted(utils_mod.SKILL_TARGETS))
        print(
            f"No skill document found. Install one for better workflow guidance: "
            f"desloppify update-skill <{names}>"
        )
    elif install.stale:
        print(
            f"Skill document is outdated "
            f"(v{install.version}, current v{utils_mod.SKILL_VERSION}). "
            f"Run: desloppify update-skill"
        )


__all__ = ["_print_llm_summary", "auto_update_skill"]
