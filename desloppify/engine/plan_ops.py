"""Focused public plan API for plan mutation operations."""

from __future__ import annotations

from desloppify.engine._plan.annotations import (
    annotation_counts,
    get_issue_description,
    get_issue_note,
    get_issue_override,
)
from desloppify.engine._plan.operations.cluster import (
    add_to_cluster,
    create_cluster,
    delete_cluster,
    merge_clusters,
    move_cluster,
    remove_from_cluster,
)
from desloppify.engine._plan.operations.lifecycle import (
    clear_focus,
    purge_ids,
    reset_plan,
    set_focus,
)
from desloppify.engine._plan.operations.meta import (
    annotate_issue,
    append_log_entry,
    describe_issue,
)
from desloppify.engine._plan.operations.queue import move_items, remove_queue_entries
from desloppify.engine._plan.operations.skip import (
    backlog_items,
    resurface_stale_skips,
    skip_items,
    unskip_items,
)
from desloppify.engine._plan.skip_policy import (
    SKIP_KIND_LABELS,
    SKIP_KIND_SECTION_LABELS,
    USER_SKIP_KINDS,
    skip_kind_from_flags,
    skip_kind_requires_attestation,
    skip_kind_requires_note,
    skip_kind_state_status,
)
from desloppify.engine._plan.step_completion import auto_complete_steps
from desloppify.engine._plan.step_parser import (
    format_steps,
    normalize_step,
    parse_steps_file,
    step_summary,
)

__all__ = [
    "SKIP_KIND_LABELS",
    "SKIP_KIND_SECTION_LABELS",
    "USER_SKIP_KINDS",
    "add_to_cluster",
    "annotate_issue",
    "annotation_counts",
    "append_log_entry",
    "backlog_items",
    "auto_complete_steps",
    "clear_focus",
    "create_cluster",
    "delete_cluster",
    "describe_issue",
    "format_steps",
    "get_issue_description",
    "get_issue_note",
    "get_issue_override",
    "merge_clusters",
    "move_cluster",
    "move_items",
    "normalize_step",
    "parse_steps_file",
    "purge_ids",
    "remove_queue_entries",
    "remove_from_cluster",
    "reset_plan",
    "resurface_stale_skips",
    "set_focus",
    "skip_items",
    "skip_kind_from_flags",
    "skip_kind_requires_attestation",
    "skip_kind_requires_note",
    "skip_kind_state_status",
    "step_summary",
    "unskip_items",
]
