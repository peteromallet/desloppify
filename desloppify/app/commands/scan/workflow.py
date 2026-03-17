"""Shared scan workflow phases used by the scan command facade."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from desloppify.languages.framework import LangRun

from desloppify.app.commands.helpers.lang import resolve_lang, resolve_lang_settings
from desloppify.app.commands.helpers.command_runtime import command_runtime
from desloppify.app.commands.helpers.runtime_options import resolve_lang_runtime_options
from desloppify.base.config import target_strict_score_from_config
from desloppify.app.commands.scan.coverage import (
    coerce_int as _coerce_int,
)
from desloppify.app.commands.scan.coverage import (
    persist_scan_coverage as _persist_scan_coverage,
)
from desloppify.app.commands.scan.coverage import (
    seed_runtime_coverage_warnings as _seed_runtime_coverage_warnings,
)
from desloppify.app.commands.scan.plan_reconcile import (
    reconcile_plan_post_scan as _reconcile_plan_post_scan_impl,
)
from desloppify.app.commands.scan.helpers import (
    audit_excluded_dirs,
    collect_codebase_metrics,
    effective_include_slow,
    resolve_scan_profile,
    warn_explicit_lang_with_no_files,
)
from desloppify.app.commands.scan.wontfix import (
    augment_with_stale_wontfix_issues as _augment_stale_wontfix_impl,
)
from desloppify.base.config import save_config as _save_config
from desloppify.base.discovery.file_paths import rel
from desloppify.base.output.terminal import colorize
from desloppify.base.discovery.source import (
    disable_file_cache,
    enable_file_cache,
    get_exclusions,
)
from desloppify.base.discovery.paths import get_project_root
from desloppify.engine._state.filtering import path_scoped_issues
from desloppify.engine._state.merge import MergeScanOptions, merge_scan
from desloppify.engine._state.noise import (
    apply_issue_noise_budget,
    resolve_issue_noise_settings,
)
from desloppify.engine._work_queue.issues import mark_stale_holistic
from desloppify.engine.planning.scan import PlanScanOptions, generate_issues as generate_plan_issues
from desloppify.base.subjective_dimensions import (
    resettable_default_dimensions,
)
from desloppify.languages.framework import (
    DetectorCoverageRecord,
    LangRunOverrides,
    disable_parse_cache,
    enable_parse_cache,
    make_lang_run,
    reset_script_import_caches,
)
from desloppify.state_io import StateModel, ensure_state_defaults, save_state, utc_now
from desloppify.state_scoring import ScoreSnapshot, score_snapshot

_WONTFIX_DECAY_SCANS_DEFAULT = 20


class ScanStateContractError(ValueError):
    """Raised when persisted scan state violates required runtime contracts."""


def _clear_needs_rescan_flag(config: dict[str, object]) -> None:
    """Best-effort clear for config.needs_rescan after a successful scan merge."""
    if not config.get("needs_rescan"):
        return
    try:
        config["needs_rescan"] = False
        _save_config(config)
    except OSError as exc:
        _ = exc
        config["needs_rescan"] = True


def _reconcile_plan_post_scan(runtime: ScanRuntime) -> None:
    """Reconcile plan queue metadata and stale subjective review dimensions."""
    _reconcile_plan_post_scan_impl(runtime)


def _state_subjective_assessments(
    state: StateModel,
) -> dict[str, object]:
    """Return normalized subjective assessment store from state."""
    assessments = state.get("subjective_assessments")
    if isinstance(assessments, dict):
        return assessments
    raise ScanStateContractError(
        "state.subjective_assessments must be an object; rerun with a valid state file"
    )


def _ensure_state_lang_capabilities(
    state: StateModel,
) -> dict[str, dict[str, object]]:
    """Return language capability map, creating storage when missing."""
    capabilities = state.get("lang_capabilities")
    if capabilities is None:
        normalized: dict[str, dict[str, object]] = {}
        state["lang_capabilities"] = normalized
        return normalized
    if isinstance(capabilities, dict):
        return capabilities
    raise ScanStateContractError(
        "state.lang_capabilities must be an object when present"
    )


def _state_review_cache(state: StateModel) -> dict[str, object]:
    """Return language review cache payload, creating storage when missing."""
    review_cache = state.get("review_cache")
    if review_cache is None:
        normalized: dict[str, object] = {}
        state["review_cache"] = normalized
        return normalized
    if isinstance(review_cache, dict):
        return review_cache
    raise ScanStateContractError(
        "state.review_cache must be an object when present"
    )


def _state_issues(state: StateModel) -> dict[str, dict[str, Any]]:
    """Return normalized issue map from state."""
    issues = state.get("work_items")
    if isinstance(issues, dict):
        return issues
    raise ScanStateContractError(
        "state.issues must be an object; state file appears corrupted"
    )


def _subjective_reset_dimensions(*, lang_name: str | None = None) -> tuple[str, ...]:
    """Resolve subjective dimensions that should reset on scan baseline reset."""
    return resettable_default_dimensions(lang_name=lang_name)


@dataclass
class ScanRuntime:
    """Resolved runtime context for a single scan invocation."""

    args: argparse.Namespace
    state_path: Path | None
    state: StateModel
    path: Path
    config: dict[str, object]
    lang: LangRun | None
    lang_label: str
    profile: str
    effective_include_slow: bool
    zone_overrides: dict[str, object] | None
    reset_subjective_count: int = 0
    coverage_warnings: list[DetectorCoverageRecord] = field(default_factory=list)
    force_rescan: bool = False


@dataclass
class ScanMergeResult:
    """State merge outputs and previous score snapshots."""

    diff: dict[str, object]
    prev_overall: float | None
    prev_objective: float | None
    prev_strict: float | None
    prev_verified: float | None
    prev_dim_scores: dict[str, object]


@dataclass
class ScanNoiseSnapshot:
    """Noise budget settings and hidden issue counts for this scan."""

    noise_budget: int
    global_noise_budget: int
    budget_warning: str | None
    hidden_by_detector: dict[str, int]
    hidden_total: int


def _configure_lang_runtime(
    args: argparse.Namespace,
    config: dict[str, object],
    state: StateModel,
    lang: LangRun | None,
) -> LangRun | None:
    """Populate runtime context and threshold overrides for a selected language."""
    if not lang:
        return None

    lang_options = resolve_lang_runtime_options(args, lang)
    lang_settings = resolve_lang_settings(config, lang)
    runtime_lang = make_lang_run(
        lang,
        overrides=LangRunOverrides(
            review_cache=_state_review_cache(state),
            review_max_age_days=config.get("review_max_age_days", 30),
            subjective_assessments=_state_subjective_assessments(state),
            runtime_settings=lang_settings,
            runtime_options=lang_options,
            large_threshold_override=config.get("large_files_threshold", 0),
            props_threshold_override=config.get("props_threshold", 0),
        ),
    )

    lang_capabilities = _ensure_state_lang_capabilities(state)
    lang_capabilities[runtime_lang.name] = {
        "fixers": sorted(runtime_lang.fixers.keys()),
        "typecheck_cmd": runtime_lang.typecheck_cmd,
    }
    return runtime_lang


def _apply_assessment_reset(payload: dict, *, source: str, now: str) -> None:
    """Apply a standard reset mutation to a single subjective assessment payload.

    Sets score to 0.0, stamps assessed_at/reset_by/placeholder, and strips
    any cached scoring artifacts (integrity_penalty, components,
    component_scores) plus provisional-override markers.
    """
    payload["score"] = 0.0
    payload["source"] = source
    payload["assessed_at"] = now
    payload["reset_by"] = source
    payload["placeholder"] = True
    payload.pop("integrity_penalty", None)
    payload.pop("components", None)
    payload.pop("component_scores", None)
    payload.pop("provisional_override", None)
    payload.pop("provisional_until_scan", None)


def _reset_subjective_assessments_for_scan_reset(
    state: StateModel,
    *,
    lang_name: str | None = None,
) -> int:
    """Reset known subjective dimensions to 0 so the next scan starts fresh."""
    assessments = _state_subjective_assessments(state)

    reset_keys = {
        key.strip()
        for key in assessments
        if isinstance(key, str) and key.strip()
    }
    reset_keys.update(_subjective_reset_dimensions(lang_name=lang_name))

    now = utc_now()
    source = "scan_reset_subjective"
    for key in sorted(reset_keys):
        payload = assessments.get(key)
        if isinstance(payload, dict):
            _apply_assessment_reset(payload, source=source, now=now)
            continue
        assessments[key] = {
            "score": 0.0,
            "source": source,
            "assessed_at": now,
            "reset_by": source,
            "placeholder": True,
        }
    return len(reset_keys)




def prepare_scan_runtime(args: argparse.Namespace) -> ScanRuntime:
    """Resolve state/config/language and apply scan-time runtime settings."""
    runtime = command_runtime(args)
    state_file = runtime.state_path
    state = runtime.state if isinstance(runtime.state, dict) else {}
    ensure_state_defaults(state)
    path = Path(args.path)
    reset_script_import_caches(str(path))
    config = runtime.config if isinstance(runtime.config, dict) else {}
    lang_config = resolve_lang(args)
    reset_subjective_count = 0
    if getattr(args, "reset_subjective", False):
        reset_subjective_count = _reset_subjective_assessments_for_scan_reset(
            state,
            lang_name=getattr(lang_config, "name", None),
        )

    include_slow = not getattr(args, "skip_slow", False)
    profile = resolve_scan_profile(getattr(args, "profile", None), lang_config)
    include_slow_effective = effective_include_slow(include_slow, profile)

    lang = _configure_lang_runtime(args, config, state, lang_config)
    coverage_warnings = _seed_runtime_coverage_warnings(lang)
    zone_overrides_raw = config.get("zone_overrides")
    zone_overrides = zone_overrides_raw if isinstance(zone_overrides_raw, dict) else None

    return ScanRuntime(
        args=args,
        state_path=state_file,
        state=state,
        path=path,
        config=config,
        lang=lang,
        lang_label=f" ({lang.name})" if lang else "",
        profile=profile,
        effective_include_slow=include_slow_effective,
        zone_overrides=zone_overrides,
        reset_subjective_count=reset_subjective_count,
        coverage_warnings=coverage_warnings,
        force_rescan=bool(getattr(args, "force_rescan", False)),
    )


def _augment_with_stale_exclusion_issues(
    issues: list[dict[str, Any]],
    runtime: ScanRuntime,
    *,
    scanned_files: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Append stale exclude issues when excluded dirs are unreferenced."""
    extra_exclusions = get_exclusions()
    if not (extra_exclusions and runtime.lang and runtime.lang.file_finder):
        return issues

    if scanned_files is None:
        scanned_files = runtime.lang.file_finder(runtime.path)
    stale = audit_excluded_dirs(
        extra_exclusions, scanned_files, get_project_root()
    )
    if not stale:
        return issues

    augmented = list(issues)
    augmented.extend(stale)
    for stale_issue in stale:
        print(colorize(f"  ℹ {stale_issue['summary']}", "dim"))
    return augmented


