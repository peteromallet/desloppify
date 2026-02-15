"""Python code smell detection."""

import re
from pathlib import Path

from ....utils import PROJECT_ROOT, find_py_files
from .smells_ast import (
    _collect_module_constants,
    _detect_ast_smells,
    _detect_duplicate_constants,
    _detect_star_import_no_all,
    _detect_vestigial_parameter,
)


def _smell(id: str, label: str, severity: str, pattern: str | None = None) -> dict:
    return {"id": id, "label": label, "pattern": pattern, "severity": severity}


SMELL_CHECKS = [
    # Regex-based detectors
    _smell("bare_except", "Bare except clause (catches everything including SystemExit)",
           "high", r"^\s*except\s*:"),
    _smell("broad_except", "Broad except — check library exceptions before narrowing",
           "medium", r"^\s*except\s+Exception\s*(?:as\s+\w+\s*)?:"),
    _smell("mutable_default", "Mutable default argument (list/dict/set literal)",
           "high", r"def\s+\w+\([^)]*=\s*(?:\[\]|\{\}|set\(\))"),
    _smell("global_keyword", "Global keyword usage", "medium", r"^\s+global\s+\w+"),
    _smell("star_import", "Star import (from X import *)", "medium", r"^from\s+\S+\s+import\s+\*"),
    _smell("type_ignore", "type: ignore comment", "medium", r"#\s*type:\s*ignore"),
    _smell("eval_exec", "eval()/exec() usage", "high", r"(?<!\.)(?<!\w)(?:eval|exec)\s*\("),
    _smell("magic_number", "Magic numbers (>1000 in logic)",
           "low", r"(?:==|!=|>=?|<=?|[+\-*/])\s*\d{4,}"),
    _smell("todo_fixme", "TODO/FIXME/HACK comments", "low", r"#\s*(?:TODO|FIXME|HACK|XXX)"),
    _smell("hardcoded_url", "Hardcoded URL in source code",
           "medium", r"""(?:['"])https?://[^\s'"]+(?:['"])"""),
    _smell("debug_tag", "Vestigial debug tag in log/print",
           "low", r"""(?:f?['"])\[([A-Z][A-Z0-9_]{2,})\]\s"""),
    _smell("workaround_tag", "Workaround tag in comment ([PascalCaseTag])",
           "low", r"#.*\[([A-Z][a-z]+(?:[A-Z][a-z]+)+)\]"),
    # Multi-line detectors (no regex pattern)
    _smell("star_import_no_all", "Star import target has no __all__ (uncontrolled namespace)", "medium"),
    _smell("empty_except", "Empty except block (except: pass)", "high"),
    _smell("swallowed_error", "Catch block that only logs (swallowed error)", "high"),
    # AST-based detectors (no regex pattern)
    _smell("monster_function", "Monster function (>150 LOC)", "high"),
    _smell("dead_function", "Dead function (body is only pass/return)", "medium"),
    _smell("inline_class", "Class defined inside a function", "medium"),
    _smell("deferred_import", "Function-level import (possible circular import workaround)", "low"),
    _smell("subprocess_no_timeout", "subprocess call without timeout (can hang forever)", "high"),
    _smell("mutable_class_var", "Class-level mutable default (shared across instances)", "high"),
    _smell("lru_cache_mutable", "lru_cache on function that reads mutable global state", "medium"),
    _smell("unsafe_file_write", "Non-atomic file write (use temp+rename for safety)", "medium"),
    _smell("duplicate_constant", "Constant defined identically in multiple modules", "medium"),
    _smell("unreachable_code", "Code after unconditional return/raise/break/continue", "high"),
    _smell("constant_return", "Function always returns the same constant value", "medium"),
    _smell("regex_backtrack", "Regex with nested quantifiers (ReDoS risk)", "high"),
    _smell("naive_comment_strip", "re.sub strips comments without string awareness", "medium"),
    _smell("callback_logging", "Logging callback parameter (use module-level logger instead)", "medium"),
    _smell("hardcoded_path_sep", "Hardcoded '/' path separator (breaks on Windows)", "medium"),
    # #48: lost exception context
    _smell("lost_exception_context", "Raise without 'from' loses exception chain", "high"),
    # #49: vestigial parameter, noop function, stderr traceback
    _smell("vestigial_parameter", "Parameter annotated as unused/deprecated in comments", "medium"),
    _smell("noop_function", "Non-trivial function whose body does nothing", "high"),
    _smell("stderr_traceback", "traceback.print_exc() bypasses structured logging", "high",
           r"traceback\.print_exc\s*\("),
    # AST-based: sys.exit in library code, silent except
    _smell("sys_exit_in_library", "sys.exit() outside CLI entry point — use exceptions", "high"),
    _smell("silent_except", "Except handler silently suppresses error (pass/continue, no log)", "high"),
    _smell("optional_param_sprawl", "Too many optional params — consider a config object", "medium"),
    _smell("annotation_quality", "Loose type annotation — use specific types", "medium"),
]


