"""Prompt template helpers for holistic review batch subagents."""

from __future__ import annotations

from pathlib import Path

from desloppify.intelligence.review.feedback_contract import (
    DIMENSION_NOTE_ISSUES_KEY,
    HIGH_SCORE_ISSUES_NOTE_THRESHOLD,
    LOW_SCORE_FINDING_THRESHOLD,
    max_batch_findings_for_dimension_count,
)


def _render_historical_focus(batch: dict[str, object]) -> str:
    focus = batch.get("historical_issue_focus")
    if not isinstance(focus, dict):
        return ""

    selected_raw = focus.get("selected_count", 0)
    try:
        selected_count = max(0, int(selected_raw))
    except (TypeError, ValueError):
        selected_count = 0

    issues = focus.get("issues", [])
    if not isinstance(issues, list):
        issues = []

    if selected_count <= 0 or not issues:
        return ""

    lines: list[str] = []
    lines.append(
        "Previously flagged issues (from past reviews of these dimensions):"
    )
    lines.append(
        "Check whether each issue still exists in the current code. Do not re-report"
        " issues that have been fixed or marked wontfix — focus on what remains or"
        " what is new. If several past issues share a root cause, call that out."
    )

    for entry in issues:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "")).strip()
        summary = str(entry.get("summary", "")).strip()
        note = str(entry.get("note", "")).strip()

        line = f"  - [{status}] {summary}"
        if note:
            line += f" (note: {note})"
        lines.append(line)
    return "\n".join(lines) + "\n\n"


def render_batch_prompt(
    *,
    repo_root: Path,
    packet_path: Path,
    batch_index: int,
    batch: dict[str, object],
) -> str:
    """Render one subagent prompt for a holistic investigation batch."""
    name = str(batch.get("name", f"Batch {batch_index + 1}"))
    dims_raw = batch.get("dimensions", [])
    dims = (
        [str(d) for d in dims_raw if isinstance(d, str) and d]
        if isinstance(dims_raw, list | tuple)
        else []
    )
    why = str(batch.get("why", "")).strip()
    files_raw = batch.get("files_to_read", [])
    files = (
        [str(f) for f in files_raw if isinstance(f, str) and f]
        if isinstance(files_raw, list | tuple)
        else []
    )
    findings_cap = max_batch_findings_for_dimension_count(len(dims))
    file_lines = "\n".join(f"- {f}" for f in files) if files else "- (none)"
    dim_text = ", ".join(dims) if dims else "(none)"
    historical_focus = _render_historical_focus(batch)
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
        f"Blind packet: {packet_path}\n"
        f"Batch index: {batch_index + 1}\n"
        f"Batch name: {name}\n"
        f"Batch dimensions: {dim_text}\n"
        f"Batch rationale: {why}\n\n"
        "Files assigned:\n"
        f"{file_lines}\n\n"
        f"{historical_focus}"
        "Task requirements:\n"
        "1. Read the blind packet and follow `system_prompt` constraints exactly.\n"
        "1a. If previously flagged issues are listed above, use them as context for your review.\n"
        "    Verify whether each still applies to the current code. Do not re-report fixed or\n"
        "    wontfix issues. Use them as starting points to look deeper — inspect adjacent code\n"
        "    and related modules for defects the prior review may have missed.\n"
        "1c. Think structurally: when you spot multiple individual issues that share a common\n"
        "    root cause (missing abstraction, duplicated pattern, inconsistent convention),\n"
        "    explain the deeper structural issue in the finding, not just the surface symptom.\n"
        "    If the pattern is significant enough, report the structural issue as its own finding\n"
        "    with appropriate fix_scope ('multi_file_refactor' or 'architectural_change') and\n"
        "    use `root_cause_cluster` to connect related symptom findings together.\n"
        "2. Evaluate ONLY listed files and ONLY listed dimensions for this batch.\n"
        f"3. Return 0-{findings_cap} high-quality findings for this batch (empty array allowed).\n"
        "3a. Do not suppress real defects to keep scores high; report every material issue you can support with evidence.\n"
        "3b. Do not default to 100. Reserve 100 for genuinely exemplary evidence in this batch.\n"
        "4. Score/finding consistency is required: broader or more severe findings MUST lower dimension scores.\n"
        f"4a. Any dimension scored below {LOW_SCORE_FINDING_THRESHOLD:.1f} MUST include explicit feedback: add at least one "
        "finding with the same `dimension` and a non-empty actionable `suggestion`.\n"
        "5. Every finding must include `related_files` with at least 2 files when possible.\n"
        "6. Every finding must include `dimension`, `identifier`, `summary`, `evidence`, `suggestion`, and `confidence`.\n"
        "7. Every finding must include `impact_scope` and `fix_scope`.\n"
        "8. Every scored dimension MUST include dimension_notes with concrete evidence.\n"
        f"9. If a dimension score is >{HIGH_SCORE_ISSUES_NOTE_THRESHOLD:.1f}, include `{DIMENSION_NOTE_ISSUES_KEY}` in dimension_notes.\n"
        "10. Use exactly one decimal place for every assessment and abstraction sub-axis score.\n"
        f"{package_org_focus}"
        "11. Ignore prior chat context and any target-threshold assumptions.\n"
        "12. Do not edit repository files.\n"
        "13. Return ONLY valid JSON, no markdown fences.\n\n"
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
        f'      "{DIMENSION_NOTE_ISSUES_KEY}": "required when score >{HIGH_SCORE_ISSUES_NOTE_THRESHOLD:.1f}",\n'
        '      "sub_axes": {"abstraction_leverage": 0-100 with one decimal place, "indirection_cost": 0-100 with one decimal place, "interface_honesty": 0-100 with one decimal place}  // required for abstraction_fitness when evidence supports it\n'
        "    }\n"
        "  },\n"
        '  "findings": [{\n'
        '    "dimension": "<dimension>",\n'
        '    "identifier": "short_id",\n'
        '    "summary": "one-line defect summary",\n'
        '    "related_files": ["relative/path.py"],\n'
        '    "evidence": ["specific code observation"],\n'
        '    "suggestion": "concrete fix recommendation",\n'
        '    "confidence": "high|medium|low",\n'
        '    "impact_scope": "local|module|subsystem|codebase",\n'
        '    "fix_scope": "single_edit|multi_file_refactor|architectural_change",\n'
        '    "root_cause_cluster": "optional_cluster_name_when_supported_by_history"\n'
        "  }],\n"
        '  "retrospective": {\n'
        '    "root_causes": ["optional: concise root-cause hypotheses"],\n'
        '    "likely_symptoms": ["optional: identifiers that look symptom-level"],\n'
        '    "possible_false_positives": ["optional: prior concept keys likely mis-scoped"]\n'
        "  }\n"
        "}\n"
    )


__all__ = ["render_batch_prompt"]
