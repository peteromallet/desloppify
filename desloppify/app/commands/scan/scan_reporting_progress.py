"""Scan reporting: detector progress section."""

from __future__ import annotations

from typing import Callable, Protocol


class _StateMod(Protocol):
    def path_scoped_findings(self, findings: dict, scan_path: object) -> dict: ...


class _NarrativeMod(Protocol):
    STRUCTURAL_MERGE: frozenset[str]


class _RegistryMod(Protocol):
    DETECTORS: dict

    def display_order(self) -> list[str]: ...


def show_detector_progress(
    state: dict,
    *,
    state_mod: _StateMod,
    narrative_mod: _NarrativeMod,
    registry_mod: _RegistryMod,
    colorize_fn: Callable[[str, str], str],
) -> None:
    """Show per-detector progress bars."""
    findings = state_mod.path_scoped_findings(state["findings"], state.get("scan_path"))
    if not findings:
        return

    by_det: dict[str, dict] = {}
    for finding in findings.values():
        detector = finding.get("detector", "unknown")
        if detector in narrative_mod.STRUCTURAL_MERGE:
            detector = "structural"
        if detector not in by_det:
            by_det[detector] = {"open": 0, "total": 0}
        by_det[detector]["total"] += 1
        if finding["status"] == "open":
            by_det[detector]["open"] += 1

    detector_order = [
        registry_mod.DETECTORS[d].display
        for d in registry_mod.display_order()
        if d in registry_mod.DETECTORS
    ]
    order_map = {display: i for i, display in enumerate(detector_order)}
    sorted_dets = sorted(by_det.items(), key=lambda item: order_map.get(item[0], 99))

    print(colorize_fn("  Detector progress (open findings by detector):", "dim"))
    print(colorize_fn("  " + "─" * 50, "dim"))
    bar_len = 15
    for detector, data in sorted_dets:
        total = data["total"]
        open_count = data["open"]
        addressed = total - open_count
        pct = round(addressed / total * 100) if total else 100

        filled = round(pct / 100 * bar_len)
        if pct == 100:
            bar = colorize_fn("█" * bar_len, "green")
        elif open_count <= 2:
            bar = colorize_fn("█" * filled, "green") + colorize_fn(
                "░" * (bar_len - filled), "dim"
            )
        else:
            bar = colorize_fn("█" * filled, "yellow") + colorize_fn(
                "░" * (bar_len - filled), "dim"
            )

        det_label = detector.replace("_", " ").ljust(18)
        open_str = (
            colorize_fn(f"{open_count:3d} open", "yellow")
            if open_count > 0
            else colorize_fn("  ✓", "green")
        )
        print(
            f"  {det_label} {bar} {pct:3d}%  {open_str}  {colorize_fn(f'/ {total}', 'dim')}"
        )

    print()


__all__ = ["show_detector_progress"]
