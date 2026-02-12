"""detect command: run a single detector directly (bypass state tracking)."""

import sys

from ..utils import c


def cmd_detect(args):
    """Run a single detector directly (bypass state tracking)."""
    detector = args.detector

    # Resolve language (from --lang flag, default to typescript)
    from ..cli import _resolve_lang
    lang = _resolve_lang(args)

    if not lang:
        # Default to TypeScript when no --lang flag is passed
        from ..lang import get_lang
        lang = get_lang("typescript")

    # Validate detector name
    if detector not in lang.detect_commands:
        print(c(f"Unknown detector for {lang.name}: {detector}", "red"))
        print(f"  Available: {', '.join(sorted(lang.detect_commands))}")
        sys.exit(1)

    # Set default thresholds for detectors that expect them
    if getattr(args, "threshold", None) is None:
        if detector == "large":
            args.threshold = lang.large_threshold
        elif detector == "dupes":
            args.threshold = 0.8

    lang.detect_commands[detector](args)
