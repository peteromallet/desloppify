"""Runtime setup helpers for review command flows."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from desloppify.engine.policy.zones import FileZoneMap
    from desloppify.languages._framework.base.types import LangConfig
    from desloppify.languages._framework.runtime import LangRun


def setup_lang(
    lang: LangConfig,
    path: Path,
    config: dict[str, Any],
    *,
    make_lang_run_fn: Callable[[LangConfig], LangRun],
    file_zone_map_cls: type[FileZoneMap],
    rel_fn: Callable[[str], str],
    log_fn: Callable[[str], None],
) -> tuple[LangRun, list[str]]:
    """Build LangRun with zone map + dep graph and return (run, files)."""
    lang_run = make_lang_run_fn(lang)
    files: list[str] = []

    if lang_run.zone_rules and lang_run.file_finder:
        files = lang_run.file_finder(path)
        zone_overrides = config.get("zone_overrides") or None
        lang_run.zone_map = file_zone_map_cls(
            files, lang_run.zone_rules, rel_fn=rel_fn, overrides=zone_overrides
        )

    if lang_run.build_dep_graph and lang_run.dep_graph is None:
        try:
            lang_run.dep_graph = lang_run.build_dep_graph(path)
        except (
            OSError,
            UnicodeDecodeError,
            ValueError,
            TypeError,
            RuntimeError,
        ) as exc:
            log_fn(f"  dep graph unavailable for review context: {exc}")

    return lang_run, files


def setup_lang_concrete(lang: LangConfig, path: Path, config: dict) -> tuple[LangRun, list[str]]:
    """Build LangRun with zone map + dep graph using concrete dependencies."""
    from desloppify.engine.policy.zones import FileZoneMap
    from desloppify.file_discovery import rel
    from desloppify.languages import runtime as lang_runtime_mod
    from desloppify.utils import log

    return setup_lang(
        lang,
        path,
        config,
        make_lang_run_fn=lang_runtime_mod.make_lang_run,
        file_zone_map_cls=FileZoneMap,
        rel_fn=rel,
        log_fn=log,
    )


__all__ = ["setup_lang", "setup_lang_concrete"]
