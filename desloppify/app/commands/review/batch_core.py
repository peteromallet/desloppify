"""Core batch processing helpers for holistic review workflows."""

from __future__ import annotations

import json
from pathlib import Path

_CONFIDENCE_WEIGHTS = {
    "high": 1.2,
    "medium": 1.0,
    "low": 0.75,
}
_IMPACT_SCOPE_WEIGHTS = {
    "local": 1.0,
    "module": 1.3,
    "subsystem": 1.6,
    "codebase": 2.0,
}
_FIX_SCOPE_WEIGHTS = {
    "single_edit": 1.0,
    "multi_file_refactor": 1.3,
    "architectural_change": 1.7,
}


def parse_batch_selection(raw: str | None, batch_count: int) -> list[int]:
    """Parse optional 1-based CSV list of batches."""
    if not raw:
        return list(range(batch_count))

    selected: list[int] = []
    seen: set[int] = set()
    for token in raw.split(","):
        text = token.strip()
        if not text:
            continue
        idx_1 = int(text)
        if idx_1 < 1 or idx_1 > batch_count:
            raise ValueError(f"batch index {idx_1} out of range 1..{batch_count}")
        idx_0 = idx_1 - 1
        if idx_0 in seen:
            continue
        seen.add(idx_0)
        selected.append(idx_0)
    return selected


def extract_json_payload(raw: str, *, log_fn) -> dict | None:
    """Best-effort extraction of first JSON object from agent output text."""
    text = raw.strip()
    if not text:
        return None

    decoder = json.JSONDecoder()
    last_decode_error: json.JSONDecodeError | None = None
    for start, ch in enumerate(text):
        if ch not in "{[":
            continue
        try:
            obj, _ = decoder.raw_decode(text[start:])
        except json.JSONDecodeError as exc:
            last_decode_error = exc
            continue
        if (
            isinstance(obj, dict)
            and isinstance(obj.get("assessments"), dict)
            and isinstance(obj.get("findings"), list)
        ):
            return obj
    if last_decode_error is not None:
        log_fn(f"  batch output JSON parse failed: {last_decode_error.msg}")
    else:
        log_fn("  batch output JSON parse failed: no valid payload found")
    return None


def _validate_dimension_note(key: str, note_raw: object) -> tuple[str, str, str, str, str]:
    """Validate a single dimension_notes entry and return parsed fields.

    Returns (evidence, impact_scope, fix_scope, confidence, unreported_risk).
    Raises ValueError on invalid structure.
    """
    if not isinstance(note_raw, dict):
        raise ValueError(
            f"dimension_notes missing object for assessed dimension: {key}"
        )
    evidence = note_raw.get("evidence")
    impact_scope = note_raw.get("impact_scope")
    fix_scope = note_raw.get("fix_scope")
    if not isinstance(evidence, list) or not evidence:
        raise ValueError(
            f"dimension_notes.{key}.evidence must be a non-empty array"
        )
    if not isinstance(impact_scope, str) or not impact_scope.strip():
        raise ValueError(
            f"dimension_notes.{key}.impact_scope must be a non-empty string"
        )
    if not isinstance(fix_scope, str) or not fix_scope.strip():
        raise ValueError(
            f"dimension_notes.{key}.fix_scope must be a non-empty string"
        )

    confidence_raw = str(note_raw.get("confidence", "medium")).strip().lower()
    confidence = (
        confidence_raw if confidence_raw in {"high", "medium", "low"} else "medium"
    )
    unreported_risk = str(note_raw.get("unreported_risk", "")).strip()
    return evidence, impact_scope, fix_scope, confidence, unreported_risk


def _normalize_abstraction_sub_axes(
    note_raw: dict,
    abstraction_sub_axes: tuple[str, ...],
) -> dict[str, float]:
    """Extract and clamp abstraction_fitness sub-axis scores from a note."""
    sub_axes_raw = note_raw.get("sub_axes")
    if sub_axes_raw is not None and not isinstance(sub_axes_raw, dict):
        raise ValueError(
            "dimension_notes.abstraction_fitness.sub_axes must be an object"
        )
    if not isinstance(sub_axes_raw, dict):
        return {}

    normalized: dict[str, float] = {}
    for axis in abstraction_sub_axes:
        axis_value = sub_axes_raw.get(axis)
        if axis_value is None:
            continue
        if isinstance(axis_value, bool) or not isinstance(
            axis_value, int | float
        ):
            raise ValueError(
                f"dimension_notes.abstraction_fitness.sub_axes.{axis} "
                "must be numeric"
            )
        normalized[axis] = round(
            max(0.0, min(100.0, float(axis_value))),
            1,
        )
    return normalized


