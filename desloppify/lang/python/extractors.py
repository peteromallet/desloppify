"""Python extraction: function bodies, class structure, param patterns."""

import hashlib
import re
from pathlib import Path

from ...detectors.base import ClassInfo, FunctionInfo
from ...detectors.passthrough import classify_params, classify_passthrough_tier
from ...utils import PROJECT_ROOT, find_py_files


def _read_file(filepath: str) -> str | None:
    """Read a file, returning None on error."""
    p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
    try:
        return p.read_text()
    except (OSError, UnicodeDecodeError):
        return None


def _find_block_end(lines: list[str], start: int, base_indent: int,
                    limit: int | None = None) -> int:
    """Find end of an indented block. Returns first line at or below base_indent."""
    end = limit if limit is not None else len(lines)
    j = start
    while j < end:
        if lines[j].strip() == "":
            j += 1
            continue
        if len(lines[j]) - len(lines[j].lstrip()) <= base_indent:
            break
        j += 1
    return j


def _find_signature_end(lines: list[str], start: int) -> int | None:
    """Find the line where a function signature closes (')' then ':'). None if not found."""
    for j in range(start, len(lines)):
        lt = lines[j]
        if ")" in lt and ":" in lt[lt.rindex(")") + 1:]:
            return j
        if j > start and lt.strip().endswith(":"):
            return j
    return None


def extract_py_functions(filepath: str) -> list[FunctionInfo]:
    """Extract function bodies from a Python file using indentation-based boundaries."""
    content = _read_file(filepath)
    if content is None:
        return []

    lines = content.splitlines()
    functions = []
    fn_re = re.compile(r"^(\s*)(?:async\s+)?def\s+(\w+)\s*\(")

    i = 0
    while i < len(lines):
        m = fn_re.match(lines[i])
        if not m:
            i += 1
            continue

        fn_indent = len(m.group(1))
        name = m.group(2)
        start_line = i

        # Find end of multi-line signature (closing ')' followed by ':')
        j = _find_signature_end(lines, i)
        if j is None:
            i += 1
            continue

        # Extract params from multi-line signature
        sig_text = "\n".join(lines[start_line:j + 1])
        open_paren = sig_text.index("(")
        close_paren = sig_text.rindex(")")
        param_str = sig_text[open_paren + 1:close_paren]
        params = extract_py_params(param_str)

        # Find body extent: all lines indented past fn_indent, trim trailing blanks
        block_end = _find_block_end(lines, j + 1, fn_indent)
        end_line = block_end
        while end_line > j + 1 and not lines[end_line - 1].strip():
            end_line -= 1
        body = "\n".join(lines[start_line:end_line])
        normalized = normalize_py_body(body)

        if len(normalized.splitlines()) >= 3:
            functions.append(FunctionInfo(
                name=name, file=filepath, line=start_line + 1,
                end_line=end_line, loc=end_line - start_line, body=body,
                normalized=normalized,
                body_hash=hashlib.md5(normalized.encode()).hexdigest(),
                params=params,
            ))
        i = end_line

    return functions


def normalize_py_body(body: str) -> str:
    """Normalize a Python function body: strip docstrings, comments, print/logging."""
    lines = body.splitlines()
    normalized = []
    in_docstring = False
    docstring_quote = None

    for line in lines:
        stripped = line.strip()

        if in_docstring:
            if docstring_quote and docstring_quote in stripped:
                in_docstring = False
            continue

        if stripped.startswith('"""') or stripped.startswith("'''"):
            docstring_quote = stripped[:3]
            if stripped.count(docstring_quote) >= 2:
                continue
            in_docstring = True
            continue

        if not stripped or stripped.startswith("#"):
            continue

        # Strip inline comments
        cp = stripped.find("  #")
        if cp > 0:
            stripped = stripped[:cp].rstrip()

        if re.match(r"(?:print\s*\(|(?:logging|logger|log)\.\w+\s*\()", stripped):
            continue
        if stripped:
            normalized.append(stripped)

    return "\n".join(normalized)


def extract_py_classes(path: Path) -> list[ClassInfo]:
    """Extract Python classes with method/attribute/base-class metrics (>=50 LOC)."""
    results = []
    for filepath in find_py_files(path):
        content = _read_file(filepath)
        if content is None:
            continue
        results.extend(_extract_classes_from_file(filepath, content.splitlines()))
    return results


