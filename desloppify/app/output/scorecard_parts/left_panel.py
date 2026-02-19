"""Left panel drawing helpers for the scorecard."""

from __future__ import annotations

from desloppify.app.output.scorecard_parts.ornaments import draw_rule_with_ornament
from desloppify.app.output.scorecard_parts.theme import (
    ACCENT,
    BG,
    BG_SCORE,
    BORDER,
    DIM,
    TEXT,
    fmt_score,
    load_font,
    scale,
    score_color,
)


def _draw_left_panel_version(
    draw,
    *,
    center_x: int,
    baseline_y: int,
    version_text: str,
    version_bbox,
    version_width: float,
    font_version,
) -> None:
    draw.text(
        (center_x - version_width / 2, baseline_y - version_bbox[1]),
        version_text,
        fill=DIM,
        font=font_version,
    )


def _draw_left_panel_title(
    draw,
    *,
    center_x: int,
    title_y: int,
    title: str,
    title_bbox,
    title_width: float,
    font_title,
) -> None:
    draw.text(
        (center_x - title_width / 2, title_y - title_bbox[1]),
        title,
        fill=TEXT,
        font=font_title,
    )


def _draw_left_panel_score(
    draw,
    *,
    center_x: int,
    score_y: int,
    score_text: str,
    score_bbox,
    score_value: float,
    font_big,
) -> None:
    score_width = draw.textlength(score_text, font=font_big)
    draw.text(
        (center_x - score_width / 2, score_y - score_bbox[1]),
        score_text,
        fill=score_color(score_value),
        font=font_big,
    )


def _draw_left_panel_strict(
    draw,
    *,
    center_x: int,
    strict_y: int,
    strict_value: float,
    strict_text: str,
    strict_label_bbox,
    strict_value_bbox,
    font_strict_label,
    font_strict_val,
) -> None:
    strict_label = "strict"
    label_width = draw.textlength(strict_label, font=font_strict_label)
    value_width = draw.textlength(strict_text, font=font_strict_val)
    gap = scale(5)
    strict_x = center_x - (label_width + gap + value_width) / 2
    draw.text(
        (strict_x, strict_y - strict_label_bbox[1]),
        strict_label,
        fill=DIM,
        font=font_strict_label,
    )
    draw.text(
        (strict_x + label_width + gap, strict_y - strict_value_bbox[1]),
        strict_text,
        fill=score_color(strict_value, muted=True),
        font=font_strict_val,
    )


def _draw_left_panel_project_pill(
    draw,
    *,
    center_x: int,
    strict_y: int,
    strict_height: int,
    project_gap: int,
    project_pill_height: int,
    pill_pad_y: int,
    pill_pad_x: int,
    project_name: str,
    project_bbox,
    font_project,
) -> None:
    pill_top = strict_y + strict_height + project_gap
    project_y = pill_top + pill_pad_y
    project_width = draw.textlength(project_name, font=font_project)
    pill_left = center_x - project_width / 2 - pill_pad_x
    pill_right = center_x + project_width / 2 + pill_pad_x
    pill_bottom = pill_top + project_pill_height
    draw.rounded_rectangle(
        (pill_left, pill_top, pill_right, pill_bottom),
        radius=scale(3),
        fill=BG,
        outline=BORDER,
        width=1,
    )
    draw.text(
        (center_x - project_width / 2, project_y - project_bbox[1]),
        project_name,
        fill=DIM,
        font=font_project,
    )


def _left_panel_measurements(
    draw,
    *,
    main_score: float,
    strict_score: float,
    project_name: str,
    package_version: str,
) -> dict:
    font_version = load_font(9, mono=True)
    font_title = load_font(15, serif=True, bold=True)
    font_big = load_font(42, serif=True, bold=True)
    font_strict_label = load_font(12, serif=True)
    font_strict_val = load_font(19, serif=True, bold=True)
    font_project = load_font(9, serif=True)
    version_text = (
        f"v{package_version}"
        if package_version and package_version != "unknown"
        else "version unknown"
    )
    title = "DESLOPPIFY SCORE"
    score_text = fmt_score(main_score)
    strict_text = fmt_score(strict_score)
    version_bbox = draw.textbbox((0, 0), version_text, font=font_version)
    title_bbox = draw.textbbox((0, 0), title, font=font_title)
    score_bbox = draw.textbbox((0, 0), score_text, font=font_big)
    strict_label_bbox = draw.textbbox((0, 0), "strict", font=font_strict_label)
    strict_value_bbox = draw.textbbox((0, 0), strict_text, font=font_strict_val)
    project_bbox = draw.textbbox((0, 0), project_name, font=font_project)
    version_h = version_bbox[3] - version_bbox[1]
    title_h = title_bbox[3] - title_bbox[1]
    score_h = score_bbox[3] - score_bbox[1]
    strict_h = max(
        strict_label_bbox[3] - strict_label_bbox[1],
        strict_value_bbox[3] - strict_value_bbox[1],
    )
    project_h = project_bbox[3] - project_bbox[1]
    return {
        "font_version": font_version,
        "font_title": font_title,
        "font_big": font_big,
        "font_strict_label": font_strict_label,
        "font_strict_val": font_strict_val,
        "font_project": font_project,
        "version_text": version_text,
        "title": title,
        "score_text": score_text,
        "strict_text": strict_text,
        "version_bbox": version_bbox,
        "title_bbox": title_bbox,
        "score_bbox": score_bbox,
        "strict_label_bbox": strict_label_bbox,
        "strict_value_bbox": strict_value_bbox,
        "project_bbox": project_bbox,
        "version_h": version_h,
        "title_h": title_h,
        "score_h": score_h,
        "strict_h": strict_h,
        "project_h": project_h,
        "version_width": draw.textlength(version_text, font=font_version),
        "title_width": draw.textlength(title, font=font_title),
    }


