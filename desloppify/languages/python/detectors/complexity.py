"""Python complexity signal compute functions.

Used by ComplexitySignal definitions in __init__.py for the structural phase.
"""

import io
import re
import tokenize
from math import gcd


def compute_max_params(content: str, lines: list[str]) -> tuple[int, str] | None:
    """Find the function with the most parameters. Returns (count, label) or None."""
    def_re = re.compile(r"def\s+\w+\s*\(", re.MULTILINE)
    max_params = 0
    for m in def_re.finditer(content):
        # Track paren depth to find matching close-paren (handles nested parens)
        depth = 1
        start = m.end()
        i = start
        while i < len(content) and depth > 0:
            ch = content[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            i += 1
        if depth != 0:
            continue
        param_str = content[start : i - 1]
        params = [p.strip() for p in param_str.split(",") if p.strip()]
        real_params = [
            p for p in params if p not in ("self", "cls") and not p.startswith("*")
        ]
        if len(real_params) > max_params:
            max_params = len(real_params)
    if max_params > 7:
        return max_params, f"function with {max_params} params"
    return None


def _detect_indent_unit(lines: list[str]) -> int:
    """Detect indentation unit from file content using GCD of indentations."""
    indents = set()
    for line in lines:
        stripped = line.lstrip()
        if stripped and not stripped.startswith("#"):
            indent = len(line) - len(stripped)
            if 0 < indent <= 16:
                indents.add(indent)
    if not indents:
        return 4
    unit = 0
    for i in indents:
        unit = gcd(unit, i)
    return max(unit, 1)


def _tokenized_nesting_depth(content: str) -> int | None:
    """Return Python suite depth, or ``None`` when tokenization cannot finish."""
    depth = 0
    max_depth = 0
    try:
        tokens = tokenize.generate_tokens(io.StringIO(content).readline)
        for token in tokens:
            if token.type == tokenize.INDENT:
                depth += 1
                max_depth = max(max_depth, depth)
            elif token.type == tokenize.DEDENT:
                depth = max(0, depth - 1)
    except (IndentationError, tokenize.TokenError):
        return None
    return max_depth


def compute_nesting_depth(content: str, lines: list[str]) -> tuple[int, str] | None:
    """Find maximum Python suite depth. Returns ``(depth, label)`` or ``None``."""
    max_depth = _tokenized_nesting_depth(content)
    if max_depth is None:
        indent_unit = _detect_indent_unit(lines)
        max_depth = max(
            (
                (len(line) - len(line.lstrip())) // indent_unit
                for line in lines
                if line.strip() and not line.lstrip().startswith("#")
            ),
            default=0,
        )
    if max_depth > 4:
        return max_depth, f"nesting depth {max_depth}"
    return None


def compute_long_functions(content: str, lines: list[str]) -> tuple[int, str] | None:
    """Find functions >80 LOC. Returns (longest_loc, label) or None."""
    results = []
    fn_re = re.compile(r"^(\s*)def\s+(\w+)")

    i = 0
    while i < len(lines):
        m = fn_re.match(lines[i])
        if not m:
            i += 1
            continue

        fn_indent = len(m.group(1))
        fn_name = m.group(2)
        fn_start = i

        j = i + 1
        while j < len(lines):
            if lines[j].strip() == "":
                j += 1
                continue
            line_indent = len(lines[j]) - len(lines[j].lstrip())
            if line_indent <= fn_indent and lines[j].strip():
                break
            j += 1

        fn_loc = j - fn_start
        if fn_loc > 80:
            results.append((fn_name, fn_loc))
        i = j

    if results:
        longest = max(results, key=lambda x: x[1])
        return longest[1], f"long function ({longest[0]}: {longest[1]} LOC)"
    return None
