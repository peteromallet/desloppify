"""Framework spec contracts (detection + scanners + tool integrations)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desloppify.languages._framework.base.types import LangRuntimeContract
from desloppify.state_io import Issue

FrameworkEvidence = dict[str, Any]


@dataclass(frozen=True)
class DetectionConfig:
    """Deterministic framework presence detection hints for an ecosystem."""

    dependencies: tuple[str, ...] = ()
    dev_dependencies: tuple[str, ...] = ()
    config_files: tuple[str, ...] = ()
    marker_files: tuple[str, ...] = ()
    marker_dirs: tuple[str, ...] = ()
    script_pattern: str | None = None

    # Markers are valuable for routing context, but default to "context only"
    # so frameworks don't light up purely from directory shape.
    marker_dirs_imply_presence: bool = False


@dataclass(frozen=True)
class ScannerRule:
    """A single scanner rule within a FrameworkSpec."""

    id: str
    requires: tuple[str, ...] = ()
    scan: Callable[[Path, LangRuntimeContract], tuple[list[dict[str, Any]], int]] | None = None
    issue_factory: Callable[[dict[str, Any]], Issue] | None = None
    log_message: Callable[[int], str] | None = None


@dataclass(frozen=True)
class ToolIntegration:
    """Framework tool integration (ToolSpec-like + phase semantics)."""

    id: str  # detector id (e.g. "next_lint")
    label: str
    cmd: str
    fmt: str
    tier: int
    slow: bool = False
    confidence: str = "medium"


@dataclass(frozen=True)
class FrameworkSpec:
    """A framework "horizontal layer" spec, analogous to tree-sitter specs."""

    id: str
    label: str
    ecosystem: str
    detection: DetectionConfig

    excludes: tuple[str, ...] = ()
    scanners: tuple[ScannerRule, ...] = ()
    tools: tuple[ToolIntegration, ...] = ()


@dataclass(frozen=True)
class EcosystemFrameworkDetection:
    """Framework presence detection result for a scan path within an ecosystem."""

    ecosystem: str
    package_root: Path
    package_json_relpath: str | None
    present: dict[str, FrameworkEvidence]


__all__ = [
    "DetectionConfig",
    "EcosystemFrameworkDetection",
    "FrameworkEvidence",
    "FrameworkSpec",
    "ScannerRule",
    "ToolIntegration",
]

