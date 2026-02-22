"""Language plugin discovery and import error surfacing."""

from __future__ import annotations

import importlib
import importlib.util
import logging
from pathlib import Path

from desloppify.languages._framework import registry_state

logger = logging.getLogger(__name__)

# Broader than PARSE_INIT_ERRORS: plugin imports may also raise SyntaxError/TypeError.
_PLUGIN_IMPORT_ERRORS: tuple[type[Exception], ...] = (
    ImportError, SyntaxError, ValueError, TypeError, RuntimeError, OSError,
)


def raise_load_errors() -> None:
    errors = registry_state.get_load_errors()
    if not errors:
        return
    lines = ["Language plugin import failures:"]
    for module_name, ex in sorted(errors.items()):
        lines.append(f"  - {module_name}: {type(ex).__name__}: {ex}")
    raise ImportError("\n".join(lines))


def load_all() -> None:
    """Import all language modules to trigger registration."""
    if registry_state.was_load_attempted():
        raise_load_errors()
        return

    lang_dir = Path(__file__).resolve().parent
    if lang_dir.name == "_framework":
        lang_dir = lang_dir.parent
    base_package = __package__.rsplit(".", 1)[0]
    failures: dict[str, BaseException] = {}

    # Discover single-file plugins by naming convention (e.g. plugin_rust.py).
    for f in sorted(lang_dir.glob("plugin_*.py")):
        module_name = f".{f.stem}"
        try:
            importlib.import_module(module_name, base_package)
        except _PLUGIN_IMPORT_ERRORS as ex:
            logger.debug("Language plugin import failed for %s: %s", module_name, ex)
            failures[module_name] = ex

    # Discover packages (e.g. lang/typescript/)
    for d in sorted(lang_dir.iterdir()):
        if (
            d.is_dir()
            and (d / "__init__.py").exists()
            and not d.name.startswith("_")
        ):
            module_name = f".{d.name}"
            try:
                importlib.import_module(module_name, base_package)
            except _PLUGIN_IMPORT_ERRORS as ex:
                logger.debug(
                    "Language package import failed for %s: %s", module_name, ex
                )
                failures[module_name] = ex

    # Discover user plugins from PROJECT_ROOT/.desloppify/plugins/*.py
    try:
        from desloppify.core._internal.text_utils import PROJECT_ROOT

        user_plugin_dir = PROJECT_ROOT / ".desloppify" / "plugins"
        if user_plugin_dir.is_dir():
            for f in sorted(user_plugin_dir.glob("*.py")):
                spec = importlib.util.spec_from_file_location(
                    f"desloppify_user_plugin_{f.stem}", f
                )
                if spec and spec.loader:
                    try:
                        mod = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(mod)
                    except _PLUGIN_IMPORT_ERRORS as ex:
                        logger.debug(
                            "User plugin import failed for %s: %s", f.name, ex
                        )
                        failures[f"user:{f.name}"] = ex
    except (OSError, ImportError) as exc:
        logger.debug("User plugin discovery skipped: %s", exc)

    registry_state.set_load_attempted(True)
    registry_state.set_load_errors(failures)
    raise_load_errors()
