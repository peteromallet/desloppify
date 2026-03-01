"""Move helpers for language plugin scaffolding."""

from __future__ import annotations

from desloppify.languages._framework.commands_base import (
    scaffold_find_replacements,
)
from desloppify.languages._framework.commands_base import (
    scaffold_find_self_replacements,
)
from desloppify.languages._framework.commands_base import (
    scaffold_verify_hint,
)


def find_replacements(*args, **kwargs):
    return scaffold_find_replacements(*args, **kwargs)


def find_self_replacements(*args, **kwargs):
    return scaffold_find_self_replacements(*args, **kwargs)


def get_verify_hint(*args, **kwargs):
    return scaffold_verify_hint(*args, **kwargs)


__all__ = ["find_replacements", "find_self_replacements", "get_verify_hint"]
