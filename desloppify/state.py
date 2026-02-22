"""Public state API facade.

State internals live in `desloppify.engine._state`; this module exposes the
stable, non-private API used by commands, review flows, and language phases.
"""

from typing import NamedTuple

from desloppify.engine._state.filtering import (
    add_ignore,
    is_ignored,
    make_finding,
    path_scoped_findings,
    remove_ignored_findings,
)
from desloppify.engine._state.merge import (
    MergeScanOptions,
    find_suspect_detectors,
    merge_scan,
    upsert_findings,
)
from desloppify.engine._state.noise import (
    DEFAULT_FINDING_NOISE_BUDGET,
    DEFAULT_FINDING_NOISE_GLOBAL_BUDGET,
    apply_finding_noise_budget,
    resolve_finding_noise_budget,
    resolve_finding_noise_global_budget,
    resolve_finding_noise_settings,
)
from desloppify.engine._state.persistence import load_state, save_state
from desloppify.engine._state.resolution import (
    coerce_assessment_score,
    match_findings,
    resolve_findings,
)

from desloppify.engine._state.schema import (
    CURRENT_VERSION,
    STATE_DIR,
    STATE_FILE,
    ConcernDismissal,
    DimensionScore,
    Finding,
    StateModel,
    StateStats,
    SubjectiveAssessment,
    SubjectiveIntegrity,
    empty_state,
    ensure_state_defaults,
    get_objective_score,
    get_overall_score,
    get_strict_score,
    get_verified_strict_score,
    json_default,
    utc_now,
    validate_state_invariants,
)
from desloppify.engine._state.scoring import (
    suppression_metrics,
)


class ScoreSnapshot(NamedTuple):
    """All four canonical scores from a single state dict."""

    overall: float | None
    objective: float | None
    strict: float | None
    verified: float | None


def score_snapshot(state: StateModel) -> ScoreSnapshot:
    """Load all four canonical scores from *state* in one call."""
    return ScoreSnapshot(
        overall=get_overall_score(state),
        objective=get_objective_score(state),
        strict=get_strict_score(state),
        verified=get_verified_strict_score(state),
    )


__all__ = [
    # Types
    "ConcernDismissal",
    "DimensionScore",
    "Finding",
    "MergeScanOptions",
    "ScoreSnapshot",
    "StateModel",
    "StateStats",
    "SubjectiveAssessment",
    "SubjectiveIntegrity",
    # Constants
    "CURRENT_VERSION",
    "DEFAULT_FINDING_NOISE_BUDGET",
    "DEFAULT_FINDING_NOISE_GLOBAL_BUDGET",
    "STATE_DIR",
    "STATE_FILE",
    # Functions
    "add_ignore",
    "apply_finding_noise_budget",
    "coerce_assessment_score",
    "empty_state",
    "ensure_state_defaults",
    "find_suspect_detectors",
    "get_objective_score",
    "get_overall_score",
    "get_strict_score",
    "get_verified_strict_score",
    "is_ignored",
    "json_default",
    "load_state",
    "make_finding",
    "match_findings",
    "merge_scan",
    "path_scoped_findings",
    "remove_ignored_findings",
    "resolve_finding_noise_budget",
    "resolve_finding_noise_global_budget",
    "resolve_finding_noise_settings",
    "resolve_findings",
    "save_state",
    "score_snapshot",
    "suppression_metrics",
    "upsert_findings",
    "utc_now",
    "validate_state_invariants",
]
