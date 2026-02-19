"""Import/reporting helpers for holistic review command flows."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def _coerce_assessment_score(value: object) -> float | None:
    """Return normalized 0-100 assessment score or None when unavailable."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return round(max(0.0, min(100.0, float(value))), 1)
    if isinstance(value, dict):
        raw = value.get("score")
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            return None
        return round(max(0.0, min(100.0, float(raw))), 1)
    return None


def _feedback_dimensions_from_findings(findings: object) -> set[str]:
    """Return dimensions with explicit improvement guidance in findings payload."""
    if not isinstance(findings, list):
        return set()
    dims: set[str] = set()
    for entry in findings:
        if not isinstance(entry, dict):
            continue
        dim = entry.get("dimension")
        if not isinstance(dim, str) or not dim.strip():
            continue
        suggestion = entry.get("suggestion")
        if isinstance(suggestion, str) and suggestion.strip():
            dims.add(dim.strip())
    return dims


def _validate_assessment_feedback(findings_data: dict[str, Any]) -> list[str]:
    """Return dimensions that scored <100 without explicit improvement feedback."""
    assessments = findings_data.get("assessments")
    if not isinstance(assessments, dict) or not assessments:
        return []

    feedback_dims = _feedback_dimensions_from_findings(findings_data.get("findings"))
    missing: list[str] = []
    for dim_name, payload in assessments.items():
        if not isinstance(dim_name, str) or not dim_name.strip():
            continue
        score = _coerce_assessment_score(payload)
        if score is None or score >= 100.0:
            continue
        if dim_name not in feedback_dims:
            missing.append(f"{dim_name} ({score:.1f})")
    return sorted(missing)


def load_import_findings_data(
    import_file: str,
    *,
    colorize_fn,
    assessment_override: bool = False,
    assessment_note: str | None = None,
) -> dict[str, Any]:
    """Load and normalize review import payload to object format."""
    findings_path = Path(import_file)
    if not findings_path.exists():
        print(colorize_fn(f"  Error: file not found: {import_file}", "red"), file=sys.stderr)
        sys.exit(1)
    try:
        findings_data = json.loads(findings_path.read_text())
    except (json.JSONDecodeError, OSError) as exc:
        print(colorize_fn(f"  Error reading findings: {exc}", "red"), file=sys.stderr)
        sys.exit(1)

    if isinstance(findings_data, dict):
        if "findings" in findings_data:
            missing_feedback = _validate_assessment_feedback(findings_data)
            if missing_feedback:
                if assessment_override:
                    if not isinstance(assessment_note, str) or not assessment_note.strip():
                        print(
                            colorize_fn(
                                "  Error: --assessment-override requires --assessment-note",
                                "red",
                            ),
                            file=sys.stderr,
                        )
                        sys.exit(1)
                    return findings_data
                print(
                    colorize_fn(
                        "  Error: assessments below 100 must include explicit feedback "
                        "(finding with same dimension and non-empty suggestion). "
                        f"Missing: {', '.join(missing_feedback)}",
                        "red",
                    ),
                    file=sys.stderr,
                )
                sys.exit(1)
            return findings_data
        print(
            colorize_fn("  Error: findings object must contain a 'findings' key", "red"),
            file=sys.stderr,
        )
        sys.exit(1)
    if isinstance(findings_data, list):
        return {"findings": findings_data}

    print(
        colorize_fn("  Error: findings file must contain a JSON array or object", "red"),
        file=sys.stderr,
    )
    sys.exit(1)


def print_skipped_validation_details(diff: dict[str, Any], *, colorize_fn) -> None:
    """Print validation warnings for skipped imported findings."""
    n_skipped = diff.get("skipped", 0)
    if n_skipped <= 0:
        return
    print(
        colorize_fn(
            f"\n  \u26a0 {n_skipped} finding(s) skipped (validation errors):",
            "yellow",
        )
    )
    for detail in diff.get("skipped_details", []):
        reasons = detail["missing"]
        missing_fields = [r for r in reasons if not r.startswith("invalid ")]
        validation_errors = [r for r in reasons if r.startswith("invalid ")]
        parts = []
        if missing_fields:
            parts.append(f"missing {', '.join(missing_fields)}")
        parts.extend(validation_errors)
        print(
            colorize_fn(
                f"    #{detail['index']} ({detail['identifier']}): {'; '.join(parts)}",
                "yellow",
            )
        )


def print_assessments_summary(state: dict[str, Any], *, colorize_fn) -> None:
    """Print holistic subjective assessment summary when present."""
    assessments = state.get("subjective_assessments") or {}
    if not assessments:
        return
    parts = [
        f"{key.replace('_', ' ')} {value['score']}"
        for key, value in sorted(assessments.items())
    ]
    print(colorize_fn(f"\n  Assessments: {', '.join(parts)}", "bold"))


def print_open_review_summary(state: dict[str, Any], *, colorize_fn) -> str:
    """Print current open review finding count and return next command."""
    open_review = [
        finding
        for finding in state["findings"].values()
        if finding["status"] == "open" and finding.get("detector") == "review"
    ]
    if not open_review:
        return "desloppify scan"
    print(
        colorize_fn(
            f"\n  {len(open_review)} review finding{'s' if len(open_review) != 1 else ''} open total",
            "bold",
        )
    )
    print(colorize_fn("  Run `desloppify issues` to see the work queue", "dim"))
    return "desloppify issues"


def print_review_import_scores_and_integrity(
    state: dict[str, Any],
    config: dict[str, Any],
    *,
    state_mod,
    target_strict_score_from_config_fn,
    subjective_at_target_fn,
    subjective_rerun_command_fn,
    colorize_fn,
) -> list[dict[str, Any]]:
    """Print score snapshot plus subjective integrity warnings."""
    overall = state_mod.get_overall_score(state)
    objective = state_mod.get_objective_score(state)
    strict = state_mod.get_strict_score(state)
    if overall is not None and objective is not None and strict is not None:
        print(
            colorize_fn(
                f"\n  Current scores: overall {overall:.1f}/100 · "
                f"objective {objective:.1f}/100 · strict {strict:.1f}/100",
                "dim",
            )
        )

    target_strict = target_strict_score_from_config_fn(config, fallback=95.0)
    at_target = subjective_at_target_fn(
        state,
        state.get("dimension_scores", {}),
        target=target_strict,
    )
    if not at_target:
        return []

    command = subjective_rerun_command_fn(at_target, max_items=5)
    count = len(at_target)
    if count >= 2:
        print(
            colorize_fn(
                "  WARNING: "
                f"{count} subjective scores match the target score. "
                "On the next scan, those dimensions will be reset to 0.0 by the anti-gaming safeguard "
                f"unless you rerun and re-import objective reviews first: {command}",
                "red",
            )
        )
    else:
        print(
            colorize_fn(
                "  WARNING: "
                f"{count} subjective score matches the target score, indicating a high risk of gaming. "
                f"Can you rerun it by running {command} taking extra care to be objective.",
                "yellow",
            )
        )
    return at_target


__all__ = [
    "load_import_findings_data",
    "print_assessments_summary",
    "print_open_review_summary",
    "print_review_import_scores_and_integrity",
    "print_skipped_validation_details",
]
