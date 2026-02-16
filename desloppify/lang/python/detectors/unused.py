"""Python unused detection via ruff (F401=unused imports, F841=unused vars)."""

import json
import re
import subprocess
from pathlib import Path

from ....utils import PROJECT_ROOT
from .... import utils as _utils_mod


def detect_unused(path: Path, category: str = "all") -> tuple[list[dict], int]:
    """Detect unused imports and variables using ruff.

    Falls back to pyflakes if ruff is not available.
    Returns (entries, total_statements_checked).
    """
    from ....utils import find_py_files
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
    select = []
    if category in ("all", "imports"):
        select.append("F401")
    if category in ("all", "vars"):
        select.append("F841")
    if not select:
        return []

    try:
        result = subprocess.run(
            ["ruff", "check", "--select", ",".join(select),
             "--output-format", "json", "--no-fix", str(path)],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    if not result.stdout.strip():
        return []

    try:
        diagnostics = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None

    entries = []
    name_re = re.compile(r"`([^`]+)`")

    for diagnostic in diagnostics:
        entry = _ruff_entry_from_diagnostic(diagnostic, category, name_re)
        if entry is not None:
            entries.append(entry)

    return entries


def _try_pyflakes(path: Path, category: str) -> list[dict] | None:
    """Fallback: try pyflakes for unused detection."""
    try:
        result = subprocess.run(
            ["pyflakes", str(path)],
            capture_output=True, text=True, cwd=PROJECT_ROOT, timeout=60,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

    entries = []
    # pyflakes output: file.py:line: 'foo' imported but unused
    import_re = re.compile(r"^(.+):(\d+):\d*\s+'([^']+)'\s+imported but unused")
    var_re = re.compile(r"^(.+):(\d+):\d*\s+local variable '([^']+)' is assigned to but never used")

    for line in (result.stdout + result.stderr).splitlines():
        entry = _parse_pyflakes_line(line, category, import_re, var_re)
        if entry is not None:
            entries.append(entry)

    return entries


def _is_excluded(filepath: str) -> bool:
    """Return True when filepath matches an active exclusion pattern."""
    patterns = _utils_mod._extra_exclusions
    if not patterns:
        return False
    return any(_utils_mod.matches_exclusion(filepath, ex) for ex in patterns)


def _extract_name(message: str, name_re: re.Pattern[str]) -> str:
    """Extract symbol name from a linter message."""
    match = name_re.search(message)
    if match:
        return match.group(1)
    return message.split()[0]


def _make_entry(filepath: str, line: int, col: int, name: str, category: str) -> dict:
    """Construct a normalized unused finding payload."""
    return {
        "file": filepath,
        "line": line,
        "col": col,
        "name": name,
        "category": category,
    }


def _ruff_entry_from_diagnostic(
    diagnostic: dict,
    category: str,
    name_re: re.Pattern[str],
) -> dict | None:
    """Convert a ruff diagnostic into an entry when it matches requested filters."""
    filepath = diagnostic.get("filename", "")
    if _is_excluded(filepath):
        return None

    cat = "imports" if diagnostic.get("code", "") == "F401" else "vars"
    if category != "all" and cat != category:
        return None

    name = _extract_name(diagnostic.get("message", ""), name_re)
    if name.startswith("_"):
        return None

    location = diagnostic.get("location", {})
    return _make_entry(
        filepath,
        location.get("row", 0),
        location.get("column", 0),
        name,
        cat,
    )


def _parse_pyflakes_line(
    line: str,
    category: str,
    import_re: re.Pattern[str],
    var_re: re.Pattern[str],
) -> dict | None:
    """Parse one pyflakes output line into an entry, if relevant."""
    import_match = import_re.match(line)
    if import_match and category in ("all", "imports"):
        filepath = import_match.group(1)
        if _is_excluded(filepath):
            return None
        return _make_entry(filepath, int(import_match.group(2)), 0, import_match.group(3), "imports")

    var_match = var_re.match(line)
    if var_match and category in ("all", "vars"):
        filepath = var_match.group(1)
        if _is_excluded(filepath):
            return None
        return _make_entry(filepath, int(var_match.group(2)), 0, var_match.group(3), "vars")

    return None
