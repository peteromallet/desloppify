"""Direct tests for scorecard drawing primitives."""

from __future__ import annotations

import desloppify.app.output.scorecard_parts.draw as scorecard_draw_mod


class _FakeDraw:
    def __init__(self):
        self.polygons: list[tuple[list[tuple[int, int]], str]] = []
        self.rectangles: list[tuple[tuple[int, int, int, int], str]] = []

    def polygon(self, points, fill=None):
        self.polygons.append((list(points), fill))

    def rectangle(self, box, fill=None):
        self.rectangles.append((tuple(box), fill))


def test_draw_ornament_creates_diamond_points():
    draw = _FakeDraw()
    scorecard_draw_mod.draw_ornament(draw, cx=10, cy=20, size=3, fill="red")

    assert len(draw.polygons) == 1
    points, fill = draw.polygons[0]
    assert points == [(10, 17), (13, 20), (10, 23), (7, 20)]
    assert fill == "red"


def test_draw_rule_with_ornament_draws_two_segments_and_center_mark():
    draw = _FakeDraw()
    scorecard_draw_mod.draw_rule_with_ornament(
        draw, y=30, x1=0, x2=100, cx=50, line_fill="line", ornament_fill="orn"
    )

    assert len(draw.rectangles) == 2
    assert draw.rectangles[0][1] == "line"
    assert draw.rectangles[1][1] == "line"
    assert len(draw.polygons) == 1
    assert draw.polygons[0][1] == "orn"


def test_draw_vertical_rule_with_ornament_draws_two_segments_and_center_mark():
    draw = _FakeDraw()
    scorecard_draw_mod.draw_vert_rule_with_ornament(
        draw, x=25, y1=0, y2=100, cy=50, line_fill="line", ornament_fill="orn"
    )

    assert len(draw.rectangles) == 2
    assert draw.rectangles[0][1] == "line"
    assert draw.rectangles[1][1] == "line"
    assert len(draw.polygons) == 1
    points, fill = draw.polygons[0]
    assert fill == "orn"
    assert points[0][0] == 25
    assert points[2][0] == 25
