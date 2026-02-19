"""Move helpers for language plugin scaffolding."""

from __future__ import annotations

from desloppify.languages._shared.scaffold_defaults import (
    scaffold_find_replacements,
    scaffold_find_self_replacements,
    scaffold_verify_hint,
)


def find_replacements(
    source_abs: str, dest_abs: str, graph: dict
) -> dict[str, list[tuple[str, str]]]:
    return scaffold_find_replacements(source_abs, dest_abs, graph)


def find_self_replacements(
    source_abs: str, dest_abs: str, graph: dict
) -> list[tuple[str, str]]:
    return scaffold_find_self_replacements(source_abs, dest_abs, graph)


def get_verify_hint() -> str:
    return scaffold_verify_hint()
