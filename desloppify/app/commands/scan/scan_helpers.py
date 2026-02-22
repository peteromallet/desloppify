"""Shared helpers for scan command orchestration."""

from __future__ import annotations

import logging
from pathlib import Path

from desloppify import languages as lang_api
from desloppify import state as state_mod
from desloppify.file_discovery import DEFAULT_EXCLUSIONS, read_file_text
from desloppify.utils import colorize

logger = logging.getLogger(__name__)


def _audit_excluded_dirs(
    exclusions: tuple[str, ...],
    scanned_files: list[str],
    project_root: Path,
) -> list[dict]:
    """Check if any --exclude directory has zero references from scanned code.

    Returns findings for directories that appear stale (no file references them).
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

    stale_findings = []
    for ex_dir in candidate_dirs:
        if ex_dir not in unresolved:
            continue
        stale_findings.append(
            state_mod.make_finding(
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
    return stale_findings


def _collect_codebase_metrics(lang, path: Path) -> dict | None:
    """Collect LOC/file/directory counts for the configured language."""
    if not lang or not lang.file_finder:
        return None
    files = lang.file_finder(path)
    total_loc = 0
    dirs = set()
    for filepath in files:
        try:
            total_loc += len(Path(filepath).read_text().splitlines())
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


def _resolve_scan_profile(profile: str | None, lang) -> str:
    """Resolve effective scan profile from CLI and language defaults."""
    if profile in {"objective", "full", "ci"}:
        return profile
    default_profile = getattr(lang, "default_scan_profile", "full") if lang else "full"
    if default_profile in {"objective", "full", "ci"}:
        return default_profile
    return "full"


def _effective_include_slow(include_slow: bool, profile: str) -> bool:
    """Determine whether slow phases should run for this profile."""
    return include_slow and profile != "ci"


def _format_hidden_by_detector(hidden_by_detector: dict[str, int]) -> str:
    """Format hidden findings counts for terminal output."""
    return ", ".join(f"{det}: +{count}" for det, count in hidden_by_detector.items())


def _warn_explicit_lang_with_no_files(
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


def _format_delta(value: float, prev: float | None) -> tuple[str, str]:
    """Return (delta_str, color) for a score change."""
    delta = value - prev if prev is not None else 0
    delta_str = f" ({'+' if delta > 0 else ''}{delta:.1f})" if delta != 0 else ""
    color = "green" if delta > 0 else ("red" if delta < 0 else "dim")
    return delta_str, color


__all__ = [
    "_audit_excluded_dirs",
    "_collect_codebase_metrics",
    "_effective_include_slow",
    "_format_delta",
    "_format_hidden_by_detector",
    "_resolve_scan_profile",
    "_warn_explicit_lang_with_no_files",
]
