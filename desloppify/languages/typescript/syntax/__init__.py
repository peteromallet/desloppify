"""Shared TypeScript syntax helpers used across detectors and fixers."""

_TS_SYNTAX_SHIM = __name__

from desloppify.languages.typescript.syntax.scanner import scan_code

__all__ = ["scan_code"]
