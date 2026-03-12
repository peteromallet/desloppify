"""External command execution helpers for generic language plugins."""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess  # nosec B404
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from desloppify.languages._framework.generic_parts.parsers import ToolParserError

SubprocessRun = Callable[..., subprocess.CompletedProcess[str]]

_SHELL_META_CHARS = re.compile(r"[|&;<>()$`\n]")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolRunResult:
    """Structured execution result for generic-tool detector commands."""

    entries: list[dict]
    status: Literal["ok", "empty", "error"]
    error_kind: str | None = None
    message: str | None = None
    returncode: int | None = None


def _shell_argv(cmd: str) -> list[str]:
    """Return a platform-appropriate shell argv for shell-meta commands."""
    if os.name == "nt":
        return ["cmd.exe", "/d", "/s", "/c", cmd]
    return ["/bin/sh", "-lc", cmd]


def resolve_command_argv(cmd: str) -> list[str]:
    """Return argv for subprocess.run without relying on shell=True."""
    if _SHELL_META_CHARS.search(cmd):
        return _shell_argv(cmd)
    try:
        argv = shlex.split(cmd, posix=os.name != "nt")
    except ValueError:
        return _shell_argv(cmd)
    if os.name == "nt":
        argv = [arg[1:-1] if len(arg) >= 2 and arg[0] == arg[-1] == '"' else arg for arg in argv]
    return argv if argv else _shell_argv(cmd)


def _output_preview(output: str, *, limit: int = 160) -> str:
    """Return a compact one-line preview of tool output for diagnostics."""
    text = " ".join(output.split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def run_tool_result(
    cmd: str,
    path: Path,
    parser: Callable[[str, Path], list[dict]],
    *,
    run_subprocess: SubprocessRun | None = None,
) -> ToolRunResult:
    """Run an external tool and parse its output with explicit failure status."""
    runner = run_subprocess or subprocess.run
    try:
        result = runner(
            resolve_command_argv(cmd),
            shell=False,
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError as exc:
        return ToolRunResult(
            entries=[],
            status="error",
            error_kind="tool_not_found",
            message=str(exc),
        )
    except subprocess.TimeoutExpired as exc:
        return ToolRunResult(
            entries=[],
            status="error",
            error_kind="tool_timeout",
            message=str(exc),
        )
    output = (result.stdout or "") + (result.stderr or "")
    if not output.strip():
        if result.returncode not in (0, None):
            return ToolRunResult(
                entries=[],
                status="error",
                error_kind="tool_failed_no_output",
                message=f"tool exited with code {result.returncode} and produced no output",
                returncode=result.returncode,
            )
        return ToolRunResult(
            entries=[],
            status="empty",
            returncode=result.returncode,
        )
    try:
        parsed = parser(output, path)
    except ToolParserError as exc:
        logger.debug("Parser decode error for tool output: %s", exc)
        return ToolRunResult(
            entries=[],
            status="error",
            error_kind="parser_error",
            message=str(exc),
            returncode=result.returncode,
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        logger.debug("Skipping tool output due to parser exception: %s", exc)
        return ToolRunResult(
            entries=[],
            status="error",
            error_kind="parser_exception",
            message=str(exc),
            returncode=result.returncode,
        )
    if not isinstance(parsed, list):
        return ToolRunResult(
            entries=[],
            status="error",
            error_kind="parser_shape_error",
            message="parser returned non-list output",
            returncode=result.returncode,
        )
    if not parsed:
        if result.returncode not in (0, None):
            preview = _output_preview(output)
            return ToolRunResult(
                entries=[],
                status="error",
                error_kind="tool_failed_unparsed_output",
                message=(
                    f"tool exited with code {result.returncode} and produced no parseable entries"
                    + (f": {preview}" if preview else "")
                ),
                returncode=result.returncode,
            )
        return ToolRunResult(
            entries=[],
            status="empty",
            returncode=result.returncode,
        )
    return ToolRunResult(
        entries=parsed,
        status="ok",
        returncode=result.returncode,
    )


__all__ = [
    "SubprocessRun",
    "ToolRunResult",
    "resolve_command_argv",
    "run_tool_result",
]
