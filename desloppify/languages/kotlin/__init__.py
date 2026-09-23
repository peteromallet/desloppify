"""Kotlin language plugin — ktlint."""

from desloppify.languages._framework.generic_support.core import generic_lang
from desloppify.languages._framework.treesitter import KOTLIN_SPEC
from desloppify.languages.kotlin.fixers import KTLINT_COMMAND, make_ktlint_fixer

_config = generic_lang(
    name="kotlin",
    extensions=[".kt", ".kts"],
    tools=[
        {
            "label": "ktlint",
            "cmd": KTLINT_COMMAND,
            "fmt": "ktlint",
            "id": "ktlint_violation",
            "tier": 2,
            "fix_cmd": "ktlint --format --log-level=none",
        },
    ],
    exclude=["build"],
    depth="shallow",
    detect_markers=["build.gradle.kts", "build.gradle"],
    treesitter_spec=KOTLIN_SPEC,
)

_config.fixers["ktlint-violation"] = make_ktlint_fixer(_config.file_finder)
_config.detect_commands["ktlint_violation"] = _config.fixers["ktlint-violation"].detect

__all__ = [
    "generic_lang",
    "KOTLIN_SPEC",
]
