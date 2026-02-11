"""Python code smell detection."""

import re
from pathlib import Path

from ....utils import PROJECT_ROOT, find_py_files


SMELL_CHECKS = [
    {
        "id": "bare_except",
        "label": "Bare except clause (catches everything including SystemExit)",
        "pattern": r"^\s*except\s*:",
        "severity": "high",
    },
    {
        "id": "broad_except",
        "label": "Broad except (catches all Exceptions)",
        "pattern": r"^\s*except\s+Exception\s*(?:as\s+\w+\s*)?:",
        "severity": "medium",
    },
    {
        "id": "mutable_default",
        "label": "Mutable default argument (list/dict/set literal)",
        "pattern": r"def\s+\w+\([^)]*=\s*(?:\[\]|\{\}|set\(\))",
        "severity": "high",
    },
    {
        "id": "global_keyword",
        "label": "Global keyword usage",
        "pattern": r"^\s+global\s+\w+",
        "severity": "medium",
    },
    {
        "id": "star_import",
        "label": "Star import (from X import *)",
        "pattern": r"^from\s+\S+\s+import\s+\*",
        "severity": "medium",
    },
    {
        "id": "type_ignore",
        "label": "type: ignore comment",
        "pattern": r"#\s*type:\s*ignore",
        "severity": "medium",
    },
    {
        "id": "eval_exec",
        "label": "eval()/exec() usage",
        "pattern": r"\b(?:eval|exec)\s*\(",
        "severity": "high",
    },
    {
        "id": "magic_number",
        "label": "Magic numbers (>1000 in logic)",
        "pattern": r"(?:==|!=|>=?|<=?|[+\-*/])\s*\d{4,}",
        "severity": "low",
    },
    {
        "id": "todo_fixme",
        "label": "TODO/FIXME/HACK comments",
        "pattern": r"#\s*(?:TODO|FIXME|HACK|XXX)",
        "severity": "low",
    },
    {
        "id": "empty_except",
        "label": "Empty except block (except: pass)",
        # Detected separately (multi-line)
        "pattern": None,
        "severity": "high",
    },
    {
        "id": "swallowed_error",
        "label": "Catch block that only logs (swallowed error)",
        # Detected separately (multi-line)
        "pattern": None,
        "severity": "high",
    },
]


def _match_is_in_string(line: str, match_start: int) -> bool:
    """Check if a regex match position falls inside a string literal.

    Algorithm: linear scan from position 0, maintaining an `in_string` state
    that tracks the current quote delimiter (None, ', ", ''', or \"\"\"). Handles
    raw/byte/f-string prefixes (r/b/f before quote), backslash escapes, and
    triple-quote open/close. Comments (#) are treated as "in string" since
    matches there aren't real code. Returns the state when reaching match_start.
    """
    i = 0
    in_string = None  # None or the quote character/sequence
    while i < len(line):
        if i == match_start:
            return in_string is not None

        ch = line[i]
        if in_string is None:
            # Check for comment - everything after # is not code
            if ch == "#":
                # match_start is after # so it's in a comment (not a string,
                # but also not real code) - treat as "in string" to skip it
                return True
            # Check for triple quotes first
            triple = line[i : i + 3]
            if triple in ('"""', "'''"):
                in_string = triple
                i += 3
                continue
            # Check for raw string prefix before a quote
            if ch in ("r", "b", "f") and i + 1 < len(line) and line[i + 1] in ('"', "'"):
                # Prefix char - advance to the quote
                i += 1
                ch = line[i]
            if ch in ('"', "'"):
                in_string = ch
                i += 1
                continue
        else:
            # Inside a string - look for the closing delimiter
            if ch == "\\" and i + 1 < len(line):
                i += 2  # skip escaped char
                continue
            if in_string in ('"""', "'''"):
                if line[i : i + 3] == in_string:
                    in_string = None
                    i += 3
                    continue
            elif ch == in_string:
                in_string = None
                i += 1
                continue
        i += 1

    # If match_start is at or past end of line, check current state
    return in_string is not None


