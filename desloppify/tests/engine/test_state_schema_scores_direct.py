from __future__ import annotations

from pathlib import Path

from desloppify.engine._state.schema_scores import json_default
from desloppify.languages._framework.frameworks.types import (
    EcosystemFrameworkDetection,
)


def test_json_default_serializes_dataclass_payloads() -> None:
    detection = EcosystemFrameworkDetection(
        ecosystem="node",
        package_root=Path("/tmp/example"),
        package_json_relpath="package.json",
        present={"nextjs": {"dep_hits": ["next"]}},
    )

    serialized = json_default(detection)

    assert isinstance(serialized, dict)
    assert serialized["ecosystem"] == "node"
    assert serialized["package_root"] == Path("/tmp/example")
    assert serialized["present"]["nextjs"]["dep_hits"] == ["next"]
