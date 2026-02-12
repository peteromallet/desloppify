"""Computed narrative context for LLM coaching and terminal headlines.

Pure functions that derive structured observations from state data.
No print statements — returns dicts that flow into _write_query().
"""

from __future__ import annotations


# ── Detector → tool mapping ────────────────────────────────

DETECTOR_TOOLS = {
    # Detectors with auto-fixers (TypeScript only)
    "unused":  {"fixers": ["unused-imports", "unused-vars", "unused-params"],
                "action_type": "auto_fix"},
    "logs":    {"fixers": ["debug-logs"], "action_type": "auto_fix"},
    "exports": {"fixers": ["dead-exports"], "action_type": "auto_fix"},
    "smells":  {"fixers": ["dead-useeffect", "empty-if-chain"],
                "action_type": "auto_fix"},  # partial — only some smells
    # Detectors where `move` is the primary tool
    "orphaned":   {"fixers": [], "action_type": "reorganize",
                   "tool": "move", "guidance": "delete dead files or relocate with `desloppify move`"},
    "flat_dirs":  {"fixers": [], "action_type": "reorganize",
                   "tool": "move", "guidance": "create subdirectories and use `desloppify move`"},
    "naming":     {"fixers": [], "action_type": "reorganize",
                   "tool": "move", "guidance": "rename files with `desloppify move` to fix conventions"},
    "single_use": {"fixers": [], "action_type": "reorganize",
                   "tool": "move", "guidance": "inline or relocate with `desloppify move`"},
    "coupling":   {"fixers": [], "action_type": "reorganize",
                   "tool": "move", "guidance": "fix boundary violations with `desloppify move`"},
    "cycles":     {"fixers": [], "action_type": "reorganize",
                   "tool": "move", "guidance": "break cycles by extracting shared code or using `desloppify move`"},
    # Detectors requiring manual intervention
    "structural": {"fixers": [], "action_type": "refactor",
                   "guidance": "decompose large files — extract logic into focused modules"},
    "props":      {"fixers": [], "action_type": "refactor",
                   "guidance": "split bloated components, extract sub-components"},
    "deprecated": {"fixers": [], "action_type": "manual_fix",
                   "guidance": "remove deprecated symbols or migrate callers"},
    "react":      {"fixers": [], "action_type": "refactor",
                   "guidance": "refactor React antipatterns (state sync, useEffect misuse)"},
    "dupes":      {"fixers": [], "action_type": "refactor",
                   "guidance": "extract shared utility or consolidate duplicates"},
    "patterns":   {"fixers": [], "action_type": "refactor",
                   "guidance": "align to single pattern across the codebase"},
}

# Structural sub-detectors that merge under "structural" — shared constant
STRUCTURAL_MERGE = {"large", "complexity", "gods", "concerns"}


def _count_open_by_detector(findings: dict) -> dict[str, int]:
    """Count open findings by detector, merging structural sub-detectors."""
    by_det: dict[str, int] = {}
    for f in findings.values():
        if f["status"] != "open":
            continue
        det = f.get("detector", "unknown")
        if det in STRUCTURAL_MERGE:
            det = "structural"
        by_det[det] = by_det.get(det, 0) + 1
    return by_det


def compute_narrative(state: dict, *, diff: dict | None = None,
                      lang: str | None = None,
                      command: str | None = None) -> dict:
    """Compute structured narrative context from state data.

    Returns a dict with: phase, headline, dimensions, actions, tools, debt, milestone.

    Args:
        state: Current state dict.
        diff: Scan diff (only present after a scan).
        lang: Language name (e.g. "python", "typescript").
        command: The command that triggered this (e.g. "scan", "fix", "resolve").
    """
    raw_history = state.get("scan_history", [])
    # Filter history to current language to avoid mixing trajectories.
    # Include entries without a lang field (pre-date this feature) for backward compat.
    history = ([h for h in raw_history if h.get("lang") in (lang, None)]
               if lang else raw_history)
    dim_scores = state.get("dimension_scores", {})
    stats = state.get("stats", {})
    obj_strict = state.get("objective_strict")
    obj_score = state.get("objective_score")
    findings = state.get("findings", {})

    by_det = _count_open_by_detector(findings)
    badge = _compute_badge_status()

    phase = _detect_phase(history, obj_strict)
    dimensions = _analyze_dimensions(dim_scores, history, state)
    debt = _analyze_debt(dim_scores, findings, history)
    milestone = _detect_milestone(state, diff, history)
    actions = _compute_actions(by_det, dim_scores, state, debt, lang)
    tools = _compute_tools(by_det, lang, badge)
    headline = _compute_headline(phase, dimensions, debt, milestone, diff,
                                 obj_strict, obj_score, stats, history)
    reminders = _compute_reminders(state, lang, phase, debt, actions,
                                   dimensions, badge, command)

    return {
        "phase": phase,
        "headline": headline,
        "dimensions": dimensions,
        "actions": actions,
        "tools": tools,
        "debt": debt,
        "milestone": milestone,
        "reminders": reminders,
    }


