"""Multi-line smell detection helpers (brace-tracked).

Shared utilities (string-aware scanning, brace tracking, comment stripping)
plus a handful of smell detectors. Monster-function, dead-function,
window-global, catch-return-default, and switch-no-default detectors live
in _smell_detectors.py.
"""

from __future__ import annotations

import re
from collections.abc import Generator


def scan_code(text: str, start: int = 0, end: int | None = None) -> Generator[tuple[int, str, bool], None, None]:
    """Yield (index, char, in_string) tuples, handling escapes correctly.

    Skips escaped characters (\\x) by advancing +2 instead of +1.
    Tracks single-quoted, double-quoted, and template literal strings.
    Correct for \\\\\" (escaped backslash before quote) where prev_ch pattern fails.
    """
    i = start
    limit = end if end is not None else len(text)
    in_str = None
    while i < limit:
        ch = text[i]
        if in_str:
            if ch == '\\' and i + 1 < limit:
                yield (i, ch, True)
                i += 1
                yield (i, text[i], True)
                i += 1
                continue
            if ch == in_str:
                in_str = None
            yield (i, ch, in_str is not None)
        else:
            if ch in ("'", '"', '`'):
                in_str = ch
                yield (i, ch, True)
            else:
                yield (i, ch, False)
        i += 1


def _strip_ts_comments(text: str) -> str:
    """Strip // and /* */ comments while preserving strings.

    Delegates to the shared implementation in utils.py.
    """
    from ....utils import strip_c_style_comments
    return strip_c_style_comments(text)


def _ts_match_is_in_string(line: str, match_start: int) -> bool:
    """Check if a match position falls inside a string literal or comment on a single line.

    Mirrors Python's _match_is_in_string but for TS syntax (', ", `, //).
    """
    i = 0
    in_str = None

    while i < len(line):
        if i == match_start:
            return in_str is not None

        ch = line[i]

        # Escape sequences inside strings
        if in_str and ch == "\\" and i + 1 < len(line):
            i += 2
            continue

        if in_str:
            if ch == in_str:
                in_str = None
            i += 1
            continue

        # Line comment — everything after is non-code
        if ch == "/" and i + 1 < len(line) and line[i + 1] == "/":
            return match_start > i

        if ch in ("'", '"', '`'):
            in_str = ch
            i += 1
            continue

        i += 1

    return False


def _detect_async_no_await(filepath: str, content: str, lines: list[str],
                           smell_counts: dict[str, list[dict]]):
    """Find async functions that don't use await.

    Algorithm: for each async declaration, track brace depth to find the function
    body extent (up to 200 lines). Scan each line for 'await' within those braces.
    If the opening brace closes (depth returns to 0) without seeing await, flag it.
    """
    async_re = re.compile(r"(?:async\s+function\s+(\w+)|(\w+)\s*=\s*async)")
    for i, line in enumerate(lines):
        m = async_re.search(line)
        if not m:
            continue
        name = m.group(1) or m.group(2)
        brace_depth = 0
        found_open = False
        has_await = False
        for j in range(i, min(i + 200, len(lines))):
            body_line = lines[j]
            prev_code_ch = ""
            for _, ch, in_s in scan_code(body_line):
                if in_s:
                    continue
                if ch == '/' and prev_code_ch == '/':
                    break  # Rest of line is comment
                elif ch == '{':
                    brace_depth += 1
                    found_open = True
                elif ch == '}':
                    brace_depth -= 1
                prev_code_ch = ch
            if "await " in body_line or "await\n" in body_line:
                has_await = True
            if found_open and brace_depth <= 0:
                break

        if found_open and not has_await:
            smell_counts["async_no_await"].append({
                "file": filepath,
                "line": i + 1,
                "content": f"async {name or '(anonymous)'} has no await",
            })


def _detect_error_no_throw(filepath: str, lines: list[str],
                           smell_counts: dict[str, list[dict]]):
    """Find console.error calls not followed by throw or return."""
    for i, line in enumerate(lines):
        if "console.error" in line:
            following = "\n".join(lines[i+1:i+4])
            if not re.search(r"\b(?:throw|return)\b", following):
                smell_counts["console_error_no_throw"].append({
                    "file": filepath,
                    "line": i + 1,
                    "content": line.strip()[:100],
                })


