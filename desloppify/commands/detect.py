"""detect command: run a single detector directly (bypass state tracking)."""

from __future__ import annotations

import argparse
import sys

from ..utils import colorize


DETECTOR_ALIASES: dict[str, str] = {
    "single-use": "single_use",
    "singleuse": "single_use",
    "passthrough": "props",
}


def _resolve_detector_key(detector: str, detect_commands: dict[str, object]) -> str | None:
    """Resolve detector aliases to a command key.

    Canonical command keys should use underscores (e.g. ``single_use``), but
    we also accept compatibility aliases (e.g. ``single-use`` and legacy
    ``passthrough`` when only ``props`` exists).
    """
    detector = detector.strip()
    if detector in detect_commands:
        return detector

    normalized = detector.lower().replace("-", "_")
    if normalized in detect_commands:
        return normalized

    alias_target = DETECTOR_ALIASES.get(detector) or DETECTOR_ALIASES.get(normalized)
    if alias_target and alias_target in detect_commands:
        return alias_target

    denormalized = detector.lower().replace("_", "-")
    if denormalized in detect_commands:
        return denormalized

    return None


def cmd_detect(args: argparse.Namespace) -> None:
    """Run a single detector directly (bypass state tracking)."""
    detector_input = args.detector

    # Resolve language (from --lang flag or auto-detection)
    from ._helpers import resolve_lang
    from ..lang import available_langs
    lang = resolve_lang(args)

    if not lang:
        langs = ", ".join(available_langs())
        hint = f" Use --lang <one of: {langs}>." if langs else " Use --lang <language>."
        print(colorize(f"No language specified.{hint}", "red"))
        sys.exit(1)

    # Validate detector name
    detector = _resolve_detector_key(detector_input, lang.detect_commands)
    if detector is None:
        print(colorize(f"Unknown detector for {lang.name}: {detector_input}", "red"))
        print(f"  Available: {', '.join(sorted(lang.detect_commands))}")
        sys.exit(1)

    # Set default thresholds for detectors that expect them
    if getattr(args, "threshold", None) is None:
        if detector == "large":
            args.threshold = lang.large_threshold
        elif detector == "dupes":
            args.threshold = 0.8

    lang.detect_commands[detector](args)
