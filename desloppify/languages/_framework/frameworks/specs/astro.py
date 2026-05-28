"""Astro framework spec (Node ecosystem)."""

from __future__ import annotations

from ..types import DetectionConfig, FrameworkSpec

ASTRO_SPEC = FrameworkSpec(
    id="astro",
    label="Astro",
    ecosystem="node",
    detection=DetectionConfig(
        dependencies=("astro",),
        config_files=(
            "astro.config.mjs",
            "astro.config.js",
            "astro.config.ts",
            "astro.config.cjs",
        ),
        script_pattern=r"(?:^|\s)astro(?:\s|$)",
    ),
    source_extensions=(".astro",),
)


__all__ = ["ASTRO_SPEC"]
