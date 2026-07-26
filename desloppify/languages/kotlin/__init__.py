"""Kotlin language plugin — ktlint."""

from desloppify.languages._framework.generic_support.core import generic_lang
from desloppify.languages._framework.treesitter import KOTLIN_SPEC
from desloppify.languages.kotlin._zones import KOTLIN_ZONE_RULES

generic_lang(
    name="kotlin",
    extensions=[".kt", ".kts"],
    tools=[
        {
            "label": "ktlint",
            "cmd": "ktlint --reporter=json",
            "fmt": "json",
            "id": "ktlint_violation",
            "tier": 2,
            "fix_cmd": "ktlint --format",
        },
    ],
    exclude=["build"],
    depth="shallow",
    detect_markers=["build.gradle.kts", "build.gradle"],
    treesitter_spec=KOTLIN_SPEC,
    zone_rules=KOTLIN_ZONE_RULES,
)

__all__ = [
    "generic_lang",
    "KOTLIN_SPEC",
    "KOTLIN_ZONE_RULES",
]
