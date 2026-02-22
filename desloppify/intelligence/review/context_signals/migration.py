"""Migration/deprecation and error-strategy signals for review context."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from desloppify.core.signal_patterns import DEPRECATION_MARKER_RE, MIGRATION_TODO_RE
from desloppify.languages import get_lang


class MigrationLangConfig(Protocol):
    """Minimal migration-related language contract expected by signal gatherers."""

    migration_mixed_extensions: set[str]
    migration_pattern_pairs: list[tuple[str, re.Pattern[str], re.Pattern[str]]]


def gather_migration_signals_by_name(
    file_contents: dict[str, str],
    lang_name: str,
    *,
    rel_fn: Callable[[str], str],
) -> dict[str, object]:
    """Gather migration signals using a language name."""
    if not isinstance(lang_name, str) or not lang_name.strip():
        raise ValueError("lang_name must be a non-empty string")
    try:
        lang_cfg = get_lang(lang_name)
    except (ImportError, ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"Unsupported language for migration signals: {lang_name}") from exc
    return gather_migration_signals_by_config(file_contents, lang_cfg, rel_fn=rel_fn)


def gather_migration_signals_by_config(
    file_contents: dict[str, str],
    lang_cfg: MigrationLangConfig,
    *,
    rel_fn: Callable[[str], str],
) -> dict[str, object]:
    """Gather migration signals using a concrete language config object."""
    _validate_lang_config(lang_cfg)
    return _gather_migration_signals(file_contents, lang_cfg, rel_fn=rel_fn)


def gather_migration_signals(
    file_contents: dict[str, str],
    lang,
    *,
    rel_fn: Callable[[str], str],
) -> dict[str, object]:
    """Compute migration/deprecated signals from file contents.

    Returns deprecated markers, migration TODOs, pattern pairs, mixed extensions.
    """
    if isinstance(lang, str):
        return gather_migration_signals_by_name(file_contents, lang, rel_fn=rel_fn)
    return gather_migration_signals_by_config(file_contents, lang, rel_fn=rel_fn)


def _validate_lang_config(lang_cfg: object) -> None:
    if lang_cfg is None:
        raise TypeError("lang config is required for migration signals")
    if not hasattr(lang_cfg, "migration_mixed_extensions"):
        raise TypeError("lang config missing 'migration_mixed_extensions'")
    if not hasattr(lang_cfg, "migration_pattern_pairs"):
        raise TypeError("lang config missing 'migration_pattern_pairs'")


def _gather_migration_signals(
    file_contents: dict[str, str],
    lang_cfg: MigrationLangConfig,
    *,
    rel_fn: Callable[[str], str],
) -> dict[str, object]:
    deprecated_files: dict[str, int] = {}
    migration_todos: list[dict] = []
    stems_by_ext: dict[str, set[str]] = {}  # stem -> set of extensions

    mixed_exts = set(lang_cfg.migration_mixed_extensions or set())

    for filepath, content in file_contents.items():
        rpath = rel_fn(filepath)

        # Deprecated markers
        dep_count = len(DEPRECATION_MARKER_RE.findall(content))
        if dep_count > 0:
            deprecated_files[rpath] = dep_count

        # Migration TODOs
        for match in MIGRATION_TODO_RE.finditer(content):
            migration_todos.append({"file": rpath, "text": match.group(0)[:120]})

        # Track stems for mixed extension detection
        path = Path(rpath)
        stem = path.stem
        ext = path.suffix
        if ext in mixed_exts:
            stems_by_ext.setdefault(stem, set()).add(ext)

    # Pattern pair detection
    pairs = list(lang_cfg.migration_pattern_pairs or [])

    pattern_results: list[dict] = []
    for name, old_re, new_re in pairs:
        old_count = sum(
            1 for content in file_contents.values() if old_re.search(content)
        )
        new_count = sum(
            1 for content in file_contents.values() if new_re.search(content)
        )
        if old_count > 0 and new_count > 0:
            pattern_results.append(
                {
                    "name": name,
                    "old_count": old_count,
                    "new_count": new_count,
                }
            )

    # Mixed extensions
    mixed_stems = sorted(stem for stem, exts in stems_by_ext.items() if len(exts) >= 2)

    result: dict[str, object] = {}
    if deprecated_files:
        result["deprecated_markers"] = {
            "total": sum(deprecated_files.values()),
            "files": deprecated_files,
        }
    if migration_todos:
        result["migration_todos"] = migration_todos[:30]
    if pattern_results:
        result["pattern_pairs"] = pattern_results
    if mixed_stems:
        result["mixed_extensions"] = mixed_stems[:20]
    return result


def classify_error_strategy(content: str) -> str | None:
    """Classify a file's primary error handling strategy."""
    throws = len(re.findall(r"\b(?:throw\s+new|raise\s+\w)", content))
    returns_null = len(re.findall(r"\breturn\s+(?:null|None|undefined)\b", content))
    result_type = len(re.findall(r"\b(?:Result|Either|Ok|Err)\b", content))
    try_catch = len(re.findall(r"\b(?:try\s*\{|try\s*:)", content))

    counts = {
        "throw": throws,
        "return_null": returns_null,
        "result_type": result_type,
        "try_catch": try_catch,
    }
    total = sum(counts.values())
    if total == 0:
        return None
    dominant = max(counts.items(), key=lambda item: item[1])[0]
    # "mixed" if no strategy accounts for >60% of occurrences
    if counts[dominant] / total < 0.6:
        return "mixed"
    return dominant


__all__ = [
    "MigrationLangConfig",
    "classify_error_strategy",
    "gather_migration_signals",
    "gather_migration_signals_by_name",
    "gather_migration_signals_by_config",
]