def _normalize_findings(
    raw_findings: object,
    dimension_notes: dict[str, dict],
    *,
    max_batch_findings: int,
) -> list[dict]:
    """Validate and normalize the findings array from a batch payload."""
    if not isinstance(raw_findings, list):
        raise ValueError("findings must be an array")

    findings: list[dict] = []
    for item in raw_findings:
        if not isinstance(item, dict):
            continue
        dim = str(item.get("dimension", "")).strip()
        note = dimension_notes.get(dim, {})
        impact_scope = str(
            item.get("impact_scope", note.get("impact_scope", ""))
        ).strip()
        fix_scope = str(item.get("fix_scope", note.get("fix_scope", ""))).strip()
        if not impact_scope or not fix_scope:
            continue
        findings.append({**item, "impact_scope": impact_scope, "fix_scope": fix_scope})
        if len(findings) >= max_batch_findings:
            break
    return findings


def _compute_batch_quality(
    assessments: dict[str, float],
    findings: list[dict],
    dimension_notes: dict[str, dict],
    allowed_dims: set[str],
    high_score_without_risk: float,
) -> dict:
    """Compute quality metrics for a single batch result."""
    return {
        "dimension_coverage": round(
            len(assessments) / max(len(allowed_dims), 1),
            3,
        ),
        "evidence_density": round(
            sum(len(note.get("evidence", [])) for note in dimension_notes.values())
            / max(len(findings), 1),
            3,
        ),
        "high_score_without_risk": high_score_without_risk,
    }


def normalize_batch_result(
    payload: dict,
    allowed_dims: set[str],
    *,
    max_batch_findings: int,
    abstraction_sub_axes: tuple[str, ...],
) -> tuple[dict[str, float], list[dict], dict[str, dict], dict[str, float]]:
    """Validate and normalize one batch payload."""
    if "assessments" not in payload:
        raise ValueError("payload missing required key: assessments")
    if "findings" not in payload:
        raise ValueError("payload missing required key: findings")

    raw_assessments = payload.get("assessments")
    if not isinstance(raw_assessments, dict):
        raise ValueError("assessments must be an object")

    raw_dimension_notes = payload.get("dimension_notes", {})
    if not isinstance(raw_dimension_notes, dict):
        raise ValueError("dimension_notes must be an object")

    assessments: dict[str, float] = {}
    dimension_notes: dict[str, dict] = {}
    high_score_without_risk = 0.0
    for key, value in raw_assessments.items():
        if not isinstance(key, str) or not key:
            continue
        if key not in allowed_dims:
            continue
        if isinstance(value, bool):
            continue
        if not isinstance(value, int | float):
            continue
        score = round(max(0.0, min(100.0, float(value))), 1)

        note_raw = raw_dimension_notes.get(key)
        evidence, impact_scope, fix_scope, confidence, unreported_risk = (
            _validate_dimension_note(key, note_raw)
        )
        if score > 85 and not unreported_risk:
            high_score_without_risk += 1

        normalized_sub_axes: dict[str, float] = {}
        if key == "abstraction_fitness":
            normalized_sub_axes = _normalize_abstraction_sub_axes(
                note_raw, abstraction_sub_axes
            )

        assessments[key] = score
        dimension_notes[key] = {
            "evidence": [str(item).strip() for item in evidence if str(item).strip()],
            "impact_scope": impact_scope.strip(),
            "fix_scope": fix_scope.strip(),
            "confidence": confidence,
            "unreported_risk": unreported_risk,
        }
        if normalized_sub_axes:
            dimension_notes[key]["sub_axes"] = normalized_sub_axes

    findings = _normalize_findings(
        payload.get("findings"),
        dimension_notes,
        max_batch_findings=max_batch_findings,
    )

    quality = _compute_batch_quality(
        assessments, findings, dimension_notes, allowed_dims, high_score_without_risk
    )
    return assessments, findings, dimension_notes, quality


def assessment_weight(
    *,
    dimension: str,
    score: float,
    findings: list[dict],
    dimension_notes: dict[str, dict],
) -> float:
    """Evidence-weighted assessment score weight with a neutral floor."""
    note = dimension_notes.get(dimension, {})
    note_evidence = len(note.get("evidence", [])) if isinstance(note, dict) else 0
    finding_count = sum(
        1
        for finding in findings
        if str(finding.get("dimension", "")).strip() == dimension
    )
    del score  # Weighting is evidence-based, score-independent.
    return float(1 + note_evidence + finding_count)


