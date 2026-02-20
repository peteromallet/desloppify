"""Extractors for language plugin scaffolding."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

from desloppify.engine.detectors.base import FunctionInfo
from desloppify.utils import PROJECT_ROOT, find_source_files

logger = logging.getLogger(__name__)

_GO_FUNC_RE = re.compile(
    r"^\s*func\s+(?:\([^)]+\)\s+)?(?P<name>\w+)(?:\[[^\]]+\])?\s*\("
)


def extract_go_functions(filepath: Path | str) -> list[FunctionInfo]:
    """Extract function-like items from one Go file."""
    source = Path(filepath)
    read_path = source if source.is_absolute() else PROJECT_ROOT / source
    try:
        content = read_path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        logger.debug("Skipping unreadable Go file %s: %s", filepath, exc)
        return []

    lines = content.splitlines()
    functions: list[FunctionInfo] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        m = _GO_FUNC_RE.match(line)
        if m:
            name = m.group("name")
            start_line = i
            brace_depth = 0
            found_open = False
            in_backticks = False
            in_block_comment = False
            j = i
            while j < len(lines):
                ln = lines[j]
                k = 0
                while k < len(ln):
                    ch = ln[k]
                    nxt = ln[k+1] if k + 1 < len(ln) else ""
                    
                    if in_block_comment:
                        if ch == '*' and nxt == '/':
                            in_block_comment = False
                            k += 2
                        else:
                            k += 1
                        continue
                        
                    if in_backticks:
                        if ch == '`':
                            in_backticks = False
                        k += 1
                        continue

                    if ch == '`':
                        in_backticks = True
                        k += 1
                    elif ch in ('"', "'"):
                        quote = ch
                        k += 1
                        while k < len(ln):
                            if ln[k] == '\\':
                                k += 2
                                continue
                            if ln[k] == quote:
                                k += 1
                                break
                            k += 1
                    elif ch == '/' and nxt == '/':
                        break
                    elif ch == '/' and nxt == '*':
                        in_block_comment = True
                        k += 2
                    elif ch == '{':
                        brace_depth += 1
                        found_open = True
                        k += 1
                    elif ch == '}':
                        brace_depth -= 1
                        k += 1
                    else:
                        k += 1
                if found_open and brace_depth <= 0:
                    break
                j += 1
                
            if found_open and j > start_line:
                body_lines = lines[start_line : j + 1]
                body = "\n".join(body_lines)
                normalized = normalize_go_body(body)
                
                # We can skip complex param extraction for Go in MVP
                params = [] 
                
                if len(normalized.splitlines()) >= 3:
                    functions.append(
                        FunctionInfo(
                            name=name,
                            file=str(filepath),
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


def extract_functions(path: Path) -> list[FunctionInfo]:
    """Extract function-like items from all Go files below a directory."""
    functions: list[FunctionInfo] = []
    for filepath in find_source_files(path, [".go"]):
        functions.extend(extract_go_functions(filepath))
    return functions


def normalize_go_body(body: str) -> str:
    lines = body.splitlines()
    normalized = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("//") or stripped.startswith("/*") or stripped.startswith("*"):
            continue
        if "fmt." in stripped or "log." in stripped:
            continue
        normalized.append(stripped)
    return "\n".join(normalized)
