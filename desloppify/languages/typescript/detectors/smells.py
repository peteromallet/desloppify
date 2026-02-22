"""TypeScript/React code smell detection.

Defines TS-specific smell rules and multi-line smell helpers (brace-tracked).
"""

import logging
import re
from pathlib import Path

from desloppify.core.fallbacks import log_best_effort_failure
from desloppify.languages.typescript.detectors._smell_detectors import (
    _detect_catch_return_default,
    _detect_dead_functions,
    _detect_monster_functions,
    _detect_switch_no_default,
    _detect_window_globals,
)
from desloppify.languages.typescript.detectors._smell_helpers import (
    _detect_async_no_await,
    _detect_error_no_throw,
    _detect_swallowed_errors,
    _strip_ts_comments,
    _ts_match_is_in_string,
    scan_code,
)
from desloppify.core._internal.text_utils import PROJECT_ROOT
from desloppify.utils import find_ts_files

logger = logging.getLogger(__name__)


TS_SMELL_CHECKS = [
    {
        "id": "empty_catch",
        "label": "Empty catch blocks",
        "pattern": r"catch\s*\([^)]*\)\s*\{\s*\}",
        "severity": "high",
    },
    {
        "id": "any_type",
        "label": "Explicit `any` types",
        "pattern": r":\s*any\b",
        "severity": "medium",
    },
    {
        "id": "ts_ignore",
        "label": "@ts-ignore / @ts-expect-error",
        "pattern": r"//\s*@ts-(?:ignore|expect-error)",
        "severity": "medium",
    },
    {
        "id": "ts_nocheck",
        "label": "@ts-nocheck disables all type checking",
        "pattern": r"^\s*//\s*@ts-nocheck",
        "severity": "high",
    },
    {
        "id": "non_null_assert",
        "label": "Non-null assertions (!.)",
        "pattern": r"\w+!\.",
        "severity": "low",
    },
    {
        "id": "hardcoded_color",
        "label": "Hardcoded color values",
        "pattern": r"""(?:color|background|border|fill|stroke)\s*[:=]\s*['"]#[0-9a-fA-F]{3,8}['"]""",
        "severity": "medium",
    },
    {
        "id": "hardcoded_rgb",
        "label": "Hardcoded rgb/rgba",
        "pattern": r"rgba?\(\s*\d+",
        "severity": "medium",
    },
    {
        "id": "async_no_await",
        "label": "Async functions without await",
        "pattern": None,  # multi-line analysis
        "severity": "medium",
    },
    {
        "id": "magic_number",
        "label": "Magic numbers (>1000 in logic)",
        "pattern": r"(?:===?|!==?|>=?|<=?|[+\-*/])\s*\d{4,}",
        "severity": "low",
    },
    {
        "id": "console_error_no_throw",
        "label": "console.error without throw/return",
        "pattern": None,  # multi-line analysis
        "severity": "medium",
    },
    {
        "id": "empty_if_chain",
        "label": "Empty if/else chains",
        "pattern": None,  # multi-line analysis
        "severity": "high",
    },
    {
        "id": "dead_useeffect",
        "label": "useEffect with empty body",
        "pattern": None,  # multi-line analysis
        "severity": "high",
    },
    {
        "id": "swallowed_error",
        "label": "Catch blocks that only log (swallowed errors)",
        "pattern": None,  # multi-line analysis
        "severity": "medium",
    },
    {
        "id": "hardcoded_url",
        "label": "Hardcoded URL in source code",
        "pattern": r"""(?:['\"])https?://[^\s'\"]+(?:['\"])""",
        "severity": "medium",
    },
    {
        "id": "todo_fixme",
        "label": "TODO/FIXME/HACK comments",
        "pattern": r"//\s*(?:TODO|FIXME|HACK|XXX)",
        "severity": "low",
    },
    {
        "id": "debug_tag",
        "label": "Vestigial debug tag in log/print",
        "pattern": r"""(?:['"`])\[([A-Z][A-Z0-9_]{2,})\]\s""",
        "severity": "low",
    },
    {
        "id": "monster_function",
        "label": "Monster function (>150 LOC)",
        # Detected via brace-tracking
        "pattern": None,
        "severity": "high",
    },
    {
        "id": "dead_function",
        "label": "Dead function (body is empty/return-only)",
        # Detected via brace-tracking
        "pattern": None,
        "severity": "medium",
    },
    {
        "id": "voided_symbol",
        "label": "Dead internal code (void-suppressed unused symbol)",
        "pattern": r"^\s*void\s+[a-zA-Z_]\w*\s*;?\s*$",
        "severity": "medium",
    },
    {
        "id": "window_global",
        "label": "Window global escape hatch (window.__*)",
        "pattern": None,  # multi-line analysis — regex needs alternation
        "severity": "medium",
    },
    {
        "id": "workaround_tag",
        "label": "Workaround tag in comment ([PascalCaseTag])",
        "pattern": r"//.*\[([A-Z][a-z]+(?:[A-Z][a-z]+)+)\]",
        "severity": "low",
    },
    {
        "id": "catch_return_default",
        "label": "Catch block returns default object (silent failure)",
        "pattern": None,  # multi-line brace-tracked
        "severity": "high",
    },
    {
        "id": "as_any_cast",
        "label": "`as any` type casts",
        "pattern": r"\bas\s+any\b",
        "severity": "medium",
    },
    {
        "id": "sort_no_comparator",
        "label": ".sort() without comparator function",
        "pattern": r"\.sort\(\s*\)",
        "severity": "medium",
    },
    {
        "id": "switch_no_default",
        "label": "Switch without default case",
        "pattern": None,  # multi-line brace-tracked
        "severity": "low",
    },
]


