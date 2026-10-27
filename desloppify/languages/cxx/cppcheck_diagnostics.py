"""Distinguish cppcheck setup/parse failures from reliable code diagnostics."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from desloppify.languages._framework.generic_parts.tool_runner import ToolRunResult

_CONFIGURATION_IDS = frozenset({"missingInclude", "missingIncludeSystem", "unknownMacro"})


def configuration_checked_result(result: ToolRunResult) -> ToolRunResult:
    """Fail the invocation when cppcheck could not understand its translation units.

    Cppcheck can exit zero while reporting missing headers or unsupported macros.
    The security runner retries individual files and preserves regex security
    fallback; returning an error here activates that coverage accounting.
    """
    if result.status == "error":
        return result
    for entry in result.entries:
        message = str(entry.get("message", ""))
        is_missing_include = "Include file:" in message and "not found" in message
        is_unknown_macro = "unknown macro here" in message and "configure" in message
        is_cpp_header_as_c = (
            "invalid C code" in message
            and Path(str(entry.get("file", ""))).suffix.lower() in {".h", ".hh", ".hpp", ".hxx"}
        )
        if entry.get("check_id") in _CONFIGURATION_IDS or is_missing_include or is_unknown_macro or is_cpp_header_as_c:
            return replace(
                result, entries=[], status="error", error_kind="tool_configuration",
                message=f"cppcheck requires include paths, macro definitions or language configuration: {message}",
            )
    return result
