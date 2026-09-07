"""Luau language plugin — selene.

Luau is Roblox's typed dialect of Lua. It is registered separately from ``lua``
rather than as an extra extension on it because the two need different
tree-sitter grammars: the Lua grammar produces ERROR nodes for type
annotations, generics and ``export type`` declarations, which would silently
degrade every AST-backed detector on an ordinarily-typed Luau codebase.
"""

from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule
from desloppify.languages._framework.generic_support.core import generic_lang
from desloppify.languages._framework.treesitter import LUAU_SPEC

# Roblox and Lune projects keep sources under src/ and vendor dependencies into
# package directories a scan should read as vendor code. Storybook stories and
# .spec files are test scaffolding rather than shipped behaviour.
LUAU_ZONE_RULES = [
    ZoneRule(
        Zone.TEST,
        ["/tests/", "/test/", ".spec.luau", ".test.luau", ".story.luau"],
    ),
    ZoneRule(
        Zone.CONFIG,
        ["/.luaurc", "/wally.toml", "/rokit.toml", "/aftman.toml", ".project.json"],
    ),
    ZoneRule(Zone.GENERATED, ["/sourcemap.json", "/_Index/"]),
    ZoneRule(Zone.VENDOR, ["/Packages/", "/ServerPackages/", "/DevPackages/"]),
] + COMMON_ZONE_RULES

# A Roblox place has no single entry script. Rojo mounts whole directory trees,
# and the runtime starts every Script (.server.luau) and LocalScript
# (.client.luau) on its own, so nothing requires them — they are roots, not
# orphans. Stories and specs are likewise loaded by a harness that discovers
# them by name rather than by require.
#
# Controllers/ and Services/ are the Roblox equivalent of Godot autoloads: the
# framework layer (Knit, and the same convention in its lookalikes) requires
# every direct child of those folders at boot, so a zero-importer module there
# is normal wiring rather than dead code.
LUAU_ENTRY_PATTERNS = [
    ".client.luau",
    ".server.luau",
    ".story.luau",
    ".spec.luau",
    "/init.luau",
    "/tests/",
    "/Controllers/",
    "/Services/",
]

generic_lang(
    name="luau",
    extensions=[".luau"],
    tools=[
        {
            "label": "selene",
            "cmd": "selene --display-style quiet .",
            "fmt": "gnu",
            "id": "selene_warning",
            "tier": 2,
            "fix_cmd": None,
        },
    ],
    depth="minimal",
    treesitter_spec=LUAU_SPEC,
    detect_markers=[
        "*.project.json",
        "wally.toml",
        "rokit.toml",
        "aftman.toml",
        ".luaurc",
    ],
    default_src="src",
    entry_patterns=LUAU_ENTRY_PATTERNS,
    external_test_dirs=["tests", "test"],
    test_file_extensions=[".luau"],
    zone_rules=LUAU_ZONE_RULES,
)

__all__ = [
    "generic_lang",
    "LUAU_SPEC",
    "LUAU_ENTRY_PATTERNS",
    "LUAU_ZONE_RULES",
]
