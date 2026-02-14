"""Language registry: auto-detection and lookup."""

import inspect
from pathlib import Path
from .base import LangConfig

_registry: dict[str, type] = {}

REQUIRED_FILES = ["commands.py", "extractors.py"]
REQUIRED_DIRS = ["detectors", "fixers"]


def _validate_lang_structure(lang_dir: Path, name: str):
    """Validate that a language plugin has all required files and directories."""
    errors = []
    for f in REQUIRED_FILES:
        if not (lang_dir / f).exists():
            errors.append(f"missing required file: {f}")
    for d in REQUIRED_DIRS:
        if not (lang_dir / d).exists():
            errors.append(f"missing required directory: {d}/")
        elif not (lang_dir / d / "__init__.py").exists():
            errors.append(f"missing {d}/__init__.py")
    if errors:
        raise ValueError(
            f"Language plugin '{name}' ({lang_dir.name}/) has structural issues:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )


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
        # Lazy-load language modules to populate registry
        _load_all()
    if name not in _registry:
        available = ", ".join(sorted(_registry.keys()))
        raise ValueError(f"Unknown language: {name!r}. Available: {available}")
    return _registry[name]()


def auto_detect_lang(project_root: Path) -> str | None:
    """Auto-detect language from project files.

    When multiple config files are present (e.g. package.json + pyproject.toml),
    counts actual source files to pick the dominant language instead of relying
    on first-match ordering.
    """
    _load_all()
    candidates = []
    if (project_root / "package.json").exists():
        candidates.append("typescript")
    if ((project_root / "pyproject.toml").exists()
            or (project_root / "setup.py").exists()
            or (project_root / "setup.cfg").exists()):
        candidates.append("python")
    if ((project_root / "global.json").exists()
            or any(project_root.glob("*.sln"))
            or any(project_root.glob("*.csproj"))
            or any(project_root.rglob("*.sln"))
            or any(project_root.rglob("*.csproj"))):
        candidates.append("csharp")
    if (project_root / "go.mod").exists():
        candidates.append("go")
    if (project_root / "Cargo.toml").exists():
        candidates.append("rust")

    # Filter to registered languages only
    candidates = [c for c in candidates if c in _registry]
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    # Multiple candidates — count source files to pick the dominant one.
    # Uses file_finder from each lang config to respect DEFAULT_EXCLUSIONS.
    best, best_count = None, -1
    for lang_name in candidates:
        lang_cfg = _registry[lang_name]()
        if lang_cfg.file_finder:
            count = len(lang_cfg.file_finder(project_root))
        else:
            count = 0
        if count > best_count:
            best, best_count = lang_name, count
    return best


def available_langs() -> list[str]:
    """Return list of registered language names."""
    _load_all()
    return sorted(_registry.keys())


def _load_all():
    """Import all language modules to trigger registration."""
    import importlib
    lang_dir = Path(__file__).parent
    # Discover .py modules (e.g. lang/rust.py)
    for f in sorted(lang_dir.glob("*.py")):
        if f.name in ("__init__.py", "base.py"):
            continue
        module_name = f.stem
        try:
            importlib.import_module(f".{module_name}", __package__)
        except ImportError:
            pass
    # Discover packages (e.g. lang/typescript/)
    for d in sorted(lang_dir.iterdir()):
        if d.is_dir() and (d / "__init__.py").exists() and not d.name.startswith("_"):
            try:
                importlib.import_module(f".{d.name}", __package__)
            except ImportError:
                pass
