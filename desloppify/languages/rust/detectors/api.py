"""Rust API-shape and public-surface policy detectors."""

from __future__ import annotations

import re
from pathlib import Path

from desloppify.base.discovery.file_paths import resolve_path
from desloppify.languages.rust.support import (
    describe_rust_file,
    find_rust_files,
    has_public_api_markers,
    is_publishable_package,
    read_text_or_none,
    strip_rust_comments,
)

from ._shared import (
    _ENUM_VARIANT_RE,
    _GETTER_RE,
    _INTO_RE,
    _NON_EXHAUSTIVE_RE,
    _PUBLIC_ERROR_RE,
    _PUBLIC_FIELD_RE,
    _USE_STATEMENT_RE,
    _WRAPPER_GETTER_NAMES,
    _argument_count,
    _entry,
    _group_files_by_manifest,
    _has_manual_thread_contract,
    _has_public_panic_path,
    _has_python_binding_attrs,
    _has_thread_assertion,
    _is_internal_module,
    _is_library_api_file,
    _is_test_content,
    _iter_public_functions,
    _iter_public_types,
    _line_number,
    _looks_like_ffi_surface,
    _looks_like_plain_getter,
    _should_skip_future_proofing,
    _starts_with_same_crate_import,
)


def detect_import_hygiene(path: Path) -> tuple[list[dict], int]:
    """Flag same-crate imports that should use `crate::...`."""
    entries: list[dict] = []
    files = find_rust_files(path)
    for filepath in files:
        absolute = Path(resolve_path(filepath))
        content = read_text_or_none(absolute)
        if content is None:
            continue

        context = describe_rust_file(absolute)
        crate_name = context.crate_name
        if not crate_name or not _is_internal_module(context):
            continue

        stripped = strip_rust_comments(content, preserve_lines=True)
        for match in _USE_STATEMENT_RE.finditer(stripped):
            statement = match.group(1).strip()
            if not _starts_with_same_crate_import(statement, crate_name):
                continue
            line = _line_number(stripped, match.start())
            entries.append(
                _entry(
                    absolute,
                    line=line,
                    name=f"crate_import::{line}",
                    summary=f"Use `crate::` for same-crate imports instead of `{crate_name}::`",
                    tier=2,
                    confidence="high",
                    detail=dict(crate_name=crate_name, statement=statement),
                )
            )
    return entries, len(files)


def detect_public_api_conventions(path: Path) -> tuple[list[dict], int]:
    """Flag high-confidence public API naming mismatches."""
    entries: list[dict] = []
    files = find_rust_files(path)
    for filepath in files:
        absolute = Path(resolve_path(filepath))
        content = read_text_or_none(absolute)
        if content is None:
            continue
        context = describe_rust_file(absolute)
        if not _is_library_api_file(context) or not has_public_api_markers(content):
            continue

        for block in _iter_public_functions(content):
            if _has_python_binding_attrs(block.attrs):
                continue
            if block.name in _WRAPPER_GETTER_NAMES:
                continue
            if _GETTER_RE.match(block.name) and _looks_like_plain_getter(block):
                entries.append(
                    _entry(
                        absolute,
                        line=block.line,
                        name=f"getter::{block.name}",
                        summary=(
                            f"Public getter `{block.name}` uses a `get_` prefix; idiomatic Rust getters are usually bare names"
                        ),
                        tier=3,
                        confidence="medium",
                    )
                )
            elif (
                _INTO_RE.match(block.name)
                and block.receiver in {"&self", "&mut self"}
                and _argument_count(block.signature) == 1
            ):
                entries.append(
                    _entry(
                        absolute,
                        line=block.line,
                        name=f"into_ref::{block.name}",
                        summary=(
                            f"Public method `{block.name}` is named `into_*` but borrows `self`; `into_*` is usually by-value in Rust"
                        ),
                        tier=3,
                        confidence="medium",
                    )
                )
    return entries, len(files)


def detect_error_boundaries(path: Path) -> tuple[list[dict], int]:
    """Flag public API error boundaries that lean on app-style error handling."""
    entries: list[dict] = []
    files = find_rust_files(path)
    for filepath in files:
        absolute = Path(resolve_path(filepath))
        content = read_text_or_none(absolute)
        if content is None:
            continue
        context = describe_rust_file(absolute)
        if not _is_library_api_file(context):
            continue
        for block in _iter_public_functions(content):
            if _PUBLIC_ERROR_RE.search(block.signature):
                entries.append(
                    _entry(
                        absolute,
                        line=block.line,
                        name=f"error_type::{block.name}",
                        summary=(
                            f"Public function `{block.name}` exposes an app-style error boundary; prefer a crate-specific error type on public APIs"
                        ),
                        tier=2,
                        confidence="medium",
                    )
                )
            if block.body and _has_public_panic_path(block.body):
                entries.append(
                    _entry(
                        absolute,
                        line=block.line,
                        name=f"panic_path::{block.name}",
                        summary=(
                            f"Public function `{block.name}` contains `unwrap`/`expect`/panic-style control flow on a public path"
                        ),
                        tier=2,
                        confidence="medium",
                    )
                )
    return entries, len(files)


