"""Narrative orchestrator — compute_narrative() entry point."""

from __future__ import annotations

from ._constants import STRUCTURAL_MERGE

from .phase import _detect_phase, _detect_milestone
from .dimensions import _analyze_dimensions, _analyze_debt
from .actions import _compute_actions, _compute_tools
from .headline import _compute_headline
from .reminders import _compute_reminders
from .strategy import _compute_strategy


def _count_open_by_detector(findings: dict) -> dict[str, int]:
    """Count open findings by detector, merging structural sub-detectors.

    When detector is "review" and detail.holistic is True, also increments
    "review_holistic" for separate holistic counting.
    """
    by_det: dict[str, int] = {}
    for f in findings.values():
        if f["status"] != "open":
            continue
        det = f.get("detector", "unknown")
        if det in STRUCTURAL_MERGE:
            det = "structural"
        by_det[det] = by_det.get(det, 0) + 1
        # Track holistic review findings separately
        if det == "review" and f.get("detail", {}).get("holistic"):
            by_det["review_holistic"] = by_det.get("review_holistic", 0) + 1
    # Track uninvestigated review findings (only when review findings exist)
    if by_det.get("review", 0) > 0:
        by_det["review_uninvestigated"] = sum(
            1 for f in findings.values()
            if f.get("status") == "open" and f.get("detector") == "review"
            and not f.get("detail", {}).get("investigation")
        )
    return by_det


def _compute_badge_status() -> dict:
    """Check if scorecard.png exists and whether README references it."""
    from ..utils import PROJECT_ROOT

    scorecard_path = PROJECT_ROOT / "scorecard.png"
    generated = scorecard_path.exists()

    in_readme = False
    if generated:
        for readme_name in ("README.md", "readme.md", "README.MD"):
            readme_path = PROJECT_ROOT / readme_name
            if readme_path.exists():
                try:
                    in_readme = "scorecard.png" in readme_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    pass
                break

    recommendation = None
    if generated and not in_readme:
        recommendation = 'Add to README: <img src="scorecard.png" width="100%">'

    return {
        "generated": generated,
        "in_readme": in_readme,
        "path": "scorecard.png",
        "recommendation": recommendation,
    }


def compute_narrative(state: dict, *, diff: dict | None = None,
                      lang: str | None = None,
                      command: str | None = None,
                      config: dict | None = None) -> dict:
    """Compute structured narrative context from state data.

    Returns a dict with: phase, headline, dimensions, actions, tools, debt, milestone.

    Args:
        state: Current state dict.
        diff: Scan diff (only present after a scan).
        lang: Language name (e.g. "python", "typescript").
        command: The command that triggered this (e.g. "scan", "fix", "resolve").
        config: Project config dict (optional; loaded from disk if not provided).
    """
    raw_history = state.get("scan_history", [])
    # Filter history to current language to avoid mixing trajectories.
    # Include entries without a lang field (pre-date this feature) for backward compat.
    history = ([h for h in raw_history if h.get("lang") in (lang, None)]
               if lang else raw_history)
    dim_scores = state.get("dimension_scores", {})
    stats = state.get("stats", {})
    obj_strict = state.get("objective_strict")
    obj_score = state.get("objective_score")
    from ..state import path_scoped_findings
    findings = path_scoped_findings(state.get("findings", {}), state.get("scan_path"))

    by_det = _count_open_by_detector(findings)
    badge = _compute_badge_status()

    phase = _detect_phase(history, obj_strict)
    dimensions = _analyze_dimensions(dim_scores, history, state)
    debt = _analyze_debt(dim_scores, findings, history)
    milestone = _detect_milestone(state, diff, history)
    actions = _compute_actions(by_det, dim_scores, state, debt, lang)
    strategy = _compute_strategy(findings, by_det, actions, phase, lang)
    tools = _compute_tools(by_det, lang, badge)
    headline = _compute_headline(phase, dimensions, debt, milestone, diff,
                                 obj_strict, obj_score, stats, history,
                                 open_by_detector=by_det)
    reminders, updated_reminder_history = _compute_reminders(
        state, lang, phase, debt, actions, dimensions, badge, command,
        config=config)

    return {
        "phase": phase,
        "headline": headline,
        "dimensions": dimensions,
        "actions": actions,
        "strategy": strategy,
        "tools": tools,
        "debt": debt,
        "milestone": milestone,
        "reminders": reminders,
        "reminder_history": updated_reminder_history,
    }
