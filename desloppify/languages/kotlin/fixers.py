"""Ktlint formatting restricted to eligible files with selected findings."""

from __future__ import annotations

import stat
import subprocess  # nosec B404
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from desloppify.base.discovery.file_paths import resolve_scan_file, safe_write_text
from desloppify.base.discovery.paths import get_project_root
from desloppify.languages._framework.base.types import FixerConfig, FixResult
from desloppify.languages._framework.generic_parts.parsers import (
    ToolParserError,
    parse_ktlint,
)
from desloppify.languages._framework.generic_parts.tool_runner import run_tool_result

KTLINT_COMMAND = "ktlint --reporter=json --log-level=none"


def _format_source(filepath: Path, source: str, root: Path) -> tuple[str, bool] | None:
    """Use stdin so file names are never interpreted as formatting globs."""
    common = ["ktlint", "--stdin", "--stdin-path", str(filepath), "--log-level=none"]
    options = {"cwd": str(root), "capture_output": True, "text": True, "timeout": 120}
    formatted = subprocess.run([*common, "--format"], input=source, **options)
    # ktlint can return exit 0 with empty stdout for a syntax error.
    if formatted.returncode not in (0, 1) or not formatted.stdout:
        return None
    checked = subprocess.run([*common, "--reporter=json"], input=formatted.stdout, **options)
    report = checked.stdout if checked.stdout.strip() else checked.stderr
    remaining = parse_ktlint(report, root)
    if (
        checked.returncode not in (0, 1)
        or (checked.returncode == 1 and not remaining)
        or any(not entry["detail"]["rule"] for entry in remaining)
    ):
        return None
    return formatted.stdout, not remaining


def make_ktlint_fixer(file_finder: Callable[[Path], list[str]]) -> FixerConfig:
    """Build a Kotlin-only fixer; generic tool behavior remains unchanged."""
    def eligible_files(path: Path) -> set[Path]:
        root = get_project_root()
        candidates = (root / filename for filename in file_finder(path))
        return {
            candidate.resolve() for candidate in candidates
            if not candidate.is_symlink() and candidate.resolve().is_relative_to(root)
        }

    def detect(path: Path) -> list[dict]:
        scan_path = Path(getattr(path, "path", path))
        eligible = eligible_files(scan_path)
        result = run_tool_result(KTLINT_COMMAND, scan_path, parse_ktlint)
        entries = []
        for entry in result.entries:
            filepath = resolve_scan_file(entry["file"], scan_root=scan_path)
            if filepath in eligible:
                entries.append({**entry, "file": str(filepath)})
        return entries

    def fix(entries: list[dict], *, dry_run: bool = False) -> FixResult:
        root = get_project_root()
        eligible = eligible_files(root)
        grouped: dict[Path, list[dict]] = {}
        skipped: Counter[str] = Counter()
        for entry in entries:
            filepath = resolve_scan_file(entry["file"])
            if filepath not in eligible:
                skipped["excluded_file"] += 1
                continue
            grouped.setdefault(filepath, []).append(entry)

        results = []
        for filepath, file_entries in grouped.items():
            try:
                with filepath.open(encoding="utf-8", newline="") as handle:
                    source = handle.read()
                formatted = _format_source(filepath, source, root)
                if formatted is None:
                    skipped["tool_failed"] += len(file_entries)
                    continue
                updated, clean = formatted
                if updated == source:
                    skipped["no_change"] += len(file_entries)
                    continue
                if not dry_run:
                    if filepath.read_bytes().decode("utf-8") != source:
                        skipped["file_changed"] += len(file_entries)
                        continue
                    mode = stat.S_IMODE(filepath.stat().st_mode)
                    safe_write_text(filepath, updated)
                    filepath.chmod(mode)
            except (OSError, UnicodeError, subprocess.TimeoutExpired, ToolParserError):
                skipped["tool_failed"] += len(file_entries)
                continue
            result = {"file": str(filepath), "summary": "Formatted with ktlint"}
            if clean:
                result["removed"] = [
                    entry.get("id", f"ktlint_violation::{entry['line']}")
                    for entry in file_entries
                ]
            else:
                result["summary"] += "; remaining violations require a rescan"
            results.append(result)
        return FixResult(entries=results, skip_reasons=dict(skipped))

    return FixerConfig(
        label="ktlint issues", detect=detect, fix=fix, detector="ktlint_violation",
    )
