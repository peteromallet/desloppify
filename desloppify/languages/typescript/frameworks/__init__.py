"""Framework support for TypeScript projects (Next.js, Vite, etc)."""

from __future__ import annotations

from .detect import detect_primary_ts_framework
from .types import FrameworkCandidate, FrameworkId, PrimaryFrameworkDetection

__all__ = [
    "FrameworkCandidate",
    "FrameworkId",
    "PrimaryFrameworkDetection",
    "detect_primary_ts_framework",
]
