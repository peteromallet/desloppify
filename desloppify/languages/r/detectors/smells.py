"""R code smell detection."""

from __future__ import annotations

import re
from pathlib import Path

from desloppify.base.discovery.source import find_source_files
from .smells_catalog import R_SMELL_CHECKS, SEVERITY_ORDER

_R_STRING_RE = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'')
_R_COMMENT_RE = re.compile(r"#[^\n]*")
_FUNCTION_DEF_RE = re.compile(
    r"(?m)^\s*\w+\s*<-\s*function\s*\(",
)
_LIBRARY_IN_FN_RE = re.compile(
    r"(?<!\w)(?:library|require)\s*\(",
)
_LIBRARY_IN_FN_CHECK_ID = "library_in_function"


def _strip_r_comments(content: str) -> str:
    """Remove R comments while preserving string literals.
    
    Replaces string contents with placeholders, strips comments, then restores strings.
    """
    strings: list[str] = []
    
    def replace_string(match: re.Match) -> str:
        strings.append(match.group(0))
        return f"__STRING_{len(strings) - 1}__"
    
    content = _R_STRING_RE.sub(replace_string, content)
    content = _R_COMMENT_RE.sub("", content)
    
    for i, s in enumerate(strings):
        content = content.replace(f"__STRING_{i}__", s)
    
    return content


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
    """Detect library()/require() calls inside function bodies.
    
    Uses a simple heuristic: track function definitions and their brace depth.
    Only braces that appear after 'function(' on the same line or shortly after
    are considered function body braces.
    """
    if _LIBRARY_IN_FN_CHECK_ID not in smell_counts:
        return

    # Join content to handle multi-line function definitions
    content = stripped_content
    
    # Find all function definitions and their brace scopes
    fn_ranges: list[tuple[int, int]] = []  # (start_pos, end_pos) in content
    
    for match in _FUNCTION_DEF_RE.finditer(content):
        start = match.start()
        # Find the opening brace of the function body
        brace_start = content.find("{", start)
        if brace_start == -1:
            continue
        
        # Find matching closing brace
        depth = 1
        pos = brace_start + 1
        while pos < len(content) and depth > 0:
            if content[pos] == "{":
                depth += 1
            elif content[pos] == "}":
                depth -= 1
            pos += 1
        
        fn_ranges.append((brace_start, pos))
    
    # Check each library/require call to see if it's inside a function
    for match in _LIBRARY_IN_FN_RE.finditer(content):
        pos = match.start()
        for start, end in fn_ranges:
            if start < pos < end:
                line = content[:pos].count("\n") + 1
                smell_counts[_LIBRARY_IN_FN_CHECK_ID].append(
                    {
                        "file": filepath,
                        "line": line,
                        "content": _line_preview(raw_content, line),
                    }
                )
                break


def _find_r_files(path: Path) -> list[str]:
    """Find R source files using the framework's discovery system.
    
    Respects project-configured exclusion patterns.
    """
    return find_source_files(str(path), [".R", ".r"])


def _read_file(filepath: str) -> str | None:
    """Read file content, returning None on error."""
    try:
        return Path(filepath).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


__all__ = ["detect_smells"]