def detect_smells(path: Path) -> tuple[list[dict], int]:
    """Detect Python code smell patterns.

    Returns (entries, total_files_checked).
    """
    smell_counts: dict[str, list[dict]] = {s["id"]: [] for s in SMELL_CHECKS}
    files = find_py_files(path)

    for filepath in files:
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            content = p.read_text()
            lines = content.splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        # Regex-based smells
        for check in SMELL_CHECKS:
            if check["pattern"] is None:
                continue
            for i, line in enumerate(lines):
                m = re.search(check["pattern"], line)
                if m and not _match_is_in_string(line, m.start()):
                    smell_counts[check["id"]].append({
                        "file": filepath,
                        "line": i + 1,
                        "content": line.strip()[:100],
                    })

        # Empty except blocks (except ...: pass or except ...: ...)
        _detect_empty_except(filepath, lines, smell_counts)

        # Swallowed errors (except that only prints/logs)
        _detect_swallowed_errors(filepath, lines, smell_counts)

    severity_order = {"high": 0, "medium": 1, "low": 2}
    entries = []
    for check in SMELL_CHECKS:
        matches = smell_counts[check["id"]]
        if matches:
            entries.append({
                "id": check["id"],
                "label": check["label"],
                "severity": check["severity"],
                "count": len(matches),
                "files": len(set(m["file"] for m in matches)),
                "matches": matches[:50],
            })
    entries.sort(key=lambda e: (severity_order.get(e["severity"], 9), -e["count"]))
    return entries, len(files)


def _walk_except_blocks(lines: list[str]):
    """Yield (line_index, except_line_stripped, body_lines) for each except block.

    Iterates over lines looking for ``except ...:``, then collects the block's
    body by following indentation.  Callers apply their own check on the body.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        # Match both "except:" and "except <Something>:" / "except Something as e:"
        if not re.match(r"except\s*(?:\w|:)", stripped) and stripped != "except:":
            continue
        if not stripped.endswith(":"):
            continue

        indent = len(line) - len(line.lstrip())
        j = i + 1
        body_lines = []
        while j < len(lines):
            next_line = lines[j]
            next_stripped = next_line.strip()
            if next_stripped == "":
                j += 1
                continue
            next_indent = len(next_line) - len(next_line.lstrip())
            if next_indent <= indent:
                break
            body_lines.append(next_stripped)
            j += 1

        yield i, stripped, body_lines


def _is_broad_except(stripped: str) -> bool:
    """Check if an except clause catches broadly (bare, Exception, BaseException).

    Narrow catches like ``except ImportError:`` or ``except (KeyError, ValueError):``
    with an empty body are legitimate (intentional suppression of a specific error),
    so we should NOT flag those as smells.
    """
    if stripped == "except:":
        return True
    m = re.match(r"except\s+(\w+)", stripped)
    if m and m.group(1) in ("Exception", "BaseException"):
        return True
    return False


def _detect_empty_except(filepath: str, lines: list[str], smell_counts: dict[str, list]):
    """Find except blocks that just pass or have empty body.

    Only flags broad catches (bare except, Exception, BaseException).
    Narrow catches like ``except ImportError: pass`` are intentional and skipped.
    """
    for i, stripped, body_lines in _walk_except_blocks(lines):
        if (not body_lines or body_lines == ["pass"]) and _is_broad_except(stripped):
            smell_counts["empty_except"].append({
                "file": filepath,
                "line": i + 1,
                "content": stripped[:100],
            })


def _detect_swallowed_errors(filepath: str, lines: list[str], smell_counts: dict[str, list]):
    """Find except blocks that only print/log the error."""
    for i, stripped, body_lines in _walk_except_blocks(lines):
        if not body_lines:
            continue  # empty - caught by other detector

        # Check if all statements are just print/logging calls
        all_logging = all(
            re.match(r"(?:print|logging\.\w+|logger\.\w+|log\.\w+)\s*\(", stmt)
            for stmt in body_lines
        )
        if all_logging and len(body_lines) >= 1:
            smell_counts["swallowed_error"].append({
                "file": filepath,
                "line": i + 1,
                "content": stripped[:100],
            })
