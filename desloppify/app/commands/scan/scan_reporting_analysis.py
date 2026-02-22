"""Post-scan narrative and integrity reporting."""

from __future__ import annotations

from desloppify import state as state_mod
from desloppify.app.commands.helpers.rendering import print_ranked_actions
from desloppify.intelligence import narrative as narrative_mod
from desloppify.intelligence import integrity as subjective_integrity_mod
from desloppify.utils import colorize


def _subjective_dimensions_below_threshold(
    state: dict, *, threshold: float = 90.0
) -> list[str]:
    """Return subjective dimensions with score below threshold and evidence issues."""
    low_dims: list[str] = []
    dimension_scores = state.get("dimension_scores", {})
    if not isinstance(dimension_scores, dict):
        return low_dims

    for dim_name, payload in dimension_scores.items():
        if not isinstance(payload, dict):
            continue
        score = payload.get("score")
        detectors = payload.get("detectors", {})
        subjective_payload = (
            detectors.get("subjective_assessment")
            if isinstance(detectors, dict)
            else None
        )
        if not isinstance(subjective_payload, dict):
            continue
        issues = subjective_payload.get("issues", 0)
        if not isinstance(score, int | float) or not isinstance(
            issues, int | float
        ):
            continue
        if score < threshold and issues > 0:
            low_dims.append(str(dim_name))
    return low_dims


def _print_narrative_plan_fields(narrative: dict) -> None:
    """Print additional narrative plan fields when present."""
    why_now = narrative.get("why_now")
    primary_action = narrative.get("primary_action")
    verification_step = narrative.get("verification_step")
    risk_flags = narrative.get("risk_flags")

    has_plan = bool(why_now) or bool(primary_action) or bool(verification_step) or bool(
        risk_flags
    )
    if not has_plan:
        return

    print(colorize("  Narrative Plan:", "cyan"))
    if isinstance(why_now, str) and why_now.strip():
        print(colorize(f"    Why now: {why_now.strip()}", "dim"))

    if isinstance(primary_action, dict):
        command = primary_action.get("command")
        description = primary_action.get("description")
        if isinstance(command, str) and command.strip():
            line = f"    Next: `{command.strip()}`"
            if isinstance(description, str) and description.strip():
                line += f" — {description.strip()}"
            print(colorize(line, "dim"))

    if isinstance(verification_step, dict):
        command = verification_step.get("command")
        reason = verification_step.get("reason")
        if isinstance(command, str) and command.strip():
            line = f"    Verify: `{command.strip()}`"
            if isinstance(reason, str) and reason.strip():
                line += f" — {reason.strip()}"
            print(colorize(line, "dim"))

    if isinstance(risk_flags, list):
        for risk in risk_flags:
            if not isinstance(risk, dict):
                continue
            message = risk.get("message")
            if not isinstance(message, str) or not message.strip():
                continue
            severity = str(risk.get("severity", "")).lower()
            style = "yellow" if severity in {"high", "critical"} else "dim"
            print(colorize(f"    Risk: {message.strip()}", style))
    print()


def _print_filtered_reminders(narrative: dict) -> None:
    """Print narrative reminders except low-value report score reminders."""
    reminders = narrative.get("reminders")
    if not isinstance(reminders, list):
        return
    messages: list[str] = []
    for reminder in reminders:
        if not isinstance(reminder, dict):
            continue
        if reminder.get("type") == "report_scores":
            continue
        message = reminder.get("message")
        if isinstance(message, str) and message.strip():
            messages.append(message.strip())
    if not messages:
        return

    print(colorize("  Reminders:", "dim"))
    for message in messages:
        print(colorize(f"    - {message}", "dim"))
    print()