def _build_ts_line_state(lines: list[str]) -> dict[int, str]:
    """Build a map of line numbers that are inside block comments or template literals.

    Returns {0-indexed line: reason} where reason is "block_comment" or "template_literal".
    Lines not in the map are normal code lines suitable for regex checks.

    Tracks:
    - Block comment state (opened by /*, closed by */)
    - Template literal state (opened by backtick, closed by backtick,
      with ${} nesting awareness)
    """
    state: dict[int, str] = {}
    in_block_comment = False
    in_template = False
    template_brace_depth = 0  # tracks ${} nesting inside template literals

    for i, line in enumerate(lines):
        if in_block_comment:
            state[i] = "block_comment"
            if "*/" in line:
                in_block_comment = False
            continue

        if in_template:
            state[i] = "template_literal"
            # Scan for closing backtick or ${} nesting
            j = 0
            while j < len(line):
                ch = line[j]
                if ch == "\\" and j + 1 < len(line):
                    j += 2
                    continue
                if ch == "$" and j + 1 < len(line) and line[j + 1] == "{":
                    template_brace_depth += 1
                    j += 2
                    continue
                if ch == "}" and template_brace_depth > 0:
                    template_brace_depth -= 1
                    j += 1
                    continue
                if ch == "`" and template_brace_depth == 0:
                    in_template = False
                    # Rest of line is normal code — don't mark it
                    # but we already marked the line; that's fine for
                    # line-level filtering
                    break
                j += 1
            continue

        # Normal code line — check for block comment or template literal start
        j = 0
        in_str = None
        while j < len(line):
            ch = line[j]

            # Skip escape sequences
            if in_str and ch == "\\" and j + 1 < len(line):
                j += 2
                continue

            # String tracking
            if in_str:
                if ch == in_str:
                    in_str = None
                j += 1
                continue

            # Line comment — rest is not code
            if ch == "/" and j + 1 < len(line) and line[j + 1] == "/":
                break

            # Block comment start
            if ch == "/" and j + 1 < len(line) and line[j + 1] == "*":
                # Check if it closes on same line
                close = line.find("*/", j + 2)
                if close != -1:
                    j = close + 2
                    continue
                else:
                    in_block_comment = True
                    break

            # Template literal start
            if ch == "`":
                # Scan for closing backtick on same line
                k = j + 1
                found_close = False
                depth = 0
                while k < len(line):
                    c = line[k]
                    if c == "\\" and k + 1 < len(line):
                        k += 2
                        continue
                    if c == "$" and k + 1 < len(line) and line[k + 1] == "{":
                        depth += 1
                        k += 2
                        continue
                    if c == "}" and depth > 0:
                        depth -= 1
                        k += 1
                        continue
                    if c == "`" and depth == 0:
                        found_close = True
                        j = k + 1
                        break
                    k += 1
                if found_close:
                    continue
                else:
                    in_template = True
                    template_brace_depth = depth
                    break

            if ch in ("'", '"'):
                in_str = ch
                j += 1
                continue

            j += 1

    return state


def _detect_empty_if_chains(filepath: str, lines: list[str], smell_counts: dict[str, list[dict]]) -> None:
    """Find if/else chains where all branches are empty."""
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not re.match(r"(?:else\s+)?if\s*\(", stripped):
            index += 1
            continue

        if re.match(r"(?:else\s+)?if\s*\([^)]*\)\s*\{\s*\}\s*$", stripped):
            chain_start = index
            cursor = index + 1
            while cursor < len(lines):
                next_stripped = lines[cursor].strip()
                if re.match(r"else\s+if\s*\([^)]*\)\s*\{\s*\}\s*$", next_stripped):
                    cursor += 1
                    continue
                if re.match(r"(?:\}\s*)?else\s*\{\s*\}\s*$", next_stripped):
                    cursor += 1
                    continue
                break
            smell_counts["empty_if_chain"].append(
                {"file": filepath, "line": chain_start + 1, "content": stripped[:100]}
            )
            index = cursor
            continue

        if re.match(r"(?:else\s+)?if\s*\([^)]*\)\s*\{\s*$", stripped):
            chain_start = index
            chain_all_empty = True
            cursor = index
            while cursor < len(lines):
                current = lines[cursor].strip()
                if cursor == chain_start:
                    if not re.match(r"(?:else\s+)?if\s*\([^)]*\)\s*\{\s*$", current):
                        chain_all_empty = False
                        break
                elif re.match(r"\}\s*else\s+if\s*\([^)]*\)\s*\{\s*$", current):
                    pass
                elif re.match(r"\}\s*else\s*\{\s*$", current):
                    pass
                elif current == "}":
                    tail = cursor + 1
                    while tail < len(lines) and lines[tail].strip() == "":
                        tail += 1
                    if tail < len(lines) and re.match(r"else\s", lines[tail].strip()):
                        cursor = tail
                        continue
                    cursor += 1
                    break
                elif current == "":
                    cursor += 1
                    continue
                else:
                    chain_all_empty = False
                    break
                cursor += 1
            if chain_all_empty and cursor > chain_start + 1:
                smell_counts["empty_if_chain"].append(
                    {"file": filepath, "line": chain_start + 1, "content": lines[chain_start].strip()[:100]}
                )
            index = max(index + 1, cursor)
            continue

        index += 1


