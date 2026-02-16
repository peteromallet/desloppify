"""Execution strategy: lanes, leverage, and parallelization."""

from __future__ import annotations

from ._constants import STRUCTURAL_MERGE, _DETECTOR_CASCADE


def _open_files_by_detector(findings: dict) -> dict[str, set[str]]:
    """Collect file sets of open findings by detector, merging structural sub-detectors."""
    by_det: dict[str, set[str]] = {}
    for f in findings.values():
        if f["status"] != "open":
            continue
        det = f.get("detector", "unknown")
        if det in STRUCTURAL_MERGE:
            det = "structural"
        filepath = f.get("file", "")
        if det not in by_det:
            by_det[det] = set()
        if filepath:
            by_det[det].add(filepath)
    return by_det


def _compute_fixer_leverage(by_det: dict[str, int], actions: list[dict],
                            phase: str, lang: str | None) -> dict:
    """Estimate how much value automated fixers would deliver.

    Returns a dict with auto_fixable_count, total_count, coverage, impact_ratio,
    and a recommendation string ("strong" | "moderate" | "none").
    """
    auto_fixable = sum(a.get("count", 0) for a in actions if a.get("type") == "auto_fix")
    total = sum(by_det.values())
    coverage = auto_fixable / total if total > 0 else 0.0
    total_impact = sum(a.get("impact", 0) for a in actions)
    auto_impact = sum(a.get("impact", 0) for a in actions if a.get("type") == "auto_fix")
    impact_ratio = auto_impact / total_impact if total_impact > 0 else 0.0

    if coverage == 0:
        rec = "none"
    elif coverage > 0.4 or impact_ratio > 0.3:
        rec = "strong"
    elif phase in ("first_scan", "stagnation", "regression") and coverage > 0.15:
        rec = "strong"
    elif coverage > 0.1:
        rec = "moderate"
    else:
        rec = "none"

    return {
        "auto_fixable_count": auto_fixable,
        "total_count": total,
        "coverage": round(coverage, 3),
        "impact_ratio": round(impact_ratio, 3),
        "recommendation": rec,
    }


def _compute_lanes(actions: list[dict],
                   files_by_det: dict[str, set[str]]) -> dict[str, dict]:
    """Partition actions into parallelizable work lanes.

    Returns a dict of lane_name -> lane_info. Each lane has:
      actions: list of action priorities
      file_count: number of files touched
      total_impact: sum of action impacts
      automation: "full" | "manual"
      run_first: True if this lane should complete before others start
    """
    cleanup_actions = []
    restructure_actions = []
    refactor_actions = []  # list of (action, det)
    debt_actions = []

    for a in actions:
        atype = a.get("type")
        if atype == "auto_fix":
            cleanup_actions.append(a)
        elif atype == "reorganize":
            restructure_actions.append(a)
        elif atype == "debt_review":
            debt_actions.append(a)
        else:
            refactor_actions.append(a)

    lanes: dict[str, dict] = {}

    # 1. Cleanup lane: auto_fix actions, cascade-ordered
    if cleanup_actions:
        # Order: detectors that cascade into others go first
        cascade_order = {det: i for i, det in enumerate(_DETECTOR_CASCADE)}

        def _cleanup_sort_key(a):
            det = a.get("detector", "")
            return (cascade_order.get(det, 99), -a.get("impact", 0))

        cleanup_actions.sort(key=_cleanup_sort_key)
        cleanup_files: set[str] = set()
        for a in cleanup_actions:
            det = a.get("detector")
            if det and det in files_by_det:
                cleanup_files |= files_by_det[det]
        lanes["cleanup"] = {
            "actions": [a["priority"] for a in cleanup_actions],
            "file_count": len(cleanup_files),
            "total_impact": round(sum(a.get("impact", 0) for a in cleanup_actions), 1),
            "automation": "full",
            "run_first": False,  # updated below if overlap
        }

    # 2. Restructure lane: reorganize actions (moves conflict — serialize)
    if restructure_actions:
        restr_files: set[str] = set()
        for a in restructure_actions:
            det = a.get("detector")
            if det and det in files_by_det:
                restr_files |= files_by_det[det]
        lanes["restructure"] = {
            "actions": [a["priority"] for a in restructure_actions],
            "file_count": len(restr_files),
            "total_impact": round(sum(a.get("impact", 0) for a in restructure_actions), 1),
            "automation": "manual",
            "run_first": False,
        }

    # 3. Refactor lanes: partition by file overlap using union-find
    if refactor_actions:
        # Build file sets per action
        action_files: list[tuple[dict, set[str]]] = []
        for a in refactor_actions:
            det = a.get("detector")
            files = files_by_det.get(det, set()) if det else set()
            action_files.append((a, files))

        # test_coverage always gets its own lane
        test_cov_actions = [(a, f) for a, f in action_files
                           if a.get("detector") == "test_coverage"]
        other_actions = [(a, f) for a, f in action_files
                        if a.get("detector") != "test_coverage"]

        # Union-find on remaining actions by file overlap
        groups = _group_by_file_overlap(other_actions)

        for i, group in enumerate(groups):
            group_files: set[str] = set()
            for a, files in group:
                group_files |= files
            lane_name = f"refactor_{i}" if len(groups) > 1 else "refactor"
            lanes[lane_name] = {
                "actions": [a["priority"] for a, _ in group],
                "file_count": len(group_files),
                "total_impact": round(sum(a.get("impact", 0) for a, _ in group), 1),
                "automation": "manual",
                "run_first": False,
            }

        if test_cov_actions:
            tc_files: set[str] = set()
            for a, files in test_cov_actions:
                tc_files |= files
            lanes["test_coverage"] = {
                "actions": [a["priority"] for a, _ in test_cov_actions],
                "file_count": len(tc_files),
                "total_impact": round(sum(a.get("impact", 0) for a, _ in test_cov_actions), 1),
                "automation": "manual",
                "run_first": False,
            }

    # 4. Debt review lane
    if debt_actions:
        lanes["debt_review"] = {
            "actions": [a["priority"] for a in debt_actions],
            "file_count": 0,
            "total_impact": 0.0,
            "automation": "manual",
            "run_first": False,
        }

    # Mark cleanup lane as run_first if its files overlap with any other lane
    if "cleanup" in lanes:
        for name, lane in lanes.items():
            if name == "cleanup":
                continue
            lane_files: set[str] = set()
            for a in actions:
                if a["priority"] in lane["actions"]:
                    det = a.get("detector")
                    if det and det in files_by_det:
                        lane_files |= files_by_det[det]
            if cleanup_files & lane_files:
                lanes["cleanup"]["run_first"] = True
                break

    return lanes


