"""Rust-specific test coverage heuristics and mappings."""

from __future__ import annotations

import functools
import re
from pathlib import Path, PurePosixPath

from desloppify.languages.rust.support import (
    RustProductionFileIndex,
    build_production_file_index,
    build_workspace_package_index,
    describe_rust_file,
    find_workspace_root,
    iter_mod_targets,
    iter_use_specs,
    match_production_candidate,
    normalize_rust_body,
    read_text_or_none,
    resolve_barrel_targets,
    resolve_mod_declaration,
    resolve_use_spec,
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
    parts = PurePosixPath(path).parts
    if (
        any(part == "tests" or part.endswith("_tests") for part in parts)
        or "/examples/" in path
        or "/benches/" in path
    ):
        return False
    return bool(_LOGIC_RE.search(strip_rust_comments(content)))


def promote_owner_covered_files(
    directly_tested: set[str],
    transitively_tested: set[str],
    production_files: set[str] | None = None,
) -> set[str]:
    """Credit Rust child modules exercised through a tested owner boundary.

    Rust commonly keeps behavioral tests beside ``domain.rs`` while splitting
    its implementation into ``domain/*.rs``. Requiring duplicate test modules
    in every child rewards file locality instead of behavioral coverage. Only
    descendants of a directly tested non-crate-root module are promoted;
    unrelated dependencies remain transitive coverage gaps.
    """
    owner_roots: list[PurePosixPath] = []
    for owner in directly_tested:
        path = PurePosixPath(owner.replace("\\", "/"))
        if path.name in {"lib.rs", "main.rs"}:
            continue
        owner_roots.append(path.parent if path.name == "mod.rs" else path.with_suffix(""))

    declared_owner: dict[str, str] = {}
    direct_declaring_owners: set[str] = set()
    if production_files:
        production_index = _production_index_for(frozenset(production_files))
        for parent in production_files:
            content = read_text_or_none(parent)
            if content is None:
                continue
            for module_name, declared_path in iter_mod_targets(content):
                target = resolve_mod_declaration(
                    module_name,
                    parent,
                    production_files,
                    declared_path=declared_path,
                    production_index=production_index,
                )
                if target:
                    declared_owner[target] = parent
        direct_declaring_owners = {
            owner
            for target in directly_tested
            if (owner := declared_owner.get(target)) is not None
        }

    promoted: set[str] = set()
    for candidate in transitively_tested:
        if declared_owner.get(candidate) in direct_declaring_owners:
            promoted.add(candidate)
            continue
        path = PurePosixPath(candidate.replace("\\", "/"))
        for owner_root in owner_roots:
            try:
                relative = path.relative_to(owner_root)
            except ValueError:
                continue
            if relative.parts:
                promoted.add(candidate)
                break
    return promoted


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
    context = describe_rust_file(test_path)
    package_index = _workspace_package_index_for(context.manifest_dir)
    production_index = _production_index_for(frozenset(production_files))
    return resolve_use_spec(
        spec,
        test_path,
        production_files,
        package_index,
        production_index=production_index,
    )


def resolve_barrel_reexports(filepath: str, production_files: set[str]) -> set[str]:
    """Expand Rust facade files such as `lib.rs` to their re-exported modules."""
    package_index = build_workspace_package_index(find_workspace_root(filepath))
    production_index = _production_index_for(frozenset(production_files))
    return resolve_barrel_targets(
        filepath,
        production_files,
        package_index,
        production_index=production_index,
    )


@functools.lru_cache(maxsize=512)
def _workspace_package_index_for(manifest_dir: Path) -> dict[str, Path]:
    return build_workspace_package_index(find_workspace_root(manifest_dir))


def parse_test_import_specs(content: str) -> list[str]:
    """Extract Rust test import specs from source text."""
    return iter_use_specs(content)


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
    production_index = _production_index_for(frozenset(production_set))
    for candidate in candidates:
        resolved = _candidate_matches(
            candidate,
            production_set,
            production_index=production_index,
        )
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


@functools.lru_cache(maxsize=8)
def _production_index_for(
    production_files: frozenset[str],
) -> RustProductionFileIndex:
    return build_production_file_index(set(production_files))


def _candidate_matches(
    candidate: Path,
    production_files: set[str],
    *,
    production_index: RustProductionFileIndex | None = None,
) -> str | None:
    return match_production_candidate(
        candidate,
        production_files,
        production_index=production_index,
    )


__all__ = [
    "ASSERT_PATTERNS",
    "BARREL_BASENAMES",
    "MOCK_PATTERNS",
    "SNAPSHOT_PATTERNS",
    "TEST_FUNCTION_RE",
    "has_inline_tests",
    "has_testable_logic",
    "is_runtime_entrypoint",
    "map_test_to_source",
    "parse_test_import_specs",
    "promote_owner_covered_files",
    "resolve_barrel_reexports",
    "resolve_import_spec",
    "strip_comments",
    "strip_test_markers",
]