def _resolve_scanned_files(runtime: ScanRuntime) -> list[str]:
    """Resolve scan file list once for post-generation lifecycle steps."""
    if not runtime.lang:
        return []
    zone_map = getattr(runtime.lang, "zone_map", None)
    if zone_map is not None and hasattr(zone_map, "all_files"):
        files = zone_map.all_files()
        if isinstance(files, list):
            return files
    file_finder = getattr(runtime.lang, "file_finder", None)
    if not file_finder:
        return []
    return file_finder(runtime.path)


def _augment_with_stale_wontfix_issues(
    issues: list[dict[str, Any]],
    runtime: ScanRuntime,
    *,
    decay_scans: int,
) -> tuple[list[dict[str, Any]], int]:
    """Append re-triage issues for stale/worsening wontfix debt."""
    return _augment_stale_wontfix_impl(
        issues,
        state=runtime.state,
        scan_path=runtime.path,
        project_root=get_project_root(),
        decay_scans=decay_scans,
    )


def run_scan_generation(
    runtime: ScanRuntime,
) -> tuple[list[dict[str, Any]], dict[str, object], dict[str, object] | None]:
    """Run detector pipeline and return issues, potentials, and codebase metrics."""
    enable_file_cache()
    enable_parse_cache()
    try:
        issues, potentials = generate_plan_issues(
            runtime.path,
            lang=runtime.lang,
            options=PlanScanOptions(
                include_slow=runtime.effective_include_slow,
                zone_overrides=runtime.zone_overrides,
                profile=runtime.profile,
            ),
        )
        scanned_files = _resolve_scanned_files(runtime)
        codebase_metrics = collect_codebase_metrics(
            runtime.lang,
            runtime.path,
            files=scanned_files,
        )
        warn_explicit_lang_with_no_files(
            runtime.args, runtime.lang, runtime.path, codebase_metrics
        )
        issues = _augment_with_stale_exclusion_issues(
            issues,
            runtime,
            scanned_files=scanned_files,
        )
        decay_scans = _coerce_int(
            runtime.config.get("wontfix_decay_scans"),
            default=_WONTFIX_DECAY_SCANS_DEFAULT,
        )
        issues, monitored_wontfix = _augment_with_stale_wontfix_issues(
            issues,
            runtime,
            decay_scans=max(decay_scans, 0),
        )
        potentials["stale_wontfix"] = monitored_wontfix
        return issues, potentials, codebase_metrics
    finally:
        disable_parse_cache()
        disable_file_cache()


