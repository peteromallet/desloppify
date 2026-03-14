"""Output parser catalog for generic language plugins."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from pathlib import Path

logger = logging.getLogger(__name__)


class ToolParserError(ValueError):
    """Raised when a parser cannot decode tool output for its declared format."""


def _load_json_output(output: str, *, parser_name: str) -> object:
    """Decode JSON output or raise a typed parser error."""
    try:
        return json.loads(output)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ToolParserError(
            f"{parser_name} parser could not decode JSON output"
        ) from exc


def _coerce_line(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def parse_gnu(output: str, scan_path: Path) -> list[dict]:
    """Parse `file:line: message` or `file:line:col: message` format."""
    entries: list[dict] = []
    for line in output.splitlines():
        match = re.match(r"^(.+?):(\d+)(?::\d+)?:\s*(.+)$", line)
        if match:
            entries.append(
                {
                    "file": match.group(1).strip(),
                    "line": int(match.group(2)),
                    "message": match.group(3).strip(),
                }
            )
    return entries


def parse_golangci(output: str, scan_path: Path) -> list[dict]:
    """Parse golangci-lint JSON output: `{"Issues": [...]}`."""
    del scan_path
    entries: list[dict] = []
    data = _load_json_output(output, parser_name="golangci")
    issues = data.get("Issues") if isinstance(data, dict) else []
    for issue in issues or []:
        pos = issue.get("Pos") or {}
        filename = pos.get("Filename", "")
        line = _coerce_line(pos.get("Line", 0))
        text = issue.get("Text", "")
        if filename and text and line is not None:
            entries.append({"file": str(filename), "line": line, "message": str(text)})
    return entries


def parse_json(output: str, scan_path: Path) -> list[dict]:
    """Parse flat JSON array with field aliases."""
    del scan_path
    entries: list[dict] = []
    data = _load_json_output(output, parser_name="json")
    items = data if isinstance(data, list) else []
    for item in items:
        if not isinstance(item, dict):
            continue
        filename = item.get("file") or item.get("filename") or item.get("path") or ""
        line = _coerce_line(item.get("line") or item.get("line_no") or item.get("row") or 0)
        message = item.get("message") or item.get("text") or item.get("reason") or ""
        if filename and message and line is not None:
            entries.append(
                {
                    "file": str(filename),
                    "line": line,
                    "message": str(message),
                }
            )
    return entries


def parse_rubocop(output: str, scan_path: Path) -> list[dict]:
    """Parse RuboCop JSON: `{"files": [{"path": ..., "offenses": [...]}]}`."""
    del scan_path
    entries: list[dict] = []
    data = _load_json_output(output, parser_name="rubocop")
    files = data.get("files") if isinstance(data, dict) else []
    for fobj in files or []:
        filepath = fobj.get("path", "")
        for offense in fobj.get("offenses") or []:
            loc = offense.get("location") or {}
            line = _coerce_line(loc.get("line", 0))
            message = offense.get("message", "")
            if filepath and message and line is not None:
                entries.append({"file": str(filepath), "line": line, "message": str(message)})
    return entries


def parse_cargo(output: str, scan_path: Path) -> list[dict]:
    """Parse cargo clippy/check JSON Lines output."""
    entries: list[dict] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.debug("Skipping unparseable cargo output line: %s", exc)
            continue
        if data.get("reason") != "compiler-message":
            continue
        msg = data.get("message") or {}
        spans = msg.get("spans") or []
        rendered = msg.get("rendered") or msg.get("message") or ""
        if not spans or not rendered:
            continue
        span = spans[0]
        filename = span.get("file_name", "")
        line_no = _coerce_line(span.get("line_start", 0))
        summary = rendered.split("\n")[0].strip() if rendered else ""
        if filename and summary and line_no is not None:
            entries.append({"file": str(filename), "line": line_no, "message": summary})
    return entries


def parse_credo(output: str, scan_path: Path) -> list[dict]:
    """Parse Credo JSON: ``{"issues": [{"filename", "line_no", "message", ...}]}``."""
    del scan_path
    entries: list[dict] = []
    data = _load_json_output(output, parser_name="credo")
    issues = data.get("issues") if isinstance(data, dict) else []
    for issue in issues or []:
        filename = issue.get("filename", "")
        line = _coerce_line(issue.get("line_no", 0))
        message = issue.get("message", "")
        category = issue.get("category", "")
        check = issue.get("check", "")
        if category and message:
            message = f"[{category}] {message}"
        if check:
            message = f"{message} ({check})"
        if filename and message and line is not None:
            entries.append({"file": str(filename), "line": line, "message": str(message)})
    return entries


def parse_eslint(output: str, scan_path: Path) -> list[dict]:
    """Parse ESLint JSON: `[{"filePath": ..., "messages": [...]}]`."""
    del scan_path
    entries: list[dict] = []
    data = _load_json_output(output, parser_name="eslint")
    for fobj in data if isinstance(data, list) else []:
        if not isinstance(fobj, dict):
            continue
        filepath = fobj.get("filePath", "")
        for msg in fobj.get("messages") or []:
            line = _coerce_line(msg.get("line", 0))
            message = msg.get("message", "")
            if filepath and message and line is not None:
                entries.append({"file": str(filepath), "line": line, "message": str(message)})
    return entries


def parse_phpstan(output: str, scan_path: Path) -> list[dict]:
    """Parse PHPStan JSON: ``{"files": {"<path>": {"messages": [{"message": "...", "line": 42}]}}}``."""
    del scan_path
    entries: list[dict] = []
    data = _load_json_output(output, parser_name="phpstan")
    files = data.get("files") if isinstance(data, dict) else {}
    for filepath, fdata in (files or {}).items():
        if not isinstance(fdata, dict):
            continue
        for msg in fdata.get("messages") or []:
            if not isinstance(msg, dict):
                continue
            line = _coerce_line(msg.get("line", 0))
            message = msg.get("message", "")
            if filepath and message and line is not None:
                entries.append({"file": str(filepath), "line": line, "message": str(message)})
    return entries


PARSERS: dict[str, Callable[[str, Path], list[dict]]] = {
    "gnu": parse_gnu,
    "golangci": parse_golangci,
    "json": parse_json,
    "credo": parse_credo,
    "phpstan": parse_phpstan,
    "rubocop": parse_rubocop,
    "cargo": parse_cargo,
    "eslint": parse_eslint,
}


__all__ = [
    "PARSERS",
    "ToolParserError",
    "parse_cargo",
    "parse_credo",
    "parse_eslint",
    "parse_gnu",
    "parse_golangci",
    "parse_json",
    "parse_phpstan",
    "parse_rubocop",
]
