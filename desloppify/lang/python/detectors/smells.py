"""Python code smell detection."""

import ast
import re
from pathlib import Path

from ....utils import PROJECT_ROOT, find_py_files


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
    _smell("eval_exec", "eval()/exec() usage", "high", r"\b(?:eval|exec)\s*\("),
    _smell("magic_number", "Magic numbers (>1000 in logic)",
           "low", r"(?:==|!=|>=?|<=?|[+\-*/])\s*\d{4,}"),
    _smell("todo_fixme", "TODO/FIXME/HACK comments", "low", r"#\s*(?:TODO|FIXME|HACK|XXX)"),
    _smell("hardcoded_url", "Hardcoded URL in source code",
           "medium", r"""(?:['"])https?://[^\s'"]+(?:['"])"""),
    # Multi-line detectors (no regex pattern)
    _smell("empty_except", "Empty except block (except: pass)", "high"),
    _smell("swallowed_error", "Catch block that only logs (swallowed error)", "high"),
    # AST-based detectors (no regex pattern)
    _smell("monster_function", "Monster function (>150 LOC)", "high"),
    _smell("dead_function", "Dead function (body is only pass/return)", "medium"),
    _smell("inline_class", "Class defined inside a function", "medium"),
    _smell("deferred_import", "Function-level import (possible circular import workaround)", "low"),
]


def _match_is_in_string(line: str, match_start: int) -> bool:
    """Check if a regex match position falls inside a string literal or comment."""
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

    for filepath in files:
        try:
            p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
            content = p.read_text()
            lines = content.splitlines()
        except (OSError, UnicodeDecodeError):
            continue

        for check in SMELL_CHECKS:
            if check["pattern"] is None:
                continue
            for i, line in enumerate(lines):
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
        if not re.match(r"except\s*(?:\w|:)", stripped) and stripped != "except:":
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


def _detect_ast_smells(filepath: str, content: str, smell_counts: dict[str, list]):
    """Detect AST-based code smells by dispatching to focused detectors."""
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _detect_monster_functions(filepath, node, smell_counts)
            _detect_dead_functions(filepath, node, smell_counts)
            _detect_deferred_imports(filepath, node, smell_counts)
            _detect_inline_classes(filepath, node, smell_counts)


def _detect_monster_functions(filepath: str, node: ast.AST, smell_counts: dict[str, list]):
    """Flag functions longer than 150 LOC."""
    if not (hasattr(node, "end_lineno") and node.end_lineno):
        return
    loc = node.end_lineno - node.lineno + 1
    if loc > 150:
        smell_counts["monster_function"].append({
            "file": filepath, "line": node.lineno, "content": f"{node.name}() — {loc} LOC",
        })


def _is_return_none(stmt: ast.AST) -> bool:
    """Check if a statement is `return` or `return None`."""
    if not isinstance(stmt, ast.Return):
        return False
    return stmt.value is None or (isinstance(stmt.value, ast.Constant) and stmt.value.value is None)


def _is_docstring(stmt: ast.AST) -> bool:
    return isinstance(stmt, ast.Expr) and isinstance(stmt.value, (ast.Constant, ast.JoinedStr))


def _detect_dead_functions(filepath: str, node: ast.AST, smell_counts: dict[str, list]):
    """Flag functions whose body is only pass, return, or return None."""
    if node.decorator_list:
        return
    body = node.body
    if len(body) == 1:
        stmt = body[0]
        if isinstance(stmt, ast.Pass) or _is_return_none(stmt):
            smell_counts["dead_function"].append({
                "file": filepath, "line": node.lineno,
                "content": f"{node.name}() — body is only {ast.dump(stmt)[:40]}",
            })
    elif len(body) == 2:
        first, second = body
        if not _is_docstring(first):
            return
        if isinstance(second, ast.Pass):
            desc = "docstring + pass"
        elif _is_return_none(second):
            desc = "docstring + return None"
        else:
            return
        smell_counts["dead_function"].append({
            "file": filepath, "line": node.lineno, "content": f"{node.name}() — {desc}",
        })


def _detect_deferred_imports(filepath: str, node: ast.AST, smell_counts: dict[str, list]):
    """Flag function-level imports (possible circular import workarounds)."""
    _SKIP_MODULES = ("typing", "typing_extensions", "__future__")
    for child in ast.walk(node):
        if not isinstance(child, (ast.Import, ast.ImportFrom)) or child.lineno <= node.lineno:
            continue
        module = getattr(child, "module", None) or ""
        if module in _SKIP_MODULES:
            continue
        names = ", ".join(a.name for a in child.names[:3])
        if len(child.names) > 3:
            names += f", +{len(child.names) - 3}"
        smell_counts["deferred_import"].append({
            "file": filepath, "line": child.lineno,
            "content": f"import {module or names} inside {node.name}()",
        })
        break  # Only flag once per function


def _detect_inline_classes(filepath: str, node: ast.AST, smell_counts: dict[str, list]):
    """Flag classes defined inside functions."""
    for child in node.body:
        if isinstance(child, ast.ClassDef):
            smell_counts["inline_class"].append({
                "file": filepath, "line": child.lineno,
                "content": f"class {child.name} defined inside {node.name}()",
            })
