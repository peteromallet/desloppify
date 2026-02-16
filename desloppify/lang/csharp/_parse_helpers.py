"""Shared parsing helpers for C# extractor routines."""

from __future__ import annotations

import re

_CSHARP_MODIFIERS = {
    "public",
    "private",
    "protected",
    "internal",
    "static",
    "virtual",
    "override",
    "abstract",
    "sealed",
    "partial",
    "async",
    "extern",
    "unsafe",
    "new",
    "required",
}


def find_matching_brace(content: str, open_pos: int) -> int | None:
    """Return index of matching '}' for a '{' at ``open_pos``."""
    depth = 0
    in_string: str | None = None
    escape = False
    for i in range(open_pos, len(content)):
        ch = content[i]
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == in_string:
                in_string = None
            continue
        if ch in ("'", '"'):
            in_string = ch
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def find_expression_end(content: str, start_pos: int) -> int | None:
    """Find terminating semicolon for an expression-bodied method."""
    round_depth = 0
    curly_depth = 0
    square_depth = 0
    in_string: str | None = None
    escape = False

    for i in range(start_pos, len(content)):
        ch = content[i]
        if in_string:
            if escape:
                escape = False
                continue
            if ch == "\\":
                escape = True
                continue
            if ch == in_string:
                in_string = None
            continue
        if ch in ("'", '"'):
            in_string = ch
            continue
        if ch == "(":
            round_depth += 1
        elif ch == ")":
            round_depth = max(0, round_depth - 1)
        elif ch == "{":
            curly_depth += 1
        elif ch == "}":
            curly_depth = max(0, curly_depth - 1)
        elif ch == "[":
            square_depth += 1
        elif ch == "]":
            square_depth = max(0, square_depth - 1)
        elif ch == ";" and round_depth == 0 and curly_depth == 0 and square_depth == 0:
            return i
    return None


def split_params(param_str: str) -> list[str]:
    """Split parameter list by comma while respecting nested generic/function syntax."""
    parts: list[str] = []
    current: list[str] = []
    depth = 0
    for ch in param_str:
        if ch in ("<", "(", "[", "{"):
            depth += 1
            current.append(ch)
        elif ch in (">", ")", "]", "}"):
            depth = max(0, depth - 1)
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def extract_csharp_params(param_str: str) -> list[str]:
    """Extract parameter names from a C# method signature fragment."""
    names: list[str] = []
    for raw in split_params(param_str):
        token = raw.strip()
        if not token:
            continue
        token = re.sub(r"^(?:this|params|ref|out|in|required)\s+", "", token)
        token = token.split("=")[0].strip()
        parts = [p for p in token.split() if p]
        if not parts:
            continue
        name = parts[-1].strip()
        if name.startswith("@"):
            name = name[1:]
        if re.match(r"^[A-Za-z_]\w*$", name):
            names.append(name)
    return names


def extract_csharp_return_annotation(signature_head: str, name: str) -> str | None:
    """Extract method return annotation from a declaration head."""
    marker = f"{name}("
    idx = signature_head.rfind(marker)
    if idx < 0:
        return None
    prefix = signature_head[:idx].strip()
    if not prefix:
        return None
    tokens = [t for t in prefix.split() if t and t not in _CSHARP_MODIFIERS]
    if not tokens:
        return None
    annotation = tokens[-1].strip()
    return annotation or None
