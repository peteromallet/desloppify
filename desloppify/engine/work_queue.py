"""Public work-queue API facade.

Work-queue internals live in ``desloppify.engine._work_queue``; this module
exposes the stable, non-private API used by commands, rendering helpers, and
test suites.
"""

from __future__ import annotations

# --- core: queue building & options ----------------------------------------
from desloppify.engine._work_queue.core import (
    ATTEST_EXAMPLE,
    QueueBuildOptions,
    build_work_queue,
    group_queue_items,
)

# --- helpers: status/scope matching, item utilities ------------------------
from desloppify.engine._work_queue.helpers import (
    ALL_STATUSES,
    build_subjective_items,
    is_review_finding,
    is_subjective_finding,
    primary_command_for_finding,
    review_finding_weight,
    scope_matches,
    slugify,
    status_matches,
    subjective_strict_scores,
    supported_fixers_for_item,
)

# --- ranking: sort keys, tier counts, grouping -----------------------------
from desloppify.engine._work_queue.ranking import (
    build_finding_items,
    choose_fallback_tier,
    item_explain,
    item_sort_key,
    subjective_score_value,
    tier_counts,
)

# --- issues: review-finding work queue -------------------------------------
from desloppify.engine._work_queue.issues import (
    expire_stale_holistic,
    impact_label,
    list_open_review_findings,
    update_investigation,
)

__all__ = [
    # core
    "ATTEST_EXAMPLE",
    "QueueBuildOptions",
    "build_work_queue",
    "group_queue_items",
    # helpers
    "ALL_STATUSES",
    "build_subjective_items",
    "is_review_finding",
    "is_subjective_finding",
    "primary_command_for_finding",
    "review_finding_weight",
    "scope_matches",
    "slugify",
    "status_matches",
    "subjective_strict_scores",
    "supported_fixers_for_item",
    # ranking
    "build_finding_items",
    "choose_fallback_tier",
    "item_explain",
    "item_sort_key",
    "subjective_score_value",
    "tier_counts",
    # issues
    "expire_stale_holistic",
    "impact_label",
    "list_open_review_findings",
    "update_investigation",
]
