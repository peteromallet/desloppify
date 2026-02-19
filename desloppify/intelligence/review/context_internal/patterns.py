"""Shared regex patterns and pattern-based helpers for review context."""

from __future__ import annotations

import re

FUNC_NAME_RE = re.compile(r"(?:function|def|async\s+def|async\s+function)\s+(\w+)")
CLASS_NAME_RE = re.compile(r"(?:class|interface|type)\s+(\w+)")

ERROR_PATTERNS = {
    "try_catch": re.compile(r"\b(?:try\s*\{|try\s*:)"),
    "returns_null": re.compile(r"\breturn\s+(?:null|None|undefined)\b"),
    "result_type": re.compile(r"\b(?:Result|Either|Ok|Err)\b"),
    "throws": re.compile(r"\b(?:throw\s+new|raise\s+\w)"),
}

NAME_PREFIX_RE = re.compile(
    r"^(get|set|is|has|can|should|use|create|make|build|parse|format|"
    r"validate|check|find|fetch|load|save|update|delete|remove|add|"
    r"handle|on|init|setup|render|compute|calculate|transform|convert|"
    r"to|from|with|ensure|assert|process|run|do|manage|execute)"
)

FROM_IMPORT_RE = re.compile(
    r"^(?:from\s+\S+\s+import\s+(.+)|import\s+(.+))$", re.MULTILINE
)


def extract_imported_names(content: str) -> set[str]:
    """Extract imported symbol names from a file's import statements."""
    names: set[str] = set()
    for match in FROM_IMPORT_RE.finditer(content):
        raw = match.group(1) or match.group(2)
        if raw is None:
            continue
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            token = part.split()[0]
            if token.startswith("(") or token == "\\":
                continue
            token = token.strip("()")
            if token.isidentifier():
                names.add(token)
    return names


def default_review_module_patterns(content: str) -> list[str]:
    """Fallback module-pattern extraction used when language hook is absent."""
    out: list[str] = []
    if re.search(r"\bexport\s+default\b", content):
        out.append("default_export")
    if re.search(r"\bexport\s+(?:function|const|class)\b", content):
        out.append("named_export")
    if re.search(r"\bdef\s+\w+", content):
        out.append("functions")
    if re.search(r"^__all__\s*=", content, re.MULTILINE):
        out.append("explicit_api")
    return out

__all__ = [
    "CLASS_NAME_RE",
    "ERROR_PATTERNS",
    "FROM_IMPORT_RE",
    "FUNC_NAME_RE",
    "NAME_PREFIX_RE",
    "default_review_module_patterns",
    "extract_imported_names",
]
