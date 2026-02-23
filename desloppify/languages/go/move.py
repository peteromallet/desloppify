"""Go move helpers for file relocation scaffolding.

Originally contributed by tinker495 (KyuSeok Jung) in PR #128.
"""

from __future__ import annotations


def find_replacements(
    source_abs: str, dest_abs: str, graph: dict
) -> dict[str, list[tuple[str, str]]]:
    """Go import rewrites are not implemented yet."""
    del source_abs, dest_abs, graph
    return {}


def find_self_replacements(
    source_abs: str, dest_abs: str, graph: dict
) -> list[tuple[str, str]]:
    """No self-import rewrites for Go at this time."""
    del source_abs, dest_abs, graph
    return []