def _build_string_line_set(lines: list[str]) -> set[int]:
    """Build a set of 0-indexed line numbers that are inside multi-line strings.

    Tracks triple-quote state across lines so regex-based checks can skip
    lines that are inside multi-line string literals.
    """
    in_multiline: str | None = None  # '"""' or "'''" or None
    string_lines: set[int] = set()

    for i, line in enumerate(lines):
        if in_multiline is not None:
            string_lines.add(i)
            # Check if this line closes the multi-line string
            if in_multiline in line:
                # Find the closing triple-quote (skip escaped ones)
                pos = 0
                while pos < len(line):
                    idx = line.find(in_multiline, pos)
                    if idx == -1:
                        break
                    # Check it's not escaped
                    backslashes = 0
                    j = idx - 1
                    while j >= 0 and line[j] == "\\":
                        backslashes += 1
                        j -= 1
                    if backslashes % 2 == 0:
                        in_multiline = None
                        break
                    pos = idx + 3
            continue

        # Check if this line opens a multi-line string
        pos = 0
        while pos < len(line):
            ch = line[pos]
            if ch == "#":
                break  # Rest is comment
            # Skip string prefixes
            if ch in ("r", "b", "f", "u", "R", "B", "F", "U") and pos + 1 < len(line):
                next_ch = line[pos + 1]
                if next_ch in ('"', "'"):
                    pos += 1
                    ch = next_ch
                elif (next_ch in ("r", "b", "f", "R", "B", "F")
                      and pos + 2 < len(line) and line[pos + 2] in ('"', "'")):
                    pos += 2
                    ch = line[pos]
            if ch in ('"', "'"):
                triple = line[pos:pos + 3]
                if triple in ('"""', "'''"):
                    # Check if it closes on the same line
                    close_idx = line.find(triple, pos + 3)
                    if close_idx == -1:
                        # Opens a multi-line string
                        in_multiline = triple
                        break
                    else:
                        pos = close_idx + 3
                        continue
                else:
                    # Single-line string — skip to closing quote
                    end = line.find(ch, pos + 1)
                    while end != -1 and end > 0 and line[end - 1] == "\\":
                        end = line.find(ch, end + 1)
                    pos = (end + 1) if end != -1 else len(line)
                    continue
            pos += 1

    return string_lines


def _match_is_in_string(line: str, match_start: int) -> bool:
    """Check if a regex match position falls inside a string literal or comment on a single line."""
    i, in_string = 0, None
    while i < len(line):
        if i == match_start:
            return in_string is not None
        ch = line[i]
        if in_string is None:
            if ch == "#":
                return True  # In a comment, not real code
            triple = line[i : i + 3]
            if triple in ('"""', "'''"):
                in_string = triple
                i += 3
                continue
            if ch in ("r", "b", "f") and i + 1 < len(line) and line[i + 1] in ('"', "'"):
                i += 1
                ch = line[i]
            if ch in ('"', "'"):
                in_string = ch
                i += 1
                continue
        else:
            if ch == "\\" and i + 1 < len(line):
                i += 2
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
    return in_string is not None


