"""TypeScript fixer loader utilities."""

from __future__ import annotations

from importlib import import_module

_FIXER_MODULES = {
    "fix_debug_logs": ".logs",
    "fix_unused_imports": ".imports",
    "fix_dead_exports": ".exports",
    "fix_unused_vars": ".vars",
    "fix_unused_params": ".params",
    "fix_dead_useeffect": ".useeffect",
    "fix_empty_if_chain": ".if_chain",
}


def get_fixer(name: str):
    """Resolve a fixer function by name without eager module imports."""
    module_name = _FIXER_MODULES.get(name)
    if module_name is None:
        raise KeyError(name)
    module = import_module(module_name, package=__name__)
    return getattr(module, name)


__all__ = ["get_fixer"]
