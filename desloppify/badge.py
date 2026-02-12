"""Scorecard badge image generator — produces a visual health summary PNG."""

from __future__ import annotations

import os
import subprocess
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
    from PIL import ImageFont  # noqa: deferred — Pillow is optional

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


def _draw_vert_rule_with_ornament(draw, x: int, y1: int, y2: int, cy: int, line_fill, ornament_fill):
    """Draw a vertical rule with a diamond ornament in the center."""
    gap = _s(8)
    draw.rectangle((x, y1, x + 1, cy - gap), fill=line_fill)
    draw.rectangle((x, cy + gap, x + 1, y2), fill=line_fill)
    _draw_ornament(draw, x, cy, _s(3), ornament_fill)


def _get_project_name() -> str:
    """Get project name from git remote (owner/repo) or fall back to directory name."""
    try:
        url = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(PROJECT_ROOT), stderr=subprocess.DEVNULL, text=True,
        ).strip()
        # SSH: git@github.com:owner/repo.git  HTTPS: https://github.com/owner/repo.git
        if ":" in url and "@" in url:
            path = url.split(":")[-1]
        else:
            path = "/".join(url.split("/")[-2:])
        return path.removesuffix(".git")
    except (subprocess.CalledProcessError, FileNotFoundError, IndexError):
        return PROJECT_ROOT.name


# -- Palette used by all drawing functions --
_BG = (247, 240, 228)
_BG_SCORE = (240, 232, 217)
_BG_TABLE = (240, 233, 220)
_BG_ROW_ALT = (234, 226, 212)
_TEXT = (58, 48, 38)
_DIM = (138, 122, 102)
_BORDER = (192, 176, 152)
_ACCENT = (148, 112, 82)
_FRAME = (172, 152, 126)


def _draw_left_panel(draw, main_score: float, strict_score: float, project_name: str,
                     lp_left: int, lp_right: int, lp_top: int, lp_bot: int):
    """Draw the left panel: score panel background, title, score, strict, project name."""
    font_title = _load_font(15, serif=True, bold=True)
    font_big = _load_font(42, serif=True, bold=True)
    font_strict_label = _load_font(12, serif=True)
    font_strict_val = _load_font(19, serif=True, bold=True)
    font_project = _load_font(9, serif=True)

    lp_cx = (lp_left + lp_right) // 2

    draw.rounded_rectangle(
        (lp_left, lp_top, lp_right, lp_bot),
        radius=_s(4), fill=_BG_SCORE, outline=_BORDER, width=1)

    # Measure all elements
    title = "DESLOPPIFY SCORE"
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_h = title_bbox[3] - title_bbox[1]
    tw = draw.textlength(title, font=font_title)

    score_str = f"{main_score:.1f}"
    score_bbox = draw.textbbox((0, 0), score_str, font=font_big)
    score_h = score_bbox[3] - score_bbox[1]

    strict_label_bbox = draw.textbbox((0, 0), "strict", font=font_strict_label)
    strict_val_str = f"{strict_score:.1f}"
    strict_val_bbox = draw.textbbox((0, 0), strict_val_str, font=font_strict_val)
    strict_h = max(strict_label_bbox[3] - strict_label_bbox[1],
                   strict_val_bbox[3] - strict_val_bbox[1])

    proj_bbox = draw.textbbox((0, 0), project_name, font=font_project)
    proj_h = proj_bbox[3] - proj_bbox[1]

    # Stack: title → ornament rule → score → strict → project pill
    ornament_gap = _s(7)
    score_gap = _s(6)
    proj_gap = _s(8)
    pill_pad_y = _s(3)
    pill_pad_x = _s(8)
    proj_pill_h = proj_h + 2 * pill_pad_y
    total_h = (title_h + ornament_gap + _s(6) + ornament_gap +
               score_h + score_gap + strict_h + proj_gap + proj_pill_h)
    y0 = (lp_top + lp_bot) // 2 - total_h // 2 + _s(3)

    # Title
    draw.text((lp_cx - tw / 2, y0 - title_bbox[1]), title, fill=_TEXT, font=font_title)

    # Ornamental rule
    rule_y = y0 + title_h + ornament_gap
    rule_inset = _s(28)
    _draw_rule_with_ornament(draw, rule_y, lp_left + rule_inset, lp_right - rule_inset,
                             lp_cx, _BORDER, _ACCENT)

    # Main score
    score_y = rule_y + _s(6) + ornament_gap
    sw = draw.textlength(score_str, font=font_big)
    draw.text((lp_cx - sw / 2, score_y - score_bbox[1]), score_str,
              fill=_score_color(main_score), font=font_big)

    # Strict label + value
    strict_y = score_y + score_h + score_gap
    sl_w = draw.textlength("strict", font=font_strict_label)
    sv_w = draw.textlength(strict_val_str, font=font_strict_val)
    gap = _s(5)
    strict_x = lp_cx - (sl_w + gap + sv_w) / 2
    draw.text((strict_x, strict_y - strict_label_bbox[1]), "strict", fill=_DIM,
              font=font_strict_label)
    draw.text((strict_x + sl_w + gap, strict_y - strict_val_bbox[1]), strict_val_str,
              fill=_score_color(strict_score, muted=True), font=font_strict_val)

    # Project name in a subtle pill
    pill_top = strict_y + strict_h + proj_gap
    proj_y = pill_top + pill_pad_y
    pw = draw.textlength(project_name, font=font_project)
    pill_left = lp_cx - pw / 2 - pill_pad_x
    pill_right = lp_cx + pw / 2 + pill_pad_x
    pill_bot = pill_top + proj_pill_h
    draw.rounded_rectangle(
        (pill_left, pill_top, pill_right, pill_bot),
        radius=_s(3), fill=_BG, outline=_BORDER, width=1)
    draw.text((lp_cx - pw / 2, proj_y - proj_bbox[1]), project_name,
              fill=_DIM, font=font_project)