def _finding_severity(
    finding: dict,
    *,
    note: dict | None,
) -> float:
    """Compute per-finding severity used for score-pressure adjustments."""
    note_ref = note if isinstance(note, dict) else {}
    confidence = str(
        finding.get("confidence", note_ref.get("confidence", "medium"))
    ).strip().lower()
    impact_scope = str(
        finding.get("impact_scope", note_ref.get("impact_scope", "local"))
    ).strip().lower()
    fix_scope = str(
        finding.get("fix_scope", note_ref.get("fix_scope", "single_edit"))
    ).strip().lower()

    confidence_weight = _CONFIDENCE_WEIGHTS.get(confidence, 1.0)
    impact_weight = _IMPACT_SCOPE_WEIGHTS.get(impact_scope, 1.0)
    fix_weight = _FIX_SCOPE_WEIGHTS.get(fix_scope, 1.0)
    return confidence_weight * impact_weight * fix_weight


def _finding_pressure_by_dimension(
    findings: list[dict],
    *,
    dimension_notes: dict[str, dict],
) -> tuple[dict[str, float], dict[str, int]]:
    """Summarize how strongly findings should pull dimension scores down."""
    pressure_by_dim: dict[str, float] = {}
    count_by_dim: dict[str, int] = {}
    for finding in findings:
        dim = str(finding.get("dimension", "")).strip()
        if not dim:
            continue
        note = dimension_notes.get(dim)
        pressure_by_dim[dim] = pressure_by_dim.get(dim, 0.0) + _finding_severity(
            finding,
            note=note if isinstance(note, dict) else None,
        )
        count_by_dim[dim] = count_by_dim.get(dim, 0) + 1
    return pressure_by_dim, count_by_dim


def _accumulate_batch_scores(
    result: dict,
    *,
    score_buckets: dict[str, list[tuple[float, float]]],
    score_raw_by_dim: dict[str, list[float]],
    merged_dimension_notes: dict[str, dict],
    abstraction_axis_scores: dict[str, list[tuple[float, float]]],
    abstraction_sub_axes: tuple[str, ...],
) -> None:
    """Accumulate assessment scores, dimension notes, and sub-axis data from one batch."""
    result_findings = result.get("findings", [])
    result_notes = result.get("dimension_notes", {})
    for key, score in result.get("assessments", {}).items():
        if isinstance(score, bool):
            continue
        score_value = float(score)
        weight = assessment_weight(
            dimension=key,
            score=score_value,
            findings=result_findings,
            dimension_notes=result_notes,
        )
        score_buckets.setdefault(key, []).append((score_value, weight))
        score_raw_by_dim.setdefault(key, []).append(score_value)

        note = result_notes.get(key)
        existing = merged_dimension_notes.get(key)
        existing_evidence = (
            len(existing.get("evidence", [])) if isinstance(existing, dict) else -1
        )
        current_evidence = (
            len(note.get("evidence", [])) if isinstance(note, dict) else -1
        )
        if current_evidence > existing_evidence:
            merged_dimension_notes[key] = note

        if key == "abstraction_fitness" and isinstance(note, dict):
            sub_axes = note.get("sub_axes")
            if isinstance(sub_axes, dict):
                for axis in abstraction_sub_axes:
                    axis_score = sub_axes.get(axis)
                    if isinstance(axis_score, bool) or not isinstance(
                        axis_score, int | float
                    ):
                        continue
                    abstraction_axis_scores[axis].append(
                        (float(axis_score), weight)
                    )


def _accumulate_batch_findings(
    result: dict,
    finding_map: dict[str, dict],
) -> None:
    """Deduplicate and accumulate findings from one batch into finding_map."""
    for finding in result.get("findings", []):
        dim = str(finding.get("dimension", "")).strip()
        ident = str(finding.get("identifier", "")).strip()
        summary = str(finding.get("summary", "")).strip()
        dedupe_key = f"{dim}::{ident}::{summary}"
        if dedupe_key in finding_map:
            continue
        finding_map[dedupe_key] = finding


def _accumulate_batch_quality(
    result: dict,
    *,
    coverage_values: list[float],
    evidence_density_values: list[float],
) -> float:
    """Accumulate quality metrics from one batch. Returns high_score_without_risk delta."""
    quality = result.get("quality", {})
    if not isinstance(quality, dict):
        return 0.0
    coverage = quality.get("dimension_coverage")
    density = quality.get("evidence_density")
    no_risk = quality.get("high_score_without_risk")
    if isinstance(coverage, int | float):
        coverage_values.append(float(coverage))
    if isinstance(density, int | float):
        evidence_density_values.append(float(density))
    return float(no_risk) if isinstance(no_risk, int | float) else 0.0


