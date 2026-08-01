"""Basic triage stage confirmation handlers (observe/reflect + attestation parsing)."""

from __future__ import annotations

import argparse

from desloppify.base.output.terminal import colorize
from desloppify.base.output.user_message import print_user_message
from desloppify.engine._plan.triage.protection import (
    clear_protected_triage_artifacts,
    protected_review_issue_ids_from_meta,
)

from ..services import TriageServices, default_triage_services
from ..stages.records import TriageStages
from .shared import (
    StageConfirmationRequest,
    ensure_stage_is_confirmable,
    finalize_stage_confirmation,
)

# Observe verdicts that trigger auto-skip on confirmation
_AUTO_SKIP_VERDICTS = frozenset({"false positive", "exaggerated"})


MIN_ATTESTATION_LEN = 80


def _find_referenced_names(text: str, names: list[str] | None) -> list[str]:
    if not names:
        return []
    return [
        name for name in names
        if name.lower().replace("_", " ") in text or name.lower() in text
    ]


def _contains_any(text: str, phrases: tuple[str, ...]) -> bool:
    return any(phrase in text for phrase in phrases)


def _count_phrase_hits(text: str, phrases: tuple[str, ...]) -> int:
    return sum(1 for phrase in phrases if phrase in text)


def _validate_observe_attestation(text: str, dimensions: list[str] | None) -> str | None:
    found = _find_referenced_names(text, dimensions)
    if found or not dimensions:
        return None
    dim_list = ", ".join(dimensions[:6])
    return f"Attestation must reference at least one dimension from the summary. Mention one of: {dim_list}"


def _validate_reflect_attestation(
    text: str,
    *,
    dimensions: list[str] | None,
    cluster_names: list[str] | None,
) -> str | None:
    refs = _find_referenced_names(text, dimensions) + _find_referenced_names(text, cluster_names)
    if refs or not (dimensions or cluster_names):
        return None
    return (
        "Attestation must reference at least one dimension or cluster name.\n"
        f"  Valid dimensions: {', '.join((dimensions or [])[:6])}\n"
        f"  Valid clusters: {', '.join((cluster_names or [])[:6]) if cluster_names else '(none yet)'}"
    )


def _validate_cluster_attestation(
    text: str,
    *,
    cluster_names: list[str] | None,
    action: str,
    stage: str,
) -> str | None:
    found = _find_referenced_names(text, cluster_names)
    if found or not cluster_names:
        return None
    if stage == "organize":
        if _contains_any(text, ("cluster", "clusters")) and _count_phrase_hits(
            text,
            ("priority", "priorities", "action step", "action steps", "description", "descriptions", "depends-on", "dependency", "dependencies", "issue", "issues", "consolidat"),
        ) >= 2:
            return None
    elif stage == "enrich":
        if _contains_any(text, ("step", "steps", "cluster", "clusters")) and _count_phrase_hits(
            text,
            ("executor-ready", "detail", "details", "file path", "file paths", "issue ref", "issue refs", "effort"),
        ) >= 2:
            return None
    elif stage == "sense-check":
        if _count_phrase_hits(
            text,
            ("content", "structure", "value", "cross-cluster", "dependency", "dependencies", "decision ledger", "enrich-level", "factually accurate"),
        ) >= 2 and _contains_any(text, ("verified", "safe", "pass", "passes", "recorded", "checked")):
            return None
    names = ", ".join(cluster_names[:6])
    return (
        f"Attestation must reference at least one cluster you {action}, or clearly describe the "
        f"verified {stage} work product. Mention one of: {names}"
    )


def validate_attestation(
    attestation: str,
    stage: str,
    *,
    dimensions: list[str] | None = None,
    cluster_names: list[str] | None = None,
) -> str | None:
    """Return error message if attestation doesn't reference required data."""
    text = attestation.lower()
    validators = {
        "observe": lambda: _validate_observe_attestation(text, dimensions),
        "reflect": lambda: _validate_reflect_attestation(
            text,
            dimensions=dimensions,
            cluster_names=cluster_names,
        ),
        "organize": lambda: _validate_cluster_attestation(
            text,
            cluster_names=cluster_names,
            action="organized",
            stage="organize",
        ),
        "enrich": lambda: _validate_cluster_attestation(
            text,
            cluster_names=cluster_names,
            action="enriched",
            stage="enrich",
        ),
        "sense-check": lambda: _validate_cluster_attestation(
            text,
            cluster_names=cluster_names,
            action="sense-checked",
            stage="sense-check",
        ),
    }
    validator = validators.get(stage)
    return validator() if validator is not None else None


