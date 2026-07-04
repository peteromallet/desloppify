"""Go-specific test coverage heuristics and mappings.

Originally contributed by tinker495 (KyuSeok Jung) in PR #128.
"""

from __future__ import annotations

import os
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
    spec: str, test_path: str, production_files: set[str]
) -> str | None:
    """Best-effort Go import-path to source-file resolution for direct imports."""
    normalized = spec.strip().strip("\"'`").replace("\\", "/").strip("/")
    if not normalized or normalized in {"C", "unsafe"}:
        return None

    segments = [segment for segment in normalized.split("/") if segment]
    if not segments:
        return None

    candidates: list[str] = []
    for idx in range(len(segments)):
        tail = "/".join(segments[idx:])
        if not tail:
            continue
        leaf = tail.split("/")[-1]
        candidates.append(f"{tail}.go")
        candidates.append(f"{tail}/{leaf}.go")

    test_path = test_path.replace("\\", "/").strip()
    if test_path:
        test_dir = os.path.dirname(test_path)
        leaf = segments[-1]
        candidates.append(f"{test_dir}/{leaf}.go")
        parent = os.path.dirname(test_dir)
        if parent:
            candidates.append(f"{parent}/{leaf}.go")

    normalized_production = {
        file_path.replace("\\", "/").strip("/"): file_path for file_path in production_files
    }
    for candidate in candidates:
        normalized_candidate = candidate.replace("\\", "/").strip("/")
        if normalized_candidate in normalized_production:
            return normalized_production[normalized_candidate]
        suffix = f"/{normalized_candidate}"
        for normalized_path, original in normalized_production.items():
            if normalized_path.endswith(suffix):
                return original
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


def map_test_to_sources(test_path: str, production_set: set[str]) -> set[str]:
    """Map a Go test file to every production file in its package.

    Go compiles all files of a directory as one package and `go test`
    reports coverage package-wide: a test file can exercise any identifier
    in its package regardless of which file defines it. Name-pairing alone
    (foo_test.go -> foo.go) therefore under-reports Go coverage and flags
    files as untested_module even when the package's test suite covers
    them (e.g. ingest_test.go covering plan.go, verify.go, run.go).
    """
    if not test_path.endswith("_test.go"):
        return set()
    test_dir = os.path.dirname(test_path)
    return {
        p
        for p in production_set
        if os.path.dirname(p) == test_dir and p.endswith(".go")
    }


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
