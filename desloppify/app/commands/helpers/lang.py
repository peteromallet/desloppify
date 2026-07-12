"""Language-resolution helpers for command modules."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from desloppify.base.discovery.paths import get_project_root
from desloppify.base.exception_sets import CommandError
from desloppify.languages import framework as lang_api

if TYPE_CHECKING:
    from desloppify.languages.framework import LangConfig


logger = logging.getLogger(__name__)


class LangResolutionError(CommandError):
    """Raised when language resolution fails with a user-facing message.

    Inherits from ``CommandError`` so the CLI top-level uses the standard
    command error path (formatted message + non-zero exit code) instead of
    bypassing the command error hierarchy.
    """

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message, exit_code=1)


def load_lang_config(lang_name: str):
    """Load one language config with explicit broken-plugin signaling."""
    try:
        return lang_api.get_lang(lang_name)
    except ValueError as exc:
        langs = lang_api.available_langs()
        langs_str = ", ".join(langs) if langs else "registered language plugins"
        raise LangResolutionError(
            f"{exc}\n  Hint: use --lang to select manually (available: {langs_str})"
        ) from exc
    except (ImportError, TypeError, AttributeError) as exc:
        raise LangResolutionError(
            f"Language plugin '{lang_name}' failed to load: {exc}"
        ) from exc


def load_lang_config_metadata(lang_name: str) -> LangConfig | None:
    """Load language metadata, isolating broken plugins from unrelated commands."""
    try:
        return load_lang_config(lang_name)
    except LangResolutionError as exc:
        logger.warning("Skipping broken language plugin metadata for %s: %s", lang_name, exc)
        return None


EXTRA_ROOT_MARKERS = (
    "package.json",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "go.mod",
    "Cargo.toml",
)


def _lang_config_markers() -> tuple[str, ...]:
    """Collect current root marker files from language plugins + fallbacks."""
    markers = set(EXTRA_ROOT_MARKERS)

    for lang_name in lang_api.available_langs():
        cfg = load_lang_config_metadata(lang_name)
        if cfg is None:
            continue
        for marker in getattr(cfg, "detect_markers", []) or []:
            if not isinstance(marker, str):
                continue
            cleaned = marker.strip()
            if cleaned:
                markers.add(cleaned)
    return tuple(sorted(markers))


def resolve_detection_root(
    args: object,
    *,
    project_root: Path | None = None,
    marker_provider: Callable[[], tuple[str, ...]] | None = None,
) -> Path:
    """Best root to auto-detect language from."""
    marker_provider = marker_provider or _lang_config_markers
    markers = marker_provider()
    project_root_path = (
        project_root if project_root is not None else get_project_root()
    ).resolve()

    raw_path = getattr(args, "path", None)
    if not raw_path:
        return project_root_path

    candidate = Path(raw_path)
    if not candidate.is_absolute():
        candidate = project_root_path / candidate
    candidate = candidate.resolve()
    candidate_root = candidate if candidate.is_dir() else candidate.parent

    probe_roots = (candidate_root, *candidate_root.parents)
    if candidate_root.is_relative_to(project_root_path):
        project_root_index = probe_roots.index(project_root_path)
        probe_roots = probe_roots[: project_root_index + 1]

    for probe_root in probe_roots:
        if any((probe_root / marker).exists() for marker in markers):
            return probe_root
    return candidate_root


def auto_detect_lang_name(args: object) -> str | None:
    """Auto-detect language using the most relevant root for this command."""
    root = resolve_detection_root(args)
    detected = lang_api.auto_detect_lang(root)
    if detected is None and root != get_project_root():
        detected = lang_api.auto_detect_lang(get_project_root())
    return detected


def resolve_lang(args: object) -> LangConfig | None:
    """Resolve language config from args, with auto-detection fallback."""
    lang_name = getattr(args, "lang", None)
    if lang_name is None:
        lang_name = auto_detect_lang_name(args)
    if lang_name is None:
        return None
    return load_lang_config(lang_name)


def resolve_lang_settings(config: dict, lang: LangConfig) -> dict[str, object]:
    """Resolve persisted per-language settings from config.languages.<lang>."""
    if not isinstance(config, dict):
        return lang.normalize_settings({})
    languages = config.get("languages", {})
    if not isinstance(languages, dict):
        return lang.normalize_settings({})
    raw = languages.get(lang.name, {})
    return lang.normalize_settings(raw if isinstance(raw, dict) else {})
