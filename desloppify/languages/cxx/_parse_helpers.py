"""Local parsing helpers for C/C++ extractor routines."""

from __future__ import annotations


def find_matching_brace(content: str, open_pos: int) -> int | None:
    """Return index of matching '}' for a '{' at ``open_pos``."""
    depth = 0
    in_string: str | None = None
    escape = False
    i = open_pos
    length = len(content)
    while i < length:
        ch = content[i]
        if in_string:
            if escape:
                escape = False
                i += 1
                continue
            if ch == "\\":
                escape = True
                i += 1
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue
        if ch in ("'", '"'):
            in_string = ch
            i += 1
            continue
        if ch == "/" and i + 1 < length and content[i + 1] == "*":
            i += 2
            while i + 1 < length:
                if content[i] == "*" and content[i + 1] == "/":
                    i += 2
                    break
                i += 1
            continue
        if ch == "/" and i + 1 < length and content[i + 1] == "/":
            i += 2
            while i < length and content[i] != "\n":
                i += 1
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


__all__ = ["find_matching_brace"]
