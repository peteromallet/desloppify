"""Scan reporting: score breakdown, delta helpers, and detector progress."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from desloppify.engine._state.schema import StateModel

# ---------------------------------------------------------------------------
# Protocol stubs for dependency-injected modules
# ---------------------------------------------------------------------------


class _StateMod(Protocol):
    def path_scoped_issues(
        self, issues: dict[str, dict[str, Any]], scan_path: Any
    ) -> dict[str, dict[str, Any]]: ...


class _NarrativeMod(Protocol):
    STRUCTURAL_MERGE: frozenset[str]


class _RegistryMod(Protocol):
    DETECTORS: dict[str, Any]

    def display_order(self) -> list[str]: ...


# ---------------------------------------------------------------------------
# Breakdown helpers (from scan_reporting_breakdown)
# ---------------------------------------------------------------------------


def dimension_bar(score: float, *, colorize_fn, bar_len: int = 15) -> str:
    """Render a score bar consistent with scan detector bars."""
    filled = max(0, min(bar_len, round(score / 100 * bar_len)))
    if score >= 98:
        return colorize_fn("█" * bar_len, "green")
    if score >= 93:
        return colorize_fn("█" * filled, "green") + colorize_fn(
            "░" * (bar_len - filled), "dim"
        )
    return colorize_fn("█" * filled, "yellow") + colorize_fn(
        "░" * (bar_len - filled), "dim"
    )


def _print_score_recipe(
    *,
    colorize_fn,
    mech_frac: float,
    subj_frac: float,
    mech_avg: float,
    subj_avg: float | None,
) -> None:
    recipe_lines = [
        line.strip()
        for line in _score_recipe_lines(
            mech_frac=mech_frac,
            subj_frac=subj_frac,
            mech_avg=mech_avg,
            subj_avg=subj_avg,
        )
        if isinstance(line, str) and line.strip()
    ]
    if not recipe_lines:
        return

    label = "  Score recipe:"
    if subj_avg is None or subj_frac <= 0.0:
        label = "  Score recipe (objective-only):"
    elif mech_frac <= 0.0:
        label = "  Score recipe (subjective-only):"

    print(colorize_fn(label, "dim"))
    for recipe_line in recipe_lines:
        print(colorize_fn(f"    {recipe_line}", "dim"))


def _score_recipe_lines(
    *,
    mech_frac: float,
    subj_frac: float,
    mech_avg: float,
    subj_avg: float | None,
) -> list[str]:
    if subj_avg is None or subj_frac <= 0.0:
        return [
            "overall = 100% mechanical",
            f"Mechanical pool average: {mech_avg:.1f}%",
        ]
    if mech_frac <= 0.0:
        return [
            "overall = 100% subjective",
            f"Subjective pool average: {subj_avg:.1f}%",
        ]
    return [
        f"overall = {mech_frac * 100:.0f}% mechanical + {subj_frac * 100:.0f}% subjective",
        f"Pool averages: mechanical {mech_avg:.1f}% · subjective {subj_avg:.1f}%",
    ]


def _sorted_weighted_drags(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    drags = [
        entry
        for entry in entries
        if float(entry.get("overall_drag", 0.0) or 0.0) > 0.01
    ]
    return sorted(
        drags,
        key=lambda entry: -float(entry.get("overall_drag", 0.0) or 0.0),
    )


def _detector_progress_bar(*, pct: int, open_count: int, bar_len: int, colorize_fn) -> str:
    filled = round(pct / 100 * bar_len)
    if pct == 100:
        return colorize_fn("█" * bar_len, "green")
    if open_count <= 2:
        return colorize_fn("█" * filled, "green") + colorize_fn(
            "░" * (bar_len - filled), "dim"
        )
    return colorize_fn("█" * filled, "yellow") + colorize_fn(
        "░" * (bar_len - filled), "dim"
    )


def _dimension_delta_entry(
    name: str,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> tuple[str, float, float, float, float, float, float] | None:
    old_score = previous.get("score", 100)
    new_score = current.get("score", 100)
    old_strict = previous.get("strict", old_score)
    new_strict = current.get("strict", new_score)
    delta = new_score - old_score
    strict_delta = new_strict - old_strict
    if abs(delta) < 0.1 and abs(strict_delta) < 0.1:
        return None
    return (
        name,
        old_score,
        new_score,
        delta,
        old_strict,
        new_strict,
        strict_delta,
    )


def _format_strict_delta(
    *,
    old_strict: float,
    new_strict: float,
    strict_delta: float,
    colorize_fn,
) -> str:
    if abs(strict_delta) < 0.1:
        return ""
    strict_sign = "+" if strict_delta > 0 else ""
    return colorize_fn(
        f"  strict: {old_strict:.1f}→{new_strict:.1f}% ({strict_sign}{strict_delta:.1f}%)",
        "dim",
    )


def show_score_model_breakdown(
    state: StateModel,
    *,
    scoring_mod,
    colorize_fn,
    dim_scores: dict[str, Any] | None = None,
) -> None:
    """Show score recipe and weighted drags."""
    if dim_scores is None:
        dim_scores = state.get("dimension_scores", {})
    if not dim_scores:
        return

    breakdown = scoring_mod.compute_health_breakdown(dim_scores)
    mech_frac = float(breakdown.get("mechanical_fraction", 1.0) or 0.0)
    subj_frac = float(breakdown.get("subjective_fraction", 0.0) or 0.0)
    mech_avg = float(breakdown.get("mechanical_avg", 100.0) or 100.0)
    subj_avg_raw = breakdown.get("subjective_avg")
    subj_avg = float(subj_avg_raw) if isinstance(subj_avg_raw, int | float) else None
    entries = [
        entry for entry in breakdown.get("entries", []) if isinstance(entry, dict)
    ]
    if not entries:
        return

    _print_score_recipe(
        colorize_fn=colorize_fn,
        mech_frac=mech_frac,
        subj_frac=subj_frac,
        mech_avg=mech_avg,
        subj_avg=subj_avg,
    )
    drags = _sorted_weighted_drags(entries)
    if drags:
        print(colorize_fn("    Biggest weighted drags:", "dim"))
        for entry in drags[:5]:
            name = str(entry.get("name", "unknown"))
            score = float(entry.get("score", 0.0) or 0.0)
            drag = float(entry.get("overall_drag", 0.0) or 0.0)
            pool = str(entry.get("pool", "unknown"))
            pool_share = float(entry.get("pool_share", 0.0) or 0.0) * 100
            print(
                colorize_fn(
                    f"      - {name}: -{drag:.2f} pts "
                    f"(score {score:.1f}%, {pool_share:.1f}% of {pool} pool)",
                    "dim",
                )
            )
    print()


def show_dimension_deltas(
    prev: dict[str, Any],
    current: dict[str, Any],
    *,
    scoring_mod,
    colorize_fn,
) -> None:
    """Show which dimensions changed between scans (health and strict)."""
    moved = []
    for dim in scoring_mod.DIMENSIONS:
        p = prev.get(dim.name, {})
        n = current.get(dim.name, {})
        if not p or not n:
            continue
        entry = _dimension_delta_entry(dim.name, p, n)
        if entry is not None:
            moved.append(entry)

    if not moved:
        return

    print(colorize_fn("  Moved:", "dim"))
    for name, old, new, delta, old_s, new_s, s_delta in sorted(
        moved, key=lambda item: item[3]
    ):
        sign = "+" if delta > 0 else ""
        color = "green" if delta > 0 else "red"
        strict_str = _format_strict_delta(
            old_strict=old_s,
            new_strict=new_s,
            strict_delta=s_delta,
            colorize_fn=colorize_fn,
        )
        print(
            colorize_fn(
                f"    {name:<22} {old:.1f}% → {new:.1f}%  ({sign}{delta:.1f}%)", color
            )
            + strict_str
        )
    print()


def _dimension_hint(
    name: str,
    *,
    static_names: set[str],
    mechanical_hints: dict[str, str],
) -> str:
    if name in static_names:
        return mechanical_hints.get(name, "run `desloppify show` for details")
    return "run `desloppify review --prepare` to assess (see skill doc for review workflow)"


def show_low_dimension_hints(
    dim_scores: dict[str, Any],
    *,
    scoring_mod,
    colorize_fn,
) -> None:
    """Show actionable hints for dimensions below 50%."""
    static_names = {dim.name for dim in scoring_mod.DIMENSIONS}

    mechanical_hints = {
        "File health": "run `desloppify show structural` — split large files",
        "Code quality": "run `desloppify show smells` — fix code smells",
        "Duplication": "run `desloppify show dupes` — deduplicate functions",
        "Test health": "run `desloppify show test_coverage` — review coverage gaps (fix code issues first, tests later)",
        "Security": "run `desloppify show security` — fix security issues",
    }

    low = []
    for name, data in dim_scores.items():
        strict = data.get("strict", data.get("score", 100))
        if strict >= 50:
            continue
        low.append((
            name,
            strict,
            _dimension_hint(
                name,
                static_names=static_names,
                mechanical_hints=mechanical_hints,
            ),
        ))

    if not low:
        return

    low.sort(key=lambda item: item[1])
    print(colorize_fn("  Needs attention:", "yellow"))
    for name, score, hint in low:
        print(colorize_fn(f"    {name} ({score:.0f}%) — {hint}", "yellow"))
    print()


# ---------------------------------------------------------------------------
# Detector progress (from scan_reporting_progress)
# ---------------------------------------------------------------------------


def _collect_detector_progress(issues: dict[str, dict[str, Any]], *, narrative_mod) -> dict[str, dict[str, int]]:
    by_detector: dict[str, dict[str, int]] = {}
    for issue in issues.values():
        detector = issue.get("detector", "unknown")
        if detector in narrative_mod.STRUCTURAL_MERGE:
            detector = "structural"
        counts = by_detector.setdefault(detector, {"open": 0, "total": 0})
        counts["total"] += 1
        if issue["status"] == "open":
            counts["open"] += 1
    return by_detector


def _sorted_detector_progress(
    by_detector: dict[str, dict[str, int]],
    *,
    registry_mod: _RegistryMod,
) -> list[tuple[str, dict[str, int]]]:
    detector_order = [
        registry_mod.DETECTORS[d].display
        for d in registry_mod.display_order()
        if d in registry_mod.DETECTORS
    ]
    order_map = {display: i for i, display in enumerate(detector_order)}
    return sorted(
        by_detector.items(),
        key=lambda item: order_map.get(item[0], 99),
    )


def _render_detector_progress_row(
    detector: str,
    data: dict[str, int],
    *,
    bar_len: int,
    colorize_fn,
) -> str:
    total = data["total"]
    open_count = data["open"]
    addressed = total - open_count
    pct = round(addressed / total * 100) if total else 100
    bar = _detector_progress_bar(
        pct=pct,
        open_count=open_count,
        bar_len=bar_len,
        colorize_fn=colorize_fn,
    )
    det_label = detector.replace("_", " ").ljust(18)
    open_str = (
        colorize_fn(f"{open_count:3d} open", "yellow")
        if open_count > 0
        else colorize_fn("  ✓", "green")
    )
    return (
        f"  {det_label} {bar} {pct:3d}%  {open_str}  "
        f"{colorize_fn(f'/ {total}', 'dim')}"
    )


def show_detector_progress(
    state: StateModel,
    *,
    state_mod: _StateMod,
    narrative_mod: _NarrativeMod,
    registry_mod: _RegistryMod,
    colorize_fn: Callable[[str, str], str],
) -> None:
    """Show per-detector progress bars."""
    work_items = state.get("work_items") or state.get("issues", {})
    issues = state_mod.path_scoped_issues(work_items, state.get("scan_path"))
    if not issues:
        return

    by_detector = _collect_detector_progress(issues, narrative_mod=narrative_mod)
    sorted_dets = _sorted_detector_progress(by_detector, registry_mod=registry_mod)

    print(colorize_fn("  Detector progress (open issues by detector):", "dim"))
    print(colorize_fn("  " + "─" * 50, "dim"))
    bar_len = 15
    for detector, data in sorted_dets:
        print(_render_detector_progress_row(
            detector,
            data,
            bar_len=bar_len,
            colorize_fn=colorize_fn,
        )
        )

    print()


__all__ = [
    "dimension_bar",
    "show_dimension_deltas",
    "show_detector_progress",
    "show_low_dimension_hints",
    "show_score_model_breakdown",
]