# ── Phase detection ────────────────────────────────────────

def _detect_phase(history: list[dict], obj_strict: float | None) -> str:
    """Detect project phase from scan history trajectory."""
    if not history:
        return "first_scan"

    if len(history) == 1:
        return "first_scan"

    strict = obj_strict
    if strict is None and history:
        strict = history[-1].get("objective_strict")

    # Check regression: strict dropped from previous scan
    if len(history) >= 2:
        prev = history[-2].get("objective_strict")
        curr = history[-1].get("objective_strict")
        if prev is not None and curr is not None and curr < prev - 0.5:
            return "regression"

    # Check stagnation: strict unchanged ±0.5 for 3+ scans
    if len(history) >= 3:
        recent = [h.get("objective_strict") for h in history[-3:]]
        if all(r is not None for r in recent):
            spread = max(recent) - min(recent)
            if spread <= 0.5:
                return "stagnation"

    # Early momentum: scans 2-5 with score rising — check BEFORE score thresholds
    # so early projects get motivational framing even if score is already high
    if len(history) <= 5:
        if len(history) >= 2:
            first = history[0].get("objective_strict")
            last = history[-1].get("objective_strict")
            if first is not None and last is not None and last > first:
                return "early_momentum"
        return "early_momentum"

    if strict is not None:
        if strict > 93:
            return "maintenance"
        if strict > 80:
            return "refinement"

    return "middle_grind"


# ── Dimension analysis ─────────────────────────────────────

def _analyze_dimensions(dim_scores: dict, history: list[dict],
                        state: dict) -> dict:
    """Compute per-dimension structured analysis."""
    if not dim_scores:
        return {}

    from .scoring import merge_potentials, compute_score_impact

    potentials = merge_potentials(state.get("potentials", {}))

    # Lowest dimensions (by strict score)
    sorted_dims = sorted(
        ((name, ds) for name, ds in dim_scores.items() if ds.get("strict", ds["score"]) < 100),
        key=lambda x: x[1].get("strict", x[1]["score"]),
    )
    lowest = []
    for name, ds in sorted_dims[:3]:
        strict = ds.get("strict", ds["score"])
        issues = ds["issues"]
        # Estimate impact from the dominant detector
        impact = 0.0
        for det, det_data in ds.get("detectors", {}).items():
            if det_data.get("issues", 0) > 0:
                imp = compute_score_impact(
                    {k: {"score": v["score"], "tier": v.get("tier", 3),
                          "detectors": v.get("detectors", {})}
                     for k, v in dim_scores.items()},
                    potentials, det, det_data["issues"])
                impact = max(impact, imp)
        lowest.append({"name": name, "strict": round(strict, 1),
                        "issues": issues, "impact": round(impact, 1)})

    # Biggest gap dimensions (lenient - strict)
    biggest_gap = []
    for name, ds in dim_scores.items():
        lenient = ds["score"]
        strict = ds.get("strict", lenient)
        gap = lenient - strict
        if gap > 1.0:
            wontfix_count = sum(
                1 for f in state.get("findings", {}).values()
                if f["status"] == "wontfix" and _finding_in_dimension(f, name, dim_scores)
            )
            biggest_gap.append({"name": name, "lenient": round(lenient, 1),
                                "strict": round(strict, 1), "gap": round(gap, 1),
                                "wontfix_count": wontfix_count})
    biggest_gap.sort(key=lambda x: -x["gap"])

    # Stagnant dimensions (strict unchanged for 3+ scans)
    stagnant = []
    if len(history) >= 3:
        for name in dim_scores:
            scores = []
            for h in history[-5:]:
                hdim = (h.get("dimension_scores") or {}).get(name)
                if hdim:
                    scores.append(hdim.get("strict", hdim.get("score")))
            if len(scores) >= 3 and all(s is not None for s in scores):
                if max(scores) - min(scores) <= 0.5:
                    stagnant.append({"name": name,
                                     "strict": round(dim_scores[name].get("strict", dim_scores[name]["score"]), 1),
                                     "stuck_scans": len(scores)})

    return {
        "lowest_dimensions": lowest,
        "biggest_gap_dimensions": biggest_gap[:3],
        "stagnant_dimensions": stagnant,
    }


