"""Go code smell detection."""

from __future__ import annotations

import re
import logging
from pathlib import Path
from typing import Any

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.languages.go.extractors import (
    find_go_files,
    _FUNC_DECL_RE,
    _find_body_brace,
    _find_matching_brace,
)

logger = logging.getLogger(__name__)


GO_SMELL_CHECKS: list[dict[str, Any]] = [
    {
        "id": "ignored_error",
        "label": "Ignored error value",
        "pattern": r"_\s*(?:,\s*_\s*)?=\s*\w+.*(?:err|Err)",
        "severity": "high",
    },
    {
        "id": "ignored_error",
        "label": "Ignored error value",
        "pattern": r"_\s*=\s*\w+\.\w+\(",
        "severity": "high",
    },
    {
        "id": "naked_return",
        "label": "Naked return (no values)",
        "pattern": r"^\s*return\s*$",
        "severity": "medium",
    },
    {
        "id": "empty_error_branch",
        "label": "Empty error-handling branch",
        "pattern": None,
        "severity": "high",
    },
    {
        "id": "panic_in_lib",
        "label": "panic() in library package",
        "pattern": None,
        "severity": "high",
    },
    {
        "id": "init_side_effects",
        "label": "func init() with side effects",
        "pattern": None,
        "severity": "medium",
    },
    {
        "id": "global_var",
        "label": "Package-level var declaration",
        "pattern": r"^var\s+\w+",
        "severity": "low",
    },
    {
        "id": "defer_in_loop",
        "label": "defer inside a for loop",
        "pattern": None,
        "severity": "high",
    },
    {
        "id": "goroutine_closure_capture",
        "label": "Goroutine captures loop variable",
        "pattern": None,
        "severity": "high",
    },
    {
        "id": "string_int_conv",
        "label": "string(int) conversion (may be []byte/rune)",
        "pattern": r"string\(\s*[a-zA-Z_]\w*\s*\)",
        "severity": "medium",
    },
    {
        "id": "hardcoded_url",
        "label": "Hardcoded URL in source code",
        "pattern": r"""(?:['\"]|`)https?://[^\s'\"` ]+(?:['\"]|`)""",
        "severity": "medium",
    },
    {
        "id": "todo_fixme",
        "label": "TODO/FIXME/HACK comments",
        "pattern": r"//\s*(?:TODO|FIXME|HACK|XXX)",
        "severity": "low",
    },
    {
        "id": "magic_number",
        "label": "Magic number in logic",
        "pattern": r"(?:==|!=|>=?|<=?|[+\-*/])\s*\d{4,}",
        "severity": "low",
    },
    {
        "id": "monster_function",
        "label": "Monster function (>100 LOC)",
        "pattern": None,
        "severity": "high",
    },
    {
        "id": "dead_function",
        "label": "Dead function (empty body)",
        "pattern": None,
        "severity": "medium",
    },
    {
        "id": "unreachable_code",
        "label": "Unreachable code after return/panic/os.Exit",
        "pattern": None,
        "severity": "medium",
    },
]

# De-duplicate check IDs for smell_counts initialization — some IDs appear
# twice (ignored_error has two regex patterns).
_UNIQUE_IDS = list(dict.fromkeys(c["id"] for c in GO_SMELL_CHECKS))


# ---------------------------------------------------------------------------
# Multi-line helpers
# ---------------------------------------------------------------------------

def _detect_empty_error_branch(
    filepath: str, lines: list[str], smell_counts: dict[str, list[dict]]
) -> None:
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not re.match(r"if\s+err\s*!=\s*nil\s*\{", stripped):
            continue
        for j in range(i + 1, min(i + 3, len(lines))):
            next_stripped = lines[j].strip()
            if not next_stripped:
                continue
            if next_stripped == "}":
                smell_counts["empty_error_branch"].append(
                    {"file": filepath, "line": i + 1, "content": stripped[:100]}
                )
            break


def _detect_panic_in_lib(
    filepath: str,
    content: str,
    lines: list[str],
    smell_counts: dict[str, list[dict]],
) -> None:
    pkg_match = re.search(r"^package\s+(\w+)", content, re.MULTILINE)
    if not pkg_match or pkg_match.group(1) == "main":
        return
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if re.search(r"\bpanic\s*\(", stripped):
            smell_counts["panic_in_lib"].append(
                {"file": filepath, "line": i + 1, "content": stripped[:100]}
            )


