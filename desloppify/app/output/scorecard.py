"""Scorecard badge image generator — produces a visual health summary PNG."""

from __future__ import annotations

import importlib
import logging
import os
from importlib import metadata as importlib_metadata
from pathlib import Path

from desloppify.app.output.scorecard_parts.meta import (
    resolve_package_version,
    resolve_project_name,
)
from desloppify.app.output.scorecard_parts.dimensions import (
    collapse_elegance_dimensions,
    limit_scorecard_dimensions,
    prepare_scorecard_dimensions,
    resolve_scorecard_lang,
)
from desloppify.app.output.scorecard_parts.theme import (
    ACCENT,
    BG,
    BG_ROW_ALT,
    BG_SCORE,
    BG_TABLE,
    BORDER,
    DIM,
    FRAME,
    SCALE,
    TEXT,
    fmt_score,
    load_font,
    scale,
    score_color,
)
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.state import get_overall_score, get_strict_score

logger = logging.getLogger(__name__)


def generate_scorecard(state: dict, output_path: str | Path) -> Path:
    """Render a landscape scorecard PNG from scan state. Returns the output path."""
    image_mod = importlib.import_module("PIL.Image")  # deferred: optional dependency
    image_draw_mod = importlib.import_module("PIL.ImageDraw")  # deferred: optional dependency
    scorecard_draw_mod = importlib.import_module("desloppify.app.output.scorecard_parts.draw")  # deferred: depends on PIL

    output_path = Path(output_path)

    main_score = get_overall_score(state) or 0
    strict_score = get_strict_score(state) or 0

    project_name = resolve_project_name(PROJECT_ROOT)
    package_version = resolve_package_version(
        PROJECT_ROOT,
        version_getter=importlib_metadata.version,
        package_not_found_error=importlib_metadata.PackageNotFoundError,
    )

    # Layout — landscape (wide), File health first
    active_dims = prepare_scorecard_dimensions(state)
    row_count = len(active_dims)
    row_h = scale(20)
    width = scale(780)
    divider_x = scale(260)
    frame_inset = scale(5)

    cols = 2
    rows_per_col = (row_count + cols - 1) // cols
    table_content_h = scale(14) + scale(4) + scale(6) + rows_per_col * row_h
    content_h = max(table_content_h + scale(28), scale(150))
    height = scale(12) + content_h

    img = image_mod.new("RGB", (width, height), BG)
    draw = image_draw_mod.Draw(img)

    # Double frame
    draw.rectangle((0, 0, width - 1, height - 1), outline=FRAME, width=scale(2))
    draw.rectangle(
        (frame_inset, frame_inset, width - frame_inset - 1, height - frame_inset - 1),
        outline=BORDER,
        width=1,
    )

    content_top = frame_inset + scale(1)
    content_bot = height - frame_inset - scale(1)
    content_mid_y = (content_top + content_bot) // 2

    # Left panel: title + score + project name
    scorecard_draw_mod.draw_left_panel(
        draw,
        main_score,
        strict_score,
        project_name,
        package_version,
        lp_left=frame_inset + scale(11),
        lp_right=divider_x - scale(11),
        lp_top=content_top + scale(4),
        lp_bot=content_bot - scale(4),
    )

    # Vertical divider with ornament
    scorecard_draw_mod.draw_vert_rule_with_ornament(
        draw,
        divider_x,
        content_top + scale(12),
        content_bot - scale(12),
        content_mid_y,
        BORDER,
        ACCENT,
    )

    # Right panel: dimension table
    scorecard_draw_mod.draw_right_panel(
        draw,
        active_dims,
        row_h,
        table_x1=divider_x + scale(11),
        table_x2=width - frame_inset - scale(11),
        table_top=content_top + scale(4),
        table_bot=content_bot - scale(4),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
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
        disabled = os.environ.get("DESLOPPIFY_NO_BADGE", "").lower() in (
            "1",
            "true",
            "yes",
        )
    if disabled:
        return None, True

    path_str = (
        getattr(args, "badge_path", None)
        or cfg.get("badge_path")
        or os.environ.get("DESLOPPIFY_BADGE_PATH", "scorecard.png")
    )
    path = Path(path_str)
    # On Windows, "/tmp/foo.png" is root-anchored but drive-relative.
    # Treat any rooted path as user-intended absolute-like input.
    is_root_anchored = bool(path.root)
    if not path.is_absolute() and not is_root_anchored:
        path = PROJECT_ROOT / path
    return path, False


def _scorecard_ignore_warning(state: dict) -> str | None:
    """Return an ignore-suppression warning line for scorecard context."""
    info = state.get("ignore_integrity", {}) if isinstance(state, dict) else {}
    if not isinstance(info, dict):
        return None
    ignored = int(info.get("ignored", 0) or 0)
    if ignored <= 0:
        return None

    suppressed_pct = float(info.get("suppressed_pct", 0.0) or 0.0)
    rounded = round(suppressed_pct)
    level = "high" if suppressed_pct >= 50 else "moderate"
    return (
        f"Ignore suppression is {rounded}% ({level}) "
        f"across {ignored} findings."
    )


__all__ = [
    "ACCENT",
    "BG",
    "BG_ROW_ALT",
    "BG_SCORE",
    "BG_TABLE",
    "BORDER",
    "DIM",
    "FRAME",
    "SCALE",
    "TEXT",
    "collapse_elegance_dimensions",
    "fmt_score",
    "limit_scorecard_dimensions",
    "load_font",
    "resolve_scorecard_lang",
    "score_color",
    "generate_scorecard",
    "get_badge_config",
    "prepare_scorecard_dimensions",
]
