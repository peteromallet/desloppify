"""Multi-line smell detection helpers (brace-tracked).

Shared utilities (string-aware scanning, brace tracking, comment stripping)
plus a handful of smell detectors. Monster-function, dead-function,
window-global, catch-return-default, and switch-no-default detectors live
in _smell_detectors.py.
"""

import re


def scan_code(text: str, start: int = 0, end: int | None = None):
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


def _detect_empty_if_chains(filepath: str, lines: list[str],
                            smell_counts: dict[str, list[dict]]):
    """Find if/else chains where all branches are empty."""
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not re.match(r"(?:else\s+)?if\s*\(", stripped):
            i += 1
            continue

        # Single-line: if (...) { }
        if re.match(r"(?:else\s+)?if\s*\([^)]*\)\s*\{\s*\}\s*$", stripped):
            chain_start = i
            j = i + 1
            while j < len(lines):
                next_stripped = lines[j].strip()
                if re.match(r"else\s+if\s*\([^)]*\)\s*\{\s*\}\s*$", next_stripped):
                    j += 1
                    continue
                if re.match(r"(?:\}\s*)?else\s*\{\s*\}\s*$", next_stripped):
                    j += 1
                    continue
                break
            smell_counts["empty_if_chain"].append({
                "file": filepath,
                "line": chain_start + 1,
                "content": stripped[:100],
            })
            i = j
            continue

        # Multi-line: if (...) { followed by } on next non-blank line
        if re.match(r"(?:else\s+)?if\s*\([^)]*\)\s*\{\s*$", stripped):
            chain_start = i
            chain_all_empty = True
            j = i
            while j < len(lines):
                cur = lines[j].strip()
                if j == chain_start:
                    if not re.match(r"(?:else\s+)?if\s*\([^)]*\)\s*\{\s*$", cur):
                        chain_all_empty = False
                        break
                elif re.match(r"\}\s*else\s+if\s*\([^)]*\)\s*\{\s*$", cur):
                    pass
                elif re.match(r"\}\s*else\s*\{\s*$", cur):
                    pass
                elif cur == "}":
                    k = j + 1
                    while k < len(lines) and lines[k].strip() == "":
                        k += 1
                    if k < len(lines) and re.match(r"else\s", lines[k].strip()):
                        j = k
                        continue
                    j += 1
                    break
                elif cur == "":
                    j += 1
                    continue
                else:
                    chain_all_empty = False
                    break
                j += 1

            if chain_all_empty and j > chain_start + 1:
                smell_counts["empty_if_chain"].append({
                    "file": filepath,
                    "line": chain_start + 1,
                    "content": lines[chain_start].strip()[:100],
                })
            i = max(i + 1, j)
            continue

        i += 1


def _detect_dead_useeffects(filepath: str, lines: list[str],
                            smell_counts: dict[str, list[dict]]):
    """Find useEffect calls with empty or whitespace/comment-only bodies.

    Algorithm: two-pass brace/paren tracking with string-escape awareness.
    Pass 1: track paren depth to find the full useEffect(...) extent.
    Pass 2: within that extent, find the arrow body ({...} after =>) using
    brace depth, skipping characters inside string literals (', ", `).
    Then strip comments from the body and check if anything remains.
    """
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not re.match(r"(?:React\.)?useEffect\s*\(\s*\(\s*\)\s*=>\s*\{", stripped):
            continue

        paren_depth = 0
        brace_depth = 0
        end = None
        for j in range(i, min(i + 30, len(lines))):
            for _, ch, in_s in scan_code(lines[j]):
                if in_s:
                    continue
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth -= 1
                    if paren_depth <= 0:
                        end = j
                        break
                elif ch == "{":
                    brace_depth += 1
                elif ch == "}":
                    brace_depth -= 1
            if end is not None:
                break

        if end is None:
            continue

        text = "\n".join(lines[i:end + 1])
        arrow_pos = text.find("=>")
        if arrow_pos == -1:
            continue
        brace_pos = text.find("{", arrow_pos)
        if brace_pos == -1:
            continue

        depth = 0
        body_end = None
        for ci, ch, in_s in scan_code(text, brace_pos):
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

        body = text[brace_pos + 1:body_end]
        body_stripped = _strip_ts_comments(body)
        if body_stripped.strip() == "":
            smell_counts["dead_useeffect"].append({
                "file": filepath,
                "line": i + 1,
                "content": stripped[:100],
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