def merge_scan_results(
    runtime: ScanRuntime,
    issues: list[dict[str, Any]],
    potentials: dict[str, object],
    codebase_metrics: dict[str, object] | None,
) -> ScanMergeResult:
    """Merge issues into persistent state and return diff + previous score snapshot."""
    scan_path_rel = rel(str(runtime.path))
    prev_scan_path = runtime.state.get("scan_path")
    path_changed = prev_scan_path is not None and prev_scan_path != scan_path_rel

    if not path_changed:
        prev = score_snapshot(runtime.state)
    else:
        prev = ScoreSnapshot(None, None, None, None)
    prev_dim_scores = (
        runtime.state.get("dimension_scores", {}) if not path_changed else {}
    )

    if runtime.lang and runtime.lang.zone_map is not None:
        runtime.state["zone_distribution"] = runtime.lang.zone_map.counts()
    zone_lookup = runtime.lang.zone_map.get if runtime.lang and runtime.lang.zone_map is not None else None
    _persist_scan_coverage(runtime.state, runtime.lang)

    target_score = target_strict_score_from_config(runtime.config)

    diff = merge_scan(
        runtime.state,
        issues,
        options=MergeScanOptions(
            lang=runtime.lang.name if runtime.lang else None,
            scan_path=scan_path_rel,
            force_resolve=getattr(runtime.args, "force_resolve", False),
            exclude=get_exclusions(),
            potentials=potentials,
            codebase_metrics=codebase_metrics,
            include_slow=runtime.effective_include_slow,
            ignore=runtime.config.get("ignore", []),
            subjective_integrity_target=target_score,
            project_root=str(get_project_root()),
            zone_lookup=zone_lookup,
        ),
    )

    mark_stale_holistic(
        runtime.state, runtime.config.get("holistic_max_age_days", 30)
    )
    save_state(
        runtime.state,
        runtime.state_path,
        subjective_integrity_target=target_score,
    )

    _clear_needs_rescan_flag(runtime.config)
    _reconcile_plan_post_scan(runtime)

    return ScanMergeResult(
        diff=diff,
        prev_overall=prev.overall,
        prev_objective=prev.objective,
        prev_strict=prev.strict,
        prev_verified=prev.verified,
        prev_dim_scores=prev_dim_scores,
    )


