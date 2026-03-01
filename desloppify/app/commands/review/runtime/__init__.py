"""Runtime helpers for review command orchestration."""

import importlib

from desloppify.app.commands.review.runtime.setup import (
    setup_lang,
    setup_lang_concrete,
)

_LAZY_EXPORTS = {
    "runner_helpers": "desloppify.app.commands.review.runner_helpers",
    "policy": ".policy",
}

__all__ = ["setup_lang", "setup_lang_concrete", *_LAZY_EXPORTS]


def __getattr__(name: str):
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    if target.startswith("."):
        value = importlib.import_module(target, __name__)
    else:
        value = importlib.import_module(target)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