def _compute_merged_assessments(
    score_buckets: dict[str, list[tuple[float, float]]],
    score_raw_by_dim: dict[str, list[float]],
    finding_pressure_by_dim: dict[str, float],
    finding_count_by_dim: dict[str, int],
) -> dict[str, float]:
    """Compute pressure-adjusted weighted mean for each dimension."""
    merged: dict[str, float] = {}
    for key, weighted_scores in sorted(score_buckets.items()):
        if not weighted_scores:
            continue
        numerator = sum(score * weight for score, weight in weighted_scores)
        denominator = sum(weight for _, weight in weighted_scores)
        weighted_mean = numerator / max(denominator, 1.0)
        floor = min(score_raw_by_dim.get(key, [weighted_mean]))
        floor_aware = (0.7 * weighted_mean) + (0.3 * floor)
        finding_pressure = finding_pressure_by_dim.get(key, 0.0)
        finding_count = finding_count_by_dim.get(key, 0)
        issue_penalty = min(
            24.0,
            (finding_pressure * 2.2) + (max(finding_count - 1, 0) * 0.8),
        )
        issue_adjusted = floor_aware - issue_penalty
        if finding_count > 0:
            issue_cap = max(60.0, 90.0 - (finding_pressure * 3.5))
            issue_adjusted = min(issue_adjusted, issue_cap)
        merged[key] = round(max(0.0, min(100.0, issue_adjusted)), 1)
    return merged


def _compute_abstraction_components(
    merged_assessments: dict[str, float],
    abstraction_axis_scores: dict[str, list[tuple[float, float]]],
    *,
    abstraction_sub_axes: tuple[str, ...],
    abstraction_component_names: dict[str, str],
) -> dict[str, float] | None:
    """Compute weighted abstraction sub-axis component scores.

    Returns component_scores dict, or None if abstraction_fitness is not assessed.
    """
    abstraction_score = merged_assessments.get("abstraction_fitness")
    if abstraction_score is None:
        return None

    component_scores: dict[str, float] = {}
    for axis in abstraction_sub_axes:
        weighted = abstraction_axis_scores.get(axis, [])
        if not weighted:
            continue
        numerator = sum(score * weight for score, weight in weighted)
        denominator = sum(weight for _, weight in weighted)
        if denominator <= 0:
            continue
        component_scores[abstraction_component_names[axis]] = round(
            max(0.0, min(100.0, numerator / denominator)),
            1,
        )
    return component_scores if component_scores else None


def merge_batch_results(
    batch_results: list[dict],
    *,
    abstraction_sub_axes: tuple[str, ...],
    abstraction_component_names: dict[str, str],
) -> dict[str, object]:
    """Deterministically merge assessments/findings across batch outputs."""
    score_buckets: dict[str, list[tuple[float, float]]] = {}
    score_raw_by_dim: dict[str, list[float]] = {}
    finding_map: dict[str, dict] = {}
    merged_dimension_notes: dict[str, dict] = {}
    coverage_values: list[float] = []
    evidence_density_values: list[float] = []
    high_score_without_risk_total = 0.0
    abstraction_axis_scores: dict[str, list[tuple[float, float]]] = {
        axis: [] for axis in abstraction_sub_axes
    }

    for result in batch_results:
        _accumulate_batch_scores(
            result,
            score_buckets=score_buckets,
            score_raw_by_dim=score_raw_by_dim,
            merged_dimension_notes=merged_dimension_notes,
            abstraction_axis_scores=abstraction_axis_scores,
            abstraction_sub_axes=abstraction_sub_axes,
        )
        _accumulate_batch_findings(result, finding_map)
        high_score_without_risk_total += _accumulate_batch_quality(
            result,
            coverage_values=coverage_values,
            evidence_density_values=evidence_density_values,
        )

    merged_findings = list(finding_map.values())
    finding_pressure_by_dim, finding_count_by_dim = _finding_pressure_by_dimension(
        merged_findings,
        dimension_notes=merged_dimension_notes,
    )

    merged_assessments = _compute_merged_assessments(
        score_buckets, score_raw_by_dim, finding_pressure_by_dim, finding_count_by_dim
    )

    merged_assessment_payload: dict[str, float | dict[str, object]] = {
        key: value for key, value in merged_assessments.items()
    }
    component_scores = _compute_abstraction_components(
        merged_assessments,
        abstraction_axis_scores,
        abstraction_sub_axes=abstraction_sub_axes,
        abstraction_component_names=abstraction_component_names,
    )
    if component_scores is not None:
        merged_assessment_payload["abstraction_fitness"] = {
            "score": merged_assessments["abstraction_fitness"],
            "components": list(component_scores),
            "component_scores": component_scores,
        }

    return {
        "assessments": merged_assessment_payload,
        "dimension_notes": merged_dimension_notes,
        "findings": merged_findings,
        "review_quality": {
            "batch_count": len(batch_results),
            "dimension_coverage": round(
                sum(coverage_values) / max(len(coverage_values), 1),
                3,
            ),
            "evidence_density": round(
                sum(evidence_density_values) / max(len(evidence_density_values), 1),
                3,
            ),
            "high_score_without_risk": int(high_score_without_risk_total),
            "finding_pressure": round(sum(finding_pressure_by_dim.values()), 3),
            "dimensions_with_findings": len(finding_count_by_dim),
        },
    }


