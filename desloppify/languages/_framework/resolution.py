"""Config instantiation and public language resolution helpers."""

from __future__ import annotations

from pathlib import Path

from . import registry_state
from .base.types import LangConfig
from .contract_validation import validate_lang_contract
from .discovery import load_all

_MARKER_GLOB_CHARS = ("*", "?", "[")


def make_lang_config(name: str, cfg_cls: type) -> LangConfig:
    """Instantiate and validate a language config."""
    try:
        cfg = cfg_cls()
    except (TypeError, ValueError, AttributeError, RuntimeError, OSError) as ex:
        raise ValueError(
            f"Failed to instantiate language config '{name}': {ex}"
        ) from ex
    validate_lang_contract(name, cfg)
    return cfg


def get_lang(name: str, *, refresh_registry: bool = False) -> LangConfig:
    """Get a language config by name.

    All plugins (full and generic) store LangConfig instances in the registry.
    Test doubles that store plain classes are instantiated on demand as a fallback.
    """
    if refresh_registry:
        load_all(force_reload=True)
    elif not registry_state.is_registered(name):
        load_all()
    if not registry_state.is_registered(name):
        available = ", ".join(sorted(registry_state.all_keys()))
        raise ValueError(f"Unknown language: {name!r}. Available: {available}")
    obj = registry_state.get(name)
    if isinstance(obj, LangConfig):
        return obj
    return make_lang_config(name, obj)  # fallback for test doubles


def auto_detect_lang(
    project_root: Path,
    *,
    refresh_registry: bool = False,
) -> str | None:
    """Auto-detect language from project files.

    When multiple config files are present (e.g. package.json + pyproject.toml),
    counts actual source files to pick the dominant language instead of relying
    on first-match ordering.
    """
    load_all(force_reload=refresh_registry)
    candidates: list[str] = []
    configs: dict[str, LangConfig] = {}

    for lang_name, obj in registry_state.all_items():
        cfg = obj if isinstance(obj, LangConfig) else make_lang_config(lang_name, obj)
        configs[lang_name] = cfg
        markers = getattr(cfg, "detect_markers", []) or []
        if markers and any(_detect_marker_exists(project_root, marker) for marker in markers):
            candidates.append(lang_name)

    if not candidates:
        # Marker-less fallback: pick language with most source files.
        best, best_count = None, 0
        for lang_name, cfg in configs.items():
            count = len(cfg.file_finder(project_root))
            if count > best_count:
                best, best_count = lang_name, count
        return best if best_count > 0 else None

    if len(candidates) == 1:
        return candidates[0]

    # Multiple candidates: choose language with most source files.
    best, best_count = None, -1
    for lang_name in candidates:
        count = len(configs[lang_name].file_finder(project_root))
        if count > best_count:
            best, best_count = lang_name, count
    return best


def _detect_marker_exists(project_root: Path, marker: str) -> bool:
    marker_text = str(marker).strip()
    if not marker_text:
        return False

    # Fast path for literal markers.
    if (project_root / marker_text).exists():
        return True

    # Wildcard markers (for example "*.fsproj") are matched at project root.
    if any(ch in marker_text for ch in _MARKER_GLOB_CHARS):
        return any(project_root.glob(marker_text))
    return False


def available_langs(*, refresh_registry: bool = False) -> list[str]:
    """Return list of registered language names."""
    load_all(force_reload=refresh_registry)
    return sorted(registry_state.all_keys())
