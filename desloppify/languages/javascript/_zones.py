"""Zone/path classification rules for JavaScript."""

from __future__ import annotations

from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule

JS_ZONE_RULES = [
    ZoneRule(
        Zone.TEST,
        ["/__tests__/", ".test.", ".spec.", ".stories.", "/__mocks__/", "setupTests."],
    ),
    ZoneRule(
        Zone.CONFIG,
        [
            "vite.config",
            "tailwind.config",
            "postcss.config",
            "eslint",
            "prettier",
            "jest.config",
            "vitest.config",
            "next.config",
            "webpack.config",
            "babel.config",
        ],
    ),
] + COMMON_ZONE_RULES

__all__ = ["JS_ZONE_RULES"]
