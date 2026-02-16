"""TypeScript function-level smell detectors — monster functions, dead functions, etc."""

import re

from ._smell_helpers import (
    _detect_dead_functions as _detect_dead_functions_impl,
    _find_function_start,
    _track_brace_body,
    _ts_match_is_in_string,
    scan_code,
)

_MAX_CATCH_BODY = 1000  # max characters to scan for catch block body
_SWITCH_SCAN_WINDOW = 5000

# Re-export moved helper for compatibility with tests/import sites.
_detect_dead_functions = _detect_dead_functions_impl


def _find_block_end(content: str, brace_start: int, max_scan: int) -> int | None:
    depth = 0
    for ci, ch, in_s in scan_code(content, brace_start, min(brace_start + max_scan, len(content))):
        if in_s:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return ci
    return None


def _line_no_and_preview(content: str, match_start: int) -> tuple[int, str]:
    line_no = content[:match_start].count("\n") + 1
    line_start = content.rfind("\n", 0, match_start) + 1
    line_end = content.find("\n", match_start)
    if line_end == -1:
        line_end = len(content)
    return line_no, content[line_start:line_end].strip()[:100]


def _extract_returned_object_body(body: str) -> str | None:
    return_obj = re.search(r"\breturn\s*\{", body)
    if not return_obj:
        return None
    obj_start = body.find("{", return_obj.start())
    obj_end = _find_block_end(body, obj_start, len(body))
    if obj_end is None:
        return None
    return body[obj_start + 1:obj_end]


def _find_opening_brace_line(lines: list[str], start: int, *, window: int = 5) -> int | None:
    for idx in range(start, min(start + window, len(lines))):
        if "{" in lines[idx]:
            return idx
    return None


def _detect_monster_functions(filepath: str, lines: list[str],
                              smell_counts: dict[str, list[dict]]):
    """Find functions/components exceeding 150 LOC via brace-tracking.

    Matches: function declarations, named arrow functions, and React components.
    Skips: interfaces, types, enums, and objects/arrays.
    """
    for i, line in enumerate(lines):
        name = _find_function_start(line, lines[i + 1:i + 3])
        if not name:
            continue

        brace_line = _find_opening_brace_line(lines, i, window=5)
        if brace_line is None:
            continue

        end_line = _track_brace_body(lines, brace_line, max_scan=2000)
        if end_line is not None:
            loc = end_line - i + 1
            if loc > 150:
                smell_counts["monster_function"].append({
                    "file": filepath,
                    "line": i + 1,
                    "content": f"{name}() — {loc} LOC",
                })


def _detect_window_globals(filepath: str, lines: list[str],
                           line_state: dict[int, str],
                           smell_counts: dict[str, list[dict]]):
    """Find window.__* assignments — global state escape hatches.

    Matches:
    - window.__foo = ...
    - (window as any).__foo = ...
    - window['__foo'] = ...
    """
    window_re = re.compile(
        r"""(?:"""
        r"""\(?\s*window\s+as\s+any\s*\)?\s*\.\s*(__\w+)"""   # (window as any).__name
        r"""|window\s*\.\s*(__\w+)"""                           # window.__name
        r"""|window\s*\[\s*['"](__\w+)['"]\s*\]"""              # window['__name']
        r""")\s*=""",
    )
    for i, line in enumerate(lines):
        if i in line_state:
            continue
        m = window_re.search(line)
        if not m:
            continue
        if _ts_match_is_in_string(line, m.start()):
            continue
        smell_counts["window_global"].append({
            "file": filepath,
            "line": i + 1,
            "content": line.strip()[:100],
        })


def _detect_catch_return_default(filepath: str, content: str,
                                  smell_counts: dict[str, list[dict]]):
    """Find catch blocks that return object literals with default/no-op values.

    Catches the pattern:
      catch (...) { ... return { key: false, key: null, key: () => {} }; }

    This is a silent failure — the caller gets valid-looking data but the
    operation actually failed.
    """
    catch_re = re.compile(r"catch\s*\([^)]*\)\s*\{")
    for m in catch_re.finditer(content):
        brace_start = m.end() - 1
        body_end = _find_block_end(content, brace_start, _MAX_CATCH_BODY)
        if body_end is None:
            continue

        body = content[brace_start + 1:body_end]
        obj_content = _extract_returned_object_body(body)
        if obj_content is None:
            continue

        noop_count = len(re.findall(r"\(\)\s*=>\s*\{\s*\}", obj_content))  # () => {}
        false_count = len(re.findall(r":\s*(?:false|null|undefined|0|''|\"\")\b", obj_content))
        default_fields = noop_count + false_count

        if default_fields >= 2:
            line_no, preview = _line_no_and_preview(content, m.start())
            smell_counts["catch_return_default"].append({
                "file": filepath,
                "line": line_no,
                "content": preview,
            })


def _detect_switch_no_default(filepath: str, content: str,
                               smell_counts: dict[str, list[dict]]):
    """Flag switch statements that have no default case."""
    switch_re = re.compile(r"\bswitch\s*\([^)]*\)\s*\{")
    for m in switch_re.finditer(content):
        brace_start = m.end() - 1
        body_end = _find_block_end(content, brace_start, _SWITCH_SCAN_WINDOW)
        if body_end is None:
            continue

        body = content[brace_start + 1:body_end]
        case_count = len(re.findall(r"\bcase\s+", body))
        if case_count < 2:
            continue

        if re.search(r"\bdefault\s*:", body):
            continue

        line_no, preview = _line_no_and_preview(content, m.start())
        smell_counts["switch_no_default"].append({
            "file": filepath,
            "line": line_no,
            "content": preview,
        })
