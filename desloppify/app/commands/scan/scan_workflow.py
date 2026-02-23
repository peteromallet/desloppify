"""Shared scan workflow phases used by the scan command facade."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from desloppify.languages._framework.runtime import LangRun

from desloppify import state as state_mod
from desloppify.app.commands.helpers.lang import resolve_lang, resolve_lang_settings
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.runtime_options import resolve_lang_runtime_options
from desloppify.app.commands.helpers.score import target_strict_score_from_config
from desloppify.app.commands.scan.scan_helpers import (
    _audit_excluded_dirs,
    _collect_codebase_metrics,
    _effective_include_slow,
    _resolve_scan_profile,
    _warn_explicit_lang_with_no_files,
)
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.engine.planning import core as plan_mod
from desloppify.engine.planning.scan import PlanScanOptions
from desloppify.engine import work_queue as issues_mod
from desloppify.file_discovery import (
    disable_file_cache,
    enable_file_cache,
    get_exclusions,
    rel,
    resolve_path,
)
from desloppify.languages._framework.runtime import LangRunOverrides, make_lang_run
from desloppify.utils import colorize

_WONTFIX_DECAY_SCANS_DEFAULT = 20
_STRUCTURAL_COMPLEXITY_GROWTH_THRESHOLD = 10
_STRUCTURAL_LOC_GROWTH_THRESHOLD = 50


def _subjective_reset_dimensions(*, lang_name: str | None = None) -> tuple[str, ...]:
    """Resolve subjective dimensions that should reset on scan baseline reset."""
    from desloppify.intelligence.review.dimensions.metadata import (
        resettable_default_dimensions,
    )

    return resettable_default_dimensions(lang_name=lang_name)


@dataclass
class ScanRuntime:
    """Resolved runtime context for a single scan invocation."""

    args: argparse.Namespace
    state_path: Path | None
    state: dict
    path: Path
    config: dict
    lang: LangRun | None
    lang_label: str
    profile: str
    effective_include_slow: bool
    zone_overrides: dict | None
    reset_subjective_count: int = 0


@dataclass
class ScanMergeResult:
    """State merge outputs and previous score snapshots."""

    diff: dict
    prev_overall: float | None
    prev_objective: float | None
    prev_strict: float | None
    prev_verified: float | None
    prev_dim_scores: dict


@dataclass
class ScanNoiseSnapshot:
    """Noise budget settings and hidden finding counts for this scan."""

    noise_budget: int
    global_noise_budget: int
    budget_warning: str | None
    hidden_by_detector: dict[str, int]
    hidden_total: int


def _configure_lang_runtime(
    args: argparse.Namespace,
    config: dict,
    state: dict,
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
            review_cache=state.get("review_cache", {}),
            review_max_age_days=config.get("review_max_age_days", 30),
            runtime_settings=lang_settings,
            runtime_options=lang_options,
            large_threshold_override=config.get("large_files_threshold", 0),
            props_threshold_override=config.get("props_threshold", 0),
        ),
    )

    state.setdefault("lang_capabilities", {})[runtime_lang.name] = {
        "fixers": sorted(runtime_lang.fixers.keys()),
        "typecheck_cmd": runtime_lang.typecheck_cmd,
    }
    return runtime_lang


def _reset_subjective_assessments_for_scan_reset(
    state: dict,
    *,
    lang_name: str | None = None,
) -> int:
    """Reset known subjective dimensions to 0 so the next scan starts fresh."""
    assessments = state.setdefault("subjective_assessments", {})
    if not isinstance(assessments, dict):
        assessments = {}
        state["subjective_assessments"] = assessments

    reset_keys = {
        key.strip()
        for key in assessments
        if isinstance(key, str) and key.strip()
    }
    reset_keys.update(_subjective_reset_dimensions(lang_name=lang_name))

    now = state_mod.utc_now()
    for key in sorted(reset_keys):
        payload = assessments.get(key)
        if isinstance(payload, dict):
            payload["score"] = 0.0
            payload["source"] = "scan_reset_subjective"
            payload["assessed_at"] = now
            payload["reset_by"] = "scan_reset_subjective"
            payload["placeholder"] = True
            payload.pop("integrity_penalty", None)
            payload.pop("components", None)
            payload.pop("component_scores", None)
            continue
        assessments[key] = {
            "score": 0.0,
            "source": "scan_reset_subjective",
            "assessed_at": now,
            "reset_by": "scan_reset_subjective",
            "placeholder": True,
        }
    return len(reset_keys)


def prepare_scan_runtime(args) -> ScanRuntime:
    """Resolve state/config/language and apply scan-time runtime settings."""
    runtime = command_runtime(args)
    state_file = runtime.state_path
    state = runtime.state
    path = Path(args.path)
    config = runtime.config
    lang_config = resolve_lang(args)
    reset_subjective_count = 0
    if getattr(args, "reset_subjective", False):
        reset_subjective_count = _reset_subjective_assessments_for_scan_reset(
            state,
            lang_name=getattr(lang_config, "name", None),
        )

    include_slow = not getattr(args, "skip_slow", False)
    profile = _resolve_scan_profile(getattr(args, "profile", None), lang_config)
    effective_include_slow = _effective_include_slow(include_slow, profile)

    lang = _configure_lang_runtime(args, config, state, lang_config)

    return ScanRuntime(
        args=args,
        state_path=state_file,
        state=state,
        path=path,
        config=config,
        lang=lang,
        lang_label=f" ({lang.name})" if lang else "",
        profile=profile,
        effective_include_slow=effective_include_slow,
        zone_overrides=config.get("zone_overrides") or None,
        reset_subjective_count=reset_subjective_count,
    )


def _augment_with_stale_exclusion_findings(
    findings: list[dict],
    runtime: ScanRuntime,
) -> list[dict]:
    """Append stale exclude findings when excluded dirs are unreferenced."""
    extra_exclusions = get_exclusions()
    if not (extra_exclusions and runtime.lang and runtime.lang.file_finder):
        return findings

    scanned_files = runtime.lang.file_finder(runtime.path)
    stale = _audit_excluded_dirs(
        extra_exclusions, scanned_files, PROJECT_ROOT
    )
    if not stale:
        return findings

    augmented = list(findings)
    augmented.extend(stale)
    for stale_finding in stale:
        print(colorize(f"  ℹ {stale_finding['summary']}", "dim"))
    return augmented


def _in_scan_scope(filepath: str, scan_path: Path) -> bool:
    if scan_path.resolve() == PROJECT_ROOT.resolve():
        return True
    full = Path(resolve_path(filepath))
    root = scan_path.resolve()
    return full == root or root in full.parents


def _to_float(value: object) -> float | None:
    if isinstance(value, bool):
        return None
    if not isinstance(value, int | float | str):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _structural_growth_details(snapshot: dict, current: dict) -> dict:
    """Return structural drift details for wontfix findings."""
    snapshot_detail = (
        snapshot.get("detail", {}) if isinstance(snapshot.get("detail"), dict) else {}
    )
    current_detail = current.get("detail", {}) if isinstance(current.get("detail"), dict) else {}
    drift: dict[str, dict[str, float]] = {}

    old_complexity = _to_float(snapshot_detail.get("complexity_score"))
    new_complexity = _to_float(current_detail.get("complexity_score"))
    if (
        old_complexity is not None
        and new_complexity is not None
        and new_complexity >= old_complexity + _STRUCTURAL_COMPLEXITY_GROWTH_THRESHOLD
    ):
        drift["complexity_score"] = {"from": old_complexity, "to": new_complexity}

    old_loc = _to_float(snapshot_detail.get("loc"))
    new_loc = _to_float(current_detail.get("loc"))
    if old_loc is not None and new_loc is not None and new_loc >= old_loc + _STRUCTURAL_LOC_GROWTH_THRESHOLD:
        drift["loc"] = {"from": old_loc, "to": new_loc}

    return drift


def _wontfix_staleness_reasons(
    previous: dict,
    current: dict,
    *,
    since_scan: int,
    decay_scans: int,
) -> tuple[list[str], dict]:
    """Determine why a wontfix finding is stale and compute structural drift."""
    reasons: list[str] = []
    if decay_scans > 0 and since_scan >= decay_scans:
        reasons.append("scan_decay")

    drift: dict = {}
    if previous.get("detector") == "structural":
        snapshot = previous.get("wontfix_snapshot")
        if isinstance(snapshot, dict):
            drift = _structural_growth_details(snapshot, current)
            if drift:
                reasons.append("severity_drift")

    return reasons, drift


def _format_drift_summary(drift: dict) -> str:
    """Format structural drift metrics into a human-readable suffix."""
    parts = []
    if "complexity_score" in drift:
        comp = drift["complexity_score"]
        parts.append(f"complexity {comp['from']:.0f}->{comp['to']:.0f}")
    if "loc" in drift:
        loc = drift["loc"]
        parts.append(f"loc {loc['from']:.0f}->{loc['to']:.0f}")
    return f"; drift: {', '.join(parts)}" if parts else ""


def _build_stale_wontfix_finding(
    finding_id: str,
    previous: dict,
    *,
    reasons: list[str],
    drift: dict,
    since_scan: int,
) -> dict:
    """Construct a stale_wontfix finding from staleness metadata."""
    tier = 4 if "severity_drift" in reasons else 3
    confidence = "high" if "severity_drift" in reasons else "medium"
    reason_text = " + ".join(reasons)
    summary = (
        f"Stale wontfix ({reason_text}): re-triage `{finding_id}` "
        f"(last reviewed {since_scan} scans ago)"
    )
    summary += _format_drift_summary(drift)

    return state_mod.make_finding(
        "stale_wontfix",
        previous.get("file", ""),
        finding_id,
        tier=tier,
        confidence=confidence,
        summary=summary,
        detail={
            "subtype": "stale_wontfix",
            "original_finding_id": finding_id,
            "original_detector": previous.get("detector"),
            "reasons": reasons,
            "scans_since_wontfix": since_scan,
            "drift": drift,
        },
    )


def _augment_with_stale_wontfix_findings(
    findings: list[dict],
    runtime: ScanRuntime,
    *,
    decay_scans: int,
) -> tuple[list[dict], int]:
    """Append re-triage findings for stale/worsening wontfix debt."""
    existing = runtime.state.get("findings", {})
    if not isinstance(existing, dict):
        return findings, 0

    current_by_id = {finding.get("id"): finding for finding in findings if finding.get("id")}
    augmented = list(findings)
    monitored = 0

    for finding_id, previous in existing.items():
        if previous.get("status") != "wontfix":
            continue
        if finding_id not in current_by_id:
            continue
        if not _in_scan_scope(previous.get("file", ""), runtime.path):
            continue

        monitored += 1
        since_scan = int(runtime.state.get("scan_count", 0) or 0) - int(
            previous.get("wontfix_scan_count", runtime.state.get("scan_count", 0) or 0)
        )
        since_scan = max(since_scan, 0)

        reasons, drift = _wontfix_staleness_reasons(
            previous, current_by_id[finding_id],
            since_scan=since_scan, decay_scans=decay_scans,
        )
        if not reasons:
            continue

        augmented.append(
            _build_stale_wontfix_finding(
                finding_id, previous,
                reasons=reasons, drift=drift, since_scan=since_scan,
            )
        )

    return augmented, monitored


def run_scan_generation(runtime: ScanRuntime) -> tuple[list[dict], dict, dict | None]:
    """Run detector pipeline and return findings, potentials, and codebase metrics."""
    from desloppify.languages._framework.treesitter import (
        disable_parse_cache,
        enable_parse_cache,
    )

    enable_file_cache()
    enable_parse_cache()
    try:
        findings, potentials = plan_mod.generate_findings(
            runtime.path,
            lang=runtime.lang,
            options=PlanScanOptions(
                include_slow=runtime.effective_include_slow,
                zone_overrides=runtime.zone_overrides,
                profile=runtime.profile,
            ),
        )
    finally:
        disable_parse_cache()
        disable_file_cache()

    codebase_metrics = _collect_codebase_metrics(runtime.lang, runtime.path)
    _warn_explicit_lang_with_no_files(
        runtime.args, runtime.lang, runtime.path, codebase_metrics
    )
    findings = _augment_with_stale_exclusion_findings(findings, runtime)
    decay_scans = int(
        runtime.config.get("wontfix_decay_scans", _WONTFIX_DECAY_SCANS_DEFAULT)
    )
    findings, monitored_wontfix = _augment_with_stale_wontfix_findings(
        findings,
        runtime,
        decay_scans=max(decay_scans, 0),
    )
    potentials["stale_wontfix"] = monitored_wontfix
    return findings, potentials, codebase_metrics


def merge_scan_results(
    runtime: ScanRuntime,
    findings: list[dict],
    potentials: dict,
    codebase_metrics: dict | None,
) -> ScanMergeResult:
    """Merge findings into persistent state and return diff + previous score snapshot."""
    scan_path_rel = rel(str(runtime.path))
    prev_scan_path = runtime.state.get("scan_path")
    path_changed = prev_scan_path is not None and prev_scan_path != scan_path_rel

    if not path_changed:
        prev = state_mod.score_snapshot(runtime.state)
    else:
        prev = state_mod.ScoreSnapshot(None, None, None, None)
    prev_dim_scores = (
        runtime.state.get("dimension_scores", {}) if not path_changed else {}
    )

    if runtime.lang and runtime.lang.zone_map is not None:
        runtime.state["zone_distribution"] = runtime.lang.zone_map.counts()

    target_score = target_strict_score_from_config(runtime.config, fallback=95.0)

    diff = state_mod.merge_scan(
        runtime.state,
        findings,
        options=state_mod.MergeScanOptions(
            lang=runtime.lang.name if runtime.lang else None,
            scan_path=scan_path_rel,
            force_resolve=getattr(runtime.args, "force_resolve", False),
            exclude=get_exclusions(),
            potentials=potentials,
            codebase_metrics=codebase_metrics,
            include_slow=runtime.effective_include_slow,
            ignore=runtime.config.get("ignore", []),
            subjective_integrity_target=target_score,
        ),
    )

    issues_mod.expire_stale_holistic(
        runtime.state, runtime.config.get("holistic_max_age_days", 30)
    )
    state_mod.save_state(
        runtime.state,
        runtime.state_path,
        subjective_integrity_target=target_score,
    )

    return ScanMergeResult(
        diff=diff,
        prev_overall=prev.overall,
        prev_objective=prev.objective,
        prev_strict=prev.strict,
        prev_verified=prev.verified,
        prev_dim_scores=prev_dim_scores,
    )


def resolve_noise_snapshot(state: dict, config: dict) -> ScanNoiseSnapshot:
    """Resolve noise budget settings and hidden finding counters."""
    noise_budget, global_noise_budget, budget_warning = (
        state_mod.resolve_finding_noise_settings(config)
    )
    open_findings = [
        finding
        for finding in state_mod.path_scoped_findings(
            state["findings"], state.get("scan_path")
        ).values()
        if finding.get("status") == "open"
    ]
    _, hidden_by_detector = state_mod.apply_finding_noise_budget(
        open_findings,
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


def persist_reminder_history(runtime: ScanRuntime, narrative: dict) -> None:
    """Persist reminder history emitted by narrative computation."""
    if not (narrative and "reminder_history" in narrative):
        return

    runtime.state["reminder_history"] = narrative["reminder_history"]
    target_score = target_strict_score_from_config(runtime.config, fallback=95.0)
    state_mod.save_state(
        runtime.state,
        runtime.state_path,
        subjective_integrity_target=target_score,
    )


__all__ = [
    "ScanMergeResult",
    "ScanNoiseSnapshot",
    "ScanRuntime",
    "merge_scan_results",
    "persist_reminder_history",
    "prepare_scan_runtime",
    "resolve_noise_snapshot",
    "run_scan_generation",
]
