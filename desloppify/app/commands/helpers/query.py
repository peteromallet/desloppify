"""Query output helpers for command modules."""

from __future__ import annotations

from desloppify.core.query import write_query as _core_write_query
from desloppify.core._internal.text_utils import PROJECT_ROOT

QUERY_FILE = PROJECT_ROOT / ".desloppify" / "query.json"


def write_query(data: dict) -> None:
    """Write structured query output to .desloppify/query.json."""
    _core_write_query(data, query_file=QUERY_FILE)


__all__ = ["QUERY_FILE", "write_query"]