def _draw_right_panel(draw, active_dims: list, row_h: int,
                      table_x1: int, table_x2: int, table_top: int, table_bot: int):
    """Draw the right panel: dimension table with header, rows, alternating tints."""
    font_header = _load_font(10, mono=True)
    font_row = _load_font(11, mono=True)
    rule_gap = _s(4)
    rows_gap = _s(6)
    row_count = len(active_dims)

    draw.rounded_rectangle(
        (table_x1, table_top, table_x2, table_bot),
        radius=_s(4), fill=_BG_TABLE, outline=_BORDER, width=1)

    # Column positions
    col_name = table_x1 + _s(12)
    col_health = table_x2 - _s(118)
    col_strict = table_x2 - _s(52)

    # Measure header for centering
    header_bbox = draw.textbbox((0, 0), "Dimension", font=font_header)
    header_h = header_bbox[3] - header_bbox[1]

    # Center table content vertically
    table_content_h = header_h + rule_gap + rows_gap + row_count * row_h
    table_content_top = (table_top + table_bot) // 2 - table_content_h // 2 + _s(2)

    # Header row
    header_y = table_content_top
    draw.text((col_name, header_y - header_bbox[1]), "Dimension", fill=_DIM, font=font_header)
    draw.text((col_health, header_y - header_bbox[1]), "Health", fill=_DIM, font=font_header)
    draw.text((col_strict, header_y - header_bbox[1]), "Strict", fill=_DIM, font=font_header)

    # Header underline
    line_y = header_y + header_h + rule_gap
    draw.rectangle((col_name, line_y, table_x2 - _s(12), line_y), fill=_BORDER)

    # Dimension rows
    sample_bbox = draw.textbbox((0, 0), "Xg", font=font_row)
    row_text_h = sample_bbox[3] - sample_bbox[1]
    row_text_offset = sample_bbox[1]

    y_band = line_y + rows_gap
    for i, (name, data) in enumerate(active_dims):
        band_top = y_band
        band_bot = y_band + row_h
        if i % 2 == 1:
            draw.rectangle((table_x1 + 1, band_top, table_x2 - 1, band_bot), fill=_BG_ROW_ALT)
        text_y = band_top + (row_h - row_text_h) // 2 - row_text_offset + _s(1)
        score = data.get("score", 100)
        strict = data.get("strict", score)
        draw.text((col_name, text_y), name, fill=_TEXT, font=font_row)
        draw.text((col_health, text_y), f"{score:.1f}%", fill=_score_color(score), font=font_row)
        draw.text((col_strict, text_y), f"{strict:.1f}%",
                  fill=_score_color(strict, muted=True), font=font_row)
        y_band += row_h


def generate_scorecard(state: dict, output_path: str | Path) -> Path:
    """Render a landscape scorecard PNG from scan state. Returns the output path."""
    from PIL import Image, ImageDraw  # noqa: deferred — Pillow is optional

    output_path = Path(output_path)
    dim_scores = state.get("dimension_scores", {})
    obj_score = state.get("objective_score")
    obj_strict = state.get("objective_strict")

    main_score = obj_score if obj_score is not None else state.get("score", 0)
    strict_score = obj_strict if obj_strict is not None else state.get("strict_score", 0)

    project_name = _get_project_name()

    # Layout — landscape (wide), File health first
    active_dims = [(name, data) for name, data in dim_scores.items()
                   if data.get("checks", 0) > 0]
    active_dims.sort(key=lambda x: (0 if x[0] == "File health" else 1, x[0]))
    row_count = len(active_dims)
    row_h = _s(22)
    divider_x = _s(248)
    W = _s(620)
    frame_inset = _s(5)

    # Height driven by whichever side is taller
    rule_gap = _s(4)
    rows_gap = _s(6)
    table_content_h = _s(14) + rule_gap + rows_gap + row_count * row_h
    content_h = max(table_content_h + _s(28), _s(150))
    H = _s(12) + content_h

    img = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)

    # Double frame
    draw.rectangle((0, 0, W - 1, H - 1), outline=_FRAME, width=_s(2))
    draw.rectangle((frame_inset, frame_inset, W - frame_inset - 1, H - frame_inset - 1),
                   outline=_BORDER, width=1)

    content_top = frame_inset + _s(1)
    content_bot = H - frame_inset - _s(1)
    content_mid_y = (content_top + content_bot) // 2

    # Left panel: title + score + project name
    _draw_left_panel(draw, main_score, strict_score, project_name,
                     lp_left=frame_inset + _s(6), lp_right=divider_x - _s(8),
                     lp_top=content_top + _s(4), lp_bot=content_bot - _s(4))

    # Vertical divider with ornament
    _draw_vert_rule_with_ornament(draw, divider_x, content_top + _s(12), content_bot - _s(12),
                                  content_mid_y, _BORDER, _ACCENT)

    # Right panel: dimension table
    _draw_right_panel(draw, active_dims, row_h,
                      table_x1=divider_x + _s(10), table_x2=W - frame_inset - _s(6),
                      table_top=content_top + _s(4), table_bot=content_bot - _s(4))

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
