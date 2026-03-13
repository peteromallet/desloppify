"""Next.js framework smells for JavaScript/JSX projects.

This phase intentionally reuses the shared (data-driven) framework detector and
Next.js smell scanners used by the TypeScript plugin so JS-only repos get the
same depth.
"""

from __future__ import annotations

from pathlib import Path

from desloppify.base.output.terminal import log
from desloppify.languages._framework.base.types import LangRuntimeContract
from desloppify.languages.typescript.frameworks import detect_primary_ts_framework
from desloppify.languages.typescript.frameworks.nextjs import nextjs_info_from_detection
from desloppify.languages.typescript.frameworks.nextjs.phase import (
    detect_nextjs_framework_smells,
)
from desloppify.state_io import Issue


def phase_nextjs(
    path: Path,
    lang: LangRuntimeContract,
) -> tuple[list[Issue], dict[str, int]]:
    framework = detect_primary_ts_framework(path, lang)
    nextjs_info = nextjs_info_from_detection(framework)
    if not nextjs_info.is_primary:
        return [], {}

    scan_root = nextjs_info.package_root
    return detect_nextjs_framework_smells(scan_root, nextjs_info, log)


__all__ = ["phase_nextjs"]

