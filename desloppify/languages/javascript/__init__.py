"""JavaScript/JSX language plugin — ESLint."""

from __future__ import annotations

from desloppify.languages._framework.generic_support.core import generic_lang
from desloppify.languages._framework.treesitter import JS_SPEC
from desloppify.languages.javascript._zones import JS_ZONE_RULES


cfg = generic_lang(
    name="javascript",
    extensions=[".js", ".jsx", ".mjs", ".cjs"],
    tools=[
        {
            "label": "ESLint",
            "cmd": "npx eslint . --format json --no-error-on-unmatched-pattern 2>/dev/null",
            "fmt": "eslint",
            "id": "eslint_warning",
            "tier": 2,
            "fix_cmd": "npx eslint . --fix --no-error-on-unmatched-pattern 2>/dev/null",
        },
    ],
    exclude=["node_modules", "dist", "build", ".next", "coverage"],
    depth="shallow",
    detect_markers=["package.json"],
    default_src="src",
    treesitter_spec=JS_SPEC,
    zone_rules=JS_ZONE_RULES,
    frameworks=True,
)

__all__ = [
    "generic_lang",
    "JS_SPEC",
    "JS_ZONE_RULES",
]
