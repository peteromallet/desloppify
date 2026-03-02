"""Move helpers for GDScript language plugin (scaffold defaults)."""

from __future__ import annotations

from desloppify.languages._framework.commands_base import (
    scaffold_find_replacements as find_replacements,
    scaffold_find_self_replacements as find_self_replacements,
    scaffold_verify_hint as get_verify_hint,
)

__all__ = ["find_replacements", "find_self_replacements", "get_verify_hint"]
