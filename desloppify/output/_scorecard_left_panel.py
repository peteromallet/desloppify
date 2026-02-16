"""Left-panel renderer for the scorecard badge."""

from __future__ import annotations

from .scorecard import (
    _ACCENT,
    _BG,
    _BG_SCORE,
    _BORDER,
    _DIM,
    _TEXT,
    _fmt_score,
    _load_font,
    _s,
    _score_color,
)


def _measure_left_panel(
    draw,
    *,
    main_score: float,
    strict_score: float,
    project_name: str,
    package_version: str,
    ignore_warning: str | None,
    font_version,
    font_title,
    font_big,
    font_strict_label,
    font_strict_val,
    font_project,
    font_warning,
) -> dict:
    """Measure left-panel text blocks and computed layout offsets."""
    version_text = (
        f"v{package_version}"
        if package_version and package_version != "unknown"
        else "version unknown"
    )
    version_bbox = draw.textbbox((0, 0), version_text, font=font_version)
    version_h = version_bbox[3] - version_bbox[1]
    version_w = draw.textlength(version_text, font=font_version)

    title = "DESLOPPIFY SCORE"
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    title_h = title_bbox[3] - title_bbox[1]
    title_w = draw.textlength(title, font=font_title)

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

    warning_gap = _s(4)
    warning_bbox = None
    warning_h = 0
    if ignore_warning:
        warning_bbox = draw.textbbox((0, 0), ignore_warning, font=font_warning)
        warning_h = warning_bbox[3] - warning_bbox[1]

    version_gap = _s(4)
    ornament_gap = _s(7)
    score_gap = _s(6)
    proj_gap = _s(8)
    pill_pad_y = _s(3)
    pill_pad_x = _s(8)
    proj_pill_h = proj_h + 2 * pill_pad_y
    total_h = (
        version_h
        + version_gap
        + title_h
        + ornament_gap
        + _s(6)
        + ornament_gap
        + score_h
        + score_gap
        + strict_h
        + proj_gap
        + proj_pill_h
        + (warning_gap + warning_h if ignore_warning else 0)
    )

    return {
        "version_text": version_text,
        "version_bbox": version_bbox,
        "version_h": version_h,
        "version_w": version_w,
        "title": title,
        "title_bbox": title_bbox,
        "title_h": title_h,
        "title_w": title_w,
        "score_str": score_str,
        "score_bbox": score_bbox,
        "score_h": score_h,
        "strict_label_bbox": strict_label_bbox,
        "strict_val_str": strict_val_str,
        "strict_val_bbox": strict_val_bbox,
        "strict_h": strict_h,
        "proj_bbox": proj_bbox,
        "warning_gap": warning_gap,
        "warning_bbox": warning_bbox,
        "version_gap": version_gap,
        "ornament_gap": ornament_gap,
        "score_gap": score_gap,
        "proj_gap": proj_gap,
        "pill_pad_y": pill_pad_y,
        "pill_pad_x": pill_pad_x,
        "proj_pill_h": proj_pill_h,
        "total_h": total_h,
    }


def _draw_left_panel_warning(
    draw,
    *,
    ignore_warning: str | None,
    warning_bbox,
    font_warning,
    lp_left: int,
    lp_right: int,
    lp_cx: int,
    pill_bot: int,
    warning_gap: int,
) -> None:
    if not ignore_warning or warning_bbox is None:
        return
    max_warn_w = (lp_right - lp_left) - _s(16)
    warning_text = ignore_warning
    while warning_text and draw.textlength(warning_text, font=font_warning) > max_warn_w:
        warning_text = warning_text[:-1]
    if warning_text != ignore_warning and len(warning_text) >= 3:
        warning_text = warning_text[:-3].rstrip() + "..."
    warning_w = draw.textlength(warning_text, font=font_warning)
    warn_y = pill_bot + warning_gap
    draw.text(
        (lp_cx - warning_w / 2, warn_y - warning_bbox[1]),
        warning_text,
        fill=_ACCENT,
        font=font_warning,
    )