def _show_subjective_score_nudge(state: dict) -> None:
    """Nudge rerun when subjective dimensions are low with evidence issues."""
    low_dims = _subjective_dimensions_below_threshold(state, threshold=90.0)
    if not low_dims:
        return

    review_cache = state.get("review_cache", {})
    reviewed_files = review_cache.get("files", {}) if isinstance(review_cache, dict) else {}
    verb = "rerun" if isinstance(reviewed_files, dict) and reviewed_files else "run"

    dim_preview = ", ".join(low_dims[:3])
    if len(low_dims) > 3:
        dim_preview += f", +{len(low_dims) - 3} more"

    print(colorize(f"  Subjective scores below 90: {dim_preview}", "yellow"))
    print(
        colorize(
            f"  You can {verb} the subjective scoring with `desloppify review --prepare`.",
            "cyan",
        )
    )
    print(
        colorize(
            "  Then review progress in `desloppify status` and investigate blockers via `desloppify issues`.",
            "dim",
        )
    )
    print()


def show_post_scan_analysis(
    diff: dict,
    state: dict,
    lang,
    *,
    target_strict_score: float = 95.0,
) -> tuple[list[str], dict]:
    """Print warnings, narrative headline, and top action. Returns (warnings, narrative)."""
    warnings = []
    if diff["reopened"] > 5:
        warnings.append(
            f"{diff['reopened']} findings reopened — was a previous fix reverted? Check: git log --oneline -5"
        )
    if diff["new"] > 10 and diff["auto_resolved"] < 3:
        warnings.append(
            f"{diff['new']} new findings with few resolutions — likely cascading from recent fixes. Run fixers again."
        )
    chronic = diff.get("chronic_reopeners", [])
    chronic_count = len(chronic) if isinstance(chronic, list) else chronic
    if chronic_count > 0:
        warnings.append(
            f"⟳ {chronic_count} chronic reopener{'s' if chronic_count != 1 else ''} "
            "(reopened 2+ times). These keep bouncing — fix properly or wontfix. "
            "Run: `desloppify show --chronic` to see them."
        )

    if warnings:
        for warning in warnings:
            print(colorize(f"  {warning}", "yellow"))
        print()

    # Computed narrative: headline + top action as terminal suggestion
    lang_name = lang.name if lang else None
    narrative = narrative_mod.compute_narrative(
        state,
        context=narrative_mod.NarrativeContext(
            diff=diff,
            lang=lang_name,
            command="scan",
        ),
    )

    # Show one actionable plan and optional strategy context.
    print(
        colorize(
            "  AGENT PLAN (use `desloppify next --count 20` to inspect more items):",
            "yellow",
        )
    )
    strategy = narrative.get("strategy") or {}
    hint = strategy.get("hint")
    actions = narrative.get("actions", [])

    if actions:
        top = actions[0]
        print(
            colorize(
                f"  Agent focus: `{top['command']}` — {top['description']}", "cyan"
            )
        )
        if hint:
            print(colorize(f"  Strategy: {hint}", "dim"))
        print()
    elif hint:
        print(colorize(f"  Agent focus: {hint}", "cyan"))
        print()

    if print_ranked_actions(actions):
        print()

    if narrative.get("headline"):
        print(colorize(f"  → {narrative['headline']}", "cyan"))
        print()

    _print_narrative_plan_fields(narrative)
    _print_filtered_reminders(narrative)
    _show_subjective_score_nudge(state)

    # Review findings nudge
    scoped_findings = state_mod.path_scoped_findings(
        state.get("findings", {}), state.get("scan_path")
    )
    open_review = [
        finding
        for finding in scoped_findings.values()
        if finding["status"] == "open" and finding.get("detector") == "review"
    ]
    open_subjective, _subjective_reasons, holistic_reasons = (
        subjective_integrity_mod.subjective_review_open_breakdown(scoped_findings)
    )
    holistic_open = sum(holistic_reasons.values())
    if open_review:
        suffix = "s" if len(open_review) != 1 else ""
        print(
            colorize(
                f"  Review: {len(open_review)} finding{suffix} pending — `desloppify issues`",
                "cyan",
            )
        )
        print()
    if open_subjective > 0:
        if holistic_open > 0:
            print(
                colorize(
                    f"  Subjective integrity: {holistic_open} holistic stale/missing signal(s) — "
                    "`desloppify review --prepare`",
                    "yellow",
                )
            )
        else:
            print(
                colorize(
                    f"  Subjective coverage: {open_subjective} file-level review signal(s) open — "
                    "`desloppify show subjective_review --status open`",
                    "cyan",
                )
            )
        print()

    # Auto-queue: nudge subjective review for high-complexity unreviewed files
    review_cache = state.get("review_cache", {}).get("files", {})
    scoped = scoped_findings
    complex_unreviewed = set()
    for finding in scoped.values():
        if (
            finding.get("detector") in ("structural", "smells")
            and finding.get("status") == "wontfix"
            and finding.get("file") not in review_cache
        ):
            complex_unreviewed.add(finding.get("file"))
    if len(complex_unreviewed) >= 3:
        print(
            colorize(
                f"  {len(complex_unreviewed)} complex files have never been reviewed — "
                "`desloppify review --prepare` would provide actionable refactoring guidance",
                "dim",
            )
        )
        print()

    return warnings, narrative