def _finding_in_dimension(finding: dict, dim_name: str, dim_scores: dict) -> bool:
    """Check if a finding's detector belongs to a dimension."""
    from .scoring import DIMENSIONS
    det = finding.get("detector", "")
    if det in STRUCTURAL_MERGE:
        det = "structural"
    for dim in DIMENSIONS:
        if dim.name == dim_name and det in dim.detectors:
            return True
    return False


# ── Debt analysis ──────────────────────────────────────────

def _analyze_debt(dim_scores: dict, findings: dict,
                  history: list[dict]) -> dict:
    """Compute wontfix debt analysis."""
    # Count wontfix
    wontfix_count = sum(1 for f in findings.values() if f["status"] == "wontfix")

    # Compute gap per dimension
    worst_dim = None
    worst_gap = 0.0
    overall_lenient = 0.0
    overall_strict = 0.0
    if dim_scores:
        from .scoring import TIER_WEIGHTS
        w_sum_l = 0.0
        w_sum_s = 0.0
        w_total = 0.0
        for name, ds in dim_scores.items():
            tier = ds.get("tier", 3)
            w = TIER_WEIGHTS.get(tier, 2)
            w_sum_l += ds["score"] * w
            w_sum_s += ds.get("strict", ds["score"]) * w
            w_total += w
            gap = ds["score"] - ds.get("strict", ds["score"])
            if gap > worst_gap:
                worst_gap = gap
                worst_dim = name
        if w_total > 0:
            overall_lenient = round(w_sum_l / w_total, 1)
            overall_strict = round(w_sum_s / w_total, 1)

    overall_gap = round(overall_lenient - overall_strict, 1)

    # Trend from history
    trend = "stable"
    if len(history) >= 3:
        gaps = []
        for h in history[-5:]:
            hs = h.get("objective_strict")
            hl = h.get("objective_score")
            if hs is not None and hl is not None:
                gaps.append(hl - hs)
        if len(gaps) >= 2:
            if gaps[-1] > gaps[0] + 0.5:
                trend = "growing"
            elif gaps[-1] < gaps[0] - 0.5:
                trend = "shrinking"

    return {
        "overall_gap": overall_gap,
        "wontfix_count": wontfix_count,
        "worst_dimension": worst_dim,
        "worst_gap": round(worst_gap, 1),
        "trend": trend,
    }


# ── Milestone detection ────────────────────────────────────

def _detect_milestone(state: dict, diff: dict | None,
                      history: list[dict]) -> str | None:
    """Detect notable milestones worth celebrating."""
    obj_strict = state.get("objective_strict")
    stats = state.get("stats", {})

    # Check T1 clear
    by_tier = stats.get("by_tier", {})
    t1_open = by_tier.get("1", {}).get("open", 0)
    t2_open = by_tier.get("2", {}).get("open", 0)

    if len(history) >= 2:
        prev_strict = history[-2].get("objective_strict")
        if prev_strict is not None and obj_strict is not None:
            # Crossed 90
            if prev_strict < 90 and obj_strict >= 90:
                return "Crossed 90% strict!"
            # Crossed 80
            if prev_strict < 80 and obj_strict >= 80:
                return "Crossed 80% strict!"

    if t1_open == 0 and t2_open == 0:
        # Check if there were T1/T2 items before
        total_t1 = sum(by_tier.get("1", {}).values())
        total_t2 = sum(by_tier.get("2", {}).values())
        if total_t1 + total_t2 > 0:
            return "All T1 and T2 items cleared!"

    if t1_open == 0:
        total_t1 = sum(by_tier.get("1", {}).values())
        if total_t1 > 0:
            return "All T1 items cleared!"

    if stats.get("open", 0) == 0 and stats.get("total", 0) > 0:
        return "Zero open findings!"

    return None