def _detect_init_side_effects(
    filepath: str,
    content: str,
    lines: list[str],
    smell_counts: dict[str, list[dict]],
) -> None:
    side_effect_patterns = [
        r"\bhttp\.\w+",
        r"\bos\.(Open|Create|Remove|Mkdir|Stat|ReadFile|WriteFile)",
        r"\bexec\.Command",
        r"\bnet\.Dial",
        r"\bsql\.Open",
        r"\bioutil\.Read",
    ]
    for match in _FUNC_DECL_RE.finditer(content):
        if match.group(1) != "init":
            continue
        brace_pos = _find_body_brace(content, match.end())
        if brace_pos is None:
            continue
        end = _find_matching_brace(content, brace_pos)
        if end is None:
            continue
        body = content[brace_pos + 1 : end]
        for pat in side_effect_patterns:
            if re.search(pat, body):
                start_line = content.count("\n", 0, match.start()) + 1
                smell_counts["init_side_effects"].append(
                    {"file": filepath, "line": start_line, "content": "func init() with side effects"}
                )
                break


def _detect_defer_in_loop(
    filepath: str, lines: list[str], smell_counts: dict[str, list[dict]]
) -> None:
    in_for = False
    for_depth = 0
    brace_depth = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if re.match(r"\bfor\b", stripped) and "{" in stripped:
            if not in_for:
                in_for = True
                for_depth = brace_depth
        brace_depth += stripped.count("{") - stripped.count("}")
        if in_for and brace_depth <= for_depth:
            in_for = False
        if in_for and re.match(r"\s*defer\b", line):
            smell_counts["defer_in_loop"].append(
                {"file": filepath, "line": i + 1, "content": stripped[:100]}
            )


def _detect_goroutine_closure(
    filepath: str, lines: list[str], smell_counts: dict[str, list[dict]]
) -> None:
    """Find goroutine closures inside for loops that capture loop variables."""
    in_for = False
    for_depth = 0
    brace_depth = 0
    for_vars: list[str] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        for_match = re.match(
            r"for\s+(?:(\w+)(?:\s*,\s*(\w+))?\s*:?=|_\s*,\s*(\w+)\s*:?=)", stripped
        )
        if for_match and "{" in stripped:
            if not in_for:
                in_for = True
                for_depth = brace_depth
                for_vars = [g for g in for_match.groups() if g]
        brace_depth += stripped.count("{") - stripped.count("}")
        if in_for and brace_depth <= for_depth:
            in_for = False
            for_vars = []
        if in_for and re.match(r"go\s+func\s*\(", stripped):
            # Check a few lines ahead for captured loop vars
            for j in range(i, min(i + 20, len(lines))):
                body_line = lines[j]
                for var in for_vars:
                    if re.search(rf"\b{re.escape(var)}\b", body_line) and j != i:
                        smell_counts["goroutine_closure_capture"].append(
                            {"file": filepath, "line": i + 1, "content": stripped[:100]}
                        )
                        # Only report once per goroutine
                        for_vars = []
                        break
                if not for_vars:
                    break


def _detect_monster_functions(
    filepath: str, content: str, smell_counts: dict[str, list[dict]]
) -> None:
    for match in _FUNC_DECL_RE.finditer(content):
        brace_pos = _find_body_brace(content, match.end())
        if brace_pos is None:
            continue
        end = _find_matching_brace(content, brace_pos)
        if end is None:
            continue
        start_line = content.count("\n", 0, match.start()) + 1
        end_line = content.count("\n", 0, end) + 1
        loc = end_line - start_line + 1
        if loc > 100:
            smell_counts["monster_function"].append(
                {
                    "file": filepath,
                    "line": start_line,
                    "content": f"func {match.group(1)} ({loc} LOC)",
                }
            )