def draw_left_panel(
    draw,
    main_score: float,
    strict_score: float,
    project_name: str,
    package_version: str,
    lp_left: int,
    lp_right: int,
    lp_top: int,
    lp_bot: int,
) -> None:
    measurements = _left_panel_measurements(
        draw,
        main_score=main_score,
        strict_score=strict_score,
        project_name=project_name,
        package_version=package_version,
    )
    font_version = measurements["font_version"]
    font_title = measurements["font_title"]
    font_big = measurements["font_big"]
    font_strict_label = measurements["font_strict_label"]
    font_strict_val = measurements["font_strict_val"]
    font_project = measurements["font_project"]
    version_text = measurements["version_text"]
    title = measurements["title"]
    score_text = measurements["score_text"]
    strict_text = measurements["strict_text"]
    version_bbox = measurements["version_bbox"]
    title_bbox = measurements["title_bbox"]
    score_bbox = measurements["score_bbox"]
    strict_label_bbox = measurements["strict_label_bbox"]
    strict_value_bbox = measurements["strict_value_bbox"]
    project_bbox = measurements["project_bbox"]
    version_h = measurements["version_h"]
    title_h = measurements["title_h"]
    score_h = measurements["score_h"]
    strict_h = measurements["strict_h"]
    project_h = measurements["project_h"]
    version_width = measurements["version_width"]
    title_width = measurements["title_width"]
    lp_center = (lp_left + lp_right) // 2

    draw.rounded_rectangle(
        (lp_left, lp_top, lp_right, lp_bot),
        radius=scale(4),
        fill=BG_SCORE,
        outline=BORDER,
        width=1,
    )

    version_gap = scale(4)
    ornament_gap = scale(7)
    score_gap = scale(6)
    project_gap = scale(8)
    pill_pad_y = scale(3)
    pill_pad_x = scale(8)
    project_pill_height = project_h + 2 * pill_pad_y
    total_h = (
        version_h
        + version_gap
        + title_h
        + ornament_gap
        + scale(6)
        + ornament_gap
        + score_h
        + score_gap
        + strict_h
        + project_gap
        + project_pill_height
    )
    base_y = (lp_top + lp_bot) // 2 - total_h // 2 + scale(3)
    _draw_left_panel_version(
        draw,
        center_x=lp_center,
        baseline_y=base_y,
        version_text=version_text,
        version_bbox=version_bbox,
        version_width=version_width,
        font_version=font_version,
    )
    title_y = base_y + version_h + version_gap
    _draw_left_panel_title(
        draw,
        center_x=lp_center,
        title_y=title_y,
        title=title,
        title_bbox=title_bbox,
        title_width=title_width,
        font_title=font_title,
    )
    rule_y = title_y + title_h + ornament_gap
    draw_rule_with_ornament(
        draw,
        rule_y,
        lp_left + scale(28),
        lp_right - scale(28),
        lp_center,
        BORDER,
        ACCENT,
    )
    score_y = rule_y + scale(6) + ornament_gap
    _draw_left_panel_score(
        draw,
        center_x=lp_center,
        score_y=score_y,
        score_text=score_text,
        score_bbox=score_bbox,
        score_value=main_score,
        font_big=font_big,
    )
    strict_y = score_y + score_h + score_gap
    _draw_left_panel_strict(
        draw,
        center_x=lp_center,
        strict_y=strict_y,
        strict_value=strict_score,
        strict_text=strict_text,
        strict_label_bbox=strict_label_bbox,
        strict_value_bbox=strict_value_bbox,
        font_strict_label=font_strict_label,
        font_strict_val=font_strict_val,
    )
    _draw_left_panel_project_pill(
        draw,
        center_x=lp_center,
        strict_y=strict_y,
        strict_height=strict_h,
        project_gap=project_gap,
        project_pill_height=project_pill_height,
        pill_pad_y=pill_pad_y,
        pill_pad_x=pill_pad_x,
        project_name=project_name,
        project_bbox=project_bbox,
        font_project=font_project,
    )
__all__ = ["draw_left_panel"]
