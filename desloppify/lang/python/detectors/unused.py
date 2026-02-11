"""Python unused detection via ruff (F401=unused imports, F841=unused vars)."""

import json
import re
import subprocess
from pathlib import Path

from ....utils import PROJECT_ROOT, _extra_exclusions


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

    for d in diagnostics:
        code = d.get("code", "")
        message = d.get("message", "")
        filepath = d.get("filename", "")
        if _extra_exclusions and any(ex in filepath for ex in _extra_exclusions):
            continue
        location = d.get("location", {})
        line = location.get("row", 0)

        # Extract name from message like "`foo` imported but unused"
        m = name_re.search(message)
        name = m.group(1) if m else message.split()[0]

        cat = "imports" if code == "F401" else "vars"
        if category != "all" and cat != category:
            continue

        # Skip _ prefixed names
        if name.startswith("_"):
            continue

        entries.append({
            "file": filepath,
            "line": line,
            "col": location.get("column", 0),
            "name": name,
            "category": cat,
        })

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
        m = import_re.match(line)
        if m and category in ("all", "imports"):
            filepath = m.group(1)
            if _extra_exclusions and any(ex in filepath for ex in _extra_exclusions):
                continue
            entries.append({
                "file": filepath,
                "line": int(m.group(2)),
                "col": 0,
                "name": m.group(3),
                "category": "imports",
            })
            continue

        m = var_re.match(line)
        if m and category in ("all", "vars"):
            filepath = m.group(1)
            if _extra_exclusions and any(ex in filepath for ex in _extra_exclusions):
                continue
            entries.append({
                "file": filepath,
                "line": int(m.group(2)),
                "col": 0,
                "name": m.group(3),
                "category": "vars",
            })

    return entries