def detect_future_proofing(path: Path) -> tuple[list[dict], int]:
    """Flag brittle public structs/enums that may want `#[non_exhaustive]`."""
    entries: list[dict] = []
    files = find_rust_files(path)
    for filepath in files:
        absolute = Path(resolve_path(filepath))
        content = read_text_or_none(absolute)
        if content is None:
            continue
        context = describe_rust_file(absolute)
        if not _is_library_api_file(context):
            continue
        if not is_publishable_package(context.manifest_dir):
            continue

        for block in _iter_public_types(content):
            if _NON_EXHAUSTIVE_RE.search(block.attrs):
                continue
            if _should_skip_future_proofing(content, block):
                continue
            if block.kind == "struct":
                public_fields = len(_PUBLIC_FIELD_RE.findall(block.body))
                if public_fields >= 2:
                    entries.append(
                        _entry(
                            absolute,
                            line=block.line,
                            name=f"struct::{block.name}",
                            summary=(
                                f"Public struct `{block.name}` exposes {public_fields} public fields without `#[non_exhaustive]`; this hardens its API shape early"
                            ),
                            tier=3,
                            confidence="medium",
                        )
                    )
            elif block.kind == "enum":
                variant_count = len(_ENUM_VARIANT_RE.findall(block.body))
                if variant_count >= 5:
                    entries.append(
                        _entry(
                            absolute,
                            line=block.line,
                            name=f"enum::{block.name}",
                            summary=(
                                f"Public enum `{block.name}` has {variant_count} variants without `#[non_exhaustive]`; adding variants later may become a breaking change"
                            ),
                            tier=3,
                            confidence="low",
                        )
                    )
    return entries, len(files)


def detect_thread_safety_contracts(path: Path) -> tuple[list[dict], int]:
    """Flag manual Send/Sync contracts without visible assertion tests."""
    entries: list[dict] = []
    by_manifest = _group_files_by_manifest(path)
    for _manifest_dir, files in by_manifest.items():
        corpus_parts: list[str] = []
        for filepath in files:
            absolute = Path(resolve_path(filepath))
            content = read_text_or_none(absolute)
            if content is None:
                continue
            if _is_test_content(absolute, content):
                corpus_parts.append(content)
        corpus = "\n".join(corpus_parts)
        for filepath in files:
            absolute = Path(resolve_path(filepath))
            content = read_text_or_none(absolute)
            if content is None:
                continue
            context = describe_rust_file(absolute)
            if not _is_library_api_file(context):
                continue
            for block in _iter_public_types(content):
                if block.kind != "struct":
                    continue
                if _looks_like_ffi_surface(block):
                    continue
                if not _has_manual_thread_contract(content, block.name):
                    continue
                if _has_thread_assertion(corpus, block.name):
                    continue
                entries.append(
                    _entry(
                        absolute,
                        line=block.line,
                        name=f"thread_contract::{block.name}",
                        summary=(
                            f"Public struct `{block.name}` has a manual Send/Sync contract but no visible assertion tests"
                        ),
                        tier=3,
                        confidence="low",
                    )
                )
    return entries, len(find_rust_files(path))


def replace_same_crate_imports(filepath: str) -> tuple[str, int]:
    """Rewrite `use my_crate::...` imports to `use crate::...` in one file."""
    absolute = Path(resolve_path(filepath))
    context = describe_rust_file(absolute)
    crate_name = context.crate_name
    if not crate_name or not _is_internal_module(context):
        return read_text_or_none(absolute) or "", 0

    content = read_text_or_none(absolute)
    if content is None:
        return "", 0

    replacements = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal replacements
        statement = match.group(1)
        count = statement.count(f"{crate_name}::")
        if count == 0:
            return match.group(0)
        replacements += count
        return match.group(0).replace(f"{crate_name}::", "crate::")

    return _USE_STATEMENT_RE.sub(repl, content), replacements


__all__ = [
    "detect_error_boundaries",
    "detect_future_proofing",
    "detect_import_hygiene",
    "detect_public_api_conventions",
    "detect_thread_safety_contracts",
    "replace_same_crate_imports",
]
