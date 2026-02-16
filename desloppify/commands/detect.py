"""detect command: run a single detector directly (bypass state tracking)."""

from __future__ import annotations

import argparse
import sys

from ..utils import colorize


def cmd_detect(args: argparse.Namespace) -> None:
    """Run a single detector directly (bypass state tracking)."""
    detector = args.detector

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
    if detector not in lang.detect_commands:
        print(colorize(f"Unknown detector for {lang.name}: {detector}", "red"))
        print(f"  Available: {', '.join(sorted(lang.detect_commands))}")
        sys.exit(1)

    # Set default thresholds for detectors that expect them
    if getattr(args, "threshold", None) is None:
        if detector == "large":
            args.threshold = lang.large_threshold
        elif detector == "dupes":
            args.threshold = 0.8

    lang.detect_commands[detector](args)
