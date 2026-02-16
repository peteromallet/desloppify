"""C#-specific test coverage heuristics and mappings."""

from __future__ import annotations

import os
import re


USING_RE = re.compile(r"^\s*using\s+([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*;", re.MULTILINE)

ASSERT_PATTERNS = [
    re.compile(p) for p in [
        r"\bAssert\.\w+\(",
        r"\bShould\(\)\.\w+\(",
        r"\bFluentAssertions\b",
    ]
]
MOCK_PATTERNS = [
    re.compile(p) for p in [
        r"\bMock<",
        r"\bSubstitute\.For<",
        r"\bFakeItEasy\b",
    ]
]
SNAPSHOT_PATTERNS: list[re.Pattern[str]] = []
TEST_FUNCTION_RE = re.compile(r"(?m)^\s*\[(?:Fact|Theory|Test(?:Method|Case)?)\]")
BARREL_BASENAMES: set[str] = set()


def has_testable_logic(_filepath: str, content: str) -> bool:
    """Return True when a file appears to include runtime logic."""
    return bool(re.search(r"\b(?:class|record|struct)\b|\b(?:public|private|protected|internal)\b.*\(", content))


def resolve_import_spec(_spec: str, _test_path: str, _production_files: set[str]) -> str | None:
    """C# import spec resolution is namespace-based and handled by fallback mapping."""
    return None


def resolve_barrel_reexports(_filepath: str, _production_files: set[str]) -> set[str]:
    """C# has no barrel-file re-export expansion for coverage mapping."""
    return set()


def parse_test_import_specs(content: str) -> list[str]:
    """Extract using directives from C# test content."""
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
    """Strip C-style comments for test quality analysis."""
    content = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    return re.sub(r"//.*$", "", content, flags=re.MULTILINE)