def _apply_observe_auto_skips(
    plan: dict,
    meta: dict,
    services: TriageServices,
) -> int:
    """Create skip entries for false-positive/exaggerated dispositions.

    Returns the number of issues auto-skipped. Also updates the disposition
    map with decision/target/decision_source and removes auto-skipped IDs
    from queue_order.
    """
    from desloppify.state_io import utc_now

    clear_protected_triage_artifacts(plan)
    dispositions = meta.get("issue_dispositions", {})
    if not dispositions:
        return 0

    skipped = plan.setdefault("skipped", {})
    queue_order = plan.get("queue_order", [])
    protected_ids = protected_review_issue_ids_from_meta(meta)
    count = 0

    for issue_id, disp in dispositions.items():
        if issue_id in protected_ids:
            continue
        verdict = disp.get("verdict", "")
        if verdict not in _AUTO_SKIP_VERDICTS:
            continue
        # Don't double-skip
        if issue_id in skipped:
            continue
        skipped[issue_id] = {
            "issue_id": issue_id,
            "kind": "triage_observe_auto",
            "reason": verdict,
            "note": disp.get("verdict_reasoning", ""),
            "created_at": utc_now(),
            "skipped_at_scan": 0,
        }
        # Update disposition with auto-skip decision
        disp["decision"] = "skip"
        disp["target"] = verdict
        disp["decision_source"] = "observe_auto"
        count += 1

    # Remove auto-skipped IDs from queue_order
    if count:
        auto_skipped_ids = {
            issue_id for issue_id, disp in dispositions.items()
            if disp.get("decision_source") == "observe_auto"
        }
        plan["queue_order"] = [
            fid for fid in queue_order if fid not in auto_skipped_ids
        ]
        services.save_plan(plan)

    return count


def _undo_observe_auto_skips(plan: dict, meta: dict) -> int:
    """Remove previously auto-skipped entries before a fresh observe run.

    Returns the number of entries un-skipped.
    """
    clear_protected_triage_artifacts(plan)
    dispositions = meta.get("issue_dispositions", {})
    skipped = plan.get("skipped", {})
    protected_ids = protected_review_issue_ids_from_meta(meta)
    count = 0

    # Find all entries with decision_source == "observe_auto"
    auto_skipped_ids = {
        issue_id for issue_id, disp in dispositions.items()
        if disp.get("decision_source") == "observe_auto"
    }
    for issue_id in auto_skipped_ids:
        if issue_id in protected_ids:
            continue
        entry = skipped.get(issue_id)
        if entry and entry.get("kind") == "triage_observe_auto":
            del skipped[issue_id]
            count += 1

    return count