def _group_by_file_overlap(
    action_files: list[tuple[dict, set[str]]],
) -> list[list[tuple[dict, set[str]]]]:
    """Group actions whose file sets overlap using union-find."""
    n = len(action_files)
    if n == 0:
        return []

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i in range(n):
        for j in range(i + 1, n):
            if action_files[i][1] & action_files[j][1]:
                union(i, j)

    groups_map: dict[int, list[int]] = {}
    for i in range(n):
        root = find(i)
        groups_map.setdefault(root, []).append(i)

    return [[action_files[i] for i in idxs] for idxs in groups_map.values()]


def _compute_strategy_hint(fixer_leverage: dict, lanes: dict,
                           can_parallelize: bool, phase: str) -> str:
    """Generate a one- or two-sentence execution strategy hint."""
    rec = fixer_leverage.get("recommendation", "none")
    coverage_pct = round(fixer_leverage.get("coverage", 0) * 100)
    lane_count = sum(1 for name, lane in lanes.items()
                     if name != "debt_review" and not lane.get("run_first"))

    if rec == "strong" and can_parallelize:
        return (f"Run fixers first — they cover {coverage_pct}% of findings. "
                f"Then {lane_count} independent workstreams, safe to parallelize. "
                f"Rescan after each phase to verify.")
    if rec == "strong":
        return (f"Run fixers first — they cover {coverage_pct}% of findings. "
                f"Then rescan to verify.")
    if can_parallelize:
        return (f"{lane_count} independent workstreams, safe to parallelize. "
                f"Rescan after each phase to verify.")
    if phase == "maintenance":
        return "Maintenance mode — address new findings as they appear."
    if phase == "stagnation":
        return "Try a different dimension to break the plateau."
    return "Work through actions in priority order. Rescan after each fix to track progress."


def _compute_strategy(findings: dict, by_det: dict[str, int],
                      actions: list[dict], phase: str,
                      lang: str | None) -> dict:
    """Orchestrate strategy computation: leverage, lanes, hint.

    Annotates each action with a 'lane' field and returns a strategy dict.
    """
    files_by_det = _open_files_by_detector(findings)
    fixer_leverage = _compute_fixer_leverage(by_det, actions, phase, lang)
    lanes = _compute_lanes(actions, files_by_det)

    # Annotate each action with its lane name
    priority_to_lane: dict[int, str] = {}
    for lane_name, lane in lanes.items():
        for p in lane["actions"]:
            priority_to_lane[p] = lane_name
    for a in actions:
        a["lane"] = priority_to_lane.get(a["priority"])

    # Determine parallelizability: 2+ significant non-blocked lanes
    non_blocked = [
        (name, lane) for name, lane in lanes.items()
        if not lane.get("run_first") and name != "debt_review"
    ]
    significant = [
        (name, lane) for name, lane in non_blocked
        if lane["file_count"] >= 5 or lane["total_impact"] >= 1.0
    ]
    can_parallelize = len(significant) >= 2

    hint = _compute_strategy_hint(fixer_leverage, lanes, can_parallelize, phase)

    # Append review clause if review findings exist
    review_action = next((a for a in actions if a.get("type") == "issue_queue"), None)
    if review_action:
        hint += f" Review: {review_action['count']} finding(s) \u2014 `desloppify issues`."

    # Serialize lanes without file sets (only counts)
    serialized_lanes = {
        name: {k: v for k, v in lane.items()}
        for name, lane in lanes.items()
    }

    return {
        "fixer_leverage": fixer_leverage,
        "lanes": serialized_lanes,
        "can_parallelize": can_parallelize,
        "hint": hint,
    }