def _detect_swallowed_errors(filepath: str, content: str, lines: list[str],
                              smell_counts: dict[str, list[dict]]):
    """Find catch blocks whose only content is console.error/warn/log (swallowed errors).

    Algorithm: regex-find each `catch(...) {`, then track brace depth with
    string-escape awareness to extract the catch body (up to 500 chars).
    Strip comments, split into statements, and check if every statement
    is a console.error/warn/log call.
    """
    catch_re = re.compile(r"catch\s*\([^)]*\)\s*\{")
    for m in catch_re.finditer(content):
        brace_start = m.end() - 1
        depth = 0
        body_end = None
        for ci, ch, in_s in scan_code(content, brace_start, min(brace_start + 500, len(content))):
            if in_s:
                continue
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    body_end = ci
                    break

        if body_end is None:
            continue

        body = content[brace_start + 1:body_end]
        body_clean = _strip_ts_comments(body).strip()

        if not body_clean:
            continue  # empty catch — caught by empty_catch detector

        statements = [s.strip().rstrip(";") for s in re.split(r"[;\n]", body_clean) if s.strip()]
        if not statements:
            continue

        all_console = all(
            re.match(r"console\.(error|warn|log)\s*\(", stmt)
            for stmt in statements
        )
        if all_console:
            line_no = content[:m.start()].count("\n") + 1
            smell_counts["swallowed_error"].append({
                "file": filepath,
                "line": line_no,
                "content": lines[line_no - 1].strip()[:100] if line_no <= len(lines) else "",
            })


def _track_brace_body(lines: list[str], start_line: int, *, max_scan: int = 2000) -> int | None:
    """Find the closing brace that matches the first opening brace from start_line.

    Tracks brace depth with string-literal awareness (', ", `).
    Returns the line index of the closing brace, or None if not found.
    """
    depth = 0
    found_open = False
    for j in range(start_line, min(start_line + max_scan, len(lines))):
        for _, ch, in_s in scan_code(lines[j]):
            if in_s:
                continue
            if ch == "{":
                depth += 1
                found_open = True
            elif ch == "}":
                depth -= 1
                if found_open and depth == 0:
                    return j
    return None


def _find_function_start(line: str, next_lines: list[str]) -> str | None:
    """Return the function name if this line starts a named function."""
    stripped = line.strip()
    if re.match(r"(?:export\s+)?(?:interface|type|enum|class)\s+", stripped):
        return None

    func_match = re.match(
        r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
        stripped,
    )
    if func_match:
        return func_match.group(1)

    var_match = re.match(r"(?:export\s+)?(?:const|let|var)\s+(\w+)", stripped)
    if not var_match:
        return None
    name = var_match.group(1)
    combined = "\n".join([stripped] + [line_text.strip() for line_text in next_lines[:2]])
    eq_pos = combined.find("=", var_match.end())
    if eq_pos == -1:
        return None
    after_eq = combined[eq_pos + 1:].lstrip()
    if re.match(r"(?:async|function)\b", after_eq):
        return name
    if after_eq.startswith("("):
        brace_pos = combined.find("{", eq_pos)
        segment = combined[eq_pos:brace_pos] if brace_pos != -1 else combined[eq_pos:]
        if "=>" in segment:
            return name
    return None


def _detect_dead_functions(filepath: str, lines: list[str], smell_counts: dict[str, list[dict]]) -> None:
    """Find functions with empty body or only return/return null."""
    for index, line in enumerate(lines):
        if index > 0 and lines[index - 1].strip().startswith("@"):
            continue
        name = _find_function_start(line, lines[index + 1:index + 3])
        if not name:
            continue

        brace_line = None
        for candidate in range(index, min(index + 5, len(lines))):
            if "{" in lines[candidate]:
                brace_line = candidate
                break
        if brace_line is None:
            continue

        end_line = _track_brace_body(lines, brace_line, max_scan=30)
        if end_line is None:
            continue

        body_text = "\n".join(lines[brace_line:end_line + 1])
        first_brace = body_text.find("{")
        last_brace = body_text.rfind("}")
        if first_brace == -1 or last_brace == -1 or first_brace >= last_brace:
            continue

        body = body_text[first_brace + 1:last_brace]
        body_clean = _strip_ts_comments(body).strip().rstrip(";")
        if body_clean in ("", "return", "return null", "return undefined"):
            label = body_clean or "empty"
            smell_counts["dead_function"].append({
                "file": filepath,
                "line": index + 1,
                "content": f"{name}() — body is {label}",
            })