def confirm_observe(
    args: argparse.Namespace,
    plan: dict,
    stages: TriageStages,
    attestation: str | None,
    *,
    services: TriageServices | None = None,
) -> None:
    """Show observe summary and record confirmation if attestation is valid."""
    resolved_services = services or default_triage_services()
    if not ensure_stage_is_confirmable(stages, stage="observe"):
        return

    obs = stages["observe"]

    print(colorize("  Stage: OBSERVE — Verify queued issues against the code", "bold"))
    print(colorize("  " + "─" * 54, "dim"))

    by_dim = obs.get("dimension_counts", {})
    dim_names = obs.get("dimension_names", sorted(by_dim))
    issue_count = int(obs.get("issue_count", 0) or 0)
    print(f"  Your analysis covered {issue_count} issues across {len(by_dim)} dimensions:")
    for dim in dim_names:
        print(f"    {dim}: {by_dim[dim]} issues")

    cited = obs.get("cited_ids", [])
    if cited:
        print(f"  You cited {len(cited)} issue IDs in your report.")

    min_citations = min(5, max(1, issue_count // 10)) if issue_count > 0 else 0
    if len(cited) < min_citations:
        print(colorize(f"\n  Cannot confirm: only {len(cited)} issue ID(s) cited in report (need {min_citations}+).", "red"))
        print(colorize("  Your observe report should reference specific issues by their hash IDs to prove", "dim"))
        print(colorize("  you actually read them. Cite at least 10% of issues or 5, whichever is smaller.", "dim"))
        print(colorize("  Re-record observe with more issue citations, then re-confirm.", "dim"))
        return

    if not finalize_stage_confirmation(
        plan=plan,
        stages=stages,
        request=StageConfirmationRequest(
            stage="observe",
            attestation=attestation,
            min_attestation_len=MIN_ATTESTATION_LEN,
            command_hint='desloppify plan triage --confirm observe --attestation "I have thoroughly reviewed..."',
            validation_stage="observe",
            validate_attestation_fn=validate_attestation,
            validation_kwargs={"dimensions": dim_names},
            log_action="triage_confirm_observe",
            not_satisfied_hint="If not, continue reviewing issues before reflecting.",
        ),
        services=resolved_services,
    ):
        return

    # Auto-skip false-positive/exaggerated issues on observe confirmation
    meta = plan.get("epic_triage_meta", {})
    auto_skipped = _apply_observe_auto_skips(plan, meta, resolved_services)
    if auto_skipped:
        print(colorize(f"  Auto-skipped {auto_skipped} false-positive/exaggerated issue(s).", "green"))

    print_user_message(
        "Hey — observe is confirmed. Run `desloppify plan triage"
        " --stage reflect --report \"...\"` next. No need to reply,"
        " just keep going."
    )


def confirm_reflect(
    args: argparse.Namespace,
    plan: dict,
    stages: dict,
    attestation: str | None,
    *,
    services: TriageServices | None = None,
) -> None:
    """Show reflect summary and record confirmation if attestation is valid."""
    resolved_services = services or default_triage_services()
    if not ensure_stage_is_confirmable(stages, stage="reflect"):
        return

    runtime = resolved_services.command_runtime(args)
    si = resolved_services.collect_triage_input(plan, runtime.state)
    ref = stages["reflect"]

    print(colorize("  Stage: REFLECT — Form strategy & present to user", "bold"))
    print(colorize("  " + "─" * 50, "dim"))

    review_issues = getattr(si, "review_issues", getattr(si, "open_issues", {}))
    recurring = resolved_services.detect_recurring_patterns(review_issues, si.resolved_issues)
    if recurring:
        print(f"  Your strategy identified {len(recurring)} recurring dimension(s):")
        for dim, info in sorted(recurring.items()):
            resolved_count = len(info["resolved"])
            open_count = len(info["open"])
            label = "potential loop" if open_count >= resolved_count else "root cause unaddressed"
            print(f"    {dim}: {resolved_count} resolved, {open_count} still open — {label}")
    else:
        print("  No recurring patterns detected.")

    report = ref.get("report", "")
    if report:
        print()
        print(colorize("  ┌─ Your strategy briefing ───────────────────────┐", "cyan"))
        for line in report.strip().splitlines()[:8]:
            print(colorize(f"  │ {line}", "cyan"))
        if len(report.strip().splitlines()) > 8:
            print(colorize("  │ ...", "cyan"))
        print(colorize("  └" + "─" * 51 + "┘", "cyan"))

    observe_stage = stages.get("observe", {})
    observe_dims = list(observe_stage.get("dimension_names", []))
    reflect_dims = sorted(set((list(recurring.keys()) if recurring else []) + observe_dims))
    reflect_clusters = [name for name in plan.get("clusters", {}) if not plan["clusters"][name].get("auto")]

    if not finalize_stage_confirmation(
        plan=plan,
        stages=stages,
        request=StageConfirmationRequest(
            stage="reflect",
            attestation=attestation,
            min_attestation_len=MIN_ATTESTATION_LEN,
            command_hint='desloppify plan triage --confirm reflect --attestation "My strategy accounts for..."',
            validation_stage="reflect",
            validate_attestation_fn=validate_attestation,
            validation_kwargs={
                "dimensions": reflect_dims,
                "cluster_names": reflect_clusters,
            },
            log_action="triage_confirm_reflect",
            not_satisfied_hint="If not, refine your strategy before organizing.",
        ),
        services=resolved_services,
    ):
        return
    print_user_message(
        "Hey — reflect is confirmed. Now create clusters, enrich"
        " them with action steps, then run `desloppify plan triage"
        " --stage organize --report \"...\"`. No need to reply,"
        " just keep going."
    )


__all__ = ["MIN_ATTESTATION_LEN", "confirm_observe", "confirm_reflect", "validate_attestation"]
