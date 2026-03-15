"""Shared helpers for scan command orchestration."""

from __future__ import annotations

import logging
from pathlib import Path

from desloppify.languages import framework as lang_api
from desloppify import state as state_mod
from desloppify.base.discovery.source import (
    DEFAULT_EXCLUSIONS,
    read_file_text,
)
from desloppify.base.discovery.file_paths import count_lines
from desloppify.base.output.terminal import colorize

logger = logging.getLogger(__name__)


def audit_excluded_dirs(
    exclusions: tuple[str, ...],
    scanned_files: list[str],
    project_root: Path,
) -> list[dict]:
    """Check if any --exclude directory has zero references from scanned code.

    Returns issues for directories that appear stale (no file references them).
    """
    if not exclusions:
        return []

    candidate_dirs = [
        ex_dir
        for ex_dir in exclusions
        if ex_dir not in DEFAULT_EXCLUSIONS and (project_root / ex_dir).is_dir()
    ]
    if not candidate_dirs:
        return []

    # Read each scanned file once and mark any exclusions observed in content.
    unresolved = set(candidate_dirs)
    for filepath in scanned_files:
        if not unresolved:
            break
        abs_path = (
            filepath if Path(filepath).is_absolute() else str(project_root / filepath)
        )
        content = read_file_text(abs_path)
        if content is None:
            logger.debug(
                "Skipping unreadable file %s while auditing exclusions", filepath
            )
            continue

        matched = {ex_dir for ex_dir in unresolved if ex_dir in content}
        if matched:
            unresolved.difference_update(matched)

    stale_issues = []
    for ex_dir in candidate_dirs:
        if ex_dir not in unresolved:
            continue
        stale_issues.append(
            state_mod.make_issue(
                "stale_exclude",
                ex_dir,
                ex_dir,
                tier=4,
                confidence="low",
                summary=(
                    f"Excluded directory '{ex_dir}' has 0 references from scanned code — "
                    "may be stale"
                ),
                detail={"directory": ex_dir, "references": 0},
            )
        )
    return stale_issues


def collect_codebase_metrics(
    lang,
    path: Path,
    *,
    files: list[str] | None = None,
) -> dict | None:
    """Collect LOC/file/directory counts for the configured language."""
    if not lang:
        return None
    if files is None and not lang.file_finder:
        return None
    scan_root = Path(path)
    files = _resolve_scan_files(lang, scan_root, files=files)
    total_loc = 0
    dirs = set()
    for filepath in files:
        try:
            abs_path = _resolve_scan_file_path(filepath, project_root=scan_root)
            content = read_file_text(abs_path)
            if content is not None:
                total_loc += len(content.splitlines())
            else:
                total_loc += count_lines(Path(abs_path))
            dirs.add(str(Path(filepath).parent))
        except (OSError, UnicodeDecodeError) as exc:
            logger.debug(
                "Skipping unreadable file %s while collecting scan metrics: %s",
                filepath,
                exc,
            )
    return {
        "total_files": len(files),
        "total_loc": total_loc,
        "total_directories": len(dirs),
    }


def _resolve_scan_files(lang, path: Path, *, files: list[str] | None = None) -> list[str]:
    """Return discovered source files, preferring an explicit precomputed list."""
    if files is not None:
        return files
    return lang.file_finder(path)


def _resolve_scan_file_path(filepath: str, *, project_root: Path) -> str:
    """Resolve relative scan filepaths against the active scan path."""
    file_path = Path(filepath)
    if file_path.is_absolute():
        return str(file_path)
    return str((project_root / file_path).resolve())


def resolve_scan_profile(profile: str | None, lang) -> str:
    """Resolve effective scan profile from CLI and language defaults."""
    if profile in {"objective", "full", "ci"}:
        return profile
    default_profile = getattr(lang, "default_scan_profile", "full") if lang else "full"
    if default_profile in {"objective", "full", "ci"}:
        return default_profile
    return "full"


def effective_include_slow(include_slow: bool, profile: str) -> bool:
    """Determine whether slow phases should run for this profile."""
    return include_slow and profile != "ci"


def _format_hidden_by_detector(hidden_by_detector: dict[str, int]) -> str:
    """Format hidden issues counts for terminal output."""
    return ", ".join(f"{det}: +{count}" for det, count in hidden_by_detector.items())


def warn_explicit_lang_with_no_files(
    args, lang, path: Path, metrics: dict | None
) -> None:
    """Warn when user explicitly selected a language but scan found zero files."""
    explicit_lang = getattr(args, "lang", None)
    if not explicit_lang or not lang or not metrics:
        return
    if metrics.get("total_files", 0) > 0:
        return

    suggestion = " Omit `--lang` to auto-detect."
    root = path if path.is_dir() else path.parent
    try:
        detected = lang_api.auto_detect_lang(root)
    except ValueError as exc:
        detected = None
        logger.debug(
            "Auto-detect failed while warning for explicit lang on %s: %s", root, exc
        )
    else:
        if detected and detected != lang.name:
            suggestion = (
                f" Detected `{detected}` for this path — use `--lang {detected}` "
                "or omit `--lang`."
            )

    print(
        colorize(
            f"  ⚠ No {lang.name} source files found under `{path}`.{suggestion}",
            "yellow",
        )
    )


def format_delta(value: float, prev: float | None) -> tuple[str, str]:
    """Return (delta_str, color) for a score change."""
    delta = value - prev if prev is not None else 0
    delta_str = f" ({'+' if delta > 0 else ''}{delta:.1f})" if delta != 0 else ""
    color = "green" if delta > 0 else ("red" if delta < 0 else "dim")
    return delta_str, color


__all__ = [
    "audit_excluded_dirs",
    "collect_codebase_metrics",
    "effective_include_slow",
    "format_delta",
    "_format_hidden_by_detector",
    "resolve_scan_profile",
    "warn_explicit_lang_with_no_files",
]
