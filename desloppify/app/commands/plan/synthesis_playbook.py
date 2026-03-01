"""Shared synthesis workflow labels and canonical command snippets."""

from __future__ import annotations

SYNTHESIS_STAGE_LABELS: tuple[tuple[str, str], ...] = (
    ("observe", "Analyse findings & spot contradictions"),
    ("reflect", "Form strategy & present to user"),
    ("organize", "Defer contradictions, cluster, & prioritize"),
    ("commit", "Write strategy & confirm"),
)

SYNTHESIS_STAGE_DEPENDENCIES: dict[str, set[str]] = {
    "observe": set(),
    "reflect": {"observe"},
    "organize": {"reflect"},
    "commit": {"organize"},
}

SYNTH_CMD_OBSERVE = (
    'desloppify plan synthesize --stage observe --report '
    '"analysis of themes and root causes..."'
)
SYNTH_CMD_REFLECT = (
    'desloppify plan synthesize --stage reflect --report '
    '"comparison against completed work..."'
)
SYNTH_CMD_ORGANIZE = (
    'desloppify plan synthesize --stage organize --report '
    '"summary of organization and priorities..."'
)
SYNTH_CMD_COMPLETE = (
    'desloppify plan synthesize --complete --strategy "execution plan..."'
)
SYNTH_CMD_COMPLETE_VERBOSE = (
    "desloppify plan synthesize --complete --strategy "
    '"execution plan with priorities and verification..."'
)
SYNTH_CMD_CONFIRM_EXISTING = (
    'desloppify plan synthesize --confirm-existing --note "..." --strategy "..."'
)
SYNTH_CMD_CLUSTER_CREATE = (
    'desloppify plan cluster create <name> --description "..."'
)
SYNTH_CMD_CLUSTER_ADD = "desloppify plan cluster add <name> <finding-patterns>"
SYNTH_CMD_CLUSTER_ENRICH = (
    'desloppify plan cluster update <name> --description "..." --steps '
    '"step 1" "step 2"'
)
SYNTH_CMD_CLUSTER_ENRICH_COMPACT = (
    'desloppify plan cluster update <name> --description "..." --steps '
    '"step1" "step2"'
)
SYNTH_CMD_CLUSTER_STEPS = (
    'desloppify plan cluster update <name> --steps "step 1" "step 2"'
)

__all__ = [
    "SYNTHESIS_STAGE_DEPENDENCIES",
    "SYNTHESIS_STAGE_LABELS",
    "SYNTH_CMD_CLUSTER_ADD",
    "SYNTH_CMD_CLUSTER_CREATE",
    "SYNTH_CMD_CLUSTER_ENRICH",
    "SYNTH_CMD_CLUSTER_ENRICH_COMPACT",
    "SYNTH_CMD_CLUSTER_STEPS",
    "SYNTH_CMD_COMPLETE",
    "SYNTH_CMD_COMPLETE_VERBOSE",
    "SYNTH_CMD_CONFIRM_EXISTING",
    "SYNTH_CMD_OBSERVE",
    "SYNTH_CMD_ORGANIZE",
    "SYNTH_CMD_REFLECT",
]
