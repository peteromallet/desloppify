"""Shared Rust tool command strings and JSON diagnostic parsers."""

from __future__ import annotations

import json
import re
import shlex
import subprocess  # nosec B404
from collections.abc import Callable
from pathlib import Path
from typing import Any

from desloppify.languages._framework.generic_parts.tool_runner import (
    SubprocessRun,
    ToolRunResult,
    resolve_command_argv,
    run_tool_result,
)
from desloppify.languages.rust.support import find_workspace_root

CLIPPY_WARNING_CMD = (
    "cargo clippy --workspace --all-targets --all-features --message-format=json "
    "-- -D warnings -W clippy::pedantic -W clippy::cargo -W clippy::unwrap_used "
    "-W clippy::expect_used -W clippy::panic -W clippy::todo -W clippy::unimplemented "
    "2>&1"
)
CARGO_ERROR_CMD = (
    "cargo check --workspace --all-targets --all-features --message-format=json 2>&1"
)
RUSTDOC_WARNING_CMD = (
    "cargo rustdoc --package {package} --all-features --lib --message-format=json "
    "-- -D rustdoc::broken_intra_doc_links "
    "-D rustdoc::private_intra_doc_links "
    "-W rustdoc::missing_crate_level_docs 2>&1"
)
_CARGO_METADATA_CMD = "cargo metadata --format-version=1 --no-deps"
_LIB_TARGET_KINDS = {"lib", "rlib", "dylib", "cdylib", "staticlib", "proc-macro"}
_INLINE_MOD_RE = re.compile(
    r"(?:pub(?:\s*\([^)]*\))?\s+)?mod\s+(?:r#)?(?:[^\W\d]|_)\w*\s*\{"
)


def _pick_primary_span(spans: list[dict[str, Any]]) -> dict[str, Any] | None:
    for span in spans:
        if span.get("is_primary"):
            return span
    return spans[0] if spans else None


