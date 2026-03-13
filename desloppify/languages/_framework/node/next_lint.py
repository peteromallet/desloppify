"""Next.js `next lint` integration.

This is treated as a framework-level smell source for Next.js projects. It
parses ESLint JSON output and maps it into per-file issues to keep state size
bounded.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess  # nosec B404
from pathlib import Path

logger = logging.getLogger(__name__)
_proc_runtime = subprocess


def _extract_json_array(text: str) -> str | None:
    """Best-effort: return the first JSON array substring in *text*."""
    start = text.find("[")
    if start == -1:
        return None
    end = text.rfind("]")
    if end == -1 or end <= start:
        return None
    return text[start : end + 1]


def _relativize(filepath: str, project_root: Path) -> str:
    try:
        p = Path(filepath)
        if p.is_absolute():
            return str(p.resolve().relative_to(project_root.resolve()))
    except Exception:  # pragma: no cover
        pass
    return filepath


def run_next_lint(project_root: Path) -> tuple[list[dict], int, str | None]:
    """Run `next lint --format json` and return (entries, potential, error).

    - entries are *per-file* aggregates: {file, line, message, count, messages}
    - potential is the number of files lint reported on (len(json array))
    - error is a short string when lint could not be run/parsed
    """
    npx_path = shutil.which("npx")
    if not npx_path:
        return [], 0, "npx executable not found in PATH"

    cmd = [npx_path, "--no-install", "next", "lint", "--format", "json"]
    try:
        result = _proc_runtime.run(  # nosec B603
            cmd,
            capture_output=True,
            text=True,
            cwd=project_root,
            timeout=180,
        )
    except (_proc_runtime.SubprocessError, OSError) as exc:
        return [], 0, f"failed to run next lint: {exc}"

    raw = (result.stdout or "").strip()
    if not raw:
        raw = (result.stderr or "").strip()
    json_text = _extract_json_array(raw)
    if not json_text:
        return [], 0, "next lint did not return JSON output (try installing dependencies)"

    try:
        data = json.loads(json_text)
    except (json.JSONDecodeError, ValueError) as exc:
        logger.debug("next lint JSON parse failed: %s", exc)
        return [], 0, "could not parse next lint JSON output"

    if not isinstance(data, list):
        return [], 0, "next lint JSON output was not a list"

    potential = len(data)
    entries: list[dict] = []
    for fobj in data:
        if not isinstance(fobj, dict):
            continue
        file_path = fobj.get("filePath") or ""
        messages = fobj.get("messages") or []
        if not file_path or not isinstance(messages, list) or not messages:
            continue

        rel = _relativize(str(file_path), project_root)
        first = next((m for m in messages if isinstance(m, dict)), None)
        if first is None:
            continue
        line = first.get("line") if isinstance(first.get("line"), int) else 1
        msg = first.get("message") if isinstance(first.get("message"), str) else "Lint issue"
        entries.append(
            {
                "file": rel,
                "line": line if line and line > 0 else 1,
                "message": msg,
                "count": len(messages),
                "messages": [
                    {
                        "line": m.get("line", 0),
                        "column": m.get("column", 0),
                        "ruleId": m.get("ruleId", ""),
                        "message": m.get("message", ""),
                        "severity": m.get("severity", 0),
                    }
                    for m in messages
                    if isinstance(m, dict)
                ][:50],
            }
        )

    return entries, potential, None


__all__ = ["run_next_lint"]

