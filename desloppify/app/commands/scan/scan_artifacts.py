"""Payload and artifact helpers for scan command output."""

from __future__ import annotations

import importlib
from pathlib import Path

from desloppify.app.commands.scan.scan_workflow import (
    ScanMergeResult,
    ScanNoiseSnapshot,
)
from desloppify.core.config import config_for_query
from desloppify.scoring import compute_health_breakdown
from desloppify.state import (
    get_objective_score,
    get_overall_score,
    get_strict_score,
    get_verified_strict_score,
)
from desloppify.utils import PROJECT_ROOT, colorize


def build_scan_query_payload(
    state: dict[str, object],
    config: dict[str, object],
    profile: str,
    diff: dict[str, object],
    warnings: list[str],
    narrative: dict[str, object],
    merge: ScanMergeResult,
    noise: ScanNoiseSnapshot,
) -> dict[str, object]:
    """Build the canonical query payload persisted after a scan."""
    return {
        "command": "scan",
        "overall_score": get_overall_score(state),
        "objective_score": get_objective_score(state),
        "strict_score": get_strict_score(state),
        "verified_strict_score": get_verified_strict_score(state),
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
        "warnings": warnings,
        "dimension_scores": state.get("dimension_scores"),
        "score_breakdown": compute_health_breakdown(state.get("dimension_scores", {})),
        "subjective_integrity": state.get("subjective_integrity"),
        "potentials": state.get("potentials"),
        "zone_distribution": state.get("zone_distribution"),
        "narrative": narrative,
        "config": config_for_query(config),
    }


def _load_scorecard_helpers():
    """Load scorecard helper callables lazily via importlib."""
    try:
        scorecard_module = importlib.import_module("desloppify.app.output.scorecard")
    except ImportError:
        return None, None
    generate = getattr(scorecard_module, "generate_scorecard", None)
    badge_config = getattr(scorecard_module, "get_badge_config", None)
    return generate, badge_config


def emit_scorecard_badge(
    args, config: dict[str, object], state: dict[str, object]
) -> Path | None:
    """Generate a scorecard image badge and print usage hints."""
    generate_scorecard, get_badge_config = _load_scorecard_helpers()
    if not callable(generate_scorecard) or not callable(get_badge_config):
        return None

    try:
        badge_path, disabled = get_badge_config(args, config)
    except OSError:
        return None
    if disabled or not badge_path:
        return None

    try:
        generate_scorecard(state, badge_path)
    except OSError:
        return None

    rel_path = badge_path.name if badge_path.parent == PROJECT_ROOT else str(badge_path)

    readme_has_badge = False
    for readme_name in ("README.md", "readme.md", "README.MD"):
        readme_path = PROJECT_ROOT / readme_name
        if readme_path.exists():
            try:
                readme_has_badge = rel_path in readme_path.read_text(
                    encoding="utf-8", errors="replace"
                )
            except OSError:
                readme_has_badge = False
            break

    if readme_has_badge:
        print(
            colorize(
                f"  Scorecard → {rel_path}  (disable: --no-badge | move: --badge-path <path>)",
                "dim",
            )
        )
        return badge_path

    print(colorize(f"  Scorecard → {rel_path}", "dim"))
    print(
        colorize(
            "  💡 Ask the user if they'd like to add it to their README with:",
            "dim",
        )
    )
    print(colorize(f'     <img src="{rel_path}" width="100%">', "dim"))
    print(colorize("     (disable: --no-badge | move: --badge-path <path>)", "dim"))
    return badge_path


__all__ = ["build_scan_query_payload", "emit_scorecard_badge"]
