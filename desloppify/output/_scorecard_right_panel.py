"""Right-panel table renderer for the scorecard badge."""

from __future__ import annotations

from .scorecard import (
    _BG_ROW_ALT,
    _BG_TABLE,
    _BORDER,
    _TEXT,
    _fmt_score,
    _load_font,
    _s,
    _score_color,
)


def _truncate_name(draw, name: str, max_name_w: int, font_row) -> str:
    if draw.textlength(name, font=font_row) <= max_name_w:
        return name
    while name and draw.textlength(name + "\u2026", font=font_row) > max_name_w:
        name = name[:-1]
    return name.rstrip() + "\u2026"


def draw_right_panel(
    draw,
    active_dims: list,
    row_h: int,
    table_x1: int,
    table_x2: int,
    table_top: int,
    table_bot: int,
) -> None:
    """Draw the right panel: two dimension cards with score rows."""
    font_row = _load_font(11, mono=True)
    font_strict = _load_font(9, mono=True)
    row_count = len(active_dims)

    cols = 2
    rows_per_col = (row_count + cols - 1) // cols

    grid_gap = _s(8)
    grid_w = ((table_x2 - table_x1) - grid_gap) // cols

    for c in range(cols):
        grid_x1 = table_x1 + c * (grid_w + grid_gap)
        grid_x2 = grid_x1 + grid_w

        draw.rounded_rectangle(
            (grid_x1, table_top, grid_x2, table_bot),
            radius=_s(4),
            fill=_BG_TABLE,
            outline=_BORDER,
            width=1,
        )

        col_name_w = _s(120)
        col_gap = _s(4)
        col_val_w = _s(34)
        total_content_w = col_name_w + col_gap + col_val_w + col_gap + col_val_w
        block_left = grid_x1 + (grid_w - total_content_w) // 2
        col_name = block_left
        col_health = col_name + col_name_w + col_gap
        col_strict = col_health + col_val_w + col_gap + _s(4)

        this_col_rows = min(rows_per_col, row_count - c * rows_per_col)
        table_content_h = this_col_rows * row_h
        table_content_top = (table_top + table_bot) // 2 - table_content_h // 2

        sample_bbox = draw.textbbox((0, 0), "Xg", font=font_row)
        row_text_h = sample_bbox[3] - sample_bbox[1]
        row_text_offset = sample_bbox[1]

        y_band = table_content_top
        start_idx = c * rows_per_col
        for i in range(this_col_rows):
            idx = start_idx + i
            if idx >= row_count:
                break
            name, data = active_dims[idx]
            band_top = y_band
            band_bot = y_band + row_h
            if i % 2 == 1:
                draw.rectangle((grid_x1 + 1, band_top, grid_x2 - 1, band_bot), fill=_BG_ROW_ALT)

            text_y = band_top + (row_h - row_text_h) // 2 - row_text_offset + _s(1)
            score = data.get("score", 100)
            strict = data.get("strict", score)

            max_name_w = col_name_w - _s(2)
            fitted_name = _truncate_name(draw, name, max_name_w, font_row)
            draw.text((col_name, text_y), fitted_name, fill=_TEXT, font=font_row)
            draw.text(
                (col_health, text_y),
                f"{_fmt_score(score)}%",
                fill=_score_color(score),
                font=font_row,
            )

            strict_text = f"{_fmt_score(strict)}%"
            strict_bbox = draw.textbbox((0, 0), strict_text, font=font_strict)
            strict_text_h = strict_bbox[3] - strict_bbox[1]
            strict_y = band_top + (row_h - strict_text_h) // 2 - strict_bbox[1]
            draw.text(
                (col_strict, strict_y),
                strict_text,
                fill=_score_color(strict, muted=True),
                font=font_strict,
            )
            y_band += row_h
