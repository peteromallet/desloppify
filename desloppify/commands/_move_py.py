"""Backward-compat Python move helpers.

Language-specific implementation now lives in `lang/python/move.py`.
"""

from ..lang.python.move import (
    _compute_py_relative_import,
    _has_exact_module,
    _path_to_py_module,
    _replace_exact_module,
    _resolve_py_relative,
    find_py_replacements,
    find_py_self_replacements,
)

__all__ = [
    "_path_to_py_module",
    "_has_exact_module",
    "_replace_exact_module",
    "_resolve_py_relative",
    "_compute_py_relative_import",
    "find_py_replacements",
    "find_py_self_replacements",
]
