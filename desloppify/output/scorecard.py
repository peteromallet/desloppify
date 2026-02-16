"""Scorecard badge image generator — produces a visual health summary PNG."""

from __future__ import annotations

import os
from importlib import metadata as importlib_metadata
from pathlib import Path

from ..utils import PROJECT_ROOT
from ._scorecard_meta import resolve_package_version, resolve_project_name
_SCALE = 2


def _score_color(score: float, *, muted: bool = False) -> tuple[int, int, int]:
    """Color-code a score: deep sage >= 90, mustard 70-90, dusty rose < 70.

    muted=True returns a desaturated variant for secondary display (strict column).
    """
    if score >= 90:
        base = (68, 120, 68)  # deep sage
    elif score >= 70:
        base = (120, 140, 72)  # olive green
    else:
        base = (145, 155, 80)  # yellow-green
    if not muted:
        return base
    # Pastel orange shades for strict column
    if score >= 90:
        return (195, 160, 115)  # light sandy peach
    elif score >= 70:
        return (200, 148, 100)  # warm apricot
    return (195, 125, 95)  # soft coral


def _load_font(
    size: int, *, serif: bool = False, bold: bool = False, mono: bool = False
):
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


def _fmt_score(score: float) -> str:
    """Format score without .0 for whole numbers."""
    if score == int(score):
        return f"{int(score)}"
    return f"{score:.1f}"


def _get_project_name() -> str:
    """Get project name from GitHub API, git remote, or directory name."""
    return resolve_project_name(PROJECT_ROOT)


def _get_package_version() -> str:
    """Get package version for scorecard display."""
    return resolve_package_version(
        PROJECT_ROOT,
        version_getter=importlib_metadata.version,
        package_not_found_error=importlib_metadata.PackageNotFoundError,
    )

_BG = (247, 240, 228)
_BG_SCORE = (240, 232, 217)
_BG_TABLE = (240, 233, 220)
_BG_ROW_ALT = (234, 226, 212)
_TEXT = (58, 48, 38)
_DIM = (138, 122, 102)
_BORDER = (192, 176, 152)
_ACCENT = (148, 112, 82)
_FRAME = (172, 152, 126)


def _active_dimensions(dim_scores: dict) -> list[tuple[str, dict]]:
    """Return score rows to render, sorted with File health first."""
    rows = [
        (name, data)
        for name, data in dim_scores.items()
        if data.get("checks", 0) > 0
        and not (
            "subjective_assessment" in data.get("detectors", {})
            and data.get("score", 0) == 0
            and data.get("issues", 0) == 0
        )
    ]
    rows.sort(key=lambda x: (0 if x[0] == "File health" else 1, x[0]))
    return rows


def _compute_layout(row_count: int) -> dict[str, int]:
    """Compute badge geometry from active row count."""
    row_h = _s(20)
    width = _s(780)
    divider_x = _s(260)
    frame_inset = _s(5)

    cols = 2
    rows_per_col = (row_count + cols - 1) // cols
    table_content_h = _s(14) + _s(4) + _s(6) + rows_per_col * row_h
    content_h = max(table_content_h + _s(28), _s(150))
    height = _s(12) + content_h

    return {
        "row_h": row_h,
        "width": width,
        "height": height,
        "divider_x": divider_x,
        "frame_inset": frame_inset,
    }


def _draw_frame(draw, *, width: int, height: int, frame_inset: int) -> None:
    """Draw the badge outer frame."""
    draw.rectangle((0, 0, width - 1, height - 1), outline=_FRAME, width=_s(2))
    draw.rectangle(
        (frame_inset, frame_inset, width - frame_inset - 1, height - frame_inset - 1),
        outline=_BORDER,
        width=1,
    )


