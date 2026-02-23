"""Go dependency graph builder (stub).

Originally contributed by tinker495 (KyuSeok Jung) in PR #128.
Go import resolution is not yet implemented — returns an empty graph.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def build_dep_graph(
    path: Path,
    roslyn_cmd: str | None = None,
) -> dict[str, dict[str, Any]]:
    """Build Go dependency graph — stub returning empty dict."""
    del path, roslyn_cmd
    return {}
