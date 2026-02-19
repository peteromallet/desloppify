"""Scorecard panel drawing helpers used by the renderer."""

from __future__ import annotations

from desloppify.app.output.scorecard_parts.left_panel import draw_left_panel
from desloppify.app.output.scorecard_parts.ornaments import (
    draw_ornament,
    draw_rule_with_ornament,
    draw_vert_rule_with_ornament,
)
from desloppify.app.output.scorecard_parts.theme import (
    BG_ROW_ALT,
    BG_TABLE,
    BORDER,
    TEXT,
    fmt_score,
    load_font,
    scale,
    score_color,
)


def draw_right_panel(
    draw,
    active_dims: list,
    row_h: int,
    table_x1: int,
    table_x2: int,
    table_top: int,
    table_bot: int,
) -> None:
    """Draw the right panel: two separate dimension tables side by side."""
    font_row = load_font(11, mono=True)
    font_strict = load_font(9, mono=True)
    row_count = len(active_dims)

    cols = 2
    rows_per_col = (row_count + cols - 1) // cols
    table_width = table_x2 - table_x1
    grid_gap = scale(8)
    grid_width = (table_width - grid_gap) // cols

    for col_index in range(cols):
        grid_x1 = table_x1 + col_index * (grid_width + grid_gap)
        grid_x2 = grid_x1 + grid_width
        draw.rounded_rectangle(
            (grid_x1, table_top, grid_x2, table_bot),
            radius=scale(4),
            fill=BG_TABLE,
            outline=BORDER,
            width=1,
        )

        name_col_width = scale(120)
        value_col_gap = scale(4)
        value_col_width = scale(34)
        total_content_width = (
            name_col_width
            + value_col_gap
            + value_col_width
            + value_col_gap
            + value_col_width
        )
        block_left = grid_x1 + (grid_width - total_content_width) // 2
        name_col_x = block_left
        health_col_x = name_col_x + name_col_width + value_col_gap
        strict_col_x = health_col_x + value_col_width + value_col_gap + scale(4)

        rows_this_col = min(rows_per_col, row_count - col_index * rows_per_col)
        content_height = rows_this_col * row_h
        content_top = (table_top + table_bot) // 2 - content_height // 2

        sample_bbox = draw.textbbox((0, 0), "Xg", font=font_row)
        row_text_height = sample_bbox[3] - sample_bbox[1]
        row_text_offset = sample_bbox[1]
        start_idx = col_index * rows_per_col

        for row_index in range(rows_this_col):
            dim_idx = start_idx + row_index
            if dim_idx >= row_count:
                break
            name, data = active_dims[dim_idx]
            band_top = content_top + row_index * row_h
            band_bottom = band_top + row_h
            if row_index % 2 == 1:
                draw.rectangle(
                    (grid_x1 + 1, band_top, grid_x2 - 1, band_bottom), fill=BG_ROW_ALT
                )
            text_y = band_top + (row_h - row_text_height) // 2 - row_text_offset + scale(1)
            score = data.get("score", 100)
            strict = data.get("strict", score)

            max_name_width = name_col_width - scale(2)
            while (
                name
                and draw.textlength(name + "\u2026", font=font_row) > max_name_width
            ):
                name = name[:-1]
            if draw.textlength(name, font=font_row) > max_name_width:
                name = name.rstrip() + "\u2026"

            draw.text((name_col_x, text_y), name, fill=TEXT, font=font_row)
            draw.text(
                (health_col_x, text_y),
                f"{fmt_score(score)}%",
                fill=score_color(score),
                font=font_row,
            )

            strict_text = f"{fmt_score(strict)}%"
            strict_bbox = draw.textbbox((0, 0), strict_text, font=font_strict)
            strict_text_height = strict_bbox[3] - strict_bbox[1]
            strict_y = band_top + (row_h - strict_text_height) // 2 - strict_bbox[1]
            draw.text(
                (strict_col_x, strict_y),
                strict_text,
                fill=score_color(strict, muted=True),
                font=font_strict,
            )

__all__ = [
    "draw_left_panel",
    "draw_right_panel",
    "draw_ornament",
    "draw_rule_with_ornament",
    "draw_vert_rule_with_ornament",
]
