"""Compatibility re-export shim for legacy TypeScript fixer helper imports."""

from __future__ import annotations

from .fixer_io import apply_fixer as _apply_fixer
from .import_rewrite import (
    _collect_import_statement as _collect_import_statement_impl,
    process_unused_import_lines as _process_unused_import_lines,
    remove_symbols_from_import_stmt as _remove_symbols_from_import_stmt,
)
from .syntax_scan import (
    collapse_blank_lines as _collapse_blank_lines,
    extract_body_between_braces as _extract_body_between_braces,
    find_balanced_end as _find_balanced_end,
)


def apply_fixer(*args, **kwargs):
    return _apply_fixer(*args, **kwargs)


def _collect_import_statement(*args, **kwargs):
    return _collect_import_statement_impl(*args, **kwargs)


def process_unused_import_lines(*args, **kwargs):
    return _process_unused_import_lines(*args, **kwargs)


def remove_symbols_from_import_stmt(*args, **kwargs):
    return _remove_symbols_from_import_stmt(*args, **kwargs)


def collapse_blank_lines(*args, **kwargs):
    return _collapse_blank_lines(*args, **kwargs)


def extract_body_between_braces(*args, **kwargs):
    return _extract_body_between_braces(*args, **kwargs)


def find_balanced_end(*args, **kwargs):
    return _find_balanced_end(*args, **kwargs)

__all__ = [
    "_collect_import_statement",
    "apply_fixer",
    "collapse_blank_lines",
    "extract_body_between_braces",
    "find_balanced_end",
    "process_unused_import_lines",
    "remove_symbols_from_import_stmt",
]
