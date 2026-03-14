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


def _extract_json_array(text: str) -> str | None:
    """Best-effort: return the first JSON array substring in *text*."""
    start = text.find("[")
    if start == -1:
        return None
    end = text.rfind("]")
    if end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _relativize_to_project_root(filepath: str, *, scan_path: Path) -> str:
    """Resolve a tool-emitted path to a project-root-relative string when possible."""
    from desloppify.base.discovery.paths import get_project_root

    project_root = get_project_root().resolve()
    try:
        p = Path(filepath)
        abs_path = p.resolve() if p.is_absolute() else (scan_path / p).resolve()
        try:
            return str(abs_path.relative_to(project_root)).replace("\\", "/")
        except ValueError:
            return str(abs_path)
    except Exception:  # pragma: no cover
        return filepath


def parse_next_lint(output: str, scan_path: Path) -> tuple[list[dict], dict]:
    """Parse Next.js `next lint --format json` output.

    Returns ``(entries, meta)`` where:
    - entries are *per-file* aggregates: {file, line, message, id, detail}
    - meta includes ``potential`` (number of files lint reported on)
    """
    raw = (output or "").strip()
    json_text = _extract_json_array(raw)
    if not json_text:
        raise ToolParserError("next_lint parser could not find JSON output array")

    data = _load_json_output(json_text, parser_name="next_lint")
    if not isinstance(data, list):
        raise ToolParserError("next_lint parser expected a JSON array")

    potential = len(data)
    entries: list[dict] = []
    for fobj in data:
        if not isinstance(fobj, dict):
            continue
        file_path = fobj.get("filePath") or ""
        messages = fobj.get("messages") or []
        if not file_path or not isinstance(messages, list) or not messages:
            continue

        rel = _relativize_to_project_root(str(file_path), scan_path=scan_path)
        first = next((m for m in messages if isinstance(m, dict)), None)
        if first is None:
            continue
        line = _coerce_line(first.get("line", 0)) or 1
        msg = first.get("message") if isinstance(first.get("message"), str) else "Lint issue"
        entries.append(
            {
                "file": rel,
                "line": line if line > 0 else 1,
                "id": "lint",
                "message": f"next lint: {msg} ({len(messages)} issue(s) in file)",
                "detail": {
                    "count": len(messages),
                    "messages": [
                        {
                            "line": _coerce_line(m.get("line", 0)) or 0,
                            "column": _coerce_line(m.get("column", 0)) or 0,
                            "ruleId": m.get("ruleId", "") if isinstance(m.get("ruleId", ""), str) else "",
                            "message": m.get("message", "") if isinstance(m.get("message", ""), str) else "",
                            "severity": _coerce_line(m.get("severity", 0)) or 0,
                        }
                        for m in messages
                        if isinstance(m, dict)
                    ][:50],
                },
            }
        )

    return entries, {"potential": potential}


ToolParseResult = list[dict] | tuple[list[dict], dict]
ToolParser = Callable[[str, Path], ToolParseResult]


PARSERS: dict[str, ToolParser] = {
    "gnu": parse_gnu,
    "golangci": parse_golangci,
    "json": parse_json,
    "credo": parse_credo,
    "rubocop": parse_rubocop,
    "cargo": parse_cargo,
    "eslint": parse_eslint,
    "next_lint": parse_next_lint,
}


__all__ = [
    "PARSERS",
    "ToolParserError",
    "ToolParseResult",
    "ToolParser",
    "parse_cargo",
    "parse_credo",
    "parse_eslint",
    "parse_gnu",
    "parse_golangci",
    "parse_json",
    "parse_next_lint",
    "parse_rubocop",
]