# ── Recommended actions ────────────────────────────────────

def _compute_actions(by_det: dict[str, int], dim_scores: dict, state: dict,
                     debt: dict, lang: str | None) -> list[dict]:
    """Compute prioritized action list with tool mapping."""
    from .scoring import merge_potentials, compute_score_impact, get_dimension_for_detector

    potentials = merge_potentials(state.get("potentials", {}))
    actions = []
    priority = 0

    def _impact_for(det: str, count: int) -> float:
        if not potentials or not dim_scores:
            return 0.0
        return compute_score_impact(
            {k: {"score": v["score"], "tier": v.get("tier", 3),
                  "detectors": v.get("detectors", {})}
             for k, v in dim_scores.items()},
            potentials, det, count)

    def _dim_name_for(det: str) -> str:
        dim = get_dimension_for_detector(det)
        return dim.name if dim else "Unknown"

    # Auto-fixable actions (or manual-fix for Python)
    for det, tool_info in DETECTOR_TOOLS.items():
        if tool_info["action_type"] != "auto_fix":
            continue
        count = by_det.get(det, 0)
        if count == 0:
            continue

        impact = _impact_for(det, count)

        # Python has no auto-fixers — suggest manual fix instead
        if lang == "python":
            priority += 1
            actions.append({
                "priority": priority,
                "type": "manual_fix",
                "count": count,
                "description": f"{count} {det} findings — fix manually",
                "command": f"desloppify show {det} --status open",
                "impact": round(impact, 1),
                "dimension": _dim_name_for(det),
            })
            continue

        for fixer in tool_info["fixers"]:
            priority += 1
            actions.append({
                "priority": priority,
                "type": "auto_fix",
                "count": count,
                "description": f"{count} {det} findings — auto-fixable",
                "command": f"desloppify fix {fixer} --dry-run",
                "impact": round(impact, 1),
                "dimension": _dim_name_for(det),
            })
            break  # One action per detector, listing first fixer

    # Reorganize actions
    for det, tool_info in DETECTOR_TOOLS.items():
        if tool_info["action_type"] != "reorganize":
            continue
        count = by_det.get(det, 0)
        if count == 0:
            continue

        impact = _impact_for(det, count)
        priority += 1
        actions.append({
            "priority": priority,
            "type": "reorganize",
            "count": count,
            "description": f"{count} {det} findings — restructure with move",
            "command": f"desloppify show {det} --status open",
            "tool_hint": tool_info.get("guidance", ""),
            "impact": round(impact, 1),
            "dimension": _dim_name_for(det),
        })

    # Refactor actions
    for det, tool_info in DETECTOR_TOOLS.items():
        if tool_info["action_type"] not in ("refactor", "manual_fix"):
            continue
        count = by_det.get(det, 0)
        if count == 0:
            continue

        impact = _impact_for(det, count)
        priority += 1
        actions.append({
            "priority": priority,
            "type": tool_info["action_type"],
            "count": count,
            "description": f"{count} {det} findings — {tool_info.get('guidance', 'manual fix')}",
            "command": f"desloppify show {det} --status open",
            "impact": round(impact, 1),
            "dimension": _dim_name_for(det),
        })

    # Debt review action
    if debt.get("overall_gap", 0) > 2.0:
        priority += 1
        actions.append({
            "priority": priority,
            "type": "debt_review",
            "description": f"{debt['overall_gap']} pts of wontfix debt — review stale decisions",
            "command": "desloppify show --status wontfix",
            "gap": debt["overall_gap"],
        })

    # Sort by impact descending, auto_fix first
    type_order = {"auto_fix": 0, "reorganize": 1, "refactor": 2, "manual_fix": 3, "debt_review": 4}
    actions.sort(key=lambda a: (type_order.get(a["type"], 9), -a.get("impact", 0)))
    for i, a in enumerate(actions):
        a["priority"] = i + 1

    return actions


# ── Tool inventory ─────────────────────────────────────────

