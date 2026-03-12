"""Shared Rust tool command strings and JSON diagnostic parsers."""

from __future__ import annotations

import json
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
) -> list[dict[str, Any]]:
    del scan_path
    entries: list[dict[str, Any]] = []
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
    return _parse_cargo_messages(output, scan_path, allowed_levels={"warning", "error"})


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
