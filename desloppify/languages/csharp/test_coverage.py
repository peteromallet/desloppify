"""C#-specific test coverage heuristics and mappings."""

from __future__ import annotations

import os
import re

from desloppify.languages.csharp.detectors.deps_support_metadata import (
    parse_file_metadata,
    parse_file_symbols,
)

ALLOW_MODULE_NAME_FALLBACK = False

USING_RE = re.compile(
    r"^\s*(?:global\s+)?using\s+static\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;", re.MULTILINE
)

ASSERT_PATTERNS = [
    re.compile(p)
    for p in [
        r"\bAssert\.\w+\(",
        r"\bShould\(\)\.\w+\(",
        r"\bFluentAssertions\b",
    ]
]
MOCK_PATTERNS = [
    re.compile(p)
    for p in [
        r"\bMock<",
        r"\bSubstitute\.For<",
        r"\bFakeItEasy\b",
    ]
]
SNAPSHOT_PATTERNS: list[re.Pattern[str]] = []
TEST_FUNCTION_RE = re.compile(r"(?m)^\s*\[(?:Fact|Theory|Test(?:Method|Case)?)\]")
BARREL_BASENAMES: set[str] = set()


def has_testable_logic(filepath: str, content: str) -> bool:
    """Return True when a file appears to include runtime logic."""
    del filepath
    return bool(
        re.search(
            r"\b(?:class|record|struct)\b|\b(?:public|private|protected|internal)\b.*\(",
            content,
        )
    )


def resolve_import_spec(
    spec: str, test_path: str, production_files: set[str]
) -> str | None:
    """Resolve an explicit static using to the file declaring that qualified type."""
    del test_path
    spec = spec.strip()
    if not spec:
        return None

    for candidate in production_files:
        namespace, _usings, _is_entrypoint = parse_file_metadata(candidate)
        declared_types, _identifiers, _extensions = parse_file_symbols(candidate)
        prefix = f"{namespace}." if namespace else ""
        if any(spec == prefix + name for name in declared_types):
            return candidate
    return None


def resolve_barrel_reexports(_filepath: str, _production_files: set[str]) -> set[str]:
    """C# has no barrel-file re-export expansion for coverage mapping."""
    return set()


def parse_test_import_specs(content: str) -> list[str]:
    """Extract explicit type imports for source-based coverage supplementation.

    Ordinary namespace imports and aliases require the dependency graph's symbol
    resolution. A namespace leaf matching a filename does not establish coverage.
    """
    return [m.group(1) for m in USING_RE.finditer(content)]


def map_test_to_source(test_path: str, production_set: set[str]) -> str | None:
    """Map a C# test file path to a production file by naming convention."""
    basename = os.path.basename(test_path)
    dirname = os.path.dirname(test_path)
    parent = os.path.dirname(dirname)

    candidates: list[str] = []
    src = basename.replace(".Tests.", ".").replace(".Test.", ".")
    if src.endswith("Tests.cs"):
        src = src[:-8] + ".cs"
    elif src.endswith("Test.cs"):
        src = src[:-7] + ".cs"
    candidates.append(os.path.join(dirname, src))
    if parent:
        candidates.append(os.path.join(parent, src))

    if os.path.basename(dirname).lower() in ("tests", "test") and parent:
        candidates.append(os.path.join(parent, basename))

    for prod in production_set:
        prod_base = os.path.basename(prod)
        for c in candidates:
            if os.path.basename(c) == prod_base and prod in production_set:
                return prod

    for c in candidates:
        if c in production_set:
            return c

    return None


def strip_test_markers(basename: str) -> str | None:
    """Strip C# test naming markers to derive a source basename."""
    out = basename.replace(".Tests.", ".").replace(".Test.", ".")
    if out.endswith("Tests.cs"):
        return out[:-8] + ".cs"
    if out.endswith("Test.cs"):
        return out[:-7] + ".cs"
    return out


def strip_comments(content: str) -> str:
    """Strip C-style comments while preserving quoted string content."""
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

        if ch in {'"', "'"}:
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
