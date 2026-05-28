"""Svelte framework spec (Node ecosystem).

Covers both Svelte 4 and SvelteKit. The detection config matches the
package name (``svelte``) and SvelteKit's metadata (``@sveltejs/kit``)
so projects using either show as present.
"""

from __future__ import annotations

from ..types import DetectionConfig, FrameworkSpec

SVELTE_SPEC = FrameworkSpec(
    id="svelte",
    label="Svelte",
    ecosystem="node",
    detection=DetectionConfig(
        dependencies=("svelte", "@sveltejs/kit"),
        config_files=(
            "svelte.config.js",
            "svelte.config.mjs",
            "svelte.config.ts",
        ),
        script_pattern=r"(?:^|\s)svelte-kit(?:\s|$)",
    ),
    source_extensions=(".svelte",),
)


__all__ = ["SVELTE_SPEC"]