def _detect_dead_useeffects(filepath: str, lines: list[str], smell_counts: dict[str, list[dict]]) -> None:
    """Find useEffect calls with empty/whitespace/comment-only bodies."""
    for line_no, line in enumerate(lines):
        stripped = line.strip()
        if not re.match(r"(?:React\.)?useEffect\s*\(\s*\(\s*\)\s*=>\s*\{", stripped):
            continue

        paren_depth = 0
        end_line = None
        for cursor in range(line_no, min(line_no + 30, len(lines))):
            for _, ch, in_string in scan_code(lines[cursor]):
                if in_string:
                    continue
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth -= 1
                    if paren_depth <= 0:
                        end_line = cursor
                        break
            if end_line is not None:
                break

        if end_line is None:
            continue

        text = "\n".join(lines[line_no:end_line + 1])
        arrow_pos = text.find("=>")
        if arrow_pos == -1:
            continue
        brace_pos = text.find("{", arrow_pos)
        if brace_pos == -1:
            continue

        depth = 0
        body_end = None
        for idx, ch, in_string in scan_code(text, brace_pos):
            if in_string:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    body_end = idx
                    break
        if body_end is None:
            continue

        body = text[brace_pos + 1:body_end]
        if _strip_ts_comments(body).strip() == "":
            smell_counts["dead_useeffect"].append(
                {"file": filepath, "line": line_no + 1, "content": stripped[:100]}
            )


def detect_smells(path: Path) -> tuple[list[dict], int]:
    """Detect TypeScript/React code smell patterns across the codebase.

    Returns (entries, total_files_checked).
    """
    checks = TS_SMELL_CHECKS
    smell_counts: dict[str, list[dict]] = {s["id"]: [] for s in checks}
    files = find_ts_files(path)

    for filepath in files:
        if "node_modules" in filepath or ".d.ts" in filepath:
            continue
        try:
            p = (
                Path(filepath)
                if Path(filepath).is_absolute()
                else PROJECT_ROOT / filepath
            )
            content = p.read_text()
            lines = content.splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            log_best_effort_failure(
                logger, f"read TypeScript smell candidate {filepath}", exc
            )
            continue

        # Build line state for string/comment filtering
        line_state = _build_ts_line_state(lines)

        # Regex-based smells
        for check in checks:
            if check["pattern"] is None:
                continue
            for i, line in enumerate(lines):
                # Skip lines inside block comments or template literals
                if i in line_state:
                    continue
                m = re.search(check["pattern"], line)
                if not m:
                    continue
                # Check if match is inside a single-line string or comment
                if _ts_match_is_in_string(line, m.start()):
                    continue
                # Skip URLs assigned to module-level constants
                if check["id"] == "hardcoded_url" and re.match(
                    r"^(?:export\s+)?(?:const|let|var)\s+[A-Z_][A-Z0-9_]*\s*=",
                    line.strip(),
                ):
                    continue
                smell_counts[check["id"]].append(
                    {
                        "file": filepath,
                        "line": i + 1,
                        "content": line.strip()[:100],
                    }
                )

        # Multi-line smell helpers (brace-tracked)
        _detect_async_no_await(filepath, content, lines, smell_counts)
        _detect_error_no_throw(filepath, lines, smell_counts)
        _detect_empty_if_chains(filepath, lines, smell_counts)
        _detect_dead_useeffects(filepath, lines, smell_counts)
        _detect_swallowed_errors(filepath, content, lines, smell_counts)
        _detect_monster_functions(filepath, lines, smell_counts)
        _detect_dead_functions(filepath, lines, smell_counts)
        _detect_window_globals(filepath, lines, line_state, smell_counts)
        _detect_catch_return_default(filepath, content, smell_counts)
        _detect_switch_no_default(filepath, content, smell_counts)

    # Build summary entries sorted by severity then count
    severity_order = {"high": 0, "medium": 1, "low": 2}
    entries = []
    for check in checks:
        matches = smell_counts[check["id"]]
        if matches:
            entries.append(
                {
                    "id": check["id"],
                    "label": check["label"],
                    "severity": check["severity"],
                    "count": len(matches),
                    "files": len(set(m["file"] for m in matches)),
                    "matches": matches[:50],
                }
            )
    entries.sort(key=lambda e: (severity_order.get(e["severity"], 9), -e["count"]))
    return entries, len(files)
