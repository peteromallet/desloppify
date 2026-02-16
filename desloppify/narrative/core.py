"""Narrative orchestrator — compute_narrative() entry point."""

from __future__ import annotations

from ._constants import STRUCTURAL_MERGE
from ..command_vocab import ISSUES, REVIEW_PREPARE, SCAN, SHOW_WONTFIX, STATUS
from ..config import (
    DEFAULT_TARGET_STRICT_SCORE,
    MAX_TARGET_STRICT_SCORE,
    MIN_TARGET_STRICT_SCORE,
)

from .phase import _detect_phase, _detect_milestone
from .dimensions import _analyze_dimensions, _analyze_debt
from .actions import _compute_actions, _compute_tools
from .headline import _compute_headline
from .reminders import _compute_reminders
from .strategy import _compute_strategy

_RISK_SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


def _resolve_target_strict_score(config: dict | None) -> tuple[int, str | None]:
    """Resolve strict-score target from config with bounded fallback."""
    raw_target = DEFAULT_TARGET_STRICT_SCORE
    if isinstance(config, dict):
        raw_target = config.get("target_strict_score", DEFAULT_TARGET_STRICT_SCORE)
    try:
        target = int(raw_target)
    except (TypeError, ValueError):
        return (
            DEFAULT_TARGET_STRICT_SCORE,
            (
                f"Invalid config `target_strict_score={raw_target!r}`; using "
                f"{DEFAULT_TARGET_STRICT_SCORE}"
            ),
        )
    if target < MIN_TARGET_STRICT_SCORE or target > MAX_TARGET_STRICT_SCORE:
        return (
            DEFAULT_TARGET_STRICT_SCORE,
            (
                f"Invalid config `target_strict_score={raw_target!r}`; using "
                f"{DEFAULT_TARGET_STRICT_SCORE}"
            ),
        )
    return target, None


def _compute_strict_target(strict_score: float | None, config: dict | None) -> dict:
    """Build strict-target context for command rendering and agents."""
    target, warning = _resolve_target_strict_score(config)
    if not isinstance(strict_score, (int, float)):
        return {
            "target": float(target),
            "current": None,
            "gap": None,
            "state": "unavailable",
            "warning": warning,
        }

    current = round(float(strict_score), 1)
    gap = round(float(target) - current, 1)
    if gap > 0:
        state = "below"
    elif gap < 0:
        state = "above"
    else:
        state = "at"
    return {
        "target": float(target),
        "current": current,
        "gap": gap,
        "state": state,
        "warning": warning,
    }


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
                except UnicodeDecodeError:
                    # Non-UTF8 README should not crash narrative generation.
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


def _compute_primary_action(actions: list[dict]) -> dict | None:
    """Extract the top action in a stable, compact form."""
    if not actions:
        return None
    top = actions[0]
    return {
        "priority": top.get("priority"),
        "type": top.get("type"),
        "detector": top.get("detector"),
        "command": top.get("command"),
        "description": top.get("description"),
        "impact": top.get("impact"),
        "lane": top.get("lane"),
        "count": top.get("count"),
    }


def _compute_why_now(
    phase: str,
    dimensions: dict,
    debt: dict,
    by_det: dict[str, int],
    primary_action: dict | None,
) -> str:
    """Explain why the selected action matters in the current context."""
    security_open = by_det.get("security", 0)
    if security_open > 0:
        s = "s" if security_open != 1 else ""
        return f"{security_open} security finding{s} remain open, so risk reduction should be first."

    if phase == "stagnation":
        return "Progress is plateaued, so the top action is the best chance to break the plateau."

    if primary_action:
        detector = primary_action.get("detector")
        impact = primary_action.get("impact")
        if isinstance(impact, (int, float)) and impact > 0:
            if detector:
                return f"`{detector}` has the highest modeled strict-score impact right now (+{impact:.1f})."
            return f"The top action has the highest modeled strict-score impact right now (+{impact:.1f})."
        if detector:
            return f"`{detector}` is currently the highest-priority unresolved workstream."

    lowest = dimensions.get("lowest_dimensions", [])
    if lowest:
        dim = lowest[0]
        return f"{dim['name']} is the lowest strict dimension ({dim['strict']}%), so it is the current bottleneck."

    if debt.get("overall_gap", 0) > 2:
        return f"Strict score is lagging by {debt['overall_gap']} points due to unresolved debt pressure."

    return "The next action is prioritized by detector severity, impact, and workflow ordering."


def _compute_verification_step(primary_action: dict | None) -> dict | None:
    """Return the explicit follow-up check for the selected action."""
    if not primary_action:
        return None

    action_type = primary_action.get("type")
    if action_type == "issue_queue":
        return {
            "command": ISSUES,
            "reason": "Confirm each review finding has investigation notes and a clear disposition.",
            "success_signal": "Review queue trends down with concrete investigation artifacts.",
        }
    if action_type == "debt_review":
        return {
            "command": SHOW_WONTFIX,
            "reason": "Re-check stale wontfix decisions before treating strict score as stable.",
            "success_signal": "Wontfix list reflects only intentional and still-valid exceptions.",
        }

    return {
        "command": SCAN,
        "reason": "Re-scan to verify the change and catch cascading findings before reporting progress.",
        "success_signal": "Open findings drop and strict score direction remains positive.",
    }


