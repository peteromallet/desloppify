"""TypeScript function-level smell detectors — monster functions, dead functions, etc."""

import re

from ._smell_helpers import scan_code, _strip_ts_comments, _ts_match_is_in_string, _track_brace_body

_MAX_CATCH_BODY = 1000  # max characters to scan for catch block body


def _find_function_start(line: str, next_lines: list[str]) -> str | None:
    """Return the function name if this line starts a named function, else None.

    Matches:
    - function foo(...)
    - export function foo(...)
    - export default function foo(...)
    - const foo = (...) => {
    - const foo = async (...) => {
    - const foo = function(...)

    Skips interfaces, types, enums, classes.
    """
    stripped = line.strip()
    if re.match(r"(?:export\s+)?(?:interface|type|enum|class)\s+", stripped):
        return None

    # function declaration
    m = re.match(
        r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+(\w+)\s*\(",
        stripped,
    )
    if m:
        return m.group(1)

    # const/let/var assignment — need to verify it's actually a function
    m = re.match(r"(?:export\s+)?(?:const|let|var)\s+(\w+)", stripped)
    if not m:
        return None
    name = m.group(1)

    # Look at what follows the = sign
    combined = "\n".join([stripped] + [l.strip() for l in next_lines[:2]])
    eq_pos = combined.find("=", m.end())
    if eq_pos == -1:
        return None
    after_eq = combined[eq_pos + 1:].lstrip()

    # Direct function: must start with (, async, or function keyword.
    # Skips function calls like useMemo(...), useRef(...), React.memo(...) that
    # may contain => in their arguments or type annotations.
    if re.match(r"(?:async|function)\b", after_eq):
        return name
    if after_eq.startswith("("):
        # Check that this ( ... ) is followed by => (arrow function params)
        # not just a function call like someFunction(...)
        brace_pos = combined.find("{", eq_pos)
        segment = combined[eq_pos:brace_pos] if brace_pos != -1 else combined[eq_pos:]
        if "=>" in segment:
            return name
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

        # Find opening brace on this or next few lines
        brace_line = None
        for k in range(i, min(i + 5, len(lines))):
            if "{" in lines[k]:
                brace_line = k
                break
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


def _detect_dead_functions(filepath: str, lines: list[str],
                           smell_counts: dict[str, list[dict]]):
    """Find functions with empty body or only return/return null.

    Matches function declarations and named arrow functions.
    Skips decorated functions (TS decorators on line above).
    """
    for i, line in enumerate(lines):
        # Skip decorated functions
        if i > 0 and lines[i - 1].strip().startswith("@"):
            continue

        name = _find_function_start(line, lines[i + 1:i + 3])
        if not name:
            continue

        # Find opening brace
        brace_line = None
        for k in range(i, min(i + 5, len(lines))):
            if "{" in lines[k]:
                brace_line = k
                break
        if brace_line is None:
            continue

        end_line = _track_brace_body(lines, brace_line, max_scan=30)
        if end_line is None:
            continue

        # Extract body between braces
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
                "line": i + 1,
                "content": f"{name}() — body is {label}",
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
        depth = 0
        body_end = None
        for ci, ch, in_s in scan_code(content, brace_start, min(brace_start + _MAX_CATCH_BODY, len(content))):
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
        # Check if body contains "return {" — a return with object literal
        return_obj = re.search(r"\breturn\s*\{", body)
        if not return_obj:
            continue

        # Extract the returned object content
        obj_start = body.find("{", return_obj.start())
        obj_depth = 0
        obj_end = None
        for ci, ch, in_s in scan_code(body, obj_start):
            if in_s:
                continue
            if ch == "{":
                obj_depth += 1
            elif ch == "}":
                obj_depth -= 1
                if obj_depth == 0:
                    obj_end = ci
                    break

        if obj_end is None:
            continue

        obj_content = body[obj_start + 1:obj_end]
        # Count default/no-op fields
        noop_count = len(re.findall(r"\(\)\s*=>\s*\{\s*\}", obj_content))  # () => {}
        false_count = len(re.findall(r":\s*(?:false|null|undefined|0|''|\"\")\b", obj_content))
        default_fields = noop_count + false_count

        if default_fields >= 2:
            line_no = content[:m.start()].count("\n") + 1
            # Use content slice to get the line without re-splitting entire file
            line_start = content.rfind("\n", 0, m.start()) + 1
            line_end = content.find("\n", m.start())
            if line_end == -1:
                line_end = len(content)
            smell_counts["catch_return_default"].append({
                "file": filepath,
                "line": line_no,
                "content": content[line_start:line_end].strip()[:100],
            })


def _detect_switch_no_default(filepath: str, content: str,
                               smell_counts: dict[str, list[dict]]):
    """Flag switch statements that have no default case."""
    switch_re = re.compile(r"\bswitch\s*\([^)]*\)\s*\{")
    for m in switch_re.finditer(content):
        brace_start = m.end() - 1
        depth = 0
        body_end = None
        for ci, ch, in_s in scan_code(content, brace_start, min(brace_start + 5000, len(content))):
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
        # Count case labels — only flag if there are actual cases
        case_count = len(re.findall(r"\bcase\s+", body))
        if case_count < 2:
            continue

        # Check for default: anywhere in the switch body
        if re.search(r"\bdefault\s*:", body):
            continue

        line_no = content[:m.start()].count("\n") + 1
        line_start = content.rfind("\n", 0, m.start()) + 1
        line_end = content.find("\n", m.start())
        if line_end == -1:
            line_end = len(content)
        smell_counts["switch_no_default"].append({
            "file": filepath,
            "line": line_no,
            "content": content[line_start:line_end].strip()[:100],
        })
