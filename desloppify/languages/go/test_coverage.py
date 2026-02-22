"""Go-specific test coverage heuristics and mappings.

Originally contributed by tinker495 (KyuSeok Jung) in PR #128.
"""

from __future__ import annotations

import re

ASSERT_PATTERNS = [
    re.compile(p)
    for p in [
        r"\bt\.Error",
        r"\bt\.Fatal",
        r"\bt\.Fail",
        r"\bassert\.",
        r"\brequire\.",
        r"\bExpect\(",
    ]
]
MOCK_PATTERNS = [
    re.compile(p)
    for p in [
        r"\bgomock\.NewController",
        r"\bmock\.",
        r"\.EXPECT\(\)",
    ]
]
SNAPSHOT_PATTERNS: list[re.Pattern[str]] = []
TEST_FUNCTION_RE = re.compile(r"(?m)^func\s+Test\w+\(.*?\*testing\.T\)")
BARREL_BASENAMES: set[str] = set()


def has_testable_logic(_filepath: str, content: str) -> bool:
    """Return True when a Go file contains func declarations."""
    return bool(re.search(r"(?m)^func\s+", content))


def resolve_import_spec(
    spec: str, _test_path: str, production_files: set[str]
) -> str | None:
    """Go tests use same-package layout, not import spec resolution."""
    return None


def resolve_barrel_reexports(_filepath: str, _production_files: set[str]) -> set[str]:
    return set()


def parse_test_import_specs(_content: str) -> list[str]:
    return []


def map_test_to_source(test_path: str, production_set: set[str]) -> str | None:
    """Map a Go test file to its source counterpart by naming convention."""
    if not test_path.endswith("_test.go"):
        return None
    src = test_path[:-8] + ".go"
    if src in production_set:
        return src
    return None


def strip_test_markers(basename: str) -> str | None:
    """Strip Go test naming marker to derive source basename."""
    if basename.endswith("_test.go"):
        return basename[:-8] + ".go"
    return None


def strip_comments(content: str) -> str:
    """Strip Go comments while preserving string literals."""
    out: list[str] = []
    in_block = False
    in_string: str | None = None
    i = 0
    while i < len(content):
        ch = content[i]
        nxt = content[i + 1] if i + 1 < len(content) else ""

        if in_block:
            if ch == "\n":
                out.append("\n")
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            i += 1
            continue

        if in_string is not None:
            out.append(ch)
            if ch == "\\" and i + 1 < len(content):
                out.append(content[i + 1])
                i += 2
                continue
            if ch == in_string:
                in_string = None
            i += 1
            continue

        if ch in ('"', '`'):
            in_string = ch
            out.append(ch)
            i += 1
            continue

        if ch == "/" and nxt == "*":
            in_block = True
            i += 2
            continue
        if ch == "/" and nxt == "/":
            while i < len(content) and content[i] != "\n":
                i += 1
            continue

        out.append(ch)
        i += 1

    return "".join(out)
