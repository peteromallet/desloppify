"""Python extraction: function bodies, class structure, param patterns."""

import hashlib
import re
from pathlib import Path

from desloppify.engine.detectors.base import FunctionInfo
from desloppify.engine.detectors.passthrough import (
    classify_params,
    classify_passthrough_tier,
)
from desloppify.languages.python.extractors_classes import extract_py_classes
from desloppify.languages.python.extractors_shared import (
    extract_py_params,
    find_block_end,
    read_file,
)
from desloppify.utils import find_py_files


def _find_signature_end(lines: list[str], start: int) -> int | None:
    """Find the line where a function signature closes."""
    for j in range(start, len(lines)):
        lt = lines[j]
        if ")" in lt and ":" in lt[lt.rindex(")") + 1 :]:
            return j
        if j > start and lt.strip().endswith(":"):
            return j
    return None


def _extract_py_return_annotation(sig_text: str) -> str | None:
    """Extract normalized return annotation from a Python signature."""
    m = re.search(r"\)\s*->\s*(.*?)\s*:", sig_text, re.DOTALL)
    if not m:
        return None
    annotation = " ".join(m.group(1).split())
    return annotation or None


def extract_py_functions(filepath: str) -> list[FunctionInfo]:
    """Extract function bodies from a Python file using indentation-based boundaries."""
    content = read_file(filepath)
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
        j = _find_signature_end(lines, i)
        if j is None:
            i += 1
            continue

        # Extract params from multi-line signature
        sig_text = "\n".join(lines[start_line : j + 1])
        open_paren = sig_text.index("(")
        close_paren = sig_text.rindex(")")
        param_str = sig_text[open_paren + 1 : close_paren]
        params = extract_py_params(param_str)

        # Find body extent: all lines indented past fn_indent, trim trailing blanks
        block_end = find_block_end(lines, j + 1, fn_indent)
        end_line = block_end
        while end_line > j + 1 and not lines[end_line - 1].strip():
            end_line -= 1
        body = "\n".join(lines[start_line:end_line])
        normalized = normalize_py_body(body)
        if len(normalized.splitlines()) >= 3:
            functions.append(
                FunctionInfo(
                    name=name,
                    file=filepath,
                    line=start_line + 1,
                    end_line=end_line,
                    loc=end_line - start_line,
                    body=body,
                    normalized=normalized,
                    body_hash=hashlib.md5(normalized.encode()).hexdigest(),
                    params=params,
                )
            )
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
        cp = stripped.find("  #")
        if cp > 0:
            stripped = stripped[:cp].rstrip()
        if re.match(r"(?:print\s*\(|(?:logging|logger|log)\.\w+\s*\()", stripped):
            continue
        if stripped:
            normalized.append(stripped)
    return "\n".join(normalized)


def py_passthrough_pattern(name: str) -> str:
    """Match same-name keyword arg: param=param in a function call."""
    escaped = re.escape(name)
    return rf"\b{escaped}\s*=\s*{escaped}\b"


_PY_DEF_RE = re.compile(r"^def\s+(\w+)\s*\(", re.MULTILINE)


def detect_passthrough_functions(path: Path) -> list[dict]:
    """Detect Python functions where most params are same-name forwarded."""
    entries = []
    for filepath in find_py_files(path):
        content = read_file(filepath)
        if content is None:
            continue
        for m in _PY_DEF_RE.finditer(content):
            name = m.group(1)
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
            param_str = content[m.end() : i - 1]
            params = extract_py_params(param_str)
            if len(params) < 4:
                continue
            rest_after_paren = content[i:]
            colon_m = re.search(r":", rest_after_paren)
            if not colon_m:
                continue
            rest = rest_after_paren[colon_m.end() :]
            bm = re.search(r"\n(?=[^\s\n#])", rest)
            body = rest[: bm.start()] if bm else rest

            has_kwargs_spread = bool(re.search(r"\*\*kwargs\b", body))
            pt, direct = classify_params(
                params, body, py_passthrough_pattern, occurrences_per_match=2
            )

            if len(pt) < 4 and not has_kwargs_spread:
                continue
            ratio = len(pt) / len(params)
            classification = classify_passthrough_tier(
                len(pt), ratio, has_spread=has_kwargs_spread
            )
            if classification is None:
                continue
            tier, confidence = classification

            entries.append(
                {
                    "file": filepath,
                    "function": name,
                    "total_params": len(params),
                    "passthrough": len(pt),
                    "direct": len(direct),
                    "ratio": round(ratio, 2),
                    "line": content[: m.start()].count("\n") + 1,
                    "tier": tier,
                    "confidence": confidence,
                    "passthrough_params": sorted(pt),
                    "direct_params": sorted(direct),
                    "has_kwargs_spread": has_kwargs_spread,
                }
            )

    return sorted(entries, key=lambda e: (-e["passthrough"], -e["ratio"]))


__all__ = [
    "detect_passthrough_functions",
    "extract_py_classes",
    "extract_py_functions",
    "extract_py_params",
    "normalize_py_body",
    "py_passthrough_pattern",
]
