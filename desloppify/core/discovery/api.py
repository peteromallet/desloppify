"""Canonical discovery API surface."""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path

from desloppify.core import source_discovery as source_discovery_mod

DEFAULT_EXCLUSIONS = source_discovery_mod.DEFAULT_EXCLUSIONS


def collect_exclude_dirs(scan_root: Path) -> list[str]:
    return source_discovery_mod.collect_exclude_dirs(scan_root)


def set_exclusions(patterns: list[str]) -> None:
    source_discovery_mod.set_exclusions(patterns)


def get_exclusions() -> tuple[str, ...]:
    return source_discovery_mod.get_exclusions()


def enable_file_cache() -> None:
    source_discovery_mod.enable_file_cache()


def disable_file_cache() -> None:
    source_discovery_mod.disable_file_cache()


def is_file_cache_enabled() -> bool:
    return source_discovery_mod.is_file_cache_enabled()


def file_cache_scope() -> Iterator[None]:
    return source_discovery_mod.file_cache_scope()


def read_file_text(filepath: str) -> str | None:
    return source_discovery_mod.read_file_text(filepath)


def clear_source_file_cache_for_tests() -> None:
    source_discovery_mod.clear_source_file_cache_for_tests()


def find_source_files(
    path: str | Path,
    extensions: Iterable[str],
    exclusions: Iterable[str] | None = None,
) -> list[str]:
    return source_discovery_mod.find_source_files(
        path,
        list(extensions),
        list(exclusions) if exclusions is not None else None,
    )


def find_ts_files(path: str | Path) -> list[str]:
    return source_discovery_mod.find_ts_files(path)


def find_tsx_files(path: str | Path) -> list[str]:
    return source_discovery_mod.find_tsx_files(path)


def find_py_files(path: str | Path) -> list[str]:
    return source_discovery_mod.find_py_files(path)


__all__ = [
    "DEFAULT_EXCLUSIONS",
    "clear_source_file_cache_for_tests",
    "collect_exclude_dirs",
    "disable_file_cache",
    "enable_file_cache",
    "file_cache_scope",
    "find_py_files",
    "find_source_files",
    "find_ts_files",
    "find_tsx_files",
    "get_exclusions",
    "is_file_cache_enabled",
    "read_file_text",
    "set_exclusions",
]
