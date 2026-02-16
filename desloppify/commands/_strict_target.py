"""Shared strict-target progress rendering helpers."""

from __future__ import annotations


def format_strict_target_progress(strict_target: dict | None) -> tuple[list[tuple[str, str]], float | None, float | None]:
    """Return display lines and numeric values for strict target progress.

    Returns:
      (lines, target, gap)
      lines: list of (message, color_style)
      target: target strict score, or None when unavailable
      gap: target - current strict score, or None when unavailable
    """
    lines: list[tuple[str, str]] = []
    if not isinstance(strict_target, dict):
        return lines, None, None

    warning = strict_target.get("warning")
    if isinstance(warning, str) and warning.strip():
        lines.append((f"  * {warning.strip()}", "yellow"))

    target = strict_target.get("target")
    current = strict_target.get("current")
    gap = strict_target.get("gap")
    state = strict_target.get("state")
    if not isinstance(target, (int, float)):
        return lines, None, None
    target_f = float(target)

    if not isinstance(current, (int, float)):
        lines.append((f"  Strict target: {target_f:.1f}/100 · current strict score unavailable", "dim"))
        return lines, target_f, None

    current_f = float(current)
    gap_f = float(gap) if isinstance(gap, (int, float)) else round(target_f - current_f, 1)
    if state == "below":
        lines.append((
            f"  Strict target: {target_f:.1f}/100 · currently {current_f:.1f}/100 ({gap_f:.1f} below target)",
            "yellow",
        ))
    elif state == "above":
        lines.append((
            f"  Strict target: {target_f:.1f}/100 · currently {current_f:.1f}/100 ({abs(gap_f):.1f} above target)",
            "green",
        ))
    else:
        lines.append((f"  Strict target: {target_f:.1f}/100 · on target", "green"))

    return lines, target_f, gap_f
