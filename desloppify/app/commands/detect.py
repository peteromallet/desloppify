"""detect command: run a single detector directly (bypass state tracking)."""

from __future__ import annotations

import argparse
import sys

from desloppify import languages as lang_api
from desloppify.app.commands.helpers.lang import resolve_lang, resolve_lang_settings
from desloppify.app.commands.helpers.runtime import command_runtime
from desloppify.app.commands.helpers.runtime_options import resolve_lang_runtime_options
from desloppify.languages import runtime as lang_runtime
from desloppify.utils import colorize


def _resolve_detector_key(
    detector: str, detect_commands: dict[str, object]
) -> str | None:
    """Resolve detector input to a command key."""
    detector = detector.strip()
    if detector in detect_commands:
        return detector

    normalized = detector.lower().replace("-", "_")
    if normalized in detect_commands:
        return normalized

    denormalized = detector.lower().replace("_", "-")
    if denormalized in detect_commands:
        return denormalized

    return None


def cmd_detect(args: argparse.Namespace) -> None:
    """Run a single detector directly (bypass state tracking)."""
    detector_input = args.detector

    # Resolve language (from --lang flag or auto-detection)
    lang_cfg = resolve_lang(args)

    if not lang_cfg:
        langs = ", ".join(lang_api.available_langs()) or "registered language plugins"
        print(
            colorize(
                f"No language specified. Use --lang <name> (available: {langs}).", "red"
            )
        )
        sys.exit(1)

    # Validate detector name
    detector = _resolve_detector_key(detector_input, lang_cfg.detect_commands)
    if detector is None:
        print(
            colorize(f"Unknown detector for {lang_cfg.name}: {detector_input}", "red")
        )
        print(f"  Available: {', '.join(sorted(lang_cfg.detect_commands))}")
        sys.exit(1)

    # Set default thresholds for detectors that expect them
    if getattr(args, "threshold", None) is None:
        if detector == "large":
            args.threshold = lang_cfg.large_threshold
        elif detector == "dupes":
            args.threshold = 0.8

    runtime = command_runtime(args)
    lang_settings = resolve_lang_settings(runtime.config, lang_cfg)
    lang_options = resolve_lang_runtime_options(args, lang_cfg)
    lang = lang_runtime.make_lang_run(
        lang_cfg,
        overrides=lang_runtime.LangRunOverrides(
            runtime_settings=lang_settings,
            runtime_options=lang_options,
        ),
    )
    args.lang_runtime_options = dict(lang_options)
    try:
        lang.detect_commands[detector](args)
    finally:
        args.lang_runtime_options = None
    if not getattr(args, "json", False):
        scan_path = getattr(args, "path", ".") or "."
        print(
            colorize(f"\n  Next command: `desloppify scan --path {scan_path}`", "dim")
        )
