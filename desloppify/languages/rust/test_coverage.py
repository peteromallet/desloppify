"""Rust-specific test coverage heuristics and mappings."""

from __future__ import annotations

import re
from pathlib import Path

from desloppify.languages.rust.support import (
    build_workspace_package_index,
    build_production_file_index,
    describe_rust_file,
    find_workspace_root,
    iter_use_specs,
    iter_include_files,
    match_production_candidate,
    normalize_rust_body,
    resolve_barrel_targets,
    resolve_use_spec,
    resolve_include_file,
    read_text_or_none,
    strip_rust_comments,
)

ASSERT_PATTERNS = [
    re.compile(pattern)
    for pattern in [
        r"\bassert!",
        r"\bassert_eq!",
        r"\bassert_ne!",
        r"\bdebug_assert!",
        r"\bmatches!",
        r"\binsta::assert_",
    ]
]
MOCK_PATTERNS = [
    re.compile(pattern)
    for pattern in [
        r"\bmockall::",
        r"\bmockito::",
        r"\bwiremock::",
        r"\bDouble\b",
    ]
]
SNAPSHOT_PATTERNS = [re.compile(r"\binsta::assert_")]
TEST_FUNCTION_RE = re.compile(r"(?m)^\s*#\s*\[\s*test\s*\]")
BARREL_BASENAMES: set[str] = {"lib.rs"}

_INLINE_TEST_RE = re.compile(
    r"(?m)#\s*\[\s*(?:cfg\s*\(\s*test\s*\)|test)\s*\]"
)
_LOGIC_RE = re.compile(
    r"(?m)^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?"
    r"(?:fn|struct|enum|trait|impl)\b"
)


def has_testable_logic(filepath: str, content: str) -> bool:
    """Return True when a Rust file contains runtime logic worth testing."""
    path = filepath.replace("\\", "/")
    if "/tests/" in path or "/examples/" in path or "/benches/" in path:
        return False
    return bool(_LOGIC_RE.search(strip_rust_comments(content)))


def has_inline_tests(_filepath: str, content: str) -> bool:
    """Return True when a Rust file embeds inline unit tests."""
    return bool(_INLINE_TEST_RE.search(content))


def is_runtime_entrypoint(filepath: str, content: str) -> bool:
    """Best-effort Rust runtime entrypoint detection for no-tests classification."""
    normalized = filepath.replace("\\", "/")
    if normalized.endswith("/src/main.rs") or "/src/bin/" in normalized:
        return True
    if normalized.endswith("/build.rs") or normalized == "build.rs":
        return True
    body = normalize_rust_body(content)
    return "fn main(" in body


def resolve_import_spec(
    spec: str, test_path: str, production_files: set[str]
) -> str | None:
    """Resolve Rust `use` specs from test files to production modules."""
    package_index = build_workspace_package_index(find_workspace_root(test_path))
    return resolve_use_spec(spec, test_path, production_files, package_index)


def resolve_barrel_reexports(filepath: str, production_files: set[str]) -> set[str]:
    """Expand Rust facade files such as `lib.rs` to their re-exported modules."""
    package_index = build_workspace_package_index(find_workspace_root(filepath))
    return resolve_barrel_targets(filepath, production_files, package_index)


def parse_test_import_specs(content: str) -> list[str]:
    """Extract Rust test import specs from source text."""
    return iter_use_specs(content)


def expand_direct_test_targets(
    directly_tested: set[str],
    production_files: set[str],
) -> set[str]:
    """Treat textually included Rust source as part of its tested owner.

    ``include!`` does not create a Rust module boundary: the included tokens
    are compiled in the including module. A direct test of that owner is
    therefore also a direct test of every recursively included source file.
    """
    production_index = build_production_file_index(production_files)
    expanded: set[str] = set()
    queue = list(directly_tested)
    visited = set(queue)
    while queue:
        owner = queue.pop()
        content = read_text_or_none(owner)
        if content is None:
            continue
        for include_path in iter_include_files(content):
            target = resolve_include_file(
                include_path,
                owner,
                production_files,
                production_index=production_index,
            )
            if target is not None and target not in visited:
                visited.add(target)
                expanded.add(target)
                queue.append(target)
    return expanded


def map_test_to_source(test_path: str, production_set: set[str]) -> str | None:
    """Map `tests/foo.rs` to `src/foo.rs` or `src/foo/mod.rs` when present."""
    test_file = Path(test_path)
    if test_file.suffix != ".rs":
        return None

    context = describe_rust_file(test_path)
    try:
        rel_to_manifest = Path(test_path).resolve().relative_to(context.manifest_dir)
    except ValueError:
        rel_to_manifest = test_file
    parts = rel_to_manifest.parts
    if not parts or parts[0] != "tests":
        return None

    relative_tail = Path(*parts[1:]) if len(parts) > 1 else Path(test_file.name)
    stem = relative_tail.stem
    parent = relative_tail.parent
    candidates = [
        context.manifest_dir / "src" / parent / f"{stem}.rs",
        context.manifest_dir / "src" / parent / stem / "mod.rs",
        context.manifest_dir / "src" / f"{stem}.rs",
        context.manifest_dir / "src" / stem / "mod.rs",
    ]
    for candidate in candidates:
        resolved = _candidate_matches(candidate, production_set)
        if resolved:
            return resolved
    return None


def strip_test_markers(basename: str) -> str | None:
    """Rust integration tests usually share the same `.rs` basename."""
    if basename.startswith("test_") and basename.endswith(".rs"):
        return basename[len("test_") :]
    if basename.endswith("_test.rs"):
        return f"{basename[:-8]}.rs"
    return None


def strip_comments(content: str) -> str:
    """Strip Rust comments while preserving literals best-effort."""
    return strip_rust_comments(content)


def _candidate_matches(candidate: Path, production_files: set[str]) -> str | None:
    return match_production_candidate(candidate, production_files)


__all__ = [
    "ASSERT_PATTERNS",
    "BARREL_BASENAMES",
    "MOCK_PATTERNS",
    "SNAPSHOT_PATTERNS",
    "TEST_FUNCTION_RE",
    "has_inline_tests",
    "has_testable_logic",
    "expand_direct_test_targets",
    "is_runtime_entrypoint",
    "map_test_to_source",
    "parse_test_import_specs",
    "resolve_barrel_reexports",
    "resolve_import_spec",
    "strip_comments",
    "strip_test_markers",
]
