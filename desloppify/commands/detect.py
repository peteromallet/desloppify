"""detect command: run a single detector directly (bypass state tracking)."""

import sys

from ..utils import colorize


def cmd_detect(args):
    """Run a single detector directly (bypass state tracking)."""
    detector = args.detector

    # Resolve language (from --lang flag, default to typescript)
    from ._helpers import _resolve_lang
    lang = _resolve_lang(args)

    if not lang:
        from ..lang import available_langs
        langs = ", ".join(available_langs()) or "python, typescript, csharp"
        print(colorize(f"No language specified. Use --lang <name> (available: {langs}).", "red"))
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
