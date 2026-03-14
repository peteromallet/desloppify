"""R code smell detection."""

from __future__ import annotations

import re
from pathlib import Path

from .smells_catalog import R_SMELL_CHECKS, SEVERITY_ORDER

_R_COMMENT_RE = re.compile(r"#[^\n]*")
_FUNCTION_DEF_RE = re.compile(
    r"(?m)^\s*\w+\s*<-\s*function\s*\(",
)
_LIBRARY_IN_FN_RE = re.compile(
    r"(?<!\w)(?:library|require)\s*\(",
)
_LIBRARY_IN_FN_CHECK_ID = "library_in_function"


def _strip_r_comments(content: str) -> str:
    """Remove R comments while preserving string literals."""
    return _R_COMMENT_RE.sub("", content)


def _line_number(content: str, offset: int) -> int:
    """Convert character offset to 1-based line number."""
    return content[:offset].count("\n") + 1


def _line_preview(content: str, line_number: int) -> str:
    """Get stripped preview of a specific line."""
    lines = content.splitlines()
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1].strip()[:100]
    return ""


def detect_smells(path: Path) -> tuple[list[dict], int]:
    """Detect R-specific code smell patterns across source files.

    Returns (entries, total_files_checked).
    """
    smell_counts: dict[str, list[dict]] = {
        check["id"]: [] for check in R_SMELL_CHECKS
    }
    total_files = 0

    for filepath in _find_r_files(path):
        total_files += 1
        content = _read_file(filepath)
        if content is None:
            continue

        stripped = _strip_r_comments(content)
        _scan_pattern_smells(filepath, content, stripped, smell_counts)
        _detect_library_in_function(filepath, content, stripped, smell_counts)

    entries: list[dict] = []
    for check in R_SMELL_CHECKS:
        matches = smell_counts[check["id"]]
        if not matches:
            continue
        entries.append(
            {
                "id": check["id"],
                "label": check["label"],
                "severity": check["severity"],
                "count": len(matches),
                "files": len({m["file"] for m in matches}),
                "matches": matches[:50],
            }
        )
    entries.sort(
        key=lambda e: (SEVERITY_ORDER.get(e["severity"], 9), -e["count"])
    )
    return entries, total_files


def _scan_pattern_smells(
    filepath: str,
    raw_content: str,
    stripped_content: str,
    smell_counts: dict[str, list[dict]],
) -> None:
    """Run regex-based smell checks for one file."""
    for check in R_SMELL_CHECKS:
        pattern = check.get("pattern")
        if pattern is None:
            continue
        for match in re.finditer(pattern, stripped_content):
            line = _line_number(stripped_content, match.start())
            smell_counts[check["id"]].append(
                {
                    "file": filepath,
                    "line": line,
                    "content": _line_preview(raw_content, line),
                }
            )


def _detect_library_in_function(
    filepath: str,
    raw_content: str,
    stripped_content: str,
    smell_counts: dict[str, list[dict]],
) -> None:
    """Detect library()/require() calls inside function bodies."""
    if _LIBRARY_IN_FN_CHECK_ID not in smell_counts:
        return

    lines = stripped_content.splitlines()
    fn_depth = 0
    for i, line in enumerate(lines):
        opens = line.count("{") - line.count("}")
        for _ in range(line.count("{")):
            fn_depth += 1
        for _ in range(line.count("}")):
            fn_depth = max(0, fn_depth - 1)

        if fn_depth > 0 and _LIBRARY_IN_FN_RE.search(line):
            smell_counts[_LIBRARY_IN_FN_CHECK_ID].append(
                {
                    "file": filepath,
                    "line": i + 1,
                    "content": _line_preview(raw_content, i + 1),
                }
            )


def _find_r_files(path: Path) -> list[str]:
    """Find R source files, skipping excluded directories."""
    excludes = {".Rhistory", ".RData", ".Rproj.user", "renv", "packrat"}
    files: list[str] = []
    for root, dirs, filenames in path.walk():
        dirs[:] = [d for d in dirs if d not in excludes]
        for fn in sorted(filenames):
            if fn.endswith((".R", ".r")) and not fn.startswith("."):
                files.append(str(root / fn))
    return files


def _read_file(filepath: str) -> str | None:
    """Read file content, returning None on error."""
    try:
        return Path(filepath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


__all__ = ["detect_smells"]
