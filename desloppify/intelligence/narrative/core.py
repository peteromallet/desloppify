"""Narrative orchestrator — compute_narrative() entry point."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypedDict

from desloppify.core.config import load_config as _load_config
from desloppify.intelligence.narrative._constants import STRUCTURAL_MERGE
from desloppify.state import get_overall_score, get_strict_score, path_scoped_findings
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.intelligence.narrative.action_engine import compute_actions
from desloppify.intelligence.narrative.action_models import ActionContext
from desloppify.intelligence.narrative.action_tools import compute_tools
from desloppify.intelligence.narrative.dimensions import (
    _analyze_debt,
    _analyze_dimensions,
)
from desloppify.intelligence.narrative.headline import _compute_headline
from desloppify.intelligence.narrative.phase import _detect_milestone, _detect_phase
from desloppify.intelligence.narrative.reminders import _compute_reminders
from desloppify.intelligence.narrative.strategy_engine import compute_strategy

_RISK_SEVERITY_ORDER = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}
DEFAULT_TARGET_STRICT_SCORE = 95
MIN_TARGET_STRICT_SCORE = 0
MAX_TARGET_STRICT_SCORE = 100
_HIGH_IGNORE_SUPPRESSION_THRESHOLD = 30.0
_WONTFIX_GAP_THRESHOLD = 1.0


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
    if not isinstance(strict_score, int | float):
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
    by_detector: dict[str, int] = {}
    for f in findings.values():
        if f["status"] != "open":
            continue
        detector = f.get("detector", "unknown")
        if detector in STRUCTURAL_MERGE:
            detector = "structural"
        by_detector[detector] = by_detector.get(detector, 0) + 1
        # Track holistic review findings separately
        if detector == "review" and f.get("detail", {}).get("holistic"):
            by_detector["review_holistic"] = by_detector.get("review_holistic", 0) + 1
    # Track uninvestigated review findings (only when review findings exist)
    if by_detector.get("review", 0) > 0:
        by_detector["review_uninvestigated"] = sum(
            1
            for f in findings.values()
            if f.get("status") == "open"
            and f.get("detector") == "review"
            and not f.get("detail", {}).get("investigation")
        )
    return by_detector


def _resolve_badge_path(project_root: Path) -> tuple[str, Path]:
    """Resolve badge path from config, defaulting to root-level scorecard.png."""
    default_rel = "scorecard.png"
    config = {}
    try:
        config = _load_config()
    except (AttributeError, OSError):
        config = {}

    raw_path = default_rel
    if isinstance(config, dict):
        configured = config.get("badge_path")
        if isinstance(configured, str) and configured.strip():
            raw_path = configured.strip()

    path = Path(raw_path)
    is_root_anchored = bool(path.root)
    if not path.is_absolute() and not is_root_anchored:
        return raw_path, project_root / path

    try:
        rel_path = str(path.relative_to(project_root))
    except ValueError:
        rel_path = str(path)
    return rel_path, path


def _compute_badge_status() -> dict:
    """Check configured scorecard path and whether README references it."""
    project_root = PROJECT_ROOT

    scorecard_rel, scorecard_path = _resolve_badge_path(project_root)
    generated = scorecard_path.exists()

    in_readme = False
    if generated:
        for readme_name in ("README.md", "readme.md", "README.MD"):
            readme_path = project_root / readme_name
            if readme_path.exists():
                try:
                    in_readme = scorecard_rel in readme_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    in_readme = False
                break

    recommendation = None
    if generated and not in_readme:
        recommendation = (
            f'Add to README: <img src="{scorecard_rel}" width="100%">'
        )

    return {
        "generated": generated,
        "in_readme": in_readme,
        "path": scorecard_rel,
        "recommendation": recommendation,
    }


def _compute_primary_action(actions: list[dict]) -> dict | None:
    """Pick the highest-priority action for user-facing guidance."""
    if not actions:
        return None
    top = actions[0]
    command = str(top.get("command", "")).strip()
    if not command:
        return None
    description = str(top.get("description", "")).strip() or "run highest-impact action"
    return {
        "command": command,
        "description": description,
    }


def _compute_why_now(
    phase: str,
    strategy: dict[str, object],
    primary_action: dict | None,
) -> str:
    """Explain why the recommended action should happen now."""
    hint = str(strategy.get("hint", "")).strip() if isinstance(strategy, dict) else ""
    if hint:
        return hint
    if primary_action and primary_action.get("description"):
        return str(primary_action["description"])
    phase_default = {
        "first_scan": "Start with highest-impact findings to establish a clean baseline.",
        "regression": "Recent regressions should be contained before new work.",
        "stagnation": "Current approach is stalling; tackle a different high-impact lane.",
        "maintenance": "Keep the codebase stable by resolving new risk quickly.",
    }
    return phase_default.get(phase, "Address the highest-impact open findings first.")


def _compute_verification_step(_command: str | None) -> dict[str, str]:
    """Verification step returned with every narrative plan."""
    return {
        "command": "desloppify scan",
        "reason": "revalidate after changes",
    }


def _compute_risk_flags(state: dict, debt: dict) -> list[dict]:
    """Build ordered risk flags from suppression and wontfix debt signals."""
    flags: list[dict] = []

    ignore_integrity = state.get("ignore_integrity", {})
    suppressed_pct = float(ignore_integrity.get("suppressed_pct", 0.0) or 0.0)
    ignored_count = int(ignore_integrity.get("ignored", 0) or 0)
    if (
        suppressed_pct >= _HIGH_IGNORE_SUPPRESSION_THRESHOLD
        or ignored_count >= 100
    ):
        severity = "high" if suppressed_pct >= 40.0 or ignored_count >= 200 else "medium"
        message = (
            f"{suppressed_pct:.1f}% findings hidden by ignore patterns"
            if suppressed_pct > 0
            else f"{ignored_count} findings hidden by ignore patterns"
        )
        flags.append(
            {
                "type": "high_ignore_suppression",
                "severity": severity,
                "message": message,
            }
        )

    wontfix_count = int(debt.get("wontfix_count", 0) or 0)
    overall_gap = float(debt.get("overall_gap", 0.0) or 0.0)
    if overall_gap >= _WONTFIX_GAP_THRESHOLD or wontfix_count > 0:
        severity = "high" if overall_gap >= 5.0 or wontfix_count >= 50 else "medium"
        flags.append(
            {
                "type": "wontfix_gap",
                "severity": severity,
                "message": (
                    f"Strict/lenient gap is {overall_gap:.1f} pts with "
                    f"{wontfix_count} wontfix findings"
                ),
            }
        )

    flags.sort(key=lambda flag: _RISK_SEVERITY_ORDER.get(flag.get("severity"), 99))
    return flags


@dataclass(frozen=True)
class NarrativeContext:
    """Optional context inputs for narrative computation."""

    diff: dict | None = None
    lang: str | None = None
    command: str | None = None
    config: dict | None = None

def _history_for_lang(raw_history: list[dict], lang: str | None) -> list[dict]:
    if not lang:
        return raw_history
    return [entry for entry in raw_history if entry.get("lang") in (lang, None)]


def _scoped_findings(state: dict) -> dict:
    return path_scoped_findings(
        state.get("findings", {}), state.get("scan_path")
    )


def _score_snapshot(state: dict) -> tuple[float | None, float | None]:
    return get_strict_score(state), get_overall_score(state)


class NarrativeResult(TypedDict):
    """Structured result from compute_narrative()."""

    phase: str
    headline: str | None
    dimensions: dict[str, Any]
    actions: list[dict[str, Any]]
    strategy: dict[str, Any]
    tools: dict[str, Any]
    debt: dict[str, Any]
    milestone: str | None
    primary_action: dict[str, str] | None
    why_now: str | None
    verification_step: dict[str, str]
    risk_flags: list[dict[str, Any]]
    strict_target: dict[str, Any]
    reminders: list[dict[str, Any]]
    reminder_history: dict[str, int]


def compute_narrative(
    state: dict,
    context: NarrativeContext | None = None,
) -> NarrativeResult:
    """Compute structured narrative context from state data."""
    resolved_context = context or NarrativeContext()

    diff = resolved_context.diff
    lang = resolved_context.lang
    command = resolved_context.command
    config = resolved_context.config

    raw_history = state.get("scan_history", [])
    history = _history_for_lang(raw_history, lang)
    dim_scores = state.get("dimension_scores", {})
    stats = state.get("stats", {})
    strict_score, overall_score = _score_snapshot(state)
    findings = _scoped_findings(state)

    by_detector = _count_open_by_detector(findings)
    badge = _compute_badge_status()

    phase = _detect_phase(history, strict_score)
    dimensions = _analyze_dimensions(dim_scores, history, state)
    debt = _analyze_debt(dim_scores, findings, history)
    milestone = _detect_milestone(state, None, history)
    action_context = ActionContext(
        by_detector=by_detector,
        dimension_scores=dim_scores,
        state=state,
        debt=debt,
        lang=lang,
    )
    actions = [dict(action) for action in compute_actions(action_context)]
    strategy = compute_strategy(findings, by_detector, actions, phase, lang)
    tools = dict(compute_tools(by_detector, state, lang, badge))
    primary_action = _compute_primary_action(actions)
    why_now = _compute_why_now(phase, strategy, primary_action)
    verification_step = _compute_verification_step(command)
    risk_flags = _compute_risk_flags(state, debt)
    strict_target = _compute_strict_target(strict_score, config)
    headline = _compute_headline(
        phase,
        dimensions,
        debt,
        milestone,
        diff,
        strict_score,
        overall_score,
        stats,
        history,
        open_by_detector=by_detector,
    )
    reminders, updated_reminder_history = _compute_reminders(
        state, lang, phase, debt, actions, dimensions, badge, command, config=config
    )

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
