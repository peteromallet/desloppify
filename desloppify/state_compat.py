"""Compatibility facade for legacy `desloppify.state` imports.

New code should prefer narrower modules such as `desloppify.state_io` and
`desloppify.state_score_snapshot`, but this module preserves the historical
surface for callers that still import the old umbrella API.
"""

from desloppify.engine._state.filtering import (
    add_ignore,
    is_ignored,
    issue_in_scan_scope,
    make_issue,
    open_scope_breakdown,
    path_scoped_issues,
    remove_ignored_issues,
)
from desloppify.engine._state.merge import (
    MergeScanOptions,
    find_suspect_detectors,
    merge_scan,
    upsert_issues,
)
from desloppify.engine._state.noise import (
    DEFAULT_ISSUE_NOISE_BUDGET,
    DEFAULT_ISSUE_NOISE_GLOBAL_BUDGET,
    apply_issue_noise_budget,
    resolve_issue_noise_budget,
    resolve_issue_noise_global_budget,
    resolve_issue_noise_settings,
)
from desloppify.engine._state.persistence import load_state, save_state, state_lock
from desloppify.engine._state.resolution import (
    coerce_assessment_score,
    match_issues,
    resolve_issue_ids,
    resolve_issues,
)
from desloppify.engine._state.schema import (
    CURRENT_VERSION,
    ConcernDismissal,
    DimensionScore,
    Issue,
    ScanMetadataModel,
    StateModel,
    StateStats,
    SubjectiveAssessment,
    SubjectiveIntegrity,
    empty_state,
    ensure_state_defaults,
    get_state_dir,
    get_state_file,
    json_default,
    migrate_state_keys,
    scan_inventory_available,
    scan_metadata,
    scan_reconstructed_issue_count,
    scan_source,
    scan_metrics_available,
    utc_now,
    validate_state_invariants,
)
from desloppify.engine._state.schema_scores import (
    get_objective_score,
    get_overall_score,
    get_strict_score,
    get_verified_strict_score,
)
from desloppify.state_score_snapshot import (
    ScoreSnapshot,
    score_snapshot,
    suppression_metrics,
)

__all__ = [
    "ConcernDismissal",
    "CURRENT_VERSION",
    "DEFAULT_ISSUE_NOISE_BUDGET",
    "DEFAULT_ISSUE_NOISE_GLOBAL_BUDGET",
    "DimensionScore",
    "Issue",
    "MergeScanOptions",
    "ScanMetadataModel",
    "ScoreSnapshot",
    "StateModel",
    "StateStats",
    "SubjectiveAssessment",
    "SubjectiveIntegrity",
    "add_ignore",
    "apply_issue_noise_budget",
    "coerce_assessment_score",
    "empty_state",
    "ensure_state_defaults",
    "find_suspect_detectors",
    "get_objective_score",
    "get_overall_score",
    "get_state_dir",
    "get_state_file",
    "get_strict_score",
    "get_verified_strict_score",
    "is_ignored",
    "issue_in_scan_scope",
    "json_default",
    "load_state",
    "make_issue",
    "match_issues",
    "merge_scan",
    "migrate_state_keys",
    "open_scope_breakdown",
    "path_scoped_issues",
    "remove_ignored_issues",
    "resolve_issue_noise_budget",
    "resolve_issue_noise_global_budget",
    "resolve_issue_noise_settings",
    "resolve_issue_ids",
    "resolve_issues",
    "save_state",
    "scan_inventory_available",
    "scan_metadata",
    "scan_metrics_available",
    "scan_reconstructed_issue_count",
    "scan_source",
    "score_snapshot",
    "state_lock",
    "suppression_metrics",
    "upsert_issues",
    "utc_now",
    "validate_state_invariants",
]
