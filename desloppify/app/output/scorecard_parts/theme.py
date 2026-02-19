"""Visual style primitives shared by scorecard rendering modules."""

from __future__ import annotations

import importlib
import logging

from desloppify.core.fallbacks import log_best_effort_failure

# Render at 2x for retina/high-DPI crispness
SCALE = 2

logger = logging.getLogger(__name__)


def score_color(score: float, *, muted: bool = False) -> tuple[int, int, int]:
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
    if score >= 70:
        return (200, 148, 100)  # warm apricot
    return (195, 125, 95)  # soft coral


def load_font(
    size: int, *, serif: bool = False, bold: bool = False, mono: bool = False
):
    """Load a font with cross-platform fallback."""
    image_font_mod = importlib.import_module("PIL.ImageFont")

    size = size * SCALE
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
            return image_font_mod.truetype(path, size)
        except OSError as exc:
            log_best_effort_failure(
                logger, f"load scorecard font candidate {path}", exc
            )
            continue
    return image_font_mod.load_default()


def scale(v: int | float) -> int:
    """Scale a layout value."""
    return int(v * SCALE)


def fmt_score(score: float) -> str:
    """Format score without .0 for whole numbers."""
    if score == int(score):
        return f"{int(score)}"
    return f"{score:.1f}"


# -- Palette used by all drawing functions --
BG = (247, 240, 228)
BG_SCORE = (240, 232, 217)
BG_TABLE = (240, 233, 220)
BG_ROW_ALT = (234, 226, 212)
TEXT = (58, 48, 38)
DIM = (138, 122, 102)
BORDER = (192, 176, 152)
ACCENT = (148, 112, 82)
FRAME = (172, 152, 126)


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
    "fmt_score",
    "load_font",
    "scale",
    "score_color",
]