def detect_smells(path: Path) -> tuple[list[dict], int]:
    """Detect Python code smell patterns. Returns (entries, total_files_checked)."""
    smell_counts: dict[str, list[dict]] = {s["id"]: [] for s in SMELL_CHECKS}
    files = find_py_files(path)
    # Collect module-level constants for cross-file duplicate detection
    constants_by_key: dict[tuple[str, str], list[tuple[str, int]]] = {}

    for filepath in files:
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            content = p.read_text()
            lines = content.splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        # Build set of lines inside multi-line strings to avoid false positives
        multiline_string_lines = _build_string_line_set(lines)

        for check in SMELL_CHECKS:
            if check["pattern"] is None:
                continue
            for i, line in enumerate(lines):
                # Skip lines inside multi-line strings
                if i in multiline_string_lines:
                    continue
                m = re.search(check["pattern"], line)
                if m and not _match_is_in_string(line, m.start()):
                    # Skip URLs assigned to module-level constants (UPPER_CASE = "https://...")
                    if check["id"] == "hardcoded_url" and re.match(
                        r"^[A-Z_][A-Z0-9_]*\s*=", line.strip()
                    ):
                        continue
                    smell_counts[check["id"]].append({
                        "file": filepath, "line": i + 1, "content": line.strip()[:100],
                    })

        _detect_empty_except(filepath, lines, smell_counts)
        _detect_swallowed_errors(filepath, lines, smell_counts)
        _detect_ast_smells(filepath, content, smell_counts)
        _detect_star_import_no_all(filepath, content, path, smell_counts)
        _detect_vestigial_parameter(filepath, content, lines, smell_counts)
        _collect_module_constants(filepath, content, constants_by_key)

    # Cross-file: detect duplicate constants
    _detect_duplicate_constants(constants_by_key, smell_counts)

    severity_order = {"high": 0, "medium": 1, "low": 2}
    entries = []
    for check in SMELL_CHECKS:
        matches = smell_counts[check["id"]]
        if matches:
            entries.append({
                "id": check["id"], "label": check["label"], "severity": check["severity"],
                "count": len(matches), "files": len(set(m["file"] for m in matches)),
                "matches": matches[:50],
            })
    entries.sort(key=lambda e: (severity_order.get(e["severity"], 9), -e["count"]))
    return entries, len(files)


def _walk_except_blocks(lines: list[str]):
    """Yield (line_index, except_line_stripped, body_lines) for each except block."""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not re.match(r"except\s*(?:\w|\(|:)", stripped) and stripped != "except:":
            continue
        if not stripped.endswith(":"):
            continue
        indent = len(line) - len(line.lstrip())
        j, body_lines = i + 1, []
        while j < len(lines):
            next_line = lines[j]
            next_stripped = next_line.strip()
            if next_stripped == "":
                j += 1
                continue
            if len(next_line) - len(next_line.lstrip()) <= indent:
                break
            body_lines.append(next_stripped)
            j += 1
        yield i, stripped, body_lines


def _is_broad_except(stripped: str) -> bool:
    """Check if except clause catches broadly (bare, Exception, BaseException)."""
    if stripped == "except:":
        return True
    m = re.match(r"except\s+(\w+)", stripped)
    return bool(m and m.group(1) in ("Exception", "BaseException"))


def _detect_empty_except(filepath: str, lines: list[str], smell_counts: dict[str, list]):
    """Find broad except blocks that just pass or have empty body."""
    for i, stripped, body_lines in _walk_except_blocks(lines):
        if (not body_lines or body_lines == ["pass"]) and _is_broad_except(stripped):
            smell_counts["empty_except"].append({
                "file": filepath, "line": i + 1, "content": stripped[:100],
            })


def _detect_swallowed_errors(filepath: str, lines: list[str], smell_counts: dict[str, list]):
    """Find except blocks that only print/log the error."""
    _LOG_RE = r"(?:print|logging\.\w+|logger\.\w+|log\.\w+)\s*\("
    for i, stripped, body_lines in _walk_except_blocks(lines):
        if body_lines and all(re.match(_LOG_RE, s) for s in body_lines):
            smell_counts["swallowed_error"].append({
                "file": filepath, "line": i + 1, "content": stripped[:100],
            })


