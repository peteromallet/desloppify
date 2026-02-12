"""Scorecard badge image generator — produces a visual health summary PNG."""

from __future__ import annotations

import os
from pathlib import Path

from .utils import PROJECT_ROOT

# Render at 2x for retina/high-DPI crispness
_SCALE = 2


def _score_color(score: float, *, muted: bool = False) -> tuple[int, int, int]:
    """Color-code a score: deep sage >= 90, mustard 70-90, dusty rose < 70.

    muted=True returns a desaturated variant for secondary display (strict column).
    """
    if score >= 90:
        base = (88, 129, 87)     # deep sage
    elif score >= 70:
        base = (178, 148, 72)    # warm mustard
    else:
        base = (168, 90, 90)     # dusty rose
    if not muted:
        return base
    # Blend toward warm gray for a secondary feel
    gray = (158, 142, 122)
    return tuple(int(b * 0.55 + g * 0.45) for b, g in zip(base, gray))


def _load_font(size: int, *, serif: bool = False, bold: bool = False, mono: bool = False):
    """Load a font with cross-platform fallback."""
    from PIL import ImageFont

    size = size * _SCALE
    candidates = []
    if mono:
        candidates = [
            "/System/Library/Fonts/SFNSMono.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
        ]
    elif serif and bold:
        candidates = [
            "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
            "/System/Library/Fonts/NewYork.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
        ]
    elif serif:
        candidates = [
            "/System/Library/Fonts/Supplemental/Georgia.ttf",
            "/System/Library/Fonts/NewYork.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
        ]
    elif bold:
        candidates = [
            "/System/Library/Fonts/SFCompact.ttf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
    else:
        candidates = [
            "/System/Library/Fonts/SFCompact.ttf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _s(v: int | float) -> int:
    """Scale a layout value."""
    return int(v * _SCALE)


def _draw_ornament(draw, cx: int, cy: int, size: int, fill):
    """Draw a small diamond ornament centered at (cx, cy)."""
    draw.polygon([
        (cx, cy - size), (cx + size, cy), (cx, cy + size), (cx - size, cy),
    ], fill=fill)


def _draw_rule_with_ornament(draw, y: int, x1: int, x2: int, cx: int, line_fill, ornament_fill):
    """Draw a horizontal rule with a diamond ornament in the center."""
    gap = _s(8)
    draw.rectangle((x1, y, cx - gap, y + 1), fill=line_fill)
    draw.rectangle((cx + gap, y, x2, y + 1), fill=line_fill)
    _draw_ornament(draw, cx, y, _s(3), ornament_fill)


def generate_scorecard(state: dict, output_path: str | Path) -> Path:
    """Render a scorecard PNG from scan state. Returns the output path."""
    from PIL import Image, ImageDraw

    output_path = Path(output_path)
    dim_scores = state.get("dimension_scores", {})
    obj_score = state.get("objective_score")
    obj_strict = state.get("objective_strict")

    main_score = obj_score if obj_score is not None else state.get("score", 0)
    strict_score = obj_strict if obj_strict is not None else state.get("strict_score", 0)

    # Fonts — serif for headings, mono for data
    font_title = _load_font(18, serif=True, bold=True)
    font_big = _load_font(48, serif=True, bold=True)
    font_strict_label = _load_font(13, serif=True)
    font_strict_val = _load_font(22, serif=True, bold=True)
    font_header = _load_font(10, mono=True)
    font_row = _load_font(11, mono=True)
    font_tiny = _load_font(9, serif=True)

    # Wes Anderson palette
    BG = (247, 240, 228)           # warm cream
    BG_SCORE = (240, 232, 217)     # slightly warm panel behind score
    BG_TABLE = (240, 233, 220)     # table background
    BG_ROW_ALT = (234, 226, 212)   # alternating row tint
    TEXT = (58, 48, 38)            # warm dark brown
    DIM = (138, 122, 102)         # warm muted
    BORDER = (192, 176, 152)      # tan border
    ACCENT = (148, 112, 82)       # warm brown accent
    FRAME = (172, 152, 126)       # frame color

    # Layout
    active_dims = [(name, data) for name, data in dim_scores.items()
                   if data.get("checks", 0) > 0]
    row_count = len(active_dims)
    W = _s(420)
    inner = _s(18)
    table_top = _s(146)
    row_h = _s(22)
    table_h = _s(24) + row_count * row_h + _s(10)
    H = table_top + table_h + _s(32)

    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # --- Double frame ---
    draw.rectangle((0, 0, W - 1, H - 1), outline=FRAME, width=_s(2))
    draw.rectangle((_s(5), _s(5), W - _s(6), H - _s(6)), outline=BORDER, width=1)

    # --- Title: centered between inner frame top and first rule ---
    rule_y = _s(40)
    title = "DESLOPPIFY SCORE"
    tw = draw.textlength(title, font=font_title)
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_h = title_bbox[3] - title_bbox[1]
    title_zone_top = _s(6)  # inner frame top
    title_y = title_zone_top + (rule_y - title_zone_top - title_h) // 2
    draw.text(((W - tw) / 2, title_y - title_bbox[1]), title, fill=TEXT, font=font_title)

    # --- Ornamental rule below title ---
    rule_margin = _s(40)
    _draw_rule_with_ornament(draw, rule_y, rule_margin, W - rule_margin, W // 2, BORDER, ACCENT)

    # --- Score panel ---
    panel_top = _s(48)
    panel_bot = _s(128)
    panel_margin = inner + _s(4)
    draw.rounded_rectangle(
        (panel_margin, panel_top, W - panel_margin, panel_bot),
        radius=_s(4), fill=BG_SCORE, outline=BORDER, width=1)

    # Measure text heights for vertical centering
    score_str = f"{main_score:.1f}"
    score_color = _score_color(main_score)
    score_bbox = draw.textbbox((0, 0), score_str, font=font_big)
    score_h = score_bbox[3] - score_bbox[1]

    strict_label = "strict"
    strict_val = f"{strict_score:.1f}"
    strict_label_bbox = draw.textbbox((0, 0), strict_label, font=font_strict_label)
    strict_val_bbox = draw.textbbox((0, 0), strict_val, font=font_strict_val)
    strict_h = max(strict_label_bbox[3] - strict_label_bbox[1],
                   strict_val_bbox[3] - strict_val_bbox[1])

    # Total content height: score + gap + strict line
    content_gap = _s(8)
    total_content_h = score_h + content_gap + strict_h
    panel_mid = (panel_top + panel_bot) // 2
    content_top = panel_mid - total_content_h // 2

    # Main score — centered in panel
    sw = draw.textlength(score_str, font=font_big)
    draw.text(((W - sw) / 2, content_top - score_bbox[1]), score_str, fill=score_color, font=font_big)

    # Strict label + value below main score
    sl_w = draw.textlength(strict_label, font=font_strict_label)
    sv_w = draw.textlength(strict_val, font=font_strict_val)
    gap = _s(5)
    strict_total_w = sl_w + gap + sv_w
    strict_x = (W - strict_total_w) / 2
    strict_y = content_top + score_h + content_gap
    # Baseline-align the two strict texts
    draw.text((strict_x, strict_y - strict_label_bbox[1]), strict_label, fill=DIM, font=font_strict_label)
    draw.text((strict_x + sl_w + gap, strict_y - strict_val_bbox[1]), strict_val, fill=_score_color(strict_score, muted=True), font=font_strict_val)

    # --- Ornamental rule above table ---
    rule2_y = table_top - _s(10)
    _draw_rule_with_ornament(draw, rule2_y, rule_margin, W - rule_margin, W // 2, BORDER, ACCENT)

    # --- Table area ---
    table_x1 = inner + _s(2)
    table_x2 = W - inner - _s(2)
    draw.rounded_rectangle(
        (table_x1, table_top, table_x2, table_top + table_h),
        radius=_s(4), fill=BG_TABLE, outline=BORDER, width=1)

    # --- Table content: measure total height, then center within table box ---
    col_name = table_x1 + _s(12)
    col_health = _s(262)
    col_strict = _s(342)

    header_bbox = draw.textbbox((0, 0), "Dimension", font=font_header)
    header_h = header_bbox[3] - header_bbox[1]
    rule_gap = _s(4)
    rows_gap = _s(10)  # gap between header underline and first row

    # Total table content: header + rule + gap + rows
    table_content_h = header_h + rule_gap + rows_gap + row_count * row_h
    table_bot = table_top + table_h
    table_content_top = table_top + (table_h - table_content_h) // 2 + _s(4)  # optical nudge

    header_y = table_content_top
    draw.text((col_name, header_y - header_bbox[1]), "Dimension", fill=DIM, font=font_header)
    draw.text((col_health, header_y - header_bbox[1]), "Health", fill=DIM, font=font_header)
    draw.text((col_strict, header_y - header_bbox[1]), "Strict", fill=DIM, font=font_header)

    # Header underline
    line_y = header_y + header_h + rule_gap
    draw.rectangle((col_name, line_y, table_x2 - _s(12), line_y), fill=BORDER)

    # --- Dimension rows with alternating tint ---
    # Measure actual row text height for vertical centering within bands
    sample_bbox = draw.textbbox((0, 0), "Xg", font=font_row)
    row_text_h = sample_bbox[3] - sample_bbox[1]
    row_text_offset = sample_bbox[1]  # top bearing

    y_band = line_y + rows_gap
    for i, (name, data) in enumerate(active_dims):
        band_top = y_band
        band_bot = y_band + row_h
        # Alternating background — full band height
        if i % 2 == 1:
            draw.rectangle((table_x1 + 1, band_top, table_x2 - 1, band_bot), fill=BG_ROW_ALT)
        # Center text vertically within band
        text_y = band_top + (row_h - row_text_h) // 2 - row_text_offset
        score = data.get("score", 100)
        strict = data.get("strict", score)
        draw.text((col_name, text_y), name, fill=TEXT, font=font_row)
        draw.text((col_health, text_y), f"{score:.1f}%", fill=_score_color(score), font=font_row)
        draw.text((col_strict, text_y), f"{strict:.1f}%", fill=_score_color(strict, muted=True), font=font_row)
        y_band += row_h

    # --- Footer: vertically centered between table bottom and inner frame ---
    footer = "github.com/peteromallet/desloppify"
    footer_bbox = draw.textbbox((0, 0), footer, font=font_tiny)
    footer_h = footer_bbox[3] - footer_bbox[1]
    footer_zone_top = table_bot
    footer_zone_bot = H - _s(6)  # inner frame bottom
    footer_y = footer_zone_top + (footer_zone_bot - footer_zone_top - footer_h) // 2
    fw = draw.textlength(footer, font=font_tiny)
    draw.text(((W - fw) / 2, footer_y - footer_bbox[1]), footer, fill=DIM, font=font_tiny)

    img.save(str(output_path), "PNG", optimize=True)
    return output_path


def get_badge_config(args) -> tuple[Path | None, bool]:
    """Resolve badge output path and whether badge generation is disabled.

    Returns (output_path, disabled). Checks CLI args, then env vars.
    """
    disabled = getattr(args, "no_badge", False) or os.environ.get("DESLOPPIFY_NO_BADGE", "").lower() in ("1", "true", "yes")
    if disabled:
        return None, True
    path_str = getattr(args, "badge_path", None) or os.environ.get("DESLOPPIFY_BADGE_PATH", "scorecard.png")
    path = Path(path_str)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path, False
