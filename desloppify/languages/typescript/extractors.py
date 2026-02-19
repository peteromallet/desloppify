"""TypeScript/React extraction: function bodies, component hook metrics, prop patterns."""

import hashlib
import logging
import re
from pathlib import Path

from desloppify.engine.detectors.base import FunctionInfo
from desloppify.languages.typescript.extractors_components import (
    detect_passthrough_components,
    extract_props,
    extract_ts_components,
    tsx_passthrough_pattern,
)
from desloppify.utils import PROJECT_ROOT

logger = logging.getLogger(__name__)


def _extract_ts_params(sig: str) -> list[str]:
    """Extract parameter names from a TS function signature string.

    Handles: function foo(a, b: string, c = 1), arrow (a, b) =>,
    destructured ({ a, b }: Props), and rest (...args).
    """
    # Find the param region: outermost parentheses before => or {
    depth = 0
    start = -1
    end = -1
    for idx, ch in enumerate(sig):
        if ch == "(":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = idx
                break

    if start < 0 or end < 0:
        # No parens — single-param arrow function: name => ...
        m = re.search(r"=\s*(\w+)\s*=>", sig)
        if m:
            return [m.group(1)]
        return []

    param_str = sig[start + 1 : end]
    if not param_str.strip():
        return []

    # Handle destructured params: ({ a, b, c }: Props) -> extract inner names
    inner = param_str.strip()
    if inner.startswith("{"):
        brace_end = inner.find("}")
        if brace_end > 0:
            inner_params = inner[1:brace_end]
            return _parse_param_names(inner_params)

    return _parse_param_names(param_str)


def _parse_param_names(param_str: str) -> list[str]:
    """Parse comma-separated param names, stripping types, defaults, and rest syntax."""
    params = []
    # Split by commas, respecting nested angle brackets and parens
    depth = 0
    current: list[str] = []
    for ch in param_str:
        if ch in ("(", "<", "{", "["):
            depth += 1
            current.append(ch)
        elif ch in (")", ">", "}", "]"):
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            params.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        params.append("".join(current))

    names = []
    for token in params:
        token = token.strip()
        if not token:
            continue
        # Strip rest syntax
        if token.startswith("..."):
            token = token[3:]
        # Take name before : (type) or = (default)
        name = re.split(r"[?:=]", token)[0].strip()
        if name and name.isidentifier():
            names.append(name)
    return names


def _extract_ts_return_annotation(sig: str) -> str | None:
    """Extract normalized return annotation from TS/TSX function signatures."""
    # function foo(...): Type {
    m = re.search(r"\)\s*:\s*(.+?)\s*\{", sig, re.DOTALL)
    if not m:
        # const foo = (...): Type =>
        m = re.search(r"\)\s*:\s*(.+?)\s*=>", sig, re.DOTALL)
    if not m:
        return None
    annotation = " ".join(m.group(1).split())
    return annotation or None


def extract_ts_functions(filepath: str) -> list[FunctionInfo]:
    """Extract function/component bodies from a TS/TSX file.

    Uses brace-tracking to determine function boundaries.
    Returns FunctionInfo with normalized body and hash for comparison.
    """
    p = Path(filepath) if Path(filepath).is_absolute() else PROJECT_ROOT / filepath
    try:
        content = p.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug(
            "Skipping unreadable TS file %s in function extraction: %s", filepath, exc
        )
        return []

    lines = content.splitlines()
    functions = []

    # Match: export function X, const X = (...) =>, const X = function
    fn_re = re.compile(
        r"^(?:export\s+)?(?:"
        r"(?:function\s+(\w+))|"
        r"(?:const\s+(\w+)\s*(?::\s*[^=]+?)?\s*=\s*[^;{]*?=>)|"
        r"(?:const\s+(\w+)\s*(?::\s*[^=]+?)?\s*=\s*function)"
        r")"
    )

    i = 0
    while i < len(lines):
        line = lines[i]
        m = fn_re.match(line.strip())
        if m:
            name = m.group(1) or m.group(2) or m.group(3)
            if not name:
                i += 1
                continue

            # Find the function body by tracking braces (skip strings)
            start_line = i
            brace_depth = 0
            found_open = False
            j = i
            while j < len(lines):
                ln = lines[j]
                k = 0
                while k < len(ln):
                    ch = ln[k]
                    if ch in ('"', "'", "`"):
                        # Skip string literal
                        quote = ch
                        k += 1
                        while k < len(ln):
                            if ln[k] == "\\":
                                k += 2
                                continue
                            if ln[k] == quote:
                                break
                            k += 1
                    elif ch == "/" and k + 1 < len(ln) and ln[k + 1] == "/":
                        break  # Rest of line is comment
                    elif ch == "{":
                        brace_depth += 1
                        found_open = True
                    elif ch == "}":
                        brace_depth -= 1
                    k += 1
                if found_open and brace_depth <= 0:
                    break
                j += 1

            if found_open and j > start_line:
                body_lines = lines[start_line : j + 1]
                body = "\n".join(body_lines)
                normalized = normalize_ts_body(body)

                # Extract params from the signature (lines before first {)
                sig_lines = []
                for k in range(start_line, j + 1):
                    sig_lines.append(lines[k])
                    if "{" in lines[k]:
                        break
                sig = "\n".join(sig_lines)
                params = _extract_ts_params(sig)

                if len(normalized.splitlines()) >= 3:
                    functions.append(
                        FunctionInfo(
                            name=name,
                            file=filepath,
                            line=start_line + 1,
                            end_line=j + 1,
                            loc=j - start_line + 1,
                            body=body,
                            normalized=normalized,
                            body_hash=hashlib.md5(normalized.encode()).hexdigest(),
                            params=params,
                        )
                    )
                i = j + 1
                continue
        i += 1

    return functions


def normalize_ts_body(body: str) -> str:
    """Normalize a TS/TSX function body for comparison.

    Strips comments, whitespace, console.log statements.
    """
    lines = body.splitlines()
    normalized = []
    for line in lines:
        stripped = line.strip()
        if (
            not stripped
            or stripped.startswith("//")
            or stripped.startswith("/*")
            or stripped.startswith("*")
        ):
            continue
        if "console." in stripped:
            continue
        normalized.append(stripped)
    return "\n".join(normalized)


__all__ = [
    "_extract_ts_params",
    "_parse_param_names",
    "detect_passthrough_components",
    "extract_props",
    "extract_ts_components",
    "extract_ts_functions",
    "normalize_ts_body",
    "tsx_passthrough_pattern",
]
