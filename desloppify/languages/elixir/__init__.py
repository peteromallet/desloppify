"""Elixir language plugin — mix credo with Elixir-aware zone rules."""

from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.languages._framework.generic import generic_lang, GenericLangOptions
from desloppify.languages._framework.treesitter import ELIXIR_SPEC

ELIXIR_ZONE_RULES = [
    ZoneRule(Zone.TEST, ["_test.exs", "/test/"]),
    ZoneRule(Zone.CONFIG, ["/config/"]),
    ZoneRule(Zone.GENERATED, ["/priv/static/"]),
    ZoneRule(Zone.VENDOR, ["/deps/"]),
] + COMMON_ZONE_RULES

generic_lang(
    name="elixir",
    extensions=[".ex", ".exs"],
    tools=[
        {
            "label": "mix credo",
            "cmd": "mix credo --format=json",
            "fmt": "credo",
            "id": "credo_issue",
            "tier": 2,
            "fix_cmd": None,
        },
    ],
    options=GenericLangOptions(
        exclude=["_build", "deps", "priv/static", "rel"],
        depth="shallow",
        detect_markers=["mix.exs"],
        treesitter_spec=ELIXIR_SPEC,
        zone_rules=ELIXIR_ZONE_RULES,
    ),
)

__all__ = [
    "ELIXIR_ZONE_RULES",
]