def _extract_classes_from_file(filepath: str, lines: list[str]) -> list[ClassInfo]:
    """Extract ClassInfo objects from a single Python file."""
    results = []
    class_re = re.compile(r"^class\s+(\w+)\s*(?:\(([^)]*)\))?\s*:")

    i = 0
    while i < len(lines):
        m = class_re.match(lines[i])
        if not m:
            i += 1
            continue

        class_name = m.group(1)
        bases = m.group(2) or ""
        class_start = i
        class_indent = len(lines[i]) - len(lines[i].lstrip())
        class_end = _find_block_end(lines, i + 1, class_indent)
        class_loc = class_end - class_start

        if class_loc < 50:
            i = class_end
            continue

        methods = _extract_methods(lines, class_start + 1, class_end, class_indent)
        attributes = _extract_init_attributes(lines, class_start, class_end)
        base_list = [b.strip() for b in bases.split(",") if b.strip()] if bases else []
        non_mixin_bases = [b for b in base_list
                           if not b.endswith("Mixin") and b not in ("object", "ABC")]

        results.append(ClassInfo(
            name=class_name, file=filepath, line=class_start + 1,
            loc=class_loc, methods=methods, attributes=attributes,
            base_classes=non_mixin_bases,
        ))
        i = class_end

    return results


def _extract_methods(lines: list[str], start: int, end: int,
                     class_indent: int) -> list[FunctionInfo]:
    """Extract methods from a class body as FunctionInfo objects."""
    methods = []
    method_re = re.compile(r"^\s+(?:async\s+)?def\s+(\w+)")

    i = start
    while i < end:
        m = method_re.match(lines[i])
        if not m:
            i += 1
            continue

        method_indent = len(lines[i]) - len(lines[i].lstrip())
        method_start = i
        j = _find_block_end(lines, i + 1, method_indent, limit=end)
        methods.append(FunctionInfo(
            name=m.group(1), file="", line=method_start + 1,
            end_line=j, loc=j - method_start, body="",
        ))
        i = j

    return methods


def _extract_init_attributes(lines: list[str], class_start: int,
                              class_end: int) -> list[str]:
    """Extract self.x = ... attribute names from __init__."""
    attrs = set()
    in_init = False
    init_indent = 0

    for k in range(class_start, class_end):
        stripped = lines[k].strip()
        if re.match(r"def\s+__init__\s*\(", stripped):
            in_init = True
            init_indent = len(lines[k]) - len(lines[k].lstrip())
            continue
        if in_init:
            if lines[k].strip() and len(lines[k]) - len(lines[k].lstrip()) <= init_indent:
                in_init = False
                continue
            for attr_m in re.finditer(r"self\.(\w+)\s*=", lines[k]):
                attrs.add(attr_m.group(1))

    return sorted(attrs)


def extract_py_params(param_str: str) -> list[str]:
    """Extract parameter names from a Python function signature."""
    params = []
    for token in " ".join(param_str.split()).split(","):
        token = token.strip()
        if not token or token in ("self", "cls"):
            continue
        name = token.lstrip("*").split(":")[0].split("=")[0].strip()
        if name and name.isidentifier():
            params.append(name)
    return params


def py_passthrough_pattern(name: str) -> str:
    """Match same-name keyword arg: param=param in a function call."""
    escaped = re.escape(name)
    return rf"\b{escaped}\s*=\s*{escaped}\b"


_PY_DEF_RE = re.compile(r"^def\s+(\w+)\s*\(", re.MULTILINE)


def detect_passthrough_functions(path: Path) -> list[dict]:
    """Detect Python functions where most params are same-name forwarded."""
    entries = []
    for filepath in find_py_files(path):
        content = _read_file(filepath)
        if content is None:
            continue

        for m in _PY_DEF_RE.finditer(content):
            name = m.group(1)
            # Track paren depth to find matching close-paren (handles nested parens)
            depth = 1
            i = m.end()
            while i < len(content) and depth > 0:
                ch = content[i]
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                i += 1
            if depth != 0:
                continue
            param_str = content[m.end():i - 1]
            params = extract_py_params(param_str)
            if len(params) < 4:
                continue

            # Skip past return annotation and colon to get function body
            rest_after_paren = content[i:]
            colon_m = re.search(r":", rest_after_paren)
            if not colon_m:
                continue
            rest = rest_after_paren[colon_m.end():]
            bm = re.search(r"\n(?=[^\s\n#])", rest)
            body = rest[:bm.start()] if bm else rest

            has_kwargs_spread = bool(re.search(r"\*\*kwargs\b", body))
            pt, direct = classify_params(
                params, body, py_passthrough_pattern, occurrences_per_match=2)

            if len(pt) < 4 and not has_kwargs_spread:
                continue

            ratio = len(pt) / len(params)
            classification = classify_passthrough_tier(
                len(pt), ratio, has_spread=has_kwargs_spread)
            if classification is None:
                continue
            tier, confidence = classification

            entries.append({
                "file": filepath, "function": name,
                "total_params": len(params), "passthrough": len(pt),
                "direct": len(direct), "ratio": round(ratio, 2),
                "line": content[:m.start()].count("\n") + 1,
                "tier": tier, "confidence": confidence,
                "passthrough_params": sorted(pt),
                "direct_params": sorted(direct),
                "has_kwargs_spread": has_kwargs_spread,
            })

    return sorted(entries, key=lambda e: (-e["passthrough"], -e["ratio"]))