def _compute_risk_flags(state: dict, by_det: dict[str, int], debt: dict, config: dict | None) -> list[dict]:
    """Compute high-signal risks that can invalidate progress claims."""
    flags: list[dict] = []

    security_open = by_det.get("security", 0)
    if security_open > 0:
        s = "s" if security_open != 1 else ""
        flags.append({
            "type": "security_open",
            "severity": "high",
            "message": f"{security_open} open security finding{s} still require manual review.",
            "command": "desloppify show security --status open",
        })

    ignore_integrity = state.get("ignore_integrity", {}) or {}
    ignored = int(ignore_integrity.get("ignored", 0) or 0)
    suppressed_pct = float(ignore_integrity.get("suppressed_pct", 0.0) or 0.0)
    if ignored > 0 and suppressed_pct >= 30:
        flags.append({
            "type": "high_ignore_suppression",
            "severity": "high",
            "message": f"{suppressed_pct:.1f}% of findings are hidden by ignore patterns.",
            "command": STATUS,
        })

    if debt.get("overall_gap", 0) >= 5 and debt.get("wontfix_count", 0) > 0:
        flags.append({
            "type": "wontfix_gap",
            "severity": "medium",
            "message": (f"{debt['overall_gap']} strict-score points are masked by wontfix debt "
                        f"({debt.get('wontfix_count', 0)} items)."),
            "command": SHOW_WONTFIX,
        })

    completeness = state.get("scan_completeness", {})
    incomplete = [lang for lang, status in sorted(completeness.items()) if status != "full"]
    if incomplete:
        flags.append({
            "type": "incomplete_scan",
            "severity": "medium",
            "message": f"Incomplete scans for: {', '.join(incomplete)} (slow phases skipped).",
            "command": f"{SCAN} --profile full",
        })

    review_cache = state.get("review_cache", {}) or {}
    raw_review_max_age = ((config if isinstance(config, dict) else {}) or {}).get("review_max_age_days", 30)
    try:
        review_max_age = int(raw_review_max_age)
    except (TypeError, ValueError):
        review_max_age = 30
    if review_max_age < 0:
        review_max_age = 0
    if review_max_age > 0 and review_cache.get("files"):
        from datetime import datetime as _dt, timezone as _tz
        try:
            oldest_str = min(
                f["reviewed_at"] for f in review_cache["files"].values()
                if f.get("reviewed_at")
            )
            oldest = _dt.fromisoformat(oldest_str)
            age_days = (_dt.now(_tz.utc) - oldest).days
            if age_days > review_max_age:
                flags.append({
                    "type": "stale_review_context",
                    "severity": "medium",
                    "message": f"Review context is stale ({age_days} days old).",
                    "command": REVIEW_PREPARE,
                })
        except (ValueError, TypeError):
            pass

    flags.sort(key=lambda f: (
        _RISK_SEVERITY_ORDER.get(str(f.get("severity", "info")), _RISK_SEVERITY_ORDER["info"]),
        str(f.get("type", "")),
    ))
    return flags


def compute_narrative(state: dict, *, diff: dict | None = None,
                      lang: str | None = None,
                      command: str | None = None,
                      config: dict | None = None) -> dict:
    """Compute structured narrative context from state data.

    Returns a dict with:
    phase, headline, dimensions, actions, strategy, tools, debt, milestone,
    primary_action, why_now, verification_step, risk_flags, reminders,
    strict_target.

    Args:
        state: Current state dict.
        diff: Scan diff (only present after a scan).
        lang: Language plugin name.
        command: The command that triggered this (e.g. "scan", "fix", "resolve").
        config: Project config dict (optional; loaded from disk if not provided).
    """
    raw_history = state.get("scan_history", [])
    cfg = config if isinstance(config, dict) else None
    # Filter history to current language to avoid mixing trajectories.
    # Include entries without a lang field (pre-date this feature) for backward compat.
    history = ([h for h in raw_history if h.get("lang") in (lang, None)]
               if lang else raw_history)
    dim_scores = state.get("dimension_scores", {})
    stats = state.get("stats", {})
    from ..state import get_overall_score, get_strict_score
    strict_score = get_strict_score(state)
    overall_score = get_overall_score(state)
    from ..state import path_scoped_findings
    findings = path_scoped_findings(state.get("findings", {}), state.get("scan_path"))

    by_det = _count_open_by_detector(findings)
    badge = _compute_badge_status()

    phase = _detect_phase(history, strict_score)
    dimensions = _analyze_dimensions(dim_scores, history, state)
    debt = _analyze_debt(dim_scores, findings, history)
    milestone = _detect_milestone(state, diff, history)
    actions = _compute_actions(by_det, dim_scores, state, debt, lang)
    strategy = _compute_strategy(findings, by_det, actions, phase, lang)
    tools = _compute_tools(by_det, state, lang, badge)
    headline = _compute_headline(phase, dimensions, debt, milestone, diff,
                                 strict_score, overall_score, stats, history,
                                 open_by_detector=by_det)
    reminders, updated_reminder_history = _compute_reminders(
        state, lang, phase, debt, actions, dimensions, badge, command,
        config=cfg)
    primary_action = _compute_primary_action(actions)
    why_now = _compute_why_now(phase, dimensions, debt, by_det, primary_action)
    verification_step = _compute_verification_step(primary_action)
    risk_flags = _compute_risk_flags(state, by_det, debt, cfg)
    strict_target = _compute_strict_target(strict_score, cfg)

    return {
        "phase": phase,
        "headline": headline,
        "dimensions": dimensions,
        "actions": actions,
        "strategy": strategy,
        "tools": tools,
        "debt": debt,
        "milestone": milestone,
        "primary_action": primary_action,
        "why_now": why_now,
        "verification_step": verification_step,
        "risk_flags": risk_flags,
        "strict_target": strict_target,
        "reminders": reminders,
        "reminder_history": updated_reminder_history,
    }
