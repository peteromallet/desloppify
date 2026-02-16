"""Language registry: auto-detection and lookup."""

from __future__ import annotations

import inspect
from pathlib import Path

from .base import DetectorPhase, FixerConfig, LangConfig

_registry: dict[str, type] = {}
_load_attempted = False
_load_errors: dict[str, BaseException] = {}

REQUIRED_FILES = [
    "commands.py",
    "extractors.py",
    "phases.py",
    "move.py",
    "review.py",
    "test_coverage.py",
]
REQUIRED_DIRS = ["detectors", "fixers", "tests"]


def _validate_lang_structure(lang_dir: Path, name: str):
    """Validate that a language plugin has all required files and directories."""
    errors = []
    for filename in REQUIRED_FILES:
        target = lang_dir / filename
        if not target.is_file():
            errors.append(f"missing required file: {filename}")
    for dirname in REQUIRED_DIRS:
        target = lang_dir / dirname
        if not target.is_dir():
            errors.append(f"missing required directory: {dirname}/")
            continue
        if not (target / "__init__.py").is_file():
            errors.append(f"missing {dirname}/__init__.py")
        if dirname == "tests" and not any(target.glob("test_*.py")):
            errors.append("tests directory must contain at least one test_*.py file")
    if errors:
        raise ValueError(
            f"Language plugin '{name}' ({lang_dir.name}/) has structural issues:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


def _validate_lang_contract(name: str, cfg: LangConfig) -> None:
    """Validate LangConfig runtime contract so broken plugins fail fast."""
    errors: list[str] = []

    if not isinstance(cfg, LangConfig):
        errors.append(f"plugin class for '{name}' must return LangConfig")
    else:
        if cfg.name != name:
            errors.append(f"config name mismatch: expected '{name}', got '{cfg.name}'")
        if not cfg.extensions:
            errors.append("extensions must be non-empty")
        if not callable(cfg.build_dep_graph):
            errors.append("build_dep_graph must be callable")
        if not callable(cfg.file_finder):
            errors.append("file_finder must be callable")
        if not callable(cfg.extract_functions):
            errors.append("extract_functions must be callable")
        if not cfg.phases:
            errors.append("phases must be non-empty")
        else:
            for idx, phase in enumerate(cfg.phases):
                if not isinstance(phase, DetectorPhase):
                    errors.append(f"phase[{idx}] is not DetectorPhase")
                    continue
                if not isinstance(phase.label, str) or not phase.label.strip():
                    errors.append(f"phase[{idx}] has empty label")
                if not callable(phase.run):
                    errors.append(f"phase[{idx}] run must be callable")
        if not isinstance(cfg.detect_commands, dict) or not cfg.detect_commands:
            errors.append("detect_commands must be a non-empty dict")
        else:
            for key, fn in cfg.detect_commands.items():
                if not isinstance(key, str) or not key.strip():
                    errors.append("detect_commands has empty/non-string key")
                elif (
                    key != key.lower()
                    or "-" in key
                    or not all(ch.isalnum() or ch == "_" for ch in key)
                ):
                    errors.append(
                        f"detect command '{key}' must use lowercase snake_case"
                    )
                if not callable(fn):
                    errors.append(f"detect command '{key}' is not callable")
        if not isinstance(cfg.fixers, dict):
            errors.append("fixers must be a dict")
        else:
            for key, fixer in cfg.fixers.items():
                if not isinstance(fixer, FixerConfig):
                    errors.append(f"fixer '{key}' is not FixerConfig")
        if not cfg.zone_rules:
            errors.append("zone_rules must be non-empty")

    if errors:
        raise ValueError(
            f"Language plugin '{name}' has invalid LangConfig contract:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


def _make_lang_config(name: str, cfg_cls: type) -> LangConfig:
    """Instantiate and validate a language config."""
    try:
        cfg = cfg_cls()
    except Exception as ex:  # pragma: no cover - defensive guard
        raise ValueError(f"Failed to instantiate language config '{name}': {ex}") from ex
    _validate_lang_contract(name, cfg)
    return cfg


def register_lang(name: str):
    """Decorator to register a language config module."""

    def decorator(cls):
        module = inspect.getmodule(cls)
        if module and hasattr(module, "__file__"):
            _validate_lang_structure(Path(module.__file__).parent, name)
        _registry[name] = cls
        return cls

    return decorator


def get_lang(name: str) -> LangConfig:
    """Get a language config by name."""
    if name not in _registry:
        _load_all()
    if name not in _registry:
        available = ", ".join(sorted(_registry.keys()))
        raise ValueError(f"Unknown language: {name!r}. Available: {available}")
    return _make_lang_config(name, _registry[name])


def auto_detect_lang(project_root: Path) -> str | None:
    """Auto-detect language from project files.

    When multiple config files are present (e.g. package.json + pyproject.toml),
    counts actual source files to pick the dominant language instead of relying
    on first-match ordering.
    """
    _load_all()
    candidates: list[str] = []
    configs: dict[str, LangConfig] = {}
    for lang_name, cfg_cls in _registry.items():
        cfg = _make_lang_config(lang_name, cfg_cls)
        configs[lang_name] = cfg
        markers = getattr(cfg, "detect_markers", []) or []
        if markers and any((project_root / marker).exists() for marker in markers):
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

    # Multiple candidates — count source files to pick the dominant one.
    # Uses file_finder from each lang config to respect DEFAULT_EXCLUSIONS.
    best, best_count = None, -1
    for lang_name in candidates:
        count = len(configs[lang_name].file_finder(project_root))
        if count > best_count:
            best, best_count = lang_name, count
    return best


def available_langs() -> list[str]:
    """Return list of registered language names."""
    _load_all()
    return sorted(_registry.keys())


def _raise_load_errors() -> None:
    if not _load_errors:
        return
    lines = ["Language plugin import failures:"]
    for module_name, ex in sorted(_load_errors.items()):
        lines.append(f"  - {module_name}: {type(ex).__name__}: {ex}")
    raise ImportError("\n".join(lines))


def _load_all():
    """Import all language modules to trigger registration."""
    global _load_attempted, _load_errors
    if _load_attempted:
        _raise_load_errors()
        return

    import importlib

    lang_dir = Path(__file__).parent
    failures: dict[str, BaseException] = {}

    # Discover .py modules (e.g. lang/rust.py)
    for f in sorted(lang_dir.glob("*.py")):
        if f.name in ("__init__.py", "base.py"):
            continue
        module_name = f".{f.stem}"
        try:
            importlib.import_module(module_name, __package__)
        except BaseException as ex:  # pragma: no cover - defensive guard
            failures[module_name] = ex

    # Discover packages (e.g. lang/typescript/)
    for d in sorted(lang_dir.iterdir()):
        if d.is_dir() and (d / "__init__.py").exists() and not d.name.startswith("_"):
            module_name = f".{d.name}"
            try:
                importlib.import_module(module_name, __package__)
            except BaseException as ex:  # pragma: no cover - defensive guard
                failures[module_name] = ex

    _load_attempted = True
    _load_errors = failures
    _raise_load_errors()