def _draw_panels(
    draw,
    *,
    active_dims: list[tuple[str, dict]],
    row_h: int,
    width: int,
    height: int,
    divider_x: int,
    frame_inset: int,
    main_score: float,
    strict_score: float,
    project_name: str,
    package_version: str,
    ignore_warning: str | None,
) -> None:
    """Draw left score panel, divider, and right dimension table."""
    from ._scorecard_left_panel import draw_left_panel
    from ._scorecard_right_panel import draw_right_panel
    from ._scorecard_draw import (
        _draw_rule_with_ornament,
        _draw_vert_rule_with_ornament,
    )

    content_top = frame_inset + _s(1)
    content_bot = height - frame_inset - _s(1)
    content_mid_y = (content_top + content_bot) // 2

    draw_left_panel(
        draw,
        main_score=main_score,
        strict_score=strict_score,
        project_name=project_name,
        package_version=package_version,
        ignore_warning=ignore_warning,
        lp_left=frame_inset + _s(11),
        lp_right=divider_x - _s(11),
        lp_top=content_top + _s(4),
        lp_bot=content_bot - _s(4),
        draw_rule_with_ornament_fn=_draw_rule_with_ornament,
    )
    _draw_vert_rule_with_ornament(
        draw,
        divider_x,
        content_top + _s(12),
        content_bot - _s(12),
        content_mid_y,
        _BORDER,
        _ACCENT,
    )
    draw_right_panel(
        draw,
        active_dims=active_dims,
        row_h=row_h,
        table_x1=divider_x + _s(11),
        table_x2=width - frame_inset - _s(11),
        table_top=content_top + _s(4),
        table_bot=content_bot - _s(4),
    )


def generate_scorecard(state: dict, output_path: str | Path) -> Path:
    """Render a landscape scorecard PNG from scan state. Returns the output path."""
    from PIL import Image, ImageDraw  # noqa: deferred — Pillow is optional
    from ..state import get_overall_score, get_strict_score

    output_path = Path(output_path)
    main_score = get_overall_score(state) or 0
    strict_score = get_strict_score(state) or 0

    active_dims = _active_dimensions(state.get("dimension_scores", {}))
    layout = _compute_layout(len(active_dims))

    img = Image.new("RGB", (layout["width"], layout["height"]), _BG)
    draw = ImageDraw.Draw(img)
    _draw_frame(draw, width=layout["width"], height=layout["height"], frame_inset=layout["frame_inset"])
    _draw_panels(
        draw,
        active_dims=active_dims,
        row_h=layout["row_h"],
        width=layout["width"],
        height=layout["height"],
        divider_x=layout["divider_x"],
        frame_inset=layout["frame_inset"],
        main_score=main_score,
        strict_score=strict_score,
        project_name=_get_project_name(),
        package_version=_get_package_version(),
        ignore_warning=_scorecard_ignore_warning(state),
    )
    img.save(str(output_path), "PNG", optimize=True)
    return output_path


def get_badge_config(args, config: dict | None = None) -> tuple[Path | None, bool]:
    """Resolve badge output path and whether badge generation is disabled.

    Returns (output_path, disabled). Checks CLI args, then config, then env vars.
    """
    cfg = config or {}
    disabled = getattr(args, "no_badge", False)
    if not disabled:
        disabled = not cfg.get("generate_scorecard", True)
    if not disabled:
        disabled = os.environ.get(
            "DESLOPPIFY_NO_BADGE", ""
        ).lower() in ("1", "true", "yes")
    if disabled:
        return None, True
    path_str = (getattr(args, "badge_path", None)
                or cfg.get("badge_path")
                or os.environ.get("DESLOPPIFY_BADGE_PATH", "scorecard.png"))
    path = Path(path_str)
    # On Windows, "/tmp/foo.png" is root-anchored but drive-relative.
    # Treat any rooted path as user-intended absolute-like input.
    is_root_anchored = bool(path.root)
    if not path.is_absolute() and not is_root_anchored:
        path = PROJECT_ROOT / path
    return path, False


def _scorecard_ignore_warning(state: dict) -> str | None:
    """Return warning text for the left panel when ignore suppression is high."""
    integrity = state.get("ignore_integrity", {}) or {}
    ignored = int(integrity.get("ignored", 0) or 0)
    suppressed_pct = float(integrity.get("suppressed_pct", 0.0) or 0.0)
    if ignored <= 0:
        return None
    if suppressed_pct >= 50:
        return f"Ignore suppression high: {suppressed_pct:.0f}% hidden"
    if suppressed_pct >= 30:
        return f"Ignore suppression: {suppressed_pct:.0f}% hidden"
    return None
