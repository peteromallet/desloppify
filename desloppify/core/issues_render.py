"""Rendering and scoring helpers for finding work orders."""

from __future__ import annotations

import logging
from datetime import datetime

from desloppify.core.registry import DETECTORS
from desloppify.scoring import CONFIDENCE_WEIGHTS, HOLISTIC_MULTIPLIER

logger = logging.getLogger(__name__)


def finding_weight(finding: dict) -> tuple[float, float, str]:
    """Compute (weight, impact_pts, finding_id) for a finding."""
    confidence = finding.get("confidence", "low")
    is_holistic = finding.get("detail", {}).get("holistic", False)

    weight = CONFIDENCE_WEIGHTS.get(confidence, 0.3)
    if is_holistic:
        weight *= HOLISTIC_MULTIPLIER

    return weight, weight, finding.get("id", "")


def _append_assessment_context(
    lines: list[str], finding: dict, subjective_assessments: dict | None
) -> None:
    if not subjective_assessments:
        return

    detail = finding.get("detail", {})
    dimension = detail.get("dimension", "")
    assessment = subjective_assessments.get(dimension)
    if not assessment:
        return

    display_dimension = dimension.replace("_", " ")
    source = assessment.get("source", "review")
    assessed_at = assessment.get("assessed_at", "")[:10]
    lines.append(
        f"**Dimension assessment**: {display_dimension} — {assessment['score']}/100 "
        f"({source} review, {assessed_at})"
    )
    lines.append(
        "Fixing this issue and re-reviewing should improve the "
        f"{display_dimension} score.\n"
    )


def _append_evidence(lines: list[str], detail: dict) -> None:
    evidence = detail.get("evidence", [])
    if evidence:
        lines.append("## Evidence\n")
        for item in evidence:
            lines.append(f"- {item}")
        lines.append("")

    evidence_lines = detail.get("evidence_lines", [])
    if evidence_lines:
        lines.append("## Code References\n")
        for item in evidence_lines:
            lines.append(f"- {item}")
        lines.append("")


def _append_files(
    lines: list[str], finding: dict, detail: dict, is_holistic: bool
) -> None:
    if is_holistic:
        related_files = detail.get("related_files", [])
        if not related_files:
            return
        lines.append("## Files\n")
        for related in related_files:
            lines.append(f"- `{related}`")
        lines.append("")
        return

    file_path = finding.get("file", "")
    if file_path and file_path != ".":
        lines.append("## Files\n")
        lines.append(f"- `{file_path}`")
        lines.append("")


def _append_investigation(lines: list[str], finding_id: str, detail: dict) -> bool:
    investigation = detail.get("investigation")
    if not investigation:
        return False

    investigated_at = detail.get("investigated_at", "")
    date_suffix = ""
    if investigated_at:
        try:
            date_suffix = (
                f" ({datetime.fromisoformat(investigated_at).strftime('%Y-%m-%d')})"
            )
        except (ValueError, TypeError) as exc:
            logger.debug(
                "Invalid investigated_at value %r on %s: %s",
                investigated_at,
                finding_id,
                exc,
            )
            date_suffix = " (invalid date)"

    lines.append(f"## Investigation{date_suffix}\n")
    lines.append(f"{investigation}\n")
    return True


def _append_footer(
    lines: list[str],
    *,
    has_investigation: bool,
    lang_name: str,
    finding_id: str,
    number: int | None,
) -> None:
    if has_investigation:
        lines.append("## Ready to Fix\n")
        lines.append("When done:\n")
        lines.append("```bash")
        lines.append(f'desloppify plan done "{finding_id}"')
        lines.append("```\n")
        return

    lines.append("## Status: Needs Investigation\n")
    lines.append("Investigate the files above, then resolve with a note:\n")
    lines.append("```bash")
    lines.append(
        f'desloppify plan done "{finding_id}" --note "description of fix"'
    )
    lines.append("```\n")
    lines.append("Or save detailed analysis first:\n")
    lines.append("```bash")
    lines.append(
        f'desloppify show "{finding_id}" --notes analysis.md'
    )
    lines.append("```\n")


def render_issue_detail(
    finding: dict,
    lang_name: str,
    number: int | None = None,
    subjective_assessments: dict | None = None,
) -> str:
    """Render one finding as a markdown work order from state."""
    finding_id = finding["id"]
    detail = finding.get("detail", {})
    detector = finding.get("detector", "")
    is_holistic = detail.get("holistic", False)
    is_review = detector in ("review", "concerns")

    # Derive dimension: from detail for review, from registry for mechanical.
    raw_dimension = detail.get("dimension", "")
    if raw_dimension:
        dimension = raw_dimension.replace("_", " ")
    else:
        meta = DETECTORS.get(detector)
        dimension = meta.dimension.replace("_", " ") if meta else "unknown"

    confidence = finding.get("confidence", "low")

    parts = finding_id.split("::")
    identifier = parts[-2] if len(parts) >= 3 else finding.get("file", "unknown")
    weight, impact_pts, _ = finding_weight(finding)
    label = "+++" if weight >= 8 else "++" if weight >= 5 else "+"

    lines: list[str] = []
    lines.append(f"# {dimension}: {identifier}\n")
    lines.append(f"**Finding**: `{finding_id}`  ")
    if not is_review:
        meta = DETECTORS.get(detector)
        detector_display = meta.display if meta else detector
        lines.append(f"**Detector**: {detector_display} | **Confidence**: {confidence}  ")
    else:
        lines.append(f"**Dimension**: {dimension} | **Confidence**: {confidence}  ")
    lines.append(f"**Score impact**: {label} (~{impact_pts:.1f} pts)\n")

    _append_assessment_context(lines, finding, subjective_assessments)

    lines.append("## Problem\n")
    lines.append(f"{finding.get('summary', '')}\n")

    _append_evidence(lines, detail)

    suggestion = detail.get("suggestion", "")
    if suggestion:
        lines.append("## Suggested Fix\n")
        lines.append(f"{suggestion}\n")

    _append_files(lines, finding, detail, is_holistic)

    reasoning = detail.get("reasoning", "")
    if reasoning:
        lines.append("## Why This Matters\n")
        lines.append(f"{reasoning}\n")

    has_investigation = _append_investigation(lines, finding_id, detail)
    _append_footer(
        lines,
        has_investigation=has_investigation,
        lang_name=lang_name,
        finding_id=finding_id,
        number=number,
    )
    return "\n".join(lines)
