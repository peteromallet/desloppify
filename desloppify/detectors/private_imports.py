"""Compatibility wrapper for Python private-import detection.

Language-specific implementation lives in `lang/python/detectors/private_imports.py`.
"""

from __future__ import annotations

from ..lang.python.detectors.private_imports import detect_private_imports

__all__ = ["detect_private_imports"]

