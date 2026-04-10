"""Prompt template helpers for holistic review batch subagents."""

from __future__ import annotations

import json
from pathlib import Path

from desloppify.intelligence.review.feedback_contract import (
    DIMENSION_NOTE_ISSUES_KEY,
    HIGH_SCORE_ISSUES_NOTE_THRESHOLD,
)

from desloppify.intelligence.review.personas import PERSONAS, render_persona_block

from ..prompt_sections import (
    PromptBatchContext,
    batch_dimension_prompts,
    build_batch_context,
    join_non_empty_sections,
    render_dimension_context_block,
    render_dimension_deferral_context,
    render_dimension_prompts_block,
    render_historical_focus,
    render_judgment_findings_section,
    render_mechanical_concern_signals,
    render_scan_evidence_note,
    render_scope_enums,
    render_scoring_frame,
    render_task_requirements,
)

_CONTEXT_SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent.parent
    / "languages"
    / "_framework"
    / "review_data"
    / "context_schema.json"
)

_context_schema_cache: dict | None = None


def _load_context_schema() -> dict:
    global _context_schema_cache  # noqa: PLW0603
    if _context_schema_cache is None:
        _context_schema_cache = json.loads(_CONTEXT_SCHEMA_PATH.read_text())
    return _context_schema_cache


def _render_metadata_block(
    *,
    repo_root: Path,
    packet_path: Path,
    batch_index: int,
    context: PromptBatchContext,
) -> str:
    return (
        "You are a focused subagent reviewer for a single holistic investigation batch.\n\n"
        f"Repository root: {repo_root}\n"
        f"Blind packet: {packet_path}\n"
        f"Batch index: {batch_index + 1}\n"
        f"Batch name: {context.name}\n"
        f"Batch rationale: {context.rationale}\n\n"
    )


def _render_context_update_example() -> str:
    """Render a concrete context_updates example from the schema file."""
    try:
        schema = _load_context_schema()
        example = schema.get("example")
        if not isinstance(example, dict) or not example:
            return ""
        return "\n// context_updates example:\n" + json.dumps(example, indent=2) + "\n"
    except (OSError, json.JSONDecodeError, KeyError):
        return ""


def _render_output_schema(context: PromptBatchContext, batch_index: int) -> str:
    return (
        "Output schema:\n"
        "{\n"
        f'  "batch": "{context.name}",\n'
        f'  "batch_index": {batch_index + 1},\n'
        '  "assessments": {"<dimension>": <0-100 with one decimal place>},\n'
        '  "dimension_notes": {\n'
        '    "<dimension>": {\n'
        '      "evidence": ["specific code observations"],\n'
        '      "impact_scope": "local|module|subsystem|codebase",\n'
        '      "fix_scope": "single_edit|multi_file_refactor|architectural_change",\n'
        '      "confidence": "high|medium|low",\n'
        f'      "{DIMENSION_NOTE_ISSUES_KEY}": "required when score >{HIGH_SCORE_ISSUES_NOTE_THRESHOLD:.1f}",\n'
        '      "sub_axes": {"abstraction_leverage": 0-100, "indirection_cost": 0-100, "interface_honesty": 0-100, "delegation_density": 0-100, "definition_directness": 0-100, "type_discipline": 0-100}  // required for abstraction_fitness when evidence supports it; all one decimal place\n'
        "    }\n"
        "  },\n"
        '  "dimension_judgment": {\n'
        '    "<dimension>": {\n'
        '      "dimension_character": "2-3 sentences characterizing the overall nature of this dimension, synthesizing both positive characteristics and defects",\n'
        '      "score_rationale": "2-3 sentences explaining the score, referencing global anchors"\n'
        "    }  // required for every assessed dimension; do not omit\n"
        "  },\n"
        '  "issues": [{\n'
        '    "dimension": "<dimension>",\n'
        '    "identifier": "short_id",\n'
        '    "summary": "one-line defect summary",\n'
        '    "related_files": ["relative/path.py"],\n'
        '    "evidence": ["specific code observation"],\n'
        '    "suggestion": "concrete fix recommendation",\n'
        '    "confidence": "high|medium|low",\n'
        '    "impact_scope": "local|module|subsystem|codebase",\n'
        '    "fix_scope": "single_edit|multi_file_refactor|architectural_change",\n'
        '    "root_cause_cluster": "optional_cluster_name_when_supported_by_history",\n'
        '    "concern_verdict": "confirmed|dismissed  // for concern signals only",\n'
        '    "concern_fingerprint": "abc123  // required when dismissed; copy from signal fingerprint",\n'
        '    "reasoning": "why dismissed  // optional, for dismissed only"\n'
        "  }],\n"
        '  "retrospective": {\n'
        '    "root_causes": ["optional: concise root-cause hypotheses"],\n'
        '    "likely_symptoms": ["optional: identifiers that look symptom-level"],\n'
        '    "possible_false_positives": ["optional: prior concept keys likely mis-scoped"]\n'
        "  },\n"
        '  "context_updates": {\n'
        '    "<dimension>": {\n'
        '      "add": [{"header": "short label", "description": "why this is the way it is", "settled": true|false, "positive": true|false}],\n'
        '      "remove": ["header of insight to remove"],\n'
        '      "settle": ["header of insight to mark as settled"],\n'
        '      "unsettle": ["header of insight to unsettle"]\n'
        "    }  // omit context_updates entirely if no changes\n"
        "  }\n"
        "}\n"
        + _render_context_update_example()
    )

def _resolve_persona(name: str):
    """Look up a Persona by name, or return None."""
    if not name:
        return None
    name_lower = name.lower()
    for persona in PERSONAS:
        if persona.name.lower() == name_lower:
            return persona
    return None


def render_batch_prompt(
    *,
    repo_root: Path,
    packet_path: Path,
    batch_index: int,
    batch: dict[str, object],
    policy_block: str = "",
) -> str:
    """Render one subagent prompt for a holistic investigation batch."""
    context = build_batch_context(batch, batch_index)
    dim_prompts = context.dimension_prompts or batch_dimension_prompts(batch)
    dimension_contexts = batch.get("dimension_contexts") if isinstance(batch, dict) else None
    persona = _resolve_persona(context.persona)
    return join_non_empty_sections(
        _render_metadata_block(
            repo_root=repo_root,
            packet_path=packet_path,
            batch_index=batch_index,
            context=context,
        ),
        render_persona_block(persona),
        render_dimension_prompts_block(context.dimensions, dim_prompts),
        policy_block,
        render_scoring_frame(),
        render_dimension_context_block(
            context.dimensions,
            dimension_contexts if isinstance(dimension_contexts, dict) else {},
        ),
        render_scan_evidence_note(),
        render_historical_focus(batch),
        render_dimension_deferral_context(batch),
        render_mechanical_concern_signals(batch),
        render_judgment_findings_section(batch),
        render_task_requirements(issues_cap=context.issues_cap, dim_set=context.dimension_set),
        render_scope_enums(),
        _render_output_schema(context, batch_index),
    )


__all__ = ["render_batch_prompt"]
