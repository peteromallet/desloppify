"""Shared prompt rendering sections used by both batch and external review paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

from desloppify.intelligence.review.feedback_contract import (
    max_batch_issues_for_dimension_count,
)


class PromptBatchPayload(TypedDict, total=False):
    """Typed packet batch contract used by prompt rendering."""

    name: str
    dimensions: list[str]
    why: str
    persona: str
    dimension_prompts: dict[str, dict[str, object]]
    judgment_finding_counts: dict[str, object]
    mechanical_finding_counts: dict[str, object]
    concern_signals: list[dict[str, object]]
    historical_issue_focus: dict[str, object]
    subjective_defer_meta: dict[str, dict[str, object]]


@dataclass(frozen=True)
class PromptBatchContext:
    name: str
    dimensions: tuple[str, ...]
    rationale: str
    issues_cap: int
    dimension_prompts: dict[str, dict[str, object]]
    persona: str

    @property
    def dimension_set(self) -> set[str]:
        return set(self.dimensions)

    @property
    def dimensions_text(self) -> str:
        return ", ".join(self.dimensions) if self.dimensions else "(none)"


def coerce_string_list(raw: object) -> tuple[str, ...]:
    if not isinstance(raw, list | tuple):
        return ()
    return tuple(str(item) for item in raw if isinstance(item, str) and item)


def build_batch_context(batch: PromptBatchPayload, batch_index: int) -> PromptBatchContext:
    dimensions = coerce_string_list(batch.get("dimensions", []))
    return PromptBatchContext(
        name=str(batch.get("name", f"Batch {batch_index + 1}")),
        dimensions=dimensions,
        rationale=str(batch.get("why", "")).strip(),
        issues_cap=max_batch_issues_for_dimension_count(len(dimensions)),
        dimension_prompts=batch_dimension_prompts(batch),
        persona=str(batch.get("persona", "")).strip(),
    )


def batch_dimension_prompts(batch: PromptBatchPayload) -> dict[str, dict[str, object]]:
    raw_prompts = batch.get("dimension_prompts")
    if not isinstance(raw_prompts, dict):
        return {}
    return {
        str(dim): prompt
        for dim, prompt in raw_prompts.items()
        if isinstance(dim, str) and isinstance(prompt, dict)
    }


SCAN_EVIDENCE_FOCUS_BY_DIMENSION = {
    "initialization_coupling": (
        "9e. For initialization_coupling, use evidence from "
        "`holistic_context.scan_evidence.mutable_globals` and "
        "`holistic_context.errors.mutable_globals`. Investigate initialization ordering "
        "dependencies, coupling through shared mutable state, and whether state should "
        "be encapsulated behind a proper registry/context manager.\n"
    ),
    "design_coherence": (
        "9f. For design_coherence, use evidence from "
        "`holistic_context.scan_evidence.signal_density` — files where "
        "multiple mechanical detectors fired. Investigate what design change would address "
        "multiple signals simultaneously. Check `scan_evidence.complexity_hotspots` for "
        "files with high responsibility cluster counts.\n"
    ),
    "error_consistency": (
        "9g. For error_consistency, use evidence from "
        "`holistic_context.errors.exception_hotspots` — files with "
        "concentrated exception handling issues. Investigate whether error handling is "
        "designed or accidental. Check for broad catches masking specific failure modes.\n"
    ),
    "cross_module_architecture": (
        "9h. For cross_module_architecture, also consult "
        "`holistic_context.coupling.boundary_violations` for import paths that "
        "cross architectural boundaries, and `holistic_context.dependencies.deferred_import_density` "
        "for files with many function-level imports (proxy for cycle pressure).\n"
    ),
    "convention_outlier": (
        "9i. For convention_outlier, also consult "
        "`holistic_context.conventions.duplicate_clusters` for cross-file "
        "function duplication and `conventions.naming_drift` for directory-level naming "
        "inconsistency.\n"
    ),
}


def render_scan_evidence_focus(dim_set: set[str]) -> str:
    """Render dimension-specific scan_evidence guidance."""
    return "".join(
        text
        for dim, text in SCAN_EVIDENCE_FOCUS_BY_DIMENSION.items()
        if dim in dim_set
    )


_HISTORICAL_STATUS_GROUPS = (
    ("open", "Still open"),
    ("deferred", "Deferred"),
    ("triaged_out", "Triaged out"),
)
_HISTORICAL_RESOLVED_GROUP = "Resolved"
_HISTORICAL_RESOLVED_STATUSES = {"fixed", "wontfix", "false_positive", "auto_resolved"}


def render_historical_focus(batch: PromptBatchPayload) -> str:
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

    lines: list[str] = [
        "Previously flagged issues — navigation aid, not scoring evidence:",
        "Check whether open issues still exist. Do not re-report resolved or deferred items.",
        "If several past issues share a root cause, call that out.",
    ]

    # Group issues by status category
    grouped: dict[str, list[dict]] = {}
    for entry in issues:
        if not isinstance(entry, dict):
            continue
        status = str(entry.get("status", "open")).strip()
        grouped.setdefault(status, []).append(entry)

    def _render_entry(entry: dict) -> str:
        status = str(entry.get("status", "")).strip()
        summary = str(entry.get("summary", "")).strip()
        note = str(entry.get("note", "")).strip()
        prefix = f"[{status}] " if status else ""
        line = f"    - {prefix}{summary}"
        if note:
            line += f" (note: {note})"
        return line

    # Render active groups first (open, deferred, triaged_out)
    for status_key, group_label in _HISTORICAL_STATUS_GROUPS:
        group = grouped.pop(status_key, [])
        if group:
            lines.append(f"\n  {group_label} ({len(group)}):")
            lines.extend(_render_entry(e) for e in group)

    # Render resolved group (all remaining resolved statuses)
    resolved: list[dict] = []
    for status_key in list(grouped):
        if status_key in _HISTORICAL_RESOLVED_STATUSES:
            resolved.extend(grouped.pop(status_key))
    if resolved:
        lines.append(f"\n  {_HISTORICAL_RESOLVED_GROUP} ({len(resolved)}):")
        lines.extend(_render_entry(e) for e in resolved)

    # Any unknown statuses
    for status_key, group in grouped.items():
        if group:
            lines.append(f"\n  {status_key} ({len(group)}):")
            lines.extend(_render_entry(e) for e in group)

    lines.append("")
    lines.append("Explore past review issues:")
    lines.append("  desloppify show review --no-budget              # all open review issues")
    lines.append("  desloppify show review --status deferred         # deferred issues")

    return "\n".join(lines) + "\n\n"


def render_dimension_deferral_context(batch: PromptBatchPayload) -> str:
    """Render deferral context for dimensions that were deferred for multiple cycles."""
    defer_meta = batch.get("subjective_defer_meta")
    if not isinstance(defer_meta, dict) or not defer_meta:
        return ""

    lines: list[str] = []
    for dim, meta in defer_meta.items():
        if not isinstance(meta, dict):
            continue
        cycles = meta.get("deferred_cycles", 0)
        if not isinstance(cycles, int) or cycles < 1:
            continue
        lines.append(
            f"Note: {dim} was deferred for {cycles} scan cycle(s) while objective issues took priority."
        )
        lines.append(
            "Previous assessment may be stale — calibrate accordingly."
        )
    if not lines:
        return ""
    return "\n".join(lines) + "\n\n"


def _concern_signal_lines(entry: dict[str, object]) -> list[str]:
    """Render one concern signal entry into prompt lines."""
    file = str(entry.get("file", "")).strip() or "(unknown file)"
    concern_type = str(entry.get("type", "")).strip() or "design_concern"
    summary = str(entry.get("summary", "")).strip()
    question = str(entry.get("question", "")).strip()
    evidence_raw = entry.get("evidence", [])
    evidence = (
        [str(item).strip() for item in evidence_raw if isinstance(item, str) and item.strip()]
        if isinstance(evidence_raw, list)
        else []
    )
    lines = [f"  - [{concern_type}] {file}"]
    if summary:
        lines.append(f"    summary: {summary}")
    if question:
        lines.append(f"    question: {question}")
    lines.extend(f"    evidence: {snippet}" for snippet in evidence[:2])
    fingerprint = str(entry.get("fingerprint", "")).strip()
    if fingerprint:
        lines.append(f"    fingerprint: {fingerprint}")
    return lines


def _iter_valid_concern_signals(
    signals: list[object],
) -> list[dict[str, object]]:
    """Filter signal entries to mapping payloads only."""
    return [entry for entry in signals if isinstance(entry, dict)]


def _build_concern_summary(valid_signals: list[dict[str, object]]) -> list[str]:
    """Build a grouped summary of concern signals by type."""
    by_type: dict[str, list[str]] = {}
    for entry in valid_signals:
        concern_type = str(entry.get("type", "")).strip() or "design_concern"
        file = str(entry.get("file", "")).strip() or "(unknown)"
        by_type.setdefault(concern_type, []).append(file)

    if not by_type:
        return []

    lines = [f"Overview ({len(valid_signals)} signals):"]
    for concern_type, files in sorted(by_type.items(), key=lambda x: -len(x[1])):
        if len(files) <= 3:
            file_list = ", ".join(files)
            lines.append(f"  {concern_type}: {len(files)} — {file_list}")
        else:
            sample = ", ".join(files[:2])
            lines.append(f"  {concern_type}: {len(files)} — {sample}, ...")
    lines.append("")
    return lines


def render_mechanical_concern_signals(batch: PromptBatchPayload) -> str:
    """Render mechanically-generated concern hypotheses for this batch."""
    signals = batch.get("concern_signals")
    if not isinstance(signals, list) or not signals:
        return ""

    valid_signals = _iter_valid_concern_signals(signals)
    if not valid_signals:
        return ""

    lines: list[str] = []
    lines.append("Mechanical concern signals — investigate and adjudicate:")
    lines.extend(_build_concern_summary(valid_signals))
    lines.append("For each concern, read the source code and report your verdict in issues[]:")
    lines.append(
        '  - Confirm → full issue object with concern_verdict: "confirmed"'
    )
    lines.append(
        '  - Dismiss → minimal object: {concern_verdict: "dismissed", concern_fingerprint: "<hash>"}'
    )
    lines.append(
        "    (only these 2 fields required — add optional reasoning/concern_type/concern_file)"
    )
    lines.append(
        "  - Unsure → skip it (will be re-evaluated next review)"
    )
    lines.append("")

    capped_signals = valid_signals[:30]
    for entry in capped_signals:
        lines.extend(_concern_signal_lines(entry))

    extra = max(0, len(valid_signals) - len(capped_signals))
    if extra:
        lines.append(f"  (+{extra} more — use `desloppify show <detector> --no-budget` to explore)")
    return "\n".join(lines) + "\n\n"


def _coerce_finding_counts(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    counts: dict[str, int] = {}
    for det, count in raw.items():
        if not isinstance(det, str):
            continue
        try:
            normalized = int(count)
        except (TypeError, ValueError):
            continue
        if normalized > 0:
            counts[det] = normalized
    return counts


def render_findings_exploration_section(batch: PromptBatchPayload) -> str:
    """Render CLI exploration commands for detector findings relevant to this batch."""
    all_counts: dict[str, int] = {}
    for key in ("judgment_finding_counts", "mechanical_finding_counts"):
        all_counts.update(_coerce_finding_counts(batch.get(key)))
    if not all_counts:
        return ""

    lines = [
        "RELEVANT FINDINGS — explore with CLI:",
        "These detectors found patterns related to this dimension. Explore the findings,",
        "then read the actual source code.",
        "",
    ]
    for detector, n in sorted(all_counts.items()):
        lines.append(f"  desloppify show {detector} --no-budget      # {n} findings")
    lines.append("")
    lines.append(
        "Report actionable issues in issues[]. Use concern_verdict and concern_fingerprint"
    )
    lines.append("for findings you want to confirm or dismiss.")
    return "\n".join(lines) + "\n\n"


# Keep the old name as an alias so existing callers don't break.
render_judgment_findings_section = render_findings_exploration_section


def render_workflow_integrity_focus(dim_set: set[str]) -> str:
    """Render workflow integrity checks for architecture/integration dimensions."""
    if not dim_set.intersection(
        {
            "cross_module_architecture",
            "high_level_elegance",
            "mid_level_elegance",
            "design_coherence",
            "initialization_coupling",
        }
    ):
        return ""
    return (
        "9j. Workflow integrity checks: when reviewing orchestration/queue/review flows,\n"
        "    explicitly look for loop-prone patterns and blind spots:\n"
        "    - repeated stale/reopen churn without clear exit criteria or gating,\n"
        "    - packet/batch data being generated but dropped before prompt execution,\n"
        "    - ranking/triage logic that can starve target-improving work,\n"
        "    - reruns happening before existing open review work is drained.\n"
        "    If found, propose concrete guardrails and where to implement them.\n"
    )


def render_package_org_focus(dim_set: set[str]) -> str:
    if "package_organization" not in dim_set:
        return ""
    return (
        "9a. For package_organization, ground scoring in objective structure signals from "
        "`holistic_context.structure` (root_files fan_in/fan_out roles, directory_profiles, "
        "coupling_matrix). Prefer thresholded evidence (for example: fan_in < 5 for root "
        "stragglers, import-affinity > 60%, directories > 10 files with mixed concerns).\n"
        "9b. Suggestions must include a staged reorg plan (target folders, move order, "
        "and import-update/validation commands).\n"
        "9c. Also consult `holistic_context.structure.flat_dir_issues` for directories "
        "flagged as overloaded, fragmented, or thin-wrapper patterns.\n"
    )


def render_abstraction_focus(dim_set: set[str]) -> str:
    if "abstraction_fitness" not in dim_set:
        return ""
    return (
        "9d. For abstraction_fitness, use evidence from `holistic_context.abstractions`:\n"
        "  - `delegation_heavy_classes`: classes where most methods forward to an inner "
        "object — entries include class_name, delegate_target, sample_methods, and line number.\n"
        "  - `facade_modules`: re-export-only modules with high re_export_ratio — entries "
        "include samples (re-exported names) and loc.\n"
        "  - `typed_dict_violations`: TypedDict fields accessed via .get()/.setdefault()/.pop() "
        "— entries include typed_dict_name, violation_type, field, and line number.\n"
        "  - `complexity_hotspots`: files where mechanical analysis found extreme parameter "
        "counts, deep nesting, or disconnected responsibility clusters.\n"
        "  Include `delegation_density`, `definition_directness`, and `type_discipline` "
        "alongside existing sub-axes in dimension_notes when evidence supports it.\n"
    )


def render_dimension_focus(dim_set: set[str]) -> str:
    return (
        render_package_org_focus(dim_set)
        + render_abstraction_focus(dim_set)
        + render_scan_evidence_focus(dim_set)
        + render_workflow_integrity_focus(dim_set)
    )


def explode_to_single_dimension(
    batches: list[PromptBatchPayload],
    dimension_prompts: dict[str, dict[str, object]] | None = None,
) -> list[PromptBatchPayload]:
    """Split multi-dimension batches into one batch per dimension.

    Preserves seed files and rationale — each exploded batch keeps the same
    file grouping but is scoped to a single dimension. When *dimension_prompts*
    is provided, each exploded batch gets a public ``dimension_prompts`` map
    scoped to its single dimension.
    """
    prompts = dimension_prompts or {}
    result: list[PromptBatchPayload] = []
    for batch in batches:
        dims = batch.get("dimensions", [])
        if not isinstance(dims, list):
            result.append(batch)
            continue
        for dim in dims:
            exploded: PromptBatchPayload = {**batch, "dimensions": [dim]}
            dim_prompt = prompts.get(dim)
            if isinstance(dim_prompt, dict):
                exploded["dimension_prompts"] = {str(dim): dim_prompt}
            result.append(exploded)
    return result


def render_dimension_prompts_block(
    dimensions: tuple[str, ...],
    dimension_prompts: dict[str, dict[str, object]],
) -> str:
    """Render inline dimension guidance so the reviewer sees the full rubric."""
    if not dimensions or not dimension_prompts:
        return ""
    lines: list[str] = ["DIMENSION TO EVALUATE:\n"]
    for dim in dimensions:
        prompt = dimension_prompts.get(dim)
        if not isinstance(prompt, dict):
            lines.append(f"## {dim}\n(no rubric available)\n")
            continue
        description = str(prompt.get("description", "")).strip()
        lines.append(f"## {dim}")
        if description:
            lines.append(description)

        look_for = prompt.get("look_for")
        if isinstance(look_for, list) and look_for:
            lines.append("Look for:")
            for item in look_for:
                lines.append(f"- {item}")

        skip = prompt.get("skip")
        if isinstance(skip, list) and skip:
            lines.append("Skip:")
            for item in skip:
                lines.append(f"- {item}")
        lines.append("")
    return "\n".join(lines) + "\n"


def render_dimension_context_block(
    dimensions: tuple[str, ...],
    dimension_contexts: dict[str, dict],
) -> str:
    """Render accumulated codebase context for dimensions that have insights.

    Only surfaces headers in the prompt text — full descriptions are in the
    blind packet's ``dimension_contexts`` section.
    """
    if not dimensions or not dimension_contexts:
        return ""

    sections: list[str] = []
    for dim in dimensions:
        ctx = dimension_contexts.get(dim)
        if not isinstance(ctx, dict):
            continue
        insights = ctx.get("insights")
        if not isinstance(insights, list) or not insights:
            continue
        lines: list[str] = [f"### {dim}"]
        for insight in insights:
            if not isinstance(insight, dict):
                continue
            header = str(insight.get("header", "")).strip()
            if not header:
                continue
            settled = insight.get("settled", False)
            positive = insight.get("positive", False)
            tags = []
            if settled:
                tags.append("settled")
            if positive:
                tags.append("+")
            prefix = f"[{', '.join(tags)}] " if tags else ""
            lines.append(f"- {prefix}{header}")
        if len(lines) > 1:
            sections.append("\n".join(lines))

    if not sections:
        return ""

    header_block = (
        "## Codebase Characteristics\n\n"
        "Previous reviews established these characteristics. [+] marks positive\n"
        "patterns; [settled] means confirmed. Augment this list: add new\n"
        "observations, refine descriptions, settle or remove items as needed.\n"
        "For full details, read `dimension_contexts.{dimension}.insights`.\n\n"
    )
    footer = (
        "\nPrinciples: Keep your own context updates succinct. Each insight should have\n"
        "a clear header (5-10 words) and a description explaining WHY, not WHAT.\n"
        "Positive patterns get `positive: true`. Settle items when confident.\n\n"
    )
    return header_block + "\n\n".join(sections) + footer


def render_scoring_frame() -> str:
    return (
        "YOUR TASK: Read the code for this batch's dimension. Judge "
        "how well the codebase serves a developer from that perspective. The dimension "
        "rubric above defines what good looks like. "
        "Cite specific observations that explain your judgment.\n\n"
    )


def render_scan_evidence_note() -> str:
    return (
        "Mechanical scan evidence — navigation aid, not scoring evidence:\n"
        "The blind packet contains `holistic_context.scan_evidence` with aggregated signals "
        "from all mechanical detectors — including complexity hotspots, error hotspots, signal "
        "density index, boundary violations, and systemic patterns. Use these as starting "
        "points for where to look beyond the seed files.\n\n"
    )


def render_task_requirements(*, issues_cap: int, dim_set: set[str]) -> str:
    dim_focus = render_dimension_focus(dim_set)
    lines = [
        "Phase 1 — Observe:",
        "1. Read the blind packet's `system_prompt` — scoring rules and calibration.",
        "2. Study the dimension rubric (description, look_for, skip).",
        "3. Review the existing characteristics list — which are settled? Which are positive? What needs updating?",
        "4. Explore the codebase freely. Use scan evidence, historical issues, and mechanical findings as navigation aids.",
        "5. Adjudicate mechanical concern signals (confirm/dismiss with fingerprint).",
        "6. Augment the characteristics list via context_updates: positive patterns (positive: true), neutral characteristics, design insights.",
        "7. Collect defects for issues[].",
        "8. Respect scope controls: exclude files/directories marked by `exclude`, `suppress`, or non-production zone overrides.",
        "9. Output a Phase 1 summary: list ALL characteristics for this dimension (existing + new, mark [+] for positive) and all defects collected. This is your consolidated reference for Phase 2.",
        "",
        "Phase 2 — Judge (after Phase 1 is complete):",
        "10. Keep issues and scoring scoped to this batch's dimension.",
        f"11. Return 0-{issues_cap} issues for this batch (empty array allowed).",
    ]
    next_num = 12
    if dim_focus:
        for focus_line in dim_focus.rstrip("\n").split("\n"):
            lines.append(f"{next_num}. {focus_line.lstrip('0123456789abcdefghij. ')}")
            next_num += 1
    lines.append(
        f"{next_num}. Complete `dimension_judgment`: write dimension_character "
        "(synthesizing characteristics and defects) then score_rationale. "
        "Set the score LAST."
    )
    next_num += 1
    lines.append(
        f"{next_num}. Output context_updates with your Phase 1 observations. "
        "Use `add` with a clear header (5-10 words) and description (1-3 "
        "sentences focused on WHY, not WHAT). Positive patterns get "
        "`positive: true`. New insights can be `settled: true` when confident. "
        "Use `settle` to promote existing unsettled insights. Use `remove` for "
        "insights no longer true. Omit context_updates if no changes."
    )
    next_num += 1
    lines.append(f"{next_num}. Do not edit repository files.")
    next_num += 1
    lines.append(f"{next_num}. Return ONLY valid JSON, no markdown fences.")
    return "\n".join(lines) + "\n\n"


def render_scope_enums() -> str:
    return (
        "Scope enums:\n"
        '- impact_scope: "local" | "module" | "subsystem" | "codebase"\n'
        '- fix_scope: "single_edit" | "multi_file_refactor" | "architectural_change"\n\n'
    )


def join_non_empty_sections(*sections: str) -> str:
    return "".join(section for section in sections if section)


__all__ = [
    "PromptBatchContext",
    "PromptBatchPayload",
    "batch_dimension_prompts",
    "coerce_string_list",
    "build_batch_context",
    "explode_to_single_dimension",
    "render_dimension_context_block",
    "render_dimension_prompts_block",
    "SCAN_EVIDENCE_FOCUS_BY_DIMENSION",
    "render_scan_evidence_focus",
    "render_historical_focus",
    "render_dimension_deferral_context",
    "render_findings_exploration_section",
    "render_judgment_findings_section",
    "render_mechanical_concern_signals",
    "render_workflow_integrity_focus",
    "render_package_org_focus",
    "render_abstraction_focus",
    "render_dimension_focus",
    "render_scoring_frame",
    "render_scan_evidence_note",
    "render_task_requirements",
    "render_scope_enums",
    "join_non_empty_sections",
]
