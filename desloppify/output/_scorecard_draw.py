"""Scorecard drawing helpers — panel rendering for the health badge."""

from __future__ import annotations

from .scorecard import (
    _ACCENT,
    _BG,
    _BG_ROW_ALT,
    _BG_SCORE,
    _BG_TABLE,
    _BORDER,
    _DIM,
    _TEXT,
    _fmt_score,
    _load_font,
    _s,
    _score_color,
)


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


def _draw_left_panel(
    draw,
    main_score: float,
    strict_score: float,
    project_name: str,
    lp_left: int,
    lp_right: int,
    lp_top: int,
    lp_bot: int,
):
    """Draw the left panel: score panel background, title, score, strict, project name."""
    font_title = _load_font(15, serif=True, bold=True)
    font_big = _load_font(42, serif=True, bold=True)
    font_strict_label = _load_font(12, serif=True)
    font_strict_val = _load_font(19, serif=True, bold=True)
    font_project = _load_font(9, serif=True)

    lp_cx = (lp_left + lp_right) // 2

    draw.rounded_rectangle(
        (lp_left, lp_top, lp_right, lp_bot),
        radius=_s(4),
        fill=_BG_SCORE,
        outline=_BORDER,
        width=1,
    )

    # Measure all elements
    title = "DESLOPPIFY SCORE"
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_h = title_bbox[3] - title_bbox[1]
    tw = draw.textlength(title, font=font_title)

    score_str = _fmt_score(main_score)
    score_bbox = draw.textbbox((0, 0), score_str, font=font_big)
    score_h = score_bbox[3] - score_bbox[1]

    strict_label_bbox = draw.textbbox((0, 0), "strict", font=font_strict_label)
    strict_val_str = _fmt_score(strict_score)
    strict_val_bbox = draw.textbbox((0, 0), strict_val_str, font=font_strict_val)
    strict_h = max(
        strict_label_bbox[3] - strict_label_bbox[1],
        strict_val_bbox[3] - strict_val_bbox[1],
    )

    proj_bbox = draw.textbbox((0, 0), project_name, font=font_project)
    proj_h = proj_bbox[3] - proj_bbox[1]

    # Stack: title → ornament rule → score → strict → project pill
    ornament_gap = _s(7)
    score_gap = _s(6)
    proj_gap = _s(8)
    pill_pad_y = _s(3)
    pill_pad_x = _s(8)
    proj_pill_h = proj_h + 2 * pill_pad_y
    total_h = (
        title_h
        + ornament_gap
        + _s(6)
        + ornament_gap
        + score_h
        + score_gap
        + strict_h
        + proj_gap
        + proj_pill_h
    )
    y0 = (lp_top + lp_bot) // 2 - total_h // 2 + _s(3)

    # Title
    draw.text((lp_cx - tw / 2, y0 - title_bbox[1]), title, fill=_TEXT, font=font_title)

    # Ornamental rule
    rule_y = y0 + title_h + ornament_gap
    rule_inset = _s(28)
    _draw_rule_with_ornament(
        draw,
        rule_y,
        lp_left + rule_inset,
        lp_right - rule_inset,
        lp_cx,
        _BORDER,
        _ACCENT,
    )

    # Main score
    score_y = rule_y + _s(6) + ornament_gap
    sw = draw.textlength(score_str, font=font_big)
    draw.text(
        (lp_cx - sw / 2, score_y - score_bbox[1]),
        score_str,
        fill=_score_color(main_score),
        font=font_big,
    )

    # Strict label + value
    strict_y = score_y + score_h + score_gap
    sl_w = draw.textlength("strict", font=font_strict_label)
    sv_w = draw.textlength(strict_val_str, font=font_strict_val)
    gap = _s(5)
    strict_x = lp_cx - (sl_w + gap + sv_w) / 2
    draw.text(
        (strict_x, strict_y - strict_label_bbox[1]),
        "strict",
        fill=_DIM,
        font=font_strict_label,
    )
    draw.text(
        (strict_x + sl_w + gap, strict_y - strict_val_bbox[1]),
        strict_val_str,
        fill=_score_color(strict_score, muted=True),
        font=font_strict_val,
    )

    # Project name in a subtle pill
    pill_top = strict_y + strict_h + proj_gap
    proj_y = pill_top + pill_pad_y
    pw = draw.textlength(project_name, font=font_project)
    pill_left = lp_cx - pw / 2 - pill_pad_x
    pill_right = lp_cx + pw / 2 + pill_pad_x
    pill_bot = pill_top + proj_pill_h
    draw.rounded_rectangle(
        (pill_left, pill_top, pill_right, pill_bot),
        radius=_s(3),
        fill=_BG,
        outline=_BORDER,
        width=1,
    )
    draw.text(
        (lp_cx - pw / 2, proj_y - proj_bbox[1]),
        project_name,
        fill=_DIM,
        font=font_project,
    )


def _draw_right_panel(
    draw,
    active_dims: list,
    row_h: int,
    table_x1: int,
    table_x2: int,
    table_top: int,
    table_bot: int,
):
    """Draw the right panel: two separate dimension tables side by side."""
    font_row = _load_font(11, mono=True)
    font_strict = _load_font(9, mono=True)
    row_count = len(active_dims)

    # Split into 2 separate grids
    cols = 2
    rows_per_col = (row_count + cols - 1) // cols

    table_w = table_x2 - table_x1
    # Gap between cards — no left margin so divider is centered between
    # the left panel and first card (table_x1 already sits _s(11) from divider)
    grid_gap = _s(8)
    available_width = table_w
    grid_w = (available_width - grid_gap) // cols
    grid_start_x = table_x1

    for c in range(cols):
        grid_x1 = grid_start_x + c * (grid_w + grid_gap)
        grid_x2 = grid_x1 + grid_w

        draw.rounded_rectangle(
            (grid_x1, table_top, grid_x2, table_bot),
            radius=_s(4),
            fill=_BG_TABLE,
            outline=_BORDER,
            width=1,
        )

        # Push values to the right, then center all 3 columns as a group
        grid_width = grid_x2 - grid_x1
        # Calculate the total width of the content block
        col_name_w = _s(120)  # Dimension column width (fits "AI Generated Debt")
        col_gap = _s(4)  # gap between columns
        col_val_w = _s(34)  # width for value columns (fits "100.0%")
        total_content_w = col_name_w + col_gap + col_val_w + col_gap + col_val_w
        # Center this block in the grid
        block_left = grid_x1 + (grid_width - total_content_w) // 2
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
                draw.rectangle(
                    (grid_x1 + 1, band_top, grid_x2 - 1, band_bot), fill=_BG_ROW_ALT
                )
            text_y = band_top + (row_h - row_text_h) // 2 - row_text_offset + _s(1)
            score = data.get("score", 100)
            strict = data.get("strict", score)
            draw.text((col_name, text_y), name, fill=_TEXT, font=font_row)
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