def resolve_noise_snapshot(
    state: StateModel,
    config: dict[str, object],
) -> ScanNoiseSnapshot:
    """Resolve noise budget settings and hidden issue counters."""
    noise_budget, global_noise_budget, budget_warning = (
        resolve_issue_noise_settings(config)
    )
    issues_by_id = _state_issues(state)
    open_issues = [
        issue
        for issue in path_scoped_issues(
            issues_by_id, state.get("scan_path")
        ).values()
        if issue.get("status") == "open"
    ]
    _, hidden_by_detector = apply_issue_noise_budget(
        open_issues,
        budget=noise_budget,
        global_budget=global_noise_budget,
    )

    return ScanNoiseSnapshot(
        noise_budget=noise_budget,
        global_noise_budget=global_noise_budget,
        budget_warning=budget_warning,
        hidden_by_detector=hidden_by_detector,
        hidden_total=sum(hidden_by_detector.values()),
    )


def persist_reminder_history(
    runtime: ScanRuntime,
    narrative: dict[str, object],
) -> None:
    """Persist reminder history emitted by narrative computation."""
    if not (narrative and "reminder_history" in narrative):
        return

    runtime.state["reminder_history"] = narrative["reminder_history"]
    target_score = target_strict_score_from_config(runtime.config)
    save_state(
        runtime.state,
        runtime.state_path,
        subjective_integrity_target=target_score,
    )


__all__ = [
    "ScanStateContractError",
    "ScanMergeResult",
    "ScanNoiseSnapshot",
    "ScanRuntime",
    "merge_scan_results",
    "persist_reminder_history",
    "prepare_scan_runtime",
    "resolve_noise_snapshot",
    "run_scan_generation",
]
