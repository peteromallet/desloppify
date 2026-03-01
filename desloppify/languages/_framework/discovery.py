"""Language plugin discovery and import error surfacing."""

from __future__ import annotations

import importlib
import importlib.util
import logging
from pathlib import Path

from . import registry_state

logger = logging.getLogger(__name__)

# Broader than PARSE_INIT_ERRORS: plugin imports may also raise SyntaxError/TypeError.
_PLUGIN_IMPORT_ERRORS: tuple[type[Exception], ...] = (
    ImportError, SyntaxError, ValueError, TypeError, RuntimeError, OSError,
)


def raise_load_errors() -> None:
    errors = registry_state.get_load_errors()
    if not errors:
        return
    summaries: list[str] = []
    for module_name, ex in sorted(errors.items()):
        ex_type = type(ex).__name__
        logger.warning(
            "Language plugin %s failed to load: %s: %s",
            module_name,
            ex_type,
            ex,
        )
        summaries.append(f"{module_name}: {ex_type}: {ex}")
    raise ImportError("; ".join(summaries))


def _report_load_errors_for_load_all() -> None:
    """Emit warning diagnostics for plugin failures without aborting discovery."""
    try:
        raise_load_errors()
    except ImportError:
        # load_all historically logs plugin failures and continues so command
        # startup can proceed with the languages that did load successfully.
        return


def load_all() -> None:
    """Import all language modules to trigger registration."""
    if registry_state.was_load_attempted():
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

    # Discover user plugins from <active-project-root>/.desloppify/plugins/*.py
    try:
        from desloppify.core._internal.text_utils import get_project_root

        user_plugin_dir = get_project_root() / ".desloppify" / "plugins"
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

    # Retry plugins that failed due to a circular import — after the first pass
    # all framework modules (e.g. generic.py) are fully initialised, so a
    # second attempt usually succeeds.
    circular_names = [
        name for name, ex in failures.items()
        if isinstance(ex, ImportError) and (
            "partially initialized" in str(ex) or "circular import" in str(ex)
        )
    ]
    for module_name in circular_names:
        try:
            importlib.import_module(module_name, base_package)
            del failures[module_name]
        except _PLUGIN_IMPORT_ERRORS:
            pass

    registry_state.set_load_attempted(True)
    registry_state.set_load_errors(failures)
    _report_load_errors_for_load_all()
