"""Payload and artifact helpers for scan command output."""

from __future__ import annotations

import importlib
import logging
import os
from pathlib import Path

from desloppify.app.commands.scan.contracts import ScanQueryPayload
from desloppify.app.commands.scan.workflow import (
    ScanMergeResult,
    ScanNoiseSnapshot,
)
from desloppify.base.config import config_for_query
from desloppify.base.exception_sets import PLAN_LOAD_EXCEPTIONS
from desloppify.base.output.fallbacks import log_best_effort_failure
from desloppify.base.output.terminal import colorize
from desloppify.base.output.contract import OutputResult
from desloppify.base.discovery.paths import get_project_root
from desloppify.engine._scoring.results.core import compute_health_breakdown
from desloppify.engine._state.filtering import open_scope_breakdown
from desloppify.engine.plan_state import load_plan
from desloppify.state_scoring import score_snapshot

logger = logging.getLogger(__name__)


def build_scan_query_payload(
    state: dict[str, object],
    config: dict[str, object],
    profile: str,
    diff: dict[str, object],
    warnings: list[str],
    narrative: dict[str, object],
    merge: ScanMergeResult,
    noise: ScanNoiseSnapshot,
) -> ScanQueryPayload:
    """Build the canonical query payload persisted after a scan."""
    scores = score_snapshot(state)
    issues = state.get("issues", {})
    open_scope = (
        open_scope_breakdown(issues, state.get("scan_path"))
        if isinstance(issues, dict)
        else None
    )
    payload = {
        "command": "scan",
        "overall_score": scores.overall,
        "objective_score": scores.objective,
        "strict_score": scores.strict,
        "verified_strict_score": scores.verified,
        "prev_overall_score": merge.prev_overall,
        "prev_objective_score": merge.prev_objective,
        "prev_strict_score": merge.prev_strict,
        "prev_verified_strict_score": merge.prev_verified,
        "profile": profile,
        "noise_budget": noise.noise_budget,
        "noise_global_budget": noise.global_noise_budget,
        "hidden_by_detector": noise.hidden_by_detector,
        "hidden_total": noise.hidden_total,
        "diff": diff,
        "stats": state["stats"],
        "open_scope": open_scope,
        "warnings": warnings,
        "dimension_scores": state.get("dimension_scores"),
        "score_breakdown": compute_health_breakdown(state.get("dimension_scores", {})),
        "subjective_integrity": state.get("subjective_integrity"),
        "score_confidence": state.get("score_confidence"),
        "potentials": state.get("potentials"),
        "scan_coverage": state.get("scan_coverage"),
        "zone_distribution": state.get("zone_distribution"),
        "narrative": narrative,
        "config": config_for_query(config),
    }

    # Add plan context if a living plan exists
    try:
        plan = load_plan()
        if plan.get("queue_order") or plan.get("clusters") or plan.get("skipped"):
            payload["plan"] = {
                "active": True,
                "focus": plan.get("active_cluster"),
                "total_ordered": len(plan.get("queue_order", [])),
                "total_skipped": len(plan.get("skipped", {})),
                "plan_overrides_narrative": True,
            }
    except PLAN_LOAD_EXCEPTIONS as exc:
        log_best_effort_failure(logger, "load plan context for scan artifacts", exc)

    return payload


def _load_scorecard_helpers():
    """Load scorecard helper callables lazily via importlib.

    Deferred: scorecard depends on PIL (optional dependency).
    """
    try:
        scorecard_module = importlib.import_module("desloppify.app.output.scorecard")
    except ImportError:
        return None, None
    generate = getattr(scorecard_module, "generate_scorecard", None)
    badge_config = getattr(scorecard_module, "get_badge_config", None)
    return generate, badge_config


def _missing_scorecard_result(args, config: dict[str, object]) -> tuple[Path | None, OutputResult]:
    explicit_badge_request = bool(
        getattr(args, "badge_path", None)
        or config.get("badge_path")
        or os.environ.get("DESLOPPIFY_BADGE_PATH")
    )
    if explicit_badge_request:
        print(
            colorize(
                "  Scorecard support not installed. Install with: pip install \"desloppify[scorecard]\"",
                "yellow",
            )
        )
        return None, OutputResult(
            ok=False,
            status="error",
            message="scorecard support not installed",
            error_kind="scorecard_dependency_missing",
        )
    return None, OutputResult(ok=True, status="skipped", message="badge generation disabled")


def _badge_relative_path(badge_path: Path) -> str:
    try:
        return str(badge_path.relative_to(get_project_root()))
    except ValueError:
        return str(badge_path)


def _readme_references_badge(rel_path: str) -> bool:
    for readme_name in ("README.md", "readme.md", "README.MD"):
        readme_path = get_project_root() / readme_name
        if not readme_path.exists():
            continue
        try:
            return rel_path in readme_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return False
    return False


def emit_scorecard_badge(
    args, config: dict[str, object], state: dict[str, object]
) -> tuple[Path | None, OutputResult]:
    """Generate a scorecard image badge and print usage hints."""
    generate_scorecard, get_badge_config = _load_scorecard_helpers()
    if not callable(generate_scorecard) or not callable(get_badge_config):
        return _missing_scorecard_result(args, config)

    try:
        badge_path, disabled = get_badge_config(args, config)
    except OSError as exc:
        print(
            colorize(f"  ⚠ Could not resolve scorecard badge path: {exc}", "yellow")
        )
        return None, OutputResult(
            ok=False,
            status="error",
            message=str(exc),
            error_kind="badge_path_resolution_error",
        )
    if disabled or not badge_path:
        return None, OutputResult(ok=True, status="skipped", message="badge generation disabled")

    try:
        generate_scorecard(state, badge_path)
    except (OSError, ImportError) as exc:
        print(colorize(f"  ⚠ Could not generate scorecard badge: {exc}", "yellow"))
        return None, OutputResult(
            ok=False,
            status="error",
            message=str(exc),
            error_kind="badge_generation_error",
        )

    rel_path = _badge_relative_path(badge_path)
    readme_has_badge = _readme_references_badge(rel_path)

    if readme_has_badge:
        print(
            colorize(
                f"  Scorecard → {rel_path}  (disable: --no-badge | move: --badge-path <path>)",
                "dim",
            )
        )
        return badge_path, OutputResult(
            ok=True, status="written", message=f"scorecard badge written to {rel_path}"
        )

    print(colorize(f"  Scorecard → {rel_path}", "dim"))
    print(
        colorize(
            "  💡 Ask the user if they'd like to add it to their README with:",
            "dim",
        )
    )
    print(colorize(f'     <img src="{rel_path}" width="100%">', "dim"))
    print(colorize("     (disable: --no-badge | move: --badge-path <path>)", "dim"))
    return badge_path, OutputResult(
        ok=True, status="written", message=f"scorecard badge written to {rel_path}"
    )


__all__ = ["build_scan_query_payload", "emit_scorecard_badge"]