def _detect_dead_functions(
    filepath: str, content: str, smell_counts: dict[str, list[dict]]
) -> None:
    for match in _FUNC_DECL_RE.finditer(content):
        brace_pos = _find_body_brace(content, match.end())
        if brace_pos is None:
            continue
        end = _find_matching_brace(content, brace_pos)
        if end is None:
            continue
        body = content[brace_pos + 1 : end].strip()
        body_clean = re.sub(r"//.*", "", body)
        body_clean = re.sub(r"/\*.*?\*/", "", body_clean, flags=re.DOTALL)
        if not body_clean.strip():
            start_line = content.count("\n", 0, match.start()) + 1
            smell_counts["dead_function"].append(
                {
                    "file": filepath,
                    "line": start_line,
                    "content": f"func {match.group(1)} (empty body)",
                }
            )


def _detect_unreachable_code(
    filepath: str, lines: list[str], smell_counts: dict[str, list[dict]]
) -> None:
    """Find code after return/panic/os.Exit that is not a closing brace or blank."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("//"):
            continue
        if re.match(r"(?:return\b|panic\(|os\.Exit\()", stripped):
            # Look at the next non-blank line
            for j in range(i + 1, min(i + 5, len(lines))):
                next_stripped = lines[j].strip()
                if not next_stripped:
                    continue
                if next_stripped.startswith("//"):
                    continue
                if next_stripped == "}":
                    break
                if next_stripped.startswith("case ") or next_stripped.startswith("default:"):
                    break
                smell_counts["unreachable_code"].append(
                    {"file": filepath, "line": j + 1, "content": next_stripped[:100]}
                )
                break


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_smells(path: Path) -> tuple[list[dict], int]:
    """Detect Go code smell patterns across the codebase.

    Returns (entries, total_files_checked).
    """
    smell_counts: dict[str, list[dict]] = {sid: [] for sid in _UNIQUE_IDS}
    files = find_go_files(path)

    for filepath in files:
        if "_test.go" in filepath or "/vendor/" in filepath:
            continue
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else Path(path) / filepath
            content = p.read_text(errors="replace")
            lines = content.splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            log_best_effort_failure(logger, f"read Go smell candidate {filepath}", exc)
            continue

        # Regex-based smells
        for check in GO_SMELL_CHECKS:
            if check["pattern"] is None:
                continue
            for i, line in enumerate(lines):
                stripped = line.strip()
                # Skip comment lines for most checks, but allow todo_fixme
                if stripped.startswith("//") and check["id"] != "todo_fixme":
                    continue
                m = re.search(check["pattern"], line)
                if not m:
                    continue
                # Skip URLs assigned to top-level constants
                if check["id"] == "hardcoded_url" and re.match(
                    r"^(?:var|const)\s+[A-Za-z_]\w*\s*=", stripped
                ):
                    continue
                smell_counts[check["id"]].append(
                    {"file": filepath, "line": i + 1, "content": stripped[:100]}
                )

        # Multi-line smell helpers
        _detect_empty_error_branch(filepath, lines, smell_counts)
        _detect_panic_in_lib(filepath, content, lines, smell_counts)
        _detect_init_side_effects(filepath, content, lines, smell_counts)
        _detect_defer_in_loop(filepath, lines, smell_counts)
        _detect_goroutine_closure(filepath, lines, smell_counts)
        _detect_monster_functions(filepath, content, smell_counts)
        _detect_dead_functions(filepath, content, smell_counts)
        _detect_unreachable_code(filepath, lines, smell_counts)

    # Build summary entries sorted by severity then count
    severity_order = {"high": 0, "medium": 1, "low": 2}
    # Build a label lookup from the first check entry for each ID
    label_lookup = {}
    severity_lookup = {}
    for check in GO_SMELL_CHECKS:
        if check["id"] not in label_lookup:
            label_lookup[check["id"]] = check["label"]
            severity_lookup[check["id"]] = check["severity"]

    entries = []
    for sid in _UNIQUE_IDS:
        matches = smell_counts[sid]
        if matches:
            entries.append(
                {
                    "id": sid,
                    "label": label_lookup[sid],
                    "severity": severity_lookup[sid],
                    "count": len(matches),
                    "files": len(set(m["file"] for m in matches)),
                    "matches": matches[:50],
                }
            )
    entries.sort(key=lambda e: (severity_order.get(e["severity"], 9), -e["count"]))
    return entries, len(files)
