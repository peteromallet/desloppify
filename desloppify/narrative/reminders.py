"""Contextual reminders with decay."""

from __future__ import annotations

from ._constants import STRUCTURAL_MERGE, _FEEDBACK_URL, _REMINDER_DECAY_THRESHOLD


def _compute_fp_rates(findings: dict) -> dict[tuple[str, str], float]:
    """Compute false_positive rate per (detector, zone) from historical findings.

    Returns rates only for combinations with >= 5 total findings and FP rate > 0.
    """
    counts: dict[tuple[str, str], dict[str, int]] = {}
    for f in findings.values():
        det = f.get("detector", "unknown")
        if det in STRUCTURAL_MERGE:
            det = "structural"
        zone = f.get("zone", "production")
        key = (det, zone)
        if key not in counts:
            counts[key] = {"total": 0, "fp": 0}
        counts[key]["total"] += 1
        if f.get("status") == "false_positive":
            counts[key]["fp"] += 1

    rates = {}
    for key, c in counts.items():
        if c["total"] >= 5 and c["fp"] > 0:
            rates[key] = c["fp"] / c["total"]
    return rates


def _compute_reminders(state: dict, lang: str | None,
                       phase: str, debt: dict, actions: list[dict],
                       dimensions: dict, badge: dict,
                       command: str | None,
                       config: dict | None = None) -> tuple[list[dict], dict]:
    """Compute context-specific reminders, suppressing those shown too many times."""
    reminders = []
    from ..state import get_strict_score
    strict_score = get_strict_score(state)
    reminder_history = state.get("reminder_history", {})

    # 1. Auto-fixers available
    auto_fix_actions = [a for a in actions if a.get("type") == "auto_fix"]
    if auto_fix_actions:
        total = sum(a.get("count", 0) for a in auto_fix_actions)
        if total > 0:
            first_cmd = auto_fix_actions[0].get("command", "desloppify fix <fixer> --dry-run")
            reminders.append({
                "type": "auto_fixers_available",
                "message": f"{total} findings are auto-fixable. Run `{first_cmd}`.",
                "command": first_cmd,
            })

    # 2. Rescan needed — only after fix or resolve, not passive queries
    if command in ("fix", "resolve", "ignore"):
        reminders.append({
            "type": "rescan_needed",
            "message": "Rescan to verify — cascading effects may create new findings.",
            "command": "desloppify scan",
        })

    # 3. Badge recommendation (strict >= 90 and README doesn't have it)
    if strict_score is not None and strict_score >= 90:
        if badge.get("generated") and not badge.get("in_readme"):
            reminders.append({
                "type": "badge_recommendation",
                "message": ('Score is above 90! Add the scorecard to your README: '
                            '<img src="scorecard.png" width="100%">'),
                "command": None,
            })

    # 4. Wontfix debt growing
    if debt.get("trend") == "growing":
        reminders.append({
            "type": "wontfix_growing",
            "message": "Wontfix debt is growing. Review stale decisions: `desloppify show --status wontfix`.",
            "command": "desloppify show --status wontfix",
        })

    # 4b. Stale wontfix decay — resurface items wontfixed long ago
    scan_count = len(state.get("scan_history", []))
    _WONTFIX_DECAY_SCANS = 20  # resurface after this many scans
    if scan_count >= _WONTFIX_DECAY_SCANS and command == "scan":
        from datetime import datetime as _dt, timezone as _tz
        findings = state.get("findings", {})
        stale_wontfix = []
        for f in findings.values():
            if f.get("status") != "wontfix":
                continue
            resolved_at = f.get("resolved_at")
            if not resolved_at:
                continue
            # Check scan_count at time of wontfix vs now
            # We can't track the exact scan count at wontfix time,
            # so use time-based staleness: >60 days old
            try:
                resolved_dt = _dt.fromisoformat(resolved_at)
                age_days = (_dt.now(_tz.utc) - resolved_dt).days
                if age_days > 60:
                    stale_wontfix.append(f)
            except (ValueError, TypeError):
                continue
        if stale_wontfix:
            reminders.append({
                "type": "wontfix_stale",
                "message": (f"{len(stale_wontfix)} wontfix item(s) are >60 days old. "
                            f"Has anything changed? Review with: "
                            f"`desloppify show \"*\" --status wontfix`"),
                "command": "desloppify show \"*\" --status wontfix",
            })

    # 5. Stagnant dimensions — be specific about what to try
    for dim in dimensions.get("stagnant_dimensions", []):
        strict = dim.get("strict", 0)
        if strict >= 99:
            msg = (f"{dim['name']} has been at {strict}% for {dim['stuck_scans']} scans. "
                   f"The remaining items may be worth marking as wontfix if they're intentional.")
        else:
            msg = (f"{dim['name']} has been stuck at {strict}% for {dim['stuck_scans']} scans. "
                   f"Try tackling it from a different angle — run `desloppify next` to find the right entry point.")
        reminders.append({
            "type": "stagnant_nudge",
            "message": msg,
            "command": None,
        })

    # 6. Dry-run first (when top action is auto_fix)
    if actions and actions[0].get("type") == "auto_fix":
        reminders.append({
            "type": "dry_run_first",
            "message": "Always --dry-run first, review changes, then apply.",
            "command": None,
        })

    # 7. Zone classification awareness (reminder decay handles repetition)
    zone_dist = state.get("zone_distribution")
    if zone_dist:
        non_prod = sum(v for k, v in zone_dist.items() if k != "production")
        if non_prod > 0:
            total = sum(zone_dist.values())
            parts = [f"{v} {k}" for k, v in sorted(zone_dist.items())
                     if k != "production" and v > 0]
            reminders.append({
                "type": "zone_classification",
                "message": (f"{non_prod} of {total} files classified as non-production "
                            f"({', '.join(parts)}). "
                            f"Override with `desloppify zone set <file> production` "
                            f"if any are misclassified."),
                "command": "desloppify zone show",
            })

    # 8. Zone-aware FP rate calibration reminders
    from ..state import path_scoped_findings
    fp_rates = _compute_fp_rates(path_scoped_findings(state.get("findings", {}), state.get("scan_path")))
    for (detector, zone), rate in fp_rates.items():
        if rate > 0.3:
            pct = round(rate * 100)
            reminders.append({
                "type": f"fp_calibration_{detector}_{zone}",
                "message": (f"{pct}% of {detector} findings in {zone} zone are false positives. "
                            f"Consider reviewing detection rules for {zone} files."),
                "command": None,
            })

    # 9a. Review findings pending — uninvestigated review findings need attention
    open_review = [f for f in path_scoped_findings(state.get("findings", {}), state.get("scan_path")).values()
                   if f.get("status") == "open" and f.get("detector") == "review"]
    if open_review:
        uninvestigated = [f for f in open_review
                          if not f.get("detail", {}).get("investigation")]
        if uninvestigated:
            reminders.append({
                "type": "review_findings_pending",
                "message": f"{len(uninvestigated)} review finding(s) need investigation. "
                           f"Run `desloppify issues` to see the work queue.",
                "command": "desloppify issues",
            })

    # 9b. Re-review needed after resolve when assessments exist
    if command == "resolve" and (state.get("subjective_assessments") or state.get("review_assessments")):
        reminders.append({
            "type": "rereview_needed",
            "message": "Score is driven by assessments \u2014 re-run "
                       "`desloppify review --prepare` after fixing to update scores.",
            "command": "desloppify review --prepare",
        })

    # 9. Review not run — nudge when mechanical score is high but no review exists
    review_cache = state.get("review_cache", {})
    if not review_cache.get("files"):
        current_strict = get_strict_score(state) or 0
        if current_strict >= 80:
            reminders.append({
                "type": "review_not_run",
                "message": ("Mechanical checks look good! Run a subjective design review "
                            "to catch issues linters miss: desloppify review --prepare"),
                "command": "desloppify review --prepare",
            })

    # 10. Review staleness — nudge when oldest review is past max age
    review_max_age = (config or {}).get("review_max_age_days", 30)
    if review_max_age > 0 and review_cache.get("files"):
        from datetime import datetime as _dt, timezone as _tz
        try:
            oldest_str = min(
                f["reviewed_at"] for f in review_cache["files"].values()
                if f.get("reviewed_at")
            )
            oldest = _dt.fromisoformat(oldest_str)
            age_days = (_dt.now(_tz.utc) - oldest).days
            if age_days > review_max_age:
                reminders.append({
                    "type": "review_stale",
                    "message": (f"Design review is {age_days} days old \u2014 "
                                f"run: desloppify review --prepare"),
                    "command": "desloppify review --prepare",
                })
        except (ValueError, TypeError):
            pass  # Malformed dates — skip

    # 11. Feedback nudge — encourage filing issues for tool improvement
    #    Scan-only so the 3 decay slots are spread across scan cycles, not
    #    burned in a single scan→show→fix session.  All variants share one
    #    decay key ("feedback_nudge") so the total is 3, not 3 per variant.
    scan_count = len(state.get("scan_history", []))
    if scan_count >= 2 and command == "scan":
        high_fp_dets = [det for (det, _zone), rate in fp_rates.items() if rate > 0.3]
        if high_fp_dets:
            nudge_msg = (
                f"Some detectors have high false-positive rates ({', '.join(high_fp_dets)}). "
                f"If patterns are being misclassified, file an issue at "
                f"{_FEEDBACK_URL} with the file and expected behavior — "
                f"it helps calibrate detection for everyone.")
        elif phase == "stagnation":
            nudge_msg = (
                f"Score has plateaued — if you suspect desloppify is missing patterns "
                f"or not capturing something it should, file an issue at "
                f"{_FEEDBACK_URL} describing what you expected. "
                f"Gaps in detection are a common cause of stagnation.")
        else:
            nudge_msg = (
                f"If you notice patterns desloppify doesn't detect, false positives, "
                f"or findings that seem off, file an issue at {_FEEDBACK_URL} — "
                f"include the file and what you expected. It helps improve the tool.")
        reminders.append({
            "type": "feedback_nudge",
            "message": nudge_msg,
            "command": None,
        })

    # Always remind agents to report scores (no decay — this is core)
    if command == "scan":
        reminders.insert(0, {
            "type": "report_scores",
            "message": ("ALWAYS share ALL scores with the user: overall, objective, and strict, "
                        "plus every dimension score (lenient + strict), including subjective dimensions. "
                        "The goal is to maximize strict scores."),
            "command": None,
            "no_decay": True,
        })

    # Apply decay: suppress reminders shown >= threshold times
    filtered = []
    for r in reminders:
        if r.get("no_decay"):
            filtered.append(r)
            continue
        count = reminder_history.get(r["type"], 0)
        if count < _REMINDER_DECAY_THRESHOLD:
            filtered.append(r)

    # Compute updated reminder history (returned via narrative result, not mutated here)
    updated_history = dict(reminder_history)
    for r in filtered:
        updated_history[r["type"]] = updated_history.get(r["type"], 0) + 1

    return filtered, updated_history
