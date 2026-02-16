"""Backward-compat TypeScript move helpers.

Language-specific implementation now lives in `lang/typescript/move.py`.
"""

from ..lang.typescript.move import (
    _compute_ts_specifiers,
    _strip_ts_ext,
    find_ts_replacements,
    find_ts_self_replacements,
)

__all__ = [
    "_strip_ts_ext",
    "_compute_ts_specifiers",
    "find_ts_replacements",
    "find_ts_self_replacements",
]
