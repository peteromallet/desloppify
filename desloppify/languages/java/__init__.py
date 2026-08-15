"""Java language plugin — pmd."""

from __future__ import annotations

import os
import re

from desloppify.languages._framework.generic_support.core import generic_lang
from desloppify.languages._framework.treesitter import JAVA_SPEC

_PMD_THREADS_ENV = "DESLOPPIFY_PMD_THREADS"
_PMD_THREADS_RE = re.compile(r"(?:0|[1-9][0-9]*|(?:0|[1-9][0-9]*)(?:\.[0-9]+)?C)")


def _pmd_threads_arg(raw: str | None = None) -> str:
    """Return a conservative PMD thread count argument."""
    value = (raw if raw is not None else os.environ.get(_PMD_THREADS_ENV, "0")).strip()
    if not _PMD_THREADS_RE.fullmatch(value):
        value = "0"
    return f"--threads {value}"


PMD_COMMAND = (
    "pmd check -d . -R rulesets/java/quickstart.xml "
    f"{_pmd_threads_arg()} -f text 2>&1"
)

generic_lang(
    name="java",
    extensions=[".java"],
    tools=[
        {
            "label": "pmd",
            "cmd": PMD_COMMAND,
            "fmt": "gnu",
            "id": "pmd_violation",
            "tier": 2,
            "fix_cmd": None,
        },
    ],
    exclude=["build", "target", ".gradle"],
    depth="minimal",
    detect_markers=["pom.xml", "build.gradle"],
    treesitter_spec=JAVA_SPEC,
)

__all__ = [
    "PMD_COMMAND",
    "generic_lang",
    "JAVA_SPEC",
]
