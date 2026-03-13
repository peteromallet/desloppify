"""Framework signature catalog for TypeScript projects.

This is intentionally data-driven so framework selection isn't hard-coded into
individual feature phases.
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import FrameworkId


@dataclass(frozen=True)
class FrameworkSignature:
    id: FrameworkId
    label: str
    dependencies: tuple[str, ...] = ()
    dev_dependencies: tuple[str, ...] = ()
    config_files: tuple[str, ...] = ()
    marker_files: tuple[str, ...] = ()
    marker_dirs: tuple[str, ...] = ()

    weight_dependency: int = 3
    weight_config: int = 2
    weight_marker: int = 2
    weight_script: int = 1

    primary_score_threshold: int = 5


TS_FRAMEWORK_SIGNATURES: tuple[FrameworkSignature, ...] = (
    FrameworkSignature(
        id="nextjs",
        label="Next.js",
        dependencies=("next",),
        config_files=("next.config.js", "next.config.mjs", "next.config.cjs", "next.config.ts"),
        marker_files=("next-env.d.ts",),
        marker_dirs=("app", "src/app", "pages", "src/pages"),
        primary_score_threshold=5,
    ),
    FrameworkSignature(
        id="vite",
        label="Vite",
        dependencies=("vite",),
        dev_dependencies=("@vitejs/plugin-react", "@vitejs/plugin-react-swc", "@vitejs/plugin-vue"),
        config_files=("vite.config.ts", "vite.config.js", "vite.config.mjs", "vite.config.cjs"),
        marker_files=("vite-env.d.ts", "src/vite-env.d.ts"),
        marker_dirs=("src",),
        primary_score_threshold=5,
    ),
)


__all__ = ["FrameworkSignature", "TS_FRAMEWORK_SIGNATURES"]

