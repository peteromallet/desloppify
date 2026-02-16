"""Scorecard drawing wrappers used by the scorecard renderer."""

from __future__ import annotations

from .scorecard import _s


def _draw_ornament(draw, cx: int, cy: int, size: int, fill):
    """Draw a small diamond ornament centered at (cx, cy)."""
    draw.polygon(
        [
            (cx, cy - size),
            (cx + size, cy),
            (cx, cy + size),
            (cx - size, cy),
        ],
        fill=fill,
    )


def _draw_rule_with_ornament(
    draw, y: int, x1: int, x2: int, cx: int, line_fill, ornament_fill
):
    """Draw a horizontal rule with a diamond ornament in the center."""
    gap = _s(8)
    draw.rectangle((x1, y, cx - gap, y + 1), fill=line_fill)
    draw.rectangle((cx + gap, y, x2, y + 1), fill=line_fill)
    _draw_ornament(draw, cx, y, _s(3), ornament_fill)


def _draw_vert_rule_with_ornament(
    draw, x: int, y1: int, y2: int, cy: int, line_fill, ornament_fill
):
    """Draw a vertical rule with a diamond ornament in the center."""
    gap = _s(8)
    draw.rectangle((x, y1, x + 1, cy - gap), fill=line_fill)
    draw.rectangle((x, cy + gap, x + 1, y2), fill=line_fill)
    _draw_ornament(draw, x, cy, _s(3), ornament_fill)


def _draw_left_panel(*args, **kwargs):
    """Backward-compatible wrapper around left-panel renderer."""
    from ._scorecard_left_panel import draw_left_panel

    kwargs.setdefault("draw_rule_with_ornament_fn", _draw_rule_with_ornament)
    return draw_left_panel(*args, **kwargs)


def _draw_right_panel(*args, **kwargs):
    """Backward-compatible wrapper around right-panel renderer."""
    from ._scorecard_right_panel import draw_right_panel

    return draw_right_panel(*args, **kwargs)