def build_batch_prompt(
    *,
    repo_root: Path,
    packet_path: Path,
    batch_index: int,
    batch: dict,
) -> str:
    """Render one subagent prompt for a holistic investigation batch."""
    name = str(batch.get("name", f"Batch {batch_index + 1}"))
    dims = [str(d) for d in batch.get("dimensions", []) if isinstance(d, str) and d]
    why = str(batch.get("why", "")).strip()
    files = [str(f) for f in batch.get("files_to_read", []) if isinstance(f, str) and f]
    file_lines = "\n".join(f"- {f}" for f in files) if files else "- (none)"
    dim_text = ", ".join(dims) if dims else "(none)"
    package_org_focus = ""
    if "package_organization" in set(dims):
        package_org_focus = (
            "9a. For package_organization, ground scoring in objective structure signals from "
            "`holistic_context.structure` (root_files fan_in/fan_out roles, directory_profiles, "
            "coupling_matrix). Prefer thresholded evidence (for example: fan_in < 5 for root "
            "stragglers, import-affinity > 60%, directories > 10 files with mixed concerns).\n"
            "9b. Suggestions must include a staged reorg plan (target folders, move order, "
            "and import-update/validation commands).\n"
        )

    return (
        "You are a focused subagent reviewer for a single holistic investigation batch.\n\n"
        f"Repository root: {repo_root}\n"
        f"Immutable packet: {packet_path}\n"
        f"Batch index: {batch_index + 1}\n"
        f"Batch name: {name}\n"
        f"Batch dimensions: {dim_text}\n"
        f"Batch rationale: {why}\n\n"
        "Files assigned:\n"
        f"{file_lines}\n\n"
        "Task requirements:\n"
        "1. Read the immutable packet and follow `system_prompt` constraints exactly.\n"
        "2. Evaluate ONLY listed files and ONLY listed dimensions for this batch.\n"
        "3. Return 0-10 high-quality findings for this batch (empty array allowed).\n"
        "4. Score/finding consistency is required: broader or more severe findings MUST lower dimension scores.\n"
        "5. Every finding must include `related_files` with at least 2 files when possible.\n"
        "6. Every finding must include `impact_scope` and `fix_scope`.\n"
        "7. Every scored dimension MUST include dimension_notes with concrete evidence.\n"
        "8. If a dimension score is >85, include `unreported_risk` in dimension_notes.\n"
        "9. Use exactly one decimal place for every assessment and abstraction sub-axis score.\n"
        f"{package_org_focus}"
        "10. Do not edit repository files.\n"
        "11. Return ONLY valid JSON, no markdown fences.\n\n"
        "Scope enums:\n"
        '- impact_scope: "local" | "module" | "subsystem" | "codebase"\n'
        '- fix_scope: "single_edit" | "multi_file_refactor" | "architectural_change"\n\n'
        "Output schema:\n"
        "{\n"
        f'  "batch": "{name}",\n'
        f'  "batch_index": {batch_index + 1},\n'
        '  "assessments": {"<dimension>": <0-100 with one decimal place>},\n'
        '  "dimension_notes": {\n'
        '    "<dimension>": {\n'
        '      "evidence": ["specific code observations"],\n'
        '      "impact_scope": "local|module|subsystem|codebase",\n'
        '      "fix_scope": "single_edit|multi_file_refactor|architectural_change",\n'
        '      "confidence": "high|medium|low",\n'
        '      "unreported_risk": "required when score >85",\n'
        '      "sub_axes": {"abstraction_leverage": 0-100 with one decimal place, "indirection_cost": 0-100 with one decimal place, "interface_honesty": 0-100 with one decimal place}  // required for abstraction_fitness when evidence supports it\n'
        "    }\n"
        "  },\n"
        '  "findings": []\n'
        "}\n"
    )


__all__ = [
    "assessment_weight",
    "build_batch_prompt",
    "extract_json_payload",
    "merge_batch_results",
    "normalize_batch_result",
    "parse_batch_selection",
]