def _parse_cargo_messages(
    output: str,
    scan_path: Path,
    *,
    allowed_levels: set[str],
    skip_inline_cfg_test_modules: bool = False,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    inline_test_cache: dict[str, tuple[tuple[int, int], ...]] = {}
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        data = _parse_json_object_line(line)
        if data is None:
            continue
        if data.get("reason") != "compiler-message":
            continue
        message = data.get("message") or {}
        level = str(message.get("level") or "").lower()
        if level not in allowed_levels:
            continue
        span = _pick_primary_span(list(message.get("spans") or []))
        if not span:
            continue
        filename = str(span.get("file_name") or "").strip()
        line_no = span.get("line_start")
        if not filename or not isinstance(line_no, int):
            continue
        if skip_inline_cfg_test_modules and _should_skip_inline_cfg_test_module_diagnostic(
            scan_path,
            filename,
            line_no,
            inline_test_cache,
        ):
            continue
        code = (message.get("code") or {}).get("code") or ""
        rendered = str(message.get("rendered") or message.get("message") or "").strip()
        if not rendered:
            continue
        summary = rendered.splitlines()[0].strip()
        if code and code not in summary:
            summary = f"[{code}] {summary}"
        entries.append(
            {
                "file": filename,
                "line": line_no,
                "message": summary,
            }
        )
    return entries


def _parse_json_object_line(line: str) -> dict[str, Any] | None:
    """Parse one cargo JSON line, ignoring human-readable noise."""
    if not line.startswith("{"):
        return None
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def parse_clippy_messages(output: str, scan_path: Path) -> list[dict[str, Any]]:
    """Parse cargo-clippy diagnostics, including denied warnings."""
    return _parse_cargo_messages(
        output,
        scan_path,
        allowed_levels={"warning", "error"},
        # Inline `#[cfg(test)] mod ...` blocks live in production files, so
        # line-level filtering prevents test-only diagnostics from inflating
        # production debt.
        skip_inline_cfg_test_modules=True,
    )


def _should_skip_inline_cfg_test_module_diagnostic(
    scan_path: Path,
    filename: str,
    line_no: int,
    inline_test_cache: dict[str, tuple[tuple[int, int], ...]],
) -> bool:
    source_file = _resolve_rust_source_file(scan_path, filename)
    if source_file is None:
        return False

    cache_key = str(source_file)
    ranges = inline_test_cache.get(cache_key)
    if ranges is None:
        source_text = _read_source_text(source_file)
        ranges = (
            tuple(_inline_cfg_test_module_line_ranges(source_text))
            if source_text is not None
            else tuple()
        )
        inline_test_cache[cache_key] = ranges

    return any(start <= line_no <= end for start, end in ranges)


def _resolve_rust_source_file(scan_path: Path, filename: str) -> Path | None:
    trimmed = filename.strip()
    if not trimmed or trimmed.startswith("<"):
        return None

    candidate = Path(trimmed)
    resolved = candidate if candidate.is_absolute() else (scan_path / candidate)
    try:
        normalized = resolved.resolve()
    except OSError:
        return None
    if normalized.suffix != ".rs" or not normalized.is_file():
        return None
    return normalized


def _read_source_text(path: Path) -> str | None:
    try:
        return path.read_text(errors="replace")
    except OSError:
        return None


def _inline_cfg_test_module_line_ranges(content: str) -> list[tuple[int, int]]:
    stripped = _strip_comments_preserve_lines(content)
    ranges: list[tuple[int, int]] = []
    cursor = 0
    while True:
        cfg_attr = _find_next_cfg_attribute(stripped, cursor)
        if cfg_attr is None:
            break
        attr_start, attr_end, expression = cfg_attr
        cursor = attr_end
        if not _cfg_expression_requires_test(expression):
            continue

        module = _find_following_inline_module(stripped, attr_end)
        if module is None:
            continue
        module_start, open_brace = module
        close_brace = _find_matching_delimiter(stripped, open_brace, "{", "}")
        if close_brace is None:
            continue
        ranges.append(
            (
                _line_number(stripped, module_start),
                _line_number(stripped, close_brace),
            )
        )
        cursor = close_brace + 1

    return _merge_line_ranges(ranges)


def _find_next_cfg_attribute(content: str, start: int) -> tuple[int, int, str] | None:
    cursor = start
    while True:
        attr_start = content.find("#[", cursor)
        if attr_start == -1:
            return None

        name_start = _skip_whitespace(content, attr_start + 2)
        name, after_name = _parse_identifier(content, name_start)
        if name != "cfg":
            cursor = attr_start + 2
            continue

        after_name = _skip_whitespace(content, after_name)
        if after_name >= len(content) or content[after_name] != "(":
            cursor = attr_start + 2
            continue

        expression_end = _find_matching_delimiter(content, after_name, "(", ")")
        if expression_end is None:
            return None

        expression = content[after_name + 1 : expression_end]
        attr_end = _skip_whitespace(content, expression_end + 1)
        if attr_end >= len(content) or content[attr_end] != "]":
            cursor = attr_start + 2
            continue

        return attr_start, attr_end + 1, expression


def _find_following_inline_module(content: str, start: int) -> tuple[int, int] | None:
    cursor = start
    while cursor < len(content):
        cursor = _skip_whitespace(content, cursor)
        if cursor >= len(content):
            return None
        if content.startswith("///", cursor) or content.startswith("//!", cursor):
            cursor = _line_end(content, cursor)
            continue
        if content.startswith("#[", cursor):
            attr_end = _find_attribute_end(content, cursor)
            if attr_end is None:
                return None
            cursor = attr_end
            continue

        module_match = _INLINE_MOD_RE.match(content, cursor)
        if module_match is None:
            return None
        open_brace = content.find("{", module_match.start(), module_match.end())
        if open_brace == -1:
            return None
        return module_match.start(), open_brace
    return None


def _find_attribute_end(content: str, start: int) -> int | None:
    if not content.startswith("#[", start):
        return None
    depth = 1
    cursor = start + 2
    while cursor < len(content):
        char = content[cursor]
        if content.startswith("//", cursor):
            cursor = _line_end(content, cursor)
            continue
        if content.startswith("/*", cursor):
            cursor = _block_comment_end(content, cursor)
            continue
        if char == '"':
            cursor = _quoted_string_end(content, cursor, '"')
            continue
        if char == "'" and _looks_like_char_literal_start(content, cursor):
            cursor = _quoted_string_end(content, cursor, "'")
            continue
        if char == "r" and _looks_like_raw_string_start(content, cursor):
            cursor = _raw_string_end(content, cursor)
            continue
        if char == "[":
            depth += 1
            cursor += 1
            continue
        elif char == "]":
            depth -= 1
            cursor += 1
            if depth == 0:
                return cursor
            continue
        cursor += 1
    return None


def _cfg_expression_requires_test(expression: str) -> bool:
    requires_test, _ = _parse_cfg_predicate(expression, 0)
    return requires_test


def _parse_cfg_predicate(expression: str, index: int) -> tuple[bool, int]:
    cursor = _skip_whitespace(expression, index)
    name, cursor = _parse_identifier(expression, cursor)
    if name is None:
        return False, cursor

    cursor = _skip_whitespace(expression, cursor)
    if cursor < len(expression) and expression[cursor] == "(":
        close_paren = _find_matching_delimiter(expression, cursor, "(", ")")
        if close_paren is None:
            return False, len(expression)

        args_required: list[bool] = []
        arg_cursor = cursor + 1
        while arg_cursor < close_paren:
            arg_cursor = _skip_whitespace(expression, arg_cursor)
            if arg_cursor >= close_paren:
                break

            arg_required, next_cursor = _parse_cfg_predicate(expression, arg_cursor)
            args_required.append(arg_required)
            if next_cursor <= arg_cursor:
                next_cursor = arg_cursor + 1
            arg_cursor = _skip_whitespace(expression, next_cursor)

            if arg_cursor < close_paren and expression[arg_cursor] == ",":
                arg_cursor += 1
                continue

            while arg_cursor < close_paren and expression[arg_cursor] != ",":
                arg_cursor += 1
            if arg_cursor < close_paren and expression[arg_cursor] == ",":
                arg_cursor += 1

        next_index = close_paren + 1
        if name == "all":
            return any(args_required), next_index
        if name == "any":
            return bool(args_required) and all(args_required), next_index
        if name == "not":
            return False, next_index
        return False, next_index

    if cursor < len(expression) and expression[cursor] == "=":
        return False, _skip_cfg_value(expression, cursor + 1)

    return name == "test", cursor


def _skip_cfg_value(expression: str, index: int) -> int:
    cursor = _skip_whitespace(expression, index)
    in_string = False
    while cursor < len(expression):
        char = expression[cursor]
        if in_string:
            if char == "\\" and cursor + 1 < len(expression):
                cursor += 2
                continue
            if char == '"':
                in_string = False
            cursor += 1
            continue

        if char == '"':
            in_string = True
            cursor += 1
            continue
        if char in {",", ")"}:
            break
        cursor += 1
    return cursor


def _parse_identifier(text: str, index: int) -> tuple[str | None, int]:
    if index >= len(text):
        return None, index
    if not (text[index].isalpha() or text[index] == "_"):
        return None, index
    cursor = index + 1
    while cursor < len(text) and (text[cursor].isalnum() or text[cursor] == "_"):
        cursor += 1
    return text[index:cursor], cursor


def _skip_whitespace(text: str, index: int) -> int:
    cursor = index
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    return cursor


def _find_matching_delimiter(
    text: str,
    start_index: int,
    opening: str,
    closing: str,
) -> int | None:
    depth = 0
    index = start_index
    while index < len(text):
        char = text[index]
        if text.startswith("//", index):
            index = _line_end(text, index)
            continue
        if text.startswith("/*", index):
            index = _block_comment_end(text, index)
            continue
        if char == '"':
            index = _quoted_string_end(text, index, '"')
            continue
        if char == "'" and _looks_like_char_literal_start(text, index):
            index = _quoted_string_end(text, index, "'")
            continue
        if char == "r" and _looks_like_raw_string_start(text, index):
            index = _raw_string_end(text, index)
            continue
        if char == opening:
            depth += 1
            index += 1
            continue
        if char == closing:
            depth -= 1
            if depth == 0:
                return index
        index += 1

    return None


def _line_end(text: str, index: int) -> int:
    newline = text.find("\n", index)
    return len(text) if newline == -1 else newline + 1


def _block_comment_end(text: str, index: int) -> int:
    depth = 1
    cursor = index + 2
    while cursor < len(text):
        if text.startswith("/*", cursor):
            depth += 1
            cursor += 2
            continue
        if text.startswith("*/", cursor):
            depth -= 1
            cursor += 2
            if depth == 0:
                return cursor
            continue
        cursor += 1
    return len(text)


def _raw_string_end(text: str, index: int) -> int:
    cursor = index + 1
    hash_count = 0
    while cursor < len(text) and text[cursor] == "#":
        hash_count += 1
        cursor += 1
    if cursor >= len(text) or text[cursor] != '"':
        return index + 1
    cursor += 1
    terminator = '"' + ("#" * hash_count)
    end = text.find(terminator, cursor)
    if end == -1:
        return len(text)
    return end + len(terminator)


def _quoted_string_end(text: str, index: int, quote: str) -> int:
    cursor = index + 1
    while cursor < len(text):
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == quote:
            return cursor + 1
        cursor += 1
    return len(text)


def _looks_like_raw_string_start(text: str, index: int) -> bool:
    if index >= len(text) or text[index] != "r":
        return False
    cursor = index + 1
    while cursor < len(text) and text[cursor] == "#":
        cursor += 1
    return cursor < len(text) and text[cursor] == '"'


def _looks_like_char_literal_start(text: str, index: int) -> bool:
    if index + 2 >= len(text):
        return False

    next_char = text[index + 1]
    if next_char == "\\":
        cursor = index + 2
        if cursor < len(text) and text[cursor] in {"x", "u"}:
            cursor += 1
            while cursor < len(text) and text[cursor] != "'":
                cursor += 1
            return cursor < len(text) and text[cursor] == "'"
        return index + 3 < len(text) and text[index + 3] == "'"

    # Lifetimes and labels are identifier-like and are not char literals.
    if next_char.isalpha() or next_char == "_":
        return False

    return text[index + 2] == "'"


def _strip_comments_preserve_lines(text: str) -> str:
    result: list[str] = []
    index = 0
    while index < len(text):
        if text.startswith("//", index):
            result.append("  ")
            index += 2
            while index < len(text) and text[index] != "\n":
                result.append(" ")
                index += 1
            continue
        if text.startswith("/*", index):
            result.append("  ")
            index += 2
            depth = 1
            while index < len(text) and depth > 0:
                if text.startswith("/*", index):
                    result.append("  ")
                    depth += 1
                    index += 2
                    continue
                if text.startswith("*/", index):
                    result.append("  ")
                    depth -= 1
                    index += 2
                    continue
                result.append("\n" if text[index] == "\n" else " ")
                index += 1
            continue
        if text[index] == '"':
            literal_end = _quoted_string_end(text, index, '"')
            result.extend(text[index:literal_end])
            index = literal_end
            continue
        if text[index] == "r" and _looks_like_raw_string_start(text, index):
            literal_end = _raw_string_end(text, index)
            result.extend(text[index:literal_end])
            index = literal_end
            continue
        if text[index] == "'" and _looks_like_char_literal_start(text, index):
            literal_end = _quoted_string_end(text, index, "'")
            result.extend(text[index:literal_end])
            index = literal_end
            continue
        result.append(text[index])
        index += 1
    return "".join(result)


def _strip_c_style_comments_preserve_lines(text: str) -> str:
    """Backwards-compatible shim for tests/imports expecting the old helper name."""
    return _strip_comments_preserve_lines(text)


def _line_number(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _merge_line_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    if not ranges:
        return []

    sorted_ranges = sorted(ranges)
    merged: list[tuple[int, int]] = [sorted_ranges[0]]
    for start, end in sorted_ranges[1:]:
        prev_start, prev_end = merged[-1]
        if start <= prev_end + 1:
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def parse_cargo_errors(output: str, scan_path: Path) -> list[dict[str, Any]]:
    """Parse cargo-check compiler errors only."""
    return _parse_cargo_messages(output, scan_path, allowed_levels={"error"})


def parse_rustdoc_messages(output: str, scan_path: Path) -> list[dict[str, Any]]:
    """Parse rustdoc diagnostics, including denied warnings."""
    return _parse_cargo_messages(output, scan_path, allowed_levels={"warning", "error"})


def build_rustdoc_warning_cmd(package: str) -> str:
    """Build a `cargo rustdoc` command for one workspace package."""
    return RUSTDOC_WARNING_CMD.format(package=shlex.quote(package))


def _extract_workspace_rustdoc_packages(payload: dict[str, Any]) -> list[str]:
    workspace_members = set(payload.get("workspace_members") or [])
    packages: list[str] = []
    for package in payload.get("packages") or []:
        if not isinstance(package, dict) or package.get("id") not in workspace_members:
            continue
        name = package.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        targets = package.get("targets") or []
        has_lib_target = False
        for target in targets:
            if not isinstance(target, dict):
                continue
            kinds = {str(kind) for kind in target.get("kind") or []}
            crate_types = {str(kind) for kind in target.get("crate_types") or []}
            if kinds & _LIB_TARGET_KINDS or crate_types & _LIB_TARGET_KINDS:
                has_lib_target = True
                break
        if has_lib_target:
            packages.append(name.strip())
    return sorted(dict.fromkeys(packages))


def _run_cargo_metadata(
    scan_path: Path,
    *,
    run_subprocess: SubprocessRun | None = None,
) -> tuple[ToolRunResult | None, list[str]]:
    runner: Callable[..., subprocess.CompletedProcess[str]] = run_subprocess or subprocess.run
    workspace_root = find_workspace_root(scan_path)
    try:
        result = runner(
            resolve_command_argv(_CARGO_METADATA_CMD),
            shell=False,
            cwd=str(workspace_root),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        return (
            ToolRunResult(
                entries=[],
                status="error",
                error_kind="tool_not_found",
                message=str(exc),
            ),
            [],
        )
    except subprocess.TimeoutExpired as exc:
        return (
            ToolRunResult(
                entries=[],
                status="error",
                error_kind="tool_timeout",
                message=str(exc),
            ),
            [],
        )

    output = (result.stdout or "") + (result.stderr or "")
    if result.returncode not in (0, None):
        preview = " ".join(output.split())
        return (
            ToolRunResult(
                entries=[],
                status="error",
                error_kind="tool_failed_unparsed_output",
                message=(
                    f"cargo metadata exited with code {result.returncode}"
                    + (f": {preview[:160].rstrip()}..." if len(preview) > 160 else f": {preview}" if preview else "")
                ),
                returncode=result.returncode,
            ),
            [],
        )
    try:
        data = json.loads(output)
    except json.JSONDecodeError as exc:
        return (
            ToolRunResult(
                entries=[],
                status="error",
                error_kind="parser_error",
                message=str(exc),
                returncode=result.returncode,
            ),
            [],
        )
    if not isinstance(data, dict):
        return (
            ToolRunResult(
                entries=[],
                status="error",
                error_kind="parser_shape_error",
                message="cargo metadata returned non-object JSON",
                returncode=result.returncode,
            ),
            [],
        )
    return None, _extract_workspace_rustdoc_packages(data)


def run_rustdoc_result(
    scan_path: Path,
    *,
    run_subprocess: SubprocessRun | None = None,
) -> ToolRunResult:
    """Run `cargo rustdoc` once per workspace library package."""
    metadata_error, packages = _run_cargo_metadata(scan_path, run_subprocess=run_subprocess)
    if metadata_error is not None:
        return metadata_error
    if not packages:
        return ToolRunResult(entries=[], status="empty", returncode=0)

    workspace_root = find_workspace_root(scan_path)
    entries: list[dict[str, Any]] = []
    returncode = 0
    for package in packages:
        result = run_tool_result(
            build_rustdoc_warning_cmd(package),
            workspace_root,
            parse_rustdoc_messages,
            run_subprocess=run_subprocess,
        )
        if result.status == "error":
            message = result.message or "cargo rustdoc failed"
            return ToolRunResult(
                entries=[],
                status="error",
                error_kind=result.error_kind,
                message=f"{package}: {message}",
                returncode=result.returncode,
            )
        if result.status == "ok":
            entries.extend(result.entries)
            if result.returncode not in (0, None):
                returncode = result.returncode
    if not entries:
        return ToolRunResult(entries=[], status="empty", returncode=returncode)
    return ToolRunResult(entries=entries, status="ok", returncode=returncode)


__all__ = [
    "build_rustdoc_warning_cmd",
    "CARGO_ERROR_CMD",
    "CLIPPY_WARNING_CMD",
    "RUSTDOC_WARNING_CMD",
    "parse_cargo_errors",
    "parse_clippy_messages",
    "parse_rustdoc_messages",
    "run_rustdoc_result",
]
