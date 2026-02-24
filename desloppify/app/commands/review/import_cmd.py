"""Import flow helpers for review command."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

from desloppify import state as state_mod
from desloppify.app.commands.helpers.query import write_query
from desloppify.app.commands.review import import_helpers as import_helpers_mod
from desloppify.app.commands.review import output as review_output_mod
from desloppify.intelligence import narrative as narrative_mod
from desloppify.intelligence import review as review_mod
from desloppify.intelligence.narrative.core import NarrativeContext
from desloppify.intelligence.review.dimensions import normalize_dimension_name
from desloppify.utils import colorize


def _resolve_override_context(
    *,
    manual_override: bool,
    manual_attest: str | None,
    assessment_override: bool,
    assessment_note: str | None,
) -> tuple[bool, str | None]:
    """Normalize legacy/new override flags to one override + attestation tuple."""
    override_enabled = bool(manual_override or assessment_override)
    override_attest = (
        manual_attest
        if isinstance(manual_attest, str) and manual_attest.strip()
        else assessment_note
    )
    return override_enabled, override_attest


def _enforce_import_flag_combos_or_exit(
    *,
    attested_external: bool,
    allow_partial: bool,
    override_enabled: bool,
    override_attest: str | None,
) -> None:
    """Fail fast on conflicting import flags to keep behavior explicit."""
    if attested_external and override_enabled:
        print(
            colorize(
                "  Error: --attested-external cannot be combined with --manual-override",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    if attested_external and allow_partial:
        print(
            colorize(
                "  Error: --attested-external cannot be combined with --allow-partial",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    if override_enabled and allow_partial:
        print(
            colorize(
                "  Error: --manual-override cannot be combined with --allow-partial",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(1)
    if override_enabled and (
        not isinstance(override_attest, str) or not override_attest.strip()
    ):
        print(
            colorize(
                "  Error: --manual-override requires --attest",
                "red",
            ),
            file=sys.stderr,
        )
        sys.exit(1)


def subjective_at_target_dimensions(
    state_or_dim_scores: dict,
    dim_scores: dict | None = None,
    *,
    target: float,
    scorecard_subjective_entries_fn,
    matches_target_score_fn,
) -> list[dict]:
    """Return scorecard-aligned subjective rows that sit on the target threshold."""
    state = state_or_dim_scores
    if dim_scores is None:
        dim_scores = state_or_dim_scores
        state = {"dimension_scores": dim_scores}

    rows: list[dict] = []
    for entry in scorecard_subjective_entries_fn(state, dim_scores=dim_scores):
        if entry.get("placeholder"):
            continue
        strict_val = float(entry.get("strict", entry.get("score", 100.0)))
        if matches_target_score_fn(strict_val, target):
            rows.append(
                {
                    "name": str(entry.get("name", "Subjective")),
                    "score": strict_val,
                    "cli_keys": list(entry.get("cli_keys", [])),
                }
            )
    rows.sort(key=lambda item: item["name"].lower())
    return rows


def _imported_assessment_keys(findings_data: dict) -> set[str]:
    """Return normalized assessment dimension keys from payload."""
    raw_assessments = findings_data.get("assessments")
    if not isinstance(raw_assessments, dict):
        return set()
    keys: set[str] = set()
    for raw_key in raw_assessments:
        normalized = normalize_dimension_name(str(raw_key))
        if normalized:
            keys.add(normalized)
    return keys


def _mark_manual_override_assessments_provisional(
    state: dict,
    *,
    assessment_keys: set[str],
) -> int:
    """Mark imported manual override assessments as provisional until next scan."""
    if not assessment_keys:
        return 0
    store = state.get("subjective_assessments")
    if not isinstance(store, dict):
        return 0

    now = state_mod.utc_now()
    expires_scan = int(state.get("scan_count", 0) or 0) + 1
    marked = 0
    for key in sorted(assessment_keys):
        payload = store.get(key)
        if not isinstance(payload, dict):
            continue
        payload["source"] = "manual_override"
        payload["assessed_at"] = now
        payload["provisional_override"] = True
        payload["provisional_until_scan"] = expires_scan
        payload.pop("placeholder", None)
        marked += 1
    return marked


def _clear_provisional_override_flags(
    state: dict,
    *,
    assessment_keys: set[str],
) -> int:
    """Clear provisional override flags when trusted internal assessments replace them."""
    if not assessment_keys:
        return 0
    store = state.get("subjective_assessments")
    if not isinstance(store, dict):
        return 0

    cleared = 0
    for key in sorted(assessment_keys):
        payload = store.get(key)
        if not isinstance(payload, dict):
            continue
        if payload.pop("provisional_override", None) is not None:
            cleared += 1
        payload.pop("provisional_until_scan", None)
        if payload.get("source") == "manual_override":
            payload["source"] = "holistic"
    return cleared


def do_import(
    import_file,
    state,
    lang,
    state_file,
    *,
    config: dict | None = None,
    allow_partial: bool = False,
    trusted_assessment_source: bool = False,
    trusted_assessment_label: str | None = None,
    attested_external: bool = False,
    manual_override: bool = False,
    manual_attest: str | None = None,
    assessment_override: bool = False,
    assessment_note: str | None = None,
) -> None:
    """Import mode: ingest agent-produced findings."""
    override_enabled, override_attest = _resolve_override_context(
        manual_override=manual_override,
        manual_attest=manual_attest,
        assessment_override=assessment_override,
        assessment_note=assessment_note,
    )
    _enforce_import_flag_combos_or_exit(
        attested_external=attested_external,
        allow_partial=allow_partial,
        override_enabled=override_enabled,
        override_attest=override_attest,
    )

    findings_data = import_helpers_mod.load_import_findings_data(
        import_file,
        colorize_fn=colorize,
        lang_name=lang.name,
        allow_partial=allow_partial,
        trusted_assessment_source=trusted_assessment_source,
        trusted_assessment_label=trusted_assessment_label,
        attested_external=attested_external,
        manual_override=override_enabled,
        manual_attest=override_attest,
        assessment_override=assessment_override,
        assessment_note=assessment_note,
    )
    assessment_policy = import_helpers_mod.assessment_policy_from_payload(findings_data)
    import_helpers_mod.print_assessment_mode_banner(
        assessment_policy,
        colorize_fn=colorize,
    )
    import_helpers_mod.print_assessment_policy_notice(
        assessment_policy,
        import_file=str(import_file),
        colorize_fn=colorize,
    )

    # Transactional import: only persist if all post-import guards pass.
    # Rebase on the latest on-disk state when available so long-running review
    # sessions don't clobber newer imports/scans that completed while batches ran.
    state_path = Path(state_file) if state_file is not None else None
    if state_path is not None and state_path.exists():
        working_state = copy.deepcopy(state_mod.load_state(state_path))
    else:
        working_state = copy.deepcopy(state)
    diff = review_mod.import_holistic_findings(findings_data, working_state, lang.name)
    label = "Holistic review"
    imported_assessment_keys = _imported_assessment_keys(findings_data)
    provisional_count = 0
    if assessment_policy.get("mode") == "manual_override":
        provisional_count = _mark_manual_override_assessments_provisional(
            working_state,
            assessment_keys=imported_assessment_keys,
        )
    elif assessment_policy.get("mode") in {"trusted_internal", "attested_external"}:
        _clear_provisional_override_flags(
            working_state,
            assessment_keys=imported_assessment_keys,
        )

    if diff.get("skipped", 0) > 0 and not allow_partial:
        print(
            colorize(
                "  Error: import produced skipped finding(s); refusing partial import.",
                "red",
            ),
            file=sys.stderr,
        )
        for detail in diff.get("skipped_details", []):
            reasons = "; ".join(detail.get("missing", []))
            print(
                colorize(
                    f"    #{detail.get('index', '?')} ({detail.get('identifier', '<none>')}): {reasons}",
                    "red",
                ),
                file=sys.stderr,
            )
        print(
            colorize(
                "  Fix the payload and retry, or pass --allow-partial to override.",
                "yellow",
            ),
            file=sys.stderr,
        )
        sys.exit(1)

    if assessment_policy.get("assessments_present"):
        audit = working_state.setdefault("assessment_import_audit", [])
        audit.append(
            {
                "timestamp": state_mod.utc_now(),
                "mode": str(assessment_policy.get("mode", "unknown")),
                "trusted": bool(assessment_policy.get("trusted", False)),
                "reason": str(assessment_policy.get("reason", "")),
                "override_used": bool(assessment_policy.get("mode") == "manual_override"),
                "attested_external": bool(
                    assessment_policy.get("mode") == "attested_external"
                ),
                "provisional": bool(assessment_policy.get("mode") == "manual_override"),
                "provisional_count": int(provisional_count),
                "attest": (override_attest or "").strip(),
                "import_file": str(import_file),
            }
        )
    state.clear()
    state.update(working_state)
    state_mod.save_state(state, state_file)

    lang_name = lang.name
    narrative = narrative_mod.compute_narrative(
        state, NarrativeContext(lang=lang_name, command="review")
    )

    print(colorize(f"\n  {label} imported:", "bold"))
    issue_count = int(diff.get("new", 0) or 0)
    print(
        colorize(
            f"  +{issue_count} new issue{'s' if issue_count != 1 else ''} "
            f"(review findings), "
            f"{diff['auto_resolved']} resolved, "
            f"{diff['reopened']} reopened",
            "dim",
        )
    )
    if provisional_count > 0:
        print(
            colorize(
                "  WARNING: manual override assessments are provisional and will "
                "reset on the next scan unless replaced by "
                "`review --run-batches --runner codex --parallel --scan-after-import`.",
                "yellow",
            )
        )
    import_helpers_mod.print_skipped_validation_details(diff, colorize_fn=colorize)
    import_helpers_mod.print_assessments_summary(state, colorize_fn=colorize)
    next_command = import_helpers_mod.print_open_review_summary(
        state, colorize_fn=colorize
    )
    at_target = review_output_mod._print_review_import_scores_and_integrity(
        state, config or {}
    )

    print(
        colorize(
            f"  Next command to improve subjective scores: `{next_command}`", "dim"
        )
    )
    write_query(
        {
            "command": "review",
            "action": "import",
            "mode": "holistic",
            "diff": diff,
            "next_command": next_command,
            "subjective_at_target": [
                {"dimension": entry["name"], "score": entry["score"]}
                for entry in at_target
            ],
            "assessment_import": {
                "mode": str(assessment_policy.get("mode", "none")),
                "trusted": bool(assessment_policy.get("trusted", False)),
                "reason": str(assessment_policy.get("reason", "")),
            },
            "narrative": narrative,
        }
    )


def do_validate_import(
    import_file,
    lang,
    *,
    allow_partial: bool = False,
    attested_external: bool = False,
    manual_override: bool = False,
    manual_attest: str | None = None,
    assessment_override: bool = False,
    assessment_note: str | None = None,
) -> None:
    """Validate import payload/policy and print mode without mutating state."""
    override_enabled, override_attest = _resolve_override_context(
        manual_override=manual_override,
        manual_attest=manual_attest,
        assessment_override=assessment_override,
        assessment_note=assessment_note,
    )
    _enforce_import_flag_combos_or_exit(
        attested_external=attested_external,
        allow_partial=allow_partial,
        override_enabled=override_enabled,
        override_attest=override_attest,
    )

    findings_data = import_helpers_mod.load_import_findings_data(
        import_file,
        colorize_fn=colorize,
        lang_name=lang.name,
        allow_partial=allow_partial,
        attested_external=attested_external,
        manual_override=override_enabled,
        manual_attest=override_attest,
        assessment_override=assessment_override,
        assessment_note=assessment_note,
    )
    assessment_policy = import_helpers_mod.assessment_policy_from_payload(findings_data)
    import_helpers_mod.print_assessment_mode_banner(
        assessment_policy,
        colorize_fn=colorize,
    )
    import_helpers_mod.print_assessment_policy_notice(
        assessment_policy,
        import_file=str(import_file),
        colorize_fn=colorize,
    )

    findings = findings_data.get("findings")
    findings_count = len(findings) if isinstance(findings, list) else 0
    print(colorize("\n  Import payload validation passed.", "bold"))
    print(colorize(f"  Findings parsed: {findings_count}", "dim"))
    if bool(assessment_policy.get("assessments_present")):
        count = int(assessment_policy.get("assessment_count", 0) or 0)
        print(colorize(f"  Assessment entries in payload: {count}", "dim"))
    print(colorize("  No state changes were made (--validate-import).", "dim"))


__all__ = ["do_import", "do_validate_import", "subjective_at_target_dimensions"]
