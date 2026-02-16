"""Scorecard badge image generator — produces a visual health summary PNG."""

from __future__ import annotations

import os
import re
import subprocess
from importlib import metadata as importlib_metadata
from pathlib import Path

from ..utils import PROJECT_ROOT

# Render at 2x for retina/high-DPI crispness
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
    """Get project name from GitHub API, git remote, or directory name.

    Tries `gh` CLI first for the canonical owner/repo (handles renames and
    transfers). Falls back to parsing the git remote URL, then directory name.
    """
    # Try gh CLI for canonical name (handles username renames, repo transfers)
    try:
        name = subprocess.check_output(
            ["gh", "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            cwd=str(PROJECT_ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
        if "/" in name:
            return name
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        subprocess.TimeoutExpired,
    ):
        pass

    # Fall back to git remote URL parsing
    try:
        url = subprocess.check_output(
            ["git", "config", "--get", "remote.origin.url"],
            cwd=str(PROJECT_ROOT),
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
        # SSH: git@github.com:owner/repo.git
        # HTTPS: https://github.com/owner/repo.git
        # HTTPS+token: https://TOKEN@github.com/owner/repo.git
        if url.startswith("git@") and ":" in url:
            path = url.split(":")[-1]
        else:
            path = "/".join(url.split("/")[-2:])
        return path.removesuffix(".git")
    except (
        subprocess.CalledProcessError,
        FileNotFoundError,
        IndexError,
        subprocess.TimeoutExpired,
    ):
        return PROJECT_ROOT.name


def _get_package_version() -> str:
    """Get package version for scorecard display.

    Prefers installed package metadata. Falls back to parsing local
    `pyproject.toml` when running from source without an installed package.
    """
    try:
        return importlib_metadata.version("desloppify")
    except importlib_metadata.PackageNotFoundError:
        pass

    pyproject_path = PROJECT_ROOT / "pyproject.toml"
    try:
        text = pyproject_path.read_text(encoding="utf-8")
        match = re.search(r'^\s*version\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
        if match:
            return match.group(1)
    except OSError:
        pass

    return "unknown"


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


def generate_scorecard(state: dict, output_path: str | Path) -> Path:
    """Render a landscape scorecard PNG from scan state. Returns the output path."""
    from PIL import Image, ImageDraw  # noqa: deferred — Pillow is optional
    from ._scorecard_draw import (  # noqa: deferred — avoids circular import
        _draw_left_panel,
        _draw_right_panel,
        _draw_vert_rule_with_ornament,
    )

    output_path = Path(output_path)
    dim_scores = state.get("dimension_scores", {})
    from ..state import get_overall_score, get_strict_score
    main_score = get_overall_score(state) or 0
    strict_score = get_strict_score(state) or 0

    project_name = _get_project_name()
    package_version = _get_package_version()

    # Layout — landscape (wide), File health first
    # Exclude unassessed subjective dimensions (score=0, issues=0) — they're placeholders
    active_dims = [
        (name, data) for name, data in dim_scores.items()
        if data.get("checks", 0) > 0
        and not (
            "subjective_assessment" in data.get("detectors", {})
            and data.get("score", 0) == 0
            and data.get("issues", 0) == 0
        )
    ]
    active_dims.sort(key=lambda x: (0 if x[0] == "File health" else 1, x[0]))
    row_count = len(active_dims)
    row_h = _s(20)
    W = _s(780)
    # Divider centered in the gap between left panel and right section
    # The space between them is from lp_right to table_x1
    # lp_right = divider_x - _s(9), table_x1 = divider_x + _s(9)
    # So divider is already centered mathematically at any divider_x
    # But we need to balance the visual space
    divider_x = _s(260)
    frame_inset = _s(5)

    # Height driven by 2-column layout
    cols = 2
    rows_per_col = (row_count + cols - 1) // cols
    rule_gap = _s(4)
    rows_gap = _s(6)
    table_content_h = _s(14) + rule_gap + rows_gap + rows_per_col * row_h
    content_h = max(table_content_h + _s(28), _s(150))
    H = _s(12) + content_h

    img = Image.new("RGB", (W, H), _BG)
    draw = ImageDraw.Draw(img)

    # Double frame
    draw.rectangle((0, 0, W - 1, H - 1), outline=_FRAME, width=_s(2))
    draw.rectangle(
        (frame_inset, frame_inset, W - frame_inset - 1, H - frame_inset - 1),
        outline=_BORDER,
        width=1,
    )

    content_top = frame_inset + _s(1)
    content_bot = H - frame_inset - _s(1)
    content_mid_y = (content_top + content_bot) // 2

    # Left panel: title + score + project name
    _draw_left_panel(
        draw,
        main_score,
        strict_score,
        project_name,
        package_version,
        lp_left=frame_inset + _s(11),  # Match outer margins
        lp_right=divider_x - _s(11),  # Match outer margins, center divider
        lp_top=content_top + _s(4),
        lp_bot=content_bot - _s(4),
    )

    # Vertical divider with ornament
    _draw_vert_rule_with_ornament(
        draw,
        divider_x,
        content_top + _s(12),
        content_bot - _s(12),
        content_mid_y,
        _BORDER,
        _ACCENT,
    )

    # Right panel: dimension table
    _draw_right_panel(
        draw,
        active_dims,
        row_h,
        table_x1=divider_x + _s(11),  # Match outer margins
        table_x2=W - frame_inset - _s(11),  # Match outer margins
        table_top=content_top + _s(4),
        table_bot=content_bot - _s(4),
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
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path, False