def _compute_tools(by_det: dict[str, int], lang: str | None,
                   badge: dict) -> dict:
    """Compute available tools inventory for the current context."""
    # Available fixers (only those with >0 open findings)
    fixers = []
    if lang != "python":
        for det, tool_info in DETECTOR_TOOLS.items():
            if tool_info["action_type"] != "auto_fix":
                continue
            count = by_det.get(det, 0)
            if count == 0:
                continue
            for fixer in tool_info["fixers"]:
                fixers.append({
                    "name": fixer,
                    "detector": det,
                    "open_count": count,
                    "command": f"desloppify fix {fixer} --dry-run",
                })

    # Move tool relevance
    org_issues = sum(by_det.get(d, 0) for d in
                     ["orphaned", "flat_dirs", "naming", "single_use", "coupling", "cycles"])
    move_reasons = []
    if by_det.get("orphaned", 0):
        move_reasons.append(f"{by_det['orphaned']} orphaned files")
    if by_det.get("coupling", 0):
        move_reasons.append(f"{by_det['coupling']} coupling violations")
    if by_det.get("single_use", 0):
        move_reasons.append(f"{by_det['single_use']} single-use files")
    if by_det.get("flat_dirs", 0):
        move_reasons.append(f"{by_det['flat_dirs']} flat directories")
    if by_det.get("naming", 0):
        move_reasons.append(f"{by_det['naming']} naming issues")

    return {
        "fixers": fixers,
        "move": {
            "available": True,
            "relevant": org_issues > 0,
            "reason": " + ".join(move_reasons) if move_reasons else None,
            "usage": "desloppify move <source> <dest> [--dry-run]",
        },
        "plan": {
            "command": "desloppify plan",
            "description": "Generate prioritized markdown cleanup plan",
        },
        "badge": badge,
    }


# ── Headline computation ──────────────────────────────────

def _compute_headline(phase: str, dimensions: dict, debt: dict,
                      milestone: str | None, diff: dict | None,
                      obj_strict: float | None, obj_score: float | None,
                      stats: dict, history: list[dict]) -> str | None:
    """Compute one computed sentence for terminal display."""
    # Milestone takes priority
    if milestone:
        return milestone

    # First scan framing
    if phase == "first_scan":
        dims = len(dimensions.get("lowest_dimensions", [])) if dimensions else 0
        open_count = stats.get("open", 0)
        if dims:
            return f"First scan complete. {open_count} open findings across {dims} dimensions."
        return f"First scan complete. {open_count} findings detected."

    # Regression — acknowledge that drops after fixes are normal
    if phase == "regression" and len(history) >= 2:
        prev = history[-2].get("objective_strict")
        curr = history[-1].get("objective_strict")
        if prev is not None and curr is not None:
            drop = round(prev - curr, 1)
            return (f"Score shifted {drop} pts — this is normal after structural changes. "
                    f"Rescan after your next fix to see the real trend.")

    # Stagnation — suggest which dimension to focus on
    if phase == "stagnation":
        if obj_strict is not None:
            stuck_scans = min(len(history), 5)
            wontfix = debt.get("wontfix_count", 0)
            # Point to the specific dimension dragging things down
            lowest_dims = dimensions.get("lowest_dimensions", [])
            if lowest_dims:
                dim = lowest_dims[0]
                if wontfix > 0:
                    return (f"Score plateaued at {obj_strict:.1f} for {stuck_scans} scans. "
                            f"{dim['name']} ({dim['strict']}%) is where the breakthrough is. "
                            f"{wontfix} wontfix items may also be worth revisiting.")
                return (f"Score plateaued at {obj_strict:.1f} for {stuck_scans} scans. "
                        f"{dim['name']} ({dim['strict']}%) is where the breakthrough is.")
            if wontfix > 0:
                return (f"Score plateaued at {obj_strict:.1f} for {stuck_scans} scans. "
                        f"{wontfix} wontfix items — revisit?")
            return (f"Score plateaued at {obj_strict:.1f} for {stuck_scans} scans. "
                    f"Try tackling a different dimension.")

    # Leverage point (lowest dimension with biggest impact)
    lowest = dimensions.get("lowest_dimensions", [])
    if lowest and lowest[0].get("impact", 0) > 0:
        top = lowest[0]
        return (f"{top['name']} is your biggest lever: "
                f"{top['issues']} items → +{top['impact']} pts")

    # Gap callout
    if debt.get("overall_gap", 0) > 5.0:
        gap = debt["overall_gap"]
        worst = debt.get("worst_dimension", "")
        if obj_strict is not None and obj_score is not None:
            return (f"Strict {obj_strict:.1f} vs lenient {obj_score:.1f} — "
                    f"{gap} pts of wontfix debt, mostly in {worst}")

    # Maintenance phase
    if phase == "maintenance":
        return f"Health {obj_strict:.1f}/100 — maintenance mode. Watch for regressions."

    # Middle grind fallback — point toward next item
    if phase == "middle_grind":
        open_count = stats.get("open", 0)
        if lowest:
            top = lowest[0]
            return (f"{open_count} findings open. {top['name']} ({top['strict']}%) "
                    f"needs attention — run `desloppify next` to start.")
        if open_count > 0:
            return f"{open_count} findings open. Run `desloppify next` for the highest-priority item."

    # Early momentum fallback — celebrate trajectory
    if phase == "early_momentum" and obj_strict is not None:
        open_count = stats.get("open", 0)
        return f"Score {obj_strict:.1f}/100 with {open_count} findings open. Keep the momentum going."

    return None