def draw_left_panel(
    draw,
    *,
    main_score: float,
    strict_score: float,
    project_name: str,
    package_version: str,
    ignore_warning: str | None,
    lp_left: int,
    lp_right: int,
    lp_top: int,
    lp_bot: int,
    draw_rule_with_ornament_fn,
) -> None:
    """Draw left score panel with title, score, strict score, and project name."""
    font_version = _load_font(9, mono=True)
    font_title = _load_font(15, serif=True, bold=True)
    font_big = _load_font(42, serif=True, bold=True)
    font_strict_label = _load_font(12, serif=True)
    font_strict_val = _load_font(19, serif=True, bold=True)
    font_project = _load_font(9, serif=True)
    font_warning = _load_font(8, mono=True)
    lp_cx = (lp_left + lp_right) // 2

    draw.rounded_rectangle(
        (lp_left, lp_top, lp_right, lp_bot),
        radius=_s(4),
        fill=_BG_SCORE,
        outline=_BORDER,
        width=1,
    )

    metrics = _measure_left_panel(
        draw,
        main_score=main_score,
        strict_score=strict_score,
        project_name=project_name,
        package_version=package_version,
        ignore_warning=ignore_warning,
        font_version=font_version,
        font_title=font_title,
        font_big=font_big,
        font_strict_label=font_strict_label,
        font_strict_val=font_strict_val,
        font_project=font_project,
        font_warning=font_warning,
    )
    y0 = (lp_top + lp_bot) // 2 - metrics["total_h"] // 2 + _s(3)

    draw.text(
        (lp_cx - metrics["version_w"] / 2, y0 - metrics["version_bbox"][1]),
        metrics["version_text"],
        fill=_DIM,
        font=font_version,
    )

    title_y = y0 + metrics["version_h"] + metrics["version_gap"]
    draw.text(
        (lp_cx - metrics["title_w"] / 2, title_y - metrics["title_bbox"][1]),
        metrics["title"],
        fill=_TEXT,
        font=font_title,
    )

    rule_y = title_y + metrics["title_h"] + metrics["ornament_gap"]
    rule_inset = _s(28)
    draw_rule_with_ornament_fn(
        draw,
        rule_y,
        lp_left + rule_inset,
        lp_right - rule_inset,
        lp_cx,
        _BORDER,
        _ACCENT,
    )

    score_y = rule_y + _s(6) + metrics["ornament_gap"]
    score_w = draw.textlength(metrics["score_str"], font=font_big)
    draw.text(
        (lp_cx - score_w / 2, score_y - metrics["score_bbox"][1]),
        metrics["score_str"],
        fill=_score_color(main_score),
        font=font_big,
    )

    strict_y = score_y + metrics["score_h"] + metrics["score_gap"]
    sl_w = draw.textlength("strict", font=font_strict_label)
    sv_w = draw.textlength(metrics["strict_val_str"], font=font_strict_val)
    gap = _s(5)
    strict_x = lp_cx - (sl_w + gap + sv_w) / 2
    draw.text(
        (strict_x, strict_y - metrics["strict_label_bbox"][1]),
        "strict",
        fill=_DIM,
        font=font_strict_label,
    )
    draw.text(
        (strict_x + sl_w + gap, strict_y - metrics["strict_val_bbox"][1]),
        metrics["strict_val_str"],
        fill=_score_color(strict_score, muted=True),
        font=font_strict_val,
    )

    pill_top = strict_y + metrics["strict_h"] + metrics["proj_gap"]
    proj_y = pill_top + metrics["pill_pad_y"]
    pw = draw.textlength(project_name, font=font_project)
    pill_left = lp_cx - pw / 2 - metrics["pill_pad_x"]
    pill_right = lp_cx + pw / 2 + metrics["pill_pad_x"]
    pill_bot = pill_top + metrics["proj_pill_h"]
    draw.rounded_rectangle(
        (pill_left, pill_top, pill_right, pill_bot),
        radius=_s(3),
        fill=_BG,
        outline=_BORDER,
        width=1,
    )
    draw.text(
        (lp_cx - pw / 2, proj_y - metrics["proj_bbox"][1]),
        project_name,
        fill=_DIM,
        font=font_project,
    )

    _draw_left_panel_warning(
        draw,
        ignore_warning=ignore_warning,
        warning_bbox=metrics["warning_bbox"],
        font_warning=font_warning,
        lp_left=lp_left,
        lp_right=lp_right,
        lp_cx=lp_cx,
        pill_bot=pill_bot,
        warning_gap=metrics["warning_gap"],
    )
