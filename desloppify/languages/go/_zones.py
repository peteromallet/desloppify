"""Zone/path classification rules for Go."""

from __future__ import annotations

from desloppify.engine.policy.zones import COMMON_ZONE_RULES, Zone, ZoneRule

GO_ZONE_RULES = [
    ZoneRule(Zone.GENERATED, [".generated.", "_gen.go", ".pb.go", "_string.go", "_enumer.go"]),
    ZoneRule(Zone.TEST, ["_test.go"]),
    ZoneRule(
        Zone.CONFIG,
        ["go.mod", "go.sum"],
    ),
] + COMMON_ZONE_RULES

__all__ = ["GO_ZONE_RULES"]
