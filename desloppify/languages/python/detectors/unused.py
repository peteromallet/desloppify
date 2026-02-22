"""Python unused detection via ruff (F401=unused imports, F841=unused vars)."""

import json
import re
import subprocess
from pathlib import Path

from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.file_discovery import (
    find_py_files,
    get_exclusions as _get_exclusions,
    matches_exclusion as _matches_exclusion,
)


def _selected_codes(category: str) -> list[str]:
    select = []
    if category in ("all", "imports"):
        select.append("F401")
    if category in ("all", "vars"):
        select.append("F841")
    return select


def _is_excluded(filepath: str, exclusions: tuple[str, ...]) -> bool:
    return bool(
        exclusions
        and any(_matches_exclusion(filepath, ex) for ex in exclusions)
    )


def _extract_unused_name(message: str, *, name_re: re.Pattern[str]) -> str:
    match = name_re.search(message)
    return match.group(1) if match else message.split()[0]


def _parse_ruff_diagnostics(
    diagnostics: list[dict],
    *,
    category: str,
    exclusions: tuple[str, ...],
) -> list[dict]:
    entries = []
    name_re = re.compile(r"`([^`]+)`")
    for diagnostic in diagnostics:
        code = diagnostic.get("code", "")
        filepath = diagnostic.get("filename", "")
        if _is_excluded(filepath, exclusions):
            continue

        # F401 in __init__.py = re-export, not dead code
        if code == "F401" and filepath.endswith("__init__.py"):
            continue

        cat = "imports" if code == "F401" else "vars"
        if category != "all" and cat != category:
            continue

        message = diagnostic.get("message", "")
        name = _extract_unused_name(message, name_re=name_re)
        if name.startswith("_"):
            continue

        location = diagnostic.get("location", {})
        entries.append(
            {
                "file": filepath,
                "line": location.get("row", 0),
                "col": location.get("column", 0),
                "name": name,
                "category": cat,
            }
        )
    return entries


def _parse_pyflakes_lines(
    lines: list[str],
    *,
    category: str,
    exclusions: tuple[str, ...],
) -> list[dict]:
    entries = []
    import_re = re.compile(r"^(.+):(\d+):\d*\s+'([^']+)'\s+imported but unused")
    var_re = re.compile(
        r"^(.+):(\d+):\d*\s+local variable '([^']+)' is assigned to but never used"
    )

    for line in lines:
        import_match = import_re.match(line)
        if import_match and category in ("all", "imports"):
            filepath = import_match.group(1)
            if _is_excluded(filepath, exclusions):
                continue
            # F401 in __init__.py = re-export, not dead code
            if filepath.endswith("__init__.py"):
                continue
            entries.append(
                {
                    "file": filepath,
                    "line": int(import_match.group(2)),
                    "col": 0,
                    "name": import_match.group(3),
                    "category": "imports",
                }
            )
            continue

        var_match = var_re.match(line)
        if var_match and category in ("all", "vars"):
            filepath = var_match.group(1)
            if _is_excluded(filepath, exclusions):
                continue
            entries.append(
                {
                    "file": filepath,
                    "line": int(var_match.group(2)),
                    "col": 0,
                    "name": var_match.group(3),
                    "category": "vars",
                }
            )
    return entries


def detect_unused(path: Path, category: str = "all") -> tuple[list[dict], int]:
    """Detect unused imports and variables using ruff.

    Falls back to pyflakes if ruff is not available.
    Returns (entries, total_statements_checked).
    """
    total_files = len(find_py_files(path))

    entries = _try_ruff(path, category)
    if entries is not None:
        return entries, total_files

    entries = _try_pyflakes(path, category)
    if entries is not None:
        return entries, total_files

    return [], total_files


def _try_ruff(path: Path, category: str) -> list[dict] | None:
    """Try ruff for unused detection."""
    select = _selected_codes(category)
    if not select:
        return []

    try:
        result = subprocess.run(
            [
                "ruff",
                "check",
                "--select",
                ",".join(select),
                "--output-format",
                "json",
                "--no-fix",
                str(path),
            ],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if not result.stdout.strip():
        return []

    try:
        diagnostics = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    exclusions = _get_exclusions()
    return _parse_ruff_diagnostics(
        diagnostics, category=category, exclusions=exclusions
    )


def _try_pyflakes(path: Path, category: str) -> list[dict] | None:
    """Fallback: try pyflakes for unused detection."""
    try:
        result = subprocess.run(
            ["pyflakes", str(path)],
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    exclusions = _get_exclusions()
    lines = (result.stdout + result.stderr).splitlines()
    return _parse_pyflakes_lines(lines, category=category, exclusions=exclusions)
