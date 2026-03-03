"""Go unused symbol detection via staticcheck."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.languages.go.extractors import find_go_files

# staticcheck checks we care about:
# U1000: unused code (functions, types, constants, variables)
# SA4006: value assigned and never used

_STATICCHECK_RE = re.compile(
    r"^(.+?):(\d+):(\d+):\s+(U1000|SA4006)\s+(.+)$"
)

_NAME_RE = re.compile(r"(?:\"([^\"]+)\"|(\S+))\s+is\s+(?:unused|assigned)")


def detect_unused(
    path: Path, category: str = "all"
) -> tuple[list[dict], int, bool]:
    """Detect unused symbols in Go code using staticcheck.

    Falls back gracefully if staticcheck is not installed.
    Returns (entries, total_files_checked, staticcheck_available).
    """
    total_files = len(find_go_files(path))

    result = _try_staticcheck(path, category)
    if result is not None:
        entries, available = result
        return entries, total_files, available

    # Graceful degradation: Go compiler already catches unused imports and locals
    return [], total_files, False


def _try_staticcheck(path: Path, category: str) -> tuple[list[dict], bool] | None:
    """Try staticcheck for unused detection.

    Returns (entries, tool_available) on success, None if staticcheck is
    not installed or timed out.
    """
    checks = []
    if category in ("all", "exports"):
        checks.append("U1000")
    if category in ("all", "vars"):
        checks.append("SA4006")
    if not checks:
        return [], True

    cmd = [
        "staticcheck",
        "-checks",
        ",".join(checks),
        "-f",
        "text",
        "./...",
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(path),
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    except UnicodeDecodeError:
        return [], True

    lines = (proc.stdout + proc.stderr).splitlines()
    return _parse_staticcheck_output(lines, category, str(path.resolve())), True


def _parse_staticcheck_output(
    lines: list[str], category: str, base_path: str
) -> list[dict]:
    """Parse staticcheck text output into entry dicts."""
    entries: list[dict] = []
    for line in lines:
        m = _STATICCHECK_RE.match(line)
        if not m:
            continue
        filepath = m.group(1)
        line_num = int(m.group(2))
        col = int(m.group(3))
        code = m.group(4)
        message = m.group(5)

        # Make path absolute if relative
        if not Path(filepath).is_absolute():
            filepath = str(Path(base_path) / filepath)

        # Skip test files
        if filepath.endswith("_test.go"):
            continue

        # Determine category
        cat = "vars" if code == "SA4006" else "exports"
        if category != "all" and cat != category:
            continue

        # Extract name from message
        name = _extract_name(message)
        if name.startswith("_"):
            continue

        entries.append({
            "file": filepath,
            "line": line_num,
            "col": col,
            "name": name,
            "category": cat,
        })
    return entries


def _extract_name(message: str) -> str:
    """Extract the symbol name from a staticcheck message."""
    m = _NAME_RE.search(message)
    if m:
        return m.group(1) or m.group(2)
    # Fallback: grab first quoted word or first word
    quote_m = re.search(r'"([^"]+)"', message)
    if quote_m:
        return quote_m.group(1)
    parts = message.split()
    return parts[0] if parts else message