def show_score_integrity(state: dict, diff: dict):
    """Show Score Integrity section — surfaces wontfix debt and ignored findings."""
    stats = state.get("stats", {})
    wontfix = stats.get("wontfix", 0)
    ignored = diff.get("ignored", 0)
    ignore_patterns = diff.get("ignore_patterns", 0)

    if wontfix <= 5 and ignored <= 0 and ignore_patterns <= 0:
        return

    overall = state_mod.get_overall_score(state)
    strict = state_mod.get_strict_score(state)
    strict_gap = (
        round(overall - strict, 1) if overall is not None and strict is not None else 0
    )

    # Wontfix % of actionable findings (open + wontfix + fixed + auto_resolved + false_positive)
    actionable = (
        stats.get("open", 0)
        + wontfix
        + stats.get("fixed", 0)
        + stats.get("auto_resolved", 0)
        + stats.get("false_positive", 0)
    )
    wontfix_pct = round(wontfix / actionable * 100) if actionable else 0

    print(colorize("  " + "┄" * 2 + " Score Integrity " + "┄" * 37, "dim"))

    if wontfix > 5:
        if wontfix_pct > 50:
            style = "red"
            msg = (
                f"  ❌ {wontfix} wontfix ({wontfix_pct}%) — over half of findings swept under rug. "
                f"Strict gap: {strict_gap} pts"
            )
        elif wontfix_pct > 25:
            style = "yellow"
            msg = (
                f"  ⚠ {wontfix} wontfix ({wontfix_pct}%) — review whether past "
                "wontfix decisions still hold"
            )
        elif wontfix_pct > 10:
            style = "yellow"
            msg = (
                f"  ⚠ {wontfix} wontfix findings ({wontfix_pct}%) — strict {strict_gap} "
                "pts below lenient"
            )
        else:
            style = "dim"
            msg = f"  {wontfix} wontfix — strict gap: {strict_gap} pts"
        print(colorize(msg, style))

        # Show top 2 dimensions with biggest strict gap
        dim_scores = state.get("dimension_scores", {})
        if dim_scores:
            gaps = []
            for name, data in dim_scores.items():
                score = data.get("score", 100)
                strict_value = data.get("strict", score)
                gap = round(score - strict_value, 1)
                if gap > 0:
                    gaps.append((name, gap))
            gaps.sort(key=lambda x: -x[1])
            if gaps:
                top = gaps[:2]
                gap_str = ", ".join(f"{name} (−{gap} pts)" for name, gap in top)
                print(colorize(f"    Biggest gaps: {gap_str}", "dim"))

    if ignored > 0:
        style = "red" if ignore_patterns > 5 or ignored > 100 else "yellow"
        print(
            colorize(
                f"  ⚠ {ignore_patterns} ignore pattern{'s' if ignore_patterns != 1 else ''} "
                f"suppressed {ignored} finding{'s' if ignored != 1 else ''} this scan",
                style,
            )
        )
        print(
            colorize(
                "    Suppressed findings still count against strict and verified scores",
                "dim",
            )
        )
    elif ignore_patterns > 0:
        print(
            colorize(
                f"  {ignore_patterns} ignore pattern{'s' if ignore_patterns != 1 else ''} "
                "active (0 findings suppressed this scan)",
                "dim",
            )
        )

    print(colorize("  " + "┄" * 55, "dim"))
    print()


__all__ = ["show_post_scan_analysis", "show_score_integrity"]
