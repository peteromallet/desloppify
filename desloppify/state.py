"""Public state API facade.

State internals live in `desloppify.engine.state_internal`; this module exposes the
stable, non-private API used by commands, review flows, and language phases.
"""

from desloppify.engine.state_internal.filtering import (
    add_ignore,
    is_ignored,
    make_finding,
    path_scoped_findings,
    remove_ignored_findings,
)
from desloppify.engine.state_internal.merge import MergeScanOptions, merge_scan
from desloppify.engine.state_internal.noise import (
    DEFAULT_FINDING_NOISE_BUDGET,
    DEFAULT_FINDING_NOISE_GLOBAL_BUDGET,
    apply_finding_noise_budget,
    resolve_finding_noise_budget,
    resolve_finding_noise_global_budget,
    resolve_finding_noise_settings,
)
from desloppify.engine.state_internal.persistence import load_state, save_state
from desloppify.engine.state_internal.resolution import match_findings, resolve_findings
from desloppify.engine.state_internal.schema import (
    CURRENT_VERSION,
    STATE_DIR,
    STATE_FILE,
    Finding,
    get_objective_score,
    get_overall_score,
    get_strict_score,
    get_verified_strict_score,
    json_default,
    utc_now,
)
from desloppify.engine.state_internal.scoring import suppression_metrics

__all__ = [
    "CURRENT_VERSION",
    "DEFAULT_FINDING_NOISE_BUDGET",
    "DEFAULT_FINDING_NOISE_GLOBAL_BUDGET",
    "Finding",
    "MergeScanOptions",
    "STATE_DIR",
    "STATE_FILE",
    "add_ignore",
    "apply_finding_noise_budget",
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
    "suppression_metrics",
    "utc_now",
]