# ── Badge / scorecard status ──────────────────────────────

def _compute_badge_status() -> dict:
    """Check if scorecard.png exists and whether README references it."""
    from .utils import PROJECT_ROOT

    scorecard_path = PROJECT_ROOT / "scorecard.png"
    generated = scorecard_path.exists()

    in_readme = False
    if generated:
        for readme_name in ("README.md", "readme.md", "README.MD"):
            readme_path = PROJECT_ROOT / readme_name
            if readme_path.exists():
                try:
                    in_readme = "scorecard.png" in readme_path.read_text()
                except OSError:
                    pass
                break

    recommendation = None
    if generated and not in_readme:
        recommendation = 'Add to README: <img src="scorecard.png" width="400">'

    return {
        "generated": generated,
        "in_readme": in_readme,
        "path": "scorecard.png",
        "recommendation": recommendation,
    }


# ── FP rate tracking ──────────────────────────────────────

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


# ── Contextual reminders ─────────────────────────────────

_REMINDER_DECAY_THRESHOLD = 3  # Suppress after this many occurrences


def _compute_reminders(state: dict, lang: str | None,
                       phase: str, debt: dict, actions: list[dict],
                       dimensions: dict, badge: dict,
                       command: str | None) -> list[dict]:
    """Compute context-specific reminders, suppressing those shown too many times."""
    reminders = []
    obj_strict = state.get("objective_strict")
    reminder_history = state.get("reminder_history", {})

    # 1. Auto-fixers available
    if lang != "python":
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
    if obj_strict is not None and obj_strict >= 90:
        if badge.get("generated") and not badge.get("in_readme"):
            reminders.append({
                "type": "badge_recommendation",
                "message": ('Score is above 90! Add the scorecard to your README: '
                            '<img src="scorecard.png" width="400">'),
                "command": None,
            })

    # 4. Wontfix debt growing
    if debt.get("trend") == "growing":
        reminders.append({
            "type": "wontfix_growing",
            "message": "Wontfix debt is growing. Review stale decisions: `desloppify show --status wontfix`.",
            "command": "desloppify show --status wontfix",
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
    fp_rates = _compute_fp_rates(state.get("findings", {}))
    for (detector, zone), rate in fp_rates.items():
        if rate > 0.3:
            pct = round(rate * 100)
            reminders.append({
                "type": f"fp_calibration_{detector}_{zone}",
                "message": (f"{pct}% of {detector} findings in {zone} zone are false positives. "
                            f"Consider reviewing detection rules for {zone} files."),
                "command": None,
            })

    # Apply decay: suppress reminders shown >= threshold times
    filtered = []
    for r in reminders:
        count = reminder_history.get(r["type"], 0)
        if count < _REMINDER_DECAY_THRESHOLD:
            filtered.append(r)

    # Update reminder history in state (counts will persist across commands)
    for r in filtered:
        reminder_history[r["type"]] = reminder_history.get(r["type"], 0) + 1
    state["reminder_history"] = reminder_history

    return filtered
