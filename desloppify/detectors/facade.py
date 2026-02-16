"""Compatibility wrapper for facade detection.

Language-specific logic lives in:
- lang/python/detectors/facade.py
- lang/typescript/detectors/facade.py
"""

from __future__ import annotations

from ..lang.python.detectors.facade import is_py_facade as _is_py_facade
from ..lang.typescript.detectors.facade import is_ts_facade as _is_ts_facade

_FACADE_DETECTORS = {
    "python": "..lang.python.detectors.facade",
    "typescript": "..lang.typescript.detectors.facade",
}


def detect_reexport_facades(
    graph: dict,
    *,
    lang: str,
    max_importers: int = 2,
    file_finder=None,
    path=None,
) -> tuple[list[dict], int]:
    """Dispatch to language-specific facade detector.

    `file_finder` and `path` are retained for backward compatibility.
    """
    _ = (file_finder, path)
    module_path = _FACADE_DETECTORS.get(lang)
    if module_path is None:
        raise ValueError(f"Unsupported language for facade detection: {lang}")

    import importlib

    mod = importlib.import_module(module_path, package="desloppify.detectors")
    return mod.detect_reexport_facades(graph, max_importers=max_importers)

