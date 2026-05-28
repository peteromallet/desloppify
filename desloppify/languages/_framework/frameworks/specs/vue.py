"""Vue framework spec (Node ecosystem).

Covers Vue 3 (and Vue 2 leftovers) as well as Nuxt, which builds on
Vue's single-file component model and shares the ``.vue`` extension.
"""

from __future__ import annotations

from ..types import DetectionConfig, FrameworkSpec

VUE_SPEC = FrameworkSpec(
    id="vue",
    label="Vue",
    ecosystem="node",
    detection=DetectionConfig(
        dependencies=("vue", "nuxt"),
        config_files=(
            "vue.config.js",
            "vue.config.mjs",
            "vue.config.ts",
            "nuxt.config.js",
            "nuxt.config.mjs",
            "nuxt.config.ts",
        ),
        script_pattern=r"(?:^|\s)(?:vue-cli-service|nuxt)(?:\s|$)",
    ),
    source_extensions=(".vue",),
)


__all__ = ["VUE_SPEC"]
