"""Canonical terminal output API surface."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from desloppify.core import output as output_mod

LOC_COMPACT_THRESHOLD = output_mod.LOC_COMPACT_THRESHOLD
COLORS = output_mod.COLORS
NO_COLOR = output_mod.NO_COLOR


def colorize(text: str, color: str) -> str:
    return output_mod.colorize(text, color)


def log(msg: str) -> None:
    output_mod.log(msg)


def print_table(
    headers: list[str],
    rows: list[list[str]],
    widths: list[int] | None = None,
) -> None:
    output_mod.print_table(headers, rows, widths)


def display_entries(
    args: object,
    entries: Sequence[Any],
    *,
    label: str,
    empty_msg: str,
    columns: Sequence[str],
    widths: list[int] | None,
    row_fn: Callable[[Any], list[str]],
    json_payload: dict | None = None,
    overflow: bool = True,
) -> bool:
    return output_mod.display_entries(
        args,
        entries,
        label=label,
        empty_msg=empty_msg,
        columns=columns,
        widths=widths,
        row_fn=row_fn,
        json_payload=json_payload,
        overflow=overflow,
    )


__all__ = [
    "LOC_COMPACT_THRESHOLD",
    "COLORS",
    "NO_COLOR",
    "colorize",
    "display_entries",
    "log",
    "print_table",
]
